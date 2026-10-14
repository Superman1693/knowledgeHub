"""文档相关路由。

注意路由声明顺序：`/trash`、`/export-all`、`/from-url` 这类**静态路径**必须写在
`/{document_id}` 之前，否则会被当成 UUID 解析并返回 422。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.schemas.document import (
    BatchDocumentRequest,
    ChunkOut,
    ClipUrlIn,
    DocumentDetail,
    DocumentListOut,
    DocumentOut,
    DocumentUpdate,
    NoteCreate,
    RevisionDetail,
    RevisionOut,
)
from app.services import document_service, link_service, web_clip_service
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
        # 先按声明大小拦截，避免超限文件被整份读入内存
        declared = getattr(upload, "size", None)
        if declared is not None and declared > settings.max_upload_bytes:
            raise ValidationError(
                f"文件 {upload.filename} 超过大小限制（{settings.max_upload_mb}MB）"
            )
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


@router.post("/notes", response_model=DocumentDetail, status_code=201)
async def create_note(payload: NoteCreate, db: Session = Depends(get_db)) -> DocumentDetail:
    """新建笔记：不经过文件上传，直接把正文写盘并建立索引。

    这是「写入闭环」的入口 —— 此前新增内容只能靠上传文件。
    """
    doc = await document_service.create_note(
        db,
        title=payload.title,
        content_text=payload.content_text,
        category_id=payload.category_id,
        tags=payload.tags,
        ai_enabled=payload.ai_enabled,
    )
    return DocumentDetail.model_validate(doc)


@router.post("/from-url", response_model=DocumentDetail, status_code=201)
async def create_from_url(payload: ClipUrlIn, db: Session = Depends(get_db)) -> DocumentDetail:
    """网页剪藏：抓取 URL → 提取正文 → 转 Markdown → 存为文档。

    这是「输入漏斗」的入口——此前看到好文章只能复制粘贴（格式乱、元数据丢、
    且脱离知识库不能双链与检索）。

    安全：该接口让服务端替用户访问外部 URL，因此对所有目标（含每一跳重定向）
    做 SSRF 校验，拒绝内网 / 本机 / 云元数据地址。详见
    `app/services/web_clip_service.py` 模块文档。
    """
    doc, _info = await web_clip_service.clip_to_document(
        db, payload.url, allow_duplicate=payload.allow_duplicate
    )
    return DocumentDetail.model_validate(doc)


@router.get("/trash", response_model=DocumentListOut)
def list_trash(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> DocumentListOut:
    """回收站列表（软删除的文档）。"""
    total, items = document_service.list_trash(db, page, page_size)
    return DocumentListOut(
        total=total,
        page=page,
        page_size=page_size,
        items=[DocumentOut.model_validate(d) for d in items],
    )


@router.post("/trash/empty")
def empty_trash(db: Session = Depends(get_db)) -> dict:
    """清空回收站（彻底删除，不可恢复）。"""
    return {"removed": document_service.empty_trash(db)}


@router.post("/trash/purge-expired")
def purge_expired_trash(db: Session = Depends(get_db)) -> dict:
    """按保留期清理回收站（`TRASH_RETENTION_DAYS`，**0 = 不清理**）。

    正常由启动流程自动执行，这里提供可手动触发/可测试的入口。
    """
    days = settings.trash_retention_days
    removed = document_service.purge_expired_trash(db, days)
    return {
        "removed": removed,
        "retention_days": days,
        "note": (
            "保留天数为 0：永不自动清理（默认）"
            if days <= 0
            else f"已清理删除时间超过 {days} 天的文档"
        ),
    }


@router.get("/site-bundle")
def site_bundle(
    include_private: bool = Query(
        False, description="是否包含私密笔记（ai_enabled=false）；默认排除"
    ),
    db: Session = Depends(get_db),
) -> dict:
    """静态站导出所需的全量数据（JSON）。

    只提供数据，**渲染与打包在前端**——复用应用自身的 markdown-it + DOMPurify
    管线，保证静态站与应用内预览一致，也避免在后端手写 HTML 净化器
    （那是最容易出安全漏洞的地方）。
    """
    return document_service.site_bundle(db, include_private=include_private)


@router.post("/export-all")
def export_all(db: Session = Depends(get_db)) -> dict:
    """把全部笔记导出为带 front-matter 的 Markdown 目录树（zip）。

    用 POST 而非 GET：该操作会在服务端生成一个新的导出产物（文件）。
    """
    return document_service.export_all(db)


@router.get("/link-targets")
def link_targets(db: Session = Depends(get_db)) -> dict:
    """可被 `[[ ]]` 链接引用的笔记（供编辑器补全与正文链接点击跳转）。

    `titles` 保留给只关心标题的调用方；`items` 带 ID，
    前端据此把正文里的 `[[标题#锚点]]` 变成能点的链接。
    """
    items = link_service.note_targets(db)
    return {
        "total": len(items),
        "titles": [i["title"] for i in items],
        "items": items,
    }


@router.post("/batch")
def batch_documents(
    payload: BatchDocumentRequest, db: Session = Depends(get_db)
) -> dict:
    """批量操作：删除 / 恢复 / 彻底删除 / 收藏 / 置顶 / 移动分类 / 打标签。

    ⚠️ 静态路径必须声明在 `/{document_id}` 之前，否则 `batch` 会被当成 UUID 解析 → 422。
    逐条返回成败（不做整批事务），详见 `document_service.batch_operation`。
    """
    return document_service.batch_operation(
        db,
        payload.action,
        payload.ids,
        category_id=payload.category_id,
        tags=payload.tags,
        value=payload.value,
    )


@router.get("", response_model=DocumentListOut)
def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category_id: uuid.UUID | None = None,
    tag: str | None = None,
    q: str | None = None,
    sort: str = Query("updated_at"),
    view: str = Query("all", description="all | favorite | pinned | recent | note"),
    db: Session = Depends(get_db),
) -> DocumentListOut:
    total, items = document_service.list_documents(
        db, page, page_size, category_id, tag, q, sort, view
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


@router.get("/{document_id}/chunks", response_model=list[ChunkOut])
def list_chunks(document_id: uuid.UUID, db: Session = Depends(get_db)) -> list[ChunkOut]:
    """文档的知识片段列表（用于引用定位与片段预览）。"""
    chunks = document_service.list_chunks(db, document_id)
    return [
        ChunkOut(
            id=c.id,
            chunk_index=c.chunk_index,
            heading=c.heading,
            page_no=c.page_no,
            content=c.content,
            token_count=c.token_count,
            has_embedding=c.embedding is not None,
        )
        for c in chunks
    ]


@router.post("/{document_id}/view", response_model=DocumentOut)
def touch_viewed(document_id: uuid.UUID, db: Session = Depends(get_db)) -> DocumentOut:
    """记录一次访问，用于「最近访问」。"""
    return DocumentOut.model_validate(document_service.touch_viewed(db, document_id))


@router.get("/{document_id}/attachments")
def document_attachments(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """列出当前笔记正文中引用的附件（通过 Markdown URL 提取）。"""
    doc = document_service.get_document(db, document_id)
    content = doc.content_text or ""
    refs = files.extract_attachment_refs(content)
    items = []
    for rel in refs:
        exists = files.abs_path(rel).exists()
        sub, name = rel.split("/", 1)[1].split("/", 1)
        items.append({
            "path": rel,
            "url": f"/api/attachments/file/{sub}/{name}",
            "exists": exists,
        })
    return {"total": len(items), "items": items}


@router.post("/{document_id}/favorite", response_model=DocumentOut)
def set_favorite(
    document_id: uuid.UUID,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
) -> DocumentOut:
    doc = document_service.set_favorite(db, document_id, bool(payload.get("value")))
    return DocumentOut.model_validate(doc)


@router.post("/{document_id}/pin", response_model=DocumentOut)
def set_pinned(
    document_id: uuid.UUID,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
) -> DocumentOut:
    doc = document_service.set_pinned(db, document_id, bool(payload.get("value")))
    return DocumentOut.model_validate(doc)


@router.post("/{document_id}/restore", response_model=DocumentOut)
def restore_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> DocumentOut:
    """从回收站恢复。"""
    return DocumentOut.model_validate(document_service.restore_document(db, document_id))


@router.delete("/{document_id}/purge", status_code=204)
def purge_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    """彻底删除（不可恢复）：记录 + 原始文件一并清除。"""
    document_service.purge_document(db, document_id)


@router.get("/{document_id}/links")
def document_links(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """双向链接：出链 + 反向链接 + 未解析链接数。"""
    document_service.get_document(db, document_id)
    return link_service.summary(db, document_id)


@router.get("/{document_id}/revisions", response_model=list[RevisionOut])
def list_revisions(
    document_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[RevisionOut]:
    """正文历史版本列表（不含全文）。"""
    return [
        RevisionOut.model_validate(r)
        for r in document_service.list_revisions(db, document_id)
    ]


@router.get("/{document_id}/revisions/{revision_id}", response_model=RevisionDetail)
def get_revision(
    document_id: uuid.UUID, revision_id: uuid.UUID, db: Session = Depends(get_db)
) -> RevisionDetail:
    """单个历史版本的全文（用于对比查看）。"""
    return RevisionDetail.model_validate(
        document_service.get_revision(db, document_id, revision_id)
    )


@router.post("/{document_id}/revisions/{revision_id}/restore", response_model=DocumentDetail)
async def restore_revision(
    document_id: uuid.UUID, revision_id: uuid.UUID, db: Session = Depends(get_db)
) -> DocumentDetail:
    """把正文回滚到该历史版本（回滚前会自动备份当前版本）。"""
    doc = await document_service.restore_revision(db, document_id, revision_id)
    return DocumentDetail.model_validate(doc)


@router.post("/{document_id}/reveal")
def reveal_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """在系统文件管理器中定位原始文件（本地应用，仅本机有效）。"""
    doc = document_service.get_document(db, document_id)
    try:
        path = files.abs_path(doc.file_path)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    ok = files.reveal_in_file_manager(path)
    return {
        "ok": ok,
        "path": str(path),
        "message": "已在文件管理器中定位" if ok else "无法打开文件管理器，请确认原始文件是否存在",
    }


@router.put("/{document_id}", response_model=DocumentDetail)
async def update_document(
    document_id: uuid.UUID, payload: DocumentUpdate, db: Session = Depends(get_db)
) -> DocumentDetail:
    """更新元数据与正文。

    正文变更会触发「快照旧版 → 写回磁盘 → 重建索引」，因此本接口是异步的。
    传入 `base_content_hash` 时启用乐观锁：与库中当前正文指纹不一致 → 409。
    """
    doc = await document_service.update_document(
        db,
        document_id,
        payload.title,
        payload.category_id,
        payload.content_text,
        payload.ai_enabled,
        payload.base_content_hash,
    )
    return DocumentDetail.model_validate(doc)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    """移入回收站（软删除），可在「回收站」中恢复或彻底删除。"""
    document_service.soft_delete_document(db, document_id)


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
