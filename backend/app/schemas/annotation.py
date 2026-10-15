"""PDF 批注的 Pydantic 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.pdf_annotation import (
    DEFAULT_ANNOTATION_COLOR,
    MAX_CONTEXT_LEN,
    MAX_QUOTE_LEN,
)


class AnnotationRect(BaseModel):
    """归一化矩形（相对页面可视区左上角，0..1）。"""

    x: float
    y: float
    w: float
    h: float


class AnnotationCreate(BaseModel):
    """新建一条高亮/批注。

    `quote` 是**主锚**：坐标丢了以后靠它重新定位，所以必填且限长。
    上限按「一整段话」而不是「一整页」设定——超过它基本是误选了整页。
    """

    page_no: int = Field(ge=1, description="1-based，与 chunk.page_no 口径一致")
    quote: str = Field(min_length=1, max_length=MAX_QUOTE_LEN)
    # 跨行/跨栏选择会产生多个矩形，所以这里是数组
    rects: list[AnnotationRect] = Field(min_length=1)
    prefix: str | None = Field(default=None, max_length=MAX_CONTEXT_LEN)
    suffix: str | None = Field(default=None, max_length=MAX_CONTEXT_LEN)
    rotation: int = 0
    color: str = DEFAULT_ANNOTATION_COLOR
    comment: str | None = None


class AnnotationUpdate(BaseModel):
    """部分更新。两者都不传即为空操作。"""

    color: str | None = None
    comment: str | None = None


class AnnotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    page_no: int
    quote: str
    prefix: str | None = None
    suffix: str | None = None
    rects: list[AnnotationRect] = []
    rotation: int = 0
    color: str = DEFAULT_ANNOTATION_COLOR
    comment: str | None = None
    created_at: datetime
    updated_at: datetime


class AnnotationListOut(BaseModel):
    """列表响应带上 total：前端要在「本文档有 N 条批注」处显示总数，
    而按页过滤时 `items` 只是该页的部分。"""

    total: int
    items: list[AnnotationOut]


class AnnotationExportOut(BaseModel):
    document_id: uuid.UUID
    title: str
    annotation_count: int
    # True = 新建了笔记；False = 更新了此前导出的那一篇（导出是幂等的）
    created: bool
