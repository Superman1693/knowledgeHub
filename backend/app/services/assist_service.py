"""笔记页内 AI 助手：对「选中的一段文字」做解释 / 总结 / 生成卡片 / 找关联。

对应 LocalMind：「AI 助手还应该能从笔记页面直接呼出，例如选中一段文字后进行
解释、总结、生成问题或查找关联资料，而不是要求用户每次都切换到单独聊天界面。」

设计取舍：
- 「找关联」**不调用对话模型**，直接用选中文字做混合检索（关键词 + 语义），
  既省额度又更快，且结果必然来自用户自己的知识库；
- 「解释 / 总结」把选中文字作为唯一输入，提示词明确要求**不引入无关知识、不编造**；
- 「生成卡片」直接落库（复用 `srs_service` 的卡片生成链路），返回卡片详情。
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.ai.factory import get_provider
from app.core.exceptions import AIUnavailableError, ValidationError
from app.rag.indexer import embed_query
from app.rag.retriever import hybrid_search

# 选中文字的长度上限（避免一次提交整篇长文）
MAX_SELECTION = 4000

ACTIONS: dict[str, str] = {
    "explain": (
        "你是技术笔记助手。请用**简洁的中文**解释下面这段内容："
        "先用一句话点明它在讲什么，再展开关键点，必要时给一个小例子。"
        "只解释这段内容本身，不要引入无关知识，也不要编造原文没有的信息。"
    ),
    "summarize": (
        "你是技术笔记助手。请把下面这段内容压缩成 **3~5 条要点**，"
        "每条一句话，用 Markdown 列表输出。不要添加原文没有的信息。"
    ),
}


async def assist(
    db: Session,
    text: str,
    action: str,
    document_id: uuid.UUID | None = None,
    count: int = 5,
) -> dict:
    """对选中文字执行一个操作，返回结构化结果。"""
    text = (text or "").strip()
    if not text:
        raise ValidationError("请先选中一段文字")
    if len(text) > MAX_SELECTION:
        text = text[:MAX_SELECTION]

    if action == "related":
        return await _related(db, text, count)

    if action == "cards":
        from app.services import srs_service

        cards = await srs_service.generate_cards_from_text(
            db, text, count, document_id=document_id
        )
        return {
            "action": action,
            "text": text,
            "cards": [srs_service.card_out(c) for c in cards],
            "count": len(cards),
        }

    if action not in ACTIONS:
        raise ValidationError(f"不支持的操作：{action}")

    messages = [
        {"role": "system", "content": ACTIONS[action]},
        {"role": "user", "content": text},
    ]
    try:
        result = await get_provider().chat(messages, stream=False)
    except AIUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"AI 处理失败：{exc}") from exc
    return {"action": action, "text": text, "result": str(result).strip()}


async def _related(db: Session, text: str, count: int) -> dict:
    """找关联资料：纯检索，不消耗对话模型。"""
    vec = await embed_query(text)
    hits = hybrid_search(
        db, text, vec, top_k=max(1, min(int(count or 5), 20)), ai_only=False
    )
    return {
        "action": "related",
        "text": text,
        "related": [h.model_dump(mode="json") for h in hits],
        "count": len(hits),
    }
