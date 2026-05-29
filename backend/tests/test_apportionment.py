"""Per-DAY 固定费用 apportionment tests (whole-department denominator).

These exercise the PURE functions that drive 公司利润率 — no DB, no
fixtures, just dict-shaped inputs that mirror what the dashboard
service builds from SQL aggregates. Failures here mean the calc layer
is wrong; passing here doesn't prove the SQL or API wiring works.

The canonical scenario (from the spec discussion):
    A 部门 2026-05 月度固定费用 = 100,000 元；May 31 天；
    A 店占 A 部门 5 月销售额 50%；今天 = 2026-05-26 → 已过 26 天。
    A 店本月应承担 = 100000 / 31 × 26 × 0.5 ≈ 41935.4839 元

Apportionment model (the fix this file was rewritten for):
    每天 daily_cost(g) = 月度费用 / 当月天数
    每天 dept_day(g)   = 该 fee group 当天【整部门】销售额  ← 分母
    每店每天扣减       = daily_cost × (该店当天销售 / dept_day)
    The denominator is the WHOLE department, NOT the filtered subset —
    so filtering by one shop/owner charges only its proportional slice,
    never the whole department's burden. (Old bug: it used the filtered
    subset as the denominator → ≈100% share → whole burden on one shop.)
"""
from __future__ import annotations

from datetime import date, timedelta

import inspect

import pytest

from app.services.dashboard_service import (
    _compute_fixed_cost_deductions,
    _dept_day_group_sales,
    _kpis_from_per_shop,
    _load_dept_day_group_sales,
    _ym,
)
from app.api.shops import _enumerate_months


# ---------------------------------------------------------------------------
# Small helpers used to build the "daily" dict shape the dashboard service
# normally gets from the SQL aggregate. Saves a lot of repetition.
# ---------------------------------------------------------------------------

_AGG_DEFAULT = {
    "income_total": 0.0,
    "actual_income": 0.0,
    "refund_total": 0.0,
    "cost_total": 0.0,
    "profit": 0.0,
    "shipping_cost": 0.0,
    "marketing_cost": 0.0,
}


def _row(sales: float, profit: float = 0.0, **extra: float) -> dict[str, float]:
    """Build one (date, shop) row of aggregated sales/profit/etc."""
    r = _AGG_DEFAULT.copy()
    r["income_total"] = sales
    r["actual_income"] = sales
    r["profit"] = profit
    r.update(extra)
    return r


def _daily(rows: dict[tuple[date, str], dict[str, float]]) -> dict:
    """{(date, shop): row} → {date: {shop: row}} (matches service shape)."""
    out: dict[date, dict[str, dict[str, float]]] = {}
    for (d, sc), vals in rows.items():
        out.setdefault(d, {})[sc] = vals
    return out


def _spread_sales(shop: str, start: date, end: date, total_sales: float,
                  profit_rate: float = 0.2) -> dict[tuple[date, str], dict[str, float]]:
    """Evenly spread `total_sales` across all days in [start, end] for one
    shop. Profit defaults to 20% of sales (arbitrary but realistic-ish)."""
    days = (end - start).days + 1
    per_day = total_sales / days
    out: dict[tuple[date, str], dict[str, float]] = {}
    cur = start
    while cur <= end:
        out[(cur, shop)] = _row(sales=per_day, profit=per_day * profit_rate)
        cur += timedelta(days=1)
    return out


def _dept_dgs(daily: dict, shop_groups: dict[str, str | None]) -> dict:
    """Build the denominator map {date: {group: total_dept_sales}} from a
    department-wide daily map — exactly what the service does via
    `_load_dept_day_group_sales`. In most tests the filtered `daily` IS the
    whole department, so we pass the same map for both. The whole-department
    regression test deliberately passes a LARGER denominator than `daily`.
    """
    return _dept_day_group_sales(daily, shop_groups)


