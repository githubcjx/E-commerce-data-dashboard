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

公司利润率 (per-DAY apportionment, whole-department denominator):

    For each day d and fee group g:
      monthly_amount(g, ym(d)) — from fee_group_monthly_cost (default 0)
      days_in_month(d)         — calendar days in d's month
      daily_cost(g)            = monthly_amount / days_in_month
      dept_day(g)              = the WHOLE fee group's sales on d — ALL its
                                 shops/owners/categories. Only the tenant and
                                 the user's data-scope limit it; the owner /
                                 category / shop-picker filters DO NOT shrink
                                 it (this is the denominator).
      Each filtered shop s in g on d:
        shop_fixed_s += daily_cost(g) × (sales_s_on_d / dept_day(g))

    The denominator is the whole department, NOT the filtered subset. So
    filtering by one owner (or one shop) charges only that owner/shop its
    proportional slice of the department's daily cost — never the whole
    department's burden. (The previous version used the filtered subset as
    the denominator, which dumped the entire burden onto whatever you
    filtered to — the bug this replaced.)

    Rules:
      • a (group, day) with 0 department sales → not deducted (不扣)
      • days after `today` are skipped (已发生天数 only)
      • every granularity (KPI total, sparkline bucket, trend bucket,
        category row) is a plain sum of the same per-day atoms, so they
        reconcile exactly with no elapsed-day fudge factor.

    Then per shop, the existing formula:
      adj_profit_s = profit_s − shop_fixed_s − sales_s × tax_rate_s
      公司利润率   = SUM(adj_profit_s) / SUM(sales_s)
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Department, FeeGroupMonthlyCost, ROLE_PLATFORM_ADMIN, ROLE_TENANT_ADMIN,
    ROLE_TENANT_SUPER_ADMIN, ROLE_TENANT_USER, SalesRecord, Shop, User,
)


def effective_scope_owners(user: User) -> list[str] | None:
    """All admin tiers see the full dataset; only tenant_user is restricted
    by their data_scope_owners list."""
    if user.role != ROLE_TENANT_USER:
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
    # 成本率 = 成本总额 / 销售额 (lower is better). Replaced the old 毛利率
    # KPI card; the value comes from _kpis_from_per_shop's "costRate".
    MetricDef("costRate", "成本率", "percent", False),
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


async def shop_meta_map(
    session: AsyncSession, tenant_id: int, shop_codes: list[str] | None = None,
) -> dict[str, tuple[str | None, float]]:
    """Return {shop_code: (fee_group_name or None, ship_service_tax_rate)}.

    Shops missing from the map default to (None, 0.0) at the call site —
    no fee group, no tax — i.e. no deduction from 公司利润率.
    """
    stmt = select(
        Shop.shop_code, Shop.fee_group_name, Shop.ship_service_tax_rate,
    ).where(Shop.tenant_id == tenant_id)
    if shop_codes:
        stmt = stmt.where(Shop.shop_code.in_(shop_codes))
    rows = (await session.execute(stmt)).all()
    return {
        code: ((grp or None) if (grp or "").strip() else None, float(tax or 0))
        for code, grp, tax in rows
    }


async def monthly_costs_map(
    session: AsyncSession, tenant_id: int, fee_groups: list[str] | None = None,
) -> dict[tuple[str, str], float]:
    """Return {(fee_group_name, "YYYY-MM"): amount} for the tenant.

    Missing entries default to 0 at the call site — equivalent to "未录入
    该月固定费用". `fee_groups`, if given, limits the query to those names
    (the typical case: we already know which groups appear in the queried
    shop set, no point fetching others).
    """
    stmt = select(
        FeeGroupMonthlyCost.fee_group_name,
        FeeGroupMonthlyCost.year_month,
        FeeGroupMonthlyCost.amount,
    ).where(FeeGroupMonthlyCost.tenant_id == tenant_id)
    if fee_groups:
        stmt = stmt.where(FeeGroupMonthlyCost.fee_group_name.in_(fee_groups))
    rows = (await session.execute(stmt)).all()
    return {(name, ym): float(amt or 0) for name, ym, amt in rows}


