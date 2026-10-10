"""会话与消息模型。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin

# 回答输出模式
MODE_DETAIL = "detail"  # 详细解释
MODE_BRIEF = "brief"  # 极简要点
MODE_EXAMPLE = "example"  # 通俗举例
VALID_MODES = {MODE_DETAIL, MODE_BRIEF, MODE_EXAMPLE}


class Conversation(Base, IdMixin, TimestampMixin):
    __tablename__ = "conversations"

    title: Mapped[str] = mapped_column(String(512), default="新会话", nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default=MODE_DETAIL, nullable=False)

    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base, IdMixin):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user|assistant|system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 引用数组，结构见 design.md 5.6
    sources: Mapped[list | None] = mapped_column(JSON)
    # 原文 | 归纳 | 联网 | 混合
    source_type: Mapped[str | None] = mapped_column(String(16))
    # 推理模型的思考过程（reasoning_content）。仅用于界面回看，不计入回答正文与引用
    reasoning: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation = relationship("Conversation", back_populates="messages")
