"""保存的检索条件（智能集合）路由。

把「关键词 + 模式 + 分类 + 标签 + 排序 + 时间区间」存成命名集合，一键复用。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.search import SavedSearchCreate, SavedSearchOut, SavedSearchRename
from app.services import saved_search_service

router = APIRouter(prefix="/api/saved-searches", tags=["saved-searches"])


@router.get("", response_model=list[SavedSearchOut])
def list_saved_searches(db: Session = Depends(get_db)) -> list[SavedSearchOut]:
    """列出全部保存的检索条件（按创建时间倒序）。"""
    return [
        SavedSearchOut.model_validate(saved_search_service.out(x))
        for x in saved_search_service.list_saved(db)
    ]


@router.post("", response_model=SavedSearchOut, status_code=201)
def create_saved_search(
    payload: SavedSearchCreate, db: Session = Depends(get_db)
) -> SavedSearchOut:
    """保存一个检索条件；重名会返回 422。"""
    item = saved_search_service.create_saved(db, payload.name, payload.params)
    return SavedSearchOut.model_validate(saved_search_service.out(item))


@router.put("/{saved_id}", response_model=SavedSearchOut)
def rename_saved_search(
    saved_id: uuid.UUID, payload: SavedSearchRename, db: Session = Depends(get_db)
) -> SavedSearchOut:
    item = saved_search_service.rename_saved(db, saved_id, payload.name)
    return SavedSearchOut.model_validate(saved_search_service.out(item))


@router.delete("/{saved_id}", status_code=204)
def delete_saved_search(saved_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    saved_search_service.delete_saved(db, saved_id)