# ---------------------------------------------------------------------------
# _ym / _enumerate_months — basic helpers
# ---------------------------------------------------------------------------

def test_ym_zero_pads_month():
    assert _ym(date(2026, 5, 1)) == "2026-05"
    assert _ym(date(2026, 12, 31)) == "2026-12"
    assert _ym(date(2026, 1, 1)) == "2026-01"


def test_enumerate_months_inclusive_ascending():
    assert _enumerate_months("2026-04", "2026-07") == [
        "2026-04", "2026-05", "2026-06", "2026-07",
    ]


def test_enumerate_months_year_boundary():
    assert _enumerate_months("2025-11", "2026-02") == [
        "2025-11", "2025-12", "2026-01", "2026-02",
    ]


def test_enumerate_months_single_month():
    assert _enumerate_months("2026-05", "2026-05") == ["2026-05"]


def test_enumerate_months_reversed_returns_empty():
    """Defensive: latest < earliest shouldn't loop forever or wrap."""
    assert _enumerate_months("2026-07", "2026-04") == []


# ---------------------------------------------------------------------------
# _dept_day_group_sales — the denominator builder
# ---------------------------------------------------------------------------

def test_dept_day_group_sales_buckets_by_day_and_group():
    """Reduces a per-(date, shop) map to per-(date, group) totals, summing
    shops in the same group and ignoring shops with no group."""
    d1, d2 = date(2026, 5, 1), date(2026, 5, 2)
    daily = _daily({
        (d1, "shopA"): _row(sales=100),
        (d1, "shopB"): _row(sales=300),   # same group as A
        (d1, "shopX"): _row(sales=999),   # no group → ignored
        (d2, "shopA"): _row(sales=50),
    })
    shop_groups = {"shopA": "deptA", "shopB": "deptA", "shopX": None}
    dgs = _dept_day_group_sales(daily, shop_groups)
    assert dgs[d1]["deptA"] == pytest.approx(400.0)
    assert "deptA" not in dgs.get(d2, {}) or dgs[d2]["deptA"] == pytest.approx(50.0)
    assert dgs[d2]["deptA"] == pytest.approx(50.0)
    # shopX never contributes a group entry.
    assert all("deptA" == g for day in dgs.values() for g in day)


def test_denominator_query_ignores_scope_owners():
    """REGRESSION: the fixed-cost denominator must NOT be restricted by the
    viewer's data scope. If `_load_dept_day_group_sales` ever takes a
    `scope_owners` param again, the per-(day, group) denominator would shrink
    to the rows a tenant_user can see — so the same person's apportioned
    fixed-cost share (and thus 公司利润率) would differ between an admin and
    a scoped普通用户 viewing the identical filter. The denominator is an
    objective company fact; it stays whole-department regardless of who looks.

    We assert it at the signature level because the DB query itself needs a
    live session this pure-function suite doesn't have — but the contract
    'no scope_owners reaches the denominator' is exactly what we must lock.
    """
    params = inspect.signature(_load_dept_day_group_sales).parameters
    assert "scope_owners" not in params, (
        "fixed-cost denominator must not be scoped by viewer data permissions"
    )


# ---------------------------------------------------------------------------
# _compute_fixed_cost_deductions — the apportionment heart
# ---------------------------------------------------------------------------

