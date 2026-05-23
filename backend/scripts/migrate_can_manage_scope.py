"""Migration: ADD COLUMN users.can_manage_scope BOOLEAN DEFAULT FALSE.

Tenant_super_admin toggles this per tenant_admin to grant the right to
edit普通用户.data_scope_owners. False by default (safe — admins don't
get the power unless explicitly granted).

Run after pulling the code update:
    docker compose exec backend python -m scripts.migrate_can_manage_scope

Safe to re-run.
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
                "WHERE table_name='users' AND column_name='can_manage_scope'"
            ))
            if not exists:
                print("Adding users.can_manage_scope (postgres) ...")
                await conn.execute(text(
                    "ALTER TABLE users ADD COLUMN can_manage_scope BOOLEAN NOT NULL DEFAULT FALSE"
                ))
                print("  ✓ added")
            else:
                print("✓ users.can_manage_scope already present")
        elif dialect == "sqlite":
            cols = (await conn.execute(text("PRAGMA table_info(users)"))).all()
            if not any(c[1] == "can_manage_scope" for c in cols):
                print("Adding users.can_manage_scope (sqlite) ...")
                # SQLite BOOLEAN is stored as INTEGER; 0/1 values.
                await conn.execute(text(
                    "ALTER TABLE users ADD COLUMN can_manage_scope BOOLEAN NOT NULL DEFAULT 0"
                ))
                print("  ✓ added")
            else:
                print("✓ users.can_manage_scope already present")
        else:
            print(f"Unsupported dialect {dialect!r}; aborting.")
            return

    print("\n✓ Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
