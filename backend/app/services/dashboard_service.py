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

公司利润率 (NEW formula):
    Per-shop: adj_profit_s = profit_s − per_capita_share_s − sales_s × tax_rate_s
    Aggregate: 公司利润率 = SUM(adj_profit_s) / SUM(sales_s)

    The two values per_capita_share and tax_rate are stored on the shops
    table; missing shops default to 0 (no deduction). This formula is
    applied at every aggregation granularity (KPI overall, KPI sparkline
    buckets, trend chart buckets, category breakdown).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Department, ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN, SalesRecord,
    Shop, User,
)


def effective_scope_owners(user: User) -> list[str] | None:
    if user.role in (ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN):
        return None
    return user.data_scope_owners


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    format: str
    higher_is_better: bool


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
    return (start, end) if start <= end else (end, start)


def previous_range(start: date, end: date) -> tuple[date, date]:
    span = (end - start).days + 1
    return start - timedelta(days=span), start - timedelta(days=1)


def _label_range(start: date, end: date) -> str:
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()} ~ {end.isoformat()}"


# ---------------------------------------------------------------------------
# Trend bucketing
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
    bucketer = _BUCKETERS.get(granularity, _bucket_day)
    out: list[tuple[date, date, str]] = []
    seen_labels: set[str] = set()
    cur = start
    while cur <= end:
        b_start, b_end, label = bucketer(cur)
        if label not in seen_labels:
            seen_labels.add(label)
            cs = max(b_start, start)
            ce = min(b_end, end)
            out.append((cs, ce, label))
        cur = b_end + timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Shop-fee + view-department helpers
# ---------------------------------------------------------------------------

async def shops_in_view_department(
    session: AsyncSession, tenant_id: int, view_dept_id: int,
) -> list[str]:
    """List of shop_codes belonging to the given view-department."""
    rows = (await session.execute(
        select(Shop.shop_code)
        .where(Shop.tenant_id == tenant_id, Shop.view_department_id == view_dept_id)
    )).all()
    return [code for (code,) in rows]


async def validate_view_department(
    session: AsyncSession, user: User, view_dept_id: int | None,
) -> int | None:
    """Cross-tenant safety: a non-platform_admin's view picker is only
    allowed to point at departments inside their own tenant. Returns the
    id if valid, else None (treat as no filter).
    """
    if view_dept_id is None:
        return None
    dept = (await session.execute(
        select(Department).where(Department.id == view_dept_id)
    )).scalar_one_or_none()
    if not dept:
        return None
    if user.role != ROLE_PLATFORM_ADMIN and user.tenant_id is not None and dept.tenant_id != user.tenant_id:
        return None
    return view_dept_id


async def shop_fees_map(
    session: AsyncSession, tenant_id: int, shop_codes: list[str] | None = None,
) -> dict[str, tuple[float, float]]:
    """Return {shop_code: (per_capita_share, ship_service_tax_rate)} for the
    tenant. If shop_codes is given, limit to those shops; missing shops
    are simply not in the map and default to (0, 0) at the call site.
    """
    stmt = select(
        Shop.shop_code, Shop.per_capita_share, Shop.ship_service_tax_rate,
    ).where(Shop.tenant_id == tenant_id)
    if shop_codes:
        stmt = stmt.where(Shop.shop_code.in_(shop_codes))
    rows = (await session.execute(stmt)).all()
    return {code: (float(share or 0), float(tax or 0)) for code, share, tax in rows}


# ---------------------------------------------------------------------------
# Filters + aggregation primitives
# ---------------------------------------------------------------------------

