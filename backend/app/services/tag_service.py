"""标签服务：CRUD、文档绑定、标签推荐、相似标签检测。"""
from __future__ import annotations

import re
import uuid
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import Document, Tag

# 中文词组 / 英文标识符
TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,6}|[A-Za-z][A-Za-z0-9_+.#-]{1,24}")
STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "are", "was",
    "一个", "我们", "可以", "这个", "那个", "因为", "所以", "如果", "但是",
    "然后", "以及", "进行", "使用", "通过", "需要", "就是", "已经", "或者",
}


def list_tags(db: Session) -> list[tuple[Tag, int]]:
    rows = db.execute(
        select(Tag, func.count(Document.id))
        .outerjoin(Tag.documents)
        .group_by(Tag.id)
        .order_by(Tag.name)
    ).all()
    return [(tag, count) for tag, count in rows]


def get_tag(db: Session, tag_id: uuid.UUID) -> Tag:
    tag = db.get(Tag, tag_id)
    if not tag:
        raise NotFoundError("标签不存在")
    return tag


def create_tag(db: Session, name: str) -> Tag:
    name = name.strip()
    if not name:
        raise ValidationError("标签名不能为空")
    exists = db.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if exists:
        raise ValidationError(f"标签已存在：{name}")
    tag = Tag(name=name)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def update_tag(db: Session, tag_id: uuid.UUID, name: str) -> Tag:
    tag = get_tag(db, tag_id)
    name = name.strip()
    dup = db.execute(
        select(Tag).where(Tag.name == name, Tag.id != tag_id)
    ).scalars().first()
    if dup:
        raise ValidationError(f"标签名已被占用：{name}")
    tag.name = name
    db.commit()
    db.refresh(tag)
    return tag


def delete_tag(db: Session, tag_id: uuid.UUID) -> None:
    tag = get_tag(db, tag_id)
    db.delete(tag)
    db.commit()


def set_document_tags(db: Session, document_id: uuid.UUID, names: list[str]) -> list[Tag]:
    """设置文档标签（覆盖式）：不存在的标签自动创建。"""
    doc = db.get(Document, document_id)
    if not doc:
        raise NotFoundError("文档不存在")
    tags: list[Tag] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        tag = db.execute(select(Tag).where(Tag.name == name)).scalars().first()
        if not tag:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        tags.append(tag)
    doc.tags = tags
    db.commit()
    return tags


def suggest_tags(
    db: Session, document_id: uuid.UUID | None, text: str | None, limit: int = 8
) -> list[str]:
    """基于内容推荐标签（确定性启发式，仅作建议）。"""
    content = text or ""
    if document_id and not content:
        doc = db.get(Document, document_id)
        if doc:
            content = doc.content_text or ""
    if not content:
        return []

    existing = [t.name for t in db.execute(select(Tag)).scalars().all()]
    result: list[str] = []

    # 1) 内容中命中的已有标签优先
    for name in existing:
        if name and name in content and name not in result:
            result.append(name)

    # 2) 词频候选
    counter = Counter(
        tok
        for tok in TOKEN_RE.findall(content)
        if tok.lower() not in STOPWORDS and len(tok) >= 2
    )
    for word, _ in counter.most_common(limit * 3):
        if word not in result:
            result.append(word)
        if len(result) >= limit:
            break

    return result[:limit]


def find_similar_tags(db: Session, name: str, threshold: float = 0.6) -> list[str]:
    """基于 PostgreSQL similarity() 找出相似标签。"""
    from sqlalchemy import text as sql_text

    rows = db.execute(
        sql_text(
            "SELECT name, similarity(name, :n) AS s FROM tags "
            "WHERE similarity(name, :n) >= :th ORDER BY s DESC"
        ),
        {"n": name, "th": threshold},
    ).all()
    return [r[0] for r in rows]
