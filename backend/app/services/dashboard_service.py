"""Dashboard aggregation queries — all scoped by `tenant_id`.

Per-tenant isolation: every query filters `SalesRecord.tenant_id == tenant_id`,
so members of one company share their data pool but can never see another
company's rows. Role within the tenant (admin vs user) doesn't affect what data
is visible — only who can manage users.

Range semantics:
    The KPI / trend / category endpoints accept `start_date` and `end_date`
    that *the user explicitly picked* (range filter on the dashboard). The
    "current period" is that range; the "previous period" is the immediately
    preceding range of the same length, e.g. picking 5.8–5.14 gives a prev
    of 5.1–5.7.

Trend chart:
    For K-line zoom/scroll the trend endpoint returns *all* buckets that fall
    inside the chosen range (granularity = day | week | month | year). The
    frontend uses ECharts dataZoom to show only a window initially.

Performance:
    Each endpoint does a single `GROUP BY date` query covering the longest
    span it needs (typically [prev_start, end_date]) and aggregates buckets
    in Python. ix_sales_tenant_date covers the predicate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SalesRecord, Tenant


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    format: str
    higher_is_better: bool


# Order here is the *default* layout order on the dashboard.
METRIC_DEFS: list[MetricDef] = [
    MetricDef("sales", "销售额", "currency", True),
    MetricDef("profit", "利润额", "currency", True),
    MetricDef("profitRate", "经营利润率", "percent", True),
    MetricDef("companyProfitRate", "公司利润率", "percent", True),
    MetricDef("grossMargin", "毛利率", "percent", True),
    MetricDef("refundRate", "发货退款率", "percent", False),
    MetricDef("shipPct", "快递费用占比", "percent", False),
    MetricDef("adPct", "营销费用占比", "percent", False),
]

# Columns we pull (and sum) once per page render — every KPI derives from these.
_AGG_COLS = (
    "income_total",
    "actual_income",
    "refund_total",
    "cost_total",
    "profit",
    "shipping_cost",
    "marketing_cost",
)


# ---------------------------------------------------------------------------
# Range helpers
# ---------------------------------------------------------------------------

def normalize_range(start: date, end: date) -> tuple[date, date]:
    """Swap if user picked them out of order."""
    return (start, end) if start <= end else (end, start)


def previous_range(start: date, end: date) -> tuple[date, date]:
    """Period immediately preceding [start, end] with the same length."""
    span = (end - start).days + 1
    return start - timedelta(days=span), start - timedelta(days=1)


def _label_range(start: date, end: date) -> str:
    """Compact human-readable label for a date range, used in KPI cards."""
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()} ~ {end.isoformat()}"


# ---------------------------------------------------------------------------
# Trend bucketing — group days into K-line points by granularity
# ---------------------------------------------------------------------------

def _bucket_day(d: date) -> tuple[date, date, str]:
    return d, d, d.isoformat()


def _bucket_week(d: date) -> tuple[date, date, str]:
    weekday = d.weekday()
    s = d - timedelta(days=weekday)
    e = s + timedelta(days=6)
    return s, e, f"{s.isoformat()}~{e.isoformat()}"


def _bucket_month(d: date) -> tuple[date, date, str]:
    s = d.replace(day=1)
    if s.month == 12:
        nm = s.replace(year=s.year + 1, month=1)
    else:
        nm = s.replace(month=s.month + 1)
    e = nm - timedelta(days=1)
    return s, e, f"{s.year:04d}-{s.month:02d}"


def _bucket_year(d: date) -> tuple[date, date, str]:
    s = date(d.year, 1, 1)
    e = date(d.year, 12, 31)
    return s, e, f"{s.year:04d}"


_BUCKETERS = {
    "day": _bucket_day,
    "week": _bucket_week,
    "month": _bucket_month,
    "year": _bucket_year,
}


def _enumerate_buckets(start: date, end: date, granularity: str) -> list[tuple[date, date, str]]:
    """Walk [start, end] producing one bucket per day/week/month/year. Each
    bucket is clamped to the user's selected range so e.g. picking 5.10–5.20
    with granularity=week gives a bucket clamped to that 5-day overlap.
    """
    bucketer = _BUCKETERS.get(granularity, _bucket_day)
    out: list[tuple[date, date, str]] = []
    seen_labels: set[str] = set()
    cur = start
    while cur <= end:
        b_start, b_end, label = bucketer(cur)
        if label not in seen_labels:
            seen_labels.add(label)
            # Clamp to user's selected range so partial buckets at the edges
            # only aggregate days the user actually asked for.
            cs = max(b_start, start)
            ce = min(b_end, end)
            out.append((cs, ce, label))
        # Step to the day after the bucket end to find the next bucket.
        cur = b_end + timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Filters + aggregation primitives
# ---------------------------------------------------------------------------

def _apply_filters(stmt, tenant_id: int, shop_code: str | None, owner: str | None, category: str | None):
    stmt = stmt.where(SalesRecord.tenant_id == tenant_id)
    if shop_code and shop_code != "all":
        stmt = stmt.where(SalesRecord.shop_code == shop_code)
    if owner and owner != "all":
        stmt = stmt.where(SalesRecord.owner == owner)
    if category and category != "all":
        stmt = stmt.where(SalesRecord.category == category)
    return stmt


async def _daily_aggregates(
    session: AsyncSession,
    tenant_id: int,
    start: date,
    end: date,
    shop_code: str | None,
    owner: str | None,
    category: str | None,
) -> dict[date, dict[str, float]]:
    """One query: GROUP BY date over [start, end], return {date: {col: float}}."""
    if start > end:
        return {}
    cols = (
        SalesRecord.date,
        func.coalesce(func.sum(SalesRecord.income_total), 0).label("income_total"),
        func.coalesce(func.sum(SalesRecord.actual_income), 0).label("actual_income"),
        func.coalesce(func.sum(SalesRecord.refund_total), 0).label("refund_total"),
        func.coalesce(func.sum(SalesRecord.cost_total), 0).label("cost_total"),
        func.coalesce(func.sum(SalesRecord.profit), 0).label("profit"),
        func.coalesce(func.sum(SalesRecord.shipping_cost), 0).label("shipping_cost"),
        func.coalesce(func.sum(SalesRecord.marketing_cost), 0).label("marketing_cost"),
    )
    stmt = select(*cols).where(and_(SalesRecord.date >= start, SalesRecord.date <= end))
    stmt = _apply_filters(stmt, tenant_id, shop_code, owner, category).group_by(SalesRecord.date)
    rows = (await session.execute(stmt)).all()
    return {
        r.date: {col: float(getattr(r, col) or 0) for col in _AGG_COLS}
        for r in rows
    }


def _sum_range(daily: dict[date, dict[str, float]], start: date, end: date) -> dict[str, float]:
    out = {col: 0.0 for col in _AGG_COLS}
    if start > end:
        return out
    for d, vals in daily.items():
        if start <= d <= end:
            for col in _AGG_COLS:
                out[col] += vals[col]
    return out


def _kpis_from_sums(sums: dict[str, float], fixed_profit_rate: float, subtract_fixed: bool) -> dict[str, float]:
    """Compute every KPI from a single set of summed columns.

    fixed_profit_rate is the per-tenant 公司利润率 base; subtract_fixed
    toggles whether the 公司利润率 metric actually applies the deduction
    (when off, it just mirrors 经营利润率).
    """
    gmv = sums["income_total"] or sums["actual_income"]
    cost = sums["cost_total"]
    profit = sums["profit"]
    refund = sums["refund_total"]

    def pct(num: float, den: float) -> float:
        return (num / den * 100) if den else 0.0

    profit_rate = pct(profit, gmv)
    company_profit_rate = profit_rate - (fixed_profit_rate * 100 if subtract_fixed else 0)

    return {
        "sales": gmv,
        "profit": profit,
        "profitRate": profit_rate,
        "companyProfitRate": company_profit_rate,
        "grossMargin": pct(gmv - cost, gmv),
        "refundRate": pct(refund, gmv),
        "shipPct": pct(sums["shipping_cost"], gmv),
        "adPct": pct(sums["marketing_cost"], gmv),
    }


def _delta_pct(curr: float, prev: float) -> float | None:
    if prev == 0:
        return None
    return (curr - prev) / abs(prev) * 100


async def _tenant_fixed_rate(session: AsyncSession, tenant_id: int) -> float:
    """Read this tenant's 公司利润率 base; default 0.13 if not set."""
    row = (await session.execute(
        select(Tenant.fixed_profit_rate).where(Tenant.id == tenant_id)
    )).scalar_one_or_none()
    return float(row) if row is not None else 0.13


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

