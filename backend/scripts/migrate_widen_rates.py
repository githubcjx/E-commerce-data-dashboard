"""Migration: widen all rate columns from NUMERIC(10, 6) to NUMERIC(20, 6).

Why: NUMERIC(10, 6) caps absolute values at 9999.999999. Real-world exports
occasionally contain calculated rates with tiny denominators that produce
massive values (e.g. profit_rate = 12345.67 ≈ 1.2M %), tripping
`numeric field overflow` on insert. NUMERIC(20, 6) is large enough that this
no longer fails for any plausible input.

Run once after pulling the code update:
    docker compose exec backend python -m scripts.migrate_widen_rates

Idempotent and safe to re-run; ALTER COLUMN TYPE is a no-op when the column
is already the target type.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db import engine


RATE_COLUMNS = [
    "pre_ship_refund_rate",
    "post_ship_refund_rate",
    "refund_rate",
    "material_cost_rate",
    "gift_cost_rate",
    "gross_margin",
    "marketing_cost_rate",
    "shipping_cost_rate",
    "platform_cost_rate",
    "profit_rate",
]


async def main() -> None:
    dialect = engine.dialect.name
    if dialect != "postgresql":
        print(f"Dialect is {dialect!r} — SQLite doesn't enforce NUMERIC precision, "
              "no migration needed. Exiting.")
        return

    print("Widening rate columns on sales_records to NUMERIC(20, 6)...")
    async with engine.begin() as conn:
        for col in RATE_COLUMNS:
            print(f"  ALTER COLUMN {col}")
            await conn.execute(text(
                f"ALTER TABLE sales_records ALTER COLUMN {col} TYPE NUMERIC(20, 6)"
            ))
    print("✓ Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
