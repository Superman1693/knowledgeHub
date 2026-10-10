"""知识分类路由。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.category import CategoryCreate, CategoryOut, CategoryUpdate
from app.services import category_service

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[CategoryOut]:
    return [
        CategoryOut(
            id=cat.id,
            name=cat.name,
            description=cat.description,
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
