"""本地模型适配（Ollama 兼容接口）。"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.ai.base import AIProvider
from app.core.config import settings
from app.core.exceptions import AIUnavailableError


class LocalProvider(AIProvider):
    name = "local"

    def __init__(self) -> None:
        self.base = settings.local_model_base_url.rstrip("/")
        self.timeout = settings.request_timeout

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:  # noqa: BLE001
            return []

    async def health(self) -> tuple[bool, str]:
        models = await self.list_models()
        if models:
            return True, f"本地模型服务可用，共 {len(models)} 个模型"
        return False, f"本地模型服务不可用（请确认 {self.base} 可访问、Ollama 已启动）"

    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        stream: bool = False,
    ) -> str | AsyncIterator[dict]:
        model = model or settings.chat_model
        if not model:
            raise AIUnavailableError("未配置聊天模型（CHAT_MODEL 为空）")
        payload = {"model": model, "messages": messages, "stream": stream}

        if stream:
            return self._stream_chat(payload)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base}/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json().get("message", {}).get("content", "")
        except httpx.HTTPError as exc:
            raise AIUnavailableError(f"本地模型调用失败：{exc}") from exc

    async def _stream_chat(self, payload: dict) -> AsyncIterator[dict]:
        """流式返回增量：{"type": "reasoning"|"content", "text": str}。

        Ollama 对思考型模型会在 message.thinking 中给出思考过程。
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", f"{self.base}/api/chat", json=payload
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        message = obj.get("message", {})
                        thinking = message.get("thinking")
                        if thinking:
                            yield {"type": "reasoning", "text": thinking}
                        piece = message.get("content", "")
                        if piece:
                            yield {"type": "content", "text": piece}
        except httpx.HTTPError as exc:
            raise AIUnavailableError(f"本地模型流式调用失败：{exc}") from exc

    async def embed(
        self, texts: list[str], model: str | None = None
    ) -> list[list[float]]:
        """批量生成嵌入，按 `embedding_batch_size` 分批（与外部服务行为一致）。"""
        model = model or settings.embedding_model
        if not model:
            raise AIUnavailableError("未配置嵌入模型（EMBEDDING_MODEL 为空）")
        if not texts:
            return []

        size = max(1, settings.embedding_batch_size)
        out: list[list[float]] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for start in range(0, len(texts), size):
                    batch = texts[start : start + size]
                    resp = await client.post(
                        f"{self.base}/api/embed",
                        json={"model": model, "input": batch},
                    )
                    if resp.status_code == 404:
                        # 兼容旧版 Ollama 接口（逐条提交）
                        for text in batch:
                            rr = await client.post(
                                f"{self.base}/api/embeddings",
                                json={"model": model, "prompt": text},
                            )
                            rr.raise_for_status()
                            out.append(rr.json()["embedding"])
                        continue
                    resp.raise_for_status()
                    vecs = resp.json().get("embeddings", [])
                    if len(vecs) != len(batch):
                        # 数量不匹配会让向量与片段错位，宁可失败也不写入错误索引
                        raise AIUnavailableError(
                            f"嵌入返回数量不匹配：请求 {len(batch)} 条，返回 {len(vecs)} 条"
                        )
                    out.extend(vecs)
        except httpx.HTTPError as exc:
            raise AIUnavailableError(f"本地嵌入调用失败：{exc}") from exc
        return out
