"""知识分类服务。"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import Category, Document
from app.schemas.category import CategoryCreate, CategoryUpdate


def list_categories(db: Session) -> list[tuple[Category, int]]:
    """返回 (分类, 文档数) 列表。"""
    rows = db.execute(
        select(Category, func.count(Document.id))
        .outerjoin(Document, Document.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.name)
    ).all()
    return [(cat, count) for cat, count in rows]


def get_category(db: Session, category_id: uuid.UUID) -> Category:
    cat = db.get(Category, category_id)
    if not cat:
        raise NotFoundError("分类不存在")
    return cat


def create_category(db: Session, payload: CategoryCreate) -> Category:
    exists = db.execute(
        select(Category).where(Category.name == payload.name)
    ).scalars().first()
    if exists:
        raise ValidationError(f"分类已存在：{payload.name}")
    cat = Category(name=payload.name, description=payload.description)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def update_category(db: Session, category_id: uuid.UUID, payload: CategoryUpdate) -> Category:
    cat = get_category(db, category_id)
    if payload.name is not None:
        dup = db.execute(
            select(Category).where(Category.name == payload.name, Category.id != category_id)
        ).scalars().first()
        if dup:
            raise ValidationError(f"分类名已被占用：{payload.name}")
        cat.name = payload.name
    if payload.description is not None:
        cat.description = payload.description
    db.commit()
    db.refresh(cat)
    return cat


def delete_category(db: Session, category_id: uuid.UUID) -> None:
    """删除分类：仅解除文档关联，不删除文档。"""
    cat = get_category(db, category_id)
    db.execute(
        Document.__table__.update()
        .where(Document.category_id == category_id)
        .values(category_id=None)
    )
    db.delete(cat)
    db.commit()
