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
from app.api import documents as documents_api
from app.api import glossary as glossary_api
from app.api import health as health_api
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


@app.get("/")
def root() -> dict:
    return {"app": "KnowledgeHub", "version": "0.1.0", "docs": "/docs"}
