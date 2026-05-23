"""Wipe all sales data + import history for a tenant. Use this when you
want to re-import from scratch (because previous imports got tangled and
you'd rather start clean than untangle).

DOES NOT TOUCH:
  - Tenants, users, departments, shops, user_departments
  - Tenants stay configured. Shops stay configured (with their fee
    settings). After re-import the same shop_codes will re-populate
    automatically and keep their existing fee config.

DOES DELETE:
  - All sales_records for the tenant
  - All import_batches for the tenant

Usage:
    # Dry-run preview
    python -m scripts.purge_tenant_data --tenant <code>

    # Actually delete (requires --yes to bypass the confirm prompt)
    python -m scripts.purge_tenant_data --tenant <code> --apply --yes
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import delete, func, select

from app.db import SessionLocal
from app.models import ImportBatch, SalesRecord, Tenant


async def main() -> None:
    parser = argparse.ArgumentParser(description="Wipe sales data + import history for a tenant")
    parser.add_argument("--tenant", required=True, help="Tenant code (e.g. acme)")
    parser.add_argument("--apply", action="store_true",
                        help="Actually delete. Without this, dry-run only.")
    parser.add_argument("--yes", action="store_true",
                        help="Skip interactive confirmation (combine with --apply)")
    args = parser.parse_args()

    async with SessionLocal() as session:
        t = (await session.execute(
            select(Tenant).where(Tenant.code == args.tenant)
        )).scalar_one_or_none()
        if not t:
            print(f"❌ Tenant code {args.tenant!r} not found")
            return

        # Pre-flight counts.
        n_records = await session.scalar(
            select(func.count(SalesRecord.id)).where(SalesRecord.tenant_id == t.id)
        )
        n_batches = await session.scalar(
            select(func.count(ImportBatch.id)).where(ImportBatch.tenant_id == t.id)
        )

        print(f"=== 目标企业 ===")
        print(f"  {t.code} · {t.name} (id={t.id})")
        print()
        print(f"=== 将删除 ===")
        print(f"  sales_records:  {n_records:,} 行")
        print(f"  import_batches: {n_batches:,} 条")
        print()
        print(f"=== 保留不动 ===")
        print(f"  users / departments / shops / 配置")

        if not args.apply:
            print(f"\n☑ Dry-run。如需真删，加 --apply --yes 重跑。")
            return

        if not args.yes:
            confirm = input(f"\n⚠️  最终确认：把企业 [{t.code}] 的 {n_records:,} 行销售数据"
                            f"和 {n_batches:,} 条导入记录全部删除？[y/N]: ")
            if confirm.strip().lower() not in ("y", "yes"):
                print("已取消。")
                return

        # Cascade order: records first, then batches.
        await session.execute(
            delete(SalesRecord).where(SalesRecord.tenant_id == t.id)
        )
        await session.execute(
            delete(ImportBatch).where(ImportBatch.tenant_id == t.id)
        )
        await session.commit()
        print(f"\n✓ 已清空企业 [{t.code}] 的所有销售数据和导入记录。")
        print(f"  现在可以重新打开「导入」页上传原始 Excel 重建数据。")


if __name__ == "__main__":
    asyncio.run(main())
