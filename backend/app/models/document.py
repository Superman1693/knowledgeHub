"""文档模型。"""
from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin
from app.models.tag import document_tags

# 文档处理状态
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_INDEXED = "indexed"  # 已分块且已向量化
STATUS_PARTIAL = "partial"  # 已分块但未向量化：关键词检索可用，语义检索不可用
STATUS_FAILED = "failed"
VALID_STATUSES = {
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_INDEXED,
    STATUS_PARTIAL,
    STATUS_FAILED,
}


class Document(Base, IdMixin, TimestampMixin):
    __tablename__ = "documents"

    # 标题关键词检索索引（与 chunks.content 的 pg_trgm 索引对应）
    __table_args__ = (
        Index(
            "ix_documents_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # 相对数据目录的路径，避免迁移后绝对路径失效
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )

    content_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_PENDING, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    category = relationship("Category", back_populates="documents")
    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.chunk_index",
    )
    tags = relationship("Tag", secondary=document_tags, back_populates="documents")
