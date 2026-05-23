"""Per-shop configuration + fee-group aggregation.

Shop-level fields:
  - view_department_id: FK to departments (drives 部门视角)
  - fee_group_name:     free-text label (no FK), groups shops with the
                        same fee config in the 店铺管理 list
  - per_capita_share, ship_service_tax_rate: numbers feeding 公司利润率

Two views over the same data:

  GET  /api/shops              — every shop, one row each (used by the
                                  部门管理 picker and the dashboard's
                                  shop dropdown).
  GET  /api/shops/fee-groups   — aggregated by fee_group_name, one row
                                  per distinct group (used by 店铺管理).

Group operations (店铺管理 CRUD):
  POST   /api/shops/fee-groups        — create-or-update a group; rename
                                        + reconcile member set in one call.
  DELETE /api/shops/fee-groups/{name} — clear fee config on every shop
                                        currently in this group (shops
                                        stay, since they come from imports).
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    Department, ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN, Shop, User,
)
from ..schemas import (
    ApiResponse, ShopFeeGroupOut, ShopFeeGroupSave, ShopFeeGroupShop,
    ShopOut, ShopUpdate,
)
from ..security import require_backend_access

router = APIRouter(prefix="/api/shops", tags=["shops"])


def _scope_for(actor: User, explicit_tenant_id: int | None) -> int:
    if actor.role == ROLE_PLATFORM_ADMIN:
        if explicit_tenant_id is None:
            raise HTTPException(status_code=400, detail="平台管理员需指定 tenant_id")
        return explicit_tenant_id
    return actor.tenant_id


def _can_manage(actor: User) -> bool:
    return actor.role in (ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN)


def _shop_to_out(shop: Shop, view_depts: dict[int, str]) -> ShopOut:
    return ShopOut(
        id=shop.id,
        tenant_id=shop.tenant_id,
        shop_code=shop.shop_code,
        shop_name=shop.shop_name,
        view_department_id=shop.view_department_id,
        view_department_name=view_depts.get(shop.view_department_id) if shop.view_department_id else None,
        fee_group_name=shop.fee_group_name,
        per_capita_share=float(shop.per_capita_share or 0),
        ship_service_tax_rate=float(shop.ship_service_tax_rate or 0),
        created_at=shop.created_at,
        updated_at=shop.updated_at,
    )


@router.get("", response_model=ApiResponse[list[ShopOut]])
async def list_shops(
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    """Per-shop list. Used by the 部门管理 picker and dashboard."""
    scope = _scope_for(actor, tenant_id)
    shops = (await db.execute(
        select(Shop).where(Shop.tenant_id == scope).order_by(Shop.shop_code.asc())
    )).scalars().all()
    dept_rows = (await db.execute(
        select(Department.id, Department.name).where(Department.tenant_id == scope)
    )).all()
    dept_map = {d_id: d_name for d_id, d_name in dept_rows}
    return ApiResponse(data=[_shop_to_out(s, dept_map) for s in shops])


@router.get("/fee-groups", response_model=ApiResponse[list[ShopFeeGroupOut]])
async def list_fee_groups(
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated view: one row per distinct fee_group_name. Shops without
    a fee_group_name don't show up (they haven't been configured yet)."""
    scope = _scope_for(actor, tenant_id)
    shops = (await db.execute(
        select(Shop)
        .where(
            Shop.tenant_id == scope,
            Shop.fee_group_name.isnot(None),
            Shop.fee_group_name != "",
        )
        .order_by(Shop.fee_group_name.asc(), Shop.shop_code.asc())
    )).scalars().all()

    groups: dict[str, ShopFeeGroupOut] = {}
    for s in shops:
        name = s.fee_group_name
        item = groups.get(name)
        if item is None:
            item = ShopFeeGroupOut(
                name=name,
                per_capita_share=float(s.per_capita_share or 0),
                ship_service_tax_rate=float(s.ship_service_tax_rate or 0),
                shops=[],
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            groups[name] = item
        item.shops.append(ShopFeeGroupShop(shop_code=s.shop_code, shop_name=s.shop_name))
        # Group-level created_at = earliest member; updated_at = latest.
        # (Shops in a well-formed group all share the same numeric values;
        # we surface the first one we saw.)
        if s.created_at < item.created_at:
            item.created_at = s.created_at
        if s.updated_at > item.updated_at:
            item.updated_at = s.updated_at
    return ApiResponse(data=list(groups.values()))


@router.post("/fee-groups", response_model=ApiResponse[dict])
async def save_fee_group(
    body: ShopFeeGroupSave,
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a fee group.

    Edit semantics: if `original_name` is given, any shop currently in
    that group but missing from `shop_codes` has its fee config cleared
    (the shop drops out of the group). All shops in `shop_codes` get the
    new (name, values) bundle. Renaming is supported by passing
    original_name != name.
    """
    if not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可修改店铺费用")
    scope = _scope_for(actor, tenant_id)

    new_name = (body.name or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="请填写费用所属部门名称")
    orig_name = (body.original_name or "").strip() or None

    # Block creating two groups with the same name. (Renaming to an
    # existing name is also blocked unless we're absorbing into that
    # group, which is more confusing than helpful.)
    if orig_name != new_name:
        clash = await db.scalar(
            select(Shop.id).where(
                Shop.tenant_id == scope,
                Shop.fee_group_name == new_name,
            ).limit(1)
        )
        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"已存在名为「{new_name}」的费用配置，请改用其他名称",
            )

    share = Decimal(str(body.per_capita_share)).quantize(Decimal("0.0001"))
    tax = Decimal(str(body.ship_service_tax_rate)).quantize(Decimal("0.0001"))
    new_codes = set(body.shop_codes or [])

    removed = 0
    if orig_name:
        # Find shops currently in the original group; drop ones not in
        # the new selection.
        current = (await db.execute(
            select(Shop.shop_code)
            .where(Shop.tenant_id == scope, Shop.fee_group_name == orig_name)
        )).all()
        to_remove = [c for (c,) in current if c not in new_codes]
        if to_remove:
            res = await db.execute(
                sa_update(Shop)
                .where(Shop.tenant_id == scope, Shop.shop_code.in_(to_remove))
                .values(
                    fee_group_name=None,
                    per_capita_share=Decimal("0"),
                    ship_service_tax_rate=Decimal("0"),
                )
            )
            removed = res.rowcount or 0

    applied = 0
    if new_codes:
        res = await db.execute(
            sa_update(Shop)
            .where(Shop.tenant_id == scope, Shop.shop_code.in_(list(new_codes)))
            .values(
                fee_group_name=new_name,
                per_capita_share=share,
                ship_service_tax_rate=tax,
            )
        )
        applied = res.rowcount or 0

    await db.commit()
    return ApiResponse(data={"applied": applied, "removed": removed, "name": new_name})


@router.delete("/fee-groups/{name}", response_model=ApiResponse[dict])
async def delete_fee_group(
    name: str,
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    """Clear every shop's fee config for this group. The shops themselves
    stay (they come from imports), only the (name, share, tax) bundle is
    wiped — so they re-appear as "未配置" until added back to a group."""
    if not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可删除费用配置")
    scope = _scope_for(actor, tenant_id)
    res = await db.execute(
        sa_update(Shop)
        .where(Shop.tenant_id == scope, Shop.fee_group_name == name)
        .values(
            fee_group_name=None,
            per_capita_share=Decimal("0"),
            ship_service_tax_rate=Decimal("0"),
        )
    )
    await db.commit()
    return ApiResponse(data={"cleared": res.rowcount or 0})


@router.patch("/{shop_code}", response_model=ApiResponse[ShopOut])
async def update_shop(
    shop_code: str,
    body: ShopUpdate,
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    """Edit a single shop's fields. Used by 部门管理 to move shops between
    view-departments, and as the underlying "clear fee config" call.
    """
    if not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可修改店铺配置")
    scope = _scope_for(actor, tenant_id)
    shop = (await db.execute(
        select(Shop).where(Shop.tenant_id == scope, Shop.shop_code == shop_code)
    )).scalar_one_or_none()
    if not shop:
        raise HTTPException(status_code=404, detail="店铺不存在")

    sent = body.model_fields_set

    if "view_department_id" in sent:
        if body.view_department_id is not None:
            await _ensure_dept_in_tenant(db, scope, body.view_department_id)
        shop.view_department_id = body.view_department_id

    if "fee_group_name" in sent:
        shop.fee_group_name = (body.fee_group_name or "").strip() or None

    if "per_capita_share" in sent and body.per_capita_share is not None:
        shop.per_capita_share = Decimal(str(body.per_capita_share)).quantize(Decimal("0.0001"))

    if "ship_service_tax_rate" in sent and body.ship_service_tax_rate is not None:
        shop.ship_service_tax_rate = Decimal(str(body.ship_service_tax_rate)).quantize(Decimal("0.0001"))

    await db.commit()
    await db.refresh(shop)
    dept_rows = (await db.execute(
        select(Department.id, Department.name).where(Department.tenant_id == scope)
    )).all()
    dept_map = {d_id: d_name for d_id, d_name in dept_rows}
    return ApiResponse(data=_shop_to_out(shop, dept_map))


async def _ensure_dept_in_tenant(db: AsyncSession, tenant_id: int, dept_id: int) -> None:
    dept = (await db.execute(
        select(Department).where(Department.id == dept_id, Department.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=400, detail="所选部门不属于该企业")
