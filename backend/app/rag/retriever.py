"""RAG 检索器：关键词（pg_trgm）+ 语义（pgvector）+ 混合融合。

说明：本机 PostgreSQL 无中文分词器，因此关键词检索统一走 pg_trgm
（ILIKE 子串匹配 + similarity 相似度），语义检索走 pgvector 余弦距离。

隐私与软删除（LocalMind 规则在现有技术栈下的落地）：
- 回收站中的文档（`deleted_at` 非空）**任何检索都不返回**；
- `ai_only=True` 时额外只检索 `ai_enabled=true` 的笔记 —— AI 问答强制走这条路径，
  即「私密笔记在**检索阶段**就被排除」，而不是靠提示词提醒模型忽略。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Chunk
from app.rag.tokenize import extract_pinyin_terms, extract_terms
from app.schemas.search import SearchHit

SNIPPET_LEN = 300

# ---------------- 编辑距离容错（模糊匹配）----------------
# pg_trgm 的 word_similarity 阈值。0.3 是 pg_trgm 的默认相似度阈值，
# 实测 "respose"→"response" 能到 0.625，而 "vue"→"value" 只有 0.28 被挡掉，
# 区分度够用。
FUZZY_SIMILARITY_THRESHOLD = 0.3
# 只对 >=4 字符的纯英文词生效。短词容错后几乎能匹配任何东西
# （"go" 可容错到 got/god/gone/going…），中文词用 trgm 容错语义也不对。
FUZZY_MIN_LEN = 4
# 精确检索结果少于此数量时才回退到模糊检索。设成 3 而不是 0：
# 用户搜一个常见词时不该被模糊噪声打扰，只有「几乎搜不到」才需要容错。
FUZZY_MIN_RESULTS = 3

logger = get_logger(__name__)


@dataclass
class _Row:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    heading: str | None
    page_no: int | None
    content: str
    score: float
    parent_id: uuid.UUID | None = None
    parent_content: str | None = None
    doc_updated_at: datetime | None = None
    doc_created_at: datetime | None = None


def _attach_parents(db: Session, rows: list[_Row]) -> None:
    """为命中片段补上父块内容（父子检索用），原地修改 rows。

    检索命中「子块」，但回传给模型的是其所属「父块」—— 子块精准匹配、
    父块上下文完整。未开启父子检索时 parent_id 全为 None，此处直接跳过。
    """
    ids = {r.parent_id for r in rows if r.parent_id}
    if not ids:
        return
    contents = dict(
        db.execute(select(Chunk.id, Chunk.content).where(Chunk.id.in_(ids))).all()
    )
    for r in rows:
        if r.parent_id:
            r.parent_content = contents.get(r.parent_id)


def _build_filters(
    category_id: uuid.UUID | None,
    tags: list[str] | None,
    ai_only: bool = False,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[str, dict]:
    clauses: list[str] = []
    params: dict = {}
    # 回收站中的文档永远不参与检索
    clauses.append("d.deleted_at IS NULL")
    if ai_only:
        # 隐私：不允许 AI 读取的笔记在 SQL 层直接排除
        clauses.append("d.ai_enabled = true")
    if category_id:
        clauses.append("d.category_id = CAST(:cat AS uuid)")
        params["cat"] = str(category_id)
    if tags:
        clauses.append(
            "d.id IN (SELECT dt.document_id FROM document_tags dt "
            "JOIN tags t ON t.id = dt.tag_id WHERE t.name = ANY(:tags))"
        )
        params["tags"] = list(tags)
    # 按文档更新时间筛选区间（需求 11.4）。用闭区间，前端传当天 00:00 也能命中。
    if date_from is not None:
        clauses.append("d.updated_at >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        clauses.append("d.updated_at <= :date_to")
        params["date_to"] = date_to
    return (" AND " + " AND ".join(clauses) if clauses else ""), params


def keyword_search(
    db: Session,
    query: str,
    limit: int,
    category_id: uuid.UUID | None = None,
    tags: list[str] | None = None,
    ai_only: bool = False,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    fuzzy: bool = False,
) -> list[_Row]:
    """pg_trgm 关键词检索：多词命中计数 + 相似度排序。

    先把查询分词（中文 2-gram + 英文整词），片段命中**任一词**即召回，
    再按「命中词数」与「整体相似度」排序。
    这样自然语言问句（如「解构为什么丢失响应性」）也能命中片段，
    而不是要求整句话作为子串出现。

    另外把「看起来是拼音」的词项单独挑出来匹配 `pinyin` / `pinyin_initials`
    两列（见 `app/rag/pinyin.py`）。刻意分成两个词集而不是混在一起：
    英文词（如 `go`）若也拿去匹配拼音列，会命中 `gong` 的全拼造成假阳性。

    `fuzzy=True` 时额外开启编辑距离容错（拼错的英文单词也能命中）。
    刻意**不作为默认分支**：模糊匹配噪声大（`go` 能容错到 `gong`/`got`/`god`），
    常开会让正常搜索结果里混入一堆不相关片段。
    由上层在「精确检索结果不足」时才回退开启，见 `keyword_only`。
    """
    terms = extract_terms(query)
    if not terms:
        return []

    pinyin_terms = extract_pinyin_terms(query)
    filt, params = _build_filters(category_id, tags, ai_only, date_from, date_to)

    # 模糊分支：只对「够长的英文词」生效。
    # 短词（<=3 字符）容错后几乎能匹配任何东西，中文词用 trgm 容错语义也不对。
    fuzzy_terms = (
        [t for t in terms if len(t) >= FUZZY_MIN_LEN and t.isascii() and t.isalpha()]
        if fuzzy
        else []
    )

    fuzzy_clause = ""
    if fuzzy_terms:
        fuzzy_clause = f"""
            OR EXISTS (
                SELECT 1 FROM fq
                 WHERE word_similarity(fq.term, c.content || ' ' || coalesce(c.heading, ''))
                       > :fuzzy_threshold
            )"""
    fuzzy_cte = (
        ", fq AS (SELECT unnest(CAST(:fterms AS text[])) AS term)" if fuzzy_terms else ""
    )
    sql = text(
        f"""
        WITH q AS (SELECT unnest(CAST(:terms AS text[])) AS term),
             pq AS (SELECT unnest(CAST(:pterms AS text[])) AS term){fuzzy_cte}
        SELECT c.id AS chunk_id, c.document_id, d.title, c.heading, c.page_no, c.content,
               c.parent_id, d.updated_at AS doc_updated_at, d.created_at AS doc_created_at,
               ((SELECT count(*) FROM q
                  WHERE c.content ILIKE '%' || q.term || '%'
                     OR c.heading  ILIKE '%' || q.term || '%')
                +
                (SELECT count(*) FROM pq
                  WHERE c.pinyin          ILIKE '%' || pq.term || '%'
                     OR c.pinyin_initials ILIKE '%' || pq.term || '%')
                +
                -- 标题命中单独计数：用户按文档名找资料时（搜「Harness」想找
                -- Harness.md），标题才是最强的意图信号，权重应高于正文偶遇。
                (SELECT count(*) FROM q
                  WHERE d.title ILIKE '%' || q.term || '%') * 2) AS hit_terms,
               similarity(c.content, :q) AS sim
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        -- ⚠️ 所有 EXISTS 必须整体括起来：SQL 里 `A OR B AND C` 等于 `A OR (B AND C)`，
        -- 不括的话正文命中会绕过 {filt}——那是隐私过滤（ai_enabled）与
        -- 回收站/日期过滤所在的地方，等于把私密笔记和已删除笔记泄漏给检索结果。
        WHERE (
            EXISTS (
                SELECT 1 FROM q
                 WHERE c.content ILIKE '%' || q.term || '%'
                    OR c.heading  ILIKE '%' || q.term || '%'
            )
            OR EXISTS (
                SELECT 1 FROM pq
                 WHERE c.pinyin          ILIKE '%' || pq.term || '%'
                    OR c.pinyin_initials ILIKE '%' || pq.term || '%'
            )
            -- 标题命中：文档标题不在 chunks.content 里，此前搜标题里的独有词
            -- （如 Harness.md 的「Harness」）完全搜不到——用户按名字找资料
            -- 这个最基本场景是断的。
            OR EXISTS (
                SELECT 1 FROM q WHERE d.title ILIKE '%' || q.term || '%'
            ){fuzzy_clause}
        )
        -- 父块是子块内容的拼接，不参与检索，否则同一段内容会命中两次
        AND c.id NOT IN (SELECT parent_id FROM chunks WHERE parent_id IS NOT NULL)
        {filt}
        ORDER BY hit_terms DESC, sim DESC
        LIMIT :lim
        """
    )
    params.update(
        {
            "terms": terms,
            "pterms": pinyin_terms,
            "fterms": fuzzy_terms,
            "fuzzy_threshold": FUZZY_SIMILARITY_THRESHOLD,
            "q": query,
            "lim": limit,
        }
    )
    rows = db.execute(sql, params).mappings().all()

    total_terms = len(terms)
    out = [
        _Row(
            chunk_id=r["chunk_id"],
            document_id=r["document_id"],
            title=r["title"],
            heading=r["heading"],
            page_no=r["page_no"],
            content=r["content"],
            # 命中词占比（0~1）+ 整体相似度（0~1）
            score=float(r["hit_terms"]) / total_terms + float(r["sim"] or 0.0),
            parent_id=r["parent_id"],
            doc_updated_at=r["doc_updated_at"],
            doc_created_at=r["doc_created_at"],
        )
        for r in rows
    ]
    _attach_parents(db, out)
    return out


def semantic_search(
    db: Session,
    query_vec: list[float],
    limit: int,
    category_id: uuid.UUID | None = None,
    tags: list[str] | None = None,
    ai_only: bool = False,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[_Row]:
    """pgvector 语义检索：余弦距离排序。"""
    filt, params = _build_filters(category_id, tags, ai_only, date_from, date_to)
    vec_literal = "[" + ",".join(f"{x:.8f}" for x in query_vec) + "]"
    sql = text(
        f"""
        SELECT c.id AS chunk_id, c.document_id, d.title, c.heading, c.page_no, c.content,
               c.parent_id, d.updated_at AS doc_updated_at, d.created_at AS doc_created_at,
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
    out = [
        _Row(
            chunk_id=r["chunk_id"],
            document_id=r["document_id"],
            title=r["title"],
            heading=r["heading"],
            page_no=r["page_no"],
            content=r["content"],
            score=float(r["sim"] or 0.0),
            parent_id=r["parent_id"],
            doc_updated_at=r["doc_updated_at"],
            doc_created_at=r["doc_created_at"],
        )
        for r in rows
    ]
    _attach_parents(db, out)
    return out


