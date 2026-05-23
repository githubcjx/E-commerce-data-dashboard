from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    Department, ROLE_PLATFORM_ADMIN, ROLE_TENANT_ADMIN, ROLE_TENANT_SUPER_ADMIN,
    ROLE_TENANT_USER, SalesRecord, Tenant, User, UserDepartment,
)
from ..schemas import ApiResponse, DepartmentBrief, UserCreate, UserOut, UserUpdate
from ..security import hash_password, require_backend_access

router = APIRouter(prefix="/api/users", tags=["users"])

ASSIGNABLE_ROLES = {ROLE_TENANT_ADMIN, ROLE_TENANT_USER}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scope_for(actor: User, explicit_tenant_id: int | None) -> int:
    if actor.role == ROLE_PLATFORM_ADMIN:
        if explicit_tenant_id is None:
            raise HTTPException(status_code=400, detail="平台管理员需指定 tenant_id")
        return explicit_tenant_id
    return actor.tenant_id


def _can_create(actor: User) -> bool:
    return actor.role in (ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN)


def _can_delete(actor: User, target: User) -> bool:
    if actor.id == target.id:
        return False
    if target.role == ROLE_PLATFORM_ADMIN:
        return False
    if actor.role == ROLE_PLATFORM_ADMIN:
        return True
    if actor.role == ROLE_TENANT_SUPER_ADMIN:
        return (
            target.tenant_id == actor.tenant_id
            and target.role != ROLE_TENANT_SUPER_ADMIN
        )
    return False


def _can_edit(actor: User, target: User) -> tuple[bool, set[str]]:
    """Return (allowed, allowed_fields).

    Plain admin can now edit data_scope_owners too (per the new rule that
    scope-editing is super + admin, not super-only).
    """
    if target.role == ROLE_PLATFORM_ADMIN:
        return False, set()

    if actor.role == ROLE_PLATFORM_ADMIN:
        return True, {"password", "display_name", "role", "data_scope_owners", "department_ids"}

    if actor.role == ROLE_TENANT_SUPER_ADMIN:
        if target.tenant_id != actor.tenant_id:
            return False, set()
        if target.role == ROLE_TENANT_SUPER_ADMIN and target.id != actor.id:
            return False, set()
        if target.id == actor.id:
            # Editing self: super may update name/password but not own role
            # (would orphan the tenant) and supers have no departments.
            return True, {"password", "display_name"}
        return True, {"password", "display_name", "role", "data_scope_owners", "department_ids"}

    if actor.role == ROLE_TENANT_ADMIN:
        # Plain admin: can edit普通user in own tenant + adjust departments
        # + adjust data_scope_owners. Cannot touch password of others (per
        # historical design — only super resets passwords).
        if target.tenant_id != actor.tenant_id:
            return False, set()
        if target.role != ROLE_TENANT_USER:
            return False, set()
        return True, {"display_name", "department_ids", "data_scope_owners"}

    return False, set()


def _validate_role(role: str) -> None:
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail="角色非法（仅可设置为 tenant_admin / tenant_user）",
        )


async def _resolve_departments(
    db: AsyncSession, tenant_id: int, department_ids: list[int] | None, role: str,
) -> list[int]:
    """Validate the requested department_ids for create/update.

    Super-admins / platform-admins must have an empty list. Others must
    have at least one. Every id must point at a department in the same
    tenant.
    """
    ids = list(department_ids or [])
    if role in (ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN):
        if ids:
            raise HTTPException(status_code=400, detail="超级管理员不归属任何部门")
        return []
    if not ids:
        raise HTTPException(status_code=400, detail="请至少选择一个部门")
    depts = (await db.execute(
        select(Department).where(Department.id.in_(ids))
    )).scalars().all()
    if len(depts) != len(set(ids)):
        raise HTTPException(status_code=400, detail="部分部门不存在")
    for d in depts:
        if d.tenant_id != tenant_id:
            raise HTTPException(status_code=400, detail=f"部门「{d.name}」不属于该企业")
    return list(set(ids))


