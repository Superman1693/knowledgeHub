"""批量 AI 摘要：对多篇文档并行生成摘要。

LocalMind P2「批量 AI 摘要」：用户选择文件后批量处理。
限制并发数，避免一次性打满对话模型额度；单篇失败不影响其余。
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import Document

logger = get_logger(__name__)

SUMMARY_PROMPT = """你是笔记摘要助手。请把下面的笔记内容压缩为一段**简洁的摘要**（80~150 字）。
要求：
1. 只概括原文要点，**不添加原文没有的信息**。
2. 用一段连续的中文段落输出，不要列表、不要标题。
3. 如果原文过短或无实质内容，输出「（原文内容过少，无法生成有效摘要）」。"""

# 并发上限：同时调用对话模型的最大文档数
MAX_CONCURRENCY = 3
MAX_BATCH = 20


def _truncate(text: str, limit: int = 3000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n…（后文截断）"


async def _summarize_one(provider, text: str) -> str:
    messages = [
        {"role": "system", "content": SUMMARY_PROMPT},
        {"role": "user", "content": _truncate(text)},
    ]
    try:
        raw = await provider.chat(messages, stream=False)
        return str(raw).strip() or "（空）"
    except Exception as exc:  # noqa: BLE001
        logger.warning("单篇摘要失败：%s", exc)
        return f"（生成失败：{exc}）"


async def batch_summarize(
    db: Session,
    document_ids: list[uuid.UUID],
) -> dict:
    """对多篇文档生成摘要，返回结果列表。

    单篇失败不影响其余；并发上限 MAX_CONCURRENCY 控制同时调用数。
    """
    if not document_ids:
        raise ValidationError("请指定至少一篇文档")
    if len(document_ids) > MAX_BATCH:
        raise ValidationError(f"单次最多 {MAX_BATCH} 篇")

    docs = list(
        db.execute(
            select(Document)
            .where(
                Document.id.in_(document_ids),
                Document.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    found_ids = {d.id for d in docs}
    missing = [str(did) for did in document_ids if did not in found_ids]
    if not docs:
        raise NotFoundError("指定的文档均不存在")

    from app.ai.factory import get_provider

    provider = get_provider()
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def _run(doc: Document) -> dict:
        async with semaphore:
            summary = await _summarize_one(provider, doc.content_text or "")
        return {
            "document_id": str(doc.id),
            "title": doc.title,
            "summary": summary,
        }

    tasks = [_run(d) for d in docs]
    results = await asyncio.gather(*tasks)

    return {
        "total": len(results),
        "items": list(results),
        "missing": missing,
    }
