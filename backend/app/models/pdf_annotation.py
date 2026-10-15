"""PDF 批注模型：引文锚定的高亮与批注。

## 为什么锚点是「引文 + 页号 + 归一化矩形」三者组合

直觉做法是把高亮绑定到「页面坐标」，但坐标在 PDF 换版本或重排版后整体失效，
而且无法参与检索。把锚点绑定到**用户划中的那句话本身**（`quote`）才能稳定：

| 锚 | 管什么 | 失效条件 |
|---|---|---|
| `page_no` | 快速定位到第几页 | PDF 换版后页码可能整体偏移 |
| `quote` | **真正的身份**，也是坐标丢失后重新定位的依据 | 只有原文被改写才失效 |
| `rects` | 重绘高亮的像素位置（已归一化，与缩放无关） | PDF 换版可能错位，需靠 quote 重算 |

`prefix` / `suffix` 各存引文前后约 32 字符，用于消歧——
同一页里「因此我们可以认为」可能出现多次。

## 刻意不做的事

- **不生成 chunk、不碰向量库**。批注通过「导出成 `.md` 笔记」参与检索，
  于是混合检索 / 拼音 / 拼错容错 / 双链 / 复习全部自动可用，检索层一行不改。
- **不在 `documents` 上加字段**。「本文档有几条批注」用 COUNT 子查询即可，
  需要缓存时再加，不提前加列。
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin

# 高亮颜色。刻意用有限枚举而不是自由文本：颜色是给人快速区分语义用的，
# 放开任意值只会让同一篇文档里出现 8 种相近的黄色。
ANNOTATION_COLORS = {"yellow", "green", "blue", "pink", "purple"}
DEFAULT_ANNOTATION_COLOR = "yellow"

# 引文长度上限。超过它的一定不是「划中一句话」，而是整页误选。
MAX_QUOTE_LEN = 2000
# 上下文长度上限（前端传 32，这里留余量）
MAX_CONTEXT_LEN = 200


class PdfAnnotation(Base, IdMixin, TimestampMixin):
    """一条 PDF 高亮/批注。"""

    __tablename__ = "pdf_annotations"

    __table_args__ = (
        # 渲染某一页时要一次性取该页全部批注，这是最高频的查询
        Index("ix_pdf_annotations_doc_page", "document_id", "page_no"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        # 级联删除：PDF 被彻底删除时批注自动清掉，不留孤儿数据。
        # 注意与 flashcards 的取向不同——闪卡承载用户的学习进度，
        # 目标消失时置空而不是删除；批注只是原文的附着物，随原文一起走。
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 1-based，与 `chunk.page_no` 口径一致（否则前端跳页会差一）
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # 划中的原文（主锚）。规范化后存储：去掉软连字符、折叠空白
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    prefix: Mapped[str | None] = mapped_column(Text)
    suffix: Mapped[str | None] = mapped_column(Text)
    # 归一化矩形数组（0..1）。多值几何数据，且**不参与索引**，
    # 用 JSONB 比拆列或建子表都合适
    rects: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    # 页面旋转角（0/90/180/270）。归一化坐标本身已免疫旋转，
    # 存它只为排查问题与将来按方向做不同渲染
    rotation: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    color: Mapped[str] = mapped_column(
        String(16), default=DEFAULT_ANNOTATION_COLOR,
        server_default=DEFAULT_ANNOTATION_COLOR, nullable=False,
    )
    # 用户自己的话。**这才是导出成笔记时被索引的正文**，引文只作为引用块
    comment: Mapped[str | None] = mapped_column(Text)

    document: Mapped["Document"] = relationship()  # noqa: F821