async def _user_departments(db: AsyncSession, user_id: int) -> list[DepartmentBrief]:
    rows = (await db.execute(
        select(Department)
        .join(UserDepartment, UserDepartment.department_id == Department.id)
        .where(UserDepartment.user_id == user_id)
        .order_by(Department.id.asc())
    )).scalars().all()
    return [DepartmentBrief.model_validate(d) for d in rows]


async def _set_user_departments(db: AsyncSession, user_id: int, dept_ids: list[int]) -> None:
    """Replace the user's department links wholesale."""
    existing = (await db.execute(
        select(UserDepartment).where(UserDepartment.user_id == user_id)
    )).scalars().all()
    for link in existing:
        await db.delete(link)
    await db.flush()
    for did in dept_ids:
        db.add(UserDepartment(user_id=user_id, department_id=did))


async def _hydrate_user(db: AsyncSession, user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.departments = await _user_departments(db, user.id)
    return out


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
    admin dialog to populate the data-scope multi-select and the
    display-name combobox.
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
    users = (await db.execute(
        select(User).where(User.tenant_id == scope).order_by(User.id.asc())
    )).scalars().all()
    if not users:
        return ApiResponse(data=[])

    # Bulk-load all department memberships for this tenant's users in one
    # query, then attach.
    user_ids = [u.id for u in users]
    link_rows = (await db.execute(
        select(UserDepartment.user_id, Department)
        .join(Department, Department.id == UserDepartment.department_id)
        .where(UserDepartment.user_id.in_(user_ids))
    )).all()
    depts_by_user: dict[int, list[DepartmentBrief]] = {uid: [] for uid in user_ids}
    for uid, dept in link_rows:
        depts_by_user[uid].append(DepartmentBrief.model_validate(dept))

    out: list[UserOut] = []
    for u in users:
        item = UserOut.model_validate(u)
        item.departments = depts_by_user.get(u.id, [])
        out.append(item)
    return ApiResponse(data=out)


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

    dept_ids = await _resolve_departments(db, scope, body.department_ids, body.role)

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
    await db.flush()
    if dept_ids:
        await _set_user_departments(db, user.id, dept_ids)
    await db.commit()
    await db.refresh(user)
    return ApiResponse(data=await _hydrate_user(db, user))


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

    sent = body.model_fields_set

    if "password" in sent and body.password is not None:
        if "password" not in allowed_fields:
            raise HTTPException(status_code=403, detail="无权修改密码")
        target.password_hash = hash_password(body.password)

    if "display_name" in sent:
        if "display_name" not in allowed_fields:
            raise HTTPException(status_code=403, detail="无权修改显示名")
        target.display_name = body.display_name

    new_role = target.role
    if "role" in sent and body.role is not None and body.role != target.role:
        if "role" not in allowed_fields:
            raise HTTPException(status_code=403, detail="无权修改角色")
        _validate_role(body.role)
        new_role = body.role

    # Department membership — full-replace semantics. When the role is
    # flipping to/from super, _resolve_departments enforces the right
    # cardinality.
    if "department_ids" in sent:
        if "department_ids" not in allowed_fields:
            raise HTTPException(status_code=403, detail="无权调整部门归属")
        ids = await _resolve_departments(db, target.tenant_id, body.department_ids, new_role)
        await _set_user_departments(db, target.id, ids)
    elif new_role != target.role:
        # Role flipped, dept list wasn't sent: validate the existing one
        # against the new role (and clear if becoming super).
        if new_role in (ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN):
            await _set_user_departments(db, target.id, [])
        else:
            existing = await _user_departments(db, target.id)
            if not existing:
                raise HTTPException(status_code=400, detail="请至少选择一个部门")

    if new_role != target.role:
        target.role = new_role

    if "data_scope_owners" in sent:
        if "data_scope_owners" not in allowed_fields:
            raise HTTPException(status_code=403, detail="无权修改数据范围")
        target.data_scope_owners = body.data_scope_owners

    await db.commit()
    await db.refresh(target)
    return ApiResponse(data=await _hydrate_user(db, target))


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
