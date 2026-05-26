"""Pytest config: make `from app...` and `from scripts...` imports work
when running `pytest` from the backend/ root, the same way uvicorn does.

Also points DATABASE_URL at an in-memory SQLite by default so importing
app modules doesn't try to connect to a real Postgres — pure-function
tests don't need a DB at all, but the import chain touches app.db.
"""
import os
import sys
from pathlib import Path

# Ensure the backend root (containing app/ and scripts/) is on sys.path.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# In-memory SQLite — safe default for tests that import app.db transitively.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
