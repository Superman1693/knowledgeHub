"""备份与恢复测试（含孤儿文件清理）。

注意：本测试使用真实数据库与数据目录（与其他 API 测试一致），
测试结束会清理自己创建的数据。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _clear_all(client: TestClient) -> None:
    for doc in client.get("/api/documents").json()["items"]:
        client.delete(f"/api/documents/{doc['id']}")
    for conv in client.get("/api/conversations").json():
        client.delete(f"/api/conversations/{conv['id']}")
    for tag in client.get("/api/tags").json():
        client.delete(f"/api/tags/{tag['id']}")
    for cat in client.get("/api/categories").json():
        client.delete(f"/api/categories/{cat['id']}")


def _clear_files() -> None:
    if settings.documents_path.exists():
        for f in settings.documents_path.rglob("*"):
            if f.is_file():
                f.unlink()


def _doc_files() -> list:
    if not settings.documents_path.exists():
        return []
    return [f for f in settings.documents_path.glob("*") if f.is_file()]


def test_backup_restore_roundtrip_and_orphan_cleanup(client: TestClient) -> None:
    # 该测试会清空并恢复整个数据库。为避免破坏已有资料，
    # 仅在库为空时运行；库中已有数据时直接跳过。
    if client.get("/api/documents").json()["total"] > 0 or client.get("/api/conversations").json():
        pytest.skip("检测到已有数据，跳过会清空数据库的备份/恢复往返测试")

    _clear_files()

    # 1) 上传一份文档（会落盘一个文件）
    resp = client.post(
        "/api/documents",
        files=[("files", ("keep.md", b"# Keep\n\nthis one is in the backup", "text/markdown"))],
    )
    assert resp.status_code == 201
    assert len(_doc_files()) == 1

    # 2) 备份
    backup = client.post("/api/backup").json()
    assert backup["size"] > 0

    # 3) 再上传一份，制造"备份之后新增、不在备份内"的文件
    client.post(
        "/api/documents",
        files=[("files", ("orphan.md", b"# Orphan\n\nnot in backup", "text/markdown"))],
    )
    assert len(_doc_files()) == 2

    # 4) 恢复：数据库回滚到备份状态，磁盘文件也应回到备份状态
    restored = client.post("/api/restore", json={"name": backup["name"], "confirm": True}).json()
    assert restored["restored"] is True

    # 数据一致
    assert client.get("/api/documents").json()["total"] == 1
    # 孤儿文件已被清理（修复点：之前只清数据库不清磁盘）
    assert len(_doc_files()) == 1, "恢复后不应残留孤儿文件"

    # 5) 未确认时不得执行恢复
    bad = client.post("/api/restore", json={"name": backup["name"], "confirm": False})
    assert bad.status_code == 422

    _clear_all(client)
    _clear_files()
