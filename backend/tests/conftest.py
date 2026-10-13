"""pytest 公共配置。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# 保证能 import app 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session")
def embedding_available() -> bool:
    """探测一次嵌入服务是否可用（会话级，避免每个用例都打一次 API）。

    本机的嵌入服务走外部免费额度，配额耗尽时返回 403。此时凡是
    「语义检索 / 重建索引」类用例都会按设计降级（关键词检索仍可用），
    并非代码缺陷——应该跳过或断言降级行为，而不是报红。
    """
    from app.rag import indexer

    try:
        vec = asyncio.run(indexer.embed_query("连接性探测"))
    except Exception:  # noqa: BLE001
        return False
    return bool(vec)


@pytest.fixture
def requires_embedding(embedding_available: bool) -> None:
    """在依赖嵌入服务的用例上声明：不可用时跳过并说明原因。"""
    if not embedding_available:
        pytest.skip("嵌入服务当前不可用（配额耗尽或网络故障），语义检索类用例跳过")