def test_canonical_user_example():
    """The exact scenario from the requirements discussion:
       A部门月度 = 100k, May 31 天, A店 50% 销售额, 今天 5/26
       A 店应承担 ≈ 41935.4839
    """
    today = date(2026, 5, 26)
    # Two shops in 部门A, A 店和 B 店各占 50% 销售额（用对称数据简化验证）
    rows: dict = {}
    rows.update(_spread_sales("shopA", date(2026, 5, 1), today, total_sales=100_000))
    rows.update(_spread_sales("shopB", date(2026, 5, 1), today, total_sales=100_000))
    daily = _daily(rows)

    shop_groups = {"shopA": "deptA", "shopB": "deptA"}
    monthly_costs = {("deptA", "2026-05"): 100_000.0}
    dgs = _dept_dgs(daily, shop_groups)

    deductions = _compute_fixed_cost_deductions(
        daily, dgs, date(2026, 5, 1), date(2026, 5, 31),
        shop_groups, monthly_costs, today,
    )

    expected_per_shop = 100_000 / 31 * 26 * 0.5  # ≈ 41935.4839
    assert deductions["shopA"] == pytest.approx(expected_per_shop, rel=1e-6)
    assert deductions["shopB"] == pytest.approx(expected_per_shop, rel=1e-6)

    # The group total burden = (100000/31) * 26 ≈ 83870.9677
    total = deductions["shopA"] + deductions["shopB"]
    assert total == pytest.approx(100_000 / 31 * 26, rel=1e-6)


def test_filtering_one_shop_uses_whole_dept_denominator():
    """REGRESSION (the bug this rewrite fixes): when the dashboard is
    filtered to a single shop/owner, that shop must bear only its
    proportional slice of the department's burden — the denominator stays
    the WHOLE department, it does not shrink to the filtered subset.

    Full dept = shopA + shopB, each 50% of sales for the whole of May.
    Filtered view shows only shopA. shopA should be charged 50% of the
    100k burden (= 50000), NOT the whole 100k.
    """
    today = date(2026, 5, 31)  # whole month elapsed
    shop_groups = {"shopA": "deptA", "shopB": "deptA"}
    monthly_costs = {("deptA", "2026-05"): 100_000.0}

    # Whole-department daily (both shops) → the denominator.
    full_rows: dict = {}
    full_rows.update(_spread_sales("shopA", date(2026, 5, 1), date(2026, 5, 31), total_sales=100_000))
    full_rows.update(_spread_sales("shopB", date(2026, 5, 1), date(2026, 5, 31), total_sales=100_000))
    full_daily = _daily(full_rows)
    dgs = _dept_dgs(full_daily, shop_groups)

    # Filtered daily: ONLY shopA survives the filter.
    filtered_daily = _daily(
        _spread_sales("shopA", date(2026, 5, 1), date(2026, 5, 31), total_sales=100_000)
    )

    deductions = _compute_fixed_cost_deductions(
        filtered_daily, dgs, date(2026, 5, 1), date(2026, 5, 31),
        shop_groups, monthly_costs, today,
    )
    # 50% share of 100k burden — NOT the whole 100k (that was the bug).
    assert deductions["shopA"] == pytest.approx(50_000.0, rel=1e-6)
    # shopB was filtered out → not in the filtered result.
    assert "shopB" not in deductions


def test_uneven_sales_share_apportions_proportionally():
    """Shop A 70% of group sales → Shop A bears 70% of the group's burden."""
    today = date(2026, 5, 31)  # whole month elapsed
    rows: dict = {}
    rows.update(_spread_sales("shopA", date(2026, 5, 1), date(2026, 5, 31), total_sales=70_000))
    rows.update(_spread_sales("shopB", date(2026, 5, 1), date(2026, 5, 31), total_sales=30_000))
    daily = _daily(rows)

    shop_groups = {"shopA": "deptA", "shopB": "deptA"}
    monthly_costs = {("deptA", "2026-05"): 100_000.0}
    dgs = _dept_dgs(daily, shop_groups)

    deductions = _compute_fixed_cost_deductions(
        daily, dgs, date(2026, 5, 1), date(2026, 5, 31),
        shop_groups, monthly_costs, today,
    )
    # Full month → burden = 100_000. Split 70/30 by sales.
    assert deductions["shopA"] == pytest.approx(70_000, rel=1e-6)
    assert deductions["shopB"] == pytest.approx(30_000, rel=1e-6)


