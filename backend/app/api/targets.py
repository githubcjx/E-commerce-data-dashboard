"""人员目标完成情况 — 目标编辑、完成率、排名、月末提醒.

Auth model (per the agreed design):
  - PUT (set targets)            → require_tenant_super_admin (super + platform)
  - GET list / ranking / reminder → require_backend_access (any admin can view)
  - GET /me                       → any logged-in user, limited to their scope

platform_admin has no own tenant — they pass ?tenant_id= like the users API.
"""

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import ROLE_PLATFORM_ADMIN, User
from ..schemas import ApiResponse, TargetSave
from ..security import (
    get_current_user, require_backend_access, require_tenant_super_admin,
)
from ..services import target_service as svc
from ..services.dashboard_service import effective_scope_owners

router = APIRouter(prefix="/api/targets", tags=["targets"])

_YM_RE = re.compile(r"^\d{4}-\d{2}$")


def _tenant_for(actor: User, explicit_tenant_id: int | None) -> int:
    if actor.role == ROLE_PLATFORM_ADMIN:
        if explicit_tenant_id is None:
            raise HTTPException(status_code=400, detail="平台管理员需指定 tenant_id")
        return explicit_tenant_id
    if actor.tenant_id is None:
        raise HTTPException(status_code=400, detail="无所属企业")
    return actor.tenant_id


def _valid_ym(year_month: str) -> None:
    if not _YM_RE.match(year_month or ""):
        raise HTTPException(status_code=400, detail="月份格式应为 YYYY-MM")


@router.get("", response_model=ApiResponse[dict])
async def list_targets(
    year_month: str = Query(..., description="YYYY-MM"),
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    """Every 负责人 + target/actual/completion for the month — the editor grid."""
    _valid_ym(year_month)
    tid = _tenant_for(actor, tenant_id)
    today = date.today()
    owners = await svc.all_owners(db, tid)
    tmap = await svc.targets_map(db, tid, year_month)
    actuals = await svc.owner_actuals(db, tid, year_month, today)
    rows = [svc.progress_row(o, tmap.get(o), actuals.get(o)) for o in owners]
    return ApiResponse(data={"year_month": year_month, "rows": rows})


@router.put("", response_model=ApiResponse[dict])
async def save_targets(
    body: TargetSave,
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_tenant_super_admin),
    db: AsyncSession = Depends(get_db),
):
    tid = _tenant_for(actor, tenant_id)
    saved = await svc.save_targets(db, tid, body.year_month, body.items)
    return ApiResponse(data={"saved": saved})


@router.get("/ranking", response_model=ApiResponse[dict])
async def ranking(
    year_month: str = Query(..., description="YYYY-MM"),
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    _valid_ym(year_month)
    tid = _tenant_for(actor, tenant_id)
    data = await svc.get_ranking(db, tid, year_month, date.today())
    return ApiResponse(data=data)


@router.get("/me", response_model=ApiResponse[dict])
async def my_targets(
    year_month: str = Query(..., description="YYYY-MM"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A user's own goal progress — limited to the 负责人 in their data scope."""
    _valid_ym(year_month)
    if user.tenant_id is None:
        raise HTTPException(status_code=400, detail="无所属企业")
    today = date.today()
    scope = effective_scope_owners(user)  # None=all, []=none, [...]=limited
    actuals = await svc.owner_actuals(
        db, user.tenant_id, year_month, today, scope_owners=scope,
    )
    tmap = await svc.targets_map(db, user.tenant_id, year_month)
    if scope is None:
        owners = await svc.all_owners(db, user.tenant_id)
    elif not scope:
        owners = []
    else:
        owners = sorted(scope)
    rows = [svc.progress_row(o, tmap.get(o), actuals.get(o)) for o in owners]
    return ApiResponse(data={"year_month": year_month, "rows": rows})


@router.get("/reminder", response_model=ApiResponse[dict])
async def reminder(
    tenant_id: int | None = Query(default=None),
    actor: User = Depends(require_backend_access),
    db: AsyncSession = Depends(get_db),
):
    """月末最后工作日提醒 — only meaningful inside a tenant context."""
    if actor.role == ROLE_PLATFORM_ADMIN and tenant_id is None:
        return ApiResponse(data={
            "should_remind": False, "year_month": None,
            "missing_owners": [], "missing_count": 0,
        })
    tid = _tenant_for(actor, tenant_id)
    data = await svc.get_reminder(db, tid, date.today())
    return ApiResponse(data=data)