async def get_kpis(
    session, tenant_id, start_date, end_date, granularity, shop_code, owner, category,
    subtract_fixed: bool = True,
):
    start_date, end_date = normalize_range(start_date, end_date)
    prev_start, prev_end = previous_range(start_date, end_date)
    fixed = await _tenant_fixed_rate(session, tenant_id)

    # One query covers prev + current span; series buckets are inside current.
    daily = await _daily_aggregates(
        session, tenant_id, prev_start, end_date, shop_code, owner, category
    )

    curr_kpi = _kpis_from_sums(_sum_range(daily, start_date, end_date), fixed, subtract_fixed)
    prev_kpi = _kpis_from_sums(_sum_range(daily, prev_start, prev_end), fixed, subtract_fixed)

    buckets = _enumerate_buckets(start_date, end_date, granularity)
    series_by_metric: dict[str, list[float]] = {m.key: [] for m in METRIC_DEFS}
    for b_start, b_end, _label in buckets:
        bucket_kpi = _kpis_from_sums(_sum_range(daily, b_start, b_end), fixed, subtract_fixed)
        for m in METRIC_DEFS:
            series_by_metric[m.key].append(bucket_kpi[m.key])

    items = []
    for m in METRIC_DEFS:
        items.append({
            "key": m.key,
            "label": m.label,
            "value": curr_kpi[m.key],
            "prev": prev_kpi[m.key],
            "delta_pct": _delta_pct(curr_kpi[m.key], prev_kpi[m.key]),
            "higher_is_better": m.higher_is_better,
            "format": m.format,
            "series": series_by_metric[m.key],
        })
    return {
        "items": items,
        "start_date": start_date,
        "end_date": end_date,
        "granularity": granularity,
        "current_label": _label_range(start_date, end_date),
        "previous_label": _label_range(prev_start, prev_end),
        "fixed_profit_rate": fixed,
        "subtract_fixed": subtract_fixed,
    }


