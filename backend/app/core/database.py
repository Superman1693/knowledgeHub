"""数据库连接与会话管理。"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


# pool_pre_ping：连接前探活，避免长连接失效
engine = create_engine(
    settings.resolved_database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：提供请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_connection() -> tuple[bool, str]:
    """检测数据库连通性，返回 (是否可用, 说明)。

    用于启动脚本与 /api/health，区分三类失败原因。
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        low = msg.lower()
        if "password" in low or "authentication" in low or "认证" in msg:
            return False, f"账号或密码错误：{msg}"
        if "does not exist" in low or "不存在" in msg:
            return False, f"数据库不存在：{msg}"
        if "could not connect" in low or "refused" in low or "无法连接" in msg:
            return False, f"数据库服务未启动或端口不可达：{msg}"
        return False, f"数据库连接失败：{msg}"
