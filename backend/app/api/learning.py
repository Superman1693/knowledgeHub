"""学习辅助路由：模拟面试、评分点评、错题管理、快捷复习。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import AIUnavailableError, AppError, ValidationError
from app.services import learning_service, srs_service

router = APIRouter(prefix="/api/learning", tags=["learning"])


def _as_uuid(value, field: str) -> uuid.UUID:
    """把请求里的字符串安全地转成 UUID；非法时抛 422 而不是 500。"""
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError(f"{field} 不是合法的 UUID：{value}") from exc


def _as_int(value, field: str, default: int | None = None) -> int:
    """把请求里的值安全地转成整数；非法或缺失时抛 422。"""
    if value is None or value == "":
        if default is not None:
            return default
        raise ValidationError(f"缺少参数 {field}")
    try:
        return int(value)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"{field} 必须是整数") from exc


@router.post("/questions")
async def generate_questions(
    payload: dict = Body(...), db: Session = Depends(get_db)
) -> dict:
    """依据知识库生成面试题 / 复习题。"""
    try:
        return await learning_service.generate_questions(
            db,
            count=_as_int(payload.get("count"), "count", 5),
            direction=payload.get("direction"),
            difficulty=str(payload.get("difficulty") or "medium"),
            mode=str(payload.get("mode") or "interview"),
        )
    except AppError:
        raise  # 业务异常（404 / 422 / 503 等）原样透出，不要统一成 503
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
            source_chunk_id=_as_uuid(src_chunk, "source_chunk_id") if src_chunk else None,
            source_document_id=_as_uuid(src_doc, "source_document_id") if src_doc else None,
        )
    except AppError:
        raise  # 业务异常（404 / 422 / 503 等）原样透出，不要统一成 503
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


# ==================== 闪卡与间隔复习（SRS） ====================


@router.get("/cards")
def list_cards(
    due_only: bool = Query(False, description="只返回已到期的卡片（复习队列）"),
    document_id: uuid.UUID | None = None,
    include_suspended: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """卡片列表；due_only=true 时是「今日复习」队列。"""
    cards = srs_service.list_cards(
        db,
        due_only=due_only,
        document_id=document_id,
        include_suspended=include_suspended,
        limit=limit,
    )
    return {"total": len(cards), "items": [srs_service.card_out(c) for c in cards]}


@router.post("/cards", status_code=201)
def create_card(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    """手动新建一张卡片。"""
    doc_id = payload.get("document_id")
    chunk_id = payload.get("source_chunk_id")
    card = srs_service.create_card(
        db,
        front=str(payload.get("front") or ""),
        back=str(payload.get("back") or ""),
        document_id=_as_uuid(doc_id, "document_id") if doc_id else None,
        source_chunk_id=_as_uuid(chunk_id, "source_chunk_id") if chunk_id else None,
        tags=payload.get("tags"),
    )
    return srs_service.card_out(card)


@router.post("/cards/generate")
async def generate_cards(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    """依据某篇笔记用 AI 生成卡片（只依据原文，不编造）。"""
    did = payload.get("document_id")
    if not did:
        raise ValidationError("请指定 document_id")
    try:
        cards = await srs_service.generate_cards_ai(
            db,
            _as_uuid(did, "document_id"),
            _as_int(payload.get("count"), "count", 8),
        )
    except AppError:
        raise  # 404 / 422 / 503 原样透出
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"生成卡片失败：{exc}") from exc
    return {"total": len(cards), "items": [srs_service.card_out(c) for c in cards]}


@router.get("/cards/export-anki")
def export_cards_anki(
    document_id: uuid.UUID | None = None,
    include_suspended: bool = Query(False),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """导出卡片为 Anki 文本导入格式（TSV）。

    用 GET：这是纯读取操作，不产生服务端文件。
    Anki 里「文件 → 导入」选这个文件，勾选「允许 HTML」即可。
    ⚠️ 本路由必须声明在 `/{card_id}` 之前，否则 export-anki 会被当成 UUID 解析。
    """
    text = srs_service.export_anki_text(
        db, document_id=document_id, include_suspended=include_suspended
    )
    filename = "knowledgehub-cards-anki.txt"
    if document_id:
        filename = f"knowledgehub-{str(document_id)[:8]}-anki.txt"
    return PlainTextResponse(
        text,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.put("/cards/{card_id}")
def update_card(
    card_id: uuid.UUID, payload: dict = Body(...), db: Session = Depends(get_db)
) -> dict:
    card = srs_service.update_card(
        db,
        card_id,
        front=payload.get("front"),
        back=payload.get("back"),
        suspended=payload.get("suspended"),
    )
    return srs_service.card_out(card)


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    srs_service.delete_card(db, card_id)


@router.post("/cards/{card_id}/review")
def review_card(
    card_id: uuid.UUID, payload: dict = Body(...), db: Session = Depends(get_db)
) -> dict:
    """提交一次复习评分（0~5），按 SM-2 更新下次复习时间。"""
    rating = _as_int(payload.get("rating"), "rating")
    card = srs_service.get_card(db, card_id)
    updated = srs_service.apply_review(db, card, rating)
    return {"card": srs_service.card_out(updated), "stats": srs_service.review_stats(db)}


@router.get("/cards/{card_id}/reviews")
def card_reviews(card_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """某张卡片的复习历史。"""
    card = srs_service.get_card(db, card_id)
    logs = [
        {
            "id": str(log.id),
            "rating": log.rating,
            "prev_interval": log.prev_interval,
            "next_interval": log.next_interval,
            "ease_after": log.ease_after,
            "reviewed_at": log.reviewed_at.isoformat() if log.reviewed_at else None,
        }
        for log in card.reviews
    ]
    return {"total": len(logs), "items": logs}


@router.get("/srs-stats")
def srs_stats(db: Session = Depends(get_db)) -> dict:
    """间隔复习统计：待复习 / 各状态 / 今日已复习 / 连续学习天数。"""
    return srs_service.review_stats(db)
