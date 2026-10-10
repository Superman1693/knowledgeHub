"""外部模型适配（OpenAI 兼容 API）。"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.ai.base import AIProvider
from app.core.config import settings
from app.core.exceptions import AIUnavailableError


class ExternalProvider(AIProvider):
    name = "external"

    def __init__(
        self, base_url: str | None = None, api_key: str | None = None
    ) -> None:
        """可显式指定地址与密钥，便于「对话」与「嵌入」使用不同服务。"""
        base = base_url if base_url is not None else settings.external_api_base_url
        key = api_key if api_key is not None else settings.external_api_key
        self.base = (base or "").rstrip("/")
        self.key = key or ""
        self.timeout = settings.request_timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    def _require_config(self) -> None:
        if not self.base:
            raise AIUnavailableError("未配置外部服务地址（EXTERNAL_API_BASE_URL 为空）")
        if not self.key:
            raise AIUnavailableError("未配置外部服务密钥（EXTERNAL_API_KEY 为空）")

    async def list_models(self) -> list[str]:
        try:
            self._require_config()
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base}/models", headers=self._headers)
                resp.raise_for_status()
                data = resp.json()
                return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        except Exception:  # noqa: BLE001
            return []

    async def health(self) -> tuple[bool, str]:
        if not self.base or not self.key:
            return False, "外部服务未配置完整（缺少地址或密钥）"
        models = await self.list_models()
        if models:
            return True, f"外部服务可用，共 {len(models)} 个模型"
        return False, "外部服务不可用或鉴权失败"

    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        stream: bool = False,
    ) -> str | AsyncIterator[dict]:
        self._require_config()
        model = model or settings.chat_model
        if not model:
            raise AIUnavailableError("未配置聊天模型（CHAT_MODEL 为空）")
        payload = {"model": model, "messages": messages, "stream": stream}

        if stream:
            return self._stream_chat(payload)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base}/chat/completions",
                    headers=self._headers,
                    json=payload,
                )
                resp.raise_for_status()
                choices = resp.json().get("choices", [])
                return choices[0]["message"]["content"] if choices else ""
        except httpx.HTTPError as exc:
            raise AIUnavailableError(f"外部服务调用失败：{exc}") from exc

    async def _stream_chat(self, payload: dict) -> AsyncIterator[dict]:
        """流式返回增量。

        产出形如 {"type": "reasoning"|"content", "text": str}：
        - reasoning：推理模型的思考过程（deepseek-v4 等会先输出 reasoning_content）
        - content  ：最终回答内容
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base}/chat/completions",
                    headers=self._headers,
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        # 部分服务会发送 choices 为空数组的块（如仅含 usage 的收尾块）
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        reasoning = delta.get("reasoning_content")
                        if reasoning:
                            yield {"type": "reasoning", "text": reasoning}
                        piece = delta.get("content")
                        if piece:
                            yield {"type": "content", "text": piece}
        except httpx.HTTPError as exc:
            raise AIUnavailableError(f"外部服务流式调用失败：{exc}") from exc

    async def embed(
        self, texts: list[str], model: str | None = None
    ) -> list[list[float]]:
        self._require_config()
        model = model or settings.embedding_model
        if not model:
            raise AIUnavailableError("未配置嵌入模型（EMBEDDING_MODEL 为空）")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base}/embeddings",
                    headers=self._headers,
                    json={"model": model, "input": texts},
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])
                return [item["embedding"] for item in data]
        except httpx.HTTPError as exc:
            raise AIUnavailableError(f"外部嵌入调用失败：{exc}") from exc
