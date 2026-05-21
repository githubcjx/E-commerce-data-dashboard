import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import ImportBatch, ROLE_PLATFORM_ADMIN, User
from ..schemas import ApiResponse, ImportBatchOut
from ..security import require_import_access
from ..services.import_service import rollback_batch, run_import

router = APIRouter(prefix="/api/import", tags=["import"])
settings = get_settings()


def _tenant_for(user: User) -> int:
    """Resolve the tenant a regular request runs under.

    platform_admin has no tenant of their own, so they cannot directly import
    or query their own data; they must do that within a tenant context. For
    simplicity we just reject the call here — platform_admin uses /api/tenants.
    """
    if user.tenant_id is None:
        raise HTTPException(status_code=400, detail="平台管理员请在企业内操作")
    return user.tenant_id


@router.post("/upload", response_model=ApiResponse[ImportBatchOut])
async def upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(require_import_access),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_for(user)
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls 文件")

    content = await file.read()
    if len(content) > settings.upload_max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件超过 {settings.upload_max_mb}MB 限制")

    tmp_dir = Path(tempfile.gettempdir()) / "ec_dashboard_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    batch_id = uuid.uuid4().hex
    tmp_path = tmp_dir / f"{batch_id}__{file.filename}"
    tmp_path.write_bytes(content)

    batch = ImportBatch(
        id=batch_id,
        tenant_id=tenant_id,
        user_id=user.id,
        filename=file.filename,
        file_size=len(content),
        status="processing",
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)

    background.add_task(run_import, batch_id, str(tmp_path), tenant_id)
    return ApiResponse(data=ImportBatchOut.model_validate(batch))


@router.get("/batches/{batch_id}", response_model=ApiResponse[ImportBatchOut])
async def get_batch(
    batch_id: str,
    user: User = Depends(require_import_access),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(ImportBatch).where(ImportBatch.id == batch_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="批次不存在")
    if user.role != ROLE_PLATFORM_ADMIN and row.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="无权查看其他企业的批次")
    return ApiResponse(data=ImportBatchOut.model_validate(row))


@router.get("/batches", response_model=ApiResponse[list[ImportBatchOut]])
async def list_batches(
    limit: int = 30,
    user: User = Depends(require_import_access),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_for(user)
    rows = (await db.execute(
        select(ImportBatch)
        .where(ImportBatch.tenant_id == tenant_id)
        .order_by(ImportBatch.created_at.desc())
        .limit(limit)
    )).scalars().all()
    return ApiResponse(data=[ImportBatchOut.model_validate(r) for r in rows])


@router.delete("/batches/{batch_id}", response_model=ApiResponse[dict])
async def rollback(
    batch_id: str,
    user: User = Depends(require_import_access),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_for(user)
    row = (await db.execute(select(ImportBatch).where(ImportBatch.id == batch_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="批次不存在")
    if row.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="无权回滚其他企业的批次")
    deleted = await rollback_batch(db, batch_id, tenant_id)
    return ApiResponse(data={"deleted": deleted})
