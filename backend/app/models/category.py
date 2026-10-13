"""知识分类模型（支持多级文件夹）。

LocalMind 的「多级文件夹」在现有技术栈下的落地：
用自引用 `parent_id` 表达层级，前端渲染为树；`parent_id` 为空表示根分类。

删除策略：父分类被删除时子分类**上提为根**（`ON DELETE SET NULL`），
而不是级联删除 —— 级联会把用户辛苦建立的分类体系连同文档归属一起抹掉。
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class Category(Base, IdMixin, TimestampMixin):
    __tablename__ = "categories"

    __table_args__ = (
        # 同一父节点下不允许重名（根节点重名由 service 层校验，
        # 因为 PostgreSQL 中 (NULL, name) 不受唯一约束约束）
        UniqueConstraint("parent_id", "name", name="uq_categories_parent_name"),
        Index("ix_categories_parent_id", "parent_id"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # 多级文件夹：为空表示根分类
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL", name="fk_categories_parent"),
        nullable=True,
    )

    documents = relationship("Document", back_populates="category")
    parent = relationship(
        "Category", remote_side="Category.id", back_populates="children"
    )
    children = relationship(
        "Category",
        back_populates="parent",
        order_by="Category.name",
    )
