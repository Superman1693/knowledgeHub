"""专属术语词典模型。

用于解释技术缩写、项目自定义名词、框架术语、个人习惯用语与项目组件名称。
在问答时会优先检索词典，命中则作为高优先级的上下文提供给模型。
"""
from __future__ import annotations

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin

# 术语分类
CATEGORY_ABBR = "缩写"
CATEGORY_FRAMEWORK = "框架术语"
CATEGORY_PROJECT = "项目名词"
CATEGORY_HABIT = "习惯用语"
CATEGORY_OTHER = "其他"
VALID_CATEGORIES = {
    CATEGORY_ABBR,
    CATEGORY_FRAMEWORK,
    CATEGORY_PROJECT,
    CATEGORY_HABIT,
    CATEGORY_OTHER,
}


class GlossaryTerm(Base, IdMixin, TimestampMixin):
    __tablename__ = "glossary_terms"

    term: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    # 别名 / 缩写 / 同义写法，便于命中
    aliases: Mapped[list | None] = mapped_column(JSON)
    category: Mapped[str | None] = mapped_column(String(64))
