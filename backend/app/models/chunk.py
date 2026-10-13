"""知识片段模型（含向量列）。"""
from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.models.base import Base, IdMixin, TimestampMixin


class Chunk(Base, IdMixin, TimestampMixin):
    __tablename__ = "chunks"

    # 检索索引在此声明，避免 Alembic autogenerate 误判为「多余索引」而删除
    __table_args__ = (
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_chunks_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),
        # 拼音列的 trgm 索引：查询是 `pinyin ILIKE '%xiang%'`，
        # 没有索引会退化成全表扫描（拼音串很长，代价比 content 还高）。
        Index(
            "ix_chunks_pinyin_trgm",
            "pinyin",
            postgresql_using="gin",
            postgresql_ops={"pinyin": "gin_trgm_ops"},
        ),
        Index(
            "ix_chunks_pinyin_initials_trgm",
            "pinyin_initials",
            postgresql_using="gin",
            postgresql_ops={"pinyin_initials": "gin_trgm_ops"},
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str | None] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 拼音检索列：全拼与首字母，都不加分隔符。
    # 可空 —— pypinyin 未安装或老数据未回填时为 NULL，检索自动退回纯文本匹配。
    pinyin: Mapped[str | None] = mapped_column(Text, nullable=True)
    pinyin_initials: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_no: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 维度由嵌入模型决定，随配置变化（变更需重建索引）
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )

    # 父子检索：子块（有 embedding）用于检索，parent_id 指向的父块（无 embedding）
    # 用于回传给模型以补足上下文。父块自身与单级分块的片段该列为 NULL。
    # 外键必须显式命名：否则 autogenerate 会渲染出 drop_constraint(None) 使迁移失败。
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE", name="fk_chunks_parent_id"),
        nullable=True,
        index=True,
    )

    document = relationship("Document", back_populates="chunks")
