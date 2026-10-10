"""本地文件存储：上传落盘、路径解析、删除与校验。"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from app.core.config import settings

# 允许的扩展名（对应 requirements.md 需求 5）
ALLOWED_EXTENSIONS = {
    "md", "markdown", "txt",
    "pdf",
    "docx",
    "py", "js", "ts", "jsx", "tsx",
    "html", "htm", "css",
    "json", "yaml", "yml",
    "ini", "toml", "conf", "cfg", "env",
    "java", "go", "rs", "c", "cpp", "h", "hpp", "cs", "php", "rb", "sql", "sh", "bat",
    "xml", "csv", "log",
}

# 二进制型扩展名（需专用解析器）
BINARY_EXTENSIONS = {"pdf", "docx"}


def ext_of(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def is_allowed(filename: str) -> bool:
    return ext_of(filename) in ALLOWED_EXTENSIONS


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def save_upload(filename: str, content: bytes) -> tuple[str, str, int]:
    """保存上传文件到 data/documents/。

    返回 (相对数据目录的路径, 扩展名, 字节数)。
    """
    settings.documents_path.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    dest = settings.documents_path / stored_name
    dest.write_bytes(content)
    rel = dest.relative_to(settings.data_path).as_posix()
    return rel, ext_of(filename), len(content)


def abs_path(rel: str) -> Path:
    """相对路径 → 绝对路径（并防止越权到数据目录之外）。"""
    p = (settings.data_path / rel).resolve()
    base = settings.data_path.resolve()
    if not str(p).startswith(str(base)):
        raise ValueError(f"非法文件路径：{rel}")
    return p


def delete_file(rel: str) -> bool:
    """删除原始文件；不存在返回 False。"""
    try:
        p = abs_path(rel)
    except ValueError:
        return False
    if p.exists() and p.is_file():
        p.unlink()
        return True
    return False


def read_text(rel: str) -> str:
    return abs_path(rel).read_text(encoding="utf-8", errors="replace")


def write_export(name: str, content: str) -> str:
    """把导出内容写入 data/exports/，返回绝对路径。"""
    settings.exports_path.mkdir(parents=True, exist_ok=True)
    safe = Path(name).name
    dest = settings.exports_path / safe
    dest.write_text(content, encoding="utf-8")
    return str(dest)
