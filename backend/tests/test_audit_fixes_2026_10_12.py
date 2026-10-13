"""2026-10-12 深度排查：备份完整性、AI 上下文过滤、错误语义、计数口径。

约定与其它回归测试一致：使用真实数据库与数据目录，**每个用例自建自清**，
不依赖 AI 服务，不破坏库中已有资料。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.exceptions import ValidationError
from app.main import app
from app.models import Chunk, Document, Tag
from app.services import backup_service, learning_service, tag_service


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


# ---------------- 备份 / 恢复完整性 ----------------

def test_backup_covers_note_revisions() -> None:
    """版本历史表必须进入备份与清空清单（此前缺失 → 恢复后版本历史全丢）。"""
    names = {name for name, _ in backup_service.DUMP_TABLES}
    assert "note_revisions" in names, "备份转储清单缺少 note_revisions"
    assert "note_revisions" in backup_service.CLEAR_ORDER, "清空清单缺少 note_revisions"

    db = SessionLocal()
    try:
        data = backup_service.dump_all(db)
    finally:
        db.close()
    assert "note_revisions" in data


def test_clear_order_deletes_children_before_parents() -> None:
    """note_revisions 必须在 documents 之前清空，否则外键违约。"""
    order = backup_service.CLEAR_ORDER
    assert order.index("note_revisions") < order.index("documents")
    assert order.index("chunks") < order.index("documents")
    assert order.index("review_logs") < order.index("flashcards")


def test_validate_dump_rejects_incomplete_backup() -> None:
    """结构损坏/为空的备份必须在清空数据库**之前**被拒绝。"""
    with pytest.raises(ValidationError):
        backup_service._validate_dump({})            # 空对象：会清空全库却插 0 行
    with pytest.raises(ValidationError):
        backup_service._validate_dump([])            # 不是对象
    with pytest.raises(ValidationError):
        backup_service._validate_dump({"documents": "not-a-list"})

    # 合法（含全部必需键）的 dump 应当通过；note_revisions 允许缺失（兼容旧备份）
    ok = {name: [] for name, _ in backup_service.DUMP_TABLES}
    ok.pop("note_revisions")
    ok["document_tags"] = []
    assert backup_service._validate_dump(ok) is ok


def test_backup_covers_every_registered_table() -> None:
    """**自动**校验：任何新注册的模型表都必须进备份清单。

    这条断言是防止「再次漏表」的根本手段——此前 note_revisions / glossary_terms /
    quiz_records 都是因为表清单硬编码、新增表时忘记同步而丢数据。
    """
    from app.models import Base

    dumped = {name for name, _ in backup_service.DUMP_TABLES} | {"document_tags"}
    expected = {t.name for t in Base.metadata.sorted_tables}
    missing = sorted(expected - dumped)
    assert not missing, f"以下表未纳入备份/恢复清单：{missing}"


def test_dump_is_referentially_complete() -> None:
    """转储必须自洽：每行带全列，且外键指向的 id 都能在转储内找到。"""
    from sqlalchemy import inspect as sa_inspect

    db = SessionLocal()
    try:
        data = backup_service.dump_all(db)
    finally:
        db.close()

    # 1) 每张表的每行都包含该模型的全部列
    for name, model in backup_service.DUMP_TABLES:
        cols = {c.key for c in sa_inspect(model).mapper.column_attrs}
        for row in data[name]:
            assert set(row.keys()) == cols, f"{name} 的行缺少列：{cols - set(row)}"

    # 2) 关键外键在转储内可解析（恢复时不会因悬空引用失败）
    #    注意 app_settings 的主键列名是 key，不能假定都叫 id
    ids: dict[str, set] = {}
    for name, model in backup_service.DUMP_TABLES:
        pk = [c.key for c in sa_inspect(model).mapper.primary_key]
        if len(pk) == 1:
            ids[name] = {r[pk[0]] for r in data[name]}
    doc_ids = ids.get("documents", set())
    chunk_ids = ids.get("chunks", set())
    for row in data["chunks"]:
        assert row["document_id"] in doc_ids, "片段引用了转储中不存在的文档"
        if row["parent_id"]:
            assert row["parent_id"] in chunk_ids, "子块引用了转储中不存在的父块"
    for row in data["note_revisions"]:
        assert row["document_id"] in doc_ids, "版本历史引用了转储中不存在的文档"
    for row in data["note_links"]:
        assert row["source_document_id"] in doc_ids, "链接的来源文档不在转储中"
        if row["target_document_id"]:
            assert row["target_document_id"] in doc_ids, "链接的目标文档不在转储中"


# ---------------- 扩展模块错误语义（404/422 不得被吞成 503）----------------

def test_bad_uuid_returns_422_not_503(client: TestClient) -> None:
    assert client.post(
        "/api/insights/batch-summary", json={"document_ids": ["not-a-uuid"]}
    ).status_code == 422
    assert client.post(
        "/api/devhelper/timeline", json={"document_id": "not-a-uuid"}
    ).status_code == 422
    assert client.post(
        "/api/insights/assist",
        json={"action": "explain", "text": "一段文字", "document_id": "not-a-uuid"},
    ).status_code == 422


def test_learning_invalid_params_return_422(client: TestClient) -> None:
    # 缺少 document_id
    assert client.post("/api/learning/cards/generate", json={}).status_code == 422
    # rating 非整数（此前未捕获 → 500）
    cid = str(uuid.uuid4())
    assert client.post(
        f"/api/learning/cards/{cid}/review", json={"rating": "abc"}
    ).status_code == 422
    # 缺少 rating
    assert client.post(
        f"/api/learning/cards/{cid}/review", json={}
    ).status_code == 422
    # count 非整数
    assert client.post("/api/learning/questions", json={"count": "x"}).status_code == 422


# ---------------- AI 上下文不得包含回收站 / 私密笔记 ----------------

def test_pick_chunks_excludes_private_and_deleted() -> None:
    """出题素材会被整段发给模型，私密与回收站文档必须在 SQL 层排除。"""
    marker = f"ZZAUDIT{ uuid.uuid4().hex[:8] }".upper()
    db = SessionLocal()
    doc = Document(
        title=f"审计-私密-{marker}.md",
        original_filename=f"audit-{marker}.md",
        file_path=f"documents/audit-{marker}.md",
        file_type="md",
        file_size=10,
        content_text=f"{marker} 这段内容用于验证隐私过滤。",
        ai_enabled=False,
    )
    db.add(doc)
    db.commit()
    chunk = Chunk(
        document_id=doc.id,
        chunk_index=0,
        content=f"{marker} 私密片段内容，不应被选中出题。",
        token_count=10,
        embedding=[0.1] * 1024,
    )
    db.add(chunk)
    db.commit()
    chunk_id = chunk.id
    doc_id = doc.id

    try:
        picked = {c.id for c in learning_service._pick_chunks(db, 5, marker)}
        assert chunk_id not in picked, "私密笔记的片段不得作为出题素材"

        # 打开 AI 开关后应当可以被选中
        db.get(Document, doc_id).ai_enabled = True
        db.commit()
        picked = {c.id for c in learning_service._pick_chunks(db, 5, marker)}
        assert chunk_id in picked, "公开笔记的片段应当可以作为出题素材"

        # 移入回收站后再次被排除
        db.get(Document, doc_id).deleted_at = datetime.now(timezone.utc)
        db.commit()
        picked = {c.id for c in learning_service._pick_chunks(db, 5, marker)}
        assert chunk_id not in picked, "回收站文档的片段不得作为出题素材"
    finally:
        row = db.get(Document, doc_id)
        if row:
            db.delete(row)
        db.commit()
        db.close()


# ---------------- 未登记文件收录的上限 ----------------

def test_mass_orphan_registration_is_capped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一次性收录未登记文件必须有上限。

    该接口会把 data/documents 中**所有**未登记文件导入为文档，每篇都触发一次嵌入调用。
    没有上限时，目录里堆了上百个文件就会让请求长时间挂起、超时后留下半成品。
    """
    from app.core.config import settings
    from app.services import workspace_service

    baseline = client.post("/api/workspace/scan", params={"apply": False}).json()
    if baseline["orphan_count"] > 0:
        pytest.skip("环境存在未收录文件残留，跳过（避免收录它们污染知识库）")

    monkeypatch.setattr(workspace_service, "MAX_REGISTER_ORPHANS", 1)
    made: list = []
    for i in range(2):
        p = settings.documents_path / f"回归-上限-{uuid.uuid4().hex[:8]}-{i}.md"
        p.write_text("# 上限验证\n", encoding="utf-8")
        made.append(p)
    try:
        res = client.post("/api/workspace/scan", params={"register_orphans": True})
        assert res.status_code == 422, res.text
        # 被拒绝时不得导入任何文件
        after = client.post("/api/workspace/scan", params={"apply": False}).json()
        assert after["orphan_count"] == 2, "超限被拒绝后不应导入任何文件"
    finally:
        for p in made:
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass


# ---------------- 标签计数口径 ----------------

def test_tag_counts_exclude_trashed_documents() -> None:
    """标签文档数必须排除回收站，否则与文档列表对不上。"""
    name = f"审计标签{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    doc = Document(
        title=f"审计-标签-{name}.md",
        original_filename=f"audit-{name}.md",
        file_path=f"documents/audit-{name}.md",
        file_type="md",
        file_size=1,
    )
    tag = Tag(name=name)
    db.add(doc)
    db.add(tag)
    db.flush()
    doc.tags.append(tag)
    db.commit()
    doc_id, tag_id = doc.id, tag.id

    try:
        counts = {t.name: c for t, c in tag_service.list_tags(db)}
        assert counts.get(name) == 1

        db.get(Document, doc_id).deleted_at = datetime.now(timezone.utc)
        db.commit()
        counts = {t.name: c for t, c in tag_service.list_tags(db)}
        assert counts.get(name) == 0, "回收站文档不应计入标签的文档数"
    finally:
        row = db.get(Document, doc_id)
        if row:
            db.delete(row)
        db.flush()
        tag_row = db.get(Tag, tag_id)
        if tag_row:
            db.delete(tag_row)
        db.commit()
        db.close()