async def dept_shops_for_groups(
    session: AsyncSession, tenant_id: int, fee_groups: list[str],
) -> dict[str, str]:
    """Return {shop_code: fee_group_name} for ALL shops in the given fee
    groups — the denominator's shop universe.

    This is deliberately INDEPENDENT of the dashboard's owner / category /
    shop-picker filters: the fixed cost is apportioned against the WHOLE
    department's sales, so we must know every shop in each group, not just
    the ones that survived the current filter. (Data-scope isolation is
    applied later, on the sales query, not here.)
    """
    if not fee_groups:
        return {}
    rows = (await session.execute(
        select(Shop.shop_code, Shop.fee_group_name)
        .where(Shop.tenant_id == tenant_id, Shop.fee_group_name.in_(fee_groups))
    )).all()
    return {code: grp for code, grp in rows if code and grp}


# ---------------------------------------------------------------------------
# Per-day fixed-cost apportionment
# ---------------------------------------------------------------------------

def _ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _dept_day_group_sales(
    dept_daily: dict[date, dict[str, dict[str, float]]],
    dept_shop_fee_groups: dict[str, str | None],
) -> dict[date, dict[str, float]]:
    """Precompute the DENOMINATOR: {date: {fee_group: total_dept_sales}}.

    `dept_daily` is the department-wide per-(date, shop) sales map (fetched
    WITHOUT owner/category/shop-picker filters, so it covers every shop in
    each group). We reduce it to a per-day per-group total — the "部门当天
    总销售额" each shop's share is measured against.
    """
    out: dict[date, dict[str, float]] = {}
    for d, by_shop in dept_daily.items():
        g_sales = out.setdefault(d, {})
        for sc, vals in by_shop.items():
            grp = dept_shop_fee_groups.get(sc)
            if not grp:
                continue
            sales = vals["income_total"] or vals["actual_income"]
            if sales:
                g_sales[grp] = g_sales.get(grp, 0.0) + sales
    return out


def _compute_fixed_cost_deductions(
    daily: dict[date, dict[str, dict[str, float]]],
    dept_day_group_sales: dict[date, dict[str, float]],
    sub_start: date,
    sub_end: date,
    shop_fee_groups: dict[str, str | None],
    monthly_costs: dict[tuple[str, str], float],
    today: date,
) -> dict[str, float]:
    """Per-DAY apportionment of fee-group monthly fixed cost to each filtered
    shop within [sub_start, sub_end]. Returns {shop_code: amount_to_deduct}.

    For each day d (sub_start ≤ d ≤ sub_end and d ≤ today):
        daily_cost(g) = monthly_amount(g, ym(d)) / days_in_month(d)
        dept_day(g)   = department-wide sales of g on d   (the denominator,
                        from `dept_day_group_sales`)
        deduction_s  += daily_cost(g) × (shop_s_sales_on_d / dept_day(g))

    The denominator is the WHOLE department's daily sales, NOT the filtered
    subset `daily` — that's the whole point: filtering by one owner/shop only
    charges its proportional share, never the whole group's burden.

    Rules:
      • a (group, day) with 0 department sales → not deducted (不扣)
      • days after `today` are skipped (已发生天数 only)
      • the result is a plain sum over days, so any coarser granularity
        (week/month bucket, full overview) equals the sum of its days.
    """
    out: dict[str, float] = {}
    if sub_end < sub_start:
        return out

    for d, by_shop in daily.items():
        if not (sub_start <= d <= sub_end) or d > today:
            continue
        ym = _ym(d)
        # Filtered shops with sales on day d, grouped by fee_group.
        per_group: dict[str, dict[str, float]] = {}
        for sc, vals in by_shop.items():
            grp = shop_fee_groups.get(sc)
            if not grp:
                continue
            sales = vals["income_total"] or vals["actual_income"]
            if sales:
                per_group.setdefault(grp, {})[sc] = sales
        if not per_group:
            continue

        days_in_m = calendar.monthrange(d.year, d.month)[1]
        dept_groups = dept_day_group_sales.get(d, {})
        for grp, shops in per_group.items():
            amount = monthly_costs.get((grp, ym), 0.0)
            if amount <= 0:
                continue
            dept_sales = dept_groups.get(grp, 0.0)
            if dept_sales <= 0:
                continue  # 零销售 → 不扣（用户决策）
            daily_cost = amount / days_in_m
            for sc, sales in shops.items():
                out[sc] = out.get(sc, 0.0) + daily_cost * (sales / dept_sales)
    return out


