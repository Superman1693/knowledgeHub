"""文档相关 Pydantic 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    category_id: uuid.UUID | None = None
    content_text: str | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    original_filename: str
    file_type: str
    file_size: int
    status: str
    error_message: str | None = None
    chunk_count: int
    category_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentOut):
    content_text: str | None = None


class DocumentListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[DocumentOut]
