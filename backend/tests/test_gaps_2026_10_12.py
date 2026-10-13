"""2026-10-12 第二批：缺口补齐的回归测试。

覆盖本轮新增能力：
- 编辑乐观锁（409 冲突）
- 文档批量操作（逐条结果 + 追加式打标签）
- 标签合并
- 检索日期区间
- 图片 OCR 导入
- 设置项（重排序开关）与数据目录切换保护

约定与其它回归测试一致：使用真实数据库与数据目录，每个用例自建自清，不依赖 AI 服务。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import ValidationError
from app.main import app
from app.models import Document, Tag
from app.services import (
    backup_service,
    document_service,
    parsers,
    settings_service,
    tag_service,
    workspace_service,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _note(client: TestClient, title: str, text: str) -> dict:
    resp = client.post("/api/documents/notes", json={"title": title, "content_text": text})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _purge(client: TestClient, doc_id: str) -> None:
    try:
        client.delete(f"/api/documents/{doc_id}/purge")
    except (Exception, SystemExit):  # noqa: BLE001
        pass


# ---------------- 编辑乐观锁（冲突检测） ----------------

def test_update_survives_embedding_outage(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """嵌入不可用时，保存正文仍必须成功（降级为 partial，不 503）。

    2026-10-13 实测：外部嵌入配额耗尽返回 403 时，`update_document` 让
    `EmbeddingUnavailableError` 直接冒泡 → 任何编辑都 503，
    而内容其实已经写进库和磁盘了。这与 `EmbeddingUnavailableError`
    自己的语义（"片段已写入、关键词检索可用"）矛盾，也已修复。
    """
    from app.core.exceptions import EmbeddingUnavailableError
    from app.services import document_service as ds

    async def _boom(*_args, **_kwargs):
        raise EmbeddingUnavailableError("测试：模拟嵌入不可用")

    # document_service 是 `from app.rag.indexer import build_index`，
    # 所以要打在 document_service 的模块级名字上才生效。
    monkeypatch.setattr(ds, "build_index", _boom)

    doc = _note(client, "回归-嵌入降级", "第一版内容")
    doc_id = doc["id"]
    try:
        resp = client.put(
            f"/api/documents/{doc_id}", json={"content_text": "配额耗尽时的新内容"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["content_text"] == "配额耗尽时的新内容"

        # 内容已落库
        detail = client.get(f"/api/documents/{doc_id}").json()
        assert detail["content_text"] == "配额耗尽时的新内容"
        # 内容已写回磁盘（接口不暴露 file_path，按库里路径解析）
        db = SessionLocal()
        try:
            row = db.get(Document, uuid.UUID(doc_id))
            assert row is not None
            disk = settings.data_path / row.file_path
        finally:
            db.close()
        assert "配额耗尽时的新内容" in disk.read_text(encoding="utf-8")
        # 版本历史仍然生成（保存链路完整）
        assert len(client.get(f"/api/documents/{doc_id}/revisions").json()) == 1
    finally:
        _purge(client, doc_id)

def test_update_conflict_detected(client: TestClient) -> None:
    """正文指纹对不上时必须 409，而不是静默覆盖别人的修改。

    注意：正文变更会触发重建索引，需要嵌入服务。本机嵌入配额耗尽时接口按设计返回
    503（片段已保留、只是没向量），因此「基线正确」一例只断言**不出现 409**，
    再另行 GET 校验内容与指纹确实已更新。
    """
    doc = _note(client, "回归-冲突", "第一版内容")
    doc_id = doc["id"]
    try:
        base = client.get(f"/api/documents/{doc_id}").json()
        assert base["content_hash"], "详情接口应返回正文指纹"

        # 1) 基线错误 → 409
        bad = client.put(
            f"/api/documents/{doc_id}",
            json={
                "content_text": "我的新内容",
                "base_content_hash": "0" * 64,
            },
        )
        assert bad.status_code == 409, bad.text
        # 冲突时不得写入
        still = client.get(f"/api/documents/{doc_id}").json()
        assert still["content_text"] == "第一版内容"

        # 2) 基线正确 → 不得 409，且内容与指纹都已更新
        ok = client.put(
            f"/api/documents/{doc_id}",
            json={
                "content_text": "我的新内容",
                "base_content_hash": base["content_hash"],
            },
        )
        assert ok.status_code != 409, ok.text
        after = client.get(f"/api/documents/{doc_id}").json()
        assert after["content_text"] == "我的新内容"
        assert after["content_hash"] != base["content_hash"]

        # 3) 不带基线（强制覆盖）仍可用，保持向后兼容
        forced = client.put(f"/api/documents/{doc_id}", json={"content_text": "强制覆盖"})
        assert forced.status_code != 409, forced.text
        assert client.get(f"/api/documents/{doc_id}").json()["content_text"] == "强制覆盖"
    finally:
        _purge(client, doc_id)


# ---------------- 文档批量操作 ----------------

def test_batch_operations_report_per_item(client: TestClient) -> None:
    """批量操作逐条返回成败：一条失败不应让整批 500。"""
    a = _note(client, "回归-批量A", "A")
    b = _note(client, "回归-批量B", "B")
    a_id, b_id = a["id"], b["id"]
    try:
        res = client.post(
            "/api/documents/batch",
            json={"action": "favorite", "ids": [a_id, b_id], "value": True},
        ).json()
        assert res["ok_count"] == 2
        assert res["failed"] == []
        assert client.get(f"/api/documents/{a_id}").json()["is_favorite"] is True

        # 混入不存在的 id：成功的照常，失败的如实登记
        missing = str(uuid.uuid4())
        res2 = client.post(
            "/api/documents/batch",
            json={"action": "pin", "ids": [a_id, missing], "value": True},
        ).json()
        assert res2["ok_count"] == 1
        assert len(res2["failed"]) == 1
        assert res2["failed"][0]["id"] == missing

        # 非法动作 → 每条都被记为失败（而不是 500）
        res3 = client.post(
            "/api/documents/batch",
            json={"action": "delete", "ids": []},
        )
        assert res3.status_code == 422  # 空 ids 由 schema 拦下
    finally:
        _purge(client, a_id)
        _purge(client, b_id)


def test_batch_tag_appends_instead_of_overwriting(client: TestClient) -> None:
    """批量打标签必须是**追加**：覆盖式会把原有标签不可逆地抹掉。"""
    name_old = f"回归保留{uuid.uuid4().hex[:6]}"
    name_new = f"回归追加{uuid.uuid4().hex[:6]}"
    doc = _note(client, "回归-批量标签", "正文")
    doc_id = doc["id"]
    try:
        client.post(f"/api/tags/document/{doc_id}", json={"names": [name_old]})
        res = client.post(
            "/api/documents/batch",
            json={"action": "tag", "ids": [doc_id], "tags": [name_new]},
        ).json()
        assert res["ok_count"] == 1
        names = {t["name"] for t in client.get(f"/api/documents/{doc_id}").json()["tags"]}
        assert name_old in names, "原有标签不应被批量打标签抹掉"
        assert name_new in names
    finally:
        _purge(client, doc_id)
        db = SessionLocal()
        try:
            for n in (name_old, name_new):
                t = db.execute(select(Tag).where(Tag.name == n)).scalars().first()
                if t:
                    db.delete(t)
            db.commit()
        finally:
            db.close()


# ---------------- 标签合并 ----------------

def test_merge_tags_moves_documents(client: TestClient) -> None:
    """合并标签：文档改挂目标标签，来源标签被删除，且不撞主键。"""
    src_name = f"回归合并源{uuid.uuid4().hex[:6]}"
    dst_name = f"回归合并目标{uuid.uuid4().hex[:6]}"
    d1 = _note(client, "回归-合并1", "x")
    d2 = _note(client, "回归-合并2", "y")
    try:
        # d1 只挂源标签；d2 两个都挂（考验主键冲突处理）
        client.post(f"/api/tags/document/{d1['id']}", json={"names": [src_name]})
        client.post(f"/api/tags/document/{d2['id']}", json={"names": [src_name, dst_name]})

        tags = {t["name"]: t["id"] for t in client.get("/api/tags").json()}
        src_id, dst_id = tags[src_name], tags[dst_name]

        res = client.post(f"/api/tags/{src_id}/merge", json={"target_id": dst_id}).json()
        assert res["target_name"] == dst_name
        assert res["moved"] == 1, "只有 d1 需要新挂目标标签"

        after = {t["name"] for t in client.get("/api/tags").json()}
        assert src_name not in after, "来源标签应被删除"
        assert dst_name in after

        for did in (d1["id"], d2["id"]):
            names = [t["name"] for t in client.get(f"/api/documents/{did}").json()["tags"]]
            assert names.count(dst_name) == 1, "目标标签不应重复挂载"
            assert src_name not in names
    finally:
        _purge(client, d1["id"])
        _purge(client, d2["id"])
        db = SessionLocal()
        try:
            for n in (src_name, dst_name):
                t = db.execute(select(Tag).where(Tag.name == n)).scalars().first()
                if t:
                    db.delete(t)
            db.commit()
        finally:
            db.close()


def test_merge_tag_rejects_self(client: TestClient) -> None:
    """合并到自己应被拒绝（否则会把自己的关联全删掉）。"""
    db = SessionLocal()
    tag = Tag(name=f"回归自合并{uuid.uuid4().hex[:6]}")
    db.add(tag)
    db.commit()
    tag_id = tag.id
    try:
        with pytest.raises(ValidationError):
            tag_service.merge_tags(db, tag_id, tag_id)
    finally:
        row = db.get(Tag, tag_id)
        if row:
            db.delete(row)
        db.commit()
        db.close()


# ---------------- 检索日期区间 ----------------

def test_search_date_range_filters(client: TestClient) -> None:
    """按更新时间筛选区间：未来起点应为 0 命中，过去起点应有命中。"""
    marker = f"ZZDATERANGE{uuid.uuid4().hex[:8]}".upper()
    doc = _note(client, f"回归-日期-{marker}.md", f"{marker} 用于验证日期区间筛选")
    doc_id = doc["id"]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    last_year = (date.today() - timedelta(days=365)).isoformat()
    try:
        none_yet = client.post(
            "/api/search",
            json={"query": marker, "mode": "keyword", "date_from": f"{tomorrow}T00:00:00"},
        ).json()
        assert none_yet["total"] == 0

        found = client.post(
            "/api/search",
            json={"query": marker, "mode": "keyword", "date_from": f"{last_year}T00:00:00"},
        ).json()
        assert found["total"] >= 1

        # 结束时间在过去 → 同样排除
        excluded = client.post(
            "/api/search",
            json={"query": marker, "mode": "keyword", "date_to": f"{last_year}T23:59:59"},
        ).json()
        assert excluded["total"] == 0
    finally:
        _purge(client, doc_id)


# ---------------- 图片 OCR 导入 ----------------

def test_images_are_importable_and_parsed_by_ocr(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """图片应能作为文档导入，并由 OCR 提取文字。

    这里把 OCR 引擎替换成固定返回值：本用例验证的是**分派与解析链路**，
    真实 OCR 模型是否可用取决于运行环境（不可用时不应让测试失败）。
    文件写在 `tmp_path` 而**不是** `data/documents`——否则用例残留会被
    「扫描同步」当成未收录文件，污染知识库。
    """
    assert "png" in parsers.files.ALLOWED_EXTENSIONS
    assert "jpg" in parsers.files.ALLOWED_EXTENSIONS

    from app.services import ocr_service

    monkeypatch.setattr(ocr_service, "ocr_status", lambda: {
        "available": True,
        "hint": "",
        "engine": "test",
        "renderer_installed": True,
    })
    monkeypatch.setattr(
        ocr_service, "ocr_image_bytes", lambda data: "识别出来的文字\n第二行"
    )

    path = tmp_path / "ocr.png"
    # 写一个最小的合法 PNG 头即可（解析器只把字节交给 OCR）
    path.write_bytes(
        bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489")
    )
    doc = parsers.parse(path, "png")
    assert "识别出来的文字" in doc.text


def test_image_parse_reports_missing_ocr(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """OCR 不可用时，图片应给出明确提示而不是静默产出空文档。"""
    from app.services import ocr_service

    monkeypatch.setattr(ocr_service, "ocr_status", lambda: {
        "available": False,
        "hint": "未安装 OCR 引擎",
        "engine": None,
        "renderer_installed": False,
    })
    path = tmp_path / "ocr-off.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(parsers.ParseError):
        parsers.parse(path, "png")


# ---------------- 设置项 ----------------

def test_rerank_is_configurable_via_settings() -> None:
    """重排序开关必须能通过设置接口配置（此前只在 .env 里，界面改不了）。"""
    assert "rerank_enabled" in settings_service.OVERRIDE_KEYS
    assert "rerank_candidates" in settings_service.OVERRIDE_KEYS
    from app.schemas.settings import SettingsOut, SettingsUpdate

    assert "rerank_enabled" in SettingsOut.model_fields
    assert "rerank_enabled" in SettingsUpdate.model_fields


def test_data_dir_change_is_guarded() -> None:
    """切换数据目录：同一目录（写法不同）视为未改；换目录且库中有文档时拒绝。"""
    db = SessionLocal()
    try:
        assert settings_service._normalize_data_dir(db, str(settings.data_path)) is None
        assert settings_service._normalize_data_dir(db, "./data") is None

        has_docs = (
            db.execute(select(Document.id).limit(1)).scalars().first() is not None
        )
        if has_docs:
            with pytest.raises(ValidationError):
                settings_service._normalize_data_dir(db, "./another_data_dir")
    finally:
        db.close()


# ---------------- 保存的检索条件（智能集合） ----------------

def test_saved_search_crud(client: TestClient) -> None:
    name = f"回归集合{uuid.uuid4().hex[:6]}"
    created = client.post(
        "/api/saved-searches",
        json={"name": name, "params": {"query": "x", "mode": "keyword", "tags": ["vue"]}},
    )
    assert created.status_code == 201, created.text
    sid: str | None = created.json()["id"]
    try:
        # 重名 → 422（重名会让列表里出现两个看不出区别的入口）
        assert (
            client.post("/api/saved-searches", json={"name": name, "params": {}}).status_code
            == 422
        )
        # 空名 → 422
        assert (
            client.post("/api/saved-searches", json={"name": "", "params": {}}).status_code
            == 422
        )

        listed = {s["name"]: s for s in client.get("/api/saved-searches").json()}
        assert name in listed
        # params 原样保存（JSONB 往返不丢字段）
        assert listed[name]["params"]["query"] == "x"
        assert listed[name]["params"]["tags"] == ["vue"]

        renamed = client.put(f"/api/saved-searches/{sid}", json={"name": f"{name}改"})
        assert renamed.status_code == 200
        assert renamed.json()["name"] == f"{name}改"

        assert client.delete(f"/api/saved-searches/{sid}").status_code == 204
        assert sid not in {s["id"] for s in client.get("/api/saved-searches").json()}
        sid = None
    finally:
        if sid:
            client.delete(f"/api/saved-searches/{sid}")


def test_saved_search_is_backed_up() -> None:
    """新表必须进备份清单，否则换机后「常用检索」全丢。"""
    names = {name for name, _ in backup_service.DUMP_TABLES}
    assert "saved_searches" in names
    assert "saved_searches" in backup_service.CLEAR_ORDER


# ---------------- 启动扫描（只读） ----------------

def test_startup_scan_is_read_only() -> None:
    """启动扫描只扫描、绝不修改知识库。"""
    db = SessionLocal()
    try:
        before = db.execute(select(func.count()).select_from(Document)).scalar_one()
        result = workspace_service.startup_scan(db)
        after = db.execute(select(func.count()).select_from(Document)).scalar_one()
        assert before == after, "启动扫描不得改变文档数"
        assert result is not None
        assert {"changed_count", "missing_count", "orphan_count", "scanned_at"} <= set(result)
    finally:
        db.close()


def test_workbench_exposes_startup_scan(client: TestClient) -> None:
    res = client.get("/api/workspace/workbench").json()
    assert "startup_scan" in res


# ---------------- 回收站保留期 ----------------

def test_trash_retention_disabled_by_default(client: TestClient) -> None:
    """保留期为 0 → 什么都不删（默认「永不自动清理」）。"""
    assert settings.trash_retention_days == 0
    res = client.post("/api/documents/trash/purge-expired").json()
    assert res["removed"] == 0
    assert "永不自动清理" in res["note"]


def test_trash_retention_purges_only_expired() -> None:
    """超过保留期的彻底删除，未超过的保留。"""
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex[:8]
    fresh = Document(
        title=f"回归-保留期内-{suffix}.md",
        original_filename=f"fresh-{suffix}.md",
        file_path=f"documents/fresh-{suffix}.md",
        file_type="md",
        file_size=1,
        deleted_at=now - timedelta(days=1),
    )
    old = Document(
        title=f"回归-超期-{suffix}.md",
        original_filename=f"old-{suffix}.md",
        file_path=f"documents/old-{suffix}.md",
        file_type="md",
        file_size=1,
        deleted_at=now - timedelta(days=30),
    )
    db.add_all([fresh, old])
    db.commit()
    fresh_id, old_id = fresh.id, old.id
    try:
        removed = document_service.purge_expired_trash(db, days=7)
        assert removed >= 1
        assert db.get(Document, fresh_id) is not None, "保留期内的不应被清理"
        assert db.get(Document, old_id) is None, "超过保留期的应被彻底删除"
    finally:
        for doc_id in (fresh_id, old_id):
            row = db.get(Document, doc_id)
            if row:
                db.delete(row)
        db.commit()
        db.close()
