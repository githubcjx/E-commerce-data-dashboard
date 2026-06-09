"""Migration: ADD COLUMN users.token_version INTEGER NOT NULL DEFAULT 0.

Session epoch used to force-logout an account on every device. A password
change bumps this counter; the value is embedded in each JWT (the `tv`
claim) and checked on every request, so all tokens issued before the change
are rejected. Default 0 — existing tokens carry no `tv` claim and are read
as 0, so deploying this does NOT log everyone out.

Run after pulling the code update:
    docker compose exec backend python -m scripts.migrate_user_token_version

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
                "WHERE table_name='users' AND column_name='token_version'"
            ))
            if not exists:
                print("Adding users.token_version (postgres) ...")
                await conn.execute(text(
                    "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"
                ))
                print("  ✓ added")
            else:
                print("✓ users.token_version already present")
        elif dialect == "sqlite":
            cols = (await conn.execute(text("PRAGMA table_info(users)"))).all()
            if not any(c[1] == "token_version" for c in cols):
                print("Adding users.token_version (sqlite) ...")
                await conn.execute(text(
                    "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"
                ))
                print("  ✓ added")
            else:
                print("✓ users.token_version already present")
        else:
            print(f"Unsupported dialect {dialect!r}; aborting.")
            return

    print("\n✓ Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