def test_zero_sales_group_in_month_is_not_deducted():
    """User rule: if a fee group has 0 sales in a month within the window,
    don't deduct — i.e. no redistribution to a no-sales month."""
    today = date(2026, 5, 31)
    daily = _daily({})  # no sales at all
    shop_groups = {"shopA": "deptA"}
    monthly_costs = {("deptA", "2026-05"): 100_000.0}
    dgs = _dept_dgs(daily, shop_groups)

    deductions = _compute_fixed_cost_deductions(
        daily, dgs, date(2026, 5, 1), date(2026, 5, 31),
        shop_groups, monthly_costs, today,
    )
    assert deductions == {}  # no shop got any burden


def test_one_shop_with_zero_sales_others_carry_the_full_burden():
    """A 店 0 销售，B 店全部销售 → A 拿不到分摊，B 承担 100%。
    (This is the natural consequence of 'split by sales share' — sales=0
    means share=0, and the rest of the group's burden goes to active shops.)
    """
    today = date(2026, 5, 31)
    rows: dict = {}
    # Only shopB has any sales
    rows.update(_spread_sales("shopB", date(2026, 5, 1), date(2026, 5, 31), total_sales=100_000))
    daily = _daily(rows)

    shop_groups = {"shopA": "deptA", "shopB": "deptA"}
    monthly_costs = {("deptA", "2026-05"): 100_000.0}
    dgs = _dept_dgs(daily, shop_groups)

    deductions = _compute_fixed_cost_deductions(
        daily, dgs, date(2026, 5, 1), date(2026, 5, 31),
        shop_groups, monthly_costs, today,
    )
    assert "shopA" not in deductions  # 0% share → no entry
    assert deductions["shopB"] == pytest.approx(100_000, rel=1e-6)


def test_shop_without_fee_group_gets_no_deduction():
    """A shop tagged with no fee_group_name has no fixed-cost burden,
    regardless of its sales."""
    today = date(2026, 5, 31)
    rows = _spread_sales("shopX", date(2026, 5, 1), date(2026, 5, 31), total_sales=100_000)
    daily = _daily(rows)

    shop_groups = {"shopX": None}     # no group
    monthly_costs = {}                # also no monthly cost configured
    dgs = _dept_dgs(daily, shop_groups)

    deductions = _compute_fixed_cost_deductions(
        daily, dgs, date(2026, 5, 1), date(2026, 5, 31),
        shop_groups, monthly_costs, today,
    )
    assert deductions == {}


def test_monthly_amount_zero_skipped():
    """Future-proofing: an explicitly-zero monthly amount produces no
    deduction (same as 'no row at all')."""
    today = date(2026, 5, 31)
    rows = _spread_sales("shopA", date(2026, 5, 1), date(2026, 5, 31), total_sales=100_000)
    daily = _daily(rows)

    shop_groups = {"shopA": "deptA"}
    monthly_costs = {("deptA", "2026-05"): 0.0}  # explicit zero
    dgs = _dept_dgs(daily, shop_groups)

    deductions = _compute_fixed_cost_deductions(
        daily, dgs, date(2026, 5, 1), date(2026, 5, 31),
        shop_groups, monthly_costs, today,
    )
    assert deductions == {}


def test_cross_month_range_per_month_independent():
    """Query 2026-04 + 2026-05 with different monthly amounts.
    April: full 30 days, May: 26 of 31 days (today = 5/26).
    Burdens compute per-day with each month's own daily_cost, summed per shop.
    """
    today = date(2026, 5, 26)
    rows: dict = {}
    rows.update(_spread_sales("shopA", date(2026, 4, 1), date(2026, 4, 30), total_sales=300))
    rows.update(_spread_sales("shopA", date(2026, 5, 1), today, total_sales=260))
    daily = _daily(rows)

    shop_groups = {"shopA": "deptA"}
    monthly_costs = {
        ("deptA", "2026-04"): 60_000.0,    # April: 60k / 30 × 30 = 60_000
        ("deptA", "2026-05"): 100_000.0,   # May:   100k / 31 × 26 ≈ 83870.97
    }
    dgs = _dept_dgs(daily, shop_groups)

    deductions = _compute_fixed_cost_deductions(
        daily, dgs, date(2026, 4, 1), date(2026, 5, 31),
        shop_groups, monthly_costs, today,
    )
    expected_apr = 60_000.0
    expected_may = 100_000 / 31 * 26
    assert deductions["shopA"] == pytest.approx(expected_apr + expected_may, rel=1e-6)


