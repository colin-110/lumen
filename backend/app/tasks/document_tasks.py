from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path

import app.db.base  # noqa: F401 - registers every model so relationship() string refs resolve
from app.core.celery_app import celery_app, run_async
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

# Failures that are a property of the file, not of the infrastructure. These
# are recorded on the row and never retried; everything else (storage
# timeouts, Qdrant hiccups, a database blip) falls through to Celery's retry.
PERMANENT_ERRORS = (
    UnsupportedDocumentError,
    UnicodeDecodeError,
    ValueError,
)


async def _process_document(document_id: str) -> None:
    async with AsyncSessionLocal() as db:
        doc = await crud_document.get(db, id=uuid.UUID(document_id))
        if not doc:
            logger.error("Document %s not found; skipping", document_id)
            return

        await crud_document.update(
            db, db_obj=doc, obj_in=DocumentUpdate(status=DocumentStatus.PROCESSING)
        )

        suffix = Path(doc.filename).suffix
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = tmp.name

            if not await storage.download_file(doc.storage_key, tmp_path):
                await crud_document.update(
                    db,
                    db_obj=doc,
                    obj_in=DocumentUpdate(
                        status=DocumentStatus.FAILED, error_message="Download from storage failed"
                    ),
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

            chunks = split_text(
                text, chunk_size=settings.CHUNK_SIZE, chunk_overlap=settings.CHUNK_OVERLAP
            )
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
            logger.info(
                "Indexed %d chunks for document %s (%s)", chunk_count, document_id, doc.filename
            )

        except PERMANENT_ERRORS as exc:
            # Nothing about retrying a corrupt file, an unsupported format or
            # text we cannot decode will make it succeed. Retrying them burned
            # four attempts and rewrote the same failure row four times, while
            # occupying a worker slot that a real document could have used.
            logger.info("Document %s failed permanently: %s", document_id, exc)
            await crud_document.update(
                db,
                db_obj=doc,
                obj_in=DocumentUpdate(status=DocumentStatus.FAILED, error_message=str(exc)[:1000]),
            )
        except Exception as exc:
            logger.error("Failed to process document %s: %s", document_id, exc, exc_info=True)
            await crud_document.update(
                db,
                db_obj=doc,
                obj_in=DocumentUpdate(status=DocumentStatus.FAILED, error_message=str(exc)[:1000]),
            )
            raise
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)


async def ingest_document_inline(document_id: str) -> None:
    """Run ingestion in the API process, for deployments running without a
    Celery worker (see settings.INGEST_INLINE).

    Reuses `_process_document` verbatim so the two modes can't drift — the
    only difference is who calls it and what happens on failure. There's no
    retry here: `_process_document` already records permanent failures on the
    row, and a transient failure surfaces as a FAILED document the user can
    re-upload, rather than silently disappearing.
    """
    try:
        await _process_document(document_id)
    except Exception:
        logger.error("Inline ingestion failed for document %s", document_id, exc_info=True)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, acks_late=True)
def process_document(self, document_id: str):
    """Parse, chunk, embed and index a document. Retries on transient failure
    (storage/Qdrant hiccups); permanent failures (bad file, unsupported type)
    are caught inside `_process_document` and recorded on the row instead of
    retried."""
    try:
        # run_async, not asyncio.run: the DB connection pool is shared across
        # tasks and cannot survive its loop being closed. See run_async.
        run_async(_process_document(document_id))
    except Exception as exc:
        logger.warning("Retrying document %s after error: %s", document_id, exc)
        raise self.retry(exc=exc) from exc
