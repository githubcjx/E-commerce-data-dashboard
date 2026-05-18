from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import DashboardLayout, User
from ..schemas import ApiResponse, LayoutPayload
from ..security import get_current_user

router = APIRouter(prefix="/api/layout", tags=["layout"])

DEFAULT_LAYOUT_JSON = '{"order":["sales","refundRate","grossMargin","profit","profitRate","shipPct","adPct"],"sections":["trend","categoryTable"]}'


def _tenant_for(user: User) -> int:
    if user.tenant_id is None:
        raise HTTPException(status_code=400, detail="平台管理员无个人布局")
    return user.tenant_id


@router.get("", response_model=ApiResponse[dict])
async def get_layout(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tid = _tenant_for(user)
    row = (await db.execute(
        select(DashboardLayout).where(
            DashboardLayout.tenant_id == tid,
            DashboardLayout.user_id == user.id,
        )
    )).scalar_one_or_none()
    if not row:
        return ApiResponse(data={"layout_json": DEFAULT_LAYOUT_JSON})
    return ApiResponse(data={"layout_json": row.layout_json, "updated_at": row.updated_at.isoformat()})


@router.put("", response_model=ApiResponse[dict])
async def put_layout(payload: LayoutPayload, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tid = _tenant_for(user)
    row = (await db.execute(
        select(DashboardLayout).where(
            DashboardLayout.tenant_id == tid,
            DashboardLayout.user_id == user.id,
        )
    )).scalar_one_or_none()
    if row:
        row.layout_json = payload.layout_json
    else:
        row = DashboardLayout(tenant_id=tid, user_id=user.id, layout_json=payload.layout_json)
        db.add(row)
    await db.commit()
    return ApiResponse(data={"saved": True})
