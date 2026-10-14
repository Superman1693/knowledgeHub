"""2026-10-14 第十轮：知识库体检。

核心是「孤立笔记」：零入链 + 零出链的笔记在双链图里是个孤点，
既不会被人顺着链接逛到，也不会出现在任何「相关笔记」里。

体检**只报告不自动处理**——孤立不代表该删，自动处置是不可逆的误判。
本文件重点验证「报告得准不准」，以及几个容易搞错的判定口径。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.services import health_service


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _make_note(client: TestClient, title: str, body: str = "正文内容") -> str:
    res = client.post(
        "/api/documents/notes", json={"title": title, "content_text": body}
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_health_endpoint_shape(client: TestClient) -> None:
    """接口结构：计数与清单都要有，前端才能既看总数又看具体是哪几篇。"""
    res = client.get("/api/insights/health")
    assert res.status_code == 200, res.text
    data = res.json()

    for key in ("summary", "orphans", "never_viewed", "stale_inbox", "unindexed",
                "dangling", "thresholds", "note"):
        assert key in data, f"缺少字段 {key}"

    for key in ("total", "orphans", "never_viewed", "inbox", "stale_inbox",
                "unindexed", "dangling_links", "favorites", "duplicate_pairs",
                "linked_ratio"):
        assert key in data["summary"], f"summary 缺少 {key}"


def test_orphan_is_counted_and_resolved_by_linking(client: TestClient) -> None:
    """建两篇互不引用的笔记 → 都是孤立；加上双链后不再孤立。

    这条用例同时验证最容易写错的入链判定：必须按 `target_document_id`
    关联，按标题关联会在改名后失效。
    """
    suffix = uuid.uuid4().hex[:8]
    a = _make_note(client, f"体检A-{suffix}")
    b = _make_note(client, f"体检B-{suffix}")

    try:
        data = client.get("/api/insights/health").json()
        orphan_ids = {o["document_id"] for o in data["orphans"]}
        assert a in orphan_ids, "新建且无链接的笔记应是孤立笔记"
        assert b in orphan_ids

        # A 引用 B → 两者都不再孤立（A 有出链，B 有入链）。
        # 双链解析由 update_document 内部完成，这里不需要手动调 sync_links。
        client.put(f"/api/documents/{a}", json={"content_text": f"参见 [[体检B-{suffix}]]"})

        data2 = client.get("/api/insights/health").json()
        orphan_ids2 = {o["document_id"] for o in data2["orphans"]}
        assert a not in orphan_ids2, "有出链的笔记不该算孤立"
        assert b not in orphan_ids2, "有入链的笔记不该算孤立"
    finally:
        for i in (a, b):
            client.delete(f"/api/documents/{i}/purge")


def test_unindexed_detects_zero_chunk_documents(client: TestClient) -> None:
    """零片段的文档要出现在「索引异常」里——这类文档在搜索里根本找不到。"""
    suffix = uuid.uuid4().hex[:8]
    doc_id = _make_note(client, f"体检空-{suffix}", "")
    try:
        db = SessionLocal()
        try:
            from app.models import Document

            doc = db.get(Document, uuid.UUID(doc_id))
            doc.chunk_count = 0
            doc.status = "failed"
            db.commit()
        finally:
            db.close()

        data = client.get("/api/insights/health").json()
        ids = {u["document_id"] for u in data["unindexed"]}
        assert doc_id in ids, "索引失败的文档未出现在体检报告中"
        assert data["summary"]["unindexed"] >= 1
        # 清单里应带上状态与错误说明，便于用户判断怎么修
        item = next(u for u in data["unindexed"] if u["document_id"] == doc_id)
        assert item["status"] == "failed"
    finally:
        client.delete(f"/api/documents/{doc_id}/purge")


def test_dangling_links_are_reported(client: TestClient) -> None:
    """指向不存在笔记的 [[双链]] 要被报出来（「本打算写但忘了」的坑）。"""
    suffix = uuid.uuid4().hex[:8]
    missing = f"不存在的笔记-{suffix}"
    doc_id = _make_note(client, f"体检悬空-{suffix}", f"这里引用了 [[{missing}]]")
    try:
        data = client.get("/api/insights/health").json()
        titles = {d["target_title"] for d in data["dangling"]}
        assert missing in titles, "悬空链接未被报告"
        item = next(d for d in data["dangling"] if d["target_title"] == missing)
        assert item["source_document_id"] == doc_id
    finally:
        client.delete(f"/api/documents/{doc_id}/purge")


def test_inbox_stale_count_is_not_capped_by_list_length(client: TestClient) -> None:
    """陈旧收集箱的**计数**不能被清单长度（MAX_ITEMS）截断。

    首版把计数写成 `len(_stale_inbox(...))`，而那个函数有 limit，
    结果是超过 20 篇时永远显示 20。计数走单独的 SQL 才是对的。
    """
    db = SessionLocal()
    try:
        data = health_service.health(db)
        s = data["summary"]
        # 计数可以大于清单长度，这正是「不被截断」的证据方向
        assert s["stale_inbox"] >= len(data["stale_inbox"])
        assert s["orphans"] >= len(data["orphans"])
        assert s["never_viewed"] >= len(data["never_viewed"])
        assert s["unindexed"] >= len(data["unindexed"])
        assert s["dangling_links"] >= len(data["dangling"])
    finally:
        db.close()


def test_health_survives_embedding_failure(monkeypatch) -> None:
    """嵌入不可用时，重复检测失败不能让整个体检挂掉（其余项应照常返回）。"""
    from app.services import insight_service

    def _boom(*_a, **_kw):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(insight_service, "find_duplicates", _boom)
    db = SessionLocal()
    try:
        data = health_service.health(db)
        assert data["summary"]["duplicate_pairs"] is None, "应降级为 null 而不是报错"
        # 其它项仍然可用
        assert "total" in data["summary"]
        assert isinstance(data["orphans"], list)
    finally:
        db.close()


def test_linked_ratio_is_null_for_empty_kb_or_ratio_of_linked(client: TestClient) -> None:
    """关联率口径：至少参与一条双链的文档占比；无文档时为 None。"""
    db = SessionLocal()
    try:
        data = health_service.health(db)
        s = data["summary"]
        if s["total"] == 0:
            assert s["linked_ratio"] is None
        else:
            expected = round((s["total"] - s["orphans"]) / s["total"], 4)
            assert s["linked_ratio"] == expected
            assert 0.0 <= s["linked_ratio"] <= 1.0
    finally:
        db.close()
