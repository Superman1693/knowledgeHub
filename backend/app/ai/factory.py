"""AI 提供方工厂。

对话与嵌入可以是**不同的服务**：
- 对话：由 AI_MODE 决定（local = Ollama 兼容 / external = OpenAI 兼容）
- 嵌入：若单独配置了 EMBEDDING_BASE_URL，则使用该独立服务；
        否则复用对话提供方（例如本地 Ollama 同时提供 chat 与 embed）。
"""
from __future__ import annotations

from app.ai.base import AIProvider
from app.ai.external_provider import ExternalProvider
from app.ai.local_provider import LocalProvider
from app.core.config import settings


def get_provider(mode: str | None = None) -> AIProvider:
    """返回对话提供方：local（默认）/ external。"""
    resolved = (mode or settings.ai_mode or "local").lower()
    if resolved == "external":
        return ExternalProvider()
    return LocalProvider()


def get_embedding_provider() -> AIProvider:
    """返回嵌入提供方（可能来自与对话不同的服务）。"""
    base = (settings.embedding_base_url or "").strip()
    if base:
        return ExternalProvider(base_url=base, api_key=settings.embedding_api_key)
    return get_provider()


def embedding_configured() -> bool:
    """嵌入能力是否已配置完整。"""
    if not (settings.embedding_model or "").strip():
        return False
    base = (settings.embedding_base_url or "").strip()
    if base:
        return bool((settings.embedding_api_key or "").strip())
    if (settings.ai_mode or "").lower() == "external":
        return bool((settings.external_api_base_url or "").strip()) and bool(
            (settings.external_api_key or "").strip()
        )
    return True  # 本地模式：地址有默认值
