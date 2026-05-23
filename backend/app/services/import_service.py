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
    inserted = updated = 0
    crashed = False
    error_msg: str | None = None
    parse_stats: dict[str, int] = {}
    # Track conflict keys within the current un-flushed buffer; if the same
    # (tenant, shop, date, sku) appears again we overwrite the earlier entry
    # to keep last-write-wins. Without this, PG raises
    # "ON CONFLICT DO UPDATE command cannot affect row a second time".
    seen_keys: dict[tuple, int] = {}
    try:
        async with SessionLocal() as session:
            buffer: list[dict] = []
            for rec in parse_workbook(file_path, stats=parse_stats):
                rec["batch_id"] = batch_id
                rec["tenant_id"] = tenant_id
                key = (tenant_id, rec["shop_code"], rec["date"], rec["sku"])
                if key in seen_keys:
                    buffer[seen_keys[key]] = rec
                    continue
                seen_keys[key] = len(buffer)
                buffer.append(rec)
                if len(buffer) >= BATCH_SIZE:
                    ins, upd = await _upsert(session, buffer)
                    inserted += ins
                    updated += upd
                    buffer.clear()
                    seen_keys.clear()
            if buffer:
                ins, upd = await _upsert(session, buffer)
                inserted += ins
                updated += upd
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("Import failed: %s", exc)
        crashed = True
        error_msg = str(exc)[:1900]

    # Soft-skipped rows: parser saw them but they're unusable. Surface to user.
    skipped_no_keys = parse_stats.get("skipped_no_keys", 0)
    skipped_bad_date = parse_stats.get("skipped_bad_date", 0)
    skipped = skipped_no_keys + skipped_bad_date

    scanned = parse_stats.get("scanned", inserted + updated + skipped)

    if crashed:
        # On crash, count everything we tried to import as failed.
        failed = scanned
        status = "failed"
    else:
        failed = skipped
        status = "success"
        if skipped:
            parts = []
            if skipped_no_keys:
                parts.append(f"缺少 店铺编码/日期/分类 {skipped_no_keys} 行")
            if skipped_bad_date:
                parts.append(f"日期无法识别 {skipped_bad_date} 行")
            error_msg = "已跳过：" + "；".join(parts)

    async with SessionLocal() as session:
        await session.execute(
            update(ImportBatch)
            .where(ImportBatch.id == batch_id)
            .values(
                total_rows=scanned,
                inserted_rows=inserted,
                updated_rows=updated,
                failed_rows=failed,
                status=status,
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
    """Delete all rows tied to a batch_id (scoped to tenant). Returns deleted count.

    Also flips the batch's own status to 'rolled_back' so the UI can render
    an unmistakable 已回滚 badge even after the page reloads — without this,
    a rolled-back batch still looked like a successful one and the user had
    no persistent confirmation of the operation.

    Idempotent: re-rolling an already-rolled-back batch returns 0 and is a
    no-op apart from refreshing the status.
    """
    res = await session.execute(
        delete(SalesRecord)
        .where(SalesRecord.batch_id == batch_id)
        .where(SalesRecord.tenant_id == tenant_id)
    )
    deleted = res.rowcount or 0
    await session.execute(
        update(ImportBatch)
        .where(ImportBatch.id == batch_id)
        .where(ImportBatch.tenant_id == tenant_id)
        .values(status="rolled_back")
    )
    await session.commit()
    return deleted
