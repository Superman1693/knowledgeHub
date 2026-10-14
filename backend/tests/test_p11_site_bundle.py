"""2026-10-14 第十一轮：静态站导出的数据接口。

渲染与打包在前端（复用 markdown-it + DOMPurify），后端只提供数据。
因此这里验的是**数据契约**与**私密笔记的默认排除**——
后者是安全相关：静态站是拿来分享/发布的，
「不进入 AI 检索」不等于「可以公开」。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _note(client: TestClient, title: str, body: str = "正文", **extra) -> str:
    res = client.post(
        "/api/documents/notes", json={"title": title, "content_text": body, **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_bundle_shape_and_fields(client: TestClient) -> None:
    """前端渲染需要：标题、正文、分类、标签、时间，以及 ai_enabled（本地过滤私密）。"""
    res = client.get("/api/documents/site-bundle")
    assert res.status_code == 200, res.text
    data = res.json()

    for key in ("generated_at", "count", "excluded_private", "include_private", "notes", "note"):
        assert key in data, f"缺少字段 {key}"

    assert data["count"] == len(data["notes"])
    if data["notes"]:
        n = data["notes"][0]
        for key in ("id", "title", "content_text", "category", "tags", "updated_at",
                    "created_at", "ai_enabled"):
            assert key in n, f"note 缺少 {key}"
        assert isinstance(n["tags"], list)


def test_excludes_deleted_notes(client: TestClient) -> None:
    """回收站里的笔记不该出现在导出里。"""
    suffix = uuid.uuid4().hex[:8]
    doc_id = _note(client, f"导出-已删除-{suffix}")
    client.delete(f"/api/documents/{doc_id}")  # 软删除 → 进回收站
    try:
        data = client.get("/api/documents/site-bundle").json()
        assert doc_id not in {n["id"] for n in data["notes"]}, "回收站笔记被导出了"
    finally:
        client.delete(f"/api/documents/{doc_id}/purge")


def test_private_notes_excluded_by_default(client: TestClient) -> None:
    """私密笔记默认不导出，且要能明确告知排除了几篇。

    这是安全默认：静态站是分享/发布用的，
    「不进入 AI 检索」不等于「可以公开」。
    """
    suffix = uuid.uuid4().hex[:8]
    secret = _note(client, f"导出-私密-{suffix}", "机密内容", ai_enabled=False)
    public = _note(client, f"导出-公开-{suffix}", "公开内容")
    try:
        default = client.get("/api/documents/site-bundle").json()
        ids = {n["id"] for n in default["notes"]}
        assert secret not in ids, "私密笔记被默认导出了"
        assert public in ids
        assert default["excluded_private"] >= 1, "未报告排除了几篇私密笔记"
        assert default["include_private"] is False

        # 显式要求时才包含
        allb = client.get(
            "/api/documents/site-bundle", params={"include_private": True}
        ).json()
        ids_all = {n["id"] for n in allb["notes"]}
        assert secret in ids_all
        assert allb["excluded_private"] == 0
        assert allb["include_private"] is True
    finally:
        for i in (secret, public):
            client.delete(f"/api/documents/{i}/purge")


def test_private_flag_present_for_frontend_filtering(client: TestClient) -> None:
    """`include_private=true` 时每条都带 ai_enabled，前端才能本地过滤。"""
    data = client.get(
        "/api/documents/site-bundle", params={"include_private": True}
    ).json()
    assert all("ai_enabled" in n for n in data["notes"])
    assert all(isinstance(n["ai_enabled"], bool) for n in data["notes"])
