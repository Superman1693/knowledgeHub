"""保存的检索条件（智能集合）。

把「关键词 + 检索模式 + 分类 + 标签 + 排序 + 时间区间」存成一个命名集合，
侧栏/检索页一键进入，省掉每次重填同一套筛选。

设计取舍：整个筛选条件存成一份 JSONB（`params`），而不是给每个筛选项建一列。
理由是筛选项本身还会增长（文档状态、类型、页码范围…），每加一项都要改表结构并不划算；
而这里的访问模式只有「按名字列出来 → 点开时原样套用」，没有按单个字段查询的需求。
"""
from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class SavedSearch(Base, IdMixin, TimestampMixin):
    """一个保存下来的检索条件。"""

    __tablename__ = "saved_searches"

    __table_args__ = (
        # 集合名唯一：重名会让列表里出现两个看不出区别的入口
        UniqueConstraint("name", name="uq_saved_searches_name"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 筛选条件原文：keyword / mode / category_id / tags / sort / date_from / date_to / top_k
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
