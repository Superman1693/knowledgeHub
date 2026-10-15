"""PDF 批注路由。

路径刻意分成两组：
- `/api/documents/{id}/annotations*` —— 归入文档（「这份 PDF 的批注」）
- `/api/annotations/{aid}*`         —— 批注自身的标识（改、删、出卡片）

⚠️ 静态段必须声明在动态段之前（项目约定第 5 条）：
`/annotations/export` 若排在 `/{annotation_id}` 之后，`export` 会被当成 UUID
解析并返回 422 —— 历史上 `/link-targets` 就是这么踩的。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.annotation import (
    AnnotationCreate,
    AnnotationExportOut,
    AnnotationListOut,
    AnnotationOut,
    AnnotationUpdate,
)
from app.services import assist_service, pdf_annotation_service

router = APIRouter(prefix="/api", tags=["annotations"])


# ---------------------------------------------------------------------------
# 按文档操作
# ---------------------------------------------------------------------------

@router.get("/documents/{document_id}/annotations", response_model=AnnotationListOut)
def list_annotations(
    document_id: uuid.UUID,
    page: int | None = Query(None, ge=1, description="只取某一页的批注"),
    db: Session = Depends(get_db),
) -> AnnotationListOut:
    # 文档不存在要 404 而不是静默返回空列表（否则前端以为「这篇没批注」）
    pdf_annotation_service.ensure_document_exists(db, document_id)
    items = pdf_annotation_service.list_annotations(db, document_id, page_no=page)
    return AnnotationListOut(
        # total 是**该文档全部**批注数，不是过滤后的条数：
        # 前端要显示「本文档共 N 条」，按页过滤时这个数字不该跟着缩水
        total=pdf_annotation_service.count_annotations(db, document_id),
        items=[AnnotationOut.model_validate(a) for a in items],
    )


@router.post(
    "/documents/{document_id}/annotations",
    response_model=AnnotationOut,
    status_code=201,
)
def create_annotation(
    document_id: uuid.UUID,
    payload: AnnotationCreate,
    db: Session = Depends(get_db),
) -> AnnotationOut:
    ann = pdf_annotation_service.create_annotation(
        db,
        document_id,
        page_no=payload.page_no,
        quote=payload.quote,
        rects=[r.model_dump() for r in payload.rects],
        prefix=payload.prefix,
        suffix=payload.suffix,
        rotation=payload.rotation,
        color=payload.color,
        comment=payload.comment,
    )
    return AnnotationOut.model_validate(ann)


@router.post(
    "/documents/{document_id}/annotations/export", response_model=AnnotationExportOut
)
async def export_annotations(
    document_id: uuid.UUID, db: Session = Depends(get_db)
) -> AnnotationExportOut:
    """把批注导出成一篇可检索、可双链的 Markdown 笔记（幂等）。"""
    doc, count, created = await pdf_annotation_service.export_annotations(db, document_id)
    return AnnotationExportOut(
        document_id=doc.id,
        title=doc.title,
        annotation_count=count,
        created=created,
    )


# ---------------------------------------------------------------------------
# 按批注操作
# ---------------------------------------------------------------------------

@router.put("/annotations/{annotation_id}", response_model=AnnotationOut)
def update_annotation(
    annotation_id: uuid.UUID,
    payload: AnnotationUpdate,
    db: Session = Depends(get_db),
) -> AnnotationOut:
    ann = pdf_annotation_service.update_annotation(
        db,
        annotation_id,
        color=payload.color,
        comment=payload.comment,
        # Pydantic 无法区分「没传 comment」与「传了 null」，
        # 用 `model_fields_set` 判断才能支持「清空批注」这个真实操作
        touch_comment="comment" in payload.model_fields_set,
    )
    return AnnotationOut.model_validate(ann)


@router.delete("/annotations/{annotation_id}", status_code=204)
def delete_annotation(annotation_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    pdf_annotation_service.delete_annotation(db, annotation_id)


@router.post("/annotations/{annotation_id}/cards")
async def annotation_cards(
    annotation_id: uuid.UUID,
    count: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),
) -> dict:
    """由批注生成闪卡（复用已有的「选中文字 → 出题」链路）。"""
    ann = pdf_annotation_service.get_annotation(db, annotation_id)
    text = pdf_annotation_service.quote_for_card(db, annotation_id)
    return await assist_service.assist(
        db, text, "cards", document_id=ann.document_id, count=count
    )
