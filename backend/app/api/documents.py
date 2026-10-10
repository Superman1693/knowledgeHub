"""文档相关路由。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.schemas.document import DocumentDetail, DocumentListOut, DocumentOut, DocumentUpdate
from app.services import document_service
from app.storage import files

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", status_code=201)
async def upload_documents(
    background: BackgroundTasks,
    files_in: list[UploadFile] = File(..., alias="files"),
    db: Session = Depends(get_db),
) -> dict:
    """上传一个或多个文档，返回创建结果并异步触发处理。"""
    results = []
    for upload in files_in:
        content = await upload.read()
        if len(content) > settings.max_upload_bytes:
            raise ValidationError(
                f"文件 {upload.filename} 超过大小限制（{settings.max_upload_mb}MB）"
            )
        doc, duplicate = document_service.create_document(
            db, upload.filename or "untitled", content
        )
        background.add_task(document_service.process_document, doc.id)
        results.append(
            {
                "document": DocumentOut.model_validate(doc).model_dump(mode="json"),
                "duplicate_warning": duplicate,
            }
        )
    return {"items": results}


@router.get("", response_model=DocumentListOut)
def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category_id: uuid.UUID | None = None,
    tag: str | None = None,
    q: str | None = None,
    sort: str = Query("updated_at"),
    db: Session = Depends(get_db),
) -> DocumentListOut:
    total, items = document_service.list_documents(
        db, page, page_size, category_id, tag, q, sort
    )
    return DocumentListOut(
        total=total,
        page=page,
        page_size=page_size,
        items=[DocumentOut.model_validate(d) for d in items],
    )


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> DocumentDetail:
    doc = document_service.get_document(db, document_id)
    return DocumentDetail.model_validate(doc)


@router.put("/{document_id}", response_model=DocumentOut)
def update_document(
    document_id: uuid.UUID, payload: DocumentUpdate, db: Session = Depends(get_db)
) -> DocumentOut:
    doc = document_service.update_document(
        db, document_id, payload.title, payload.category_id, payload.content_text
    )
    return DocumentOut.model_validate(doc)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    document_service.delete_document(db, document_id)


@router.post("/{document_id}/reindex")
async def reindex_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    count = await document_service.reindex_document(db, document_id)
    return {"chunk_count": count}


@router.get("/{document_id}/export")
def export_document(
    document_id: uuid.UUID, fmt: str = Query("md"), db: Session = Depends(get_db)
) -> dict:
    name, content = document_service.export_document(db, document_id, fmt)
    return {"filename": name, "content": content}


@router.get("/{document_id}/file")
def download_original(document_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    doc = document_service.get_document(db, document_id)
    path = files.abs_path(doc.file_path)
    return FileResponse(path, filename=doc.original_filename)
