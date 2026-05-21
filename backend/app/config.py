from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "电商数据看板"
    debug: bool = False

    # Defaults to a local SQLite file so the project runs with zero infra.
    # In production, override via DATABASE_URL env var to PostgreSQL:
    #   postgresql+asyncpg://user:pass@host:5432/ec_dashboard
    database_url: str = "sqlite+aiosqlite:///./demo.db"

    # JWT
    jwt_secret: str = "change-me-in-production-please-32-chars"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7

    # Initial platform admin (created at first startup if no superadmin exists).
    # In production override BOTH via .env so secrets never touch git history.
    platform_admin_username: str = "cjx"
    platform_admin_password: str = "change-me-on-first-deploy"

    # Per-upload limit. Whole file is read into memory before being spooled to
    # disk (see import_api.upload), so peak RAM ≈ 2× this value. On a 2C2G
    # server 50 MB is the comfortable ceiling; raising past 80 MB without
    # switching to streaming I/O risks OOM under concurrent uploads.
    upload_max_mb: int = 50
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
