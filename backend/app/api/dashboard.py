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
    """Parse the picker's comma-separated value into a list, or None for
    "全部" / empty. The sentinel "all" (legacy) is treated as None too.
    """
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
    subtract_fixed: bool = Query(True, description="公司利润率是否减去固定利润率"),
    view_department_id: int | None = Query(
        None,
        description="超级管理员: 以哪个部门视角查看 (用于解算 公司利润率)",
    ),
):
    return {
        "start_date": start_date,
        "end_date": end_date,
        "granularity": granularity,
        "shop_codes": _parse_csv(shop_code),
        "owners": _parse_csv(owner),
        "categories": _parse_csv(category),
        "subtract_fixed": subtract_fixed,
        "view_department_id": view_department_id,
    }


@router.get("/kpi", response_model=ApiResponse[dict])
async def kpi(
    params: dict = Depends(_common),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = _tenant_for(user)
    view_dept = params.pop("view_department_id", None)
    rate, has_rate = await svc.resolve_fixed_rate(db, user, view_dept)
    data = await svc.get_kpis(
        db, tenant_id=tid,
        scope_owners=svc.effective_scope_owners(user),
        fixed_profit_rate=rate, has_fixed_rate=has_rate,
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
    view_dept = params.pop("view_department_id", None)
    rate, has_rate = await svc.resolve_fixed_rate(db, user, view_dept)
    data = await svc.get_trend(
        db, tenant_id=tid, metric=metric,
        scope_owners=svc.effective_scope_owners(user),
        fixed_profit_rate=rate, has_fixed_rate=has_rate,
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
    subtract_fixed: bool = Query(True),
    view_department_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = _tenant_for(user)
    rate, has_rate = await svc.resolve_fixed_rate(db, user, view_department_id)
    data = await svc.get_category_breakdown(
        db, tid, start_date, end_date,
        _parse_csv(shop_code), _parse_csv(owner), _parse_csv(category),
        subtract_fixed=subtract_fixed,
        scope_owners=svc.effective_scope_owners(user),
        fixed_profit_rate=rate, has_fixed_rate=has_rate,
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
