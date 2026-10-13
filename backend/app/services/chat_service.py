"""会话与问答服务（含 SSE 流式输出、引用保存、重新生成）。"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.factory import get_provider
from app.ai.prompts import build_messages, insufficient_answer
from app.ai.web_search import search_web
from app.core.database import SessionLocal
from app.core.exceptions import AIUnavailableError, NotFoundError
from app.core.logging import get_logger
from app.models import Conversation, Message
from app.models.conversation import MODE_DETAIL
from app.rag.indexer import embed_query
from app.rag.retriever import hybrid_search
from app.rag.source_type import classify as classify_source
from app.schemas.chat import AskRequest, ConversationCreate, ConversationUpdate
from app.services import glossary_service

logger = get_logger(__name__)

HISTORY_LIMIT = 10


# ---------------- CRUD ----------------
def list_conversations(db: Session) -> list[tuple[Conversation, int]]:
    rows = db.execute(
        select(Conversation, func.count(Message.id))
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
    ).all()
    return [(c, n) for c, n in rows]


def get_conversation(db: Session, conversation_id: uuid.UUID) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise NotFoundError("会话不存在")
    return conv


def create_conversation(db: Session, payload: ConversationCreate) -> Conversation:
    conv = Conversation(
        title=payload.title or "新会话",
        mode=payload.mode or MODE_DETAIL,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def update_conversation(
    db: Session, conversation_id: uuid.UUID, payload: ConversationUpdate
) -> Conversation:
    conv = get_conversation(db, conversation_id)
    if payload.title is not None:
        conv.title = payload.title
    if payload.mode is not None:
        conv.mode = payload.mode
    db.commit()
    db.refresh(conv)
    return conv


def delete_conversation(db: Session, conversation_id: uuid.UUID) -> None:
    conv = get_conversation(db, conversation_id)
    db.delete(conv)
    db.commit()


def get_messages(db: Session, conversation_id: uuid.UUID) -> list[Message]:
    get_conversation(db, conversation_id)
    return list(
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        .scalars()
        .all()
    )


# ---------------- SSE 辅助 ----------------
def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _history(messages: list[Message]) -> list[dict]:
    recent = messages[-HISTORY_LIMIT:]
    return [
        {"role": m.role, "content": m.content}
        for m in recent
        if m.role in ("user", "assistant")
    ]


def _touch_conversation(conv: Conversation) -> None:
    """显式刷新会话的 updated_at。

    新增 Message 不会 UPDATE 会话行，因此 TimestampMixin 的 onupdate 不会触发；
    不刷新的话会话列表（按 updated_at 排序）永远停在首条消息的时间，刚聊过的会话不会置顶。
    """
    conv.updated_at = func.now()


# ---------------- 核心：检索 + 生成 ----------------
async def _answer_events(
    db: Session,
    conv: Conversation,
    question: str,
    mode: str,
    history: list[dict],
    use_web: bool = False,
) -> AsyncIterator[str]:
    """执行「术语词典 + 检索（+ 联网）→ 生成 → 保存」，产出 SSE 事件。

    事件类型：sources / glossary / web / thinking / delta / done / error。
    ask 与 regenerate 共用本函数，保证行为一致。
    """
    # 1) 优先检索专属术语词典（需求 17.3）
    glossary_terms = glossary_service.lookup_terms(db, question)
    glossary_text = glossary_service.render_glossary(glossary_terms)
    if glossary_terms:
        yield _sse(
            "glossary",
            [
                {"term": t.term, "definition": t.definition, "category": t.category}
                for t in glossary_terms
            ],
        )

    # 2) 检索知识库
    vec = await embed_query(question)
    # 隐私（LocalMind 规则）：AI 问答只在 ai_enabled=true 的笔记中检索，
    # 私密笔记在 SQL 层即被排除；回收站中的文档同样不参与检索。
    hits = hybrid_search(db, question, vec, ai_only=True)
    yield _sse("sources", [h.model_dump(mode="json") for h in hits])

    # 3) 联网补充：仅当用户显式启用时才发起；未启用/失败时不联网、不伪称
    web_results: list[dict] = []
    web_note = ""
    if use_web:
        found, web_note = await search_web(question)
        web_results = [r.as_dict() for r in found]
        yield _sse(
            "web",
            {"results": web_results, "ok": bool(web_results), "message": web_note},
        )

    # 4) 既无资料、也无术语命中、也无联网结果：明确告知，不编造
    if not hits and not glossary_terms and not web_results:
        text = insufficient_answer(hits)
        msg = Message(
            conversation_id=conv.id,
            role="assistant",
            content=text,
            sources=[],
            source_type=None,
        )
        db.add(msg)
        _touch_conversation(conv)
        db.commit()
        db.refresh(msg)
        yield _sse("delta", {"text": text})
        yield _sse("done", {"message_id": str(msg.id), "sources": []})
        return

    # 5) 生成
    messages = build_messages(
        question,
        hits,
        mode,
        history=history,
        use_web=use_web,
        glossary=glossary_text,
        web_results=web_results,
        web_note=web_note,
    )
    provider = get_provider()
    collected: list[str] = []
    reasoning_parts: list[str] = []
    reasoning_chars = 0
    try:
        stream = await provider.chat(messages, stream=True)
        async for chunk in stream:  # type: ignore[union-attr]
            ctype = chunk.get("type", "content")
            text = chunk.get("text", "")
            if not text:
                continue
            if ctype == "reasoning":
                # 推理模型的思考过程：增量透传给前端展示（类似 DeepSeek 的思考区），
                # 同时累积保存，重开会话后仍可回看；但不计入回答正文。
                reasoning_parts.append(text)
                reasoning_chars += len(text)
                yield _sse("thinking", {"text": text, "chars": reasoning_chars})
            else:
                collected.append(text)
                yield _sse("delta", {"text": text})
    except AIUnavailableError as exc:
        yield _sse("error", {"message": str(exc)})
        return

    full = "".join(collected)
    sources = [h.model_dump(mode="json") for h in hits]
    source_type = classify_source(
        hits=hits, web_results=web_results, glossary_terms=glossary_terms
    )
    msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content=full,
        sources=sources,
        source_type=source_type,
        reasoning="".join(reasoning_parts) or None,
    )
    db.add(msg)
    _touch_conversation(conv)
    db.commit()
    db.refresh(msg)
    yield _sse(
        "done",
        {
            "message_id": str(msg.id),
            "sources": sources,
            "source_type": source_type,
            "web_results": web_results,
        },
    )


# ---------------- 提问 ----------------
async def ask_stream(conversation_id: uuid.UUID, payload: AskRequest) -> AsyncIterator[str]:
    """提问并以 SSE 事件流返回回答。"""
    db = SessionLocal()
    try:
        conv = db.get(Conversation, conversation_id)
        if not conv:
            yield _sse("error", {"message": "会话不存在"})
            return

        mode = payload.mode or conv.mode
        # 历史上下文（不含本次提问）
        history = _history(get_messages(db, conversation_id))

        db.add(Message(conversation_id=conv.id, role="user", content=payload.question))
        if conv.title == "新会话":
            conv.title = payload.question[:30]
        _touch_conversation(conv)
        db.commit()

        async for event in _answer_events(
            db, conv, payload.question, mode, history, payload.use_web
        ):
            yield event
    except Exception as exc:  # noqa: BLE001
        logger.exception("问答失败")
        yield _sse("error", {"message": f"问答失败：{exc}"})
    finally:
        db.close()


# ---------------- 重新生成 ----------------
async def regenerate_stream(
    message_id: uuid.UUID, use_web: bool = False
) -> AsyncIterator[str]:
    """重新生成某条 AI 回答（删除原回答后按同一提问重新检索与生成）。

    use_web 由前端传入当前联网开关状态；默认 False——重新生成本身不构成
    新的联网授权，因此不会主动外发（需求 14.5）。
    """
    db = SessionLocal()
    try:
        target = db.get(Message, message_id)
        if not target or target.role != "assistant":
            yield _sse("error", {"message": "只能重新生成 AI 回答"})
            return

        conv = db.get(Conversation, target.conversation_id)
        if not conv:
            yield _sse("error", {"message": "会话不存在"})
            return

        # 该回答之前最近的用户提问
        question_msg = (
            db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.role == "user",
                    Message.created_at <= target.created_at,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if not question_msg:
            yield _sse("error", {"message": "找不到对应的提问，无法重新生成"})
            return

        # 重新生成前的历史（提问之前的消息）
        earlier = (
            db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.created_at < question_msg.created_at,
                )
                .order_by(Message.created_at, Message.id)
            )
            .scalars()
            .all()
        )
        history = _history(list(earlier))

        question = question_msg.content
        # 删除原回答，避免同一提问出现多条回答
        db.delete(target)
        db.commit()

        async for event in _answer_events(
            db, conv, question, conv.mode, history, use_web
        ):
            yield event
    except Exception as exc:  # noqa: BLE001
        logger.exception("重新生成失败")
        yield _sse("error", {"message": f"重新生成失败：{exc}"})
    finally:
        db.close()
