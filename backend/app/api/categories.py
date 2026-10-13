"""知识分类路由。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.category import (
    CategoryCreate,
    CategoryOut,
    CategoryTreeNode,
    CategoryUpdate,
)
from app.services import category_service

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("/tree", response_model=list[CategoryTreeNode])
def category_tree(db: Session = Depends(get_db)) -> list[CategoryTreeNode]:
    """分类树（含自身文档数与「含子孙」的总数）。"""
    return [CategoryTreeNode.model_validate(node) for node in category_service.tree(db)]


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[CategoryOut]:
    return [
        CategoryOut(
            id=cat.id,
            name=cat.name,
            description=cat.description,
            parent_id=cat.parent_id,
            created_at=cat.created_at,
            updated_at=cat.updated_at,
            document_count=count,
        )
        for cat, count in category_service.list_categories(db)
    ]


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)) -> CategoryOut:
    cat = category_service.create_category(db, payload)
    return CategoryOut.model_validate(cat)


@router.put("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: uuid.UUID, payload: CategoryUpdate, db: Session = Depends(get_db)
) -> CategoryOut:
    cat = category_service.update_category(db, category_id, payload)
    return CategoryOut.model_validate(cat)


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    category_service.delete_category(db, category_id)
