"""Batch import orchestration: parse → UPSERT → batch bookkeeping."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal, engine
from ..models import ImportBatch, SalesRecord
from .excel_parser import parse_workbook

log = logging.getLogger(__name__)

_DIALECT = engine.dialect.name
if _DIALECT == "postgresql":
    from sqlalchemy.dialects.postgresql import insert as dialect_insert  # noqa: E402
else:
    from sqlalchemy.dialects.sqlite import insert as dialect_insert  # noqa: E402

BATCH_SIZE = 1000


async def run_import(batch_id: str, file_path: str, tenant_id: int) -> None:
    """Background task: parse the file and upsert records scoped to `tenant_id`."""
    inserted = updated = failed = total = 0
    error_msg: str | None = None
    try:
        async with SessionLocal() as session:
            buffer: list[dict] = []
            for rec in parse_workbook(file_path):
                rec["batch_id"] = batch_id
                rec["tenant_id"] = tenant_id
                buffer.append(rec)
                total += 1
                if len(buffer) >= BATCH_SIZE:
                    ins, upd = await _upsert(session, buffer)
                    inserted += ins
                    updated += upd
                    buffer.clear()
            if buffer:
                ins, upd = await _upsert(session, buffer)
                inserted += ins
                updated += upd
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("Import failed: %s", exc)
        error_msg = str(exc)[:1900]
        failed = total

    async with SessionLocal() as session:
        await session.execute(
            update(ImportBatch)
            .where(ImportBatch.id == batch_id)
            .values(
                total_rows=total,
                inserted_rows=inserted,
                updated_rows=updated,
                failed_rows=failed,
                status="failed" if error_msg else "success",
                error_message=error_msg,
                finished_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    try:
        Path(file_path).unlink(missing_ok=True)
    except OSError:
        pass


async def _upsert(session: AsyncSession, rows: list[dict]) -> tuple[int, int]:
    """ON CONFLICT DO UPDATE for (tenant_id, shop_code, date, sku)."""
    if not rows:
        return 0, 0

    keys = [(r["tenant_id"], r["shop_code"], r["date"], r["sku"]) for r in rows]
    existing = await session.execute(
        select(SalesRecord.tenant_id, SalesRecord.shop_code, SalesRecord.date, SalesRecord.sku)
        .where(tuple_(
            SalesRecord.tenant_id, SalesRecord.shop_code, SalesRecord.date, SalesRecord.sku
        ).in_(keys))
    )
    existing_set = {(t, s, d, k) for t, s, d, k in existing.all()}
    updated = sum(1 for k in keys if k in existing_set)
    inserted = len(keys) - updated

    stmt = dialect_insert(SalesRecord).values(rows)
    update_cols = {c.name: c for c in stmt.excluded if c.name not in ("id", "created_at", "tenant_id")}
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "shop_code", "date", "sku"],
        set_=update_cols,
    )
    await session.execute(stmt)
    return inserted, updated


async def rollback_batch(session: AsyncSession, batch_id: str, tenant_id: int) -> int:
    """Delete all rows tied to a batch_id (scoped to tenant). Returns deleted count."""
    res = await session.execute(
        delete(SalesRecord)
        .where(SalesRecord.batch_id == batch_id)
        .where(SalesRecord.tenant_id == tenant_id)
    )
    await session.commit()
    return res.rowcount or 0
