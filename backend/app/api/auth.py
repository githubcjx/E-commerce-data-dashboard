from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import TENANT_STATUS_DISABLED, Tenant, User
from ..schemas import ApiResponse, LoginRequest, LoginResponse, TenantBrief, UserOut
from ..security import create_token, get_current_user, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=ApiResponse[LoginResponse])
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")

    tenant_brief: TenantBrief | None = None
    if user.tenant_id is not None:
        tenant = (await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=401, detail="所属企业不存在")
        if tenant.status == TENANT_STATUS_DISABLED:
            raise HTTPException(status_code=403, detail="所属企业已停用，请联系平台管理员")
        tenant_brief = TenantBrief.model_validate(tenant)

    token, expire = create_token(user.id, user.role, user.tenant_id)
    return ApiResponse(data=LoginResponse(
        token=token,
        expire_at=expire,
        user=UserOut.model_validate(user),
        tenant=tenant_brief,
    ))


@router.get("/me", response_model=ApiResponse[LoginResponse])
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Reuse LoginResponse shape but with the existing token's expiry — caller
    # can drop the token field. Cheaper than two schemas.
    tenant_brief = None
    if user.tenant_id is not None:
        tenant = (await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one_or_none()
        tenant_brief = TenantBrief.model_validate(tenant) if tenant else None
    from datetime import datetime, timezone
    return ApiResponse(data=LoginResponse(
        token="",
        expire_at=datetime.now(timezone.utc),
        user=UserOut.model_validate(user),
        tenant=tenant_brief,
    ))
