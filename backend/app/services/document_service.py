"""文档服务：上传、新建笔记、解析、索引、增删改查、回收站、版本历史、导出。

本模块是 LocalMind「写入闭环」在现有技术栈（FastAPI + PostgreSQL）下的落点：
- `create_note`：不经过文件上传，直接把正文写成 `.md` 并建索引；
- `update_document`：正文变更时**快照旧版 + 写回磁盘 + 重建索引**三件事一起做，
  解决此前「改了库里的 content_text，磁盘文件没变、检索结果也没变」的脱节问题；
- `soft_delete_*` / `restore_*` / `purge_*`：软删除 + 回收站，替代此前的硬删除；
- `export_all`：把全部笔记导出为带 YAML front-matter 的 Markdown 目录树（zip）。
"""
from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import (
    ConflictError,
    EmbeddingUnavailableError,
    NotFoundError,
    ParseError,
    ValidationError,
)
from app.core.logging import get_logger
from app.models import Chunk, Document, NoteLink, NoteRevision, Tag
from app.models.document import (
    STATUS_FAILED,
    STATUS_INDEXED,
    STATUS_PARTIAL,
    STATUS_PENDING,
    STATUS_PROCESSING,
)
from app.rag.indexer import build_index
from app.services import link_service, parsers
from app.storage import files

logger = get_logger(__name__)

# 列表视图
VIEW_ALL = "all"
VIEW_FAVORITE = "favorite"
VIEW_PINNED = "pinned"
VIEW_RECENT = "recent"
VIEW_NOTE = "note"

# 单篇笔记保留的历史版本数上限（超出后丢弃最旧的，避免快照无限增长）
MAX_REVISIONS = 50


