from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")
_engine_kwargs: dict = {"echo": settings.debug}
if not _is_sqlite:
    _engine_kwargs.update(pool_size=10, max_overflow=20, pool_pre_ping=True)

engine = create_async_engine(settings.database_url, **_engine_kwargs)

if _is_sqlite:
    # SQLite needs WAL + busy_timeout for any real concurrency. Without WAL a
    # background import will block /api/auth/me lookups with `database is locked`.
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=10000")  # ms — wait for writers
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
