"""系统设置与状态 Pydantic 模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SettingsOut(BaseModel):
    """对外暴露的设置（不含密钥明文）。"""

    ai_mode: str
    local_model_base_url: str
    external_api_base_url: str
    has_external_key: bool
    chat_model: str
    embedding_model: str
    embedding_dim: int
    embedding_base_url: str
    has_embedding_key: bool
    request_timeout: int
    data_dir: str
    max_upload_mb: int
    hybrid_alpha: float
    hybrid_beta: float
    search_top_k: int
    chunk_mode: str = "semantic"
    parent_child_enabled: bool = True
    storage_mode: str
    default_answer_mode: str
    web_search_enabled: bool = False
    web_search_provider: str = "bing"
    web_search_api_url: str = ""
    web_search_top_k: int = 5
    has_web_search_key: bool = False


class SettingsUpdate(BaseModel):
    ai_mode: str | None = None
    local_model_base_url: str | None = None
    external_api_base_url: str | None = None
    external_api_key: str | None = None
    chat_model: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    request_timeout: int | None = None
    data_dir: str | None = None
    max_upload_mb: int | None = None
    hybrid_alpha: float | None = None
    hybrid_beta: float | None = None
    search_top_k: int | None = None
    chunk_mode: str | None = None
    parent_child_enabled: bool | None = None
    default_answer_mode: str | None = None
    web_search_enabled: bool | None = None
    web_search_provider: str | None = None
    web_search_api_url: str | None = None
    web_search_api_key: str | None = None
    web_search_top_k: int | None = None


class ModelTestResult(BaseModel):
    ok: bool
    message: str
    models: list[str] = Field(default_factory=list)
    embedding_ok: bool = False
    embedding_message: str = ""


class IndexStatusOut(BaseModel):
    document_total: int
    indexed: int
    partial: int = 0  # 已分块但未向量化（关键词检索可用）
    pending: int
    processing: int
    failed: int
    chunk_total: int
    embedded_chunks: int


class HealthOut(BaseModel):
    status: str
    database_ok: bool
    database_message: str
    storage_mode: str
    ai_mode: str
    data_dir: str