def _normalize(rows: list[_Row]) -> dict[uuid.UUID, float]:
    """把分数归一化到 0..1。"""
    if not rows:
        return {}
    scores = [r.score for r in rows]
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return {r.chunk_id: 1.0 for r in rows}
    return {r.chunk_id: (r.score - lo) / (hi - lo) for r in rows}


def _highlights(
    content: str, heading: str | None, terms: list[str], title: str | None = None
) -> list[str]:
    """列出该片段实际命中的查询词（前端据此在 snippet 与标题里高亮）。

    标题也参与：标题命中现在能召回片段，若不高亮，用户看到结果会不明白
    为什么这篇被召回来。
    """
    haystack = f"{content or ''}\n{heading or ''}\n{title or ''}".lower()
    return [t for t in terms if t and t.lower() in haystack]


def _to_hit(
    row: _Row,
    score: float,
    kw: float | None,
    sem: float | None,
    terms: list[str] | None = None,
) -> SearchHit:
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
        parent_id=row.parent_id,
        parent_content=row.parent_content,
        highlights=_highlights(row.content, row.heading, terms or [], row.title),
        document_updated_at=row.doc_updated_at,
        document_created_at=row.doc_created_at,
    )


def _dedupe_by_parent(hits: list[SearchHit]) -> list[SearchHit]:
    """父子检索去重：同一父块下的多个子块只保留得分最高的一条。

    hits 已按得分降序排列，故首次出现的即为该父块的最佳命中。
    不去重的话，一个父块会被重复回传，白白占用模型上下文。
    """
    seen: set[uuid.UUID] = set()
    out: list[SearchHit] = []
    for h in hits:
        key = h.parent_id or h.chunk_id
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def _ts(value: datetime | None) -> float:
    """安全的时间戳转换（None → 0）。"""
    try:
        return value.timestamp() if value else 0.0
    except (ValueError, OSError):  # pragma: no cover - 极端时区数据
        return 0.0


