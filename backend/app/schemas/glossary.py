"""术语词典 Pydantic 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GlossaryCreate(BaseModel):
    term: str = Field(min_length=1, max_length=255)
    definition: str = Field(min_length=1)
    aliases: list[str] | None = None
    category: str | None = None


class GlossaryUpdate(BaseModel):
    term: str | None = Field(default=None, min_length=1, max_length=255)
    definition: str | None = Field(default=None, min_length=1)
    aliases: list[str] | None = None
    category: str | None = None


class GlossaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    term: str
    definition: str
    aliases: list | None = None
    category: str | None = None
    created_at: datetime
    updated_at: datetime


class GlossaryLookupRequest(BaseModel):
    text: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=50)
