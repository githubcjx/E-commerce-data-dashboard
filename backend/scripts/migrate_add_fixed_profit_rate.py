"""Migration: add tenants.fixed_profit_rate (NUMERIC(6, 4), default 0.13).

Used to compute 公司利润率 = 经营利润率 − fixed_profit_rate per tenant.
Idempotent — re-runs are a no-op because we check the column first.

Run once after pulling the code update:
    docker compose exec backend python -m scripts.migrate_add_fixed_profit_rate
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db import engine


async def main() -> None:
    dialect = engine.dialect.name
    async with engine.begin() as conn:
        if dialect == "postgresql":
            exists = await conn.scalar(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='tenants' AND column_name='fixed_profit_rate'"
            ))
            if exists:
                print("✓ fixed_profit_rate already present, nothing to do.")
                return
            print("Adding tenants.fixed_profit_rate NUMERIC(6, 4) DEFAULT 0.13 ...")
            await conn.execute(text(
                "ALTER TABLE tenants ADD COLUMN fixed_profit_rate "
                "NUMERIC(6, 4) NOT NULL DEFAULT 0.13"
            ))
            print("✓ Migration complete.")
        elif dialect == "sqlite":
            cols = (await conn.execute(text("PRAGMA table_info(tenants)"))).all()
            if any(c[1] == "fixed_profit_rate" for c in cols):
                print("✓ fixed_profit_rate already present, nothing to do.")
                return
            print("Adding tenants.fixed_profit_rate (sqlite) ...")
            await conn.execute(text(
                "ALTER TABLE tenants ADD COLUMN fixed_profit_rate "
                "NUMERIC(6, 4) NOT NULL DEFAULT 0.13"
            ))
            print("✓ Migration complete.")
        else:
            print(f"Unsupported dialect {dialect!r}; aborting.")


if __name__ == "__main__":
    asyncio.run(main())