async def get_trend(
    session, tenant_id, start_date, end_date, granularity, metric,
    shop_code, owner, category, subtract_fixed: bool = True,
):
    if metric not in {m.key for m in METRIC_DEFS}:
        metric = "sales"
    start_date, end_date = normalize_range(start_date, end_date)
    fixed = await _tenant_fixed_rate(session, tenant_id)

    daily = await _daily_aggregates(
        session, tenant_id, start_date, end_date, shop_code, owner, category
    )

    buckets = _enumerate_buckets(start_date, end_date, granularity)
    points = []
    for b_start, b_end, label in buckets:
        bucket_kpi = _kpis_from_sums(_sum_range(daily, b_start, b_end), fixed, subtract_fixed)
        points.append({"date": label, "value": bucket_kpi[metric]})
    return {"metric": metric, "points": points, "granularity": granularity}


async def get_category_breakdown(
    session, tenant_id, start_date, end_date, shop_code, owner, subtract_fixed: bool = True,
):
    """Per-category aggregate with prev-period 环比 on sales + profit.

    Two queries (current + previous), then merge in Python by category name.
    """
    start_date, end_date = normalize_range(start_date, end_date)
    prev_start, prev_end = previous_range(start_date, end_date)
    fixed = await _tenant_fixed_rate(session, tenant_id)

    def _select_for(start: date, end: date):
        cols = (
            SalesRecord.category,
            func.coalesce(func.sum(SalesRecord.income_total), 0).label("income_total"),
            func.coalesce(func.sum(SalesRecord.actual_income), 0).label("actual_income"),
            func.coalesce(func.sum(SalesRecord.refund_total), 0).label("refund_total"),
            func.coalesce(func.sum(SalesRecord.cost_total), 0).label("cost_total"),
            func.coalesce(func.sum(SalesRecord.profit), 0).label("profit"),
            func.coalesce(func.sum(SalesRecord.shipping_cost), 0).label("shipping_cost"),
        )
        stmt = select(*cols).where(and_(SalesRecord.date >= start, SalesRecord.date <= end)).group_by(SalesRecord.category)
        return _apply_filters(stmt, tenant_id, shop_code, owner, None)

    curr_rows = (await session.execute(_select_for(start_date, end_date))).all()
    prev_rows = (await session.execute(_select_for(prev_start, prev_end))).all()

    def to_sums(r):
        return {
            "income_total": float(r.income_total or 0),
            "actual_income": float(r.actual_income or 0),
            "refund_total": float(r.refund_total or 0),
            "cost_total": float(r.cost_total or 0),
            "profit": float(r.profit or 0),
            "shipping_cost": float(r.shipping_cost or 0),
            # marketing_cost isn't displayed in the category table, but
            # _kpis_from_sums expects it — pad with 0.
            "marketing_cost": 0.0,
        }

    prev_by_cat = {r.category: to_sums(r) for r in prev_rows}

    out = []
    for r in curr_rows:
        cat = r.category or "(未分类)"
        sums = to_sums(r)
        kpi = _kpis_from_sums(sums, fixed, subtract_fixed)

        # 环比 for sales + profit
        prev = prev_by_cat.get(r.category)
        prev_sales = (prev["income_total"] or prev["actual_income"]) if prev else 0.0
        prev_profit = prev["profit"] if prev else 0.0

        out.append({
            "name": cat,
            "sales": kpi["sales"],
            "sales_prev": prev_sales,
            "sales_delta_pct": _delta_pct(kpi["sales"], prev_sales),
            "profit": kpi["profit"],
            "profit_prev": prev_profit,
            "profit_delta_pct": _delta_pct(kpi["profit"], prev_profit),
            "company_profit_rate": kpi["companyProfitRate"],
            "gross_margin": kpi["grossMargin"],
            "refund_rate": kpi["refundRate"],
            "ship_pct": kpi["shipPct"],
        })
    # Sort by sales desc for stable display
    out.sort(key=lambda x: x["sales"], reverse=True)
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
