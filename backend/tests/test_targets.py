"""人员目标完成情况 — service + router + guard tests.

Unlike test_apportionment (pure dict math), the feature here is genuinely
DB-backed (per-owner SQL aggregates), so these run against an in-memory
SQLite engine — the dev/test half of the dual-DB design. Each test spins up
its OWN fresh engine (StaticPool → one shared :memory: DB) so they're fully
isolated, and drives the async service/endpoints via asyncio.run, keeping the
suite free of any pytest-asyncio dependency.

Layers covered:
  - calendar/pure helpers (month bounds, next month, last workday, completion)
  - service queries (actuals: tenant/month/today isolation, income fallback,
    data-scope; all_owners; save upsert; ranking; reminder)
  - router wiring (tenant resolution, scope plumbing via effective_scope_owners,
    bad-month rejection, platform-admin needs tenant_id)
  - auth guards (only super edits; plain admin/user rejected)
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    PerformanceTarget, ROLE_PLATFORM_ADMIN, ROLE_TENANT_ADMIN,
    ROLE_TENANT_SUPER_ADMIN, ROLE_TENANT_USER, SalesRecord, User,
)
from app.schemas import TargetSave, TargetSaveItem
from app.services import target_service as t
from app.api.targets import (
    list_targets, save_targets, my_targets,
    ranking as ep_ranking, reminder as ep_reminder,
)
from app.security import require_backend_access, require_tenant_super_admin


# ---------------------------------------------------------------------------
# Infra
# ---------------------------------------------------------------------------

async def _make_session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return AsyncSession(engine)


_SKU = [0]


def _sale(**kw) -> SalesRecord:
    """One sales row. Auto-unique sku so the (tenant,shop,date,sku) key never
    collides regardless of what the test sets."""
    _SKU[0] += 1
    base = dict(shop_code="S1", sku=f"k{_SKU[0]}", actual_income=0)
    base.update(kw)
    return SalesRecord(**base)


async def _seed(session: AsyncSession, rows) -> None:
    for r in rows:
        session.add(r)
    await session.commit()


def _su(tenant_id=1):
    return User(id=1, tenant_id=tenant_id, username="s", password_hash="x",
                role=ROLE_TENANT_SUPER_ADMIN)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_month_bounds_and_next_month():
    assert t.month_bounds("2026-06") == (date(2026, 6, 1), date(2026, 6, 30))
    assert t.month_bounds("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert t.next_month("2026-06") == "2026-07"
    assert t.next_month("2026-12") == "2027-01"  # year wrap


def test_last_workday_skips_weekends():
    # 2026-05-31 is a Sunday → last workday is Fri 2026-05-29.
    assert t.last_workday_of_month(2026, 5) == date(2026, 5, 29)
    # 2026-08-31 is a Monday → itself.
    assert t.last_workday_of_month(2026, 8) == date(2026, 8, 31)
    # Whatever the month, the result is never a weekend.
    for m in range(1, 13):
        assert t.last_workday_of_month(2026, m).weekday() < 5


def test_completion_math():
    assert t._completion(900, 1000) == 0.9
    assert t._completion(1250, 1000) == 1.25       # may exceed 100%
    assert t._completion(0, 1000) == 0.0           # 0 actual is a real 0%, not None
    assert t._completion(150, 0) is None           # no denominator → None
    assert t._completion(150, None) is None


def test_progress_row_shapes():
    # No target row → completions None, has_target False, rate still computed.
    r = t.progress_row("A", None, {"sales": 500, "profit": 80})
    assert r["sales_completion"] is None and r["profit_completion"] is None
    assert r["has_target"] is False
    assert r["actual_profit_rate"] == 80 / 500
    # Zero sales → no division-by-zero, rate is 0.0.
    r2 = t.progress_row("B", None, {})
    assert r2["actual_profit_rate"] == 0.0


# ---------------------------------------------------------------------------
# Service: owner_actuals
# ---------------------------------------------------------------------------

def test_owner_actuals_tenant_and_month_isolation():
    async def scenario():
        async with await _make_session() as s:
            await _seed(s, [
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="A", income_total=600, profit=120),
                _sale(tenant_id=1, date=date(2026, 6, 3), owner="A", income_total=300, profit=30),
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="B", income_total=500, profit=80),
                _sale(tenant_id=1, date=date(2026, 7, 1), owner="A", income_total=999, profit=999),  # other month
                _sale(tenant_id=2, date=date(2026, 6, 2), owner="Z", income_total=111, profit=11),    # other tenant
            ])
            acts = await t.owner_actuals(s, 1, "2026-06", date(2026, 6, 30))
            assert set(acts) == {"A", "B"}
            assert acts["A"] == {"sales": 900.0, "profit": 150.0}  # summed, July excluded
            assert acts["B"] == {"sales": 500.0, "profit": 80.0}
    asyncio.run(scenario())


def test_owner_actuals_today_cutoff():
    async def scenario():
        async with await _make_session() as s:
            await _seed(s, [
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="A", income_total=100, profit=10),
                _sale(tenant_id=1, date=date(2026, 6, 10), owner="A", income_total=900, profit=90),  # after today
            ])
            # today = 06-04 → only the 06-02 row counts (已发生天数).
            acts = await t.owner_actuals(s, 1, "2026-06", date(2026, 6, 4))
            assert acts["A"] == {"sales": 100.0, "profit": 10.0}
    asyncio.run(scenario())


def test_owner_actuals_income_fallback():
    async def scenario():
        async with await _make_session() as s:
            # income_total = 0 → sales falls back to actual_income (dashboard parity).
            await _seed(s, [
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="A", income_total=0, actual_income=500, profit=50),
            ])
            acts = await t.owner_actuals(s, 1, "2026-06", date(2026, 6, 30))
            assert acts["A"]["sales"] == 500.0
    asyncio.run(scenario())


def test_owner_actuals_data_scope():
    async def scenario():
        async with await _make_session() as s:
            await _seed(s, [
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="A", income_total=100, profit=10),
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="B", income_total=200, profit=20),
            ])
            today = date(2026, 6, 30)
            assert set(await t.owner_actuals(s, 1, "2026-06", today, scope_owners=None)) == {"A", "B"}
            assert set(await t.owner_actuals(s, 1, "2026-06", today, scope_owners=["A"])) == {"A"}
            assert await t.owner_actuals(s, 1, "2026-06", today, scope_owners=[]) == {}
    asyncio.run(scenario())


def test_all_owners():
    async def scenario():
        async with await _make_session() as s:
            await _seed(s, [
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="B", income_total=1),
                _sale(tenant_id=1, date=date(2026, 6, 3), owner="A", income_total=1),
                _sale(tenant_id=1, date=date(2026, 6, 4), owner="A", income_total=1),  # dup owner
                _sale(tenant_id=1, date=date(2026, 6, 5), owner=None, income_total=1),  # null skipped
                _sale(tenant_id=2, date=date(2026, 6, 2), owner="Z", income_total=1),   # other tenant
            ])
            assert await t.all_owners(s, 1) == ["A", "B"]              # distinct + sorted
            assert await t.all_owners(s, 1, scope_owners=["B"]) == ["B"]
            assert await t.all_owners(s, 1, scope_owners=[]) == []
    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Service: save (upsert), ranking, reminder
# ---------------------------------------------------------------------------

def test_save_targets_upsert_no_duplicate():
    async def scenario():
        async with await _make_session() as s:
            await t.save_targets(s, 1, "2026-06", [
                TargetSaveItem(owner="A", target_sales=1000, target_profit=200, target_profit_rate=0.2),
                TargetSaveItem(owner="B", target_sales=500, target_profit=100, target_profit_rate=0.2),
            ])
            # Re-save A with new numbers — must UPDATE in place, not insert a 2nd row.
            await t.save_targets(s, 1, "2026-06", [
                TargetSaveItem(owner="A", target_sales=900, target_profit=150, target_profit_rate=0.18),
            ])
            total = (await s.execute(
                select(PerformanceTarget).where(PerformanceTarget.tenant_id == 1)
            )).scalars().all()
            assert len(total) == 2
            tmap = await t.targets_map(s, 1, "2026-06")
            assert float(tmap["A"].target_sales) == 900.0
            assert float(tmap["A"].target_profit_rate) == 0.18
    asyncio.run(scenario())


def test_get_ranking_sorts_and_excludes_untargeted():
    async def scenario():
        async with await _make_session() as s:
            await _seed(s, [
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="A", income_total=1250, profit=200),
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="B", income_total=1000, profit=80),
                # C has a target but NO sales → completion 0.0 (ranked last, not dropped).
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="D", income_total=999, profit=999),  # D sells, no target
            ])
            await t.save_targets(s, 1, "2026-06", [
                TargetSaveItem(owner="A", target_sales=1000, target_profit=200, target_profit_rate=0.2),
                TargetSaveItem(owner="B", target_sales=1000, target_profit=100, target_profit_rate=0.1),
                TargetSaveItem(owner="C", target_sales=1000, target_profit=100, target_profit_rate=0.1),
            ])
            rank = await t.get_ranking(s, 1, "2026-06", date(2026, 6, 30))
            sales_order = [r["owner"] for r in rank["sales_ranking"]]
            assert sales_order == ["A", "B", "C"]   # 1.25 > 1.0 > 0.0 ; D excluded (no target)
            profit_order = [r["owner"] for r in rank["profit_ranking"]]
            assert profit_order == ["A", "B", "C"]  # A 1.0, B 0.8, C 0.0
    asyncio.run(scenario())


def test_reminder_lifecycle():
    async def scenario():
        async with await _make_session() as s:
            await _seed(s, [
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="A", income_total=1),
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="B", income_total=1),
            ])
            # Before the last workday → quiet.
            assert (await t.get_reminder(s, 1, date(2026, 6, 4)))["should_remind"] is False
            # On the last workday (06-30) with next month unset → fire for both.
            r = await t.get_reminder(s, 1, date(2026, 6, 30))
            assert r["should_remind"] is True
            assert r["year_month"] == "2026-07"
            assert r["missing_count"] == 2
            # Fill next month for everyone → quiet again.
            await t.save_targets(s, 1, "2026-07", [
                TargetSaveItem(owner="A", target_sales=1, target_profit=1, target_profit_rate=0.1),
                TargetSaveItem(owner="B", target_sales=1, target_profit=1, target_profit_rate=0.1),
            ])
            assert (await t.get_reminder(s, 1, date(2026, 6, 30)))["should_remind"] is False
    asyncio.run(scenario())


def test_reminder_quiet_when_no_owners():
    async def scenario():
        async with await _make_session() as s:
            # No sales at all → nobody to set targets for → never nag.
            assert (await t.get_reminder(s, 1, date(2026, 6, 30)))["should_remind"] is False
    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Router wiring
# ---------------------------------------------------------------------------

def test_router_save_list_me_flow():
    async def scenario():
        async with await _make_session() as s:
            await _seed(s, [
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="A", income_total=1000, profit=200),
                _sale(tenant_id=1, date=date(2026, 6, 2), owner="B", income_total=500, profit=80),
            ])
            su = _su()
            await save_targets(
                body=TargetSave(year_month="2026-06", items=[
                    TargetSaveItem(owner="A", target_sales=800, target_profit=160, target_profit_rate=0.2),
                    TargetSaveItem(owner="B", target_sales=1000, target_profit=100, target_profit_rate=0.2),
                ]),
                tenant_id=None, actor=su, db=s,
            )
            listed = await list_targets(year_month="2026-06", tenant_id=None, actor=su, db=s)
            rows = {r["owner"]: r for r in listed.data["rows"]}
            assert rows["A"]["sales_completion"] == 1000 / 800
            assert rows["B"]["profit_completion"] == 80 / 100

            # 普通用户 scoped to A → /me returns only A (data isolation plumbed).
            uu = User(id=2, tenant_id=1, username="u", password_hash="x",
                      role=ROLE_TENANT_USER, data_scope_owners=["A"])
            mine = await my_targets(year_month="2026-06", user=uu, db=s)
            assert [r["owner"] for r in mine.data["rows"]] == ["A"]
    asyncio.run(scenario())


def test_router_rejects_bad_month_and_missing_tenant():
    async def scenario():
        async with await _make_session() as s:
            su = _su()
            with pytest.raises(HTTPException):
                await list_targets(year_month="2026/06", tenant_id=None, actor=su, db=s)
            # platform_admin must pass tenant_id (no own tenant).
            pa = User(id=9, tenant_id=None, username="cjx", password_hash="x",
                      role=ROLE_PLATFORM_ADMIN)
            with pytest.raises(HTTPException):
                await list_targets(year_month="2026-06", tenant_id=None, actor=pa, db=s)
            # reminder is gracefully quiet for platform_admin without a tenant.
            rem = await ep_reminder(tenant_id=None, actor=pa, db=s)
            assert rem.data["should_remind"] is False
    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Auth guards (the "仅超级管理员可编辑" decision)
# ---------------------------------------------------------------------------

def test_guards_only_super_edits():
    user = User(id=1, tenant_id=1, username="u", password_hash="x", role=ROLE_TENANT_USER)
    admin = User(id=2, tenant_id=1, username="a", password_hash="x", role=ROLE_TENANT_ADMIN)
    super_ = User(id=3, tenant_id=1, username="s", password_hash="x", role=ROLE_TENANT_SUPER_ADMIN)

    # Edit guard: only super (and platform) — plain admin & user rejected.
    assert asyncio.run(require_tenant_super_admin(super_)) is super_
    with pytest.raises(HTTPException):
        asyncio.run(require_tenant_super_admin(admin))
    with pytest.raises(HTTPException):
        asyncio.run(require_tenant_super_admin(user))

    # View guard (list/ranking): any backend admin ok, plain user rejected.
    assert asyncio.run(require_backend_access(admin)) is admin
    with pytest.raises(HTTPException):
        asyncio.run(require_backend_access(user))
