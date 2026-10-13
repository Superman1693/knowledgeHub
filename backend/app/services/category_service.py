"""知识分类服务（支持多级文件夹）。

LocalMind「多级文件夹」的落地：
- `parent_id` 自引用表达层级；`parent_id IS NULL` 为根分类；
- `tree()` 返回嵌套结构，每个节点带「自身文档数」与「含子孙的总数」；
- 创建/更新时校验：父分类存在、**同层不重名**、**不得形成环**；
- 删除分类只解除文档关联（不删文档），子分类由数据库 `ON DELETE SET NULL` 上提为根。
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import Category, Document
from app.schemas.category import CategoryCreate, CategoryUpdate


def _doc_counts(db: Session) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Document.category_id, func.count(Document.id))
        .where(Document.category_id.is_not(None), Document.deleted_at.is_(None))
        .group_by(Document.category_id)
    ).all()
    return {cid: n for cid, n in rows}


def list_categories(db: Session) -> list[tuple[Category, int]]:
    """返回 (分类, 文档数) 平铺列表（按层级+名称排序）。"""
    counts = _doc_counts(db)
    cats = list(
        db.execute(
            select(Category).order_by(Category.parent_id.nulls_first(), Category.name)
        )
        .scalars()
        .all()
    )
    return [(c, counts.get(c.id, 0)) for c in cats]


def get_category(db: Session, category_id: uuid.UUID) -> Category:
    cat = db.get(Category, category_id)
    if not cat:
        raise NotFoundError("分类不存在")
    return cat


def tree(db: Session) -> list[dict]:
    """返回分类树（含自身文档数与含子孙的总数）。"""
    counts = _doc_counts(db)
    cats = list(db.execute(select(Category)).scalars().all())

    nodes: dict[uuid.UUID, dict] = {}
    for c in cats:
        nodes[c.id] = {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "parent_id": c.parent_id,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "document_count": counts.get(c.id, 0),
            "total_count": counts.get(c.id, 0),
            "children": [],
        }

    roots: list[dict] = []
    for c in cats:
        node = nodes[c.id]
        parent = nodes.get(c.parent_id) if c.parent_id else None
        if parent is not None:
            parent["children"].append(node)
        else:
            # 父节点不存在（数据异常）时也当作根，避免节点丢失
            roots.append(node)

    def sort_and_sum(items: list[dict]) -> int:
        items.sort(key=lambda x: str(x["name"]))
        total = 0
        for it in items:
            total += int(it["document_count"]) + sort_and_sum(it["children"])
            it["total_count"] = int(it["document_count"]) + sum(
                int(ch["total_count"]) for ch in it["children"]
            )
        return total

    sort_and_sum(roots)
    return roots


def _sibling_name_taken(
    db: Session, name: str, parent_id: uuid.UUID | None, exclude_id: uuid.UUID | None = None
) -> bool:
    stmt = select(Category).where(Category.name == name)
    stmt = (
        stmt.where(Category.parent_id.is_(None))
        if parent_id is None
        else stmt.where(Category.parent_id == parent_id)
    )
    if exclude_id is not None:
        stmt = stmt.where(Category.id != exclude_id)
    return db.execute(stmt).scalars().first() is not None


def create_category(db: Session, payload: CategoryCreate) -> Category:
    name = payload.name.strip()
    if not name:
        raise ValidationError("分类名不能为空")
    if payload.parent_id is not None:
        get_category(db, payload.parent_id)  # 父分类必须存在
    if _sibling_name_taken(db, name, payload.parent_id):
        raise ValidationError(f"同级下已存在同名分类：{name}")

    cat = Category(
        name=name, description=payload.description, parent_id=payload.parent_id
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _descendant_ids(db: Session, category_id: uuid.UUID) -> set[uuid.UUID]:
    """该分类的全部子孙 id（用于阻止把父节点移到自己的子孙下形成环）。"""
    result: set[uuid.UUID] = set()
    frontier = [category_id]
    while frontier:
        current = frontier.pop()
        rows = db.execute(
            select(Category.id).where(Category.parent_id == current)
        ).scalars().all()
        for cid in rows:
            if cid not in result:
                result.add(cid)
                frontier.append(cid)
    return result


def update_category(db: Session, category_id: uuid.UUID, payload: CategoryUpdate) -> Category:
    cat = get_category(db, category_id)

    new_parent = cat.parent_id
    if payload.move_to_root:
        new_parent = None
    elif payload.parent_id is not None:
        new_parent = payload.parent_id
        if new_parent == category_id:
            raise ValidationError("不能把分类设为自己的父分类")
        get_category(db, new_parent)
        if new_parent in _descendant_ids(db, category_id):
            raise ValidationError("不能把分类移动到它自己的子分类下（会形成环）")

    name = payload.name.strip() if payload.name is not None else cat.name
    if not name:
        raise ValidationError("分类名不能为空")
    if _sibling_name_taken(db, name, new_parent, exclude_id=category_id):
        raise ValidationError(f"同级下已存在同名分类：{name}")

    cat.name = name
    if payload.description is not None:
        cat.description = payload.description
    cat.parent_id = new_parent

    db.commit()
    db.refresh(cat)
    return cat


def delete_category(db: Session, category_id: uuid.UUID) -> None:
    """删除分类：解除文档关联，子分类由 DB 上提为根；不删除任何文档。"""
    cat = get_category(db, category_id)
    db.execute(
        Document.__table__.update()
        .where(Document.category_id == category_id)
        .values(category_id=None)
    )
    db.delete(cat)
    db.commit()


def category_document_ids(db: Session, category_id: uuid.UUID) -> list[uuid.UUID]:
    """该分类（不含子分类）下的文档 id。"""
    return list(
        db.execute(
            select(Document.id).where(
                Document.category_id == category_id, Document.deleted_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
