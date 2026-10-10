"""学习辅助路由：模拟面试、评分点评、错题管理、快捷复习。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import AIUnavailableError
from app.services import learning_service

router = APIRouter(prefix="/api/learning", tags=["learning"])


@router.post("/questions")
async def generate_questions(
    payload: dict = Body(...), db: Session = Depends(get_db)
) -> dict:
    """依据知识库生成面试题 / 复习题。"""
    try:
        return await learning_service.generate_questions(
            db,
            count=int(payload.get("count") or 5),
            direction=payload.get("direction"),
            difficulty=str(payload.get("difficulty") or "medium"),
            mode=str(payload.get("mode") or "interview"),
        )
    except AIUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"出题失败：{exc}") from exc


@router.post("/grade")
async def grade(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    """评分并记录作答（低于及格线自动进错题本）。"""
    src_chunk = payload.get("source_chunk_id")
    src_doc = payload.get("source_document_id")
    try:
        return await learning_service.grade_answer(
            db,
            question=str(payload.get("question") or ""),
            reference_answer=str(payload.get("reference_answer") or ""),
            user_answer=str(payload.get("user_answer") or ""),
            direction=payload.get("direction"),
            difficulty=payload.get("difficulty"),
            source_chunk_id=uuid.UUID(src_chunk) if src_chunk else None,
            source_document_id=uuid.UUID(src_doc) if src_doc else None,
        )
    except AIUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"评分失败：{exc}") from exc


@router.get("/mistakes")
def list_mistakes(
    include_mastered: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """错题列表（只含真实提交过且未达标的记录）。"""
    items = learning_service.list_mistakes(db, include_mastered, limit)
    return {"total": len(items), "items": items}


@router.post("/mistakes/{record_id}/mastered")
def set_mastered(
    record_id: uuid.UUID,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
) -> dict:
    """标记 / 取消「已掌握」。"""
    return learning_service.set_mastered(db, record_id, bool(payload.get("mastered")))


@router.delete("/mistakes/{record_id}", status_code=204)
def delete_mistake(record_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    learning_service.delete_record(db, record_id)


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    """复习概览统计。"""
    return learning_service.review_stats(db)
