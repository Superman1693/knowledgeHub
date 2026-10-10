"""会话与问答 Pydantic 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AnswerMode = Literal["detail", "brief", "example"]


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    mode: AnswerMode = "detail"


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    mode: AnswerMode | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    sources: list | None = None
    source_type: str | None = None
    # 推理模型的思考过程（可空）；前端用于折叠展示，不计入回答正文
    reasoning: str | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    mode: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    mode: AnswerMode | None = None
    use_web: bool = False
