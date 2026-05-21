"""Migration: introduce tenant_super_admin role + users.data_scope_owners column.

Does two idempotent things:
  1. Adds users.data_scope_owners JSON column (nullable). Default NULL =
     unrestricted access.
  2. Promotes every existing tenant_admin user to tenant_super_admin. They
     were the "boss" of their tenant under the old model and should keep
     being so — the new "tenant_admin" role is a strictly-lesser tier.

Run after pulling the code update:
    docker compose exec backend python -m scripts.migrate_roles_and_scope

Safe to re-run.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db import engine


async def main() -> None:
    dialect = engine.dialect.name
    async with engine.begin() as conn:
        # ---- 1. data_scope_owners column -----------------------------------
        if dialect == "postgresql":
            col_exists = await conn.scalar(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='users' AND column_name='data_scope_owners'"
            ))
            if not col_exists:
                print("Adding users.data_scope_owners JSON ...")
                # JSONB would be marginally faster but JSON keeps parity with
                # SQLite, which is the more important consideration here.
                await conn.execute(text(
                    "ALTER TABLE users ADD COLUMN data_scope_owners JSON"
                ))
                print("  ✓ added")
            else:
                print("✓ users.data_scope_owners already present")
        elif dialect == "sqlite":
            cols = (await conn.execute(text("PRAGMA table_info(users)"))).all()
            if not any(c[1] == "data_scope_owners" for c in cols):
                print("Adding users.data_scope_owners (sqlite) ...")
                await conn.execute(text(
                    "ALTER TABLE users ADD COLUMN data_scope_owners TEXT"
                ))
                print("  ✓ added")
            else:
                print("✓ users.data_scope_owners already present")
        else:
            print(f"Unsupported dialect {dialect!r}; aborting.")
            return

        # ---- 2. Promote existing tenant_admin → tenant_super_admin ---------
        # Existing single-admin tenants keep the same person as the boss,
        # just under the new role name.
        result = await conn.execute(text(
            "UPDATE users SET role='tenant_super_admin' WHERE role='tenant_admin'"
        ))
        n = result.rowcount or 0
        if n:
            print(f"✓ Promoted {n} tenant_admin user(s) → tenant_super_admin")
        else:
            print("✓ No tenant_admin users to promote (already migrated or fresh DB)")

    print("\n✓ Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
