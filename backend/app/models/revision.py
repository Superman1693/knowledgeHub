"""笔记版本历史模型。

LocalMind 的「版本历史」在现有技术栈下的落地方式：
每次保存正文**之前**把上一版快照写入本表，正文可随时回滚，
避免误编辑把内容永久覆盖（此前项目只有「重建索引」，没有任何内容历史）。

设计取舍：快照是整篇全文，而非 diff —— 个人知识库单篇体量小，
整篇存储实现简单、回滚可靠，且便于直接对比；不做增量 diff 以免引入复杂度。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin


class NoteRevision(Base, IdMixin):
    """一次正文快照（不可变，只追加）。"""

    __tablename__ = "note_revisions"

    # 外键显式命名，避免 autogenerate 渲染出 drop_constraint(None) 使迁移失败
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "documents.id", ondelete="CASCADE", name="fk_note_revisions_document"
        ),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text)
    # 正文字符数，列表展示与体积判断用
    char_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 变更说明（如「编辑保存」「回滚自某一版」）
    note: Mapped[str | None] = mapped_column(String(128))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document = relationship("Document", back_populates="revisions")
