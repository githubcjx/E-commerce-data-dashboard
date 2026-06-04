"""人员目标完成情况 — per-月、per-负责人 业绩目标与完成率计算.

Design (see PerformanceTarget model + CLAUDE.md):
  - Subject is the 负责人 (sales_records.owner), NOT the login account.
  - Only TARGETS are stored; 完成率 = 当月实际 ÷ 目标, computed here so the
    numbers stay live and tamper-proof.
  - 利润额/利润率 use 经营口径 (this owner's own rows: SUM(profit),
    SUM(profit)/SUM(sales)) — NOT the company 公司利润率 (its固定费用 is
    apportioned per-SHOP and doesn't decompose cleanly to a person).
  - 销售额 mirrors the dashboard definition: SUM(income_total), falling back
    to SUM(actual_income) when income_total is 0.
"""

from calendar import monthrange
from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PerformanceTarget, SalesRecord
from ..schemas import TargetSaveItem


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------

def month_bounds(year_month: str) -> tuple[date, date]:
    """'YYYY-MM' → (first_day, last_day) of that calendar month."""
    y, m = int(year_month[:4]), int(year_month[5:7])
    return date(y, m, 1), date(y, m, monthrange(y, m)[1])


def next_month(year_month: str) -> str:
    y, m = int(year_month[:4]), int(year_month[5:7])
    return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"


def last_workday_of_month(year: int, month: int) -> date:
    """Last Mon–Fri of the month.

    v1 only skips weekends — it does NOT know about Chinese public holidays /
    调休. Good enough as a "月末快到了" nudge; swap in a holiday calendar later
    if precision is needed.
    """
    d = date(year, month, monthrange(year, month)[1])
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

async def all_owners(
    session: AsyncSession, tenant_id: int, scope_owners: list[str] | None = None,
) -> list[str]:
    """Distinct 负责人 names for the tenant. `scope_owners`: None=all,
    []=none, [...]=limited (data isolation for 普通用户)."""
    if scope_owners is not None and not scope_owners:
        return []
    stmt = select(SalesRecord.owner).where(SalesRecord.tenant_id == tenant_id).distinct()
    if scope_owners is not None:
        stmt = stmt.where(SalesRecord.owner.in_(scope_owners))
    rows = (await session.execute(stmt)).all()
    return sorted(o for (o,) in rows if o)


async def owner_actuals(
    session: AsyncSession,
    tenant_id: int,
    year_month: str,
    today: date,
    scope_owners: list[str] | None = None,
) -> dict[str, dict[str, float]]:
    """Per-owner 经营口径 actuals for the month, counting only 已发生 days
    (date <= today). Returns {owner: {'sales': .., 'profit': ..}}."""
    if scope_owners is not None and not scope_owners:
        return {}
    m_start, m_end = month_bounds(year_month)
    end = min(m_end, today)
    if m_start > end:
        return {}
    stmt = (
        select(
            SalesRecord.owner,
            func.coalesce(func.sum(SalesRecord.income_total), 0).label("income_total"),
            func.coalesce(func.sum(SalesRecord.actual_income), 0).label("actual_income"),
            func.coalesce(func.sum(SalesRecord.profit), 0).label("profit"),
        )
        .where(and_(
            SalesRecord.tenant_id == tenant_id,
            SalesRecord.date >= m_start,
            SalesRecord.date <= end,
        ))
        .group_by(SalesRecord.owner)
    )
    if scope_owners is not None:
        stmt = stmt.where(SalesRecord.owner.in_(scope_owners))
    rows = (await session.execute(stmt)).all()
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        if not r.owner:
            continue
        sales = float(r.income_total or 0) or float(r.actual_income or 0)
        out[r.owner] = {"sales": sales, "profit": float(r.profit or 0)}
    return out


async def targets_map(
    session: AsyncSession, tenant_id: int, year_month: str,
) -> dict[str, PerformanceTarget]:
    rows = (await session.execute(
        select(PerformanceTarget).where(and_(
            PerformanceTarget.tenant_id == tenant_id,
            PerformanceTarget.year_month == year_month,
        ))
    )).scalars().all()
    return {t.owner: t for t in rows}


