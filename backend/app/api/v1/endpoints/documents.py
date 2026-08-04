from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.crud.crud_document import document as crud_document
from app.db.session import get_db
from app.models.document import DocumentStatus
from app.models.user import User
from app.schemas.document import DocumentCreate, DocumentRead, DocumentUpdate
from app.services.qdrant_client import delete_document_points
from app.services.storage import storage
from app.tasks.document_tasks import process_document

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Upload a document; parsing/embedding happens asynchronously via Celery."""
    await enforce_rate_limit(f"upload:{current_user.id}", settings.RATE_LIMIT_UPLOAD_PER_MINUTE)

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing")

    suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    file_size = len(content)
    if file_size == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if file_size > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit",
        )

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
            obj_in=DocumentUpdate(status=DocumentStatus.FAILED, error_message="Storage upload failed"),
        )
        raise HTTPException(status_code=502, detail="Failed to store document")

    process_document.delay(str(doc.id))
    return doc


@router.get("/", response_model=list[DocumentRead])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    return await crud_document.get_multi_by_owner(db, owner_id=current_user.id, skip=skip, limit=limit)


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    doc = await crud_document.get_for_owner(db, id=document_id, owner_id=current_user.id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> None:
    doc = await crud_document.get_for_owner(db, id=document_id, owner_id=current_user.id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    await storage.delete_file(doc.storage_key)
    delete_document_points(str(doc.id))
    await crud_document.remove(db, db_obj=doc)
