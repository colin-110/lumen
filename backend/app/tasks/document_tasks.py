from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid

import app.db.base  # noqa: F401 - registers every model so relationship() string refs resolve
from app.core.celery_app import celery_app
from app.core.config import settings
from app.crud.crud_document import document as crud_document
from app.db.session import AsyncSessionLocal
from app.models.document import DocumentStatus
from app.schemas.document import DocumentUpdate
from app.services import retrieval, semantic_cache
from app.services.chunking import split_text
from app.services.document_parser import UnsupportedDocumentError, extract_text
from app.services.storage import storage

logger = logging.getLogger(__name__)


async def _process_document(document_id: str) -> None:
    async with AsyncSessionLocal() as db:
        doc = await crud_document.get(db, id=uuid.UUID(document_id))
        if not doc:
            logger.error("Document %s not found; skipping", document_id)
            return

        await crud_document.update(db, db_obj=doc, obj_in=DocumentUpdate(status=DocumentStatus.PROCESSING))

        suffix = os.path.splitext(doc.filename)[1] or ""
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = tmp.name

            if not await storage.download_file(doc.storage_key, tmp_path):
                await crud_document.update(
                    db,
                    db_obj=doc,
                    obj_in=DocumentUpdate(status=DocumentStatus.FAILED, error_message="Download from storage failed"),
                )
                return

            text = extract_text(tmp_path, doc.filename)
            if not text.strip():
                await crud_document.update(
                    db,
                    db_obj=doc,
                    obj_in=DocumentUpdate(
                        status=DocumentStatus.FAILED,
                        error_message="No extractable text found (scanned/empty document?)",
                    ),
                )
                return

            chunks = split_text(text, chunk_size=settings.CHUNK_SIZE, chunk_overlap=settings.CHUNK_OVERLAP)
            chunk_count = await retrieval.index_chunks(
                document_id=doc.id,
                filename=doc.filename,
                owner_id=doc.owner_id,
                organization_id=doc.organization_id,
                chunks=chunks,
            )

            await crud_document.update(
                db,
                db_obj=doc,
                obj_in=DocumentUpdate(status=DocumentStatus.COMPLETED, chunk_count=chunk_count),
            )
            org_id = str(doc.organization_id) if doc.organization_id else None
            await semantic_cache.invalidate(org_id, str(doc.owner_id))
            logger.info("Indexed %d chunks for document %s (%s)", chunk_count, document_id, doc.filename)

        except UnsupportedDocumentError as exc:
            await crud_document.update(
                db, db_obj=doc, obj_in=DocumentUpdate(status=DocumentStatus.FAILED, error_message=str(exc))
            )
        except Exception as exc:  # noqa: BLE001 - convert to a stored failure, not a task crash
            logger.error("Failed to process document %s: %s", document_id, exc, exc_info=True)
            await crud_document.update(
                db, db_obj=doc, obj_in=DocumentUpdate(status=DocumentStatus.FAILED, error_message=str(exc)[:1000])
            )
            raise
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, acks_late=True)
def process_document(self, document_id: str):
    """Parse, chunk, embed and index a document. Retries on transient failure
    (storage/Qdrant hiccups); permanent failures (bad file, unsupported type)
    are caught inside `_process_document` and recorded on the row instead of
    retried."""
    try:
        asyncio.run(_process_document(document_id))
    except Exception as exc:
        logger.warning("Retrying document %s after error: %s", document_id, exc)
        raise self.retry(exc=exc)
