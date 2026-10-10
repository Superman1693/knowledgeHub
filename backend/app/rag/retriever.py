"""RAG 检索器：关键词（pg_trgm）+ 语义（pgvector）+ 混合融合。

说明：本机 PostgreSQL 无中文分词器，因此关键词检索统一走 pg_trgm
（ILIKE 子串匹配 + similarity 相似度），语义检索走 pgvector 余弦距离。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.tokenize import extract_terms
from app.schemas.search import SearchHit

SNIPPET_LEN = 300


@dataclass
class _Row:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    heading: str | None
    page_no: int | None
    content: str
    score: float


def _build_filters(
    category_id: uuid.UUID | None, tags: list[str] | None
) -> tuple[str, dict]:
    clauses: list[str] = []
    params: dict = {}
    if category_id:
        clauses.append("d.category_id = CAST(:cat AS uuid)")
        params["cat"] = str(category_id)
    if tags:
        clauses.append(
            "d.id IN (SELECT dt.document_id FROM document_tags dt "
            "JOIN tags t ON t.id = dt.tag_id WHERE t.name = ANY(:tags))"
        )
        params["tags"] = list(tags)
    return (" AND " + " AND ".join(clauses) if clauses else ""), params


def keyword_search(
    db: Session,
    query: str,
    limit: int,
    category_id: uuid.UUID | None = None,
    tags: list[str] | None = None,
) -> list[_Row]:
    """pg_trgm 关键词检索：多词命中计数 + 相似度排序。

    先把查询分词（中文 2-gram + 英文整词），片段命中**任一词**即召回，
    再按「命中词数」与「整体相似度」排序。
    这样自然语言问句（如「解构为什么丢失响应性」）也能命中片段，
    而不是要求整句话作为子串出现。
    """
    terms = extract_terms(query)
    if not terms:
        return []

    filt, params = _build_filters(category_id, tags)
    sql = text(
        f"""
        WITH q AS (SELECT unnest(CAST(:terms AS text[])) AS term)
        SELECT c.id AS chunk_id, c.document_id, d.title, c.heading, c.page_no, c.content,
               (SELECT count(*) FROM q
                 WHERE c.content ILIKE '%' || q.term || '%'
                    OR c.heading  ILIKE '%' || q.term || '%') AS hit_terms,
               similarity(c.content, :q) AS sim
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE EXISTS (
            SELECT 1 FROM q
             WHERE c.content ILIKE '%' || q.term || '%'
                OR c.heading  ILIKE '%' || q.term || '%'
        )
        {filt}
        ORDER BY hit_terms DESC, sim DESC
        LIMIT :lim
        """
    )
    params.update({"terms": terms, "q": query, "lim": limit})
    rows = db.execute(sql, params).mappings().all()

    total_terms = len(terms)
    return [
        _Row(
            chunk_id=r["chunk_id"],
            document_id=r["document_id"],
            title=r["title"],
            heading=r["heading"],
            page_no=r["page_no"],
            content=r["content"],
            # 命中词占比（0~1）+ 整体相似度（0~1）
            score=float(r["hit_terms"]) / total_terms + float(r["sim"] or 0.0),
        )
        for r in rows
    ]


def semantic_search(
    db: Session,
    query_vec: list[float],
    limit: int,
    category_id: uuid.UUID | None = None,
    tags: list[str] | None = None,
) -> list[_Row]:
    """pgvector 语义检索：余弦距离排序。"""
    filt, params = _build_filters(category_id, tags)
    vec_literal = "[" + ",".join(f"{x:.8f}" for x in query_vec) + "]"
    sql = text(
        f"""
        SELECT c.id AS chunk_id, c.document_id, d.title, c.heading, c.page_no, c.content,
               1 - (c.embedding <=> CAST(:vec AS vector)) AS sim
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.embedding IS NOT NULL
        {filt}
        ORDER BY c.embedding <=> CAST(:vec AS vector)
        LIMIT :lim
        """
    )
    params.update({"vec": vec_literal, "lim": limit})
    rows = db.execute(sql, params).mappings().all()
    return [
        _Row(
            chunk_id=r["chunk_id"],
            document_id=r["document_id"],
            title=r["title"],
            heading=r["heading"],
            page_no=r["page_no"],
            content=r["content"],
            score=float(r["sim"] or 0.0),
        )
        for r in rows
    ]


def _normalize(rows: list[_Row]) -> dict[uuid.UUID, float]:
    """把分数归一化到 0..1。"""
    if not rows:
        return {}
    scores = [r.score for r in rows]
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return {r.chunk_id: 1.0 for r in rows}
    return {r.chunk_id: (r.score - lo) / (hi - lo) for r in rows}


def _to_hit(row: _Row, score: float, kw: float | None, sem: float | None) -> SearchHit:
    snippet = row.content.strip().replace("\n", " ")
    if len(snippet) > SNIPPET_LEN:
        snippet = snippet[:SNIPPET_LEN] + "…"
    return SearchHit(
        document_id=row.document_id,
        document_title=row.title,
        chunk_id=row.chunk_id,
        heading=row.heading,
        page_no=row.page_no,
        snippet=snippet,
        score=round(score, 4),
        keyword_score=round(kw, 4) if kw is not None else None,
        semantic_score=round(sem, 4) if sem is not None else None,
    )


def hybrid_search(
    db: Session,
    query: str,
    query_vec: list[float] | None,
    top_k: int | None = None,
    category_id: uuid.UUID | None = None,
    tags: list[str] | None = None,
    alpha: float | None = None,
    beta: float | None = None,
) -> list[SearchHit]:
    """混合检索：关键词 + 语义按权重融合。"""
    k = top_k or settings.search_top_k
    a = alpha if alpha is not None else settings.hybrid_alpha
    b = beta if beta is not None else settings.hybrid_beta

    pool = max(k * 3, 20)
    kw_rows = keyword_search(db, query, pool, category_id, tags)
    sem_rows = (
        semantic_search(db, query_vec, pool, category_id, tags) if query_vec else []
    )

    kw_norm = _normalize(kw_rows)
    sem_norm = _normalize(sem_rows)

    by_id: dict[uuid.UUID, _Row] = {}
    for r in kw_rows + sem_rows:
        by_id.setdefault(r.chunk_id, r)

    scored: list[tuple[float, _Row, float | None, float | None]] = []
    for cid, row in by_id.items():
        kw = kw_norm.get(cid)
        sem = sem_norm.get(cid)
        score = a * (kw or 0.0) + b * (sem or 0.0)
        scored.append((score, row, kw, sem))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [_to_hit(row, score, kw, sem) for score, row, kw, sem in scored[:k]]


def keyword_only(
    db: Session, query: str, top_k: int, category_id=None, tags=None
) -> list[SearchHit]:
    rows = keyword_search(db, query, top_k, category_id, tags)
    norm = _normalize(rows)
    return [_to_hit(r, norm.get(r.chunk_id, r.score), r.score, None) for r in rows]


def semantic_only(
    db: Session, query_vec: list[float], top_k: int, category_id=None, tags=None
) -> list[SearchHit]:
    rows = semantic_search(db, query_vec, top_k, category_id, tags)
    norm = _normalize(rows)
    return [_to_hit(r, norm.get(r.chunk_id, r.score), None, r.score) for r in rows]
