"""工作区服务：每日笔记、笔记模板、外部变更扫描、工作台汇总。

对应 LocalMind 的三处设计：
- 「每日笔记」：自动创建按日期命名的笔记；
- 「笔记模板」：技术笔记 / 项目复盘 / 读书笔记 / 面试记录；
- 「文件与数据库一致性」：**程序启动时扫描知识库，对比文件与索引记录**，
  并明确指出「不能只依赖文件监听器，因为程序异常退出时可能漏掉事件」——
  因此这里提供的是**主动扫描**（可随时手动触发），而不是依赖监听。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.models import Chunk, Document
from app.models.document import STATUS_FAILED
from app.storage import files

logger = get_logger(__name__)

# 一次性收录「未登记文件」的数量上限。
# `register_orphans=true` 会把 data/documents 中**所有**未登记文件导入为文档，
# 每篇都要解析 + 分块 + 嵌入（一次网络调用）。文件一多，请求会长时间挂起并可能
# 在超时后留下「收了一半」的状态。超过上限时明确拒绝，让用户分批处理，
# 而不是让请求默默跑到超时。
MAX_REGISTER_ORPHANS = 200

# 启动扫描的最近一次结果（只读缓存，供工作台提示用）。
# 启动扫描**只读**——任何改动知识库的动作都必须由用户在「扫描同步」里显式确认。
STARTUP_SCAN: dict | None = None

# 内置模板：首次启动时写入 data/templates/，之后用户可自行编辑
BUILTIN_TEMPLATES: dict[str, str] = {
    "技术笔记.md": """# 主题

## 背景 / 问题现象

## 原因分析

## 解决方案

```
代码或命令
```

## 验证结果

## 参考
""",
    "项目复盘.md": """# 项目名称

## 目标

## 实际结果

## 做对了什么

## 做错了什么

## 下次改进

## 可复用产出
""",
    "读书笔记.md": """# 书名 / 文章标题

- 作者：
- 阅读日期：

## 核心观点

## 我的理解

## 可落地的行动

## 金句摘录
""",
    "面试记录.md": """# 面试记录

- 公司 / 岗位：
- 日期：

## 问题与回答

### Q1

**回答：**

**复盘：**

## 未答上的知识点

## 后续补强计划
""",
}

DAILY_TEMPLATE = """# {day}

## 今日记录


## 待办

- [ ] 

## 学到的东西

