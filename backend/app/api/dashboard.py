from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import User
from ..schemas import ApiResponse
from ..security import get_current_user
from ..services import dashboard_service as svc

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _tenant_for(user: User) -> int:
    if user.tenant_id is None:
        raise HTTPException(status_code=400, detail="平台管理员请在企业内查看数据")
    return user.tenant_id


def _parse_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    v = value.strip()
    if not v or v == "all":
        return None
    items = [s.strip() for s in v.split(",") if s.strip()]
    if not items or "all" in items:
        return None
    return items


def _common(
    start_date: date = Query(..., description="范围起"),
    end_date: date = Query(..., description="范围止"),
    granularity: str = Query("day", regex="^(day|week|month|year)$"),
    shop_code: str = Query("all", description="店铺 code，多个以逗号分隔；'all' 表示全部"),
    owner: str = Query("all", description="负责人，多个以逗号分隔；'all' 表示全部"),
    category: str = Query("all", description="类目，多个以逗号分隔；'all' 表示全部"),
    view_department_id: int | None = Query(
        None, description="部门视角 — 限定为该部门下的店铺",
    ),
):
    return {
        "start_date": start_date,
        "end_date": end_date,
        "granularity": granularity,
        "shop_codes": _parse_csv(shop_code),
        "owners": _parse_csv(owner),
        "categories": _parse_csv(category),
        "view_department_id": view_department_id,
    }


@router.get("/kpi", response_model=ApiResponse[dict])
async def kpi(
    params: dict = Depends(_common),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = _tenant_for(user)
    data = await svc.get_kpis(
        db, tenant_id=tid,
        scope_owners=svc.effective_scope_owners(user),
        user=user,
        **params,
    )
    return ApiResponse(data=data)


@router.get("/trend", response_model=ApiResponse[dict])
async def trend(
    metric: str = Query("sales"),
    params: dict = Depends(_common),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = _tenant_for(user)
    data = await svc.get_trend(
        db, tenant_id=tid, metric=metric,
        scope_owners=svc.effective_scope_owners(user),
        user=user,
        **params,
    )
    return ApiResponse(data=data)


@router.get("/category", response_model=ApiResponse[list[dict]])
async def category(
    start_date: date = Query(...),
    end_date: date = Query(...),
    shop_code: str = Query("all"),
    owner: str = Query("all"),
    category: str = Query("all"),
    view_department_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = _tenant_for(user)
    data = await svc.get_category_breakdown(
        db, tid, start_date, end_date,
        _parse_csv(shop_code), _parse_csv(owner), _parse_csv(category),
        scope_owners=svc.effective_scope_owners(user),
        view_department_id=view_department_id,
        user=user,
    )
    return ApiResponse(data=data)


@router.get("/filters", response_model=ApiResponse[dict])
async def filters(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = _tenant_for(user)
    data = await svc.get_filters(
        db, tid, scope_owners=svc.effective_scope_owners(user),
    )
    return ApiResponse(data=data)
