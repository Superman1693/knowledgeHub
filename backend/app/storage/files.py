"""本地文件存储：上传落盘、路径解析、删除与校验。"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

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
BINARY_EXTENSIONS = {"pdf", "docx", "png", "jpg", "jpeg", "webp", "bmp", "gif", "avif"}

# 图片扩展名（附件里的图片可直接在 Markdown 中以内联图片形式引用）
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif"}
# 可**作为文档导入**的图片：这些格式能通过 OCR 提取文字。
# 不含 svg —— 它是矢量文本格式，走文本解析而不是 OCR。
OCR_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "avif"}
# 把可 OCR 的图片纳入「可作为文档导入」的白名单：
# 截图里的报错信息/配置是技术笔记最常见的素材，此前只能当附件存着、进不了知识库。
ALLOWED_EXTENSIONS |= OCR_IMAGE_EXTENSIONS
# 允许作为附件上传的扩展名（比「可解析文档」宽：附件只需存放与引用）
ATTACHMENT_EXTENSIONS = IMAGE_EXTENSIONS | {
    "pdf", "docx", "doc", "xlsx", "xls", "csv", "txt", "md",
    "zip", "7z", "rar", "mp3", "wav", "mp4", "mov", "json", "yaml", "yml",
}


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


def save_note(filename: str, content: str) -> tuple[str, str, int]:
    """把「应用内新建的笔记」写入 data/documents/。

    与 save_upload 的差别：入参是文本而非字节，且强制 .md 后缀（无后缀时补 .md）。
    返回 (相对数据目录的路径, 扩展名, 字节数)。
    """
    settings.documents_path.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower() or ".md"
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    dest = settings.documents_path / stored_name
    data = content.encode("utf-8")
    dest.write_bytes(data)
    rel = dest.relative_to(settings.data_path).as_posix()
    return rel, ext_of(filename) or "md", len(data)


def write_text(rel: str, content: str) -> int:
    """覆盖写入已有文件（编辑保存用），返回写入字节数。"""
    path = abs_path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    path.write_bytes(data)
    return len(data)


# ---------------- 附件 ----------------
def is_allowed_attachment(filename: str) -> bool:
    return ext_of(filename) in ATTACHMENT_EXTENSIONS


def save_attachment(filename: str, content: bytes) -> tuple[str, str, int]:
    """保存附件到 data/attachments/{images|documents}/。

    图片单独放 images/，便于前端预览与批量管理。
    返回 (相对数据目录的路径, 扩展名, 字节数)。
    """
    ext = ext_of(filename)
    sub = "images" if ext in IMAGE_EXTENSIONS else "documents"
    base = settings.attachments_path / sub
    base.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{('.' + ext) if ext else ''}"
    dest = base / stored
    dest.write_bytes(content)
    rel = dest.relative_to(settings.data_path).as_posix()
    return rel, ext, len(content)


def list_attachments() -> list[dict]:
    """列出全部附件（含 url 与大小）。"""
    items: list[dict] = []
    for sub in ("images", "documents"):
        base = settings.attachments_path / sub
        if not base.exists():
            continue
        for f in sorted(base.iterdir()):
            if not f.is_file():
                continue
            try:
                stat = f.stat()
            except OSError:
                continue
            items.append(
                {
                    "name": f.name,
                    "sub": sub,
                    "size": stat.st_size,
                    "url": f"/api/attachments/file/{sub}/{f.name}",
                }
            )
    return items


def delete_attachment(rel: str) -> bool:
    """删除附件；与 delete_file 一样「尽力删除、绝不抛异常」。"""
    return delete_file(rel)


def extract_attachment_refs(content: str) -> list[str]:
    """从 Markdown 内容中提取附件引用路径（相对数据目录）。

    匹配 `/api/attachments/file/{sub}/{name}` 形式的 URL，
    返回去重后的 `attachments/{sub}/{name}` 路径列表。
    用于：文档详情页展示「本笔记引用了哪些附件」、附件管理页标记「未被引用」。
    """
    import re

    pattern = re.compile(r"/api/attachments/file/(images|documents)/([^\s\)\]\"']+)")
    seen: set[str] = set()
    out: list[str] = []
    for match in pattern.finditer(content or ""):
        rel = f"attachments/{match.group(1)}/{match.group(2)}"
        if rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def read_bytes(rel: str) -> bytes:
    return abs_path(rel).read_bytes()


def abs_path(rel: str) -> Path:
    """相对路径 → 绝对路径（并防止越权到数据目录之外）。"""
    p = (settings.data_path / rel).resolve()
    base = settings.data_path.resolve()
    # 必须用 is_relative_to 逐段比较：startswith 会把 `<data>_evil` 误判为 `<data>` 之内
    if not p.is_relative_to(base):
        raise ValueError(f"非法文件路径：{rel}")
    return p


def delete_file(rel: str) -> bool:
    """删除原始文件；不存在或删除失败一律返回 False，**绝不抛异常**。

    为什么不能抛：调用方（purge / empty_trash）此时通常**已经提交了数据库变更**，
    若把文件删除失败变成 500，用户会误以为「删除没成功」而重复操作。
    真实场景里删除失败很常见：Windows 上文件被编辑器/杀毒软件占用、只读属性、权限不足。
    """
    try:
        p = abs_path(rel)
    except ValueError:
        return False
    try:
        if p.exists() and p.is_file():
            p.unlink()
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除文件失败（数据库记录已删除，文件残留）：%s -> %s", rel, exc)
    except SystemExit:
        # 某些运行环境（沙箱/安全外壳）会在批量删除时拦截 unlink 并抛 SystemExit。
        # 这里显式吞掉：记录已在数据库侧删除，不该因此向用户报 500；
        # 文件残留是环境限制，仅记录日志，不做任何绕过。
        logger.warning("文件删除被运行环境拦截，文件残留：%s", rel)
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


def reveal_in_file_manager(path: Path) -> bool:
    """在系统文件管理器中定位该文件（本地应用场景）。

    文件不存在时返回 False，不抛异常。
    """
    if not path.exists():
        return False
    try:
        if os.name == "nt":
            # explorer 的 /select 会打开资源管理器并选中该文件
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
        return True
    except Exception:  # noqa: BLE001
        return False
