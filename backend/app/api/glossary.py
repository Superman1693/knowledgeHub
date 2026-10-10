"""专属术语词典路由。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.glossary import (
    GlossaryCreate,
    GlossaryLookupRequest,
    GlossaryOut,
    GlossaryUpdate,
)
from app.services import glossary_service

router = APIRouter(prefix="/api/glossary", tags=["glossary"])


@router.get("", response_model=list[GlossaryOut])
def list_terms(
    q: str | None = Query(default=None), db: Session = Depends(get_db)
) -> list[GlossaryOut]:
    return [GlossaryOut.model_validate(t) for t in glossary_service.list_terms(db, q)]


@router.post("", response_model=GlossaryOut, status_code=201)
def create_term(payload: GlossaryCreate, db: Session = Depends(get_db)) -> GlossaryOut:
    return GlossaryOut.model_validate(glossary_service.create_term(db, payload))


@router.put("/{term_id}", response_model=GlossaryOut)
def update_term(
    term_id: uuid.UUID, payload: GlossaryUpdate, db: Session = Depends(get_db)
) -> GlossaryOut:
    return GlossaryOut.model_validate(glossary_service.update_term(db, term_id, payload))


@router.delete("/{term_id}", status_code=204)
def delete_term(term_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    glossary_service.delete_term(db, term_id)


@router.post("/lookup")
def lookup(payload: GlossaryLookupRequest, db: Session = Depends(get_db)) -> dict:
    """查询文本中命中的术语（用于预览问答时会用到哪些词典条目）。"""
    terms = glossary_service.lookup_terms(db, payload.text, payload.limit)
    return {
        "terms": [GlossaryOut.model_validate(t).model_dump(mode="json") for t in terms],
        "rendered": glossary_service.render_glossary(terms),
    }
