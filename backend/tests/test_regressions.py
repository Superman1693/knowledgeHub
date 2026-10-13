"""2026-10-11 缺陷排查确认问题的回归测试。

约束：这些测试**不得破坏**库中已有资料——凡会改数据的用例，
都在 finally 中清理自己创建的行；不依赖 AI 服务。
"""
from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.main import app
from app.models import Conversation, Document, Tag
from app.services import backup_service, chat_service
from app.storage import files


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


# ---------------- P0：备份 / 恢复 ----------------

def test_dump_covers_all_business_tables() -> None:
    """转储与清空清单必须覆盖全部业务表（此前漏了 glossary_terms / quiz_records）。"""
    db = SessionLocal()
    try:
        data = backup_service.dump_all(db)
    finally:
        db.close()

    names = {name for name, _ in backup_service.DUMP_TABLES}
    assert "glossary_terms" in names
    assert "quiz_records" in names
    assert "glossary_terms" in data and "quiz_records" in data
    # 清空清单同样要包含，否则恢复后残留脏数据
    assert "glossary_terms" in backup_service.CLEAR_ORDER
    assert "quiz_records" in backup_service.CLEAR_ORDER


def test_dump_orders_parent_chunks_before_children() -> None:
    """chunks 转储顺序必须「父块在前」，否则恢复时自引用外键违约。"""
    db = SessionLocal()
    try:
        rows = backup_service.dump_all(db)["chunks"]
    finally:
        db.close()

    seen: set[str] = set()
    for row in rows:
        parent_id = row.get("parent_id")
        if parent_id:
            assert str(parent_id) in seen, "子块出现在其父块之前：恢复会触发外键违约"
        seen.add(str(row["id"]))


def test_safe_restore_target_blocks_zip_slip() -> None:
    """备份条目越出数据目录时必须被拒绝（Zip Slip）。"""
    assert backup_service._safe_restore_target("documents/a.md") is not None
    assert backup_service._safe_restore_target("../evil.txt") is None
    assert backup_service._safe_restore_target("documents/../../../evil.txt") is None


# ---------------- P1：标签去重 ----------------

def test_set_document_tags_dedupes(client: TestClient) -> None:
    """重复标签名不得触发 UniqueViolation（此前返回 500）。"""
    db = SessionLocal()
    doc = Document(
        title="regression-doc.md",
        original_filename="regression-doc.md",
        file_path="documents/regression-doc.md",
        file_type="md",
        file_size=1,
    )
    db.add(doc)
    db.commit()
    doc_id = doc.id
    db.close()

    try:
        resp = client.post(
            f"/api/tags/document/{doc_id}",
            json={"names": ["回归标签A", "回归标签A", " 回归标签A ", ""]},
        )
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["tags"]) == 1
    finally:
        db = SessionLocal()
        try:
            row = db.get(Document, doc_id)
            if row:
                db.delete(row)
            tag = db.execute(select(Tag).where(Tag.name == "回归标签A")).scalars().first()
            if tag:
                db.delete(tag)
            db.commit()
        finally:
            db.close()


# ---------------- P1：错误语义（404 / 422 不得被吞成 503）----------------

def test_extension_not_found_returns_404(client: TestClient) -> None:
    missing = str(uuid.uuid4())
    assert client.post(f"/api/insights/mindmap/{missing}").status_code == 404
    assert client.post(f"/api/insights/organize/{missing}").status_code == 404
    assert client.get(f"/api/devhelper/timeline/dates/{missing}").status_code == 404


def test_extension_validation_returns_422(client: TestClient) -> None:
    assert client.post("/api/devhelper/review", json={"code": ""}).status_code == 422
    assert client.post("/api/devhelper/troubleshoot", json={"symptom": ""}).status_code == 422
    assert client.post("/api/devhelper/breakdown", json={"requirement": ""}).status_code == 422


def test_glossary_blank_term_rejected(client: TestClient) -> None:
    resp = client.post("/api/glossary", json={"term": "   ", "definition": "x"})
    assert resp.status_code == 422


# ---------------- P2：会话时间戳 / 路径校验 ----------------

def test_touch_conversation_bumps_updated_at() -> None:
    """新增消息后会话 updated_at 必须前进（否则会话列表排序陈旧）。"""
    db = SessionLocal()
    conv = Conversation(title="回归-时间戳", mode="detail")
    db.add(conv)
    db.commit()
    try:
        before = conv.updated_at
        time.sleep(0.01)
        chat_service._touch_conversation(conv)
        db.commit()
        db.refresh(conv)
        assert conv.updated_at > before
    finally:
        db.delete(conv)
        db.commit()
        db.close()


def test_abs_path_rejects_outside_data_dir() -> None:
    with pytest.raises(ValueError):
        files.abs_path("../evil.txt")
    with pytest.raises(ValueError):
        files.abs_path("../../evil.txt")
    # 前缀相同但并非子目录（此前 startswith 会误判为合法）
    with pytest.raises(ValueError):
        files.abs_path("../data_evil/evil.txt")
    # 合法相对路径不受影响
    assert files.abs_path("documents/ok.md").name == "ok.md"
