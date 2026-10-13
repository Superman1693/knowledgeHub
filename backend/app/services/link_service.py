"""双向链接服务：解析 `[[标题]]`、维护链接边、查询出链与反向链接。

LocalMind 的「双向链接 / 反向链接」在现有技术栈下的落地：
- 正文保存或重建索引时整篇重解析（先删该文档的全部出链，再按当前正文重建），
  保证链接与正文永远一致，不做增量 diff；
- 目标笔记不存在时**保留标题**（`target_document_id` 为空），前端可提示并一键新建；
- 目标笔记创建后调用 `resolve_pending()` 把此前的未解析链接补上。

依赖方向：本模块只依赖 models，不反向依赖 document_service（避免循环导入）。
"""
from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Document, NoteLink

logger = get_logger(__name__)

# `[[标题]]`、`[[标题|显示别名]]`、`[[标题#锚点]]`；
# 标题不允许换行与中括号。`#` 后是块级引用的锚点（小节标题）。
_LINK_RE = re.compile(r"\[\[([^\[\]\n|#]+?)(?:#([^\[\]\n|]+?))?(?:\|([^\[\]\n]+?))?\]\]")
# 嵌入引用 `![[标题#锚点]]`：把目标内容嵌进当前笔记，语义与普通链接不同
_EMBED_RE = re.compile(r"!\[\[([^\[\]\n|#]+?)(?:#([^\[\]\n|]+?))?(?:\|([^\[\]\n]+?))?\]\]")
# 单篇最多解析的出链数，防止异常正文产生海量边
MAX_LINKS_PER_NOTE = 200


def extract_links(text: str) -> list[dict]:
    """提取正文中的双链，返回 [{title, anchor, is_embed}]（去重、保序）。

    `anchor` 为 None 表示引用整篇；`is_embed` 区分 `![[ ]]` 与 `[[ ]]`。
    去重键是 (标题, 锚点, 是否嵌入) —— 同一篇笔记引用两个不同小节
    是两条合法引用，不能按标题合并。
    """
    out: list[dict] = []
    seen: set[tuple[str, str | None, bool]] = set()

    def _add(title: str, anchor: str | None, is_embed: bool) -> None:
        title = (title or "").strip()
        if not title:
            return
        anchor = (anchor or "").strip() or None
        key = (title.lower(), anchor.lower() if anchor else None, is_embed)
        if key in seen:
            return
        seen.add(key)
        out.append({"title": title, "anchor": anchor, "is_embed": is_embed})

    for m in _EMBED_RE.finditer(text or ""):
        _add(m.group(1), m.group(2), True)
    for m in _LINK_RE.finditer(text or ""):
        # `![[...]]` 的前半段会被 _LINK_RE 匹配到（`!` 不在字符类里），
        # 用负向前查排除掉，否则同一条嵌入会被记成普通链接。
        start = m.start()
        if start > 0 and (text or "")[start - 1] == "!":
            continue
        _add(m.group(1), m.group(2), False)

    return out[:MAX_LINKS_PER_NOTE]


def extract_link_titles(text: str) -> list[str]:
    """提取正文中的双链标题（去重、保序、忽略自反与空标题）。

    保留此函数是为了兼容既有调用方（编辑器补全等只需要标题）；
    新代码请用 `extract_links` 以拿到锚点与嵌入标记。
    """
    titles: list[str] = []
    seen: set[str] = set()
    for item in extract_links(text):
        title = item["title"]
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
        if len(titles) >= MAX_LINKS_PER_NOTE:
            break
    return titles


def _title_index(db: Session, exclude_id: uuid.UUID | None = None) -> dict[str, uuid.UUID]:
    """建立「标题 → 文档 ID」索引。

    上传文档的 title 就是文件名（如 `vue.md`），而用户写链接时通常只写 `[[vue]]`，
    因此同时用「完整标题」和「去掉扩展名的主干」两种键去匹配。
    """
    rows = db.execute(
        select(Document.id, Document.title).where(Document.deleted_at.is_(None))
    ).all()
    index: dict[str, uuid.UUID] = {}
    for doc_id, title in rows:
        if exclude_id is not None and doc_id == exclude_id:
            continue
        raw = (title or "").strip()
        if not raw:
            continue
        index[raw.lower()] = doc_id
        stem = raw.rsplit(".", 1)[0].strip().lower()
        if stem:
            index.setdefault(stem, doc_id)
    return index


