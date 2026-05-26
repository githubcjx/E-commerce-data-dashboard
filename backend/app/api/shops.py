"""Per-shop configuration + fee-group aggregation + per-month fixed cost.

Shop-level fields:
  - view_department_id:    FK to departments (drives 部门视角)
  - fee_group_name:        free-text label (no FK), groups shops with the
                           same fee config in the 店铺管理 list AND keys
                           into fee_group_monthly_cost
  - ship_service_tax_rate: per-shop %-based fee feeding 公司利润率

The 固定费用 (formerly shops.per_capita_share, a flat per-shop amount)
is now stored as **monthly totals per fee group** in
fee_group_monthly_cost — see the dashboard service for the per-month
apportionment formula.

Routes:
  GET    /api/shops                                       — every shop, one row each
  GET    /api/shops/fee-groups                            — aggregated by fee_group_name
  POST   /api/shops/fee-groups                            — create-or-update group (name + tax + members)
  DELETE /api/shops/fee-groups/{name}                     — clear fee config + drop monthly rows
  GET    /api/shops/fee-groups/{name}/monthly-costs       — list every month from earliest data → 当月
  PUT    /api/shops/fee-groups/{name}/monthly-costs       — batch upsert the dialog's edits
"""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete as sa_delete, func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    Department, FeeGroupMonthlyCost, ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN,
    SalesRecord, Shop, User,
)
from ..schemas import (
    ApiResponse, MonthlyCostList, MonthlyCostRow, MonthlyCostSave,
    ShopFeeGroupOut, ShopFeeGroupSave, ShopFeeGroupShop, ShopOut, ShopUpdate,
)
from ..security import require_backend_access