def test_future_days_in_range_contribute_zero():
    """Query 2026-05 + 2026-06 with today=5/26. Days after today don't
    count (已发生天数 only) — June has no elapsed days here."""
    today = date(2026, 5, 26)
    rows: dict = {}
    rows.update(_spread_sales("shopA", date(2026, 5, 1), today, total_sales=260))
    # No June sales (those days haven't happened yet).
    daily = _daily(rows)

    shop_groups = {"shopA": "deptA"}
    monthly_costs = {
        ("deptA", "2026-05"): 100_000.0,
        ("deptA", "2026-06"): 100_000.0,   # set but shouldn't apply yet
    }
    dgs = _dept_dgs(daily, shop_groups)

    deductions = _compute_fixed_cost_deductions(
        daily, dgs, date(2026, 5, 1), date(2026, 6, 30),
        shop_groups, monthly_costs, today,
    )
    # Only May (through the 26th) burden applies; later days skipped.
    assert deductions["shopA"] == pytest.approx(100_000 / 31 * 26, rel=1e-6)


def test_sales_after_today_are_skipped():
    """Even if a row exists for a day after `today`, it must not be charged
    (guards against stray future-dated data)."""
    today = date(2026, 5, 10)
    rows = _spread_sales("shopA", date(2026, 5, 1), date(2026, 5, 31), total_sales=310)
    daily = _daily(rows)

    shop_groups = {"shopA": "deptA"}
    monthly_costs = {("deptA", "2026-05"): 31_000.0}  # 1000/day
    dgs = _dept_dgs(daily, shop_groups)

    deductions = _compute_fixed_cost_deductions(
        daily, dgs, date(2026, 5, 1), date(2026, 5, 31),
        shop_groups, monthly_costs, today,
    )
    # Only 5/1..5/10 = 10 days × 1000 = 10000 (sole shop → 100% share).
    assert deductions["shopA"] == pytest.approx(10_000.0, rel=1e-6)


def test_subwindow_inside_month_uses_window_days_only():
    """Trend-chart-style: a single-day bucket should get 1/days_in_month
    of the monthly burden, not the full month's."""
    today = date(2026, 5, 31)
    rows = _spread_sales("shopA", date(2026, 5, 15), date(2026, 5, 15), total_sales=100)
    daily = _daily(rows)

    shop_groups = {"shopA": "deptA"}
    monthly_costs = {("deptA", "2026-05"): 31_000.0}  # round number: 1000/day
    dgs = _dept_dgs(daily, shop_groups)

    deductions = _compute_fixed_cost_deductions(
        daily, dgs, date(2026, 5, 15), date(2026, 5, 15),
        shop_groups, monthly_costs, today,
    )
    assert deductions["shopA"] == pytest.approx(1_000.0, rel=1e-6)


