"""Per-shop configuration.

Per-shop, the admin sets:
  - view_department_id: FK to departments (decides 部门视角 visibility)
  - fee_group_name:     FREE-TEXT label, just for grouping shops with the
                        same fee config in the UI — NOT linked to the
                        departments table in any way
  - per_capita_share:   numeric, feeds 公司利润率 formula
  - ship_service_tax_rate: numeric (fraction), feeds 公司利润率 formula

Permission model:
    list (GET)        - any backend-access user
    update (PATCH)    - super_admin / platform_admin only
    fee batch (POST)  - super_admin / platform_admin only

Shops are NOT user-creatable here: they appear automatically when their
shop_code first lands in a sales_records import.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    Department, ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN, Shop, User,
)
from ..schemas import ApiResponse, ShopFeeBatchUpdate, ShopOut, ShopUpdate
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
    scope = _scope_for(actor, tenant_id)
    shops = (await db.execute(
        select(Shop).where(Shop.tenant_id == scope).order_by(Shop.shop_code.asc())
    )).scalars().all()
    dept_rows = (await db.execute(
        select(Department.id, Department.name).where(Department.tenant_id == scope)
    )).all()
    dept_map = {d_id: d_name for d_id, d_name in dept_rows}
    return ApiResponse(data=[_shop_to_out(s, dept_map) for s in shops])


@router.patch("/{shop_code}", response_model=ApiResponse[ShopOut])
async def update_shop(
    shop_code: str,
    body: ShopUpdate,
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
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
        # Free-text — no validation beyond schema's length cap.
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


@router.post("/fee-batch", response_model=ApiResponse[dict])
async def apply_fee_batch(
    body: ShopFeeBatchUpdate,
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    """Apply one fee config (group label + values) to many shops at once.

    A shop_code that appears here gets its fee config replaced. Shops not
    listed are untouched.
    """
    if not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可批量修改店铺费用")
    scope = _scope_for(actor, tenant_id)

    if not body.shop_codes:
        return ApiResponse(data={"updated": 0})

    label = (body.fee_group_name or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="请填写费用所属部门名称")

    share = Decimal(str(body.per_capita_share)).quantize(Decimal("0.0001"))
    tax = Decimal(str(body.ship_service_tax_rate)).quantize(Decimal("0.0001"))
    res = await db.execute(
        sa_update(Shop)
        .where(Shop.tenant_id == scope, Shop.shop_code.in_(body.shop_codes))
        .values(
            fee_group_name=label,
            per_capita_share=share,
            ship_service_tax_rate=tax,
        )
    )
    await db.commit()
    return ApiResponse(data={"updated": res.rowcount or 0})


async def _ensure_dept_in_tenant(db: AsyncSession, tenant_id: int, dept_id: int) -> None:
    dept = (await db.execute(
        select(Department).where(Department.id == dept_id, Department.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=400, detail="所选部门不属于该企业")
