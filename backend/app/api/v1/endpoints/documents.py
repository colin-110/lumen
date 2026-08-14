from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.crud.crud_document import document as crud_document
from app.db.session import get_db
from app.models.document import DocumentStatus
from app.models.user import User
from app.schemas.document import DocumentCreate, DocumentRead, DocumentUpdate
from app.services import semantic_cache
from app.services.qdrant_client import delete_document_points
from app.services.storage import storage
from app.tasks.document_tasks import ingest_document_inline, process_document

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".log"}


async def _read_bounded(file: UploadFile, limit: int) -> bytes:
    """Read the upload, aborting as soon as it exceeds `limit`.

    `await file.read()` buffers the entire body *before* the size check, so a
    multi-gigabyte POST was fully spooled to the container's disk only to be
    rejected with a 413. Reading in chunks and stopping at the limit bounds
    what an unauthenticated-by-size request can cost us.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {limit // (1024 * 1024)}MB limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Upload a document; parsing/embedding happens asynchronously via Celery."""
    await enforce_rate_limit(f"upload:{current_user.id}", settings.RATE_LIMIT_UPLOAD_PER_MINUTE)

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing")

    # Reject on the declared length first when the client provides one, so an
    # oversized upload is refused before its body is transferred at all.
    declared = request.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit",
        )

    suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await _read_bounded(file, settings.MAX_UPLOAD_BYTES)
    file_size = len(content)
    if file_size == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    doc_id = uuid.uuid4()
    object_name = f"{current_user.organization_id or current_user.id}/{doc_id}/{file.filename}"

    doc_in = DocumentCreate(
        id=doc_id,
        filename=file.filename,
        file_type=file.content_type or suffix.lstrip("."),
        file_size=file_size,
        storage_key=object_name,
        owner_id=current_user.id,
        organization_id=current_user.organization_id,
    )
    doc = await crud_document.create(db, obj_in=doc_in)

    uploaded = await storage.upload_file(content, object_name, file.content_type)
    if not uploaded:
        await crud_document.update(
            db,
            db_obj=doc,
            obj_in=DocumentUpdate(
                status=DocumentStatus.FAILED, error_message="Storage upload failed"
            ),
        )
        raise HTTPException(status_code=502, detail="Failed to store document")

    try:
        if settings.INGEST_INLINE:
            # Small-footprint mode: no Celery worker process to hand off to, so
            # parse/chunk/embed/index runs here after the response is sent. See
            # INGEST_INLINE in core/config.py for the durability trade-off.
            background_tasks.add_task(ingest_document_inline, str(doc.id))
        else:
            process_document.delay(str(doc.id))
    except Exception as exc:
        # The broker is down. Without this the row sat at PENDING forever with
        # the object already in storage, and the user saw a 500 for an upload
        # that had in fact been stored — no error on the row, no retry, no way
        # to tell it apart from a document still in the queue.
        logger.error("Could not enqueue ingestion for %s", doc.id, exc_info=True)
        await crud_document.update(
            db,
            db_obj=doc,
            obj_in=DocumentUpdate(
                status=DocumentStatus.FAILED,
                error_message="Could not queue processing (task broker unavailable). Please retry.",
            ),
        )
        raise HTTPException(
            status_code=503,
            detail="Document stored but processing could not be queued. Please retry.",
        ) from exc

    return doc


@router.get("/", response_model=list[DocumentRead])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    return await crud_document.get_multi_for_tenant(
        db,
        owner_id=current_user.id,
        organization_id=current_user.organization_id,
        skip=skip,
        limit=limit,
    )


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    doc = await crud_document.get_for_tenant(
        db, id=document_id, owner_id=current_user.id, organization_id=current_user.organization_id
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> None:
    doc = await crud_document.get_for_tenant(
        db, id=document_id, owner_id=current_user.id, organization_id=current_user.organization_id
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    # Visible to the whole organization, deletable only by the person who
    # uploaded it. 403 rather than 404 because the document demonstrably
    # exists — the user can see it in the list and cite it in chat.
    if doc.owner_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Only the person who uploaded this document can delete it"
        )

    # Order matters. The database row is the index of record for everything
    # else, so it goes last: if Qdrant or object storage fails, the document
    # is still listed and still deletable rather than becoming an invisible
    # row whose chunks keep answering questions.
    await delete_document_points(str(doc.id))
    await storage.delete_file(doc.storage_key)
    await semantic_cache.invalidate_for_document(
        str(doc.organization_id) if doc.organization_id else None,
        str(doc.owner_id),
        str(doc.id),
    )
    await crud_document.remove(db, db_obj=doc)