def _apply_filters(
    stmt, tenant_id: int,
    shop_codes: list[str] | None, owners: list[str] | None,
    categories: list[str] | None,
    scope_owners: list[str] | None = None,
):
    """Common WHERE clauses for every dashboard query.

    Multi-select arrays:
      None / [] → no filter
      [..]      → col IN (this list)

    scope_owners enforces per-user data isolation; intersects with owner picker.
    """
    stmt = stmt.where(SalesRecord.tenant_id == tenant_id)
    if shop_codes:
        stmt = stmt.where(SalesRecord.shop_code.in_(shop_codes))
    if categories:
        stmt = stmt.where(SalesRecord.category.in_(categories))

    if scope_owners is None:
        if owners:
            stmt = stmt.where(SalesRecord.owner.in_(owners))
    elif not scope_owners:
        stmt = stmt.where(SalesRecord.id == -1)
    else:
        if owners:
            inter = [o for o in owners if o in set(scope_owners)]
            if not inter:
                stmt = stmt.where(SalesRecord.id == -1)
            else:
                stmt = stmt.where(SalesRecord.owner.in_(inter))
        else:
            stmt = stmt.where(SalesRecord.owner.in_(scope_owners))
    return stmt


async def _daily_aggregates_by_shop(
    session: AsyncSession,
    tenant_id: int,
    start: date,
    end: date,
    shop_codes: list[str] | None,
    owners: list[str] | None,
    categories: list[str] | None,
    scope_owners: list[str] | None = None,
) -> dict[date, dict[str, dict[str, float]]]:
    """Group BY (date, shop_code) so 公司利润率 can compute per-shop fee
    deductions before aggregating across shops.

    Returns {date: {shop_code: {col: float, ...}}}.
    """
    if start > end:
        return {}
    cols = (
        SalesRecord.date,
        SalesRecord.shop_code,
        func.coalesce(func.sum(SalesRecord.income_total), 0).label("income_total"),
        func.coalesce(func.sum(SalesRecord.actual_income), 0).label("actual_income"),
        func.coalesce(func.sum(SalesRecord.refund_total), 0).label("refund_total"),
        func.coalesce(func.sum(SalesRecord.cost_total), 0).label("cost_total"),
        func.coalesce(func.sum(SalesRecord.profit), 0).label("profit"),
        func.coalesce(func.sum(SalesRecord.shipping_cost), 0).label("shipping_cost"),
        func.coalesce(func.sum(SalesRecord.marketing_cost), 0).label("marketing_cost"),
    )
    stmt = select(*cols).where(and_(SalesRecord.date >= start, SalesRecord.date <= end))
    stmt = _apply_filters(stmt, tenant_id, shop_codes, owners, categories, scope_owners)
    stmt = stmt.group_by(SalesRecord.date, SalesRecord.shop_code)
    rows = (await session.execute(stmt)).all()

    out: dict[date, dict[str, dict[str, float]]] = {}
    for r in rows:
        d = r.date
        sc = r.shop_code or ""
        out.setdefault(d, {})[sc] = {col: float(getattr(r, col) or 0) for col in _AGG_COLS}
    return out


def _sum_range_by_shop(
    daily: dict[date, dict[str, dict[str, float]]], start: date, end: date,
) -> dict[str, dict[str, float]]:
    """Aggregate the per-(date, shop) buckets over a date range into per-shop sums."""
    out: dict[str, dict[str, float]] = {}
    if start > end:
        return out
    for d, by_shop in daily.items():
        if not (start <= d <= end):
            continue
        for sc, vals in by_shop.items():
            agg = out.setdefault(sc, {col: 0.0 for col in _AGG_COLS})
            for col in _AGG_COLS:
                agg[col] += vals[col]
    return out


def _kpis_from_per_shop(
    per_shop: dict[str, dict[str, float]],
    fees: dict[str, tuple[float, float]],
) -> dict[str, float]:
    """Compute every KPI from per-shop sums + per-shop fees.

    公司利润率 = SUM(profit_s − per_capita_share_s − sales_s × tax_s) / SUM(sales_s).
    Other metrics aggregate the standard way (sum cols across shops).
    """
    total = {col: 0.0 for col in _AGG_COLS}
    adj_profit_total = 0.0
    for sc, sums in per_shop.items():
        for col in _AGG_COLS:
            total[col] += sums[col]
        share, tax_rate = fees.get(sc, (0.0, 0.0))
        sales_s = sums["income_total"] or sums["actual_income"]
        profit_s = sums["profit"]
        adj_profit_total += profit_s - share - sales_s * tax_rate

    gmv = total["income_total"] or total["actual_income"]
    cost = total["cost_total"]
    profit = total["profit"]
    refund = total["refund_total"]

    def pct(num: float, den: float) -> float:
        return (num / den * 100) if den else 0.0

    return {
        "sales": gmv,
        "profit": profit,
        "profitRate": pct(profit, gmv),
        "companyProfitRate": pct(adj_profit_total, gmv),
        "grossMargin": pct(gmv - cost, gmv),
        "refundRate": pct(refund, gmv),
        "shipPct": pct(total["shipping_cost"], gmv),
        "adPct": pct(total["marketing_cost"], gmv),
    }


