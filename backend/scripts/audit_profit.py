"""Direct SQL audit: sum sales_records.profit for a tenant + filters.

Reproduces the dashboard's 利润额 number with no business logic in the
way — just raw SUM over the same WHERE clauses. Use this to verify
what the system has vs what the Excel source says.

Usage (from inside the backend container):
    python -m scripts.audit_profit --tenant <code> \
        --start 2026-05-01 --end 2026-05-31

    Optional filters (comma-separated, mirrors dashboard's multi-selects):
        --shop A,B,C
        --owner 张三,李四
        --category 服装,鞋

    Optional inspection:
        --show-rows 20      Print the top-20 highest-profit raw rows
        --batches           List all import batches (active + rolled_back)
                             for this tenant before the audit

Examples:
    # Quick "what does the dashboard see for 2026-05?"
    python -m scripts.audit_profit --tenant acme --start 2026-05-01 --end 2026-05-31

    # Reproduce a specific dashboard filter combination
    python -m scripts.audit_profit --tenant acme \
        --start 2026-05-01 --end 2026-05-31 \
        --shop SHOP-A,SHOP-B --owner 张三

    # Also show top 30 raw rows
    python -m scripts.audit_profit --tenant acme \
        --start 2026-05-01 --end 2026-05-31 --show-rows 30
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date as date_cls

from sqlalchemy import and_, func, select

from app.db import SessionLocal
from app.models import ImportBatch, SalesRecord, Tenant


def _parse_csv(s: str | None) -> list[str] | None:
    if not s:
        return None
    return [x.strip() for x in s.split(",") if x.strip()]


def _parse_date(s: str) -> date_cls:
    y, m, d = map(int, s.split("-"))
    return date_cls(y, m, d)


def _fmt_money(v) -> str:
    return f"{float(v or 0):>20,.2f}"


async def _list_all_batches(session, tenant_id: int) -> None:
    """All ImportBatch rows for this tenant, oldest first."""
    rows = (await session.execute(
        select(ImportBatch)
        .where(ImportBatch.tenant_id == tenant_id)
        .order_by(ImportBatch.created_at.asc())
    )).scalars().all()
    print("=== 该企业的所有导入批次 ===")
    print(f"{'状态':<12} {'创建时间':<22} {'文件名':<40} {'总':>8} {'新增':>8} {'更新':>8}")
    for b in rows:
        ts = b.created_at.strftime("%Y-%m-%d %H:%M:%S")
        fname = (b.filename or "")[:40]
        print(f"{b.status:<12} {ts:<22} {fname:<40} "
              f"{b.total_rows:>8} {b.inserted_rows:>8} {b.updated_rows:>8}")
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Audit 利润额 SUM by tenant + filters")
    parser.add_argument("--tenant", required=True, help="Tenant code (e.g. acme)")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--shop", help="Shop codes (comma-separated)")
    parser.add_argument("--owner", help="Owner names (comma-separated)")
    parser.add_argument("--category", help="Categories (comma-separated)")
    parser.add_argument("--show-rows", type=int, default=0,
                        help="Print this many top-profit raw rows")
    parser.add_argument("--batches", action="store_true",
                        help="List all import batches for the tenant up-front")
    args = parser.parse_args()

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    shops = _parse_csv(args.shop)
    owners = _parse_csv(args.owner)
    cats = _parse_csv(args.category)

    async with SessionLocal() as session:
        tenant = (await session.execute(
            select(Tenant).where(Tenant.code == args.tenant)
        )).scalar_one_or_none()
        if not tenant:
            print(f"❌ Tenant code {args.tenant!r} not found")
            return

        print(f"=== 审计参数 ===")
        print(f"企业:       {tenant.code} · {tenant.name} (id={tenant.id})")
        print(f"时间范围:    {start.isoformat()} ~ {end.isoformat()}")
        print(f"店铺筛选:    {shops or '全部'}")
        print(f"负责人筛选:  {owners or '全部'}")
        print(f"类目筛选:    {cats or '全部'}")
        print()

        if args.batches:
            await _list_all_batches(session, tenant.id)

        # Common WHERE clauses — used by every query below to stay consistent.
        conds = [
            SalesRecord.tenant_id == tenant.id,
            SalesRecord.date >= start,
            SalesRecord.date <= end,
        ]
        if shops:
            conds.append(SalesRecord.shop_code.in_(shops))
        if owners:
            conds.append(SalesRecord.owner.in_(owners))
        if cats:
            conds.append(SalesRecord.category.in_(cats))

        # ----- Total -----
        row = (await session.execute(
            select(
                func.coalesce(func.sum(SalesRecord.profit), 0),
                func.coalesce(func.sum(SalesRecord.income_total), 0),
                func.coalesce(func.sum(SalesRecord.actual_income), 0),
                func.count(SalesRecord.id),
            ).where(and_(*conds))
        )).one()
        profit, income, actual, n = row
        sales = float(income or 0) or float(actual or 0)

        print(f"=== 汇总 ===")
        print(f"匹配行数:    {n:>20,}")
        print(f"利润额 SUM:  {_fmt_money(profit)}    ← 这是看板「利润额」KPI 的值")
        print(f"销售额 SUM:  {_fmt_money(sales)}    (income_total 优先，否则 actual_income)")
        if sales:
            print(f"经营利润率:  {float(profit) / sales * 100:.4f} %")
        print()

        # ----- By shop -----
        rows = (await session.execute(
            select(
                SalesRecord.shop_code,
                SalesRecord.shop_name,
                func.coalesce(func.sum(SalesRecord.profit), 0),
                func.count(SalesRecord.id),
            )
            .where(and_(*conds))
            .group_by(SalesRecord.shop_code, SalesRecord.shop_name)
            .order_by(func.sum(SalesRecord.profit).desc())
        )).all()
        if rows:
            print(f"=== 按店铺拆分 ===")
            print(f"{'店铺':<40} {'行数':>8} {'利润额':>20}")
            for code, name, p, c in rows:
                label = (f"{name or '-'} ({code or '-'})")[:40]
                print(f"{label:<40} {c:>8,} {_fmt_money(p)}")
            print()

        # ----- By category -----
        rows = (await session.execute(
            select(
                SalesRecord.category,
                func.coalesce(func.sum(SalesRecord.profit), 0),
                func.count(SalesRecord.id),
            )
            .where(and_(*conds))
            .group_by(SalesRecord.category)
            .order_by(func.sum(SalesRecord.profit).desc())
        )).all()
        if rows:
            print(f"=== 按类目拆分 ===")
            print(f"{'类目':<30} {'行数':>8} {'利润额':>20}")
            for cat, p, c in rows:
                label = (cat or '(空)')[:30]
                print(f"{label:<30} {c:>8,} {_fmt_money(p)}")
            print()

        # ----- By owner -----
        rows = (await session.execute(
            select(
                SalesRecord.owner,
                func.coalesce(func.sum(SalesRecord.profit), 0),
                func.count(SalesRecord.id),
            )
            .where(and_(*conds))
            .group_by(SalesRecord.owner)
            .order_by(func.sum(SalesRecord.profit).desc())
        )).all()
        if rows:
            print(f"=== 按负责人拆分 ===")
            print(f"{'负责人':<20} {'行数':>8} {'利润额':>20}")
            for owner, p, c in rows:
                label = (owner or '(空)')[:20]
                print(f"{label:<20} {c:>8,} {_fmt_money(p)}")
            print()

        # ----- By import batch -----
        # Useful for spotting "where did this row come from" + the
        # rollback/upsert interaction we discussed.
        batch_rows = (await session.execute(
            select(
                SalesRecord.batch_id,
                func.coalesce(func.sum(SalesRecord.profit), 0),
                func.count(SalesRecord.id),
            )
            .where(and_(*conds))
            .group_by(SalesRecord.batch_id)
            .order_by(func.sum(SalesRecord.profit).desc())
        )).all()
        if batch_rows:
            print(f"=== 按导入批次拆分（数据当前归属哪个批次）===")
            print(f"{'批次ID':<10} {'状态':<14} {'文件名':<40} {'行数':>8} {'利润额':>20}")
            for batch_id, p, c in batch_rows:
                if batch_id:
                    b = (await session.execute(
                        select(ImportBatch).where(ImportBatch.id == batch_id)
                    )).scalar_one_or_none()
                    fname = (b.filename if b else "(批次记录已删)")[:40]
                    status = b.status if b else "?"
                    short_id = batch_id[:8]
                else:
                    fname = "(无 batch_id)"
                    status = "?"
                    short_id = "-"
                print(f"{short_id:<10} {status:<14} {fname:<40} {c:>8,} {_fmt_money(p)}")
            print()
            # Tip-style note. If a 'rolled_back' batch appears here, it
            # means the batch was rolled back but some rows still carry
            # its batch_id (likely shared with a prior batch via upsert).
            statuses = set()
            for bid, _, _ in batch_rows:
                if not bid:
                    continue
                b = (await session.execute(
                    select(ImportBatch).where(ImportBatch.id == bid)
                )).scalar_one_or_none()
                if b:
                    statuses.add(b.status)
            if "rolled_back" in statuses:
                print("⚠️  上面出现了 status=rolled_back 的批次仍有数据 — 这是"
                      "upsert+rollback 的副作用，参考之前讨论的 batch_id bug。")
                print()

        # ----- Optional raw rows -----
        if args.show_rows > 0:
            rows = (await session.execute(
                select(SalesRecord)
                .where(and_(*conds))
                .order_by(SalesRecord.profit.desc())
                .limit(args.show_rows)
            )).scalars().all()
            print(f"=== 利润额最高的 {len(rows)} 条原始记录 ===")
            print(f"{'日期':<12} {'店铺':<20} {'分类':<24} {'负责人':<10} {'利润额':>14}")
            for r in rows:
                print(f"{r.date.isoformat():<12} {(r.shop_code or '-')[:20]:<20} "
                      f"{(r.sku or '-')[:24]:<24} {(r.owner or '-')[:10]:<10} "
                      f"{float(r.profit or 0):>14,.2f}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
