"""文档服务：上传、解析、索引、增删改查、导出。"""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.exceptions import (
    EmbeddingUnavailableError,
    NotFoundError,
    ParseError,
    ValidationError,
)
from app.core.logging import get_logger
from app.models import Chunk, Document, Tag
from app.models.document import (
    STATUS_FAILED,
    STATUS_INDEXED,
    STATUS_PARTIAL,
    STATUS_PENDING,
    STATUS_PROCESSING,
)
from app.rag.indexer import build_index
from app.services import parsers
from app.storage import files

logger = get_logger(__name__)


# ---------------- 上传 ----------------
def create_document(
    db: Session, filename: str, content: bytes
) -> tuple[Document, bool]:
    """保存并创建文档记录。返回 (文档, 是否疑似重复)。"""
    if not files.is_allowed(filename):
        raise ValidationError(f"不支持的文件格式：{filename}")

    duplicate = (
        db.execute(
            select(Document).where(
                Document.original_filename == filename,
                Document.file_size == len(content),
            )
        )
        .scalars()
        .first()
        is not None
    )

    rel, ext, size = files.save_upload(filename, content)
    doc = Document(
        title=filename,
        original_filename=filename,
        file_path=rel,
        file_type=ext,
        file_size=size,
        status=STATUS_PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc, duplicate


# ---------------- 处理（后台任务）----------------
async def process_document(document_id: uuid.UUID) -> None:
    """完整处理流程：解析 → 分块 → 嵌入 → 索引 → 状态。"""
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if not doc:
            return
        doc.status = STATUS_PROCESSING
        doc.error_message = None
        db.commit()

        path = files.abs_path(doc.file_path)
        parsed = parsers.parse(path, doc.file_type)
        doc.content_text = parsed.text
        db.commit()

        count = await build_index(db, doc, parsed)
        doc.chunk_count = count
        doc.status = STATUS_INDEXED
        db.commit()
        logger.info("文档 %s 处理完成，片段数 %s", document_id, count)
    except EmbeddingUnavailableError as exc:
        db.rollback()
        doc = db.get(Document, document_id)
        if doc:
            # 片段已写入数据库：关键词检索可用，仅语义检索不可用
            doc.status = STATUS_PARTIAL if doc.chunk_count > 0 else STATUS_FAILED
            doc.error_message = str(exc)
            db.commit()
        logger.warning("文档 %s 未向量化（关键词检索仍可用）：%s", document_id, exc)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        doc = db.get(Document, document_id)
        if doc:
            doc.status = STATUS_FAILED
            doc.error_message = str(exc)
            db.commit()
        logger.error("文档 %s 处理失败：%s", document_id, exc)
    finally:
        db.close()


# ---------------- 查询 ----------------
def list_documents(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    category_id: uuid.UUID | None = None,
    tag: str | None = None,
    q: str | None = None,
    sort: str = "updated_at",
) -> tuple[int, list[Document]]:
    stmt = select(Document)
    if category_id:
        stmt = stmt.where(Document.category_id == category_id)
    if tag:
        stmt = stmt.where(Document.tags.any(Tag.name == tag))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(Document.title.ilike(like), Document.original_filename.ilike(like))
        )

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    order_col = Document.created_at if sort == "created_at" else Document.updated_at
    stmt = stmt.order_by(order_col.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list(db.execute(stmt).scalars().all())
    return total, items


def get_document(db: Session, document_id: uuid.UUID) -> Document:
    doc = db.get(Document, document_id)
    if not doc:
        raise NotFoundError("文档不存在")
    return doc


def list_chunks(db: Session, document_id: uuid.UUID) -> list[Chunk]:
    """返回文档的知识片段（按片段序号升序）。

    用于引用定位：前端据片段 ID 滚动到对应位置并高亮。
    父子检索下只返回**子块**（真正参与检索的片段）；父块是子块内容的拼接，
    仅用于回传给模型，不在片段列表中展示，否则同一段内容会出现两次。
    """
    get_document(db, document_id)
    parent_ids = select(Chunk.parent_id).where(Chunk.parent_id.is_not(None))
    return list(
        db.execute(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .where(Chunk.id.not_in(parent_ids))
            .order_by(Chunk.chunk_index)
        )
        .scalars()
        .all()
    )


def update_document(
    db: Session,
    document_id: uuid.UUID,
    title: str | None = None,
    category_id: uuid.UUID | None = None,
    content_text: str | None = None,
) -> Document:
    doc = get_document(db, document_id)
    if title is not None:
        doc.title = title
    if category_id is not None:
        doc.category_id = category_id
    if content_text is not None:
        doc.content_text = content_text
    db.commit()
    db.refresh(doc)
    return doc


def delete_document(db: Session, document_id: uuid.UUID) -> None:
    """删除文档：数据库记录（级联 chunks）+ 原始文件。"""
    doc = get_document(db, document_id)
    rel = doc.file_path
    db.delete(doc)
    db.commit()
    files.delete_file(rel)


async def reindex_document(db: Session, document_id: uuid.UUID) -> int:
    """重建索引。"""
    doc = get_document(db, document_id)
    if not doc.content_text:
        path = files.abs_path(doc.file_path)
        parsed = parsers.parse(path, doc.file_type)
        doc.content_text = parsed.text
    else:
        parsed = parsers.ParsedDocument(text=doc.content_text)
    doc.status = STATUS_PROCESSING
    db.commit()
    try:
        count = await build_index(db, doc, parsed)
        doc.chunk_count = count
        doc.status = STATUS_INDEXED
        doc.error_message = None
        db.commit()
        return count
    except EmbeddingUnavailableError as exc:
        doc.status = STATUS_PARTIAL if doc.chunk_count > 0 else STATUS_FAILED
        doc.error_message = str(exc)
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        doc.status = STATUS_FAILED
        doc.error_message = str(exc)
        db.commit()
        raise


# ---------------- 导出 ----------------
def export_document(db: Session, document_id: uuid.UUID, fmt: str = "md") -> tuple[str, str]:
    """导出为 Markdown / 文本，返回 (文件名, 内容)。"""
    doc = get_document(db, document_id)
    body = doc.content_text
    if not body:
        chunks = (
            db.execute(
                select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.chunk_index)
            )
            .scalars()
            .all()
        )
        body = "\n\n".join(c.content for c in chunks)
    if not body:
        raise ParseError("该文档没有可导出的文本内容")

    stem = doc.title.rsplit(".", 1)[0] or "document"
    if fmt == "txt":
        return f"{stem}.txt", body
    md = f"# {doc.title}\n\n{body}\n"
    return f"{stem}.md", md


def index_status(db: Session) -> dict:
    """统计索引状态。"""
    rows = db.execute(
        select(Document.status, func.count()).group_by(Document.status)
    ).all()
    counts = {status: n for status, n in rows}
    chunk_total = db.execute(select(func.count()).select_from(Chunk)).scalar_one()
    embedded = db.execute(
        select(func.count()).select_from(Chunk).where(Chunk.embedding.is_not(None))
    ).scalar_one()
    return {
        "document_total": sum(counts.values()),
        "indexed": counts.get(STATUS_INDEXED, 0),
        "partial": counts.get(STATUS_PARTIAL, 0),
        "pending": counts.get(STATUS_PENDING, 0),
        "processing": counts.get(STATUS_PROCESSING, 0),
        "failed": counts.get(STATUS_FAILED, 0),
        "chunk_total": chunk_total,
        "embedded_chunks": embedded,
    }
