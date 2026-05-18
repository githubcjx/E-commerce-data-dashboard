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


def _common(
    end_date: date = Query(..., description="结束日期"),
    granularity: str = Query("day", regex="^(day|week|month)$"),
    shop_code: str = Query("all"),
    owner: str = Query("all"),
    category: str = Query("all"),
):
    return {
        "end_date": end_date,
        "granularity": granularity,
        "shop_code": shop_code,
        "owner": owner,
        "category": category,
    }


@router.get("/kpi", response_model=ApiResponse[dict])
async def kpi(
    params: dict = Depends(_common),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = _tenant_for(user)
    data = await svc.get_kpis(db, tenant_id=tid, **params)
    return ApiResponse(data=data)


@router.get("/trend", response_model=ApiResponse[dict])
async def trend(
    metric: str = Query("sales"),
    params: dict = Depends(_common),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = _tenant_for(user)
    data = await svc.get_trend(db, tenant_id=tid, metric=metric, **params)
    return ApiResponse(data=data)


@router.get("/category", response_model=ApiResponse[list[dict]])
async def category(
    end_date: date = Query(...),
    granularity: str = Query("day", regex="^(day|week|month)$"),
    shop_code: str = Query("all"),
    owner: str = Query("all"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = _tenant_for(user)
    data = await svc.get_category_breakdown(db, tid, end_date, granularity, shop_code, owner)
    return ApiResponse(data=data)


@router.get("/filters", response_model=ApiResponse[dict])
async def filters(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tid = _tenant_for(user)
    data = await svc.get_filters(db, tid)
    return ApiResponse(data=data)
