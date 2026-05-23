import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .api import auth, dashboard, departments, import_api, layout, shops, tenants, users
from .config import get_settings
from .db import Base, SessionLocal, engine
from .models import ROLE_PLATFORM_ADMIN, User
from .security import hash_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(title=settings.app_name, version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _bootstrap_platform_admin() -> None:
    async with SessionLocal() as session:
        existing = (await session.execute(
            select(User).where(User.role == ROLE_PLATFORM_ADMIN)
        )).scalar_one_or_none()
        if existing:
            return
        user = User(
            tenant_id=None,
            username=settings.platform_admin_username,
            password_hash=hash_password(settings.platform_admin_password),
            role=ROLE_PLATFORM_ADMIN,
            display_name="平台管理员",
        )
        session.add(user)
        await session.commit()
        log.info("Bootstrapped platform admin: %s", settings.platform_admin_username)


@app.on_event("startup")
async def on_startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _bootstrap_platform_admin()


@app.get("/api/health")
async def health() -> dict:
    return {"code": 0, "data": {"status": "ok"}, "msg": "ok"}


app.include_router(auth.router)
app.include_router(tenants.router)
app.include_router(users.router)
app.include_router(departments.router)
app.include_router(shops.router)
app.include_router(import_api.router)
app.include_router(dashboard.router)
app.include_router(layout.router)
