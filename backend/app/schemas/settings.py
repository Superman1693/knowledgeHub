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
    # LLM 重排序（检索后用对话模型精排）。此前后端已实现但设置页无法开启，
    # 等于功能不可达——这里补上开关与候选数量。
    rerank_enabled: bool = False
    rerank_candidates: int = 10
    # 回收站保留天数：0 = 永不自动清理（默认）
    trash_retention_days: int = 0


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
    # LLM 重排序：开启后检索会用对话模型对候选重新排序（更准，但更慢、更费额度）
    rerank_enabled: bool | None = None
    rerank_candidates: int | None = Field(default=None, ge=1, le=50)
    # 回收站保留天数：0 = 永不自动清理
    trash_retention_days: int | None = Field(default=None, ge=0, le=3650)


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
    # 此前 service 层已计算、但 schema 未声明 → 被 Pydantic 静默丢弃
    note_total: int = 0
    trash_total: int = 0


class HealthOut(BaseModel):
    status: str
    database_ok: bool
    database_message: str
    storage_mode: str
    ai_mode: str
    data_dir: str
    # 可选能力状态：让用户一眼看出分词与 OCR 是否生效
    segmentation: str = "bigram"  # jieba / bigram
    ocr_engine: str | None = None  # rapidocr / tesseract / None（不可用）
    ocr_available: bool = False
    # 拼音检索是否可用（未安装 pypinyin 时为 False，检索退回纯文本匹配）
    pinyin_search: bool = False
