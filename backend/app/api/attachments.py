"""附件路由：上传、列表、下载（含图片内联预览）。

把此前一直是死代码的 `settings.attachments_path` 真正用起来：
技术笔记里的截图、示例文件、导出包都可以作为附件上传，并在 Markdown 中引用。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.storage import files

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


@router.get("")
def list_attachments(db: Session = Depends(get_db)) -> dict:
    """列出全部附件（图片与文档）。"""
    items = files.list_attachments()
    return {"total": len(items), "items": items}


@router.post("", status_code=201)
async def upload_attachment(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> dict:
    """上传附件，返回可直接写进 Markdown 的片段。

    图片返回 `![名称](url)`，其它文件返回 `[名称](url)`。
    """
    filename = file.filename or "attachment"
    if not files.is_allowed_attachment(filename):
        raise ValidationError(f"不支持的附件格式：{filename}")

    declared = getattr(file, "size", None)
    if declared is not None and declared > settings.max_upload_bytes:
        raise ValidationError(
            f"附件超过大小限制（{settings.max_upload_mb}MB）：{filename}"
        )
    content = await file.read()
    if not content:
        raise ValidationError("附件内容为空")
    if len(content) > settings.max_upload_bytes:
        raise ValidationError(
            f"附件超过大小限制（{settings.max_upload_mb}MB）：{filename}"
        )

    rel, ext, size = files.save_attachment(filename, content)
    sub, name = rel.split("/")[1], rel.split("/")[-1]
    url = f"/api/attachments/file/{sub}/{name}"
    label = filename.rsplit(".", 1)[0] or filename
    is_image = ext in files.IMAGE_EXTENSIONS
    markdown = f"![{label}]({url})" if is_image else f"[{label}]({url})"

    return {
        "path": rel,
        "url": url,
        "markdown": markdown,
        "size": size,
        "filename": filename,
        "kind": "image" if is_image else "file",
    }


@router.get("/file/{sub}/{name}")
def get_attachment(sub: str, name: str) -> FileResponse:
    """按附件路径返回文件。

    路径通过 `files.abs_path` 解析，已用 `is_relative_to` 校验，
    因此 `../` 之类的越权路径会被拒绝。
    """
    try:
        path = files.abs_path(f"attachments/{sub}/{name}")
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if not path.exists() or not path.is_file():
        raise NotFoundError("附件不存在")
    return FileResponse(path)


@router.delete("/file/{sub}/{name}", status_code=204)
def delete_attachment(sub: str, name: str) -> None:
    """删除附件（尽力删除，失败不影响返回）。"""
    try:
        rel = f"attachments/{sub}/{name}"
        files.abs_path(rel)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    files.delete_attachment(rel)