def _delta_pct(curr: float, prev: float) -> float | None:
    if prev == 0:
        return None
    return (curr - prev) / abs(prev) * 100


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

async def _resolve_shop_codes(
    session: AsyncSession, tenant_id: int, user: User,
    shop_codes: list[str] | None, view_department_id: int | None,
) -> list[str] | None:
    """Intersect the user-picked shop_codes with the view-department's
    shop list (if a view-department is in play).

    Returns:
      None  → no shop filter (the picker was 全部 and no view dept)
      []    → no shops match (view dept is empty, or intersection is empty)
              — caller should treat as "match nothing" rather than "全部"
      [..]  → final shop filter list

    Note the "[]" sentinel: when the view-dept picker is set but the dept
    has no shops yet, we DO want an empty result, not "fall back to no
    filter". The dashboard code below converts [] into a tautologically
    false WHERE so the response is empty.
    """
    view_dept_id = await validate_view_department(session, user, view_department_id)
    if view_dept_id is None:
        return shop_codes if shop_codes else None
    view_shops = await shops_in_view_department(session, tenant_id, view_dept_id)
    if not shop_codes:
        return view_shops  # may be []
    # Intersect; preserve the user's order
    allowed = set(view_shops)
    inter = [s for s in shop_codes if s in allowed]
    return inter  # may be []


def _bake_empty_filter(stmt):
    """Force a query to return no rows — used when the resolved shop list
    is an empty list (intentional 0-match), not None."""
    return stmt.where(SalesRecord.id == -1)


async def get_kpis(
    session, tenant_id, start_date, end_date, granularity,
    shop_codes, owners, categories,
    subtract_fixed: bool = True,  # kept for backwards compat, no longer used
    scope_owners: list[str] | None = None,
    view_department_id: int | None = None,
    user: User | None = None,
):
    start_date, end_date = normalize_range(start_date, end_date)
    prev_start, prev_end = previous_range(start_date, end_date)

    resolved_codes = await _resolve_shop_codes(
        session, tenant_id, user, shop_codes, view_department_id,
    )
    # An empty list (vs None) means "force empty result". Skip the queries
    # and synthesize zeroed KPIs so the frontend renders cleanly.
    if resolved_codes == []:
        empty_per_shop: dict[str, dict[str, float]] = {}
        fees: dict[str, tuple[float, float]] = {}
        curr_kpi = _kpis_from_per_shop(empty_per_shop, fees)
        prev_kpi = _kpis_from_per_shop(empty_per_shop, fees)
        buckets = _enumerate_buckets(start_date, end_date, granularity)
        zero_series = [0.0] * len(buckets)
        items = []
        for m in METRIC_DEFS:
            items.append({
                "key": m.key, "label": m.label,
                "value": 0.0, "prev": 0.0, "delta_pct": None,
                "higher_is_better": m.higher_is_better, "format": m.format,
                "series": zero_series.copy(),
            })
        return {
            "items": items, "start_date": start_date, "end_date": end_date,
            "granularity": granularity,
            "current_label": _label_range(start_date, end_date),
            "previous_label": _label_range(prev_start, prev_end),
        }

    daily = await _daily_aggregates_by_shop(
        session, tenant_id, prev_start, end_date,
        resolved_codes, owners, categories, scope_owners,
    )

    # Single query for shop-fee lookup (limited to shops actually in scope).
    all_shop_codes = set()
    for by_shop in daily.values():
        all_shop_codes.update(by_shop.keys())
    fees = await shop_fees_map(session, tenant_id, list(all_shop_codes))

    curr_per_shop = _sum_range_by_shop(daily, start_date, end_date)
    prev_per_shop = _sum_range_by_shop(daily, prev_start, prev_end)
    curr_kpi = _kpis_from_per_shop(curr_per_shop, fees)
    prev_kpi = _kpis_from_per_shop(prev_per_shop, fees)

    buckets = _enumerate_buckets(start_date, end_date, granularity)
    series_by_metric: dict[str, list[float]] = {m.key: [] for m in METRIC_DEFS}
    for b_start, b_end, _label in buckets:
        bucket_per_shop = _sum_range_by_shop(daily, b_start, b_end)
        bucket_kpi = _kpis_from_per_shop(bucket_per_shop, fees)
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
    }


