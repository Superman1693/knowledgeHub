"""向量索引构建：分块 → 嵌入 → 写入 chunks。"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.ai.factory import get_embedding_provider
from app.core.config import settings
from app.core.exceptions import AIUnavailableError, EmbeddingUnavailableError
from app.core.logging import get_logger
from app.models import Chunk, Document
from app.rag.chunker import (
    ChunkData,
    chunk_document,
    chunk_document_ai,
    chunk_document_semantic,
    estimate_tokens,
)
from app.rag.pinyin import pinyin_of
from app.services.parsers import ParsedDocument

logger = get_logger(__name__)


def _group_for_parents(chunks: list[ChunkData], parent_size: int) -> list[list[int]]:
    """把子块按顺序分组，每组累积到 parent_size，返回每组的下标列表。

    组边界即父块边界 —— 检索命中任一子块，都会回传整个组的内容。
    """
    groups: list[list[int]] = []
    cur: list[int] = []
    cur_len = 0
    for i, c in enumerate(chunks):
        if cur and cur_len + len(c.content) > parent_size:
            groups.append(cur)
            cur = []
            cur_len = 0
        cur.append(i)
        cur_len += len(c.content)
    if cur:
        groups.append(cur)
    return groups


async def build_index(db: Session, document: Document, parsed: ParsedDocument) -> int:
    """为文档构建/重建向量索引，返回片段数。

    嵌入失败时：仍保留片段（关键词检索可用），但抛出异常由上层标记为 failed。
    """
    # 1) 清理旧片段（重建场景）
    db.query(Chunk).filter(Chunk.document_id == document.id).delete()
    db.flush()

    # 2) 分块：rule（兜底）/ semantic（嵌入相似度）/ ai（模型判断边界）
    #    后两者失败或超限时都会自动回退规则分块
    mode = (settings.chunk_mode or "rule").strip().lower()
    if mode == "ai":
        chunks = await chunk_document_ai(parsed.text, parsed.pages or None)
    elif mode == "semantic":
        chunks = await chunk_document_semantic(parsed.text, parsed.pages or None)
    else:
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
    #    开启父子检索时：先按 parent_chunk_size 把子块合并写入「父块」（无向量），
    #    再写子块并挂上 parent_id。检索用子块（精准），回传给模型的是父块（完整）。
    parent_of: dict[int, uuid.UUID] = {}
    if settings.parent_child_enabled:
        for group in _group_for_parents(chunks, settings.parent_chunk_size):
            content = "\n".join(chunks[i].content for i in group).strip()
            parent = Chunk(
                document_id=document.id,
                chunk_index=chunks[group[0]].index,
                heading=chunks[group[0]].heading,
                content=content,
                page_no=None,
                token_count=estimate_tokens(content),
                embedding=None,
            )
            db.add(parent)
            db.flush()  # 需要父块 id 才能挂到子块上
            for i in group:
                parent_of[i] = parent.id

    for i, c in enumerate(chunks):
        # 拼音列：标题 + 正文一起转。标题参与是因为用户常按小节标题回忆内容
        # （"我记得有个叫响应式布局的小节"）。
        # pypinyin 未安装时返回空串 → 存 NULL，检索自动退回纯文本匹配。
        full_py, initials_py = pinyin_of(f"{c.heading or ''}\n{c.content or ''}")
        db.add(
            Chunk(
                document_id=document.id,
                chunk_index=c.index,
                heading=c.heading,
                content=c.content,
                pinyin=full_py or None,
                pinyin_initials=initials_py or None,
                page_no=c.page_no,
                token_count=c.token_count,
                embedding=vectors[i] if vectors else None,
                parent_id=parent_of.get(i),
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
