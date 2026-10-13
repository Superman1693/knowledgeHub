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
    Flashcard,
    GlossaryTerm,
    Message,
    NoteLink,
    NoteRevision,
    QuizRecord,
    ReviewLog,
    SavedSearch,
    Tag,
    document_tags,
)

logger = get_logger(__name__)

# 恢复时的清空顺序（先子后父）。
# note_links / quiz_records / glossary_terms / review_logs / flashcards 必须一并清空：
# 否则恢复后它们仍指向被删除的 documents / chunks，或残留与备份不一致的数据。
CLEAR_ORDER = [
    "saved_searches",    # 无外键依赖，先清
    "review_logs",       # 引用 flashcards
    "flashcards",        # 引用 documents / chunks
    "note_links",        # 引用 documents
    "note_revisions",    # 引用 documents（版本历史）
    "quiz_records",      # 引用 documents / chunks
    "glossary_terms",
    "messages",
    "conversations",
    "document_tags",
    "chunks",
    "documents",
    "tags",
    "categories",
    "app_settings",
]

# 转储与恢复顺序（先父后子）。
# chunks / note_links / flashcards 必须排在 quiz_records、review_logs 之前。
DUMP_TABLES = [
    ("categories", Category),
    ("tags", Tag),
    ("documents", Document),
    ("conversations", Conversation),
    ("note_revisions", NoteRevision),   # 版本历史（引用 documents）
    ("chunks", Chunk),
    ("note_links", NoteLink),
    ("flashcards", Flashcard),
    ("review_logs", ReviewLog),
    ("glossary_terms", GlossaryTerm),
    ("quiz_records", QuizRecord),
    ("messages", Message),
    ("app_settings", AppSetting),
    ("saved_searches", SavedSearch),
]

# 旧版本备份可能缺少后来新增的表（如 note_revisions），缺失时按「空」处理以保持兼容；
# 其余表名必须存在，否则判定为损坏的备份 —— 避免「先清空全库、再插入 0 行」的数据灾难。
OPTIONAL_BACKUP_KEYS = {"note_revisions"}


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
        stmt = select(model)
        if model is Chunk:
            # 父子检索下 chunks 存在自引用（parent_id → chunks.id）。
            # 转储顺序即恢复插入顺序，必须让父块（parent_id IS NULL）排在子块之前，
            # 否则恢复时会先插子块、自引用外键立即违约。
            stmt = stmt.order_by(Chunk.parent_id.is_not(None), Chunk.chunk_index)
        rows = db.execute(stmt).scalars().all()
        data[name] = [_row_to_dict(r) for r in rows]
    # 关联表
    assoc = db.execute(select(document_tags)).all()
    data["document_tags"] = [
        {"document_id": str(r[0]), "tag_id": str(r[1])} for r in assoc
    ]
    return data


def _safe_restore_target(rel: str) -> Path | None:
    """把备份条目名映射为数据目录内的安全路径；越出数据目录时返回 None。

    防止 Zip Slip：恶意备份可含 `files/../../../evil` 这类条目，
    不加校验会覆盖数据目录之外的任意文件。
    """
    target = (settings.data_path / rel).resolve()
    base = settings.data_path.resolve()
    if not target.is_relative_to(base):
        return None
    return target


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
        "contains": [
            "数据库全部业务表（JSON，含版本历史 note_revisions）",
            "documents/ 原始文档",
            "attachments/ 附件",
        ],
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


def _validate_dump(data: object) -> dict:
    """校验备份 dump 的结构完整性，返回规范化后的 dict。

    恢复是破坏性操作（先清空全库再导入），所以必须在动数据之前就把损坏的备份挡下来：
    否则一个合法但为空的 JSON `{}` 会**清空全库却插入 0 行**。
    """
    if not isinstance(data, dict):
        raise ValidationError("备份文件损坏：db_dump.json 不是对象")
    required = (
        {name for name, _ in DUMP_TABLES} | {"document_tags"}
    ) - OPTIONAL_BACKUP_KEYS
    missing = sorted(required - set(data.keys()))
    if missing:
        raise ValidationError(f"备份文件不完整，缺少数据表：{', '.join(missing)}")
    for key, rows in data.items():
        if not isinstance(rows, list):
            raise ValidationError(f"备份文件损坏：{key} 不是数组")
    return data


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
        data = _validate_dump(json.loads(zf.read("db_dump.json").decode("utf-8")))

        # 「清空 + 导入」放在同一个事务内，任一步失败即整体回滚，
        # 不会留下「已清空但没导入」的半损坏状态。
        try:
            for table in CLEAR_ORDER:
                db.execute(text(f"DELETE FROM {table}"))
            db.flush()

            # 恢复表：每张表落库后再处理下一张，保证外键顺序
            # （documents→categories、chunks→documents、quiz_records→chunks）。
            for name_key, model in DUMP_TABLES:
                rows = data.get(name_key, [])
                if model is Chunk:
                    # chunks 自引用：先插父块并 flush，再插子块，避免 parent_id 外键违约
                    for row in rows:
                        if not row.get("parent_id"):
                            db.add(model(**row))
                    db.flush()
                    for row in rows:
                        if row.get("parent_id"):
                            db.add(model(**row))
                else:
                    for row in rows:
                        db.add(model(**row))
                db.flush()
            for row in data.get("document_tags", []):
                db.execute(
                    document_tags.insert().values(
                        document_id=row["document_id"], tag_id=row["tag_id"]
                    )
                )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("恢复备份失败，已回滚到恢复前状态：%s", exc)
            raise ValidationError(
                f"恢复失败（数据库已回滚，未做任何改动）：{exc}"
            ) from exc

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
            if not member.startswith("files/"):
                continue
            rel = member[len("files/") :]
            target = _safe_restore_target(rel)
            if target is None:
                logger.warning("跳过非法的备份条目（越出数据目录）：%s", member)
                continue
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
