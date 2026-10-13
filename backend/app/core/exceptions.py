"""统一异常定义与 FastAPI 异常处理。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """业务异常基类。"""

    status_code = 400
    code = "APP_ERROR"

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class ParseError(AppError):
    status_code = 400
    code = "PARSE_ERROR"


class AIUnavailableError(AppError):
    status_code = 503
    code = "AI_UNAVAILABLE"


class EmbeddingUnavailableError(AIUnavailableError):
    """嵌入模型不可用。

    区别于普通 AI 失败：此时知识片段已成功写入数据库，
    关键词检索（pg_trgm）仍然可用，只是缺少向量，语义检索不可用。
    """

    code = "EMBEDDING_UNAVAILABLE"


class StorageError(AppError):
    status_code = 500
    code = "STORAGE_ERROR"


class ConflictError(AppError):
    """并发修改冲突（乐观锁失败）。

    典型场景：笔记在应用外（VS Code / Typora）被改动，而应用内也正在编辑，
    保存时底层内容已被改写。此时宁可**拒绝保存并让用户对比**，
    也不要静默覆盖掉另一份修改——那会无声地丢内容。
    """

    status_code = 409
    code = "CONFLICT"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "code": "INTERNAL_ERROR",
                "message": "服务器内部错误",
                "detail": str(exc),
            },
        )
