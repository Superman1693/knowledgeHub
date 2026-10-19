"""2026-10-13 第八轮：速记捕获与相关笔记。

对应「输入漏斗」缺口的第一批修复：
- 速记：`POST /api/workspace/capture` 把一句话追加到今日笔记；
- 相关笔记：`GET /api/insights/related/{id}` 暴露到文档详情页（后端原本就有）。

约定与其它回归测试一致：真实数据库 + 真实 data 目录，用例自建自清。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.services import workspace_service


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


# ---------------- 速记条目插入位置 ----------------

def test_capture_line_inserted_into_daily_section() -> None:
    """速记必须落在「## 今日记录」小节内，不能跑到文末区。

    每日笔记模板里「今日记录」下面还有「待办」「学到的东西」两节，
    若无脑追加到文末，速记会堆在「学到的东西」后面，越记越乱。
    """
    body = (
        "# 2026-10-13\n\n## 今日记录\n\n\n## 待办\n\n- [ ] 买菜\n\n## 学到的东西\n\n"
    )
    out = workspace_service._append_to_daily(body, "- 09:00 第一条")
    lines = out.splitlines()

    i_rec = lines.index("## 今日记录")
    i_entry = lines.index("- 09:00 第一条")
    i_todo = lines.index("## 待办")
    assert i_rec < i_entry < i_todo, "速记未落在「今日记录」与「待办」之间"

    # 连续追加不应产生越来越长的空行堆积
    out2 = workspace_service._append_to_daily(out, "- 09:01 第二条")
    assert "- 09:00 第一条" in out2 and "- 09:01 第二条" in out2
    assert out2.splitlines().count("") <= out.splitlines().count("") + 1


def test_capture_falls_back_when_no_section() -> None:
    """没有「今日记录」小节时追加到文末，不能丢内容。"""
    out = workspace_service._append_to_daily("随手写的一段正文", "- 09:00 兜底")
    assert out.endswith("- 09:00 兜底\n")
    assert "随手写的一段正文" in out

    # 空正文也要能用
    assert workspace_service._append_to_daily("", "- 09:00 空") == "- 09:00 空\n"


# ---------------- 速记接口 ----------------

def test_quick_capture_api(client: TestClient) -> None:
    """端到端：POST /workspace/capture 应把内容写进今日笔记并可检索到。"""
    db = SessionLocal()
    existing = workspace_service.find_daily_note(db)
    had_daily = existing is not None
    before = (existing.content_text or "") if existing else ""
    db.close()

    marker = f"速记回归{uuid.uuid4().hex[:8]}"
    try:
        res = client.post("/api/workspace/capture", json={"text": marker})
        assert res.status_code == 200, res.text
        payload = res.json()
        assert payload["document_id"]
        assert payload["daily_created"] == (not had_daily)

        # 多行输入应压成单行条目（一行一条便于以后按行筛选）
        res2 = client.post(
            "/api/workspace/capture", json={"text": f"{marker}-多行\n第二行内容"}
        )
        assert res2.status_code == 200

        detail = client.get(f"/api/documents/{payload['document_id']}").json()
        text = detail["content_text"]
        assert marker in text
        assert f"{marker}-多行 第二行内容" in text, "多行未压成单行"
        # 条目带时间戳
        assert any(
            ln.startswith("- ") and ":" in ln and marker in ln
            for ln in text.splitlines()
        )

        # 空内容必须被拒（422），不能静默写入一个空条目
        assert client.post("/api/workspace/capture", json={"text": "   "}).status_code == 422
        assert client.post("/api/workspace/capture", json={}).status_code == 422
    finally:
        db = SessionLocal()
        doc = workspace_service.find_daily_note(db)
        if doc is not None:
            if had_daily:
                doc.content_text = before
                db.commit()
            else:
                from app.services import document_service

                document_service.purge_document(db, doc.id)
        db.close()


def test_capture_rejects_overlong_text(client: TestClient) -> None:
    """超长内容应引导去新建笔记，而不是塞进今日笔记的一天条目里。"""
    res = client.post("/api/workspace/capture", json={"text": "x" * 2001})
    assert res.status_code == 422
    assert "新建笔记" in res.text


# ---------------- 相关笔记 ----------------

def test_related_documents_are_ranked_and_exclude_self(
    client: TestClient, seeded_library: None
) -> None:
    """相关笔记：不得包含自己，相似度按降序排列。"""
    docs = client.get("/api/documents", params={"page_size": 10}).json()["items"]
    if not docs:
        pytest.skip("库中无文档，跳过相关笔记校验")

    target = docs[0]
    res = client.get(f"/api/insights/related/{target['id']}", params={"limit": 5})
    assert res.status_code == 200, res.text
    items = res.json()["items"]

    ids = [i["document_id"] for i in items]
    assert target["id"] not in ids, "相关笔记不应包含自己"
    sims = [i["similarity"] for i in items]
    assert sims == sorted(sims, reverse=True), "未按相似度降序"


def test_related_documents_404_for_unknown_id(client: TestClient) -> None:
    """不存在的文档应返回 404，而不是 500 或空列表。"""
    res = client.get(f"/api/insights/related/{uuid.uuid4()}")
    assert res.status_code == 404
