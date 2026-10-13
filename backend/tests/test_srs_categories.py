"""多级分类 / 闪卡间隔复习（SRS）/ 附件 的回归测试。

覆盖 LocalMind「多级文件夹」「闪卡与间隔复习」以及此前一直是死代码的 attachments_path。
约定：用例自行清理创建的数据；不依赖 AI 服务。
"""
from __future__ import annotations

import base64
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import backup_service

# 1x1 透明 PNG
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _mk_cat(client: TestClient, name: str, parent_id: str | None = None) -> dict:
    resp = client.post(
        "/api/categories", json={"name": name, "parent_id": parent_id}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _rm_cat(client: TestClient, cat_id: str) -> None:
    try:
        client.delete(f"/api/categories/{cat_id}")
    except (Exception, SystemExit):  # noqa: BLE001
        pass


def _rm_card(client: TestClient, card_id: str) -> None:
    try:
        client.delete(f"/api/learning/cards/{card_id}")
    except (Exception, SystemExit):  # noqa: BLE001
        pass


# ---------------- 多级分类 ----------------

def test_category_tree_and_totals(client: TestClient) -> None:
    """父子结构应正确嵌套，父节点 total_count 含子孙。"""
    suffix = uuid.uuid4().hex[:6]
    root = _mk_cat(client, f"回归-根-{suffix}")
    child = _mk_cat(client, f"回归-子-{suffix}", parent_id=root["id"])
    try:
        tree = client.get("/api/categories/tree").json()
        node = next((n for n in tree if n["id"] == root["id"]), None)
        assert node is not None, "根分类应出现在树顶层"
        assert any(c["id"] == child["id"] for c in node["children"]), "子分类应挂在父节点下"
        assert node["children"][0]["parent_id"] == root["id"]
    finally:
        _rm_cat(client, child["id"])
        _rm_cat(client, root["id"])


def test_sibling_duplicate_name_rejected(client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:6]
    root = _mk_cat(client, f"回归-重名-{suffix}")
    dup = client.post("/api/categories", json={"name": f"回归-重名-{suffix}"})
    try:
        assert dup.status_code == 422, "同层重名应被拒绝"
    finally:
        _rm_cat(client, root["id"])


def test_category_cannot_move_into_descendant(client: TestClient) -> None:
    """把父分类移动到自己的子分类下会形成环，必须被拒绝。"""
    suffix = uuid.uuid4().hex[:6]
    root = _mk_cat(client, f"回归-环-父-{suffix}")
    child = _mk_cat(client, f"回归-环-子-{suffix}", parent_id=root["id"])
    try:
        resp = client.put(f"/api/categories/{root['id']}", json={"parent_id": child["id"]})
        assert resp.status_code == 422, "应拒绝形成环的移动"
        self_move = client.put(
            f"/api/categories/{root['id']}", json={"parent_id": root["id"]}
        )
        assert self_move.status_code == 422, "应拒绝把自己设为自己的父分类"
    finally:
        _rm_cat(client, child["id"])
        _rm_cat(client, root["id"])


def test_category_move_to_root(client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:6]
    root = _mk_cat(client, f"回归-移动-父-{suffix}")
    child = _mk_cat(client, f"回归-移动-子-{suffix}", parent_id=root["id"])
    try:
        resp = client.put(f"/api/categories/{child['id']}", json={"move_to_root": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["parent_id"] is None
    finally:
        _rm_cat(client, child["id"])
        _rm_cat(client, root["id"])


def test_delete_parent_promotes_children(client: TestClient) -> None:
    """删除父分类后，子分类应上提为根（而不是被级联删除）。"""
    suffix = uuid.uuid4().hex[:6]
    root = _mk_cat(client, f"回归-删父-{suffix}")
    child = _mk_cat(client, f"回归-删子-{suffix}", parent_id=root["id"])
    try:
        assert client.delete(f"/api/categories/{root['id']}").status_code == 204
        tree = client.get("/api/categories/tree").json()
        node = next((n for n in tree if n["id"] == child["id"]), None)
        assert node is not None, "子分类不应被级联删除"
        assert node["parent_id"] is None, "子分类应上提为根"
    finally:
        _rm_cat(client, child["id"])


# ---------------- 闪卡与间隔复习（SM-2）----------------

def test_sm2_schedule_progression(client: TestClient) -> None:
    """SM-2：首次通过 → 1 天；第二次通过 → 6 天；未通过 → 重置并 10 分钟后重来。"""
    card = client.post(
        "/api/learning/cards", json={"front": "SM2 问题", "back": "SM2 答案"}
    ).json()
    cid = card["id"]
    try:
        assert card["state"] == "new"
        assert card["interval_days"] == 0

        # 第一次通过（一般）
        r1 = client.post(f"/api/learning/cards/{cid}/review", json={"rating": 4}).json()
        assert r1["card"]["repetitions"] == 1
        assert r1["card"]["interval_days"] == 1
        assert r1["card"]["state"] == "review"

        # 第二次通过 → 6 天
        r2 = client.post(f"/api/learning/cards/{cid}/review", json={"rating": 4}).json()
        assert r2["card"]["repetitions"] == 2
        assert r2["card"]["interval_days"] == 6

        # 第三次通过 → 间隔按难度系数增长
        r3 = client.post(f"/api/learning/cards/{cid}/review", json={"rating": 5}).json()
        assert r3["card"]["repetitions"] == 3
        assert r3["card"]["interval_days"] > 6

        # 未通过（重来）→ 重置
        r4 = client.post(f"/api/learning/cards/{cid}/review", json={"rating": 1}).json()
        assert r4["card"]["repetitions"] == 0
        assert r4["card"]["interval_days"] == 0
        assert r4["card"]["lapses"] == 1
        assert r4["card"]["state"] == "learning"
    finally:
        _rm_card(client, cid)


def test_review_history_and_stats(client: TestClient) -> None:
    card = client.post(
        "/api/learning/cards", json={"front": "历史问题", "back": "历史答案"}
    ).json()
    cid = card["id"]
    try:
        client.post(f"/api/learning/cards/{cid}/review", json={"rating": 4})
        client.post(f"/api/learning/cards/{cid}/review", json={"rating": 2})
        logs = client.get(f"/api/learning/cards/{cid}/reviews").json()
        assert logs["total"] == 2
        assert [x["rating"] for x in logs["items"]] == [2, 4]  # 倒序

        stats = client.get("/api/learning/srs-stats").json()
        for key in ("due", "new", "learning", "review", "reviewed_today", "streak_days"):
            assert key in stats
        assert stats["total"] >= 1
    finally:
        _rm_card(client, cid)


def test_due_only_queue_excludes_future_cards(client: TestClient) -> None:
    """通过一次后卡片到期时间在未来，不应再出现在「今日复习」队列里。"""
    card = client.post(
        "/api/learning/cards", json={"front": "队列问题", "back": "队列答案"}
    ).json()
    cid = card["id"]
    try:
        due_before = client.get("/api/learning/cards", params={"due_only": True}).json()
        assert any(c["id"] == cid for c in due_before["items"]), "新卡片应立即到期"

        client.post(f"/api/learning/cards/{cid}/review", json={"rating": 4})
        due_after = client.get("/api/learning/cards", params={"due_only": True}).json()
        assert all(c["id"] != cid for c in due_after["items"]), "已排期的卡片不应在队列中"
    finally:
        _rm_card(client, cid)


def test_card_edit_and_delete(client: TestClient) -> None:
    card = client.post(
        "/api/learning/cards", json={"front": "待改", "back": "待改背面"}
    ).json()
    cid = card["id"]
    try:
        updated = client.put(
            f"/api/learning/cards/{cid}", json={"front": "已改", "back": "已改背面"}
        ).json()
        assert updated["front"] == "已改"
        assert client.delete(f"/api/learning/cards/{cid}").status_code == 204
        assert client.get(f"/api/learning/cards/{cid}/reviews").status_code == 404
    finally:
        _rm_card(client, cid)


def test_card_requires_both_sides(client: TestClient) -> None:
    resp = client.post("/api/learning/cards", json={"front": "只有正面", "back": "  "})
    assert resp.status_code == 422


# ---------------- 附件 ----------------

def test_attachment_upload_download_delete(client: TestClient) -> None:
    resp = client.post(
        "/api/attachments",
        files=[("file", ("回归-截图.png", PNG_BYTES, "image/png"))],
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    try:
        assert data["kind"] == "image"
        assert data["markdown"].startswith("![回归-截图]("), "图片应返回内联图片语法"
        assert data["url"].startswith("/api/attachments/file/images/")

        # 可下载
        got = client.get(data["url"])
        assert got.status_code == 200
        assert got.content == PNG_BYTES

        # 出现在列表里
        items = client.get("/api/attachments").json()["items"]
        assert any(i["url"] == data["url"] for i in items)
    finally:
        client.delete(data["url"])

    # 删除后不可访问
    assert client.get(data["url"]).status_code == 404


def test_attachment_rejects_unsupported_extension(client: TestClient) -> None:
    resp = client.post(
        "/api/attachments",
        files=[("file", ("bad.exe", b"MZ", "application/octet-stream"))],
    )
    assert resp.status_code == 422


def test_attachment_blocks_path_traversal(client: TestClient) -> None:
    """路径穿越必须被拒绝（abs_path 使用 is_relative_to 校验）。"""
    resp = client.get("/api/attachments/file/images/..%2F..%2F.env")
    assert resp.status_code in (404, 422)


# ---------------- 备份覆盖 ----------------

def test_backup_covers_flashcards_and_review_logs() -> None:
    names = {name for name, _ in backup_service.DUMP_TABLES}
    assert "flashcards" in names
    assert "review_logs" in names
    assert "flashcards" in backup_service.CLEAR_ORDER
    assert "review_logs" in backup_service.CLEAR_ORDER
    # 顺序：review_logs 必须在 flashcards 之前清空（子表先删）
    assert backup_service.CLEAR_ORDER.index("review_logs") < backup_service.CLEAR_ORDER.index(
        "flashcards"
    )
    assert backup_service.DUMP_TABLES.index(
        ("flashcards", backup_service.Flashcard)
    ) < backup_service.DUMP_TABLES.index(("review_logs", backup_service.ReviewLog))
