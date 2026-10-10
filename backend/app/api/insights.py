"""知识加工路由：冗余检测、跨文档关联、思维导图、整理归档。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import AIUnavailableError
from app.services import insight_service

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/duplicates")
def duplicates(
    threshold: float = Query(0.10, ge=0.01, le=1.0, description="余弦距离阈值，越小越相似"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """内容高度相似的片段对（纯向量计算，不消耗对话模型）。"""
    items = insight_service.find_duplicates(db, threshold, limit)
    return {
        "total": len(items),
        "threshold": threshold,
        "items": items,
        "note": "相似片段仅供参考，系统不会自动合并或删除任何内容",
    }


@router.get("/related/{document_id}")
def related(
    document_id: uuid.UUID,
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    """与指定文档内容最相近的其它文档（用于发现跨文档的知识关联）。"""
    items = insight_service.related_documents(db, document_id, limit)
    return {"total": len(items), "items": items}


@router.post("/mindmap/{document_id}")
async def mindmap(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """用 AI 把文档整理成 Mermaid 思维导图（节点取自原文）。"""
    try:
        return await insight_service.build_mindmap(db, document_id)
    except AIUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"生成思维导图失败：{exc}") from exc


@router.post("/organize/{document_id}")
async def organize(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """为文档生成归档建议（标题 / 分类 / 标签 / 摘要），不会自动应用。"""
    try:
        return await insight_service.organize_document(db, document_id)
    except AIUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"生成归档建议失败：{exc}") from exc
