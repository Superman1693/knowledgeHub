"""笔记双向链接模型（`[[标题]]` → 知识网络）。

LocalMind 设计里的「双向链接 / 反向链接」在现有技术栈下的落地：
- 正文里的 `[[标题]]` 在保存/重建索引时被解析，写入本表形成有向边；
- 目标笔记存在时记录 `target_document_id`，不存在时保留 `target_title`，
  前端可据此提示「该链接指向的笔记尚未创建」并一键新建；
- 反向链接 = 本表中 `target_document_id` 指向当前文档的所有行。

设计取舍：**只存边，不存渲染结果**。每次保存时整篇重解析（先删后插），
保证与正文一致；个人知识库单篇链接量很小，代价可忽略。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin


class NoteLink(Base, IdMixin):
    """一条出链（source → target）。"""

    __tablename__ = "note_links"

    __table_args__ = (
        # 同一篇笔记对同一「标题 + 锚点」只保留一条边，避免重复解析产生脏数据。
        # 锚点必须进约束：`[[A#简介]]` 与 `[[A#安装]]` 是两条不同的引用，
        # 只按标题去重会把后者当成重复而丢掉。
        # （Postgres 中 NULL 互不相等，所以引用整篇的 `[[A]]` 可以出现多次，
        #  由 extract 层按 (标题, 锚点) 去重兜底。）
        UniqueConstraint(
            "source_document_id",
            "target_title",
            "target_anchor",
            name="uq_note_links_source_target",
        ),
        Index("ix_note_links_target_document", "target_document_id"),
    )

    # 外键显式命名，避免 autogenerate 渲染出 drop_constraint(None) 使迁移失败
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "documents.id", ondelete="CASCADE", name="fk_note_links_source"
        ),
        nullable=False,
        index=True,
    )
    # 目标笔记被删除时置空（保留「曾有链接指向」的信息，同时不阻塞删除）
    target_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "documents.id", ondelete="SET NULL", name="fk_note_links_target"
        ),
        nullable=True,
    )
    # `[[ ]]` 中写的原始标题（用于未创建笔记时提示与一键新建）
    target_title: Mapped[str] = mapped_column(String(512), nullable=False)
    # 块级引用的锚点：`[[标题#小节]]` 中 `#` 后的部分。
    # 为空表示引用整篇。前端据此跳转后滚动到对应标题。
    target_anchor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 是否是嵌入引用：`![[标题]]`（把目标内容嵌进当前笔记）
    # 与普通链接 `[[标题]]` 区分开——语义不同，渲染也不同。
    is_embed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source = relationship("Document", foreign_keys=[source_document_id])
    target = relationship("Document", foreign_keys=[target_document_id])
