"""健康检查路由。"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.core.database import check_connection
from app.schemas.settings import HealthOut

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    ok, message = check_connection()
    return HealthOut(
        status="ok" if ok else "degraded",
        database_ok=ok,
        database_message=message,
        storage_mode=settings.storage_mode,
        ai_mode=settings.ai_mode,
        data_dir=str(settings.data_path),
    )
