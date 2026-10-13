"""双向链接 + 工作区（每日笔记 / 模板 / 扫描）回归测试。

覆盖 LocalMind「关联闭环」与「文件与数据库一致性」在本技术栈下的落地。
约定：用例自行清理创建的数据。
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import backup_service


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _create_note(client: TestClient, title: str, text: str = "") -> dict:
    resp = client.post("/api/documents/notes", json={"title": title, "content_text": text})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _purge(client: TestClient, doc_id: str) -> None:
    """尽力清理测试数据。

    某些运行环境会拦截批量文件删除（抛 SystemExit），此时数据库记录已删除、
    仅磁盘文件残留；清理失败不应让测试本身报错。
    """
    try:
        client.delete(f"/api/documents/{doc_id}/purge")
    except (Exception, SystemExit):  # noqa: BLE001
        pass


def _doc_file_path(doc_id: str) -> Path:
    from app.core.database import SessionLocal
    from app.models import Document

    db = SessionLocal()
    try:
        doc = db.get(Document, uuid.UUID(doc_id))
        assert doc is not None
        return Path(settings.data_path) / doc.file_path
    finally:
        db.close()


# ---------------- 双向链接 ----------------

def test_backlinks_and_outgoing(client: TestClient) -> None:
    """A 里写 [[B]]，B 创建后应互为关联：A 有出链，B 有反向链接。"""
    b = _create_note(client, "回归-链接目标B", "被引用的笔记")
    a = _create_note(client, "回归-链接来源A", "参考 [[回归-链接目标B]] 的结论")
    try:
        links_a = client.get(f"/api/documents/{a['id']}/links").json()
        assert links_a["outgoing_count"] == 1
        assert links_a["outgoing"][0]["target_title"] == "回归-链接目标B"
        assert links_a["outgoing"][0]["resolved"] is True
        assert links_a["outgoing"][0]["target_document_id"] == b["id"]

        links_b = client.get(f"/api/documents/{b['id']}/links").json()
        # 断言「包含 A 的反链」而非精确条数：同一标题可能被其它文档引用，
        # 精确计数会把无关文档也计入，属于脆弱断言
        assert any(x["source_document_id"] == a["id"] for x in links_b["backlinks"])
        assert any(
            x["source_document_title"] == "回归-链接来源A" for x in links_b["backlinks"]
        )
    finally:
        _purge(client, a["id"])
        _purge(client, b["id"])


def test_unresolved_link_resolved_after_target_created(client: TestClient) -> None:
    """先写指向不存在笔记的链接 → 未解析；目标创建后自动解析。"""
    a = _create_note(client, "回归-先写链接", "指向 [[回归-后建目标]]")
    target = None
    try:
        links = client.get(f"/api/documents/{a['id']}/links").json()
        assert links["unresolved_count"] == 1
        assert links["outgoing"][0]["resolved"] is False
        assert links["outgoing"][0]["target_document_id"] is None

        target = _create_note(client, "回归-后建目标", "后来才创建")
        links = client.get(f"/api/documents/{a['id']}/links").json()
        assert links["unresolved_count"] == 0
        assert links["outgoing"][0]["resolved"] is True
        assert links["outgoing"][0]["target_document_id"] == target["id"]
    finally:
        _purge(client, a["id"])
        if target:
            _purge(client, target["id"])


def test_links_rebuilt_when_content_changes(client: TestClient) -> None:
    """正文里的链接被删除后，出链也应随之清空。"""
    b = _create_note(client, "回归-链接重建B", "目标")
    a = _create_note(client, "回归-链接重建A", "有链接 [[回归-链接重建B]]")
    try:
        assert client.get(f"/api/documents/{a['id']}/links").json()["outgoing_count"] == 1
        client.put(f"/api/documents/{a['id']}", json={"content_text": "链接已删除"})
        assert client.get(f"/api/documents/{a['id']}/links").json()["outgoing_count"] == 0
    finally:
        _purge(client, a["id"])
        _purge(client, b["id"])


def test_link_targets_list(client: TestClient) -> None:
    doc = _create_note(client, "回归-补全标题", "内容")
    try:
        res = client.get("/api/documents/link-targets").json()
        assert "回归-补全标题" in res["titles"]
    finally:
        _purge(client, doc["id"])


def test_backup_covers_note_links() -> None:
    """note_links 必须进入备份清单（此前漏表导致备份丢数据）。"""
    names = {name for name, _ in backup_service.DUMP_TABLES}
    assert "note_links" in names
    assert "note_links" in backup_service.CLEAR_ORDER


# ---------------- 每日笔记 / 模板 ----------------

def test_daily_note_is_idempotent(client: TestClient) -> None:
    """今日笔记重复获取应返回同一篇，不重复创建。"""
    first = client.post("/api/workspace/daily").json()
    second = client.post("/api/workspace/daily").json()
    try:
        assert first["id"] == second["id"]
        assert first["source"] == "note"
    finally:
        _purge(client, first["id"])


def test_builtin_templates_available(client: TestClient) -> None:
    res = client.get("/api/workspace/templates").json()
    names = [t["name"] for t in res["items"]]
    assert "技术笔记" in names
    assert "项目复盘" in names

    detail = client.get("/api/workspace/templates/技术笔记.md").json()
    assert "## 背景" in detail["content"]


# ---------------- 工作台 ----------------

def test_workbench_summary(client: TestClient) -> None:
    res = client.get("/api/workspace/workbench").json()
    for key in ("recent_edited", "recent_viewed", "inbox", "favorites", "counts", "daily_title"):
        assert key in res
    assert res["counts"]["documents"] >= 0
    assert res["counts"]["trash"] >= 0
    assert isinstance(res["daily_title"], str) and res["daily_title"]


# ---------------- 外部变更扫描 ----------------

def test_scan_detects_and_syncs_external_change(
    client: TestClient, embedding_available: bool
) -> None:
    """在应用外改动 .md 后，扫描应发现并能在 apply 时同步内容。

    关注点是**发现 + 同步内容**。重建索引需要嵌入服务，配额耗尽时它按设计降级
    为 partial（内容已同步、关键词检索可用），此时不断言 reindexed 计数。
    """
    doc = _create_note(client, "回归-外部改动", "原始内容")
    path = _doc_file_path(doc["id"])
    try:
        # 模拟外部编辑：直接改磁盘文件
        path.write_text("外部写入的新内容 EXTERNALCHANGEZZQ", encoding="utf-8")

        report = client.post("/api/workspace/scan", params={"apply": False}).json()
        changed_ids = [c["document_id"] for c in report["changed"]]
        assert doc["id"] in changed_ids, "扫描未发现被外部改动的文件"

        applied = client.post("/api/workspace/scan", params={"apply": True}).json()
        # 重建索引需要嵌入服务：配额耗尽时它按设计降级，reindexed 不计入。
        # 本用例关注的是「发现 + 同步内容」，故只在嵌入可用时要求重建成功。
        if embedding_available:
            assert applied["applied"]["reindexed"] >= 1
        else:
            assert applied["applied"]["reindexed"] == 0

        detail = client.get(f"/api/documents/{doc['id']}").json()
        assert "EXTERNALCHANGEZZQ" in (detail["content_text"] or "")
        assert detail["chunk_count"] >= 1
    finally:
        _purge(client, doc["id"])


def test_scan_reports_orphan_file(client: TestClient) -> None:
    """未收录文件应被识别；且**只有显式确认**才会被收录为文档。

    ⚠️ 安全前提：`register_orphans=true` 会收录目录中**所有**未登记文件（产品行为，
    前端会先列出数量让用户确认）。因此若 `data/documents` 里已有历史残留文件，
    本用例会把它们**全部导入**，污染知识库、拖慢后续用例（甚至因批量嵌入失败而报错）。
    2026-10-12 实测：一次残留导致知识库从 3 篇膨胀到 66 篇。
    所以这里先检查基线，环境不干净就直接 skip，**不带病执行**。
    """
    baseline = client.post("/api/workspace/scan", params={"apply": False}).json()
    if baseline["orphan_count"] > 0:
        pytest.skip(
            f"data/documents 已存在 {baseline['orphan_count']} 个未收录文件（环境残留）；"
            "register_orphans 会把它们全部导入，故跳过本用例"
        )

    unique = f"回归-未收录-{uuid.uuid4().hex[:8]}.md"
    orphan = settings.documents_path / unique
    orphan.write_text("# 未收录\n\n直接放进目录的文件", encoding="utf-8")
    registered_ids: list[str] = []
    try:
        report = client.post("/api/workspace/scan", params={"apply": False}).json()
        assert any(o["filename"] == unique for o in report["orphan"])
        assert report["orphan_count"] == 1, "干净环境下应只有本用例制造的未收录文件"

        # 只重建索引（apply=true）不应收录未登记文件——这是刻意的安全边界
        client.post("/api/workspace/scan", params={"apply": True}).json()
        items = client.get("/api/documents", params={"q": unique}).json()["items"]
        assert not any(d["title"] == unique for d in items), (
            "apply=true 不应自动收录未登记文件"
        )

        # 显式确认收录
        res = client.post(
            "/api/workspace/scan",
            params={"apply": False, "register_orphans": True},
        ).json()
        registered_ids = list(res["applied"]["registered"])
        assert len(registered_ids) == 1, "干净环境下只应收录本用例的文件"
        items = client.get("/api/documents", params={"q": unique}).json()["items"]
        assert any(d["title"] == unique for d in items), "显式确认后应收录未登记文件"
    finally:
        for doc_id in registered_ids:
            _purge(client, doc_id)
        if orphan.exists():
            try:
                orphan.unlink()
            except OSError:
                pass
