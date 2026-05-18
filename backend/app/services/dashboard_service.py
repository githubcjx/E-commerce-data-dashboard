"""Dashboard aggregation queries — all scoped by `tenant_id`.

Per-tenant isolation: every query filters `SalesRecord.tenant_id == tenant_id`,
so members of one company share their data pool but can never see another
company's rows. Role within the tenant (admin vs user) doesn't affect what data
is visible — only who can manage users.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SalesRecord


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    format: str
    higher_is_better: bool


METRIC_DEFS: list[MetricDef] = [
    MetricDef("sales", "销售额", "currency", True),
    MetricDef("refundRate", "退款率", "percent", False),
    MetricDef("grossMargin", "毛利率", "percent", True),
    MetricDef("profit", "利润额", "currency", True),
    MetricDef("profitRate", "利润率", "percent", True),
    MetricDef("shipPct", "快递费用占比", "percent", False),
    MetricDef("adPct", "营销费用占比", "percent", False),
]


def _period_range(end_date: date, granularity: str) -> tuple[date, date]:
    if granularity == "day":
        return end_date, end_date
    if granularity == "week":
        weekday = end_date.weekday()
        start = end_date - timedelta(days=weekday)
        end = start + timedelta(days=6)
        return start, end
    if granularity == "month":
        start = end_date.replace(day=1)
        if start.month == 12:
            next_m = start.replace(year=start.year + 1, month=1)
        else:
            next_m = start.replace(month=start.month + 1)
        end = next_m - timedelta(days=1)
        return start, end
    return end_date, end_date


def _previous_range(start: date, end: date, granularity: str) -> tuple[date, date]:
    if granularity == "day":
        return start - timedelta(days=1), end - timedelta(days=1)
    if granularity == "week":
        return start - timedelta(days=7), end - timedelta(days=7)
    if granularity == "month":
        prev_end = start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        return prev_start, prev_end
    return start, end


def _trend_dates(end_date: date, granularity: str) -> list[tuple[date, date, str]]:
    if granularity == "day":
        return [
            (
                end_date - timedelta(days=i),
                end_date - timedelta(days=i),
                (end_date - timedelta(days=i)).isoformat(),
            )
            for i in reversed(range(10))
        ]
    if granularity == "week":
        weekday = end_date.weekday()
        cur_start = end_date - timedelta(days=weekday)
        out = []
        for i in reversed(range(12)):
            s = cur_start - timedelta(days=7 * i)
            e = s + timedelta(days=6)
            out.append((s, e, f"{s.isoformat()}~{e.isoformat()}"))
        return out
    if granularity == "month":
        out = []
        y, m = end_date.year, end_date.month
        months: list[tuple[int, int]] = []
        for _ in range(12):
            months.append((y, m))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        months.reverse()
        for yy, mm in months:
            s = date(yy, mm, 1)
            if mm == 12:
                nm = date(yy + 1, 1, 1)
            else:
                nm = date(yy, mm + 1, 1)
            e = nm - timedelta(days=1)
            out.append((s, e, f"{yy:04d}-{mm:02d}"))
        return out
    return []


def _apply_filters(stmt, tenant_id: int, shop_code: str | None, owner: str | None, category: str | None):
    stmt = stmt.where(SalesRecord.tenant_id == tenant_id)
    if shop_code and shop_code != "all":
        stmt = stmt.where(SalesRecord.shop_code == shop_code)
    if owner and owner != "all":
        stmt = stmt.where(SalesRecord.owner == owner)
    if category and category != "all":
        stmt = stmt.where(SalesRecord.category == category)
    return stmt


async def _aggregate(
    session: AsyncSession,
    tenant_id: int,
    start: date,
    end: date,
    shop_code: str | None,
    owner: str | None,
    category: str | None,
) -> dict[str, float]:
    """Aggregate raw rows in [start, end] into the 8 KPIs.

    Conventions matched to the real 数据源.xlsx:
    - "销售额" = sum(收入-收入总额) — gross merchandise value (GMV).
      In real exports `收入-实收金额` is often blank, so we never use it as
      the sales base; income_total is the canonical gross.
    - All rate denominators (退款率/毛利率/利润率/快递占比/营销占比) are GMV.
    """
    cols = (
        func.coalesce(func.sum(SalesRecord.income_total), 0).label("income_total"),
        func.coalesce(func.sum(SalesRecord.actual_income), 0).label("actual_income"),
        func.coalesce(func.sum(SalesRecord.refund_total), 0).label("refund_total"),
        func.coalesce(func.sum(SalesRecord.cost_total), 0).label("cost_total"),
        func.coalesce(func.sum(SalesRecord.profit), 0).label("profit"),
        func.coalesce(func.sum(SalesRecord.shipping_cost), 0).label("shipping_cost"),
        func.coalesce(func.sum(SalesRecord.marketing_cost), 0).label("marketing_cost"),
    )
    stmt = select(*cols).where(and_(SalesRecord.date >= start, SalesRecord.date <= end))
    stmt = _apply_filters(stmt, tenant_id, shop_code, owner, category)
    row = (await session.execute(stmt)).one()

    income_total = float(row.income_total or 0)
    actual_income = float(row.actual_income or 0)
    # Fall back to actual_income only when income_total really is zero (e.g. a
    # source file that ships net revenue instead of gross). Real-world default
    # is income_total.
    gmv = income_total if income_total else actual_income
    cost_total = float(row.cost_total or 0)
    refund_total = float(row.refund_total or 0)
    profit = float(row.profit or 0)

    def pct(num: float, den: float) -> float:
        return (num / den * 100) if den else 0.0

    return {
        "sales": gmv,
        "refundRate": pct(refund_total, gmv),
        "grossMargin": pct(gmv - cost_total, gmv),
        "profit": profit,
        "profitRate": pct(profit, gmv),
        "shipPct": pct(float(row.shipping_cost or 0), gmv),
        "adPct": pct(float(row.marketing_cost or 0), gmv),
    }


def _delta_pct(curr: float, prev: float) -> float | None:
    if prev == 0:
        return None
    return (curr - prev) / abs(prev) * 100


async def get_kpis(session, tenant_id, end_date, granularity, shop_code, owner, category):
    cur_start, cur_end = _period_range(end_date, granularity)
    prev_start, prev_end = _previous_range(cur_start, cur_end, granularity)
    curr = await _aggregate(session, tenant_id, cur_start, cur_end, shop_code, owner, category)
    prev = await _aggregate(session, tenant_id, prev_start, prev_end, shop_code, owner, category)

    trend_ranges = _trend_dates(end_date, granularity)
    series_by_metric: dict[str, list[float]] = {m.key: [] for m in METRIC_DEFS}
    for s, e, _label in trend_ranges:
        agg = await _aggregate(session, tenant_id, s, e, shop_code, owner, category)
        for m in METRIC_DEFS:
            series_by_metric[m.key].append(agg[m.key])

    items = []
    for m in METRIC_DEFS:
        items.append({
            "key": m.key,
            "label": m.label,
            "value": curr[m.key],
            "prev": prev[m.key],
            "delta_pct": _delta_pct(curr[m.key], prev[m.key]),
            "higher_is_better": m.higher_is_better,
            "format": m.format,
            "series": series_by_metric[m.key],
        })
    return {"items": items, "end_date": end_date, "granularity": granularity}


async def get_trend(session, tenant_id, end_date, granularity, metric, shop_code, owner, category):
    if metric not in {m.key for m in METRIC_DEFS}:
        metric = "sales"
    ranges = _trend_dates(end_date, granularity)
    points = []
    for s, e, label in ranges:
        agg = await _aggregate(session, tenant_id, s, e, shop_code, owner, category)
        points.append({"date": label, "value": agg[metric]})
    return {"metric": metric, "points": points}


async def get_category_breakdown(session, tenant_id, end_date, granularity, shop_code, owner):
    start, end = _period_range(end_date, granularity)
    stmt = (
        select(
            SalesRecord.category,
            func.coalesce(func.sum(SalesRecord.income_total), 0).label("income_total"),
            func.coalesce(func.sum(SalesRecord.actual_income), 0).label("actual_income"),
            func.coalesce(func.sum(SalesRecord.profit), 0).label("profit"),
            func.coalesce(func.sum(SalesRecord.cost_total), 0).label("cost_total"),
            func.coalesce(func.sum(SalesRecord.refund_total), 0).label("refund_total"),
        )
        .where(and_(SalesRecord.date >= start, SalesRecord.date <= end))
        .group_by(SalesRecord.category)
        .order_by(func.sum(SalesRecord.income_total).desc())
    )
    stmt = _apply_filters(stmt, tenant_id, shop_code, owner, None)
    rows = (await session.execute(stmt)).all()

    out = []
    for r in rows:
        income_total = float(r.income_total or 0)
        actual_income = float(r.actual_income or 0)
        gmv = income_total if income_total else actual_income
        refund_total = float(r.refund_total or 0)
        cost_total = float(r.cost_total or 0)
        out.append({
            "name": r.category or "(未分类)",
            "sales": gmv,
            "profit": float(r.profit or 0),
            "gross_margin": ((gmv - cost_total) / gmv * 100) if gmv else 0.0,
            "refund_rate": (refund_total / gmv * 100) if gmv else 0.0,
        })
    return out


async def get_filters(session, tenant_id):
    shop_stmt = select(SalesRecord.shop_code, SalesRecord.shop_name).where(SalesRecord.tenant_id == tenant_id).distinct()
    shops = [{"code": code, "name": name or code} for code, name in (await session.execute(shop_stmt)).all() if code]
    owners = sorted(
        o for (o,) in (await session.execute(
            select(SalesRecord.owner).where(SalesRecord.tenant_id == tenant_id).distinct()
        )).all() if o
    )
    cats = sorted(
        c for (c,) in (await session.execute(
            select(SalesRecord.category).where(SalesRecord.tenant_id == tenant_id).distinct()
        )).all() if c
    )
    return {"shops": shops, "owners": owners, "categories": cats}
