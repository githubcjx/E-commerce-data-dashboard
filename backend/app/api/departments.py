"""Per-tenant department management.

Permission model:
    tenant_super_admin / platform_admin
        - full CRUD on departments inside their tenant (or any tenant for
          platform_admin via ?tenant_id=)
        - assign / reassign members at create or update time
    tenant_admin
        - read-only on the department list (so the user form can show the
          dropdown labels), and `PATCH /:id/members` to swap members
          between departments — but cannot change name / rate / create /
          delete.
    tenant_user
        - blocked entirely; not surfaced in the UI.

Delete rule:
    A department with members > 0 cannot be deleted; the super-admin must
    transfer members out first. This prevents accidentally orphaning users.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    Department, ROLE_PLATFORM_ADMIN, ROLE_TENANT_ADMIN, ROLE_TENANT_SUPER_ADMIN,
    ROLE_TENANT_USER, Tenant, User,
)
from ..schemas import (
    ApiResponse, DepartmentCreate, DepartmentDetailOut, DepartmentMember,
    DepartmentOut, DepartmentUpdate,
)
from ..security import require_backend_access

router = APIRouter(prefix="/api/departments", tags=["departments"])


def _scope_for(actor: User, explicit_tenant_id: int | None) -> int:
    if actor.role == ROLE_PLATFORM_ADMIN:
        if explicit_tenant_id is None:
            raise HTTPException(status_code=400, detail="平台管理员需指定 tenant_id")
        return explicit_tenant_id
    return actor.tenant_id


def _can_manage(actor: User) -> bool:
    """Can create / delete / rename / set rate. Super or platform only."""
    return actor.role in (ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN)


def _can_assign_members(actor: User) -> bool:
    """Can move users in/out of departments. Plain admin can do this too."""
    return actor.role in (
        ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN, ROLE_TENANT_ADMIN,
    )


async def _member_count(db: AsyncSession, dept_id: int) -> int:
    n = await db.scalar(
        select(func.count(User.id)).where(User.department_id == dept_id)
    )
    return int(n or 0)


def _to_out(dept: Department, member_count: int) -> DepartmentOut:
    out = DepartmentOut.model_validate(dept)
    out.fixed_profit_rate = float(dept.fixed_profit_rate)
    out.member_count = member_count
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=ApiResponse[list[DepartmentOut]])
async def list_departments(
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    scope = _scope_for(actor, tenant_id)
    rows = (await db.execute(
        select(Department, func.count(User.id))
        .outerjoin(User, User.department_id == Department.id)
        .where(Department.tenant_id == scope)
        .group_by(Department.id)
        .order_by(Department.id.asc())
    )).all()
    out = [_to_out(d, int(n or 0)) for d, n in rows]
    return ApiResponse(data=out)


@router.get("/{dept_id}", response_model=ApiResponse[DepartmentDetailOut])
async def get_department(
    dept_id: int,
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    dept = (await db.execute(select(Department).where(Department.id == dept_id))).scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=404, detail="部门不存在")
    if actor.role != ROLE_PLATFORM_ADMIN and dept.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=403, detail="无权查看其他企业的部门")
    members = (await db.execute(
        select(User).where(User.department_id == dept_id).order_by(User.id.asc())
    )).scalars().all()
    out = DepartmentDetailOut(
        id=dept.id, tenant_id=dept.tenant_id, name=dept.name,
        fixed_profit_rate=float(dept.fixed_profit_rate),
        member_count=len(members),
        created_at=dept.created_at,
        members=[DepartmentMember.model_validate(m) for m in members],
    )
    return ApiResponse(data=out)


@router.post("", response_model=ApiResponse[DepartmentOut])
async def create_department(
    body: DepartmentCreate,
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可创建部门")
    scope = _scope_for(actor, body.tenant_id)

    tenant = (await db.execute(select(Tenant).where(Tenant.id == scope))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="企业不存在")

    dup = (await db.execute(
        select(Department).where(
            Department.tenant_id == scope, Department.name == body.name,
        )
    )).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="部门名称已存在")

    dept = Department(
        tenant_id=scope,
        name=body.name,
        fixed_profit_rate=Decimal(str(body.fixed_profit_rate)).quantize(Decimal("0.0001")),
        created_by=actor.id,
    )
    db.add(dept)
    await db.flush()  # populate dept.id

    # Move requested members into this department. Validate every id is in
    # the same tenant and is not a super_admin / platform_admin.
    if body.member_ids:
        await _assign_members(db, dept, body.member_ids)

    await db.commit()
    await db.refresh(dept)
    return ApiResponse(data=_to_out(dept, await _member_count(db, dept.id)))


@router.patch("/{dept_id}", response_model=ApiResponse[DepartmentOut])
async def update_department(
    dept_id: int,
    body: DepartmentUpdate,
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    dept = (await db.execute(select(Department).where(Department.id == dept_id))).scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=404, detail="部门不存在")
    if actor.role != ROLE_PLATFORM_ADMIN and dept.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=403, detail="无权修改其他企业的部门")

    sent = body.model_fields_set
    changes_managed_fields = ("name" in sent and body.name is not None) or (
        "fixed_profit_rate" in sent and body.fixed_profit_rate is not None
    )
    changes_members = "member_ids" in sent and body.member_ids is not None

    if changes_managed_fields and not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可修改部门名称/费率")
    if changes_members and not _can_assign_members(actor):
        raise HTTPException(status_code=403, detail="无权调整部门成员")

    if "name" in sent and body.name is not None and body.name != dept.name:
        dup = (await db.execute(
            select(Department).where(
                Department.tenant_id == dept.tenant_id,
                Department.name == body.name,
                Department.id != dept.id,
            )
        )).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail="部门名称已存在")
        dept.name = body.name

    if "fixed_profit_rate" in sent and body.fixed_profit_rate is not None:
        dept.fixed_profit_rate = Decimal(str(body.fixed_profit_rate)).quantize(Decimal("0.0001"))

    if changes_members:
        await _replace_members(db, dept, body.member_ids or [])

    await db.commit()
    await db.refresh(dept)
    return ApiResponse(data=_to_out(dept, await _member_count(db, dept.id)))


@router.delete("/{dept_id}", response_model=ApiResponse[dict])
async def delete_department(
    dept_id: int,
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可删除部门")
    dept = (await db.execute(select(Department).where(Department.id == dept_id))).scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=404, detail="部门不存在")
    if actor.role != ROLE_PLATFORM_ADMIN and dept.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=403, detail="无权删除其他企业的部门")

    n = await _member_count(db, dept.id)
    if n > 0:
        raise HTTPException(status_code=400, detail=f"部门下还有 {n} 位成员，请先迁出后再删除")

    await db.delete(dept)
    await db.commit()
    return ApiResponse(data={"deleted": dept_id})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _assign_members(db: AsyncSession, dept: Department, member_ids: list[int]) -> None:
    """Move the listed users INTO this department.

    Validates every id:
      - belongs to the same tenant
      - is not a super_admin / platform_admin (those don't have departments)
    """
    if not member_ids:
        return
    users = (await db.execute(select(User).where(User.id.in_(member_ids)))).scalars().all()
    if len(users) != len(member_ids):
        raise HTTPException(status_code=400, detail="部分成员账号不存在")
    for u in users:
        if u.tenant_id != dept.tenant_id:
            raise HTTPException(status_code=400, detail=f"用户 {u.username} 不属于该企业")
        if u.role in (ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN):
            raise HTTPException(status_code=400, detail=f"超级管理员 {u.username} 不能归属部门")
        u.department_id = dept.id


async def _replace_members(db: AsyncSession, dept: Department, new_ids: list[int]) -> None:
    """Make the department's member set exactly == new_ids.

    Users currently in this department but not in new_ids get their
    department_id cleared (un-assigned). They do NOT auto-move to another
    department — the caller (super-admin) must reassign explicitly via a
    subsequent PATCH on the destination department.
    """
    current = (await db.execute(
        select(User).where(User.department_id == dept.id)
    )).scalars().all()
    new_set = set(new_ids)
    current_ids = {u.id for u in current}

    # Removed members (currently in dept, not in new set).
    for u in current:
        if u.id not in new_set:
            u.department_id = None

    # Added members (in new set, not currently in dept).
    to_add = [uid for uid in new_ids if uid not in current_ids]
    if to_add:
        await _assign_members(db, dept, to_add)
