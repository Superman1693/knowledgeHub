"""分类与标签 Pydantic 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------- 分类 ----------
class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime
    document_count: int = 0


# ---------- 标签 ----------
class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    document_count: int = 0


class TagSuggestRequest(BaseModel):
    document_id: uuid.UUID | None = None
    text: str | None = None
    limit: int = Field(default=8, ge=1, le=30)
    # True 时调用对话模型按主题推荐（更准，需已配置模型）；False 走词频启发式
    use_ai: bool = False
