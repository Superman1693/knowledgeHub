"""备份与恢复服务：数据库 JSON 转储 + 原始文件打包。"""
from __future__ import annotations

import json
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import (
    AppSetting,
    Category,
    Chunk,
    Conversation,
    Document,
    Message,
    Tag,
    document_tags,
)

logger = get_logger(__name__)

# 恢复时的清空顺序（先子后父）
CLEAR_ORDER = [
    "messages",
    "conversations",
    "document_tags",
    "chunks",
    "documents",
    "tags",
    "categories",
    "app_settings",
]

# 转储顺序（先父后子）
DUMP_TABLES = [
    ("categories", Category),
    ("tags", Tag),
    ("documents", Document),
    ("chunks", Chunk),
    ("conversations", Conversation),
    ("messages", Message),
    ("app_settings", AppSetting),
]


def _jsonable(value):
    if isinstance(value, (uuid.UUID,)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _row_to_dict(obj) -> dict:
    return {
        c.key: _jsonable(getattr(obj, c.key))
        for c in inspect(obj).mapper.column_attrs
    }


def dump_all(db: Session) -> dict:
    """把全部业务表转储为可 JSON 序列化的字典。"""
    data: dict[str, list[dict]] = {}
    for name, model in DUMP_TABLES:
        rows = db.execute(select(model)).scalars().all()
        data[name] = [_row_to_dict(r) for r in rows]
    # 关联表
    assoc = db.execute(select(document_tags)).all()
    data["document_tags"] = [
        {"document_id": str(r[0]), "tag_id": str(r[1])} for r in assoc
    ]
    return data


# ---------------- 备份 ----------------
def create_backup(db: Session) -> dict:
    settings.backups_path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"knowledgehub_backup_{ts}.zip"
    dest = settings.backups_path / name

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("db_dump.json", json.dumps(dump_all(db), ensure_ascii=False, indent=1))
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "created_at": datetime.now().isoformat(),
                    "storage_mode": settings.storage_mode,
                    "app": "KnowledgeHub",
                    "version": 1,
                },
                ensure_ascii=False,
            ),
        )
        for sub in ("documents", "attachments"):
            base = settings.data_path / sub
            if base.exists():
                for f in base.rglob("*"):
                    if f.is_file():
                        zf.write(f, f"files/{sub}/{f.relative_to(base).as_posix()}")

    return {
        "name": name,
        "path": str(dest),
        "size": dest.stat().st_size,
        "contains": ["数据库全部业务表（JSON）", "documents/ 原始文档", "attachments/ 附件"],
    }


def list_backups() -> list[dict]:
    if not settings.backups_path.exists():
        return []
    items = []
    for f in sorted(settings.backups_path.glob("*.zip"), reverse=True):
        items.append({"name": f.name, "size": f.stat().st_size})
    return items


def _load_manifest(path: Path) -> dict | None:
    try:
        with zipfile.ZipFile(path) as zf:
            if "manifest.json" not in zf.namelist():
                return None
            return json.loads(zf.read("manifest.json").decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def restore_backup(db: Session, name: str) -> dict:
    """从备份恢复：先校验完整性与版本，再覆盖导入。"""
    path = settings.backups_path / Path(name).name
    if not path.exists():
        raise NotFoundError("备份文件不存在")

    manifest = _load_manifest(path)
    if manifest is None:
        raise ValidationError("备份文件损坏：缺少 manifest.json")
    if manifest.get("version") != 1:
        raise ValidationError(f"备份版本不兼容：{manifest.get('version')}")

    with zipfile.ZipFile(path) as zf:
        if "db_dump.json" not in zf.namelist():
            raise ValidationError("备份文件损坏：缺少 db_dump.json")
        data = json.loads(zf.read("db_dump.json").decode("utf-8"))

        # 清空现有数据
        for table in CLEAR_ORDER:
            if table == "document_tags":
                db.execute(text("DELETE FROM document_tags"))
            else:
                db.execute(text(f"DELETE FROM {table}"))
        db.commit()

        # 恢复表
        for name_key, model in DUMP_TABLES:
            for row in data.get(name_key, []):
                db.add(model(**row))
        db.flush()
        for row in data.get("document_tags", []):
            db.execute(
                document_tags.insert().values(
                    document_id=row["document_id"], tag_id=row["tag_id"]
                )
            )
        db.commit()

        # 恢复文件：先清空原目录，避免残留孤儿文件
        # （备份定义了完整状态；否则被覆盖掉记录的旧文件会一直留在磁盘上）
        for sub in ("documents", "attachments"):
            base = settings.data_path / sub
            if base.exists():
                for f in base.rglob("*"):
                    if f.is_file():
                        try:
                            f.unlink()
                        except OSError:
                            logger.warning("无法删除待覆盖文件：%s", f)

        restored_files = 0
        for member in zf.namelist():
            if member.startswith("files/"):
                rel = member[len("files/") :]
                target = settings.data_path / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))
                restored_files += 1

    return {"restored": True, "files": restored_files, "tables": len(DUMP_TABLES) + 1}


# ---------------- 维护 ----------------
def clean_cache() -> dict:
    """清理可重建缓存，不触碰正式数据。"""
    removed = 0
    freed = 0
    if settings.cache_path.exists():
        for f in settings.cache_path.rglob("*"):
            if f.is_file():
                freed += f.stat().st_size
                f.unlink()
                removed += 1
    return {"removed": removed, "freed_bytes": freed}


def data_dir_info() -> dict:
    def size_of(p: Path) -> int:
        if not p.exists():
            return 0
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

    return {
        "data_dir": str(settings.data_path),
        "documents_bytes": size_of(settings.documents_path),
        "attachments_bytes": size_of(settings.attachments_path),
        "exports_bytes": size_of(settings.exports_path),
        "backups_bytes": size_of(settings.backups_path),
        "cache_bytes": size_of(settings.cache_path),
        "logs_bytes": size_of(settings.logs_path),
    }
