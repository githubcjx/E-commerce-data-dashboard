from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    ROLE_PLATFORM_ADMIN, ROLE_TENANT_ADMIN, ROLE_TENANT_USER, Tenant, User,
)
from ..schemas import ApiResponse, UserCreate, UserOut, UserUpdate
from ..security import hash_password, require_tenant_admin

router = APIRouter(prefix="/api/users", tags=["users"])

TENANT_ROLES = {ROLE_TENANT_ADMIN, ROLE_TENANT_USER}


def _scope_for(actor: User, explicit_tenant_id: int | None) -> int:
    """Resolve which tenant a tenant-admin-level call operates on.

    - tenant_admin: forced to their own tenant; explicit_tenant_id is ignored.
    - platform_admin: must specify tenant_id (else 400).
    """
    if actor.role == ROLE_PLATFORM_ADMIN:
        if explicit_tenant_id is None:
            raise HTTPException(status_code=400, detail="平台管理员需指定 tenant_id")
        return explicit_tenant_id
    return actor.tenant_id  # guaranteed non-null for tenant_admin


def _can_act_on(actor: User, target: User) -> bool:
    """Authorization for editing/deleting a target user.

    - platform_admin: can manage anyone except other platform_admin and not self
    - tenant_admin: same tenant only, cannot operate on platform_admin, cannot manage self
    """
    if actor.id == target.id:
        return False  # can't manage self via admin endpoints
    if target.role == ROLE_PLATFORM_ADMIN:
        return False  # platform admins are off-limits to user-admin endpoints
    if actor.role == ROLE_PLATFORM_ADMIN:
        return True
    if actor.role == ROLE_TENANT_ADMIN:
        return target.tenant_id == actor.tenant_id
    return False


def _validate_role_for_actor(actor: User, requested_role: str) -> None:
    if requested_role not in TENANT_ROLES:
        raise HTTPException(status_code=400, detail="角色非法（tenant_admin / tenant_user）")


@router.get("", response_model=ApiResponse[list[UserOut]])
async def list_users(
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
):
    scope = _scope_for(actor, tenant_id)
    rows = (await db.execute(
        select(User)
        .where(User.tenant_id == scope)
        .order_by(User.id.asc())
    )).scalars().all()
    return ApiResponse(data=[UserOut.model_validate(u) for u in rows])


@router.post("", response_model=ApiResponse[UserOut])
async def create_user(
    body: UserCreate,
    actor: User = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
):
    _validate_role_for_actor(actor, body.role)
    scope = _scope_for(actor, body.tenant_id)

    # Verify the tenant exists when platform_admin specifies one.
    tenant = (await db.execute(select(Tenant).where(Tenant.id == scope))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="企业不存在")

    exists = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="用户名已存在")

    user = User(
        tenant_id=scope,
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        display_name=body.display_name,
        created_by=actor.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return ApiResponse(data=UserOut.model_validate(user))


@router.put("/{user_id}", response_model=ApiResponse[UserOut])
async def update_user(
    user_id: int,
    body: UserUpdate,
    actor: User = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not _can_act_on(actor, target):
        raise HTTPException(status_code=403, detail="无权操作该用户")

    if body.password is not None:
        target.password_hash = hash_password(body.password)
    if body.display_name is not None:
        target.display_name = body.display_name
    if body.role is not None and body.role != target.role:
        _validate_role_for_actor(actor, body.role)
        target.role = body.role

    await db.commit()
    await db.refresh(target)
    return ApiResponse(data=UserOut.model_validate(target))


@router.delete("/{user_id}", response_model=ApiResponse[dict])
async def delete_user(
    user_id: int,
    actor: User = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not _can_act_on(actor, target):
        raise HTTPException(status_code=403, detail="无权删除该用户")
    await db.delete(target)
    await db.commit()
    return ApiResponse(data={"deleted": user_id})