async def get_trend(
    session, tenant_id, start_date, end_date, granularity, metric,
    shop_codes, owners, categories,
    subtract_fixed: bool = True,
    scope_owners: list[str] | None = None,
    view_department_id: int | None = None,
    user: User | None = None,
):
    if metric not in {m.key for m in METRIC_DEFS}:
        metric = "sales"
    start_date, end_date = normalize_range(start_date, end_date)

    resolved_codes = await _resolve_shop_codes(
        session, tenant_id, user, shop_codes, view_department_id,
    )
    if resolved_codes == []:
        buckets = _enumerate_buckets(start_date, end_date, granularity)
        return {
            "metric": metric,
            "points": [{"date": label, "value": 0.0} for _, _, label in buckets],
            "granularity": granularity,
        }

    daily = await _daily_aggregates_by_shop(
        session, tenant_id, start_date, end_date,
        resolved_codes, owners, categories, scope_owners,
    )
    all_shop_codes = set()
    for by_shop in daily.values():
        all_shop_codes.update(by_shop.keys())
    fees = await shop_fees_map(session, tenant_id, list(all_shop_codes))

    buckets = _enumerate_buckets(start_date, end_date, granularity)
    points = []
    for b_start, b_end, label in buckets:
        bucket_per_shop = _sum_range_by_shop(daily, b_start, b_end)
        bucket_kpi = _kpis_from_per_shop(bucket_per_shop, fees)
        points.append({"date": label, "value": bucket_kpi[metric]})
    return {"metric": metric, "points": points, "granularity": granularity}


