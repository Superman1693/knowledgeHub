"""术语词典服务：CRUD 与问答时的术语命中。"""
from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import GlossaryTerm
from app.schemas.glossary import GlossaryCreate, GlossaryUpdate


def list_terms(db: Session, q: str | None = None) -> list[GlossaryTerm]:
    stmt = select(GlossaryTerm)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(GlossaryTerm.term.ilike(like), GlossaryTerm.definition.ilike(like))
        )
    return list(db.execute(stmt.order_by(GlossaryTerm.term)).scalars().all())


def get_term(db: Session, term_id: uuid.UUID) -> GlossaryTerm:
    term = db.get(GlossaryTerm, term_id)
    if not term:
        raise NotFoundError("术语不存在")
    return term


def create_term(db: Session, payload: GlossaryCreate) -> GlossaryTerm:
    name = payload.term.strip()
    if not name:
        raise ValidationError("术语名不能为空")
    exists = db.execute(
        select(GlossaryTerm).where(GlossaryTerm.term == name)
    ).scalars().first()
    if exists:
        raise ValidationError(f"术语已存在：{name}")
    term = GlossaryTerm(
        term=name,
        definition=payload.definition,
        aliases=payload.aliases,
        category=payload.category,
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return term


def update_term(db: Session, term_id: uuid.UUID, payload: GlossaryUpdate) -> GlossaryTerm:
    term = get_term(db, term_id)
    data = payload.model_dump(exclude_none=True)
    if "term" in data:
        dup = db.execute(
            select(GlossaryTerm).where(
                GlossaryTerm.term == data["term"], GlossaryTerm.id != term_id
            )
        ).scalars().first()
        if dup:
            raise ValidationError(f"术语名已被占用：{data['term']}")
    for key, value in data.items():
        setattr(term, key, value)
    db.commit()
    db.refresh(term)
    return term


def delete_term(db: Session, term_id: uuid.UUID) -> None:
    term = get_term(db, term_id)
    db.delete(term)
    db.commit()


def lookup_terms(db: Session, text: str, limit: int = 8) -> list[GlossaryTerm]:
    """找出文本中命中的术语（按术语名或其别名子串匹配）。

    术语词典规模通常很小，这里直接全量取出后在内存匹配，逻辑简单且结果确定。
    """
    if not text or not text.strip():
        return []
    lowered = text.lower()
    matched: list[GlossaryTerm] = []
    for term in db.execute(select(GlossaryTerm)).scalars().all():
        candidates = [term.term, *(term.aliases or [])]
        if any(c and str(c).lower() in lowered for c in candidates):
            matched.append(term)
    # 长术语优先，避免「API」抢先于「RESTful API」
    matched.sort(key=lambda t: len(t.term), reverse=True)
    return matched[:limit]


def render_glossary(terms: list[GlossaryTerm]) -> str:
    """把命中的术语渲染为提示词片段。"""
    if not terms:
        return ""
    lines = []
    for term in terms:
        alias = ""
        if term.aliases:
            alias = f"（别名：{'、'.join(str(a) for a in term.aliases)}）"
        cat = f"[{term.category}] " if term.category else ""
        lines.append(f"- {cat}{term.term}{alias}：{term.definition}")
    return "\n".join(lines)
