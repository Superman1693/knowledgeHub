"""AI 适配层抽象接口。

统一屏蔽「本地模型」与「外部 API」的差异，上层只依赖本接口。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class AIProvider(ABC):
    """聊天 + 嵌入 的统一接口。"""

    name: str = "base"

    @abstractmethod
    async def list_models(self) -> list[str]:
        """返回可用模型名列表。"""

    @abstractmethod
    async def health(self) -> tuple[bool, str]:
        """检测服务可用性，返回 (是否可用, 说明)。"""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        stream: bool = False,
    ) -> str | AsyncIterator[dict]:
        """对话生成。

        stream=False → 返回完整字符串；
        stream=True  → 返回异步迭代器，逐段产出
                       {"type": "reasoning"|"content", "text": str}。
                       推理模型（如 deepseek-v4）会先产出 reasoning 再产出 content。
        """

    @abstractmethod
    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """批量生成嵌入向量。"""