async def _load_dept_day_group_sales(
    session: AsyncSession,
    tenant_id: int,
    fee_groups_in_scope: list[str],
    monthly_costs: dict[tuple[str, str], float],
    start: date,
    end: date,
) -> dict[date, dict[str, float]]:
    """Fetch + reduce the department-wide per-(day, group) sales denominator.

    Returns {} (→ nothing to apportion) when there are no in-scope groups or
    no configured monthly cost, so callers never pay for the extra query when
    no deduction would happen anyway.

    This denominator drops EVERY user-facing restriction — the owner /
    category / shop-picker filters AND `scope_owners` (the per-user data
    scope). The fixed cost is an objective company fact: the whole fee
    group spent X this month and it is apportioned against the whole group's
    real sales. If `scope_owners` shrank this denominator, the same person's
    apportioned share would change depending on WHO is viewing the dashboard
    — a tenant_user scoped to themselves would see the denominator collapse
    to their own sales, inflating their share and lowering their
    公司利润率 below what an admin sees for the identical filter. (That was
    the reported bug.) Data isolation is NOT bypassed: this query only ever
    produces aggregate per-(day, group) totals — never row-level detail — and
    stays strictly within `tenant_id`.
    """
    if not fee_groups_in_scope or not monthly_costs:
        return {}
    dept_shop_groups = await dept_shops_for_groups(
        session, tenant_id, fee_groups_in_scope,
    )
    dept_codes = list(dept_shop_groups.keys())
    if not dept_codes:
        return {}
    dept_daily = await _daily_aggregates_by_shop(
        session, tenant_id, start, end,
        dept_codes, None, None, None,  # no owner/cat/shop filter, no scope_owners
    )
    return _dept_day_group_sales(dept_daily, dept_shop_groups)


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
    tax_rates: dict[str, float],
    fixed_costs: dict[str, float],
) -> dict[str, float]:
    """Compute every KPI from per-shop sums + apportioned fixed costs.

    公司利润率 = SUM(profit_s − fixed_cost_s − sales_s × tax_s) / SUM(sales_s).
    Other metrics aggregate the standard way (sum cols across shops).

    `tax_rates`   : {shop_code: ship_service_tax_rate}  (default 0)
    `fixed_costs` : {shop_code: total apportioned fixed cost for the window}
                    — already pre-computed by _compute_fixed_cost_deductions
                    for the EXACT same window these per-shop sums cover.
    """
    total = {col: 0.0 for col in _AGG_COLS}
    adj_profit_total = 0.0
    for sc, sums in per_shop.items():
        for col in _AGG_COLS:
            total[col] += sums[col]
        sales_s = sums["income_total"] or sums["actual_income"]
        profit_s = sums["profit"]
        tax_rate = tax_rates.get(sc, 0.0)
        fixed_s = fixed_costs.get(sc, 0.0)
        adj_profit_total += profit_s - fixed_s - sales_s * tax_rate

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
        # 成本率 = 成本总额 / 销售额 (lower is better). Used by both the KPI
        # cards and the 类目汇总 table — replaced the old 毛利率 (gmv−cost)/gmv.
        "costRate": pct(cost, gmv),
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
    today = date.today()

    resolved_codes = await _resolve_shop_codes(
        session, tenant_id, user, shop_codes, view_department_id,
    )
    # An empty list (vs None) means "force empty result". Skip the queries
    # and synthesize zeroed KPIs so the frontend renders cleanly.
    if resolved_codes == []:
        empty: dict[str, dict[str, float]] = {}
        empty_f: dict[str, float] = {}
        curr_kpi = _kpis_from_per_shop(empty, empty_f, empty_f)
        prev_kpi = _kpis_from_per_shop(empty, empty_f, empty_f)
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

    # Resolve per-shop fee_group + tax_rate, then load monthly cost rows
    # for the groups actually represented (one round-trip each).
    all_shop_codes = set()
    for by_shop in daily.values():
        all_shop_codes.update(by_shop.keys())
    meta = await shop_meta_map(session, tenant_id, list(all_shop_codes))
    shop_groups = {sc: grp for sc, (grp, _tax) in meta.items()}
    tax_rates = {sc: tax for sc, (_grp, tax) in meta.items()}
    fee_groups_in_scope = sorted({g for g in shop_groups.values() if g})
    monthly_costs = await monthly_costs_map(
        session, tenant_id, fee_groups_in_scope,
    ) if fee_groups_in_scope else {}

    # Department-wide denominator: ALL shops in the in-scope fee groups, over
    # the SAME range as `daily`, but WITHOUT any user-facing restriction
    # (owner/category/shop-picker filters AND scope_owners). The fixed cost
    # is apportioned against the whole group's real sales so the result is
    # identical no matter who views it. Only fetched when there's an actual
    # cost to apportion — otherwise deductions are all 0 anyway.
    dept_dgs = await _load_dept_day_group_sales(
        session, tenant_id, fee_groups_in_scope, monthly_costs,
        prev_start, end_date,
    )

    def _kpi_for(sub_start: date, sub_end: date) -> dict[str, float]:
        per_shop = _sum_range_by_shop(daily, sub_start, sub_end)
        fixed = _compute_fixed_cost_deductions(
            daily, dept_dgs, sub_start, sub_end, shop_groups, monthly_costs, today,
        )
        return _kpis_from_per_shop(per_shop, tax_rates, fixed)

    curr_kpi = _kpi_for(start_date, end_date)
    prev_kpi = _kpi_for(prev_start, prev_end)

    buckets = _enumerate_buckets(start_date, end_date, granularity)
    series_by_metric: dict[str, list[float]] = {m.key: [] for m in METRIC_DEFS}
    for b_start, b_end, _label in buckets:
        bucket_kpi = _kpi_for(b_start, b_end)
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
    today = date.today()

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
    meta = await shop_meta_map(session, tenant_id, list(all_shop_codes))
    shop_groups = {sc: grp for sc, (grp, _tax) in meta.items()}
    tax_rates = {sc: tax for sc, (_grp, tax) in meta.items()}
    fee_groups_in_scope = sorted({g for g in shop_groups.values() if g})
    monthly_costs = await monthly_costs_map(
        session, tenant_id, fee_groups_in_scope,
    ) if fee_groups_in_scope else {}

    dept_dgs = await _load_dept_day_group_sales(
        session, tenant_id, fee_groups_in_scope, monthly_costs,
        start_date, end_date,
    )

    buckets = _enumerate_buckets(start_date, end_date, granularity)
    points = []
    for b_start, b_end, label in buckets:
        bucket_per_shop = _sum_range_by_shop(daily, b_start, b_end)
        # Per-bucket apportionment: each bucket is a sum of its days' per-day
        # apportioned costs, so day/week/month buckets always reconcile with
        # the overview (which is just the sum over the full range).
        bucket_fixed = _compute_fixed_cost_deductions(
            daily, dept_dgs, b_start, b_end, shop_groups, monthly_costs, today,
        )
        bucket_kpi = _kpis_from_per_shop(bucket_per_shop, tax_rates, bucket_fixed)
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
    """Per-category aggregate with prev-period 环比 on sales + profit,
    plus percentage-point 差额 on 公司利润率 / 成本率 / 快递费率.

    Fixed cost allocation per category: each shop's full-range fixed cost
    (apportioned across fee groups for the window) is split into the
    categories that shop sold in, weighted by sales share. This makes the
    SUM(cat company_profit_rate components) reconcile with the overall
    公司利润率 displayed on the KPI cards.
    """
    start_date, end_date = normalize_range(start_date, end_date)
    prev_start, prev_end = previous_range(start_date, end_date)
    today = date.today()

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

    # Daily-by-shop (no category dimension) feeds both the fixed-cost
    # apportionment AND the per-shop total sales we need for the cat-split.
    # Same WHERE filters as the per-cat query above, including categories.
    daily_curr = await _daily_aggregates_by_shop(
        session, tenant_id, start_date, end_date,
        resolved_codes, owners, categories, scope_owners,
    )
    daily_prev = await _daily_aggregates_by_shop(
        session, tenant_id, prev_start, prev_end,
        resolved_codes, owners, categories, scope_owners,
    )

    all_codes: set[str] = set()
    for r in curr_rows:
        all_codes.add(r.shop_code or "")
    for r in prev_rows:
        all_codes.add(r.shop_code or "")
    meta = await shop_meta_map(session, tenant_id, list(all_codes))
    shop_groups = {sc: grp for sc, (grp, _tax) in meta.items()}
    tax_rates = {sc: tax for sc, (_grp, tax) in meta.items()}
    fee_groups_in_scope = sorted({g for g in shop_groups.values() if g})
    monthly_costs = await monthly_costs_map(
        session, tenant_id, fee_groups_in_scope,
    ) if fee_groups_in_scope else {}

    # One denominator map spanning prev_start..end_date covers both the
    # current and previous sub-ranges (it's keyed by date; the deduction
    # function clips to each sub-window).
    dept_dgs = await _load_dept_day_group_sales(
        session, tenant_id, fee_groups_in_scope, monthly_costs,
        prev_start, end_date,
    )

    def _shop_full_fixed_and_sales(daily, sub_start, sub_end):
        """Pre-compute per-shop full fixed cost AND per-shop total sales
        across the sub-range — both needed to allocate to categories."""
        fixed = _compute_fixed_cost_deductions(
            daily, dept_dgs, sub_start, sub_end, shop_groups, monthly_costs, today,
        )
        per_shop = _sum_range_by_shop(daily, sub_start, sub_end)
        sales_total = {
            sc: (vals["income_total"] or vals["actual_income"])
            for sc, vals in per_shop.items()
        }
        return fixed, sales_total

    curr_fixed, curr_sales_total = _shop_full_fixed_and_sales(daily_curr, start_date, end_date)
    prev_fixed, prev_sales_total = _shop_full_fixed_and_sales(daily_prev, prev_start, prev_end)

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

    def _cat_allocated_fixed(per_shop_in_cat, shop_full_fixed, shop_full_sales):
        """Allocate each shop's full-range fixed cost to this category
        proportionally to the category's share of the shop's total sales.
        Shops with 0 total sales contribute 0 (avoid div-by-zero)."""
        out: dict[str, float] = {}
        for sc, sums in per_shop_in_cat.items():
            total_sales = shop_full_sales.get(sc, 0.0)
            if total_sales <= 0:
                continue
            cat_sales = sums["income_total"] or sums["actual_income"]
            share = cat_sales / total_sales
            out[sc] = shop_full_fixed.get(sc, 0.0) * share
        return out

    out = []
    for cat, per_shop in curr_by_cat.items():
        cat_fixed = _cat_allocated_fixed(per_shop, curr_fixed, curr_sales_total)
        kpi = _kpis_from_per_shop(per_shop, tax_rates, cat_fixed)
        prev_per_shop = prev_by_cat.get(cat, {})
        if prev_per_shop:
            prev_cat_fixed = _cat_allocated_fixed(prev_per_shop, prev_fixed, prev_sales_total)
            prev_kpi = _kpis_from_per_shop(prev_per_shop, tax_rates, prev_cat_fixed)
        else:
            prev_kpi = None

        def _rate_diff(key: str) -> float | None:
            # 差额 = 本期率 − 上期率，单位是百分点（8% vs 7% → +1），不是环比变化率
            return kpi[key] - prev_kpi[key] if prev_kpi is not None else None

        prev_sales = prev_kpi["sales"] if prev_kpi else 0.0
        prev_profit = prev_kpi["profit"] if prev_kpi else 0.0
        out.append({
            "name": cat,
            "sales": kpi["sales"],
            "sales_prev": prev_sales,
            "sales_delta_pct": _delta_pct(kpi["sales"], prev_sales),
            "profit": kpi["profit"],
            "profit_prev": prev_profit,
            "profit_delta_pct": _delta_pct(kpi["profit"], prev_profit),
            "company_profit_rate": kpi["companyProfitRate"],
            "company_profit_rate_prev": prev_kpi["companyProfitRate"] if prev_kpi else None,
            "company_profit_rate_diff": _rate_diff("companyProfitRate"),
            "cost_rate": kpi["costRate"],
            "cost_rate_prev": prev_kpi["costRate"] if prev_kpi else None,
            "cost_rate_diff": _rate_diff("costRate"),
            "refund_rate": kpi["refundRate"],
            "ship_pct": kpi["shipPct"],
            "ship_pct_prev": prev_kpi["shipPct"] if prev_kpi else None,
            "ship_pct_diff": _rate_diff("shipPct"),
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
