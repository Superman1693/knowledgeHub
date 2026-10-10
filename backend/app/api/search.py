"""检索路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.search import SearchRequest, SearchResponse
from app.services import search_service

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def do_search(req: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    return await search_service.search(db, req)
