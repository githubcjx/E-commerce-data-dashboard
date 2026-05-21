from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    ROLE_PLATFORM_ADMIN, ROLE_TENANT_ADMIN, ROLE_TENANT_SUPER_ADMIN,
    ROLE_TENANT_USER, SalesRecord, Tenant, User,
)
from ..schemas import ApiResponse, UserCreate, UserOut, UserUpdate
from ..security import hash_password, require_backend_access

router = APIRouter(prefix="/api/users", tags=["users"])

# Roles a non-platform actor is allowed to *assign* via create/update. The
# super-admin role is reserved for the initial tenant account.
ASSIGNABLE_ROLES = {ROLE_TENANT_ADMIN, ROLE_TENANT_USER}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scope_for(actor: User, explicit_tenant_id: int | None) -> int:
    """Resolve which tenant a tenant-scoped call operates on.

    - tenant_super_admin / tenant_admin: forced to their own tenant.
    - platform_admin: must specify tenant_id (else 400).
    """
    if actor.role == ROLE_PLATFORM_ADMIN:
        if explicit_tenant_id is None:
            raise HTTPException(status_code=400, detail="平台管理员需指定 tenant_id")
        return explicit_tenant_id
    return actor.tenant_id  # non-null for tenant_super_admin / tenant_admin


def _can_create(actor: User) -> bool:
    """Only super_admin (within tenant) and platform_admin can create users."""
    return actor.role in (ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN)


def _can_delete(actor: User, target: User) -> bool:
    """Only super_admin / platform_admin can delete, and never themselves."""
    if actor.id == target.id:
        return False
    if target.role == ROLE_PLATFORM_ADMIN:
        return False
    if actor.role == ROLE_PLATFORM_ADMIN:
        return True
    if actor.role == ROLE_TENANT_SUPER_ADMIN:
        # super_admin can delete admin/user in their own tenant, never
        # another super_admin (there should be only one anyway, but defensively).
        return (
            target.tenant_id == actor.tenant_id
            and target.role != ROLE_TENANT_SUPER_ADMIN
        )
    return False


def _can_edit(actor: User, target: User) -> tuple[bool, set[str]]:
    """Return (allowed, allowed_fields).

    allowed_fields is the set of UserUpdate fields the actor may set on the
    target. For super/platform actors that's everything; for plain admins
    only basic fields on a tenant_user target.
    """
    if target.role == ROLE_PLATFORM_ADMIN:
        return False, set()

    # platform_admin
    if actor.role == ROLE_PLATFORM_ADMIN:
        return True, {"password", "display_name", "role", "data_scope_owners"}

    # super_admin: full control within own tenant; cannot edit ANOTHER
    # super_admin (defensive — only one per tenant).
    if actor.role == ROLE_TENANT_SUPER_ADMIN:
        if target.tenant_id != actor.tenant_id:
            return False, set()
        if target.role == ROLE_TENANT_SUPER_ADMIN and target.id != actor.id:
            return False, set()
        # Editing self: super may update name/password but not change own
        # role away (otherwise tenant is left without a super).
        if target.id == actor.id:
            return True, {"password", "display_name"}
        return True, {"password", "display_name", "role", "data_scope_owners"}

    # plain tenant_admin: same tenant, only普通user target, only basic fields.
    if actor.role == ROLE_TENANT_ADMIN:
        if target.tenant_id != actor.tenant_id:
            return False, set()
        if target.role != ROLE_TENANT_USER:
            return False, set()
        return True, {"password", "display_name"}

    return False, set()


def _validate_role(role: str) -> None:
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail="角色非法（仅可设置为 tenant_admin / tenant_user）",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/owners", response_model=ApiResponse[dict])
async def list_owners(
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    """Unrestricted list of 负责人 names for THE TENANT — used by the user
    admin dialog to populate the data-scope multi-select. Never scoped by
    the actor's own data_scope (a tenant_admin shouldn't be able to see this
    anyway because they can't edit scopes, but defensively we still don't
    filter here — endpoint requires backend access).
    """
    scope = _scope_for(actor, tenant_id)
    rows = (await db.execute(
        select(SalesRecord.owner).where(SalesRecord.tenant_id == scope).distinct()
    )).all()
    owners = sorted(o for (o,) in rows if o)
    return ApiResponse(data={"owners": owners})


@router.get("", response_model=ApiResponse[list[UserOut]])
async def list_users(
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
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
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    if not _can_create(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可创建账号")
    _validate_role(body.role)
    scope = _scope_for(actor, body.tenant_id)

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
        data_scope_owners=body.data_scope_owners,
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
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    allowed, allowed_fields = _can_edit(actor, target)
    if not allowed:
        raise HTTPException(status_code=403, detail="无权操作该用户")

    sent = body.model_fields_set  # which keys the client actually sent

    if "password" in sent and body.password is not None:
        if "password" not in allowed_fields:
            raise HTTPException(status_code=403, detail="无权修改密码")
        target.password_hash = hash_password(body.password)

    if "display_name" in sent:
        if "display_name" not in allowed_fields:
            raise HTTPException(status_code=403, detail="无权修改显示名")
        target.display_name = body.display_name

    if "role" in sent and body.role is not None and body.role != target.role:
        if "role" not in allowed_fields:
            raise HTTPException(status_code=403, detail="无权修改角色")
        _validate_role(body.role)
        target.role = body.role

    if "data_scope_owners" in sent:
        if "data_scope_owners" not in allowed_fields:
            raise HTTPException(status_code=403, detail="无权修改数据范围")
        target.data_scope_owners = body.data_scope_owners

    await db.commit()
    await db.refresh(target)
    return ApiResponse(data=UserOut.model_validate(target))


@router.delete("/{user_id}", response_model=ApiResponse[dict])
async def delete_user(
    user_id: int,
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not _can_delete(actor, target):
        raise HTTPException(status_code=403, detail="无权删除该用户")
    await db.delete(target)
    await db.commit()
    return ApiResponse(data={"deleted": user_id})
