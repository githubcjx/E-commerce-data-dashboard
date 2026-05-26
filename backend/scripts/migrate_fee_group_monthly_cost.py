"""Migration: per-month fixed cost for fee groups.

Two changes, both idempotent:

  1. CREATE TABLE fee_group_monthly_cost
       (id, tenant_id, fee_group_name, year_month CHAR(7), amount, ...)
     UNIQUE (tenant_id, fee_group_name, year_month)

     New 公司利润率 公式按月分摊：amount 是该费用部门**整月**的固定费用总额，
     运行时按"当月总额 / 当月天数 × 已发生天数 × 该店销售占比"分摊给店铺。

  2. DROP COLUMN shops.per_capita_share
     旧的"每店固定均摊"语义和新的"部门月度总额"不可逆推，旧数据无意义。
     按用户决定一刀切删字段；前端也同步移除该输入。

Run once after pulling:
    docker compose exec backend python -m scripts.migrate_fee_group_monthly_cost
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db import engine


async def _table_exists(conn, name: str, dialect: str) -> bool:
    if dialect == "postgresql":
        return bool(await conn.scalar(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name=:n"
        ), {"n": name}))
    if dialect == "sqlite":
        return bool(await conn.scalar(text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"
        ), {"n": name}))
    return False


async def _column_exists(conn, table: str, col: str, dialect: str) -> bool:
    if dialect == "postgresql":
        return bool(await conn.scalar(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ), {"t": table, "c": col}))
    if dialect == "sqlite":
        rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
        return any(r[1] == col for r in rows)
    return False


async def main() -> None:
    dialect = engine.dialect.name
    if dialect not in ("postgresql", "sqlite"):
        print(f"Unsupported dialect {dialect!r}; aborting.")
        return

    async with engine.begin() as conn:
        # ------------------------------------------------------------------
        # 1) fee_group_monthly_cost
        # ------------------------------------------------------------------
        if await _table_exists(conn, "fee_group_monthly_cost", dialect):
            print("[OK] fee_group_monthly_cost already exists.")
        else:
            print("Creating fee_group_monthly_cost ...")
            if dialect == "postgresql":
                await conn.execute(text("""
                    CREATE TABLE fee_group_monthly_cost (
                        id              BIGSERIAL    PRIMARY KEY,
                        tenant_id       INTEGER      NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                        fee_group_name  VARCHAR(100) NOT NULL,
                        year_month      CHAR(7)      NOT NULL,
                        amount          NUMERIC(18,4) NOT NULL DEFAULT 0,
                        created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                        updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_fgmc_tenant_group_month
                          UNIQUE (tenant_id, fee_group_name, year_month)
                    )
                """))
                await conn.execute(text(
                    "CREATE INDEX ix_fgmc_tenant_group "
                    "ON fee_group_monthly_cost (tenant_id, fee_group_name)"
                ))
            else:  # sqlite
                await conn.execute(text("""
                    CREATE TABLE fee_group_monthly_cost (
                        id              INTEGER      PRIMARY KEY AUTOINCREMENT,
                        tenant_id       INTEGER      NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                        fee_group_name  VARCHAR(100) NOT NULL,
                        year_month      CHAR(7)      NOT NULL,
                        amount          NUMERIC(18,4) NOT NULL DEFAULT 0,
                        created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT uq_fgmc_tenant_group_month
                          UNIQUE (tenant_id, fee_group_name, year_month)
                    )
                """))
                await conn.execute(text(
                    "CREATE INDEX ix_fgmc_tenant_group "
                    "ON fee_group_monthly_cost (tenant_id, fee_group_name)"
                ))
            print("[OK] fee_group_monthly_cost created.")

        # ------------------------------------------------------------------
        # 2) DROP shops.per_capita_share
        # ------------------------------------------------------------------
        if not await _column_exists(conn, "shops", "per_capita_share", dialect):
            print("[OK] shops.per_capita_share already absent.")
        else:
            print("Dropping shops.per_capita_share ...")
            # Postgres always supports; SQLite 3.35+ supports DROP COLUMN.
            await conn.execute(text("ALTER TABLE shops DROP COLUMN per_capita_share"))
            print("[OK] shops.per_capita_share dropped.")

    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
