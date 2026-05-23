"""Per-tenant department management.

Two responsibilities:
  - Roster:    which users belong to this department (M2M, a user can be in
               many departments).
  - 视角店铺:   which shops show up under this department's 部门视角 on the
               dashboard (one shop ↔ at most one view-department).

Fee data is NOT here anymore — it lives per-shop on the shops table,
managed in the 店铺管理 panel.

Permission model:
    tenant_super_admin / platform_admin
        - full CRUD on departments inside their tenant (or any tenant for
          platform_admin via ?tenant_id=)
        - assign / reassign members + view-shops
    tenant_admin
        - read-only on the list (needed to populate dropdowns), plus the
          right to move members between departments via /api/users
    tenant_user
        - blocked entirely; not surfaced in the UI.

Delete rule:
    A department with members > 0 cannot be deleted. Shops that point at
    this department for either view or fee have those pointers nulled
    (ON DELETE SET NULL).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    Department, ROLE_PLATFORM_ADMIN, ROLE_TENANT_ADMIN, ROLE_TENANT_SUPER_ADMIN,
    Shop, User, UserDepartment,
)
from ..schemas import (
    ApiResponse, DepartmentCreate, DepartmentMember, DepartmentOut,
    DepartmentShop, DepartmentUpdate,
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
    """Can create / delete / rename. Super or platform only."""
    return actor.role in (ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN)


def _can_assign_members(actor: User) -> bool:
    return actor.role in (
        ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN, ROLE_TENANT_ADMIN,
    )


# ---------------------------------------------------------------------------
# Hydration helpers
# ---------------------------------------------------------------------------

async def _hydrate(db: AsyncSession, depts: list[Department]) -> list[DepartmentOut]:
    """Bulk-load members + view-shops for the given departments.

    Two grouped queries (one per relation) keep this O(1) round-trips per
    list call instead of O(N).
    """
    if not depts:
        return []
    dept_ids = [d.id for d in depts]

    # Members per department (via user_departments).
    member_rows = (await db.execute(
        select(UserDepartment.department_id, User)
        .join(User, User.id == UserDepartment.user_id)
        .where(UserDepartment.department_id.in_(dept_ids))
        .order_by(User.id.asc())
    )).all()
    members_by_dept: dict[int, list[DepartmentMember]] = {d_id: [] for d_id in dept_ids}
    for dept_id, user in member_rows:
        members_by_dept[dept_id].append(DepartmentMember.model_validate(user))

    # View-shops per department.
    shop_rows = (await db.execute(
        select(Shop).where(Shop.view_department_id.in_(dept_ids)).order_by(Shop.shop_code.asc())
    )).scalars().all()
    shops_by_dept: dict[int, list[DepartmentShop]] = {d_id: [] for d_id in dept_ids}
    for shop in shop_rows:
        shops_by_dept[shop.view_department_id].append(DepartmentShop(
            shop_code=shop.shop_code, shop_name=shop.shop_name,
        ))

    return [
        DepartmentOut(
            id=d.id,
            tenant_id=d.tenant_id,
            name=d.name,
            members=members_by_dept.get(d.id, []),
            view_shops=shops_by_dept.get(d.id, []),
            created_at=d.created_at,
        )
        for d in depts
    ]


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
    depts = (await db.execute(
        select(Department).where(Department.tenant_id == scope).order_by(Department.id.asc())
    )).scalars().all()
    return ApiResponse(data=await _hydrate(db, depts))


@router.post("", response_model=ApiResponse[DepartmentOut])
async def create_department(
    body: DepartmentCreate,
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    if not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可创建部门")
    scope = _scope_for(actor, body.tenant_id)

    dup = (await db.execute(
        select(Department).where(
            Department.tenant_id == scope, Department.name == body.name,
        )
    )).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="部门名称已存在")

    dept = Department(tenant_id=scope, name=body.name, created_by=actor.id)
    db.add(dept)
    await db.flush()

    if body.member_ids:
        await _set_members(db, dept, body.member_ids)
    if body.view_shop_codes:
        await _set_view_shops(db, dept, body.view_shop_codes)

    await db.commit()
    await db.refresh(dept)
    return ApiResponse(data=(await _hydrate(db, [dept]))[0])


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
    changes_name = "name" in sent and body.name is not None
    changes_view_shops = "view_shop_codes" in sent and body.view_shop_codes is not None
    changes_members = "member_ids" in sent and body.member_ids is not None

    if changes_name and not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可修改部门名称")
    if changes_view_shops and not _can_manage(actor):
        raise HTTPException(status_code=403, detail="仅超级管理员可调整部门视角店铺")
    if changes_members and not _can_assign_members(actor):
        raise HTTPException(status_code=403, detail="无权调整部门成员")

    if changes_name and body.name != dept.name:
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

    if changes_members:
        await _set_members(db, dept, body.member_ids or [])
    if changes_view_shops:
        await _set_view_shops(db, dept, body.view_shop_codes or [])

    await db.commit()
    await db.refresh(dept)
    return ApiResponse(data=(await _hydrate(db, [dept]))[0])


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

    member_n = await db.scalar(
        select(func.count(UserDepartment.user_id)).where(UserDepartment.department_id == dept_id)
    )
    if member_n:
        raise HTTPException(
            status_code=400, detail=f"部门下还有 {member_n} 位成员，请先迁出后再删除",
        )

    await db.delete(dept)
    await db.commit()
    return ApiResponse(data={"deleted": dept_id})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _set_members(db: AsyncSession, dept: Department, member_ids: list[int]) -> None:
    """Replace this department's member list. Validates each id belongs
    to the same tenant and is not a super_admin / platform_admin."""
    if member_ids:
        users = (await db.execute(select(User).where(User.id.in_(member_ids)))).scalars().all()
        if len(users) != len(set(member_ids)):
            raise HTTPException(status_code=400, detail="部分成员账号不存在")
        for u in users:
            if u.tenant_id != dept.tenant_id:
                raise HTTPException(status_code=400, detail=f"用户 {u.username} 不属于该企业")
            if u.role in (ROLE_PLATFORM_ADMIN, ROLE_TENANT_SUPER_ADMIN):
                raise HTTPException(status_code=400, detail=f"超级管理员 {u.username} 不能归属部门")

    # Wipe + reseed the department's M2M link list — much simpler than diff.
    existing = (await db.execute(
        select(UserDepartment).where(UserDepartment.department_id == dept.id)
    )).scalars().all()
    for link in existing:
        await db.delete(link)
    await db.flush()
    for uid in member_ids:
        db.add(UserDepartment(user_id=uid, department_id=dept.id))


async def _set_view_shops(db: AsyncSession, dept: Department, shop_codes: list[str]) -> None:
    """Replace this department's view-shop list.

    Implementation: any shop in this tenant currently pointing at this
    dept gets its view_department_id cleared, then shop_codes are pointed
    here. Because Shop.view_department_id is single-valued, picking a
    shop already owned by another department automatically takes it away
    from that other department (one-shop ↔ one-view-dept).
    """
    # Clear current view-deps that point here.
    await db.execute(
        sa_update(Shop)
        .where(Shop.view_department_id == dept.id)
        .values(view_department_id=None)
    )
    if not shop_codes:
        return
    # Point the selected shops at this dept. Shops missing from the table
    # are silently ignored — the admin shouldn't normally see them in the
    # picker, but it's safer than 400-ing the whole request.
    res = await db.execute(
        sa_update(Shop)
        .where(Shop.tenant_id == dept.tenant_id, Shop.shop_code.in_(shop_codes))
        .values(view_department_id=dept.id)
    )
    _ = res  # rowcount is informational only
