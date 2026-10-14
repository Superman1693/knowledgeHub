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
from app.api import attachments as attachments_api
from app.api import devhelper as devhelper_api
from app.api import documents as documents_api
from app.api import glossary as glossary_api
from app.api import graph as graph_api
from app.api import health as health_api
from app.api import insights as insights_api
from app.api import learning as learning_api
from app.api import search as search_api
from app.api import saved_searches as saved_searches_api
from app.api import settings as settings_api
from app.api import tags as tags_api
from app.api import workspace as workspace_api
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.security import AccessTokenMiddleware, assert_exposure_is_safe
from app.services import document_service, settings_service, workspace_service

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 最先执行：对外监听却没设口令就拒绝启动（fail-closed）。
    # 放在最前面是刻意的——任何初始化动作之前就该拦下来，
    # 不能出现"已经连上数据库、开了扫描、然后才报错退出"的状态。
    assert_exposure_is_safe()

    setup_logging()
    settings.ensure_dirs()
    # 首次启动写入内置笔记模板（已存在则不覆盖）
    workspace_service.ensure_builtin_templates()
    # 应用数据库中的配置覆盖层
    db = SessionLocal()
    try:
        try:
            settings_service.load_overrides(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("加载配置覆盖失败（可能数据库未初始化）：%s", exc)
        # 回收站保留期清理：默认关闭（trash_retention_days=0，永不自动清理）
        try:
            removed = document_service.purge_expired_trash(
                db, settings.trash_retention_days
            )
            if removed:
                logger.info("已按保留期清理回收站 %s 篇", removed)
        except Exception as exc:  # noqa: BLE001
            logger.warning("回收站保留期清理失败（不影响使用）：%s", exc)
        # 启动时**只读**扫描外部变更：只在工作台提示，不修改任何内容
        workspace_service.startup_scan(db)
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

# 局域网访问口令校验（未设 ACCESS_TOKEN 时是直通）。
# ⚠️ 必须注册在 CORS **之前**：Starlette 中越晚注册的中间件越靠外层，
# 所以先注册口令、后注册 CORS，CORS 才会在最外层——
# 这样口令中间件返回的 401 也会带上 CORS 头。否则浏览器只报"跨域失败"，
# 用户根本看不到"口令错误"这个真正原因。
app.add_middleware(AccessTokenMiddleware)

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
app.include_router(attachments_api.router)
app.include_router(glossary_api.router)
app.include_router(search_api.router)
# 保存的检索条件（智能集合）
app.include_router(saved_searches_api.router)
app.include_router(chat_api.router)
app.include_router(settings_api.router)
app.include_router(backup_api.router)
# 工作区：工作台 / 每日笔记 / 模板 / 外部变更扫描
app.include_router(workspace_api.router)
# 扩展模块：知识加工 / 学习辅助 / 项目开发辅助
app.include_router(insights_api.router)
app.include_router(learning_api.router)
app.include_router(devhelper_api.router)
# 知识图谱
app.include_router(graph_api.router)


@app.get("/")
def root() -> dict:
    return {"app": "KnowledgeHub", "version": "0.1.0", "docs": "/docs"}
