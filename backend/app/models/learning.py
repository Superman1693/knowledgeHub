"""学习辅助模型：面试/复习的答题记录（错题本）。

约束（requirements.md 扩展路线图）：复习与面试**不得虚构用户曾经答错的题目** ——
因此错题只能来自本表中真实提交过、且得分低于阈值 的记录。
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class QuizRecord(Base, IdMixin, TimestampMixin):
    """一次问答/面试作答记录。"""

    __tablename__ = "quiz_records"

    # 题目与参考答案（均由 AI 依据知识库生成）
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[str | None] = mapped_column(Text)

    # 用户作答与评分；未作答时 user_answer / score 为空
    user_answer: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int | None] = mapped_column(Integer)
    feedback: Mapped[str | None] = mapped_column(Text)

    # 面试维度
    direction: Mapped[str | None] = mapped_column(String(64))
    difficulty: Mapped[str | None] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(16), default="review", nullable=False)

    # 依据来源：题目所依据的知识片段（用于引用与追溯）
    # 外键显式命名，避免 autogenerate 渲染出 drop_constraint(None)
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "chunks.id",
            ondelete="SET NULL",
            name="fk_quiz_records_source_chunk",
        ),
        nullable=True,
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "documents.id",
            ondelete="SET NULL",
            name="fk_quiz_records_source_document",
        ),
        nullable=True,
    )

    # 复习状态：用户手动标记已掌握
    mastered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[list | None] = mapped_column(JSONB)
