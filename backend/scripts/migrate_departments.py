"""Migration: introduce per-tenant 部门 (departments).

Idempotent steps:
  1. CREATE TABLE departments (id, tenant_id, name, fixed_profit_rate, ...)
     with UNIQUE(tenant_id, name).
  2. ALTER TABLE users ADD COLUMN department_id (nullable, FK → departments.id
     ON DELETE SET NULL).
  3. For every tenant, ensure a department named '临时部门' exists. Its
     `fixed_profit_rate` is seeded from the (now-deprecated) tenants
     .fixed_profit_rate value if present, else 0.13.
  4. Move every user whose role IS tenant_admin OR tenant_user AND whose
     department_id IS NULL into their tenant's 临时部门.
  5. Drop the now-unused tenants.fixed_profit_rate column.

Run after pulling code update:
    docker compose exec backend python -m scripts.migrate_departments

Safe to re-run.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db import engine


TEMP_DEPT_NAME = "临时部门"
DEFAULT_RATE = "0.13"


async def main() -> None:  # noqa: C901 — single linear script, fine
    dialect = engine.dialect.name
    if dialect not in ("postgresql", "sqlite"):
        print(f"Unsupported dialect {dialect!r}; aborting.")
        return

    async with engine.begin() as conn:
        # ---- 1. departments table -----------------------------------------
        if dialect == "postgresql":
            exists = await conn.scalar(text(
                "SELECT 1 FROM information_schema.tables WHERE table_name='departments'"
            ))
            if not exists:
                print("Creating departments table ...")
                await conn.execute(text(
                    """
                    CREATE TABLE departments (
                        id              SERIAL PRIMARY KEY,
                        tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                        name            VARCHAR(100) NOT NULL,
                        fixed_profit_rate NUMERIC(6,4) NOT NULL DEFAULT 0.13,
                        created_by      INTEGER,
                        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_dept_tenant_name UNIQUE (tenant_id, name)
                    )
                    """
                ))
                await conn.execute(text("CREATE INDEX ix_dept_tenant ON departments(tenant_id)"))
                print("  ✓ created")
            else:
                print("✓ departments table already present")
        else:  # sqlite
            row = (await conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='departments'"
            ))).first()
            if not row:
                print("Creating departments table (sqlite) ...")
                await conn.execute(text(
                    """
                    CREATE TABLE departments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                        name VARCHAR(100) NOT NULL,
                        fixed_profit_rate NUMERIC(6,4) NOT NULL DEFAULT 0.13,
                        created_by INTEGER,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT uq_dept_tenant_name UNIQUE (tenant_id, name)
                    )
                    """
                ))
                await conn.execute(text("CREATE INDEX ix_dept_tenant ON departments(tenant_id)"))
                print("  ✓ created")
            else:
                print("✓ departments table already present")

        # ---- 2. users.department_id column --------------------------------
        if dialect == "postgresql":
            has_col = await conn.scalar(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='users' AND column_name='department_id'"
            ))
            if not has_col:
                print("Adding users.department_id ...")
                await conn.execute(text(
                    "ALTER TABLE users ADD COLUMN department_id INTEGER "
                    "REFERENCES departments(id) ON DELETE SET NULL"
                ))
                await conn.execute(text(
                    "CREATE INDEX ix_users_department_id ON users(department_id)"
                ))
                print("  ✓ added")
            else:
                print("✓ users.department_id already present")
        else:  # sqlite
            cols = (await conn.execute(text("PRAGMA table_info(users)"))).all()
            if not any(c[1] == "department_id" for c in cols):
                print("Adding users.department_id (sqlite) ...")
                await conn.execute(text(
                    "ALTER TABLE users ADD COLUMN department_id INTEGER "
                    "REFERENCES departments(id) ON DELETE SET NULL"
                ))
                # SQLite doesn't error on duplicate CREATE INDEX IF NOT EXISTS,
                # use that form for re-runs.
                await conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_users_department_id ON users(department_id)"
                ))
                print("  ✓ added")
            else:
                print("✓ users.department_id already present")

        # ---- 3. Seed 临时部门 per tenant ----------------------------------
        # If the old tenants.fixed_profit_rate column still exists, use its
        # value as the seed; else fall back to DEFAULT_RATE.
        if dialect == "postgresql":
            has_old_col = await conn.scalar(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='tenants' AND column_name='fixed_profit_rate'"
            ))
        else:
            t_cols = (await conn.execute(text("PRAGMA table_info(tenants)"))).all()
            has_old_col = any(c[1] == "fixed_profit_rate" for c in t_cols)

        select_tenants = (
            "SELECT id, COALESCE(fixed_profit_rate, " + DEFAULT_RATE + ") AS rate FROM tenants"
            if has_old_col else
            "SELECT id, " + DEFAULT_RATE + " AS rate FROM tenants"
        )
        tenants = (await conn.execute(text(select_tenants))).all()
        created_n = 0
        for tid, rate in tenants:
            existing = await conn.scalar(text(
                "SELECT id FROM departments WHERE tenant_id=:tid AND name=:name"
            ), {"tid": tid, "name": TEMP_DEPT_NAME})
            if existing:
                continue
            await conn.execute(text(
                "INSERT INTO departments (tenant_id, name, fixed_profit_rate) "
                "VALUES (:tid, :name, :rate)"
            ), {"tid": tid, "name": TEMP_DEPT_NAME, "rate": rate})
            created_n += 1
        print(f"✓ 临时部门: created {created_n}, existing {len(tenants) - created_n}")

        # ---- 4. Move existing tenant_admin / tenant_user into 临时部门 -----
        # Anyone whose role is tenant_admin or tenant_user AND who has no
        # department gets dropped into 临时部门 of their own tenant.
        result = await conn.execute(text(
            """
            UPDATE users
            SET department_id = (
                SELECT d.id FROM departments d
                WHERE d.tenant_id = users.tenant_id AND d.name = :name
            )
            WHERE department_id IS NULL
              AND tenant_id IS NOT NULL
              AND role IN ('tenant_admin', 'tenant_user')
            """
        ), {"name": TEMP_DEPT_NAME})
        n_moved = result.rowcount or 0
        print(f"✓ Assigned {n_moved} user(s) to their 临时部门")

        # ---- 5. Drop tenants.fixed_profit_rate ----------------------------
        if has_old_col:
            if dialect == "postgresql":
                print("Dropping tenants.fixed_profit_rate ...")
                await conn.execute(text(
                    "ALTER TABLE tenants DROP COLUMN fixed_profit_rate"
                ))
                print("  ✓ dropped")
            else:
                # SQLite < 3.35 doesn't support DROP COLUMN. Modern SQLite
                # (3.35+) does — try it, fall back to leaving the column.
                try:
                    await conn.execute(text(
                        "ALTER TABLE tenants DROP COLUMN fixed_profit_rate"
                    ))
                    print("  ✓ dropped (sqlite)")
                except Exception as e:  # pragma: no cover
                    print(f"  ⚠ could not drop fixed_profit_rate on sqlite: {e}")
                    print("  (column is unused going forward; safe to leave)")
        else:
            print("✓ tenants.fixed_profit_rate already gone")

    print("\n✓ Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
