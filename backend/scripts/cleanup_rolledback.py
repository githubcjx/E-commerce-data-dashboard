"""Find and (optionally) delete sales_records that still carry the
batch_id of a rolled-back batch.

Why this can happen: when an import upserts an existing row, the old
row's batch_id gets updated to the NEW batch's id. So if you later roll
back the new batch, you delete rows that originally came from the old
batch — but if you roll back the OLD batch, those re-tagged rows aren't
touched. The result: some rows linger with batch_id pointing at a
rolled-back batch instead of being gone.

Usage (from inside the backend container):
    # 1) Dry-run — count & summarize without touching anything
    python -m scripts.cleanup_rolledback --tenant <code>

    # 2) Actually delete the orphans
    python -m scripts.cleanup_rolledback --tenant <code> --apply

    # 3) Inspect across all tenants (platform-wide audit)
    python -m scripts.cleanup_rolledback --all
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import and_, delete, func, select

from app.db import SessionLocal
from app.models import ImportBatch, SalesRecord, Tenant


async def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup orphan rows from rolled-back batches")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--tenant", help="Tenant code (e.g. acme)")
    g.add_argument("--all", action="store_true", help="Scan every tenant")
    parser.add_argument("--apply", action="store_true",
                        help="Actually delete the orphans. Without this, dry-run only.")
    args = parser.parse_args()

    async with SessionLocal() as session:
        if args.all:
            tenants = (await session.execute(select(Tenant))).scalars().all()
        else:
            t = (await session.execute(
                select(Tenant).where(Tenant.code == args.tenant)
            )).scalar_one_or_none()
            if not t:
                print(f"❌ Tenant code {args.tenant!r} not found")
                return
            tenants = [t]

        total_orphans = 0
        for t in tenants:
            print(f"\n=== {t.code} · {t.name} (id={t.id}) ===")

            # Find every rolled-back batch in this tenant.
            rb = (await session.execute(
                select(ImportBatch.id, ImportBatch.filename, ImportBatch.created_at)
                .where(ImportBatch.tenant_id == t.id, ImportBatch.status == "rolled_back")
                .order_by(ImportBatch.created_at.asc())
            )).all()
            if not rb:
                print("  ✓ 该企业没有 rolled_back 状态的批次")
                continue

            rb_ids = [bid for bid, _, _ in rb]
            # Count orphan rows + show per-batch breakdown.
            rows = (await session.execute(
                select(
                    SalesRecord.batch_id,
                    func.count(SalesRecord.id),
                    func.coalesce(func.sum(SalesRecord.profit), 0),
                )
                .where(SalesRecord.tenant_id == t.id, SalesRecord.batch_id.in_(rb_ids))
                .group_by(SalesRecord.batch_id)
            )).all()
            orphan_n = sum(c for _, c, _ in rows)
            orphan_profit = sum(float(p or 0) for _, _, p in rows)
            print(f"  发现 {len(rb)} 个已回滚批次，残留行数: {orphan_n}, "
                  f"残留利润额总和: {orphan_profit:,.2f}")
            if rows:
                print(f"  {'批次ID':<10} {'文件名':<40} {'残留行':>10} {'残留利润额':>20}")
                meta = {bid: (fn, ct) for bid, fn, ct in rb}
                for bid, c, p in rows:
                    fname = (meta.get(bid, ("?", None))[0] or "")[:40]
                    print(f"  {bid[:8]:<10} {fname:<40} {c:>10,} {float(p or 0):>20,.2f}")

            total_orphans += orphan_n

            if args.apply and orphan_n > 0:
                res = await session.execute(
                    delete(SalesRecord)
                    .where(SalesRecord.tenant_id == t.id, SalesRecord.batch_id.in_(rb_ids))
                )
                await session.commit()
                print(f"  ✓ 已删除 {res.rowcount or 0} 行残留数据")

        print()
        if args.apply:
            print(f"✓ 完成，全部删除残留数据。")
        else:
            print(f"☑ Dry-run 结束。如需真删，加 --apply 重跑。")
            print(f"  全部企业残留总行数: {total_orphans:,}")


if __name__ == "__main__":
    asyncio.run(main())
