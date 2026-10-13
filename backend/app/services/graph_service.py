"""知识图谱服务：把「笔记 + 双向链接 + 标签」组装成可可视化的图。

对应 LocalMind「知识关系图谱：按笔记、标签和引用展示关系网络」。

设计要点：
- **节点**是未删除的文档；**边**有两种：
  - `link`：来自 `note_links` 的显式双向链接（只取两端都解析成功的）；
  - `tag` ：共享标签的文档之间连边（可选，`weight` = 共享标签数），用于发现「没有显式引用
    但主题相近」的笔记。
- 支持**以某篇笔记为中心**取二度子图（ego graph），避免整库节点过多时图不可读。
- 节点带 `degree`（度数），前端据此调整半径，让「枢纽笔记」一眼可见。
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Document, NoteLink, Tag, document_tags

MAX_NODES = 400
MAX_TAG_EDGES = 400
# 共享标签配对的总数上限：单个热门标签（如 400 篇文档）两两配对会产生约 8 万条边，
# 旧实现是「先全量配对、再截断」，大库下会直接卡死。这里边算边判上限，超限即停。
MAX_TAG_PAIRS = 20000


def _load_nodes(db: Session) -> dict[uuid.UUID, dict]:
    rows = db.execute(
        select(
            Document.id,
            Document.title,
            Document.source,
            Document.category_id,
            Document.chunk_count,
            Document.ai_enabled,
            Document.updated_at,
        ).where(Document.deleted_at.is_(None))
    ).all()
    cats = dict(db.execute(select(Category.id, Category.name)).all())
    return {
        r[0]: {
            "id": str(r[0]),
            "title": r[1],
            "source": r[2],
            "category_id": str(r[3]) if r[3] else None,
            "category_name": cats.get(r[3]) if r[3] else None,
            "chunk_count": r[4] or 0,
            "ai_enabled": bool(r[5]),
            "updated_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    }


def _link_edges(db: Session, valid: set[uuid.UUID]) -> list[dict]:
    rows = db.execute(
        select(NoteLink.source_document_id, NoteLink.target_document_id).where(
            NoteLink.target_document_id.is_not(None)
        )
    ).all()
    edges: list[dict] = []
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for src, dst in rows:
        if src not in valid or dst not in valid or src == dst:
            continue
        key = (min(src, dst), max(src, dst))
        if key in seen:
            continue
        seen.add(key)
        edges.append({"source": str(src), "target": str(dst), "kind": "link", "weight": 1})
    return edges


def _tag_edges(db: Session, valid: set[uuid.UUID]) -> list[dict]:
    """共享标签的文档两两连边（按共享标签数计权重），带上限避免爆炸。"""
    rows = db.execute(
        select(document_tags.c.document_id, document_tags.c.tag_id)
    ).all()
    tag_docs: dict[uuid.UUID, set[uuid.UUID]] = {}
    for doc_id, tag_id in rows:
        if doc_id in valid:
            tag_docs.setdefault(tag_id, set()).add(doc_id)

    pairs: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    truncated = False
    # 按 tag_id 排序，保证每次请求的配对顺序确定（否则截断结果不可复现）
    for tag_id in sorted(tag_docs, key=str):
        ordered = sorted(tag_docs[tag_id], key=str)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                key = (ordered[i], ordered[j])
                pairs[key] = pairs.get(key, 0) + 1
                if len(pairs) >= MAX_TAG_PAIRS:
                    truncated = True
                    break
            if truncated:
                break
        if truncated:
            break
    if truncated:
        logger.warning(
            "共享标签配对达到上限 %s（节点过多），图谱的标签边已被截断", MAX_TAG_PAIRS
        )

    edges = [
        {"source": str(a), "target": str(b), "kind": "tag", "weight": w}
        for (a, b), w in sorted(pairs.items(), key=lambda kv: -kv[1])[:MAX_TAG_EDGES]
    ]
    return edges


def _ego_subset(
    focus: uuid.UUID, edges: list[dict], depth: int = 2
) -> set[uuid.UUID]:
    """从中心节点出发的 BFS 子图（默认二度）。"""
    adjacency: dict[str, set[str]] = {}
    for e in edges:
        adjacency.setdefault(e["source"], set()).add(e["target"])
        adjacency.setdefault(e["target"], set()).add(e["source"])

    keep = {str(focus)}
    frontier = {str(focus)}
    for _ in range(depth):
        nxt: set[str] = set()
        for node in frontier:
            nxt |= adjacency.get(node, set())
        nxt -= keep
        keep |= nxt
        frontier = nxt
        if not frontier:
            break
    return {uuid.UUID(x) for x in keep}


def build_graph(
    db: Session,
    focus_id: uuid.UUID | None = None,
    include_tags: bool = False,
    limit: int = MAX_NODES,
) -> dict:
    """构建图谱数据。"""
    nodes = _load_nodes(db)
    if not nodes:
        return {"nodes": [], "edges": [], "stats": {"node_count": 0, "edge_count": 0}}

    edges = _link_edges(db, set(nodes.keys()))
    if include_tags:
        edges += _tag_edges(db, set(nodes.keys()))

    if focus_id is not None and focus_id in nodes:
        keep = _ego_subset(focus_id, edges)
        # 中心节点本身可能没有任何边，也要保留
        keep.add(focus_id)
    else:
        # 无中心时按更新时间取最近 limit 个节点，再保留集合内部的边
        ranked = sorted(
            nodes.values(), key=lambda n: n["updated_at"] or "", reverse=True
        )[: max(1, min(limit, MAX_NODES))]
        keep = {uuid.UUID(n["id"]) for n in ranked}

    edges = [e for e in edges if uuid.UUID(e["source"]) in keep and uuid.UUID(e["target"]) in keep]

    degree: dict[str, int] = {}
    for e in edges:
        degree[e["source"]] = degree.get(e["source"], 0) + 1
        degree[e["target"]] = degree.get(e["target"], 0) + 1

    out_nodes = []
    for nid in keep:
        node = nodes.get(nid)
        if not node:
            continue
        node = dict(node)
        node["degree"] = degree.get(node["id"], 0)
        out_nodes.append(node)

    isolated = [n for n in out_nodes if n["degree"] == 0]
    return {
        "nodes": out_nodes,
        "edges": edges,
        "stats": {
            "node_count": len(out_nodes),
            "edge_count": len(edges),
            "link_edges": len([e for e in edges if e["kind"] == "link"]),
            "tag_edges": len([e for e in edges if e["kind"] == "tag"]),
            "isolated": len(isolated),
            "focus_id": str(focus_id) if focus_id else None,
            "include_tags": include_tags,
        },
    }
