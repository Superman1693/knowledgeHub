"""日志配置：控制台 + 滚动文件。"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.core.config import settings

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """初始化根日志（幂等）。日志文件写入 <data_dir>/logs/。"""
    global _configured
    if _configured:
        return

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        settings.logs_path.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.logs_path / "app.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except Exception:  # noqa: BLE001 - 日志目录不可写时仅用控制台
        root.warning("日志目录不可写，仅输出到控制台")

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
