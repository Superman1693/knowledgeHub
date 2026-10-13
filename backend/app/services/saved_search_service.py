"""保存的检索条件（智能集合）：增删改查。

约束：
- 名称唯一（重名会让列表里出现两个看不出区别的入口）；
- 数量有上限（避免把侧栏塞满，也避免误写循环把表刷爆）。
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import SavedSearch

# 单用户场景下 100 个集合已经远超实际需要
MAX_SAVED = 100


def out(item: SavedSearch) -> dict:
    return {
        "id": str(item.id),
        "name": item.name,
        "params": item.params or {},
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def list_saved(db: Session) -> list[SavedSearch]:
    """按创建时间倒序列出（最近存的排前面）。"""
    return list(
        db.execute(select(SavedSearch).order_by(SavedSearch.created_at.desc()))
        .scalars()
        .all()
    )


def get_saved(db: Session, saved_id: uuid.UUID) -> SavedSearch:
    item = db.get(SavedSearch, saved_id)
    if not item:
        raise NotFoundError("保存的检索条件不存在")
    return item


def _validate_name(db: Session, name: str, exclude_id: uuid.UUID | None = None) -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError("集合名称不能为空")
    if len(name) > 128:
        raise ValidationError("集合名称过长（最多 128 个字符）")
    dup = (
        db.execute(
            select(SavedSearch).where(
                SavedSearch.name == name,
                SavedSearch.id != exclude_id if exclude_id else True,
            )
        )
        .scalars()
        .first()
    )
    if dup:
        raise ValidationError(f"已存在同名集合「{name}」，请换一个名字")
    return name


def create_saved(db: Session, name: str, params: dict) -> SavedSearch:
    name = _validate_name(db, name)
    total = db.execute(select(func.count()).select_from(SavedSearch)).scalar_one()
    if total >= MAX_SAVED:
        raise ValidationError(f"最多保存 {MAX_SAVED} 个检索条件，请先删除一些")
    item = SavedSearch(name=name, params=params or {})
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def rename_saved(db: Session, saved_id: uuid.UUID, name: str) -> SavedSearch:
    item = get_saved(db, saved_id)
    item.name = _validate_name(db, name, exclude_id=saved_id)
    db.commit()
    db.refresh(item)
    return item


def delete_saved(db: Session, saved_id: uuid.UUID) -> None:
    db.delete(get_saved(db, saved_id))
    db.commit()
