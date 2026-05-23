"""Migration: introduce Shop entity + user-departments M2M.

Idempotent steps:
  1. CREATE TABLE user_departments (user_id, department_id) — composite PK.
  2. Migrate existing users.department_id rows into user_departments.
  3. CREATE TABLE shops (id, tenant_id, shop_code, shop_name,
     view_department_id, fee_group_name, per_capita_share,
     ship_service_tax_rate, ...). Also handles the upgrade path from
     an earlier iteration that used a fee_department_id FK column.
  4. For each tenant, seed shops from distinct (shop_code, shop_name) in
     sales_records. view_department_id defaults to the tenant's 临时部门;
     fee_group_name is left blank for the admin to fill in.
  5. Drop users.department_id and departments.fixed_profit_rate columns.

Run after pulling the code update:
    docker compose exec backend python -m scripts.migrate_shops_and_user_depts

Safe to re-run.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db import engine


TEMP_DEPT_NAME = "临时部门"


async def main() -> None:  # noqa: C901
    dialect = engine.dialect.name
    if dialect not in ("postgresql", "sqlite"):
        print(f"Unsupported dialect {dialect!r}; aborting.")
        return

    async with engine.begin() as conn:
        # ---- 1. user_departments table -----------------------------------
        if dialect == "postgresql":
            exists = await conn.scalar(text(
                "SELECT 1 FROM information_schema.tables WHERE table_name='user_departments'"
            ))
            if not exists:
                print("Creating user_departments table ...")
                await conn.execute(text(
                    """
                    CREATE TABLE user_departments (
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
                        PRIMARY KEY (user_id, department_id)
                    )
                    """
                ))
                print("  ✓ created")
            else:
                print("✓ user_departments already present")
        else:  # sqlite
            row = (await conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='user_departments'"
            ))).first()
            if not row:
                print("Creating user_departments table (sqlite) ...")
                await conn.execute(text(
                    """
                    CREATE TABLE user_departments (
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
                        PRIMARY KEY (user_id, department_id)
                    )
                    """
                ))
                print("  ✓ created")
            else:
                print("✓ user_departments already present")

        # ---- 2. Migrate users.department_id → user_departments -----------
        # Only do this when the old column still exists (post-pre-deploy).
        if dialect == "postgresql":
            has_old_col = await conn.scalar(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='users' AND column_name='department_id'"
            ))
        else:
            cols = (await conn.execute(text("PRAGMA table_info(users)"))).all()
            has_old_col = any(c[1] == "department_id" for c in cols)

        if has_old_col:
            res = await conn.execute(text(
                """
                INSERT INTO user_departments (user_id, department_id)
                SELECT id, department_id FROM users
                WHERE department_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM user_departments ud
                    WHERE ud.user_id = users.id AND ud.department_id = users.department_id
                  )
                """
            ))
            n = res.rowcount or 0
            print(f"✓ Copied {n} user→department link(s) into user_departments")
        else:
            print("✓ users.department_id already gone — skip M2M copy")

        # ---- 3. shops table ----------------------------------------------
        # `fee_group_name` is a free-text label NOT linked to departments.
        # Earlier iterations of this migration used `fee_department_id` (FK);
        # the upgrade path below handles both cases.
        if dialect == "postgresql":
            exists = await conn.scalar(text(
                "SELECT 1 FROM information_schema.tables WHERE table_name='shops'"
            ))
            if not exists:
                print("Creating shops table ...")
                await conn.execute(text(
                    """
                    CREATE TABLE shops (
                        id              SERIAL PRIMARY KEY,
                        tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                        shop_code       VARCHAR(64) NOT NULL,
                        shop_name       VARCHAR(200),
                        view_department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
                        fee_group_name  VARCHAR(100),
                        per_capita_share      NUMERIC(18,4) NOT NULL DEFAULT 0,
                        ship_service_tax_rate NUMERIC(6,4)  NOT NULL DEFAULT 0,
                        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_shop_tenant_code UNIQUE (tenant_id, shop_code)
                    )
                    """
                ))
                await conn.execute(text("CREATE INDEX ix_shop_tenant ON shops(tenant_id)"))
                await conn.execute(text("CREATE INDEX ix_shop_view_dept ON shops(view_department_id)"))
                print("  ✓ created")
            else:
                print("✓ shops already present")
                # Upgrade path: drop fee_department_id (FK), add fee_group_name.
                has_fee_dept = await conn.scalar(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='shops' AND column_name='fee_department_id'"
                ))
                if has_fee_dept:
                    print("  Dropping shops.fee_department_id (deprecated FK) ...")
                    await conn.execute(text("ALTER TABLE shops DROP COLUMN fee_department_id"))
                has_fee_group = await conn.scalar(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='shops' AND column_name='fee_group_name'"
                ))
                if not has_fee_group:
                    print("  Adding shops.fee_group_name ...")
                    await conn.execute(text(
                        "ALTER TABLE shops ADD COLUMN fee_group_name VARCHAR(100)"
                    ))
        else:  # sqlite
            row = (await conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='shops'"
            ))).first()
            if not row:
                print("Creating shops table (sqlite) ...")
                await conn.execute(text(
                    """
                    CREATE TABLE shops (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                        shop_code VARCHAR(64) NOT NULL,
                        shop_name VARCHAR(200),
                        view_department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
                        fee_group_name VARCHAR(100),
                        per_capita_share      NUMERIC(18,4) NOT NULL DEFAULT 0,
                        ship_service_tax_rate NUMERIC(6,4)  NOT NULL DEFAULT 0,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT uq_shop_tenant_code UNIQUE (tenant_id, shop_code)
                    )
                    """
                ))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_shop_tenant ON shops(tenant_id)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_shop_view_dept ON shops(view_department_id)"))
                print("  ✓ created")
            else:
                print("✓ shops already present")
                cols = (await conn.execute(text("PRAGMA table_info(shops)"))).all()
                names = {c[1] for c in cols}
                if "fee_department_id" in names:
                    print("  Dropping shops.fee_department_id (sqlite) ...")
                    try:
                        await conn.execute(text("ALTER TABLE shops DROP COLUMN fee_department_id"))
                    except Exception as e:  # pragma: no cover
                        print(f"  ⚠ could not drop: {e}")
                if "fee_group_name" not in names:
                    print("  Adding shops.fee_group_name (sqlite) ...")
                    await conn.execute(text(
                        "ALTER TABLE shops ADD COLUMN fee_group_name VARCHAR(100)"
                    ))

        # ---- 4. Seed shops from sales_records ----------------------------
        # Per-tenant: distinct (shop_code, shop_name) → INSERT IF NOT EXISTS.
        # view_department_id defaults to the tenant's 临时部门 so the
        # 部门视角 picker works out of the box; fee_group_name is left
        # blank for the admin to fill in via 店铺管理.
        tenants = (await conn.execute(text("SELECT id FROM tenants"))).all()
        seeded = 0
        for (tid,) in tenants:
            temp_dept = await conn.scalar(text(
                "SELECT id FROM departments WHERE tenant_id=:tid AND name=:name"
            ), {"tid": tid, "name": TEMP_DEPT_NAME})
            shops_in_data = (await conn.execute(text(
                """
                SELECT shop_code, MAX(shop_name) AS shop_name
                FROM sales_records
                WHERE tenant_id = :tid AND shop_code IS NOT NULL AND shop_code <> ''
                GROUP BY shop_code
                """
            ), {"tid": tid})).all()
            for shop_code, shop_name in shops_in_data:
                exists_row = await conn.scalar(text(
                    "SELECT 1 FROM shops WHERE tenant_id=:tid AND shop_code=:code"
                ), {"tid": tid, "code": shop_code})
                if exists_row:
                    continue
                await conn.execute(text(
                    """
                    INSERT INTO shops (
                        tenant_id, shop_code, shop_name,
                        view_department_id,
                        per_capita_share, ship_service_tax_rate
                    ) VALUES (
                        :tid, :code, :name, :vdid, 0, 0
                    )
                    """
                ), {
                    "tid": tid, "code": shop_code, "name": shop_name,
                    "vdid": temp_dept,
                })
                seeded += 1
        print(f"✓ Seeded {seeded} shop(s) from sales_records (defaults: 视角=临时部门, fees=0)")

        # ---- 5. Drop deprecated columns ----------------------------------
        # users.department_id (single dept → M2M)
        if has_old_col:
            if dialect == "postgresql":
                print("Dropping users.department_id ...")
                await conn.execute(text(
                    "ALTER TABLE users DROP COLUMN department_id"
                ))
                print("  ✓ dropped")
            else:
                try:
                    await conn.execute(text(
                        "ALTER TABLE users DROP COLUMN department_id"
                    ))
                    print("  ✓ dropped (sqlite)")
                except Exception as e:  # pragma: no cover
                    print(f"  ⚠ could not drop users.department_id on sqlite: {e}")
                    print("  (column is unused going forward; safe to leave)")
        else:
            print("✓ users.department_id already gone")

        # departments.fixed_profit_rate (per-dept rate → per-shop rate)
        if dialect == "postgresql":
            has_rate_col = await conn.scalar(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='departments' AND column_name='fixed_profit_rate'"
            ))
        else:
            d_cols = (await conn.execute(text("PRAGMA table_info(departments)"))).all()
            has_rate_col = any(c[1] == "fixed_profit_rate" for c in d_cols)

        if has_rate_col:
            if dialect == "postgresql":
                print("Dropping departments.fixed_profit_rate ...")
                await conn.execute(text(
                    "ALTER TABLE departments DROP COLUMN fixed_profit_rate"
                ))
                print("  ✓ dropped")
            else:
                try:
                    await conn.execute(text(
                        "ALTER TABLE departments DROP COLUMN fixed_profit_rate"
                    ))
                    print("  ✓ dropped (sqlite)")
                except Exception as e:  # pragma: no cover
                    print(f"  ⚠ could not drop departments.fixed_profit_rate on sqlite: {e}")
        else:
            print("✓ departments.fixed_profit_rate already gone")

    print("\n✓ Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
