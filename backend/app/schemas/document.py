"""文档相关 Pydantic 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NoteCreate(BaseModel):
    """新建笔记（不经过文件上传，直接写正文）。"""

    title: str = Field(min_length=1, max_length=512)
    content_text: str = ""
    category_id: uuid.UUID | None = None
    tags: list[str] | None = None
    # 是否允许进入 AI 检索范围（私密笔记置 false）。
    # 此前这个字段只在 DocumentUpdate 里有，新建时想建私密笔记只能「先建再改」——
    # 而 Pydantic 对未知字段是静默忽略，从接口层面完全看不出来缺了这个能力。
    ai_enabled: bool = True


class DocumentUpdate(BaseModel):
    # min_length=1：与 NoteCreate 口径一致，避免把标题更新成空串
    title: str | None = Field(default=None, min_length=1, max_length=512)
    category_id: uuid.UUID | None = None
    content_text: str | None = None
    # 是否允许进入 AI 检索范围（私密笔记置 false）
    ai_enabled: bool | None = None
    # 乐观锁：客户端把「开始编辑时拿到的 content_hash」回传，
    # 服务端比对不一致说明内容已被别人（例如应用外的编辑器）改过 → 409。
    base_content_hash: str | None = None


class BatchDocumentRequest(BaseModel):
    """文档批量操作。"""

    action: Literal["delete", "restore", "purge", "favorite", "pin", "move", "tag"]
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    # move 用；tag 用
    category_id: uuid.UUID | None = None
    tags: list[str] | None = None
    # favorite / pin 用
    value: bool = True


class DocumentTagOut(BaseModel):
    """文档上挂载的标签（精简版，只带 id 与名称）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    original_filename: str
    file_type: str
    file_size: int
    status: str
    error_message: str | None = None
    chunk_count: int
    category_id: uuid.UUID | None = None
    tags: list[DocumentTagOut] = []
    # ---- 个人知识库扩展 ----
    source: str = "upload"
    is_favorite: bool = False
    is_pinned: bool = False
    ai_enabled: bool = True
    last_viewed_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentOut):
    content_text: str | None = None
    # 正文指纹（sha256）：客户端保存时原样回传，作为乐观锁基线
    content_hash: str = ""


class ChunkOut(BaseModel):
    """知识片段（用于引用定位与片段预览）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chunk_index: int
    heading: str | None = None
    page_no: int | None = None
    content: str
    token_count: int
    # 是否已生成向量（未配置嵌入模型时为 False）
    has_embedding: bool = False


class RevisionOut(BaseModel):
    """正文历史快照（列表不返回全文，避免响应过大）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    title: str
    char_count: int
    note: str | None = None
    created_at: datetime


class RevisionDetail(RevisionOut):
    content_text: str | None = None


class DocumentListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[DocumentOut]