def _apply_sort(hits: list[SearchHit], sort: str) -> list[SearchHit]:
    """按时间重排；sort=relevance 时保持原有的相关度顺序。"""
    if sort == "updated":
        hits.sort(key=lambda h: _ts(h.document_updated_at), reverse=True)
    elif sort == "created":
        hits.sort(key=lambda h: _ts(h.document_created_at), reverse=True)
    return hits


def hybrid_search(
    db: Session,
    query: str,
    query_vec: list[float] | None,
    top_k: int | None = None,
    category_id: uuid.UUID | None = None,
    tags: list[str] | None = None,
    alpha: float | None = None,
    beta: float | None = None,
    ai_only: bool = False,
    sort: str = "relevance",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[SearchHit]:
    """混合检索：关键词 + 语义按权重融合。"""
    k = top_k or settings.search_top_k
    a = alpha if alpha is not None else settings.hybrid_alpha
    b = beta if beta is not None else settings.hybrid_beta

    pool = max(k * 3, 20)
    kw_rows = keyword_search(db, query, pool, category_id, tags, ai_only, date_from, date_to)
    sem_rows = (
        semantic_search(db, query_vec, pool, category_id, tags, ai_only, date_from, date_to)
        if query_vec
        else []
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
    terms = extract_terms(query)
    # 先去重再截断：否则同一父块的多个子块会挤占 top-k 名额
    hits = [_to_hit(row, score, kw, sem, terms) for score, row, kw, sem in scored]
    deduped = _dedupe_by_parent(hits)
    return _apply_sort(deduped[:k], sort)


async def hybrid_search_reranked(
    db: Session,
    query: str,
    query_vec: list[float] | None,
    top_k: int | None = None,
    category_id: uuid.UUID | None = None,
    tags: list[str] | None = None,
    ai_only: bool = False,
    sort: str = "relevance",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[SearchHit]:
    """混合检索 + LLM 重排序。重排失败时静默回退到原始排序。

    取回比 top_k 更多的候选（`rerank_candidates`），交给模型按相关性重排后截断。
    仅当 `settings.rerank_enabled` 为 True 时才调用对话模型。

    注意 `sort`：**未启用重排时必须按 `sort` 排序**——此前这里没有把 sort 传下去，
    于是默认的 hybrid 模式下「按更新时间/创建时间排序」完全失效（静默忽略参数）。
    启用重排时以模型给出的相关性顺序为准。
    """
    k = top_k or settings.search_top_k
    candidate_count = max(k, settings.rerank_candidates)
    hits = hybrid_search(
        db,
        query,
        query_vec,
        candidate_count,
        category_id,
        tags,
        ai_only=ai_only,
        sort=sort,
        date_from=date_from,
        date_to=date_to,
    )
    if len(hits) <= 1 or not settings.rerank_enabled:
        return hits[:k]

    from app.ai.factory import get_provider
    from app.rag.reranker import rerank

    candidates = [h.model_dump(mode="json") for h in hits]
    try:
        ranked_dicts = await rerank(query, candidates, get_provider(), k)
        from app.schemas.search import SearchHit as _SH

        return [_SH.model_validate(d) for d in ranked_dicts]
    except Exception as exc:  # noqa: BLE001
        logger.warning("重排序异常，回退原始排序：%s", exc)
        return hits[:k]


def keyword_only(
    db: Session,
    query: str,
    top_k: int,
    category_id=None,
    tags=None,
    ai_only: bool = False,
    sort: str = "relevance",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[SearchHit]:
    """关键词检索（对外入口）：精确优先，结果不足时回退到模糊匹配。

    **两阶段而不是常开模糊**：模糊匹配噪声大（`go` 能容错到 `got`/`god`/`gone`），
    常开会让正常搜索结果混入一堆不相关片段。所以先用精确检索，
    只有结果少到「用户基本等于什么都没搜到」时才启用容错——
    这正是「打错一个字母」的典型场景。
    """
    terms = extract_terms(query)

    def _run(fuzzy: bool) -> list[_Row]:
        return keyword_search(
            db,
            query,
            max(top_k * 3, top_k + 10),
            category_id,
            tags,
            ai_only,
            date_from,
            date_to,
            fuzzy=fuzzy,
        )

    rows = _run(fuzzy=False)
    if len(rows) < FUZZY_MIN_RESULTS:
        # 去重：模糊命中的片段若精确检索已召回，不重复计入
        seen = {r.chunk_id for r in rows}
        extra = [r for r in _run(fuzzy=True) if r.chunk_id not in seen]
        rows = rows + extra

    norm = _normalize(rows)
    hits = [_to_hit(r, norm.get(r.chunk_id, r.score), r.score, None, terms) for r in rows]
    return _apply_sort(_dedupe_by_parent(hits)[:top_k], sort)


def semantic_only(
    db: Session,
    query_vec: list[float],
    top_k: int,
    category_id=None,
    tags=None,
    ai_only: bool = False,
    sort: str = "relevance",
    query: str = "",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[SearchHit]:
    terms = extract_terms(query) if query else []
    rows = semantic_search(
        db, query_vec, max(top_k * 3, top_k + 10), category_id, tags, ai_only, date_from, date_to
    )
    norm = _normalize(rows)
    hits = [_to_hit(r, norm.get(r.chunk_id, r.score), None, r.score, terms) for r in rows]
    return _apply_sort(_dedupe_by_parent(hits)[:top_k], sort)
