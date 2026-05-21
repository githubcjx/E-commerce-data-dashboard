from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    ROLE_TENANT_ADMIN, TENANT_STATUS_ACTIVE, TENANT_STATUS_DISABLED, Tenant, User,
)
from ..schemas import (
    ApiResponse, TenantConfigOut, TenantConfigUpdate, TenantCreate, TenantOut, TenantUpdate,
)
from ..security import get_current_user, hash_password, require_platform_admin, require_tenant_admin

router = APIRouter(prefix="/api/tenants", tags=["tenants"])

VALID_STATUSES = {TENANT_STATUS_ACTIVE, TENANT_STATUS_DISABLED}


@router.get("", response_model=ApiResponse[list[TenantOut]])
async def list_tenants(
    actor: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    # Pull all tenants + user counts in one query for the admin table.
    stmt = (
        select(Tenant, func.count(User.id).label("user_count"))
        .outerjoin(User, User.tenant_id == Tenant.id)
        .group_by(Tenant.id)
        .order_by(Tenant.id.asc())
    )
    rows = (await db.execute(stmt)).all()
    out = []
    for tenant, user_count in rows:
        item = TenantOut.model_validate(tenant)
        item.user_count = int(user_count or 0)
        out.append(item)
    return ApiResponse(data=out)


@router.post("", response_model=ApiResponse[TenantOut])
async def create_tenant(
    body: TenantCreate,
    actor: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    # Reject duplicates up-front so the error is friendly (the DB constraint
    # would catch this too, but as IntegrityError).
    code_exists = (await db.execute(select(Tenant).where(Tenant.code == body.code))).scalar_one_or_none()
    if code_exists:
        raise HTTPException(status_code=409, detail="企业短码已存在")
    user_exists = (await db.execute(select(User).where(User.username == body.admin_username))).scalar_one_or_none()
    if user_exists:
        raise HTTPException(status_code=409, detail="管理员账号已被占用")

    # Atomic: create tenant + first tenant_admin user.
    tenant = Tenant(code=body.code, name=body.name, status=TENANT_STATUS_ACTIVE, created_by=actor.id)
    db.add(tenant)
    await db.flush()  # populate tenant.id

    admin = User(
        tenant_id=tenant.id,
        username=body.admin_username,
        password_hash=hash_password(body.admin_password),
        role=ROLE_TENANT_ADMIN,
        display_name=body.admin_display_name,
        created_by=actor.id,
    )
    db.add(admin)
    await db.commit()
    await db.refresh(tenant)

    out = TenantOut.model_validate(tenant)
    out.user_count = 1
    return ApiResponse(data=out)


@router.put("/{tenant_id}", response_model=ApiResponse[TenantOut])
async def update_tenant(
    tenant_id: int,
    body: TenantUpdate,
    actor: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="企业不存在")
    if body.name is not None:
        tenant.name = body.name
    if body.status is not None:
        if body.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="状态非法（active / disabled）")
        tenant.status = body.status
    await db.commit()
    await db.refresh(tenant)
    return ApiResponse(data=TenantOut.model_validate(tenant))


@router.get("/me/config", response_model=ApiResponse[TenantConfigOut])
async def get_my_tenant_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped read of dashboard config. Any logged-in tenant user can
    read it (the dashboard needs it to render 公司利润率). Updates are restricted
    to tenant_admin below.
    """
    if user.tenant_id is None:
        raise HTTPException(status_code=400, detail="平台管理员请在企业内访问")
    tenant = (await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="企业不存在")
    return ApiResponse(data=TenantConfigOut(fixed_profit_rate=float(tenant.fixed_profit_rate or Decimal("0.13"))))


@router.put("/me/config", response_model=ApiResponse[TenantConfigOut])
async def update_my_tenant_config(
    body: TenantConfigUpdate,
    actor: User = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
):
    """Only tenant_admin (or platform_admin) of THIS tenant can change the
    固定利润率. platform_admin can also reach in here from any tenant.
    """
    if actor.tenant_id is None:
        raise HTTPException(status_code=400, detail="平台管理员请在企业内执行此操作")
    tenant = (await db.execute(select(Tenant).where(Tenant.id == actor.tenant_id))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="企业不存在")
    tenant.fixed_profit_rate = Decimal(str(body.fixed_profit_rate)).quantize(Decimal("0.0001"))
    await db.commit()
    await db.refresh(tenant)
    return ApiResponse(data=TenantConfigOut(fixed_profit_rate=float(tenant.fixed_profit_rate)))


@router.delete("/{tenant_id}", response_model=ApiResponse[dict])
async def delete_tenant(
    tenant_id: int,
    actor: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="企业不存在")
    # CASCADE removes users, sales_records, import_batches, dashboard_layouts.
    await db.execute(delete(Tenant).where(Tenant.id == tenant_id))
    await db.commit()
    return ApiResponse(data={"deleted": tenant_id})
