"""专属术语词典测试。

注意：为避免破坏用户已有数据，测试使用专属前缀的术语名，
并且只清理「本次测试创建」的条目（以测试开始前的快照为基准）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

PREFIX = "ZZ测试术语"


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def clean(client: TestClient):
    """记录快照，测试结束后只删除本次新增的术语。"""
    before = {t["id"] for t in client.get("/api/glossary").json()}
    yield
    for term in client.get("/api/glossary").json():
        if term["id"] not in before:
            client.delete(f"/api/glossary/{term['id']}")


def test_glossary_crud(client: TestClient, clean) -> None:
    created = client.post(
        "/api/glossary",
        json={
            "term": f"{PREFIX}KH",
            "definition": "KnowledgeHub 的缩写",
            "aliases": [f"{PREFIX}知识中心"],
            "category": "缩写",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["term"] == f"{PREFIX}KH"
    assert body["aliases"] == [f"{PREFIX}知识中心"]

    # 同名重复应被拒绝
    dup = client.post("/api/glossary", json={"term": f"{PREFIX}KH", "definition": "x"})
    assert dup.status_code == 422

    updated = client.put(f"/api/glossary/{body['id']}", json={"definition": "本地知识库平台"})
    assert updated.json()["definition"] == "本地知识库平台"

    listed = [t for t in client.get("/api/glossary").json() if t["id"] == body["id"]]
    assert len(listed) == 1

    client.delete(f"/api/glossary/{body['id']}")
    assert all(t["id"] != body["id"] for t in client.get("/api/glossary").json())


def test_glossary_lookup_matches_term_and_alias(client: TestClient, clean) -> None:
    client.post("/api/glossary", json={"term": f"{PREFIX}RAG", "definition": "检索增强生成"})
    client.post(
        "/api/glossary",
        json={
            "term": f"{PREFIX}KH",
            "definition": "KnowledgeHub",
            "aliases": [f"{PREFIX}知识中心"],
        },
    )

    # 命中术语名
    # 用「包含」而非「相等」断言：术语词典是全局数据，库里可能存在其它术语
    # （例如 'RAG' 恰好是本次查询文本的子串），用相等会误报失败。
    hit = client.post("/api/glossary/lookup", json={"text": f"{PREFIX}RAG 是什么"}).json()
    assert f"{PREFIX}RAG" in [t["term"] for t in hit["terms"]]

    # 命中别名
    hit2 = client.post("/api/glossary/lookup", json={"text": f"{PREFIX}知识中心怎么用"}).json()
    assert f"{PREFIX}KH" in [t["term"] for t in hit2["terms"]]

    # 未命中：不应误报（需求 17.4 的前置条件）
    hit3 = client.post(
        "/api/glossary/lookup", json={"text": f"{PREFIX}完全不存在的词条"}
    ).json()
    assert hit3["terms"] == []
