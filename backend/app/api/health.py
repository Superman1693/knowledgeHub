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
    # 存储模式配置非法时优先给出明确原因，避免用户误判「服务正常」
    if not settings.storage_mode_valid:
        return HealthOut(
            status="degraded",
            database_ok=False,
            database_message=(
                f"不支持的存储模式：{settings.storage_mode}。"
                "本项目统一使用本机 PostgreSQL 18 + pgvector，"
                "请将 .env 中的 STORAGE_MODE 设为 postgres。"
            ),
            storage_mode=settings.storage_mode,
            ai_mode=settings.ai_mode,
            data_dir=str(settings.data_path),
        )
    return HealthOut(
        status="ok" if ok else "degraded",
        database_ok=ok,
        database_message=message,
        storage_mode=settings.storage_mode,
        ai_mode=settings.ai_mode,
        data_dir=str(settings.data_path),
    )
