"""知识加工路由：冗余检测、跨文档关联、思维导图、整理归档。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import AIUnavailableError, AppError, ValidationError
from app.services import assist_service, insight_service, summary_service

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
    except AppError:
        raise  # 业务异常（404 / 422 / 503 等）原样透出，不要统一成 503
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"生成思维导图失败：{exc}") from exc


@router.post("/organize/{document_id}")
async def organize(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """为文档生成归档建议（标题 / 分类 / 标签 / 摘要），不会自动应用。"""
    try:
        return await insight_service.organize_document(db, document_id)
    except AppError:
        raise  # 业务异常（404 / 422 / 503 等）原样透出，不要统一成 503
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"生成归档建议失败：{exc}") from exc


@router.post("/assist")
async def assist(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    """笔记页内 AI 助手：对选中文字做 解释 / 总结 / 生成卡片 / 找关联。

    - `explain` / `summarize`：调用对话模型，只针对选中文字，不引入无关知识；
    - `cards`：生成闪卡并落库，返回卡片详情；
    - `related`：**不调用对话模型**，直接用选中文字做混合检索。
    """
    did = payload.get("document_id")
    try:
        count = int(payload.get("count") or 5)
    except (ValueError, TypeError) as exc:
        raise ValidationError("count 必须是整数") from exc
    doc_uuid: uuid.UUID | None = None
    if did:
        try:
            doc_uuid = uuid.UUID(str(did))
        except (ValueError, TypeError) as exc:
            raise ValidationError(f"document_id 不是合法的 UUID：{did}") from exc
    try:
        return await assist_service.assist(
            db,
            text=str(payload.get("text") or ""),
            action=str(payload.get("action") or "explain"),
            document_id=doc_uuid,
            count=count,
        )
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"AI 助手失败：{exc}") from exc


@router.post("/batch-summary")
async def batch_summary(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    """对多篇文档批量生成 AI 摘要。"""
    ids_raw = payload.get("document_ids") or []
    try:
        ids = [uuid.UUID(str(x)) for x in ids_raw]
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"document_ids 格式错误：{exc}") from exc
    try:
        return await summary_service.batch_summarize(db, ids)
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"批量摘要失败：{exc}") from exc
