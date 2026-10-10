"""应用配置：从环境变量 / .env 读取，集中管理。

所有配置项均可通过 .env 覆盖，禁止在源码中硬编码密钥。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（backend/app/core/config.py → 上溯 3 级）
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """KnowledgeHub 运行配置。"""

    model_config = SettingsConfigDict(
        # 同时支持从项目根目录与 backend/ 目录启动
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 数据库 ----------
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "knowledgehub"
    db_user: str = "kh_app"
    db_password: str = ""
    # 若显式提供 database_url，则优先使用（便于切换回退方案）
    database_url: str | None = None

    # ---------- 存储模式 ----------
    # postgres | sqlite（sqlite 为回退方案，需安装 requirements-fallback.txt）
    storage_mode: str = "postgres"

    # ---------- 数据目录 ----------
    data_dir: str = "./data"

    # ---------- 服务地址 ----------
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_port: int = 5173
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # ---------- 上传限制 ----------
    max_upload_mb: int = 50

    # ---------- AI 服务 ----------
    ai_mode: str = "local"  # local | external
    local_model_base_url: str = "http://127.0.0.1:11434"
    external_api_base_url: str = ""
    external_api_key: str = ""
    chat_model: str = ""
    embedding_model: str = ""
    embedding_dim: int = 1024
    # 嵌入服务可与对话服务分离（留空则复用对话服务的地址与密钥）
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    request_timeout: int = 60
    default_answer_mode: str = "detail"  # detail | brief | example

    # ---------- 检索参数 ----------
    hybrid_alpha: float = 0.3  # 关键词权重
    hybrid_beta: float = 0.7  # 语义权重
    search_top_k: int = 8
    chunk_size: int = 800  # 分块目标字符数
    chunk_overlap: int = 100

    # ---------- 派生属性 ----------
    @property
    def resolved_database_url(self) -> str:
        """返回实际使用的 SQLAlchemy 连接串。"""
        if self.database_url:
            return self.database_url
        if self.storage_mode == "sqlite":
            return f"sqlite:///{self.data_path / 'app.db'}"
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def data_path(self) -> Path:
        """数据目录。相对路径一律相对项目根解析，避免因启动目录不同而漂移。"""
        p = Path(self.data_dir).expanduser()
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p.resolve()

    @property
    def documents_path(self) -> Path:
        return self.data_path / "documents"

    @property
    def attachments_path(self) -> Path:
        return self.data_path / "attachments"

    @property
    def exports_path(self) -> Path:
        return self.data_path / "exports"

    @property
    def cache_path(self) -> Path:
        return self.data_path / "cache"

    @property
    def logs_path(self) -> Path:
        return self.data_path / "logs"

    @property
    def backups_path(self) -> Path:
        return self.data_path / "backups"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        """创建全部数据子目录（首次启动初始化）。"""
        for p in (
            self.data_path,
            self.documents_path,
            self.attachments_path,
            self.exports_path,
            self.backups_path,
            self.cache_path,
            self.logs_path,
        ):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
