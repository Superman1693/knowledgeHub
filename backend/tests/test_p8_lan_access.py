"""2026-10-13 第八轮：局域网访问的安全闸门。

给「手机访问知识库」开一扇门，同时必须保证这扇门不能敞着——
知识库里是私人笔记，局域网不等于可信网络。

两条不变量：
1. 对外监听却没设口令 → **拒绝启动**（fail-closed，宁可起不来也不要静默裸露）；
2. 设了口令 → 所有 /api/* 请求都要校验，且用常量时间比较。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import (
    TOKEN_HEADER,
    assert_exposure_is_safe,
    is_loopback,
)
from app.main import app


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_is_loopback_recognizes_local_hosts() -> None:
    for host in ("127.0.0.1", "localhost", "::1", " 127.0.0.1 "):
        assert is_loopback(host), f"{host!r} 应判为仅本机"
    for host in ("0.0.0.0", "192.168.1.10", "10.0.0.5", ""):
        assert not is_loopback(host), f"{host!r} 不应判为仅本机"


def test_refuses_to_start_when_exposed_without_token(monkeypatch) -> None:
    """对外监听 + 无口令 → 必须拒绝启动。这是本轮最关键的一条守卫。"""
    monkeypatch.setattr(settings, "backend_host", "0.0.0.0")
    monkeypatch.setattr(settings, "access_token", "")
    with pytest.raises(RuntimeError) as exc:
        assert_exposure_is_safe()
    # 报错信息要能直接指导用户怎么修
    assert "ACCESS_TOKEN" in str(exc.value)
    assert "127.0.0.1" in str(exc.value)


def test_allows_loopback_without_token(monkeypatch) -> None:
    """默认场景：仅本机且无口令 —— 正常放行，不影响本机使用。"""
    monkeypatch.setattr(settings, "backend_host", "127.0.0.1")
    monkeypatch.setattr(settings, "access_token", "")
    assert_exposure_is_safe()


def test_allows_exposed_with_token(monkeypatch) -> None:
    """对外监听 + 已设口令 → 放行。"""
    monkeypatch.setattr(settings, "backend_host", "0.0.0.0")
    monkeypatch.setattr(settings, "access_token", "s3cret-token")
    assert_exposure_is_safe()


def test_token_middleware_blocks_and_allows(monkeypatch, client: TestClient) -> None:
    """设了口令后：无口令/错口令 401，正确口令放行。"""
    monkeypatch.setattr(settings, "access_token", "test-token-123")

    # 无口令
    r = client.get("/api/health")
    assert r.status_code == 401, "未带口令不应放行"
    assert "口令" in r.text

    # 错口令
    r = client.get("/api/health", headers={TOKEN_HEADER: "wrong"})
    assert r.status_code == 401

    # 正确口令（请求头）
    r = client.get("/api/health", headers={TOKEN_HEADER: "test-token-123"})
    assert r.status_code == 200

    # 正确口令（查询串：浏览器直接访问 /docs 时无法加头，这是兜底通道）
    r = client.get("/api/health", params={"token": "test-token-123"})
    assert r.status_code == 200


def test_token_middleware_leaves_non_api_paths_alone(monkeypatch, client: TestClient) -> None:
    """非 /api 路径不拦：前端静态资源本身不含数据，且拦了用户连口令框都看不到。"""
    monkeypatch.setattr(settings, "access_token", "test-token-123")
    r = client.get("/docs")
    assert r.status_code != 401, "静态/文档路径不应被口令中间件拦截"


def test_middleware_is_permissive_when_no_token(monkeypatch, client: TestClient) -> None:
    """未设口令时中间件直通（本机默认场景不能受影响）。"""
    monkeypatch.setattr(settings, "access_token", "")
    r = client.get("/api/health")
    assert r.status_code == 200
