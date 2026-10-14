"""知识库体检：把「存了没用」的内容显形。

## 为什么需要它

调研里最扎心的一句是「知识库的价值取决于复用，不取决于笔记数量」。
但笔记软件普遍只告诉你**存了多少**，不告诉你**有多少在用**。
重复检测（`find_duplicates`）已经能发现「存重了」，缺的是另一半：

- **孤立笔记**：零入链 + 零出链。它在双链图和知识图谱里是个孤点，
  既不会被人顺着链接逛到，也不会出现在任何「相关笔记」里——存了等于没存。
- **从未访问**：导入之后再没打开过。
- **未分类堆积**：收集箱里躺太久，说明「先收着以后再整理」的以后再没来。
- **索引异常**：状态失败或零片段，这些内容**根本搜不到**。
- **悬空链接**：指向不存在笔记的 `[[双链]]`，是没写完的坑。

刻意**只报告不自动处理**：孤立不代表该删（可能只是还没建立关联），
自动归档或删除是不可逆的误判。体检的价值是让人看见，处置权留给用户。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_logger

logger = get_logger(__name__)

# 收集箱里的文档超过这么多天仍未分类，算「堆积」
STALE_INBOX_DAYS = 14
# 各类清单最多返回多少条（详情让用户去对应页面看）
MAX_ITEMS = 20


def _row_to_brief(r: dict) -> dict:
    return {
        "document_id": str(r["id"]),
        "title": r["title"],
        "source": r.get("source"),
        "chunk_count": r.get("chunk_count"),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
        "last_viewed_at": (
            r["last_viewed_at"].isoformat() if r.get("last_viewed_at") else None
        ),
        "days_since_created": (
            (datetime.now(timezone.utc) - r["created_at"]).days
            if r.get("created_at")
            else None
        ),
    }


def _orphans(db: Session, limit: int = MAX_ITEMS) -> list[dict]:
    """孤立笔记：既没有出链也没有入链（未删除）。

    两个 NOT EXISTS 分别对应「本笔记引用了谁」和「谁引用了本笔记」。
    ⚠️ 入链要查 `target_document_id` 而不是 `target_title`——请按文档 ID 关联，
    标题可能因改名而变，按标题查会把已改名的关联误判成孤立。
    """
    rows = db.execute(
        text(
            """
            SELECT d.id, d.title, d.source, d.chunk_count,
                   d.created_at, d.updated_at, d.last_viewed_at
            FROM documents d
            WHERE d.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM note_links l WHERE l.source_document_id = d.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM note_links l WHERE l.target_document_id = d.id
              )
            ORDER BY d.created_at ASC
            LIMIT :lim
            """
        ),
        {"lim": limit},
    ).mappings().all()
    return [_row_to_brief(dict(r)) for r in rows]


def _never_viewed(db: Session, limit: int = MAX_ITEMS) -> list[dict]:
    """从未打开过的文档。

    `last_viewed_at` 为空有两种情况：刚建还没点开、或导入后一直没看。
    这里只报「创建已超过 1 天」的，避免刚建完就报一堆。
    """
    rows = db.execute(
        text(
            """
            SELECT d.id, d.title, d.source, d.chunk_count,
                   d.created_at, d.updated_at, d.last_viewed_at
            FROM documents d
            WHERE d.deleted_at IS NULL
              AND d.last_viewed_at IS NULL
              AND d.created_at < :cutoff
            ORDER BY d.created_at ASC
            LIMIT :lim
            """
        ),
        {"cutoff": datetime.now(timezone.utc) - timedelta(days=1), "lim": limit},
    ).mappings().all()
    return [_row_to_brief(dict(r)) for r in rows]


def _stale_inbox(db: Session, limit: int = MAX_ITEMS) -> list[dict]:
    """收集箱里躺太久的未分类文档。"""
    rows = db.execute(
        text(
            """
            SELECT d.id, d.title, d.source, d.chunk_count,
                   d.created_at, d.updated_at, d.last_viewed_at
            FROM documents d
            WHERE d.deleted_at IS NULL
              AND d.category_id IS NULL
              AND d.created_at < :cutoff
            ORDER BY d.created_at ASC
            LIMIT :lim
            """
        ),
        {
            "cutoff": datetime.now(timezone.utc) - timedelta(days=STALE_INBOX_DAYS),
            "lim": limit,
        },
    ).mappings().all()
    return [_row_to_brief(dict(r)) for r in rows]


def _unindexed(db: Session, limit: int = MAX_ITEMS) -> list[dict]:
    """索引异常：状态失败，或零片段（等于搜不到）。

    这类问题最隐蔽——用户在搜索框里怎么搜都没有，却不知道是内容没被索引。
    """
    rows = db.execute(
        text(
            """
            SELECT d.id, d.title, d.source, d.chunk_count,
                   d.created_at, d.updated_at, d.last_viewed_at,
                   d.status, d.error_message
            FROM documents d
            WHERE d.deleted_at IS NULL
              AND (d.status = 'failed' OR d.chunk_count = 0)
            ORDER BY d.created_at ASC
            LIMIT :lim
            """
        ),
        {"lim": limit},
    ).mappings().all()
    out = []
    for r in rows:
        item = _row_to_brief(dict(r))
        item["status"] = r["status"]
        item["error_message"] = r["error_message"]
        out.append(item)
    return out


def _dangling(db: Session, limit: int = MAX_ITEMS) -> list[dict]:
    """悬空链接：指向不存在的笔记（`[[标题]]` 写了但目标没建）。

    这些是没写完的坑，通常意味着「本打算写但忘了」。
    """
    rows = db.execute(
        text(
            """
            SELECT l.target_title, sd.id AS source_id, sd.title AS source_title
            FROM note_links l
            JOIN documents sd ON sd.id = l.source_document_id
            WHERE l.target_document_id IS NULL
              AND sd.deleted_at IS NULL
            ORDER BY l.target_title ASC
            LIMIT :lim
            """
        ),
        {"lim": limit},
    ).mappings().all()
    return [
        {
            "target_title": r["target_title"],
            "source_document_id": str(r["source_id"]),
            "source_document_title": r["source_title"],
        }
        for r in rows
    ]


def health(db: Session, duplicate_threshold: float = 0.10) -> dict:
    """知识库体检汇总。

    刻意同时返回**计数**与**前 N 条清单**：计数用于一眼判断「要不要管」，
    清单用于「具体是哪几篇」。全量清单没必要（详情在各自页面已有）。
    """
    counters = db.execute(
        text(
            """
            SELECT
              (SELECT count(*) FROM documents WHERE deleted_at IS NULL) AS total,
              (SELECT count(*) FROM documents
                WHERE deleted_at IS NULL AND last_viewed_at IS NULL) AS never_viewed_total,
              (SELECT count(*) FROM documents
                WHERE deleted_at IS NULL AND category_id IS NULL) AS inbox_total,
              (SELECT count(*) FROM documents
                WHERE deleted_at IS NULL AND (status = 'failed' OR chunk_count = 0)
              ) AS unindexed_total,
              (SELECT count(*) FROM note_links l
                JOIN documents sd ON sd.id = l.source_document_id
                WHERE l.target_document_id IS NULL AND sd.deleted_at IS NULL
              ) AS dangling_total,
              (SELECT count(*) FROM documents d
                WHERE d.deleted_at IS NULL
                  AND NOT EXISTS (SELECT 1 FROM note_links l
                                  WHERE l.source_document_id = d.id)
                  AND NOT EXISTS (SELECT 1 FROM note_links l
                                  WHERE l.target_document_id = d.id)
              ) AS orphan_total,
              (SELECT count(*) FROM documents
                WHERE deleted_at IS NULL AND is_favorite) AS favorite_total,
              -- 收集箱里的陈旧文档数：单独 count，不能用清单长度代替
              -- （清单被 MAX_ITEMS 截断，会永远显示最多 20）
              (SELECT count(*) FROM documents
                WHERE deleted_at IS NULL AND category_id IS NULL
                  AND created_at < :stale_cutoff) AS stale_inbox_total
            """
        ),
        {
            "stale_cutoff": datetime.now(timezone.utc)
            - timedelta(days=STALE_INBOX_DAYS)
        },
    ).mappings().one()

    total = counters["total"] or 0
    # 重复对复用已有实现，但只在这里给「数量」——详情走 /insights/duplicates，
    # 那是向量计算，比其它几项贵得多，不该被体检接口拖慢
    try:
        from app.services.insight_service import find_duplicates

        duplicate_total = len(find_duplicates(db, threshold=duplicate_threshold, limit=50))
    except Exception as exc:  # noqa: BLE001
        # 嵌入不可用时重复检测会失败；体检的其它项仍应可用
        logger.warning("体检中的重复检测失败（其余项不受影响）：%s", exc)
        duplicate_total = None

    orphan_total = counters["orphan_total"] or 0
    return {
        "summary": {
            "total": total,
            "orphans": orphan_total,
            "never_viewed": counters["never_viewed_total"] or 0,
            "inbox": counters["inbox_total"] or 0,
            "stale_inbox": counters["stale_inbox_total"] or 0,
            "unindexed": counters["unindexed_total"] or 0,
            "dangling_links": counters["dangling_total"] or 0,
            "favorites": counters["favorite_total"] or 0,
            "duplicate_pairs": duplicate_total,
            # 关联率：有多少文档至少参与了一条双链。孤立笔记越多这个值越低。
            "linked_ratio": (
                round((total - orphan_total) / total, 4) if total else None
            ),
        },
        "orphans": _orphans(db),
        "never_viewed": _never_viewed(db),
        "stale_inbox": _stale_inbox(db),
        "unindexed": _unindexed(db),
        "dangling": _dangling(db),
        "thresholds": {"stale_inbox_days": STALE_INBOX_DAYS},
        "note": (
            "体检只报告不自动处理：孤立不代表该删（可能只是还没建立关联），"
            "自动归档或删除属不可逆的误判。处置权留给你。"
        ),
    }
