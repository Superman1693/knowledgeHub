"""检索服务：封装关键词 / 语义 / 混合三种检索。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import AIUnavailableError
from app.rag.indexer import embed_query
from app.rag.retriever import hybrid_search, hybrid_search_reranked, keyword_only, semantic_only
from app.schemas.search import SearchRequest, SearchResponse


async def search(db: Session, req: SearchRequest) -> SearchResponse:
    if req.mode == "keyword":
        hits = keyword_only(
            db,
            req.query,
            req.top_k,
            req.category_id,
            req.tags,
            req.ai_only,
            req.sort,
            date_from=req.date_from,
            date_to=req.date_to,
        )
    elif req.mode == "semantic":
        vec = await embed_query(req.query)
        if vec is None:
            raise AIUnavailableError(
                "语义检索需要嵌入模型，当前不可用。请检查模型配置，或改用关键词检索。"
            )
        hits = semantic_only(
            db,
            vec,
            req.top_k,
            req.category_id,
            req.tags,
            req.ai_only,
            req.sort,
            query=req.query,
            date_from=req.date_from,
            date_to=req.date_to,
        )
    else:  # hybrid：嵌入不可用时自动降级为关键词
        vec = await embed_query(req.query)
        # 是否启用 LLM 重排序由 settings.rerank_enabled 决定；
        # 未启用时按 req.sort 排序（此前 sort 在这一路上被丢掉）
        hits = await hybrid_search_reranked(
            db,
            req.query,
            vec,
            req.top_k,
            req.category_id,
            req.tags,
            ai_only=req.ai_only,
            sort=req.sort,
            date_from=req.date_from,
            date_to=req.date_to,
        )
    return SearchResponse(query=req.query, mode=req.mode, total=len(hits), hits=hits)