def sync_links(db: Session, doc: Document) -> int:
    """按当前正文重建该文档的全部出链，返回边数。"""
    db.query(NoteLink).filter(NoteLink.source_document_id == doc.id).delete(
        synchronize_session=False
    )
    db.flush()

    links = extract_links(doc.content_text or "")
    if not links:
        db.commit()
        return 0

    index = _title_index(db, exclude_id=doc.id)
    for item in links:
        target_id = index.get(item["title"].lower())
        db.add(
            NoteLink(
                source_document_id=doc.id,
                target_document_id=target_id,
                target_title=item["title"],
                target_anchor=item["anchor"],
                is_embed=item["is_embed"],
            )
        )
    db.commit()
    logger.info("笔记 %s 解析出 %s 条出链", doc.id, len(links))
    return len(links)


def resolve_pending(db: Session, doc: Document) -> int:
    """新笔记创建后，把此前指向它的「未解析链接」补上目标 ID。"""
    names = {(doc.title or "").strip().lower()}
    stem = (doc.title or "").rsplit(".", 1)[0].strip().lower()
    if stem:
        names.add(stem)
    names.discard("")
    if not names:
        return 0

    pending = (
        db.execute(select(NoteLink).where(NoteLink.target_document_id.is_(None)))
        .scalars()
        .all()
    )
    fixed = 0
    for link in pending:
        if link.source_document_id == doc.id:
            continue
        if (link.target_title or "").strip().lower() in names:
            link.target_document_id = doc.id
            fixed += 1
    if fixed:
        db.commit()
        logger.info("新笔记 %s 解析了 %s 条历史未解析链接", doc.id, fixed)
    return fixed


def outgoing(db: Session, document_id: uuid.UUID) -> list[dict]:
    """该笔记指向外部的链接。"""
    rows = (
        db.execute(
            select(NoteLink, Document.title)
            .outerjoin(Document, Document.id == NoteLink.target_document_id)
            .where(NoteLink.source_document_id == document_id)
            .order_by(NoteLink.created_at)
        )
        .all()
    )
    return [
        {
            "link_id": str(link.id),
            "target_title": link.target_title,
            "target_document_id": str(link.target_document_id)
            if link.target_document_id
            else None,
            "target_document_title": title,
            "resolved": link.target_document_id is not None,
            # 块级引用信息：锚点 + 是否嵌入。前端据此跳转定位与区分渲染
            "target_anchor": link.target_anchor,
            "is_embed": link.is_embed,
        }
        for link, title in rows
    ]


def backlinks(db: Session, document_id: uuid.UUID) -> list[dict]:
    """反向链接：哪些笔记引用了当前笔记。"""
    rows = (
        db.execute(
            select(NoteLink, Document.id, Document.title)
            .join(Document, Document.id == NoteLink.source_document_id)
            .where(
                NoteLink.target_document_id == document_id,
                Document.deleted_at.is_(None),
            )
            .order_by(NoteLink.created_at.desc())
        )
        .all()
    )
    return [
        {
            "link_id": str(link.id),
            "source_document_id": str(src_id),
            "source_document_title": src_title,
            "target_title": link.target_title,
            "target_anchor": link.target_anchor,
            "is_embed": link.is_embed,
        }
        for link, src_id, src_title in rows
    ]


def summary(db: Session, document_id: uuid.UUID) -> dict:
    """出链 + 反向链接 + 未解析数量（前端一次拿全）。"""
    out = outgoing(db, document_id)
    back = backlinks(db, document_id)
    return {
        "outgoing": out,
        "backlinks": back,
        "unresolved": [o for o in out if not o["resolved"]],
        "outgoing_count": len(out),
        "backlink_count": len(back),
        "unresolved_count": len([o for o in out if not o["resolved"]]),
    }


def note_titles(db: Session, exclude_id: uuid.UUID | None = None, limit: int = 500) -> list[str]:
    """可选作链接目标的笔记标题（供编辑器补全）。"""
    return [t["title"] for t in note_targets(db, exclude_id, limit)]


def note_targets(
    db: Session, exclude_id: uuid.UUID | None = None, limit: int = 500
) -> list[dict]:
    """可选作链接目标的笔记（含 ID），供编辑器补全与正文链接点击跳转。

    同时给「完整标题」和「去掉扩展名的主干」两种键：用户写 `[[vue]]`
    时要能命中标题为 `vue.md` 的上传文档。
    """
    stmt = (
        select(Document.id, Document.title)
        .where(Document.deleted_at.is_(None))
        .order_by(Document.updated_at.desc())
        .limit(limit)
    )
    if exclude_id is not None:
        stmt = stmt.where(Document.id != exclude_id)
    out: list[dict] = []
    seen: set[str] = set()
    for doc_id, title in db.execute(stmt).all():
        if not title:
            continue
        keys = {(title or "").strip().lower()}
        stem = (title or "").rsplit(".", 1)[0].strip().lower()
        if stem:
            keys.add(stem)
        keys.discard("")
        if seen & keys:
            continue
        seen |= keys
        out.append({"id": str(doc_id), "title": title})
    return out
