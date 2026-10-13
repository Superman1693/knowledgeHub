"""项目开发辅助路由：代码评审、故障排查、需求拆解、项目时间线。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import (
    AIUnavailableError,
    AppError,
    NotFoundError,
    ValidationError,
)
from app.services import devhelper_service

router = APIRouter(prefix="/api/devhelper", tags=["devhelper"])


def _as_uuid(value, field: str) -> uuid.UUID:
    """把请求里的字符串安全地转成 UUID；非法时抛 422 而不是 503/500。"""
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError(f"{field} 不是合法的 UUID：{value}") from exc


@router.post("/review")
async def review(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    """代码评审：区分「知识库规范」与「AI 新建议」。"""
    try:
        return await devhelper_service.review_code(
            db,
            code=str(payload.get("code") or ""),
            language=payload.get("language"),
            focus=payload.get("focus"),
        )
    except AppError:
        raise  # 业务异常（404 / 422 / 503 等）原样透出，不要统一成 503
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"代码评审失败：{exc}") from exc


@router.post("/troubleshoot")
async def troubleshoot(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    """故障排查：区分「知识库已记录」与「待验证的推测」。"""
    try:
        return await devhelper_service.troubleshoot(
            db,
            symptom=str(payload.get("symptom") or ""),
            context_hint=payload.get("context"),
        )
    except AppError:
        raise  # 业务异常（404 / 422 / 503 等）原样透出，不要统一成 503
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"故障排查失败：{exc}") from exc


@router.post("/breakdown")
async def breakdown(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    """需求拆解：产出任务清单并标注 AI 假设。"""
    try:
        return await devhelper_service.breakdown_requirement(
            db, str(payload.get("requirement") or "")
        )
    except AppError:
        raise  # 业务异常（404 / 422 / 503 等）原样透出，不要统一成 503
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"需求拆解失败：{exc}") from exc


@router.post("/timeline")
async def timeline(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    """项目时间线：无法确认日期的事件标记为未知，不做推测。"""
    did = payload.get("document_id")
    doc_uuid = _as_uuid(did, "document_id") if did else None
    try:
        return await devhelper_service.build_timeline(
            db,
            document_id=doc_uuid,
            query=payload.get("query"),
        )
    except AppError:
        raise  # 业务异常（404 / 422 / 503 等）原样透出，不要统一成 503
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"生成时间线失败：{exc}") from exc


@router.get("/timeline/dates/{document_id}")
def timeline_dates(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """只做日期抽取（不调用模型），用于快速预览文档中出现的日期。"""
    from app.models import Document

    doc = db.get(Document, document_id)
    if not doc:
        raise NotFoundError("文档不存在")
    dates = devhelper_service.extract_dates(doc.content_text or "")
    return {"document_id": str(document_id), "dates": dates, "total": len(dates)}
