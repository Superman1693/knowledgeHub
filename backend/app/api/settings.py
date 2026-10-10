"""系统设置路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.settings import (
    IndexStatusOut,
    ModelTestResult,
    SettingsOut,
    SettingsUpdate,
)
from app.services import document_service, settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)) -> SettingsOut:
    return settings_service.to_out(db)


@router.put("", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsOut:
    return settings_service.update(db, payload)


@router.post("/test-model", response_model=ModelTestResult)
async def test_model(db: Session = Depends(get_db)) -> ModelTestResult:
    return await settings_service.test_model(db)


@router.get("/index-status", response_model=IndexStatusOut)
def index_status(db: Session = Depends(get_db)) -> IndexStatusOut:
    return IndexStatusOut(**document_service.index_status(db))
