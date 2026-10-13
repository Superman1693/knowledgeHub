"""健康检查路由。"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.core.database import check_connection
from app.rag.pinyin import pinyin_available
from app.rag.tokenize import segmentation_mode
from app.schemas.settings import HealthOut
from app.services.ocr_service import ocr_status

router = APIRouter(prefix="/api", tags=["system"])


def _capabilities() -> dict:
    """可选能力状态（分词引擎 / OCR 引擎 / 拼音检索）。"""
    ocr = ocr_status()
    return {
        "segmentation": segmentation_mode(),
        "ocr_engine": ocr["engine"],
        "ocr_available": ocr["available"],
        "pinyin_search": pinyin_available(),
    }


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    ok, message = check_connection()
    caps = _capabilities()
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
            **caps,
        )
    return HealthOut(
        status="ok" if ok else "degraded",
        database_ok=ok,
        database_message=message,
        storage_mode=settings.storage_mode,
        ai_mode=settings.ai_mode,
        data_dir=str(settings.data_path),
        **caps,
    )
