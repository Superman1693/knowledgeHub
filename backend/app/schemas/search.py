"""检索相关 Pydantic 模型。"""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

SearchMode = Literal["keyword", "semantic", "hybrid"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: SearchMode = "hybrid"
    category_id: uuid.UUID | None = None
    tags: list[str] | None = None
    top_k: int = Field(default=8, ge=1, le=50)


class SearchHit(BaseModel):
    document_id: uuid.UUID
    document_title: str
    chunk_id: uuid.UUID
    heading: str | None = None
    page_no: int | None = None
    snippet: str
    score: float
    keyword_score: float | None = None
    semantic_score: float | None = None


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode
    total: int
    hits: list[SearchHit]
