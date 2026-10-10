"""向量索引构建：分块 → 嵌入 → 写入 chunks。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.factory import get_embedding_provider
from app.core.config import settings
from app.core.exceptions import AIUnavailableError, EmbeddingUnavailableError
from app.core.logging import get_logger
from app.models import Chunk, Document
from app.rag.chunker import chunk_document
from app.services.parsers import ParsedDocument

logger = get_logger(__name__)


async def build_index(db: Session, document: Document, parsed: ParsedDocument) -> int:
    """为文档构建/重建向量索引，返回片段数。

    嵌入失败时：仍保留片段（关键词检索可用），但抛出异常由上层标记为 failed。
    """
    # 1) 清理旧片段（重建场景）
    db.query(Chunk).filter(Chunk.document_id == document.id).delete()
    db.flush()

    # 2) 分块
    chunks = chunk_document(parsed.text, parsed.pages or None)
    if not chunks:
        return 0

    # 3) 生成嵌入（可能失败）
    vectors: list[list[float]] | None = None
    embed_error: str | None = None
    try:
        provider = get_embedding_provider()
        vectors = await provider.embed([c.content for c in chunks])
        if vectors and len(vectors[0]) != settings.embedding_dim:
            embed_error = (
                f"嵌入维度不匹配：模型返回 {len(vectors[0])} 维，"
                f"配置 EMBEDDING_DIM={settings.embedding_dim}。"
                "请修改配置并重建索引。"
            )
            vectors = None
    except AIUnavailableError as exc:
        embed_error = str(exc)
    except Exception as exc:  # noqa: BLE001
        embed_error = f"嵌入生成失败：{exc}"

    # 4) 写入片段
    for i, c in enumerate(chunks):
        vec = vectors[i] if vectors else None
        db.add(
            Chunk(
                document_id=document.id,
                chunk_index=c.index,
                heading=c.heading,
                content=c.content,
                page_no=c.page_no,
                token_count=c.token_count,
                embedding=vec,
            )
        )
    document.chunk_count = len(chunks)

    # 先提交片段：即使嵌入失败也要保留，保证关键词检索仍可用
    # （符合"模型不可用时非 AI 功能仍可用"的约束）
    db.commit()

    if embed_error:
        logger.warning("文档 %s 嵌入失败（片段已保留）：%s", document.id, embed_error)
        raise EmbeddingUnavailableError(embed_error)

    return len(chunks)


async def embed_query(text: str) -> list[float] | None:
    """为查询生成嵌入；失败返回 None（此时降级为关键词检索）。"""
    try:
        provider = get_embedding_provider()
        vecs = await provider.embed([text])
        return vecs[0] if vecs else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询嵌入失败，降级为关键词检索：%s", exc)
        return None