# ---------------- 上传 ----------------
def create_document(db: Session, filename: str, content: bytes) -> tuple[Document, bool]:
    """保存并创建文档记录。返回 (文档, 是否疑似重复)。"""
    if not files.is_allowed(filename):
        raise ValidationError(f"不支持的文件格式：{filename}")

    duplicate = (
        db.execute(
            select(Document).where(
                Document.original_filename == filename,
                Document.file_size == len(content),
                Document.deleted_at.is_(None),
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
        source="upload",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc, duplicate


# ---------------- 新建笔记（应用内写入，写入闭环入口） ----------------
async def create_note(
    db: Session,
    title: str,
    content_text: str = "",
    category_id: uuid.UUID | None = None,
    tags: list[str] | None = None,
    ai_enabled: bool = True,
    source: str = "note",
    source_url: str | None = None,
) -> Document:
    """新建笔记：写盘 `.md` → 建记录 → 构建索引。

    `source` / `source_url` 供网页剪藏复用同一条写入链路
    （`source="web"` + 原始地址），避免再写一份「写盘 + 建索引 + 双链解析」。
    """
    stem = (title or "").strip()
    if not stem:
        raise ValidationError("笔记标题不能为空")
    text = content_text or ""

    rel, ext, size = files.save_note(f"{stem}.md", text)
    doc = Document(
        title=stem,
        original_filename=f"{stem}.md",
        file_path=rel,
        file_type=ext or "md",
        file_size=size,
        content_text=text,
        source=source,
        source_url=source_url,
        status=STATUS_PENDING,
        # 私密笔记从建出来那一刻就不进 AI 检索范围，避免「先建后改」窗口期内
        # 被检索/问答读到
        ai_enabled=ai_enabled,
    )
    if category_id:
        doc.category_id = category_id
    db.add(doc)
    db.commit()
    db.refresh(doc)

    if tags:
        from app.services import tag_service

        tag_service.set_document_tags(db, doc.id, tags)

    await _index_text(db, doc, text)
    # 双向链接：解析本笔记的出链，并让此前指向本标题的未解析链接生效
    link_service.sync_links(db, doc)
    link_service.resolve_pending(db, doc)
    return doc


async def _index_text(db: Session, doc: Document, text: str) -> int:
    """用已知正文建索引，并把处理状态写回文档。"""
    parsed = parsers.ParsedDocument(text=text)
    try:
        count = await build_index(db, doc, parsed)
        doc.chunk_count = count
        doc.status = STATUS_INDEXED
        doc.error_message = None
        db.commit()
        return count
    except EmbeddingUnavailableError as exc:
        # 片段已写入：关键词检索可用，仅语义检索不可用
        doc.status = STATUS_PARTIAL if doc.chunk_count > 0 else STATUS_FAILED
        doc.error_message = str(exc)
        db.commit()
        return doc.chunk_count
    except Exception as exc:  # noqa: BLE001
        doc.status = STATUS_FAILED
        doc.error_message = str(exc)
        db.commit()
        logger.error("文档 %s 建索引失败：%s", doc.id, exc)
        return 0


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
        _sync_links_safe(db, doc)
        logger.info("文档 %s 处理完成，片段数 %s", document_id, count)
    except EmbeddingUnavailableError as exc:
        db.rollback()
        doc = db.get(Document, document_id)
        if doc:
            # 片段已写入数据库：关键词检索可用，仅语义检索不可用
            doc.status = STATUS_PARTIAL if doc.chunk_count > 0 else STATUS_FAILED
            doc.error_message = str(exc)
            db.commit()
            _sync_links_safe(db, doc)
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
    view: str = VIEW_ALL,
) -> tuple[int, list[Document]]:
    """文档列表。默认排除回收站；view 支持 全部/收藏/置顶/最近访问/我的笔记。

    `selectinload(Document.tags)` 消除 N+1：`DocumentOut` 含 `tags`，
    否则每行都要再查一次标签（一页最多 100 行 = 101 次查询）。
    """
    stmt = (
        select(Document)
        .options(selectinload(Document.tags))
        .where(Document.deleted_at.is_(None))
    )

    if view == VIEW_FAVORITE:
        stmt = stmt.where(Document.is_favorite.is_(True))
    elif view == VIEW_PINNED:
        stmt = stmt.where(Document.is_pinned.is_(True))
    elif view == VIEW_NOTE:
        stmt = stmt.where(Document.source == "note")
    elif view == VIEW_RECENT:
        stmt = stmt.where(Document.last_viewed_at.is_not(None))

    if category_id:
        stmt = stmt.where(Document.category_id == category_id)
    if tag:
        stmt = stmt.where(Document.tags.any(Tag.name == tag))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(Document.title.ilike(like), Document.original_filename.ilike(like))
        )

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    if view == VIEW_RECENT:
        order_col = Document.last_viewed_at
    else:
        order_col = Document.created_at if sort == "created_at" else Document.updated_at
    # 置顶永远排在最前
    stmt = stmt.order_by(Document.is_pinned.desc(), order_col.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
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


# ---------------- 更新 ----------------
def _snapshot(db: Session, doc: Document, note: str, content: str | None = None) -> None:
    """把正文快照写入版本历史，并裁剪超出上限的旧记录。"""
    text = content if content is not None else (doc.content_text or "")
    db.add(
        NoteRevision(
            document_id=doc.id,
            title=doc.title,
            content_text=text,
            char_count=len(text),
            note=note,
        )
    )
    db.flush()
    stale = (
        db.execute(
            select(NoteRevision.id)
            .where(NoteRevision.document_id == doc.id)
            .order_by(NoteRevision.created_at.desc())
            .offset(MAX_REVISIONS)
        )
        .scalars()
        .all()
    )
    if stale:
        db.query(NoteRevision).filter(NoteRevision.id.in_(stale)).delete(
            synchronize_session=False
        )
    db.commit()


async def update_document(
    db: Session,
    document_id: uuid.UUID,
    title: str | None = None,
    category_id: uuid.UUID | None = None,
    content_text: str | None = None,
    ai_enabled: bool | None = None,
    base_content_hash: str | None = None,
) -> Document:
    """更新文档元数据与正文。

    正文发生变更时会一次做三件事，缺一不可：
    1) 把**变更前**的正文快照写入 `note_revisions`（版本历史）；
    2) 把新正文**写回磁盘文件**——否则磁盘 `.md` 与库内正文脱节，
       「Markdown 可迁移」的承诺不成立；
    3) **重建索引**——否则检索到的仍是旧内容。

    **乐观锁**：客户端把开始编辑时的 `content_hash` 通过 `base_content_hash` 回传，
    与库中当前正文指纹不一致时拒绝保存（409）。这解决的是一个会**静默丢内容**的场景：
    用 VS Code 改了 `.md`、同时应用内也在编辑，谁后保存谁覆盖，另一份无声消失。
    """
    doc = get_document(db, document_id)

    if content_text is not None and base_content_hash is not None:
        current = hashlib.sha256((doc.content_text or "").encode("utf-8")).hexdigest()
        if base_content_hash != current:
            raise ConflictError(
                "这篇笔记的正文已被其它地方修改（可能是在编辑器里改了同一个文件，"
                "或另一个标签页在编辑）。为避免覆盖对方的改动，本次保存已取消；"
                "请刷新查看最新内容后再决定如何合并。"
            )

    if title is not None:
        doc.title = title
    if category_id is not None:
        doc.category_id = category_id
    if ai_enabled is not None:
        doc.ai_enabled = ai_enabled

    old_content = doc.content_text or ""
    content_changed = content_text is not None and content_text != old_content
    if content_changed:
        _snapshot(db, doc, note="编辑保存", content=old_content)
        doc.content_text = content_text
        doc.source = "note"

    db.commit()
    db.refresh(doc)

    if content_changed:
        # 只有纯文本格式才能安全回写：PDF/DOCX 是二进制容器，
        # 把正文当纯文本写回去会直接毁掉原文件。
        if doc.file_type in parsers.TEXT_EXTENSIONS:
            try:
                files.write_text(doc.file_path, content_text or "")
                doc.file_size = len((content_text or "").encode("utf-8"))
                db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("正文写回磁盘失败（库内正文已更新）：%s", exc)
        else:
            logger.info(
                "二进制格式 .%s 不回写磁盘，仅更新库内正文（原文件保持不动）",
                doc.file_type,
            )
        # 保存是主要意图：嵌入不可用时降级为 partial，不能因为没向量就存不进去
        await reindex_document(db, document_id, strict=False)
        db.refresh(doc)
        # 正文变了，出链也要跟着重建
        link_service.sync_links(db, doc)
    return doc


def batch_operation(
    db: Session,
    action: str,
    ids: list[uuid.UUID],
    category_id: uuid.UUID | None = None,
    tags: list[str] | None = None,
    value: bool = True,
) -> dict:
    """对多篇文档执行同一操作，**逐条返回结果**。

    刻意不做成「全成功或全回滚」：用户批量整理时更希望「能做的先做掉」，
    并把失败项列出来自己处理，而不是因为其中一篇不存在就整批失败、
    还得逐个重试。因此每条单独提交，失败只影响该条。
    """
    from app.services import tag_service

    ok: list[str] = []
    failed: list[dict] = []
    for doc_id in ids:
        try:
            if action == "delete":
                soft_delete_document(db, doc_id)
            elif action == "restore":
                restore_document(db, doc_id)
            elif action == "purge":
                purge_document(db, doc_id)
            elif action in ("favorite", "pin"):
                doc = get_document(db, doc_id)
                if action == "favorite":
                    doc.is_favorite = bool(value)
                else:
                    doc.is_pinned = bool(value)
                db.commit()
            elif action == "move":
                doc = get_document(db, doc_id)
                doc.category_id = category_id
                db.commit()
            elif action == "tag":
                # **追加**语义：保留原有标签，只把新标签并进去。
                # set_document_tags 是覆盖式的，批量场景下直接调用会把
                # 一批文档原有的标签全部抹掉——那是不可逆的内容损失。
                doc = get_document(db, doc_id)
                existing = [t.name for t in doc.tags]
                merged = existing + [n for n in (tags or []) if n not in existing]
                tag_service.set_document_tags(db, doc_id, merged)
            else:
                raise ValidationError(f"不支持的批量操作：{action}")
            ok.append(str(doc_id))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed.append({"id": str(doc_id), "error": str(exc) or exc.__class__.__name__})

    logger.info("批量操作 %s：成功 %s / 失败 %s", action, len(ok), len(failed))
    return {
        "action": action,
        "requested": len(ids),
        "ok_count": len(ok),
        "ok": ok,
        "failed": failed,
    }


def set_favorite(db: Session, document_id: uuid.UUID, value: bool) -> Document:
    doc = get_document(db, document_id)
    doc.is_favorite = bool(value)
    db.commit()
    db.refresh(doc)
    return doc


def set_pinned(db: Session, document_id: uuid.UUID, value: bool) -> Document:
    doc = get_document(db, document_id)
    doc.is_pinned = bool(value)
    db.commit()
    db.refresh(doc)
    return doc


def touch_viewed(db: Session, document_id: uuid.UUID) -> Document:
    """记录一次访问（用于「最近访问」）。"""
    doc = get_document(db, document_id)
    doc.last_viewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(doc)
    return doc


# ---------------- 删除 / 回收站 ----------------
def soft_delete_document(db: Session, document_id: uuid.UUID) -> Document:
    """移入回收站（软删除）：原文件与索引都保留，可随时恢复。"""
    doc = get_document(db, document_id)
    if doc.deleted_at is None:
        doc.deleted_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(doc)
    return doc


def restore_document(db: Session, document_id: uuid.UUID) -> Document:
    """从回收站恢复。"""
    doc = get_document(db, document_id)
    if doc.deleted_at is not None:
        doc.deleted_at = None
        db.commit()
        db.refresh(doc)
    return doc


def _purge_rows(db: Session, doc: Document) -> None:
    """显式清理子表，再删文档本身。

    `chunks` 存在自引用（parent_id → chunks.id），数据库级 ON DELETE CASCADE 会先
    把子块删掉，导致 ORM 级联删除时报「expected to delete N row(s); M were matched」
    告警；改用批量 DELETE，行为确定且不产生噪音日志。
    """
    db.query(Chunk).filter(Chunk.document_id == doc.id).delete(
        synchronize_session=False
    )
    db.query(NoteRevision).filter(NoteRevision.document_id == doc.id).delete(
        synchronize_session=False
    )
    # 出链显式删除（指向本笔记的入链由 DB 的 ON DELETE SET NULL 处理）
    db.query(NoteLink).filter(NoteLink.source_document_id == doc.id).delete(
        synchronize_session=False
    )
    db.flush()
    db.delete(doc)


def purge_document(db: Session, document_id: uuid.UUID) -> None:
    """彻底删除：数据库记录（级联 chunks / revisions）+ 原始文件。"""
    doc = get_document(db, document_id)
    rel = doc.file_path
    _purge_rows(db, doc)
    db.commit()
    files.delete_file(rel)


def empty_trash(db: Session) -> int:
    """清空回收站，返回删除的文档数。"""
    docs = list(
        db.execute(select(Document).where(Document.deleted_at.is_not(None)))
        .scalars()
        .all()
    )
    rels = [d.file_path for d in docs]
    for d in docs:
        _purge_rows(db, d)
    db.commit()
    for rel in rels:
        files.delete_file(rel)
    return len(docs)


def purge_expired_trash(db: Session, days: int) -> int:
    """彻底删除回收站中超过保留期的文档，返回删除数量。

    `days <= 0` 表示**永不自动清理**（默认）：
    「我以为它还在」的内容被系统悄悄删掉，比一直占着磁盘更糟，
    所以这个功能默认关闭，必须用户显式设置保留天数。
    """
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    docs = list(
        db.execute(
            select(Document).where(
                Document.deleted_at.is_not(None),
                Document.deleted_at <= cutoff,
            )
        )
        .scalars()
        .all()
    )
    if not docs:
        return 0
    rels = [d.file_path for d in docs]
    for d in docs:
        _purge_rows(db, d)
    db.commit()
    for rel in rels:
        files.delete_file(rel)
    logger.info("回收站保留期清理：删除 %s 篇（删除时间早于 %s）", len(docs), cutoff.isoformat())
    return len(docs)


def list_trash(db: Session, page: int = 1, page_size: int = 20) -> tuple[int, list[Document]]:
    stmt = (
        select(Document)
        .options(selectinload(Document.tags))
        .where(Document.deleted_at.is_not(None))
        .order_by(Document.deleted_at.desc())
    )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = list(
        db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    )
    return total, items


# ---------------- 版本历史 ----------------
def list_revisions(db: Session, document_id: uuid.UUID) -> list[NoteRevision]:
    get_document(db, document_id)
    return list(
        db.execute(
            select(NoteRevision)
            .where(NoteRevision.document_id == document_id)
            .order_by(NoteRevision.created_at.desc())
        )
        .scalars()
        .all()
    )


def get_revision(
    db: Session, document_id: uuid.UUID, revision_id: uuid.UUID
) -> NoteRevision:
    rev = db.get(NoteRevision, revision_id)
    if not rev or rev.document_id != document_id:
        raise NotFoundError("历史版本不存在")
    return rev


async def restore_revision(
    db: Session, document_id: uuid.UUID, revision_id: uuid.UUID
) -> Document:
    """把正文回滚到某个历史版本。

    回滚前先对**当前**正文做一次快照，保证回滚本身也可逆。
    """
    rev = get_revision(db, document_id, revision_id)
    doc = get_document(db, document_id)

    _snapshot(db, doc, note="回滚前的自动备份")
    doc.content_text = rev.content_text or ""
    if rev.title:
        doc.title = rev.title
    doc.source = "note"
    db.commit()

    if doc.file_type in parsers.TEXT_EXTENSIONS:
        try:
            files.write_text(doc.file_path, doc.content_text or "")
            doc.file_size = len((doc.content_text or "").encode("utf-8"))
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("回滚写回磁盘失败（库内正文已回滚）：%s", exc)
    else:
        logger.info("二进制格式 .%s 回滚时不动原文件", doc.file_type)

    # 回滚是主要意图：同样不能因为嵌入不可用而回滚失败
    await reindex_document(db, document_id, strict=False)
    db.refresh(doc)
    return doc


# ---------------- 重建索引 ----------------
def _sync_links_safe(db: Session, doc: Document) -> None:
    """重建出链；失败只记日志，绝不影响索引流程。"""
    try:
        link_service.sync_links(db, doc)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("解析双链失败（不影响索引）：%s", exc)


async def reindex_document(
    db: Session, document_id: uuid.UUID, strict: bool = True
) -> int:
    """重建索引。

    `strict=False` 时，嵌入不可用只把文档降级为 `partial`
    （片段已在、关键词检索可用、语义检索不可用）而**不抛异常**——
    用于「保存正文 / 回滚版本」这类以保存为主要意图的链路：
    用户改完内容不该因为 embedding 配额耗尽而存不进去。
    显式的「重建索引」接口保持 strict=True，让调用方明确知道没重建完。
    """
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
        if strict:
            raise
        logger.warning("文档 %s 重建索引降级为 partial（关键词检索仍可用）：%s", doc.id, exc)
        return doc.chunk_count
    except Exception as exc:  # noqa: BLE001
        doc.status = STATUS_FAILED
        doc.error_message = str(exc)
        db.commit()
        raise
    finally:
        # 链接只需与正文一致：即使向量化失败（关键词检索仍可用）也应维护
        _sync_links_safe(db, doc)


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


def _front_matter(doc: Document) -> str:
    """生成 YAML front-matter（对齐 LocalMind 的 Markdown 元数据规范）。"""
    tags = ", ".join(t.name for t in doc.tags)
    lines = [
        "---",
        f"id: {doc.id}",
        f"title: {doc.title}",
        f"createdAt: {doc.created_at.isoformat() if doc.created_at else ''}",
        f"updatedAt: {doc.updated_at.isoformat() if doc.updated_at else ''}",
        f"tags: [{tags}]",
        f"type: {doc.file_type}",
        f"source: {doc.source}",
        f"aiEnabled: {str(doc.ai_enabled).lower()}",
        "---",
        "",
    ]
    return "\n".join(lines)


def site_bundle(db: Session, include_private: bool = False) -> dict:
    """导出静态站所需的全部数据（不渲染 HTML，由前端用同一套管线渲染）。

    **为什么渲染放在前端**：App 的 Markdown 管线是 `markdown-it({html: true})`
    + **DOMPurify** 净化。`html: true` 是必须的（语雀/Notion 导出的笔记含
    `<font style=...>` 这类内联标签）。后端没有 DOMPurify，而**手写 HTML
    净化器正是最危险的事**——本项目历史上就因为用正则黑名单做净化被
    `<svg/onload=...>` 绕过，才换成 DOMPurify。
    所以后端只提供数据，渲染交给前端已有的、已验证过的那条管线，
    顺带保证「静态站的样子 = 应用里预览的样子」。

    `include_private=False`（默认）时排除 `ai_enabled=False` 的私密笔记。
    静态站是拿来分享/发布的，把私密笔记默认卷进去风险太大；
    要导出就显式勾选，并会在返回值里告诉你排除了几篇。
    """
    stmt = select(Document).where(Document.deleted_at.is_(None))
    docs = list(db.execute(stmt.order_by(Document.title)).scalars().all())

    excluded = 0
    notes: list[dict] = []
    for doc in docs:
        if not include_private and doc.ai_enabled is False:
            excluded += 1
            continue
        notes.append(
            {
                "id": str(doc.id),
                "title": doc.title,
                "content_text": doc.content_text or "",
                "category": doc.category.name if doc.category else None,
                "tags": [t.name for t in doc.tags],
                "source": doc.source,
                "source_url": doc.source_url,
                # 带上私密标记：前端据此在本地过滤，不必为「是否含私密」
                # 再请求一次（一次拿全量，两种导出共用）
                "ai_enabled": doc.ai_enabled,
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            }
        )

    return {
        "generated_at": datetime.now().isoformat(),
        "count": len(notes),
        "excluded_private": excluded,
        "include_private": include_private,
        "notes": notes,
        "note": (
            "渲染与打包在前端完成：复用应用自身的 markdown-it + DOMPurify 管线，"
            "保证静态站与应用内预览一致。"
        ),
    }


def export_all(db: Session) -> dict:
    """把全部笔记导出为 Markdown 目录树（zip），落到 data/exports/。

    这是「知识内容可迁移」的兜底：导出物带 YAML front-matter，
    不依赖本应用也能直接读走全部正文（回收站内容不导出）。
    """
    settings.exports_path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"localmind_export_{ts}.zip"
    dest = settings.exports_path / name

    docs = list(
        db.execute(select(Document).where(Document.deleted_at.is_(None))).scalars().all()
    )
    manifest: list[str] = []
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            stem = (doc.title or "untitled").strip() or "untitled"
            # 上传文档的 title 本身就是文件名（如 vue.md），
            # 直接拼 .md 会出现 vue.md.md，这里先去一次扩展名
            if stem.lower().endswith((".md", ".markdown", ".txt")):
                stem = stem.rsplit(".", 1)[0] or stem
            cat = doc.category.name if doc.category else "未分类"
            arc = f"notes/{cat}/{stem}.md"
            body = doc.content_text or ""
            zf.writestr(arc, _front_matter(doc) + body)
            manifest.append(arc)
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "app": "KnowledgeHub",
                    "exported_at": datetime.now().isoformat(),
                    "count": len(manifest),
                    "files": manifest,
                },
                ensure_ascii=False,
                indent=1,
            ),
        )

    return {
        "name": name,
        "path": str(dest),
        "count": len(manifest),
        "size": dest.stat().st_size,
    }


def index_status(db: Session) -> dict:
    """统计索引状态（不含回收站）。"""
    rows = db.execute(
        select(Document.status, func.count())
        .where(Document.deleted_at.is_(None))
        .group_by(Document.status)
    ).all()
    counts = {status: n for status, n in rows}
    chunk_total = db.execute(select(func.count()).select_from(Chunk)).scalar_one()
    embedded = db.execute(
        select(func.count()).select_from(Chunk).where(Chunk.embedding.is_not(None))
    ).scalar_one()
    note_count = db.execute(
        select(func.count())
        .select_from(Document)
        .where(Document.deleted_at.is_(None), Document.source == "note")
    ).scalar_one()
    trash_count = db.execute(
        select(func.count()).select_from(Document).where(Document.deleted_at.is_not(None))
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
        "note_total": note_count,
        "trash_total": trash_count,
    }
