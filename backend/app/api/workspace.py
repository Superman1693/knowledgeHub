"""工作区路由：工作台汇总、每日笔记、笔记模板、外部变更扫描。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.schemas.document import DocumentDetail
from app.services import workspace_service

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


@router.get("/workbench")
def workbench(db: Session = Depends(get_db)) -> dict:
    """工作台汇总：最近编辑 / 最近访问 / 待整理 / 收藏 / 各项计数 / 今日笔记。"""
    return workspace_service.workbench(db)


@router.post("/daily", response_model=DocumentDetail)
async def daily_note(db: Session = Depends(get_db)) -> DocumentDetail:
    """获取或创建「今日笔记」（标题为 YYYY-MM-DD）。"""
    doc, _created = await workspace_service.get_or_create_daily_note(db)
    return DocumentDetail.model_validate(doc)


@router.get("/templates")
def list_templates() -> dict:
    """列出笔记模板（data/templates/*.md）。"""
    items = workspace_service.list_templates()
    return {"total": len(items), "items": items}


@router.get("/templates/{name}")
def read_template(name: str) -> dict:
    """读取模板正文。"""
    try:
        content = workspace_service.read_template(name)
    except FileNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return {"name": name, "content": content}


@router.post("/scan")
async def scan(
    apply: bool = Query(False, description="重建被外部改动文件的索引（安全）"),
    register_orphans: bool = Query(
        False, description="把未收录文件导入为文档（会改变知识库，需显式确认）"
    ),
    db: Session = Depends(get_db),
) -> dict:
    """对比磁盘与数据库，找出外部改动 / 丢失 / 未收录的文件。

    - `apply=true`：被改动的文件从磁盘重新解析并重建索引；
    - `register_orphans=true`：未收录的文件被导入为新的知识库文档（需用户确认）。

    两者刻意分开：前者不改变知识库结构，后者会新增文档。
    """
    return await workspace_service.scan_workspace(
        db, apply=apply, register_orphans=register_orphans
    )
