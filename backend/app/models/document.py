"""文档模型。"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
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
        # 回收站 / 列表过滤按 deleted_at 判断
        Index("ix_documents_deleted_at", "deleted_at"),
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

    # ---------------- 个人知识库（PKM）扩展 ----------------
    # 正文来源：upload = 导入的外部文件；note = 在应用内新建或编辑过；
    # web = 从网页剪藏（此时 source_url 记录原地址）
    source: Mapped[str] = mapped_column(
        String(16), default="upload", server_default="upload", nullable=False
    )
    # 网页剪藏的原始地址。存它是为了：
    # 1) 溯源——剪藏来的内容必须能回到出处；
    # 2) 去重——同一网址重复剪藏时可提示而不是默默堆一份副本。
    # index=True 与迁移里的 ix_documents_source_url 对应：按 URL 查重是
    # 每次剪藏都要做的动作，走索引。两处必须一致，否则 alembic check 会报偏差。
    source_url: Mapped[str | None] = mapped_column(Text, index=True)
    # 收藏 / 置顶：常用笔记（如自己的速查表）可快速访问
    is_favorite: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    # 最近访问时间，用于「最近访问」列表
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 是否允许进入 AI 检索范围。置 false 的私密笔记在**检索阶段即被排除**，
    # 而不是只在提示词里提醒模型忽略（LocalMind 隐私规则：检索层过滤，非提示词约束）。
    ai_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    # 软删除：非空表示位于回收站，列表默认过滤，可恢复或彻底删除
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    category = relationship("Category", back_populates="documents")
    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.chunk_index",
    )
    tags = relationship("Tag", secondary=document_tags, back_populates="documents")
    revisions = relationship(
        "NoteRevision",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="NoteRevision.created_at.desc()",
    )

    @property
    def content_hash(self) -> str:
        """正文指纹（sha256），用于编辑冲突检测（乐观锁）。

        为什么不用 `updated_at` 比对：时间戳在浏览器侧只精确到毫秒，
        往返转换容易误判冲突；而正文哈希直接回答「内容是否被别人改过」，
        正是冲突检测真正要判断的事。
        """
        return hashlib.sha256((self.content_text or "").encode("utf-8")).hexdigest()
