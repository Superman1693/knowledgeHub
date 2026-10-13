"""闪卡与复习记录模型（间隔复习 / SRS）。

对应 LocalMind「闪卡与间隔复习」：正面显示问题、翻面显示答案，
依据记忆情况安排下次复习时间，并记录掌握程度与复习历史。

算法：**SM-2**（SuperMemo 2）。评分 0~5，`>=3` 视为通过。
约束：卡片必须可追溯到原资料（`document_id` / `source_chunk_id`），
目标被删除时置空而不是级联删除卡片，避免用户的学习进度被连带清掉。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin

# 卡片状态
CARD_NEW = "new"  # 尚未复习
CARD_LEARNING = "learning"  # 学习中（间隔仍在天以内）
CARD_REVIEW = "review"  # 复习中（已进入天级间隔）
VALID_CARD_STATES = {CARD_NEW, CARD_LEARNING, CARD_REVIEW}


class Flashcard(Base, IdMixin, TimestampMixin):
    """一张复习卡片。"""

    __tablename__ = "flashcards"

    __table_args__ = (
        # 「今日复习」按 due_at 过滤，是最主要的查询路径
        Index("ix_flashcards_due_at", "due_at"),
    )

    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)

    # 来源可追溯（LocalMind：生成的卡片必须可追溯到原资料）
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "documents.id", ondelete="SET NULL", name="fk_flashcards_document"
        ),
        nullable=True,
        index=True,
    )
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL", name="fk_flashcards_source_chunk"),
        nullable=True,
    )
    tags: Mapped[list | None] = mapped_column(JSONB)

    # ---------------- SM-2 状态 ----------------
    state: Mapped[str] = mapped_column(String(16), default=CARD_NEW, nullable=False)
    # 难度系数（E-Factor），初始 2.5，最低 1.3
    ease: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)
    # 当前间隔（天）；0 表示当天内复习
    interval_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 连续通过次数
    repetitions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 遗忘次数（评分为 0~2 时 +1）
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 下次复习时间；为空表示待首次复习
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 暂停：不再出现在复习队列，但不删除
    suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    reviews = relationship(
        "ReviewLog",
        back_populates="card",
        cascade="all, delete-orphan",
        order_by="ReviewLog.reviewed_at.desc()",
    )


class ReviewLog(Base, IdMixin):
    """一次复习记录（只追加，不可变）。"""

    __tablename__ = "review_logs"

    flashcard_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "flashcards.id", ondelete="CASCADE", name="fk_review_logs_flashcard"
        ),
        nullable=False,
        index=True,
    )
    # 评分 0~5（SM-2 口径）
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    prev_interval: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_interval: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ease_after: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)

    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    card = relationship("Flashcard", back_populates="reviews")
