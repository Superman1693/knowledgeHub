"""标签路由。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import AIUnavailableError
from app.schemas.category import TagCreate, TagOut, TagSuggestRequest, TagUpdate
from app.services import tag_service

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[TagOut])
def list_tags(db: Session = Depends(get_db)) -> list[TagOut]:
    return [
        TagOut(
            id=tag.id, name=tag.name, created_at=tag.created_at, document_count=count
        )
        for tag, count in tag_service.list_tags(db)
    ]


@router.post("", response_model=TagOut, status_code=201)
def create_tag(payload: TagCreate, db: Session = Depends(get_db)) -> TagOut:
    tag = tag_service.create_tag(db, payload.name)
    return TagOut.model_validate(tag)


@router.put("/{tag_id}", response_model=TagOut)
def update_tag(
    tag_id: uuid.UUID, payload: TagUpdate, db: Session = Depends(get_db)
) -> TagOut:
    tag = tag_service.update_tag(db, tag_id, payload.name)
    return TagOut.model_validate(tag)


@router.delete("/{tag_id}", status_code=204)
def delete_tag(tag_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    tag_service.delete_tag(db, tag_id)


@router.post("/suggest")
async def suggest_tags(payload: TagSuggestRequest, db: Session = Depends(get_db)) -> dict:
    """推荐标签。use_ai=true 时由对话模型按文档主题生成（更准，需已配置模型）。"""
    if payload.use_ai:
        try:
            tags = await tag_service.suggest_tags_ai(
                db, payload.document_id, payload.text, payload.limit
            )
        except Exception as exc:  # noqa: BLE001
            raise AIUnavailableError(f"AI 标签推荐失败：{exc}") from exc
        return {"suggestions": tags, "note": "由 AI 根据文档主题生成，仅供参考"}
    tags = tag_service.suggest_tags(db, payload.document_id, payload.text, payload.limit)
    return {"suggestions": tags, "note": "标签建议基于内容词频与已有标签，仅供参考"}


@router.get("/similar")
def similar_tags(name: str = Query(...), db: Session = Depends(get_db)) -> dict:
    return {"similar": tag_service.find_similar_tags(db, name)}


@router.post("/document/{document_id}")
def set_document_tags(
    document_id: uuid.UUID,
    names: list[str] = Body(..., embed=True),
    db: Session = Depends(get_db),
) -> dict:
    tags = tag_service.set_document_tags(db, document_id, names)
    return {"tags": [t.name for t in tags]}
