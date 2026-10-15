"""2026-10-14 第十二轮：PDF 批注。

测试的重点排序与实现的重点一致：

1. **引文是主锚** —— 校验最严（非空、限长），因为它决定坐标丢失后能否找回位置；
2. **备份不能漏表** —— 漏了是**静默**丢数据（项目约定第 1 条，历史漏过三次）；
3. **导出是幂等的** —— 否则用户点三次导出会堆出三篇重复笔记污染检索；
4. 坐标只做「别越界」的检查，越界裁剪而不是报错（拖出页边是常见操作）。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models import PdfAnnotation
from app.services import backup_service, pdf_annotation_service


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _make_pdf_bytes(pages: int = 3) -> bytes:
    """生成一个真实 PDF 供上传用（避免在仓库里塞二进制夹具）。"""
    import pymupdf

    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text(
            (72, 100), f"Page {i + 1}: Proxy replaces defineProperty.", fontsize=12
        )
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture()
def pdf_doc(client: TestClient):
    """上传一份 PDF，测试结束彻底删除。"""
    created: list[str] = []

    def _create() -> dict:
        res = client.post(
            "/api/documents",
            files=[("files", ("批注测试.pdf", _make_pdf_bytes(), "application/pdf"))],
        )
        assert res.status_code in (200, 201), res.text
        payload = res.json()
        items = payload.get("items", payload) if isinstance(payload, dict) else payload
        assert items, f"上传未返回文档：{payload}"
        # 上传接口每一项形如 {document: {...}, duplicate_warning: bool}
        first = items[0]
        doc = first["document"] if isinstance(first, dict) and "document" in first else first
        assert doc.get("id"), f"上传结果缺少 id：{doc}"
        created.append(doc["id"])
        return doc

    yield _create

    for doc_id in created:
        client.delete(f"/api/documents/{doc_id}/purge")


def _rect(x=0.12, y=0.2, w=0.5, h=0.02):
    return {"x": x, "y": y, "w": w, "h": h}


# ---------------------------------------------------------------------------
# 基础增删改查
# ---------------------------------------------------------------------------

def test_create_list_update_delete(client: TestClient, pdf_doc) -> None:
    doc = pdf_doc()
    did = doc["id"]

    res = client.post(
        f"/api/documents/{did}/annotations",
        json={
            "page_no": 2,
            "quote": "Proxy replaces defineProperty",
            "rects": [_rect()],
            "prefix": "Page 2: ",
            "suffix": ".",
            "color": "green",
            "comment": "这是响应式的核心变化",
        },
    )
    assert res.status_code == 201, res.text
    ann = res.json()
    aid = ann["id"]
    assert ann["page_no"] == 2
    assert ann["color"] == "green"
    assert ann["rects"][0]["x"] == pytest.approx(0.12)

    # 列表：total 是全量，items 受 page 过滤
    listed = client.get(f"/api/documents/{did}/annotations").json()
    assert listed["total"] == 1
    assert len(listed["items"]) == 1

    assert client.get(f"/api/documents/{did}/annotations", params={"page": 2}).json()["total"] == 1
    only_other = client.get(f"/api/documents/{did}/annotations", params={"page": 1}).json()
    assert only_other["items"] == []
    assert only_other["total"] == 1, "total 不该被按页过滤影响"

    # 改颜色与批注
    upd = client.put(f"/api/annotations/{aid}", json={"color": "pink", "comment": "改过了"})
    assert upd.status_code == 200
    assert upd.json()["color"] == "pink"
    assert upd.json()["comment"] == "改过了"

    # 清空批注（传 null 与「不传」是两件事）
    cleared = client.put(f"/api/annotations/{aid}", json={"comment": None})
    assert cleared.status_code == 200
    assert cleared.json()["comment"] is None

    # 删除
    assert client.delete(f"/api/annotations/{aid}").status_code == 204
    assert client.get(f"/api/documents/{did}/annotations").json()["total"] == 0


def test_only_pdf_can_be_annotated(client: TestClient) -> None:
    """笔记没有「页」这一层结构，不该接受批注。"""
    note = client.post(
        "/api/documents/notes",
        json={"title": f"批注-非PDF-{uuid.uuid4().hex[:6]}", "content_text": "正文"},
    ).json()
    try:
        res = client.post(
            f"/api/documents/{note['id']}/annotations",
            json={"page_no": 1, "quote": "随便", "rects": [_rect()]},
        )
        assert res.status_code == 422, res.text
        assert "PDF" in res.text

        # 但**读取**是宽松的：普通笔记页会查一次批注数，不该一直报错
        listed = client.get(f"/api/documents/{note['id']}/annotations")
        assert listed.status_code == 200
        assert listed.json() == {"total": 0, "items": []}
    finally:
        client.delete(f"/api/documents/{note['id']}/purge")


def test_list_unknown_document_is_404(client: TestClient) -> None:
    res = client.get(f"/api/documents/{uuid.uuid4()}/annotations")
    assert res.status_code == 404, "文档不存在应 404，而不是静默返回空列表"


# ---------------------------------------------------------------------------
# 校验：引文最严，坐标从宽
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_quote", ["", "   "])
def test_quote_is_required(client: TestClient, pdf_doc, bad_quote: str) -> None:
    """引文是主锚，丢了就无法重新定位，必须非空。"""
    did = pdf_doc()["id"]
    res = client.post(
        f"/api/documents/{did}/annotations",
        json={"page_no": 1, "quote": bad_quote, "rects": [_rect()]},
    )
    assert res.status_code == 422


def test_quote_length_is_capped(client: TestClient, pdf_doc) -> None:
    """超过上限的一定不是「划中一句话」，而是整页误选。"""
    did = pdf_doc()["id"]
    res = client.post(
        f"/api/documents/{did}/annotations",
        json={"page_no": 1, "quote": "字" * 3000, "rects": [_rect()]},
    )
    assert res.status_code == 422


def test_rects_must_not_be_empty(client: TestClient, pdf_doc) -> None:
    did = pdf_doc()["id"]
    for rects in ([], None):
        res = client.post(
            f"/api/documents/{did}/annotations",
            json={"page_no": 1, "quote": "有引文", "rects": rects},
        )
        assert res.status_code == 422


def test_out_of_page_rects_are_clamped_not_rejected(client: TestClient, pdf_doc) -> None:
    """拖选到页边之外是常见操作，为此拒掉整条批注会让人莫名其妙存不上。"""
    did = pdf_doc()["id"]
    res = client.post(
        f"/api/documents/{did}/annotations",
        json={
            "page_no": 1,
            "quote": "越界裁剪测试",
            "rects": [{"x": 0.9, "y": 0.9, "w": 0.5, "h": 0.5}],
        },
    )
    assert res.status_code == 201, res.text
    r = res.json()["rects"][0]
    assert r["x"] + r["w"] <= 1.000001
    assert r["y"] + r["h"] <= 1.000001
    client.delete(f"/api/annotations/{res.json()['id']}")


def test_zero_area_or_all_outside_rects_rejected(client: TestClient, pdf_doc) -> None:
    did = pdf_doc()["id"]
    # 宽高为 0
    r1 = client.post(
        f"/api/documents/{did}/annotations",
        json={"page_no": 1, "quote": "零面积", "rects": [{"x": 0.1, "y": 0.1, "w": 0, "h": 0.1}]},
    )
    assert r1.status_code == 422
    # 完全在页外
    r2 = client.post(
        f"/api/documents/{did}/annotations",
        json={"page_no": 1, "quote": "页外", "rects": [{"x": 5, "y": 5, "w": 0.1, "h": 0.1}]},
    )
    assert r2.status_code == 422


def test_invalid_color_and_page_rejected(client: TestClient, pdf_doc) -> None:
    did = pdf_doc()["id"]
    bad_color = client.post(
        f"/api/documents/{did}/annotations",
        json={"page_no": 1, "quote": "颜色", "rects": [_rect()], "color": "荧光绿"},
    )
    assert bad_color.status_code == 422
    assert "颜色" in bad_color.text

    for page in (0, -1):
        res = client.post(
            f"/api/documents/{did}/annotations",
            json={"page_no": page, "quote": "页码", "rects": [_rect()]},
        )
        assert res.status_code == 422


def test_duplicate_submit_is_rejected(client: TestClient, pdf_doc) -> None:
    """双击按钮/网络重试会产生完全重合的两条高亮，只会让人困惑。"""
    did = pdf_doc()["id"]
    body = {"page_no": 3, "quote": "重复提交", "rects": [_rect(0.3, 0.4, 0.2, 0.02)]}
    first = client.post(f"/api/documents/{did}/annotations", json=body)
    assert first.status_code == 201
    try:
        again = client.post(f"/api/documents/{did}/annotations", json=body)
        assert again.status_code == 409, again.text
        assert "已经有" in again.text

        # 同一句话但不同位置 → 是两条不同的批注，必须放行
        other_place = client.post(
            f"/api/documents/{did}/annotations",
            json={**body, "rects": [_rect(0.3, 0.6, 0.2, 0.02)]},
        )
        assert other_place.status_code == 201
        client.delete(f"/api/annotations/{other_place.json()['id']}")
    finally:
        client.delete(f"/api/annotations/{first.json()['id']}")


# ---------------------------------------------------------------------------
# 级联删除
# ---------------------------------------------------------------------------

def test_annotations_cascade_when_document_purged(client: TestClient, pdf_doc) -> None:
    """批注只是原文的附着物，PDF 被彻底删除时应该一起走，不留孤儿数据。"""
    did = pdf_doc()["id"]
    created = client.post(
        f"/api/documents/{did}/annotations",
        json={"page_no": 1, "quote": "级联删除验证", "rects": [_rect()]},
    )
    assert created.status_code == 201
    aid = uuid.UUID(created.json()["id"])

    assert client.delete(f"/api/documents/{did}/purge").status_code in (200, 204)

    db = SessionLocal()
    try:
        assert db.get(PdfAnnotation, aid) is None, "PDF 删除后批注成了孤儿数据"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 备份覆盖面（漏表是静默丢数据）
# ---------------------------------------------------------------------------

def test_backup_registration_is_complete() -> None:
    """新表必须同时进 DUMP_TABLES 与 CLEAR_ORDER，且顺序正确。

    这条断言与 `test_backup_covers_every_registered_table` 互补：
    那条保证「表清单不漏」，这条额外保证「清空顺序先子后父」。
    """
    names = [n for n, _ in backup_service.DUMP_TABLES]
    assert "pdf_annotations" in names
    # 转储先父后子：documents 必须在 pdf_annotations 之前
    assert names.index("documents") < names.index("pdf_annotations")
    # 清空先子后父：反过来
    clear = backup_service.CLEAR_ORDER
    assert clear.index("pdf_annotations") < clear.index("documents")


def test_dump_includes_annotation_rows(client: TestClient, pdf_doc) -> None:
    """转储要真的带上批注行，而不只是清单里有名字。"""
    did = pdf_doc()["id"]
    client.post(
        f"/api/documents/{did}/annotations",
        json={"page_no": 1, "quote": "转储验证", "rects": [_rect()], "comment": "备注"},
    )

    db = SessionLocal()
    try:
        data = backup_service.dump_all(db)
    finally:
        db.close()

    rows = [r for r in data["pdf_annotations"] if r["document_id"] == did]
    assert len(rows) == 1
    assert rows[0]["quote"] == "转储验证"
    assert rows[0]["comment"] == "备注"
    # rects 是 JSONB，转储后必须仍是结构化的列表
    assert isinstance(rows[0]["rects"], list) and rows[0]["rects"][0]["x"] == pytest.approx(0.12)


# ---------------------------------------------------------------------------
# 导出为笔记：接入写入 / 关联两个闭环
# ---------------------------------------------------------------------------

def test_export_creates_searchable_linked_note(client: TestClient, pdf_doc) -> None:
    did = pdf_doc()["id"]
    title = client.get(f"/api/documents/{did}").json()["title"]

    client.post(
        f"/api/documents/{did}/annotations",
        json={
            "page_no": 1,
            "quote": "Proxy replaces defineProperty",
            "rects": [_rect()],
            "comment": "代理拦截比属性劫持更彻底",
        },
    )
    client.post(
        f"/api/documents/{did}/annotations",
        json={"page_no": 3, "quote": "第二页之后的另一处", "rects": [_rect(0.2, 0.5, 0.4, 0.02)]},
    )

    res = client.post(f"/api/documents/{did}/annotations/export")
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["created"] is True
    assert out["annotation_count"] == 2

    note_id = out["document_id"]
    try:
        assert out["title"] == f"《{title}》 批注"
        detail = client.get(f"/api/documents/{note_id}").json()
        body = detail["content_text"]

        # 顶部双链回原文 —— 这是「关联闭环」的接入点，让 PDF 的反向链接里出现这篇笔记
        assert f"[[{title}]]" in body
        # 引文放引用块、批注放正文
        assert "> Proxy replaces defineProperty" in body
        assert "代理拦截比属性劫持更彻底" in body
        # 按页分组，页码可读
        assert "## 第 1 页" in body and "## 第 3 页" in body
        assert "共 2 条批注，覆盖 2 页" in body

        # 双链必须真的解析成功，而不只是写在正文里
        links = client.get(f"/api/documents/{note_id}/links").json()
        targets = [o["target_title"] for o in links["outgoing"]]
        assert title in targets, f"双链未解析：{targets}"
        assert all(o["resolved"] for o in links["outgoing"]), "指向 PDF 的双链应已解析"

        # 反向链接：PDF 侧能看到这篇批注笔记（关联闭环真正闭合）
        backlinks = client.get(f"/api/documents/{did}/links").json()
        assert out["title"] in [
            i["source_document_title"] for i in backlinks["backlinks"]
        ], f"PDF 的反向链接里没有批注笔记：{backlinks['backlinks']}"

        # 能参与检索（写入闭环）——导出笔记与普通笔记同构，检索层零改动
        from app.core.database import SessionLocal as _S
        from app.rag.retriever import keyword_search

        db = _S()
        try:
            hits = keyword_search(db, "代理拦截比属性劫持更彻底", 10)
            assert any(h.document_id == uuid.UUID(note_id) for h in hits), (
                "导出的批注笔记没能被关键词检索到"
            )
        finally:
            db.close()
    finally:
        client.delete(f"/api/documents/{note_id}/purge")


def test_export_is_idempotent(client: TestClient, pdf_doc) -> None:
    """重复导出必须原地更新，否则点三次就有三篇高度重复的笔记污染检索结果。"""
    did = pdf_doc()["id"]
    client.post(
        f"/api/documents/{did}/annotations",
        json={"page_no": 1, "quote": "幂等导出", "rects": [_rect()], "comment": "第一条"},
    )

    first = client.post(f"/api/documents/{did}/annotations/export").json()
    assert first["created"] is True
    note_id = first["document_id"]

    try:
        # 再加一条 → 再导出，应该是**更新**同一篇
        client.post(
            f"/api/documents/{did}/annotations",
            json={"page_no": 2, "quote": "后来又加的一条", "rects": [_rect(0.2, 0.7, 0.3, 0.02)]},
        )
        second = client.post(f"/api/documents/{did}/annotations/export").json()
        assert second["created"] is False, "第二次导出应更新已有笔记而不是新建"
        assert second["document_id"] == note_id
        assert second["annotation_count"] == 2

        body = client.get(f"/api/documents/{note_id}").json()["content_text"]
        assert "第一条" in body and "后来又加的一条" in body

        # 同名笔记只有一篇
        listing = client.get("/api/documents", params={"page_size": 100}).json()["items"]
        same_title = [d for d in listing if d["title"] == first["title"]]
        assert len(same_title) == 1, "导出产生了重复笔记"
    finally:
        client.delete(f"/api/documents/{note_id}/purge")


def test_export_without_annotations_is_rejected(client: TestClient, pdf_doc) -> None:
    did = pdf_doc()["id"]
    res = client.post(f"/api/documents/{did}/annotations/export")
    assert res.status_code == 422
    assert "还没有批注" in res.text


def test_comment_only_annotation_still_exports(client: TestClient, pdf_doc) -> None:
    """只划了线没写批注也必须能导出——划线本身就是「这里重要」的标注。"""
    did = pdf_doc()["id"]
    client.post(
        f"/api/documents/{did}/annotations",
        json={"page_no": 1, "quote": "只划线不写批注", "rects": [_rect()]},
    )
    out = client.post(f"/api/documents/{did}/annotations/export").json()
    try:
        body = client.get(f"/api/documents/{out['document_id']}").json()["content_text"]
        assert "> 只划线不写批注" in body
    finally:
        client.delete(f"/api/documents/{out['document_id']}/purge")


# ---------------------------------------------------------------------------
# 生成闪卡（复习闭环）
# ---------------------------------------------------------------------------

def test_annotation_card_text_combines_quote_and_comment(client: TestClient, pdf_doc) -> None:
    """出卡的文本应是「引文 + 批注」：单用引文出不了好题，单用批注又缺上下文。"""
    did = pdf_doc()["id"]
    ann = client.post(
        f"/api/documents/{did}/annotations",
        json={
            "page_no": 1,
            "quote": "Proxy replaces defineProperty",
            "rects": [_rect()],
            "comment": "为什么代理更彻底？",
        },
    ).json()
    try:
        db = SessionLocal()
        try:
            text = pdf_annotation_service.quote_for_card(db, uuid.UUID(ann["id"]))
        finally:
            db.close()
        assert "Proxy replaces defineProperty" in text
        assert "为什么代理更彻底？" in text
    finally:
        client.delete(f"/api/annotations/{ann['id']}")