async def get_category_breakdown(
    session, tenant_id, start_date, end_date,
    shop_codes, owners, categories,
    subtract_fixed: bool = True,
    scope_owners: list[str] | None = None,
    view_department_id: int | None = None,
    user: User | None = None,
):
    """Per-category aggregate with prev-period 环比 on sales + profit.

    公司利润率 inside a category row uses the same per-shop formula:
    aggregate (date, shop) within that category, look up fees, and apply.
    """
    start_date, end_date = normalize_range(start_date, end_date)
    prev_start, prev_end = previous_range(start_date, end_date)

    resolved_codes = await _resolve_shop_codes(
        session, tenant_id, user, shop_codes, view_department_id,
    )
    if resolved_codes == []:
        return []

    def _select_for(start: date, end: date):
        cols = (
            SalesRecord.category,
            SalesRecord.shop_code,
            func.coalesce(func.sum(SalesRecord.income_total), 0).label("income_total"),
            func.coalesce(func.sum(SalesRecord.actual_income), 0).label("actual_income"),
            func.coalesce(func.sum(SalesRecord.refund_total), 0).label("refund_total"),
            func.coalesce(func.sum(SalesRecord.cost_total), 0).label("cost_total"),
            func.coalesce(func.sum(SalesRecord.profit), 0).label("profit"),
            func.coalesce(func.sum(SalesRecord.shipping_cost), 0).label("shipping_cost"),
        )
        stmt = select(*cols).where(and_(SalesRecord.date >= start, SalesRecord.date <= end))
        stmt = _apply_filters(stmt, tenant_id, resolved_codes, owners, categories, scope_owners)
        return stmt.group_by(SalesRecord.category, SalesRecord.shop_code)

    curr_rows = (await session.execute(_select_for(start_date, end_date))).all()
    prev_rows = (await session.execute(_select_for(prev_start, prev_end))).all()

    # Collect all shop codes seen so we can fetch fees in one query.
    all_codes: set[str] = set()
    for r in curr_rows:
        all_codes.add(r.shop_code or "")
    for r in prev_rows:
        all_codes.add(r.shop_code or "")
    fees = await shop_fees_map(session, tenant_id, list(all_codes))

    def to_per_shop_per_cat(rows):
        """{category: {shop_code: {col: value, ...}}}"""
        out: dict[str, dict[str, dict[str, float]]] = {}
        for r in rows:
            cat = r.category or "(未分类)"
            sums = {
                "income_total": float(r.income_total or 0),
                "actual_income": float(r.actual_income or 0),
                "refund_total": float(r.refund_total or 0),
                "cost_total": float(r.cost_total or 0),
                "profit": float(r.profit or 0),
                "shipping_cost": float(r.shipping_cost or 0),
                "marketing_cost": 0.0,  # not in category SELECT — pad
            }
            out.setdefault(cat, {})[r.shop_code or ""] = sums
        return out

    curr_by_cat = to_per_shop_per_cat(curr_rows)
    prev_by_cat = to_per_shop_per_cat(prev_rows)

    out = []
    for cat, per_shop in curr_by_cat.items():
        kpi = _kpis_from_per_shop(per_shop, fees)
        prev_per_shop = prev_by_cat.get(cat, {})
        prev_kpi = _kpis_from_per_shop(prev_per_shop, fees) if prev_per_shop else {
            "sales": 0.0, "profit": 0.0,
        }

        out.append({
            "name": cat,
            "sales": kpi["sales"],
            "sales_prev": prev_kpi.get("sales", 0.0),
            "sales_delta_pct": _delta_pct(kpi["sales"], prev_kpi.get("sales", 0.0)),
            "profit": kpi["profit"],
            "profit_prev": prev_kpi.get("profit", 0.0),
            "profit_delta_pct": _delta_pct(kpi["profit"], prev_kpi.get("profit", 0.0)),
            "company_profit_rate": kpi["companyProfitRate"],
            "gross_margin": kpi["grossMargin"],
            "refund_rate": kpi["refundRate"],
            "ship_pct": kpi["shipPct"],
        })
    out.sort(key=lambda x: x["sales"], reverse=True)
    return out


async def get_filters(session, tenant_id, scope_owners: list[str] | None = None):
    """Filter dropdowns + data bounds."""
    shop_stmt = select(SalesRecord.shop_code, SalesRecord.shop_name).where(SalesRecord.tenant_id == tenant_id).distinct()
    shops = [{"code": code, "name": name or code} for code, name in (await session.execute(shop_stmt)).all() if code]

    if scope_owners is None:
        owner_rows = (await session.execute(
            select(SalesRecord.owner).where(SalesRecord.tenant_id == tenant_id).distinct()
        )).all()
        owners = sorted(o for (o,) in owner_rows if o)
    else:
        if not scope_owners:
            owners = []
        else:
            owner_rows = (await session.execute(
                select(SalesRecord.owner)
                .where(SalesRecord.tenant_id == tenant_id)
                .where(SalesRecord.owner.in_(scope_owners))
                .distinct()
            )).all()
            owners = sorted(o for (o,) in owner_rows if o)

    cats = sorted(
        c for (c,) in (await session.execute(
            select(SalesRecord.category).where(SalesRecord.tenant_id == tenant_id).distinct()
        )).all() if c
    )
    bounds = (await session.execute(
        select(func.min(SalesRecord.date), func.max(SalesRecord.date))
        .where(SalesRecord.tenant_id == tenant_id)
    )).one()
    date_min = bounds[0].isoformat() if bounds[0] else None
    date_max = bounds[1].isoformat() if bounds[1] else None
    return {
        "shops": shops, "owners": owners, "categories": cats,
        "date_min": date_min, "date_max": date_max,
    }