# ---------------------------------------------------------------------------
# Row assembly + completion
# ---------------------------------------------------------------------------

def _completion(actual: float, target: float) -> float | None:
    """完成率 = 实际 ÷ 目标 (decimal; 0.875 = 87.5%). None when no positive
    target — can't have a rate without a denominator."""
    return (actual / target) if target and target > 0 else None


def progress_row(
    owner: str, t: PerformanceTarget | None, act: dict[str, float] | None,
) -> dict:
    """One 负责人's target + actual + completion. Rates are decimals."""
    act = act or {}
    sales_t = float(t.target_sales) if t else 0.0
    profit_t = float(t.target_profit) if t else 0.0
    rate_t = float(t.target_profit_rate) if t else 0.0
    sales_a = float(act.get("sales", 0.0))
    profit_a = float(act.get("profit", 0.0))
    rate_a = (profit_a / sales_a) if sales_a else 0.0
    return {
        "owner": owner,
        "target_sales": sales_t,
        "target_profit": profit_t,
        "target_profit_rate": rate_t,
        "actual_sales": sales_a,
        "actual_profit": profit_a,
        "actual_profit_rate": rate_a,
        "sales_completion": _completion(sales_a, sales_t),
        "profit_completion": _completion(profit_a, profit_t),
        "has_target": t is not None,
    }


async def get_ranking(
    session: AsyncSession, tenant_id: int, year_month: str, today: date,
) -> dict:
    """Two leaderboards over 负责人 with a target: 销售额完成率 + 利润额完成率,
    each sorted desc. Owners without the relevant target are excluded from
    that board (no rate without a target)."""
    tmap = await targets_map(session, tenant_id, year_month)
    actuals = await owner_actuals(session, tenant_id, year_month, today)
    rows = [progress_row(o, t, actuals.get(o)) for o, t in tmap.items()]
    sales_rank = sorted(
        (r for r in rows if r["sales_completion"] is not None),
        key=lambda r: r["sales_completion"], reverse=True,
    )
    profit_rank = sorted(
        (r for r in rows if r["profit_completion"] is not None),
        key=lambda r: r["profit_completion"], reverse=True,
    )
    return {
        "year_month": year_month,
        "sales_ranking": list(sales_rank),
        "profit_ranking": list(profit_rank),
    }


async def get_reminder(session: AsyncSession, tenant_id: int, today: date) -> dict:
    """Should the admin be nudged to fill NEXT month's targets?

    Fires from the last workday of THIS month through month-end, and only
    while some 负责人 still lacks a target for next month (so it stops
    nagging once everything is filled)."""
    quiet = {"should_remind": False, "year_month": None,
             "missing_owners": [], "missing_count": 0}
    if today < last_workday_of_month(today.year, today.month):
        return quiet
    ym_next = next_month(f"{today.year}-{today.month:02d}")
    owners = await all_owners(session, tenant_id)
    if not owners:
        return quiet
    tmap = await targets_map(session, tenant_id, ym_next)
    missing = [o for o in owners if o not in tmap]
    return {
        "should_remind": bool(missing),
        "year_month": ym_next,
        "missing_owners": missing,
        "missing_count": len(missing),
    }


# ---------------------------------------------------------------------------
# Mutation
# ---------------------------------------------------------------------------

async def save_targets(
    session: AsyncSession, tenant_id: int, year_month: str,
    items: list[TargetSaveItem],
) -> int:
    """Upsert one month's targets per (tenant, owner). Atomic."""
    existing = await targets_map(session, tenant_id, year_month)
    for it in items:
        t = existing.get(it.owner)
        if t is None:
            session.add(PerformanceTarget(
                tenant_id=tenant_id, owner=it.owner, year_month=year_month,
                target_sales=it.target_sales, target_profit=it.target_profit,
                target_profit_rate=it.target_profit_rate,
            ))
        else:
            t.target_sales = it.target_sales
            t.target_profit = it.target_profit
            t.target_profit_rate = it.target_profit_rate
    await session.commit()
    return len(items)