def test_two_groups_each_apportions_independently():
    """部门A 和 部门B 各自一套规则，互不干扰。"""
    today = date(2026, 5, 31)
    rows: dict = {}
    rows.update(_spread_sales("shopA", date(2026, 5, 1), date(2026, 5, 31), total_sales=100_000))
    rows.update(_spread_sales("shopB", date(2026, 5, 1), date(2026, 5, 31), total_sales=50_000))
    daily = _daily(rows)

    shop_groups = {"shopA": "deptA", "shopB": "deptB"}
    monthly_costs = {
        ("deptA", "2026-05"): 60_000.0,
        ("deptB", "2026-05"): 40_000.0,
    }
    dgs = _dept_dgs(daily, shop_groups)

    deductions = _compute_fixed_cost_deductions(
        daily, dgs, date(2026, 5, 1), date(2026, 5, 31),
        shop_groups, monthly_costs, today,
    )
    # Each shop is the sole member of its group → bears 100% of its group cost.
    assert deductions["shopA"] == pytest.approx(60_000.0, rel=1e-6)
    assert deductions["shopB"] == pytest.approx(40_000.0, rel=1e-6)


def test_trend_buckets_sum_to_overview_for_a_group():
    """Sum of per-day bucket burdens equals the overview burden for the same
    window — now EXACT (not just per-group) because both are plain sums of
    the identical per-day atoms."""
    today = date(2026, 5, 26)
    # One shop, sales every day from 5/1 to 5/26.
    rows = _spread_sales("shopA", date(2026, 5, 1), today, total_sales=260)
    daily = _daily(rows)

    shop_groups = {"shopA": "deptA"}
    monthly_costs = {("deptA", "2026-05"): 100_000.0}
    dgs = _dept_dgs(daily, shop_groups)

    overview = _compute_fixed_cost_deductions(
        daily, dgs, date(2026, 5, 1), date(2026, 5, 31),
        shop_groups, monthly_costs, today,
    )
    # Sum across daily buckets (mimics what get_trend does).
    bucket_sum = 0.0
    cur = date(2026, 5, 1)
    while cur <= date(2026, 5, 31):
        b = _compute_fixed_cost_deductions(
            daily, dgs, cur, cur, shop_groups, monthly_costs, today,
        )
        bucket_sum += b.get("shopA", 0.0)
        cur += timedelta(days=1)

    assert bucket_sum == pytest.approx(overview["shopA"], rel=1e-6)


# ---------------------------------------------------------------------------
# _kpis_from_per_shop — verify 公司利润率 plumbing
# ---------------------------------------------------------------------------

def test_kpis_company_profit_rate_uses_fixed_cost_and_tax():
    """公司利润率 = (profit − fixed_cost − sales × tax) / sales × 100."""
    per_shop = {
        "shopA": _row(sales=100_000, profit=30_000),
    }
    tax_rates = {"shopA": 0.05}     # 5% tax fee
    fixed_costs = {"shopA": 10_000} # 10k apportioned fixed cost

    kpi = _kpis_from_per_shop(per_shop, tax_rates, fixed_costs)
    # adj_profit = 30000 - 10000 - 100000*0.05 = 30000 - 10000 - 5000 = 15000
    # rate = 15000 / 100000 * 100 = 15%
    assert kpi["companyProfitRate"] == pytest.approx(15.0, rel=1e-6)
    # Operating profit rate is unaffected by tax / fixed cost.
    assert kpi["profitRate"] == pytest.approx(30.0, rel=1e-6)
    # Sales / profit pass through unchanged.
    assert kpi["sales"] == 100_000
    assert kpi["profit"] == 30_000


def test_kpis_no_fixed_cost_no_tax_yields_profit_rate():
    """When no fixed-cost and no tax, 公司利润率 == 经营利润率."""
    per_shop = {"shopA": _row(sales=1000, profit=200)}
    kpi = _kpis_from_per_shop(per_shop, {}, {})
    assert kpi["companyProfitRate"] == pytest.approx(20.0, rel=1e-6)
    assert kpi["profitRate"] == pytest.approx(20.0, rel=1e-6)


def test_kpis_empty_input_is_all_zeros():
    """Defensive: no shops in window → all KPIs zero, no div-by-zero."""
    kpi = _kpis_from_per_shop({}, {}, {})
    assert kpi["sales"] == 0
    assert kpi["companyProfitRate"] == 0
    assert kpi["profitRate"] == 0
