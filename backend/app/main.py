"""KnowledgeHub 后端入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import backup as backup_api
from app.api import categories as categories_api
from app.api import chat as chat_api
from app.api import devhelper as devhelper_api
from app.api import documents as documents_api
from app.api import glossary as glossary_api
from app.api import health as health_api
from app.api import insights as insights_api
from app.api import learning as learning_api
from app.api import search as search_api
from app.api import settings as settings_api
from app.api import tags as tags_api
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.services import settings_service

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    settings.ensure_dirs()
    # 应用数据库中的配置覆盖层
    db = SessionLocal()
    try:
        settings_service.load_overrides(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载配置覆盖失败（可能数据库未初始化）：%s", exc)
    finally:
        db.close()
    if not settings.storage_mode_valid:
        logger.error(
            "不支持的存储模式 %s：本项目统一使用本机 PostgreSQL 18 + pgvector，"
            "请将 .env 中的 STORAGE_MODE 设为 postgres 后重启。",
            settings.storage_mode,
        )
    logger.info("KnowledgeHub 后端已启动，数据目录：%s", settings.data_path)
    yield
    logger.info("KnowledgeHub 后端已停止")


app = FastAPI(
    title="KnowledgeHub API",
    version="0.1.0",
    description="本地个人知识库 AI 平台后端",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(health_api.router)
app.include_router(documents_api.router)
app.include_router(categories_api.router)
app.include_router(tags_api.router)
app.include_router(glossary_api.router)
app.include_router(search_api.router)
app.include_router(chat_api.router)
app.include_router(settings_api.router)
app.include_router(backup_api.router)
# 扩展模块：知识加工 / 学习辅助 / 项目开发辅助
app.include_router(insights_api.router)
app.include_router(learning_api.router)
app.include_router(devhelper_api.router)


@app.get("/")
def root() -> dict:
    return {"app": "KnowledgeHub", "version": "0.1.0", "docs": "/docs"}
