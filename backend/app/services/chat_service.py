"""会话与问答服务（含 SSE 流式输出、引用保存、重新生成）。"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.factory import get_provider
from app.ai.prompts import build_messages, insufficient_answer
from app.core.database import SessionLocal
from app.core.exceptions import AIUnavailableError, NotFoundError
from app.core.logging import get_logger
from app.models import Conversation, Message
from app.models.conversation import MODE_DETAIL
from app.rag.indexer import embed_query
from app.rag.retriever import hybrid_search
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
            .order_by(Message.created_at)
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


# ---------------- 核心：检索 + 生成 ----------------
async def _answer_events(
    db: Session,
    conv: Conversation,
    question: str,
    mode: str,
    history: list[dict],
    use_web: bool = False,
) -> AsyncIterator[str]:
    """执行「术语词典 + 检索 → 生成 → 保存」，产出 SSE 事件。

    事件类型：sources / glossary / thinking / delta / done / error。
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
    hits = hybrid_search(db, question, vec)
    yield _sse("sources", [h.model_dump(mode="json") for h in hits])

    # 3) 既无资料也无术语命中：明确告知，不编造
    if not hits and not glossary_terms:
        text = insufficient_answer(hits)
        msg = Message(
            conversation_id=conv.id,
            role="assistant",
            content=text,
            sources=[],
            source_type=None,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        yield _sse("delta", {"text": text})
        yield _sse("done", {"message_id": str(msg.id), "sources": []})
        return

    # 4) 生成
    messages = build_messages(
        question,
        hits,
        mode,
        history=history,
        use_web=use_web,
        glossary=glossary_text,
    )
    provider = get_provider()
    collected: list[str] = []
    reasoning_chars = 0
    try:
        stream = await provider.chat(messages, stream=True)
        async for chunk in stream:  # type: ignore[union-attr]
            ctype = chunk.get("type", "content")
            text = chunk.get("text", "")
            if not text:
                continue
            if ctype == "reasoning":
                # 推理模型的思考过程：只上报进度，不计入回答正文
                reasoning_chars += len(text)
                yield _sse("thinking", {"chars": reasoning_chars})
            else:
                collected.append(text)
                yield _sse("delta", {"text": text})
    except AIUnavailableError as exc:
        yield _sse("error", {"message": str(exc)})
        return

    full = "".join(collected)
    sources = [h.model_dump(mode="json") for h in hits]
    if not hits:
        source_type = "专属术语词典"
    elif len(hits) == 1:
        source_type = "知识库原文"
    else:
        source_type = "知识库归纳推理"
    msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content=full,
        sources=sources,
        source_type=source_type,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    yield _sse("done", {"message_id": str(msg.id), "sources": sources})


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
async def regenerate_stream(message_id: uuid.UUID) -> AsyncIterator[str]:
    """重新生成某条 AI 回答（删除原回答后按同一提问重新检索与生成）。"""
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
                .order_by(Message.created_at)
            )
            .scalars()
            .all()
        )
        history = _history(list(earlier))

        question = question_msg.content
        # 删除原回答，避免同一提问出现多条回答
        db.delete(target)
        db.commit()

        async for event in _answer_events(db, conv, question, conv.mode, history):
            yield event
    except Exception as exc:  # noqa: BLE001
        logger.exception("重新生成失败")
        yield _sse("error", {"message": f"重新生成失败：{exc}"})
    finally:
        db.close()