router = APIRouter(prefix="/api/shops", tags=["shops"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        ship_service_tax_rate=float(shop.ship_service_tax_rate or 0),
        created_at=shop.created_at,
        updated_at=shop.updated_at,
    )


def _current_year_month() -> str:
    """Server-local current month. The dashboard logic also clamps to
    server-local "today" so the day-count math stays consistent."""
    t = date.today()
    return f"{t.year:04d}-{t.month:02d}"


def _year_month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _enumerate_months(earliest_ym: str, latest_ym: str) -> list[str]:
    """Inclusive list of "YYYY-MM" strings from earliest → latest, ordered
    ascending. Used by the dialog to guarantee one row per month.
    """
    ey, em = int(earliest_ym[:4]), int(earliest_ym[5:7])
    ly, lm = int(latest_ym[:4]), int(latest_ym[5:7])
    if (ey, em) > (ly, lm):
        return []
    out: list[str] = []
    y, m = ey, em
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


async def _earliest_data_month(db: AsyncSession, tenant_id: int) -> str | None:
    """MIN(date) → "YYYY-MM" for this tenant's sales_records, or None if
    nothing's been imported yet. The dialog uses this as the bottom row."""
    earliest: date | None = await db.scalar(
        select(func.min(SalesRecord.date))
        .where(SalesRecord.tenant_id == tenant_id)
    )
    return _year_month(earliest) if earliest else None


# ---------------------------------------------------------------------------
# /api/shops  + /api/shops/fee-groups (list / save / delete)
# ---------------------------------------------------------------------------

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
    """Aggregated view: one row per distinct fee_group_name, plus the
    current calendar month's 固定费用 (None when not yet set)."""
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

    cur_ym = _current_year_month()
    # Single lookup for every group's current-month amount.
    cur_rows = (await db.execute(
        select(FeeGroupMonthlyCost.fee_group_name, FeeGroupMonthlyCost.amount)
        .where(
            FeeGroupMonthlyCost.tenant_id == scope,
            FeeGroupMonthlyCost.year_month == cur_ym,
        )
    )).all()
    cur_map: dict[str, float] = {name: float(amt or 0) for name, amt in cur_rows}

    groups: dict[str, ShopFeeGroupOut] = {}
    for s in shops:
        name = s.fee_group_name
        item = groups.get(name)
        if item is None:
            item = ShopFeeGroupOut(
                name=name,
                ship_service_tax_rate=float(s.ship_service_tax_rate or 0),
                current_month=cur_ym,
                current_month_cost=cur_map.get(name),  # None if no row yet
                shops=[],
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            groups[name] = item
        item.shops.append(ShopFeeGroupShop(shop_code=s.shop_code, shop_name=s.shop_name))
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
    """Create or update a fee group (name + tax_rate + member shops).

    Renames cascade to fee_group_monthly_cost so monthly history follows.
    Shops removed from the group have their fee_group_name + tax_rate
    cleared (the shops themselves stay — they came from imports).
    """
    if not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可修改店铺费用")
    scope = _scope_for(actor, tenant_id)

    new_name = (body.name or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="请填写费用所属部门名称")
    orig_name = (body.original_name or "").strip() or None

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

    tax = Decimal(str(body.ship_service_tax_rate)).quantize(Decimal("0.0001"))
    new_codes = set(body.shop_codes or [])

    removed = 0
    if orig_name:
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
                    ship_service_tax_rate=Decimal("0"),
                )
            )
            removed = res.rowcount or 0

        # Rename cascade: move monthly_cost history to the new name.
        # Block the rename if monthly rows already exist under the target
        # name (collision); we'd be merging two histories silently.
        if orig_name != new_name:
            existing_target = await db.scalar(
                select(func.count())
                .select_from(FeeGroupMonthlyCost)
                .where(
                    FeeGroupMonthlyCost.tenant_id == scope,
                    FeeGroupMonthlyCost.fee_group_name == new_name,
                )
            )
            if existing_target:
                raise HTTPException(
                    status_code=409,
                    detail=f"已存在名为「{new_name}」的按月费用记录，无法重命名合并",
                )
            await db.execute(
                sa_update(FeeGroupMonthlyCost)
                .where(
                    FeeGroupMonthlyCost.tenant_id == scope,
                    FeeGroupMonthlyCost.fee_group_name == orig_name,
                )
                .values(fee_group_name=new_name)
            )

    applied = 0
    if new_codes:
        res = await db.execute(
            sa_update(Shop)
            .where(Shop.tenant_id == scope, Shop.shop_code.in_(list(new_codes)))
            .values(
                fee_group_name=new_name,
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
    """Drop the fee group entirely: clear shop tagging AND wipe the group's
    monthly_cost history. Member shops remain (they're imported)."""
    if not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可删除费用配置")
    scope = _scope_for(actor, tenant_id)
    res = await db.execute(
        sa_update(Shop)
        .where(Shop.tenant_id == scope, Shop.fee_group_name == name)
        .values(
            fee_group_name=None,
            ship_service_tax_rate=Decimal("0"),
        )
    )
    await db.execute(
        sa_delete(FeeGroupMonthlyCost)
        .where(
            FeeGroupMonthlyCost.tenant_id == scope,
            FeeGroupMonthlyCost.fee_group_name == name,
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


# ---------------------------------------------------------------------------
# Per-month 固定费用 — list + batch save
# ---------------------------------------------------------------------------

async def _ensure_group_exists(db: AsyncSession, tenant_id: int, name: str) -> None:
    """Reject monthly-cost ops on a non-existent fee group. We key by name
    (free-text), so existence = "≥1 shop is tagged with this name"."""
    found = await db.scalar(
        select(Shop.id).where(
            Shop.tenant_id == tenant_id, Shop.fee_group_name == name,
        ).limit(1)
    )
    if not found:
        raise HTTPException(status_code=404, detail=f"费用配置「{name}」不存在")


@router.get("/fee-groups/{name}/monthly-costs", response_model=ApiResponse[MonthlyCostList])
async def list_monthly_costs(
    name: str,
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    """Return one row per month from the earliest imported data month
    through the current calendar month, ascending. Missing months are
    filled in with amount=0 so the dialog always shows a complete grid
    (the user CAN'T add or delete rows — they only edit amounts).

    Edge case: a tenant with no imported data yet → fall back to a
    single row for the current month.
    """
    scope = _scope_for(actor, tenant_id)
    await _ensure_group_exists(db, scope, name)

    cur_ym = _current_year_month()
    earliest = await _earliest_data_month(db, scope) or cur_ym
    months = _enumerate_months(earliest, cur_ym)

    stored = (await db.execute(
        select(FeeGroupMonthlyCost.year_month, FeeGroupMonthlyCost.amount)
        .where(
            FeeGroupMonthlyCost.tenant_id == scope,
            FeeGroupMonthlyCost.fee_group_name == name,
        )
    )).all()
    amount_by_ym: dict[str, float] = {ym: float(amt or 0) for ym, amt in stored}

    rows = [
        MonthlyCostRow(
            year_month=ym,
            amount=amount_by_ym.get(ym, 0.0),
            is_current_month=(ym == cur_ym),
        )
        for ym in months
    ]
    return ApiResponse(data=MonthlyCostList(fee_group_name=name, rows=rows))


@router.put("/fee-groups/{name}/monthly-costs", response_model=ApiResponse[dict])
async def save_monthly_costs(
    name: str,
    body: MonthlyCostSave,
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    """Batch upsert. The dialog sends every row the user touched (or
    the whole list — both work). Atomic: single transaction, one commit
    at the end, so a half-saved state is impossible.

    A row with amount=0 is stored explicitly (instead of being deleted)
    so it counts as "user said 0" rather than "未录入". The calc layer
    treats both identically, but the dialog round-trips them as-is.
    """
    if not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可编辑按月费用")
    scope = _scope_for(actor, tenant_id)
    await _ensure_group_exists(db, scope, name)

    # Pull existing rows for this group once; upsert in memory then write.
    existing = (await db.execute(
        select(FeeGroupMonthlyCost).where(
            FeeGroupMonthlyCost.tenant_id == scope,
            FeeGroupMonthlyCost.fee_group_name == name,
        )
    )).scalars().all()
    by_ym: dict[str, FeeGroupMonthlyCost] = {r.year_month: r for r in existing}

    saved = 0
    for item in body.items:
        ym = item.year_month
        amt = Decimal(str(item.amount)).quantize(Decimal("0.0001"))
        if ym in by_ym:
            row = by_ym[ym]
            if row.amount != amt:
                row.amount = amt
                saved += 1
        else:
            db.add(FeeGroupMonthlyCost(
                tenant_id=scope,
                fee_group_name=name,
                year_month=ym,
                amount=amt,
            ))
            saved += 1

    await db.commit()
    return ApiResponse(data={"saved": saved})
