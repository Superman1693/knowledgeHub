"""知识图谱路由：返回笔记 + 双向链接 + 标签的关系网络。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import graph_service

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("")
def get_graph(
    focus_id: uuid.UUID | None = Query(None, description="以该文档为中心取二度子图"),
    include_tags: bool = Query(False, description="是否加入「共享标签」的连线"),
    limit: int = Query(400, ge=1, le=400),
    db: Session = Depends(get_db),
) -> dict:
    """知识图谱数据（节点 + 边 + 统计）。"""
    return graph_service.build_graph(
        db, focus_id=focus_id, include_tags=include_tags, limit=limit
    )
