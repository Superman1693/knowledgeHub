"""会话与问答路由（含 SSE 流式回答）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.chat import (
    AskRequest,
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
    MessageOut,
)
from app.services import chat_service

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)) -> list[ConversationOut]:
    return [
        ConversationOut(
            id=c.id,
            title=c.title,
            mode=c.mode,
            created_at=c.created_at,
            updated_at=c.updated_at,
            message_count=count,
        )
        for c, count in chat_service.list_conversations(db)
    ]


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(
    payload: ConversationCreate, db: Session = Depends(get_db)
) -> ConversationOut:
    conv = chat_service.create_conversation(db, payload)
    return ConversationOut.model_validate(conv)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: uuid.UUID, db: Session = Depends(get_db)
) -> ConversationDetail:
    conv = chat_service.get_conversation(db, conversation_id)
    messages = chat_service.get_messages(db, conversation_id)
    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        mode=conv.mode,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=len(messages),
        messages=[MessageOut.model_validate(m) for m in messages],
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def update_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationUpdate,
    db: Session = Depends(get_db),
) -> ConversationOut:
    conv = chat_service.update_conversation(db, conversation_id, payload)
    return ConversationOut.model_validate(conv)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    chat_service.delete_conversation(db, conversation_id)


@router.post("/conversations/{conversation_id}/messages")
async def ask(conversation_id: uuid.UUID, payload: AskRequest) -> StreamingResponse:
    """提问：返回 text/event-stream 流。"""
    return StreamingResponse(
        chat_service.ask_stream(conversation_id, payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/messages/{message_id}/regenerate")
async def regenerate(
    message_id: uuid.UUID, use_web: bool = Query(False)
) -> StreamingResponse:
    """重新生成指定的 AI 回答：删除原回答后按同一提问重新检索与生成（SSE）。

    use_web：是否同时进行联网补充（默认关闭，避免非显式的联网请求）。
    """
    return StreamingResponse(
        chat_service.regenerate_stream(message_id, use_web),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/abort")
def abort_chat() -> dict:
    """中止占位：前端通过关闭 SSE 连接实现中止。"""
    return {"ok": True, "message": "前端关闭连接即中止生成"}
