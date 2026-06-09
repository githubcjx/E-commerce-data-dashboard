from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_db
from .models import (
    BACKEND_ROLES, ROLE_PLATFORM_ADMIN, ROLE_TENANT_ADMIN,
    ROLE_TENANT_SUPER_ADMIN, User,
)

settings = get_settings()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(
    user_id: int, role: str, tenant_id: int | None, token_version: int = 0,
) -> tuple[str, datetime]:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    payload = {
        "sub": str(user_id), "role": role, "tenant_id": tenant_id,
        "tv": token_version, "exp": expire,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expire


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else auth
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期")
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 无效")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不存在")
    # Session epoch check: a password change bumps users.token_version, so any
    # token minted before it (carrying the old `tv`) is rejected here, logging
    # that account out on every device. Missing `tv` (tokens predating the
    # feature) reads as 0, matching the default — no forced logout on deploy.
    if int(payload.get("tv", 0)) != int(user.token_version or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录凭证已失效，请重新登录",
        )
    return user


async def require_backend_access(user: User = Depends(get_current_user)) -> User:
    """Any role that has access to the /admin backend page.

    Includes platform_admin, tenant_super_admin, tenant_admin (the lesser
    admin tier). NOT tenant_user. Used as the entry guard — endpoint-level
    permission (create vs edit, target restrictions) is checked separately.
    """
    if user.role not in BACKEND_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问后台")
    return user


# Backwards-compatible alias. Old code (and external callers) referred to
# require_tenant_admin meaning "anyone with backend access". Keep the same
# semantic under the more accurate name above, but expose the alias too.
require_tenant_admin = require_backend_access


async def require_tenant_super_admin(user: User = Depends(get_current_user)) -> User:
    """tenant_super_admin OR platform_admin — for create/delete/role/scope
    mutations on users."""
    if user.role not in (ROLE_TENANT_SUPER_ADMIN, ROLE_PLATFORM_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅超级管理员可执行此操作")
    return user


async def require_import_access(user: User = Depends(get_current_user)) -> User:
    """super_admin or plain tenant_admin — the two roles allowed to use the
    import feature (upload Excel, view history, rollback). Excludes
    tenant_user (no import) and platform_admin (no own tenant data).
    """
    if user.role not in (ROLE_TENANT_SUPER_ADMIN, ROLE_TENANT_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可使用导入功能")
    return user


async def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_PLATFORM_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台管理员可执行此操作")
    return user


def effective_tenant_id(user: User, request: Request) -> int | None:
    """Resolve which tenant a request operates on.

    Regular tenant users/admins → their own user.tenant_id.
    platform_admin → reads X-Tenant-Id header for cross-tenant impersonation;
    returns None if they didn't pick one (callers must decide how to handle).
    """
    if user.role == ROLE_PLATFORM_ADMIN:
        h = request.headers.get("X-Tenant-Id")
        if h:
            try:
                return int(h)
            except ValueError:
                return None
        return None
    return user.tenant_id
