"""局域网访问的安全闸门。

**为什么需要它**：本项目默认只监听 `127.0.0.1`，所有数据都在本机。
一旦把 `BACKEND_HOST` 改成 `0.0.0.0`（为了让手机能访问），知识库就暴露在
局域网上——里面是个人笔记、附件、可能还有私密内容。

局域网**不等于**可信网络：公司/宿舍 WiFi 上任何设备都能扫到这台机器。
所以对外监听必须配口令，而且这件事不能靠"记得去设置"——**必须由代码强制**。

两条规则：
1. `assert_exposure_is_safe()`：对外监听但没设口令 → **直接拒绝启动**（fail-closed）；
2. `AccessTokenMiddleware`：设了口令时，所有 `/api/*` 请求都要校验，
   用 `secrets.compare_digest` 做常量时间比较，避免按字符逐位试探的时序攻击。
"""
from __future__ import annotations

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 客户端提交口令的两种方式：
# - 请求头（前端 axios 用这个，正常路径）
# - 查询串（浏览器直接打开 /docs 或点下载链接时无法加头，用它兜底）
TOKEN_HEADER = "X-Access-Token"
TOKEN_QUERY = "token"


def is_loopback(host: str) -> bool:
    """该监听地址是否仅限本机。"""
    return (host or "").strip().lower() in {"127.0.0.1", "localhost", "::1"}


def assert_exposure_is_safe() -> None:
    """对外监听却没设口令时拒绝启动。

    刻意 fail-closed：宁可让服务起不来（用户会立刻看到原因），
    也不要让它静默地把私人知识库暴露在局域网上。
    """
    if settings.access_token:
        return
    if is_loopback(settings.backend_host):
        return
    raise RuntimeError(
        f"拒绝启动：BACKEND_HOST={settings.backend_host!r} 表示对外提供访问，"
        "但未设置 ACCESS_TOKEN。\n"
        "知识库中是私人资料，暴露在局域网上必须有口令保护。请二选一：\n"
        "  1) 保持仅本机访问：把 .env 中 BACKEND_HOST 设回 127.0.0.1；\n"
        "  2) 需要手机/其它设备访问：同时设置 ACCESS_TOKEN=<一段随机字符串>，\n"
        "     并确保网络环境可信（局域网≠可信网络）。"
    )


class AccessTokenMiddleware(BaseHTTPMiddleware):
    """设置了 ACCESS_TOKEN 时，校验所有 API 请求携带的口令。"""

    async def dispatch(self, request: Request, call_next):
        token = settings.access_token
        if not token:
            # 未设口令：仅回环场景（启动时已由 assert_exposure_is_safe 校验过）
            return await call_next(request)

        # 只保护 API；前端静态资源不含数据，且浏览器加载 /docs 时需要先拿到页面
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        supplied = request.headers.get(TOKEN_HEADER) or request.query_params.get(
            TOKEN_QUERY
        )
        # 常量时间比较：普通 == 会在首个不同字符处提前返回，理论上可被逐位试探
        if supplied and secrets.compare_digest(str(supplied), token):
            return await call_next(request)

        return JSONResponse(
            {
                "code": "unauthorized",
                "message": "缺少或错误访问口令。请在访问页填入 ACCESS_TOKEN。",
            },
            status_code=401,
        )