"""


# ---------------- 每日笔记 ----------------
def today_title(day: date | None = None) -> str:
    return (day or date.today()).strftime("%Y-%m-%d")


def find_daily_note(db: Session, day: date | None = None) -> Document | None:
    """查找当天笔记（标题为 `YYYY-MM-DD`）。"""
    title = today_title(day)
    return (
        db.execute(
            select(Document)
            .where(
                Document.title == title,
                Document.deleted_at.is_(None),
            )
            .limit(1)
        )
        .scalars()
        .first()
    )


async def get_or_create_daily_note(db: Session, day: date | None = None) -> tuple[Document, bool]:
    """获取当天笔记，不存在则创建。返回 (文档, 是否新建)。"""
    existing = find_daily_note(db, day)
    if existing:
        return existing, False

    from app.services import document_service

    title = today_title(day)
    doc = await document_service.create_note(
        db, title=title, content_text=DAILY_TEMPLATE.format(day=title)
    )
    return doc, True


# ---------------- 笔记模板 ----------------
def ensure_builtin_templates() -> None:
    """首次启动写入内置模板（已存在则不覆盖，尊重用户修改）。"""
    settings.templates_path.mkdir(parents=True, exist_ok=True)
    for name, body in BUILTIN_TEMPLATES.items():
        path = settings.templates_path / name
        if not path.exists():
            try:
                path.write_text(body, encoding="utf-8")
            except OSError as exc:  # pragma: no cover
                logger.warning("写入内置模板失败 %s：%s", name, exc)


def list_templates() -> list[dict]:
    """列出 data/templates/*.md。"""
    ensure_builtin_templates()
    items: list[dict] = []
    for f in sorted(settings.templates_path.glob("*.md")):
        try:
            stat = f.stat()
        except OSError:
            continue
        items.append(
            {
                "name": f.stem,
                "filename": f.name,
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return items


def read_template(name: str) -> str:
    """读取模板正文（只允许 templates 目录内的文件名，防路径穿越）。"""
    safe = Path(name).name
    if not safe:
        raise FileNotFoundError("模板名不能为空")
    path = settings.templates_path / safe
    if not path.exists():
        raise FileNotFoundError(f"模板不存在：{safe}")
    return path.read_text(encoding="utf-8")


# ---------------- 外部变更扫描 ----------------
def _detect(db: Session) -> tuple[dict[str, Document], dict[str, Path], list, list, list]:
    """对比磁盘与数据库，返回 (docs, disk, changed, missing, orphan)。"""
    docs = {
        d.file_path: d
        for d in db.execute(select(Document).where(Document.deleted_at.is_(None)))
        .scalars()
        .all()
    }

    disk: dict[str, Path] = {}
    if settings.documents_path.exists():
        for f in sorted(settings.documents_path.iterdir()):
            if f.is_file() and files.is_allowed(f.name):
                disk[f"documents/{f.name}"] = f

    changed: list[dict] = []
    missing: list[dict] = []
    orphan: list[dict] = []

    for rel, doc in docs.items():
        f = disk.get(rel)
        if f is None:
            missing.append(
                {"document_id": str(doc.id), "title": doc.title, "file_path": rel}
            )
        elif f.stat().st_size != doc.file_size:
            changed.append(
                {
                    "document_id": str(doc.id),
                    "title": doc.title,
                    "file_path": rel,
                    "db_size": doc.file_size,
                    "disk_size": f.stat().st_size,
                }
            )

    for rel, f in disk.items():
        if rel not in docs:
            orphan.append({"file_path": rel, "filename": f.name, "size": f.stat().st_size})

    return docs, disk, changed, missing, orphan


async def scan_workspace(
    db: Session, apply: bool = False, register_orphans: bool = False
) -> dict:
    """对比磁盘与数据库，找出外部新增 / 被改动 / 丢失的文件。

    - `changed`：磁盘文件大小与库中记录不一致 → 说明在应用外被编辑过
    - `missing`：库中有记录但磁盘文件不见了
    - `orphan` ：磁盘上有文件但库中没有记录（直接放进 data/documents 的文件）

    两个动作**刻意分开**，因为它们对知识库的影响完全不同：
    - `apply=True`：把「被改动」的文件从磁盘重新解析并重建索引 —— 安全，不改知识库结构；
    - `register_orphans=True`：把「未收录」文件**导入为新的知识库文档** —— 会改变知识库，
      因此必须由用户显式确认（目录里可能有临时文件、导出文件等，不该被静默收录）。

    同步后会重新检测一次，返回同步之后的真实状态。
    """
    docs, _disk, changed, missing, orphan = _detect(db)

    applied = {"reindexed": 0, "registered": []}
    if apply or register_orphans:
        applied = await _apply_scan(
            db,
            docs,
            changed if apply else [],
            orphan if register_orphans else [],
        )
        # 同步完成后再检测一次，报告同步后的真实差异
        _docs2, _disk2, changed, missing, orphan = _detect(db)

    return {
        "changed": changed,
        "missing": missing,
        "orphan": orphan,
        "changed_count": len(changed),
        "missing_count": len(missing),
        "orphan_count": len(orphan),
        "applied": applied,
        "note": (
            "「被改动」表示文件在应用外被编辑过，同步后会从磁盘重新解析并重建索引；"
            "「未收录」表示文件直接放进了 data/documents 但库中无记录，"
            "需显式确认后才会收录为文档。"
        ),
    }


async def _apply_scan(
    db: Session,
    docs: dict[str, Document],
    changed: list[dict],
    orphan: list[dict],
) -> dict:
    """执行同步：重建被改动文档的索引 + 收录未登记文件。"""
    from app.models.document import STATUS_PENDING
    from app.services import document_service, parsers

    if len(orphan) > MAX_REGISTER_ORPHANS:
        raise ValidationError(
            f"本次待收录文件过多（{len(orphan)} 个，上限 {MAX_REGISTER_ORPHANS} 个）："
            "一次性全部导入会长时间占用请求且可能中途失败。"
            "请分批移入文件后重试，或改用「导入文档」页上传。"
        )

    reindexed = 0
    for item in changed:
        doc = docs.get(item["file_path"])
        if not doc:
            continue
        try:
            path = files.abs_path(doc.file_path)
            parsed = parsers.parse(path, doc.file_type)
            doc.content_text = parsed.text
            doc.file_size = item["disk_size"]
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("同步文件失败 %s：%s", doc.file_path, exc)
            continue
        try:
            await document_service.reindex_document(db, doc.id)
            reindexed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("重建索引失败 %s：%s", doc.file_path, exc)

    registered: list[str] = []
    for item in orphan:
        doc = Document(
            title=item["filename"],
            original_filename=item["filename"],
            file_path=item["file_path"],
            file_type=files.ext_of(item["filename"]),
            file_size=item["size"],
            status=STATUS_PENDING,
            source="upload",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        registered.append(str(doc.id))
        # 文件已在 documents 目录内，直接建索引即可（无需再复制）
        try:
            await document_service.reindex_document(db, doc.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("收录后建索引失败 %s：%s", doc.file_path, exc)

    return {"reindexed": reindexed, "registered": registered}


# ---------------- 工作台 ----------------
def startup_scan(db: Session) -> dict | None:
    """启动时做一次**只读**扫描，把「磁盘与库不一致」的情况记下来。

    为什么值得做：在应用外（VS Code / Typora）改 `.md` 是高频场景，
    而此前必须用户自己想起来点「扫描同步」。启动时顺手扫一次，
    工作台就能提示「检测到 N 处差异」，用户再决定是否同步。

    边界：**只扫描、绝不修改**。任何改动知识库的动作（重建索引 / 收录未登记文件）
    都仍然要在「扫描同步」里由用户显式确认。失败只记日志，不影响启动。
    """
    global STARTUP_SCAN
    try:
        result = scan_workspace_sync(db)
        STARTUP_SCAN = {
            "changed_count": result["changed_count"],
            "missing_count": result["missing_count"],
            "orphan_count": result["orphan_count"],
            "scanned_at": datetime.now().isoformat(),
        }
        total = result["changed_count"] + result["missing_count"] + result["orphan_count"]
        if total:
            logger.warning(
                "启动扫描发现 %s 处磁盘与库不一致（未做任何改动）：%s", total, STARTUP_SCAN
            )
        return STARTUP_SCAN
    except Exception as exc:  # noqa: BLE001
        logger.warning("启动扫描失败（不影响使用）：%s", exc)
        return None


def scan_workspace_sync(db: Session) -> dict:
    """`scan_workspace` 的同步版本（启动时没有事件循环可直接 await 的语境）。"""
    docs, _disk, changed, missing, orphan = _detect(db)
    return {
        "changed": changed,
        "missing": missing,
        "orphan": orphan,
        "changed_count": len(changed),
        "missing_count": len(missing),
        "orphan_count": len(orphan),
    }


def workbench(db: Session) -> dict:
    """工作台汇总：最近编辑 / 最近访问 / 待整理 / 今日笔记 / 各项计数。"""
    alive = Document.deleted_at.is_(None)

    def _brief(doc: Document) -> dict:
        return {
            "id": str(doc.id),
            "title": doc.title,
            "source": doc.source,
            "status": doc.status,
            "chunk_count": doc.chunk_count,
            "category_id": str(doc.category_id) if doc.category_id else None,
            "is_favorite": doc.is_favorite,
            "is_pinned": doc.is_pinned,
            "ai_enabled": doc.ai_enabled,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "last_viewed_at": doc.last_viewed_at.isoformat() if doc.last_viewed_at else None,
        }

    recent_edited = list(
        db.execute(
            select(Document).where(alive).order_by(Document.updated_at.desc()).limit(8)
        )
        .scalars()
        .all()
    )
    recent_viewed = list(
        db.execute(
            select(Document)
            .where(alive, Document.last_viewed_at.is_not(None))
            .order_by(Document.last_viewed_at.desc())
            .limit(8)
        )
        .scalars()
        .all()
    )
    inbox = list(
        db.execute(
            select(Document)
            .where(alive, Document.category_id.is_(None))
            .order_by(Document.created_at.desc())
            .limit(8)
        )
        .scalars()
        .all()
    )
    favorites = list(
        db.execute(
            select(Document)
            .where(alive, Document.is_favorite.is_(True))
            .order_by(Document.updated_at.desc())
            .limit(8)
        )
        .scalars()
        .all()
    )

    def _count(*conds) -> int:
        return db.execute(
            select(func.count()).select_from(Document).where(*conds)
        ).scalar_one()

    counts = {
        "documents": _count(alive),
        "notes": _count(alive, Document.source == "note"),
        "favorites": _count(alive, Document.is_favorite.is_(True)),
        "inbox": _count(alive, Document.category_id.is_(None)),
        "trash": _count(Document.deleted_at.is_not(None)),
        "failed": _count(alive, Document.status == STATUS_FAILED),
        "private": _count(alive, Document.ai_enabled.is_(False)),
    }
    chunk_total = db.execute(select(func.count()).select_from(Chunk)).scalar_one()

    daily = find_daily_note(db)
    return {
        "recent_edited": [_brief(d) for d in recent_edited],
        "recent_viewed": [_brief(d) for d in recent_viewed],
        "inbox": [_brief(d) for d in inbox],
        "favorites": [_brief(d) for d in favorites],
        "counts": counts,
        "chunk_total": chunk_total,
        "daily_note": _brief(daily) if daily else None,
        "daily_title": today_title(),
        # 启动时的只读扫描结果（未做任何改动），供工作台提示"磁盘与库不一致"
        "startup_scan": STARTUP_SCAN,
    }
