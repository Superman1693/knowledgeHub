"""检索相关 Pydantic 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SearchMode = Literal["keyword", "semantic", "hybrid"]
# relevance = 相关度（默认）；updated/created = 按文档时间倒序
SearchSort = Literal["relevance", "updated", "created"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: SearchMode = "hybrid"
    category_id: uuid.UUID | None = None
    tags: list[str] | None = None
    top_k: int = Field(default=8, ge=1, le=50)
    # 排序方式：默认按相关度；按时间排序时忽略分数
    sort: SearchSort = "relevance"
    # 是否只检索允许 AI 读取的笔记（AI 问答强制 true；用户自己检索默认 false）
    ai_only: bool = False
    # 按文档更新时间筛选区间（需求 11.4「按更新时间筛选」的另一半：
    # 此前只有排序，无法表达「只看上个月写的东西」）
    date_from: datetime | None = None
    date_to: datetime | None = None


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
    # 父子检索：命中片段所属父块的内容，用于回传给模型补足上下文。
    # 未开启父子检索时为 None，此时 snippet 所在片段本身即完整内容。
    parent_id: uuid.UUID | None = None
    parent_content: str | None = None
    # 命中词列表，前端据此在 snippet 中做高亮（此前只有纯文本截断，用户要自己找）
    highlights: list[str] = []
    # 所属文档的更新时间，用于「按时间排序」
    document_updated_at: datetime | None = None
    # 所属文档的创建时间
    document_created_at: datetime | None = None


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode
    total: int
    hits: list[SearchHit]


# ---------------- 保存的检索条件（智能集合） ----------------

class SavedSearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    # 筛选条件原文，字段与 SearchRequest 对齐（存成 JSONB，加筛选项无需改表）
    params: dict = Field(default_factory=dict)


class SavedSearchRename(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class SavedSearchOut(BaseModel):
    id: uuid.UUID
    name: str
    params: dict
    created_at: datetime | None = None
    updated_at: datetime | None = None
