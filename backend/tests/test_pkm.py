"""个人知识库（PKM）能力回归测试。

覆盖 LocalMind 设计在现有技术栈下的落地：
写入闭环（新建/编辑写回/版本历史）、回收站、隐私过滤（ai_enabled）、整库导出。

约定：每个用例自行清理创建的数据（purge + 删除导出产物），不依赖 AI 服务。
"""
from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _create_note(client: TestClient, title: str, text: str) -> dict:
    resp = client.post(
        "/api/documents/notes",
        json={"title": title, "content_text": text},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _purge(client: TestClient, doc_id: str) -> None:
    """尽力清理；某些环境会拦截批量文件删除，清理失败不应让测试报错。"""
    try:
        client.delete(f"/api/documents/{doc_id}/purge")
    except (Exception, SystemExit):  # noqa: BLE001
        pass


# ---------------- 写入闭环 ----------------

def test_create_note_writes_markdown_file(client: TestClient) -> None:
    """新建笔记必须真的落盘成 .md，并完成分块。"""
    doc = _create_note(client, "回归-新建笔记", "# 标题\n\n正文内容，用于验证写入闭环。")
    try:
        assert doc["source"] == "note"
        assert doc["ai_enabled"] is True
        assert doc["chunk_count"] >= 1

        real = _doc_file_path(doc["id"])
        assert real.exists(), "新建笔记未写入磁盘"
        assert "写入闭环" in real.read_text(encoding="utf-8")

        detail = client.get(f"/api/documents/{doc['id']}").json()
        assert detail["content_text"].startswith("# 标题")
    finally:
        _purge(client, doc["id"])


def _doc_file_path(doc_id: str) -> Path:
    """从数据库取该文档的磁盘路径（比按 mtime 猜文件可靠）。"""
    from app.core.database import SessionLocal
    from app.models import Document

    db = SessionLocal()
    try:
        doc = db.get(Document, uuid.UUID(doc_id))
        assert doc is not None
        return Path(settings.data_path) / doc.file_path
    finally:
        db.close()


def test_update_note_writes_back_and_creates_revision(client: TestClient) -> None:
    """编辑正文必须同时：写回磁盘 + 生成历史版本 + 重建索引。"""
    doc = _create_note(client, "回归-编辑笔记", "第一版内容")
    doc_id = doc["id"]
    try:
        file_path = _doc_file_path(doc_id)
        assert "第一版内容" in file_path.read_text(encoding="utf-8")

        resp = client.put(
            f"/api/documents/{doc_id}",
            json={"content_text": "第二版内容（已修改）"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["content_text"] == "第二版内容（已修改）"

        # 1) 写回磁盘
        assert "第二版内容" in file_path.read_text(encoding="utf-8")
        # 2) 版本历史记录了旧版
        revs = client.get(f"/api/documents/{doc_id}/revisions").json()
        assert len(revs) == 1
        detail = client.get(f"/api/documents/{doc_id}/revisions/{revs[0]['id']}").json()
        assert detail["content_text"] == "第一版内容"
        # 3) 索引已重建
        assert resp.json()["chunk_count"] >= 1
    finally:
        _purge(client, doc_id)


def test_restore_revision_rolls_back(client: TestClient) -> None:
    doc = _create_note(client, "回归-回滚", "原始正文")
    doc_id = doc["id"]
    try:
        client.put(f"/api/documents/{doc_id}", json={"content_text": "被改坏的正文"})
        revs = client.get(f"/api/documents/{doc_id}/revisions").json()
        assert revs

        restored = client.post(
            f"/api/documents/{doc_id}/revisions/{revs[0]['id']}/restore"
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["content_text"] == "原始正文"
    finally:
        _purge(client, doc_id)


# ---------------- 回收站 ----------------

def test_soft_delete_and_restore(client: TestClient) -> None:
    doc = _create_note(client, "回归-回收站", "回收站验证内容")
    doc_id = doc["id"]
    file_path = _doc_file_path(doc_id)
    try:
        # 软删除
        assert client.delete(f"/api/documents/{doc_id}").status_code == 204

        listed = client.get("/api/documents").json()["items"]
        assert all(d["id"] != doc_id for d in listed), "软删除后不应出现在列表"
        trash = client.get("/api/documents/trash").json()["items"]
        assert any(d["id"] == doc_id for d in trash), "软删除后应出现在回收站"
        assert file_path.exists(), "软删除必须保留磁盘原文件"

        # 恢复
        assert client.post(f"/api/documents/{doc_id}/restore").status_code == 200
        listed = client.get("/api/documents").json()["items"]
        assert any(d["id"] == doc_id for d in listed)
    finally:
        _purge(client, doc_id)


# ---------------- 隐私：ai_enabled 检索过滤 ----------------

def test_ai_enabled_filters_ai_retrieval(client: TestClient) -> None:
    """设为私密后，AI 检索（ai_only）必须排除；用户自己检索仍可见。"""
    marker = "私有标记ZZQ"
    doc = _create_note(client, "回归-私密笔记", f"内容包含 {marker} 用于检索验证")
    doc_id = doc["id"]
    try:
        # 默认允许 AI：ai_only 能命中
        r1 = client.post(
            "/api/search", json={"query": marker, "mode": "keyword", "ai_only": True}
        ).json()
        assert any(h["document_id"] == doc_id for h in r1["hits"])

        # 设为私密
        assert (
            client.put(f"/api/documents/{doc_id}", json={"ai_enabled": False}).status_code
            == 200
        )

        # AI 检索被排除
        r2 = client.post(
            "/api/search", json={"query": marker, "mode": "keyword", "ai_only": True}
        ).json()
        assert all(h["document_id"] != doc_id for h in r2["hits"]), "私密笔记不应进入 AI 检索"

        # 用户自己的检索仍可命中（本地知识库不应把用户锁在门外）
        r3 = client.post(
            "/api/search", json={"query": marker, "mode": "keyword", "ai_only": False}
        ).json()
        assert any(h["document_id"] == doc_id for h in r3["hits"])
    finally:
        _purge(client, doc_id)


# ---------------- 检索高亮与排序 ----------------

def test_search_returns_highlights(client: TestClient) -> None:
    doc = _create_note(client, "回归-高亮", "关键词HIGHLIGHTZZQ 出现在正文中")
    doc_id = doc["id"]
    try:
        res = client.post(
            "/api/search",
            json={"query": "HIGHLIGHTZZQ", "mode": "keyword", "sort": "updated"},
        ).json()
        hit = next((h for h in res["hits"] if h["document_id"] == doc_id), None)
        assert hit is not None
        assert hit["highlights"], "应返回命中词用于前端高亮"
        assert hit["document_updated_at"], "应返回文档更新时间用于排序"
    finally:
        _purge(client, doc_id)


# ---------------- 整库导出 ----------------

def test_export_all_contains_front_matter(client: TestClient) -> None:
    doc = _create_note(client, "回归-导出", "导出验证正文")
    doc_id = doc["id"]
    dest: Path | None = None
    try:
        res = client.post("/api/documents/export-all").json()
        assert res["count"] >= 1
        dest = Path(res["path"])
        assert dest.exists()

        with zipfile.ZipFile(dest) as zf:
            names = zf.namelist()
            assert "manifest.json" in names
            md = next(n for n in names if n.endswith(".md"))
            body = zf.read(md).decode("utf-8")
            assert body.startswith("---"), "导出应带 YAML front-matter"
            assert "aiEnabled:" in body
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            assert manifest["count"] == res["count"]
    finally:
        _purge(client, doc_id)
        if dest and dest.exists():
            dest.unlink()
