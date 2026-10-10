"""API 接口测试（需要数据库可用且已执行迁移）。

运行前请确保：
1. PostgreSQL 已启动、.env 配置正确；
2. 已执行 `python -m alembic upgrade head`。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_root(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["app"] == "KnowledgeHub"


def test_health(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "database_ok" in body
    assert "storage_mode" in body
    assert body["storage_mode"] in ("postgres", "sqlite")


def test_settings_get(client: TestClient) -> None:
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert "ai_mode" in resp.json()


def test_index_status(client: TestClient) -> None:
    resp = client.get("/api/settings/index-status")
    assert resp.status_code == 200
    assert "chunk_total" in resp.json()


def test_documents_list(client: TestClient) -> None:
    resp = client.get("/api/documents")
    assert resp.status_code == 200
    assert "items" in resp.json()


def test_categories_list(client: TestClient) -> None:
    resp = client.get("/api/categories")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_tags_list(client: TestClient) -> None:
    resp = client.get("/api/tags")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_search_keyword(client: TestClient) -> None:
    resp = client.post("/api/search", json={"query": "测试", "mode": "keyword", "top_k": 5})
    assert resp.status_code == 200
    assert "hits" in resp.json()


def test_regenerate_unknown_message_returns_error_event(client: TestClient) -> None:
    """对不存在的消息重新生成，应以 SSE error 事件明确失败（不依赖模型）。"""
    import uuid

    resp = client.post(f"/api/messages/{uuid.uuid4()}/regenerate")
    assert resp.status_code == 200
    assert "event: error" in resp.text
