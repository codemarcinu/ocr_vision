"""REST API endpoints for Chat AI."""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.chat import orchestrator
from app.config import settings
from app.dependencies import ChatRepoDep, DbSession
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


# Request/Response models

class ChatMessageRequest(BaseModel):
    """Send a chat message."""
    message: str
    session_id: Optional[UUID] = None


class ChatMessageResponse(BaseModel):
    """Response to a chat message."""
    session_id: UUID
    message_id: int
    answer: str
    sources: list[dict]
    search_type: str
    model_used: str
    processing_time_sec: float


class ChatSessionResponse(BaseModel):
    """Chat session info."""
    id: UUID
    title: Optional[str]
    source: str
    is_active: bool
    message_count: int
    created_at: datetime
    updated_at: datetime


class ChatSessionDetailResponse(BaseModel):
    """Chat session with messages."""
    id: UUID
    title: Optional[str]
    source: str
    is_active: bool
    created_at: datetime
    messages: list[dict]


# Endpoints

@router.post("/message", response_model=ChatMessageResponse)
@limiter.limit("20/minute")
async def send_message(
    request: Request,
    data: ChatMessageRequest,
    session: DbSession,
    chat_repo: ChatRepoDep,
):
    """Send a message to the chat. Creates a new session if session_id is not provided."""
    if not settings.CHAT_ENABLED:
        raise HTTPException(status_code=503, detail="Chat jest wyłączony")

    # Create or get session
    if data.session_id:
        chat_session = await chat_repo.get_by_id(data.session_id)
        if not chat_session:
            raise HTTPException(status_code=404, detail="Sesja nie znaleziona")
    else:
        chat_session = await chat_repo.create_session(source="api")
        await session.commit()

    # Save user message
    await chat_repo.add_message(
        session_id=chat_session.id,
        role="user",
        content=data.message,
    )
    await session.commit()

    # Process through orchestrator
    response = await orchestrator.process_message(
        message=data.message,
        session_id=chat_session.id,
        db_session=session,
    )

    # Save assistant message
    assistant_msg = await chat_repo.add_message(
        session_id=chat_session.id,
        role="assistant",
        content=response.answer,
        sources=response.sources,
        search_type=response.search_type,
        search_query=response.search_query,
        model_used=response.model_used,
        processing_time_sec=response.processing_time_sec,
    )

    # Auto-generate title from first message
    if not chat_session.title:
        await chat_repo.generate_title(chat_session.id)

    await session.commit()

    return ChatMessageResponse(
        session_id=chat_session.id,
        message_id=assistant_msg.id,
        answer=response.answer,
        sources=response.sources,
        search_type=response.search_type,
        model_used=response.model_used,
        processing_time_sec=response.processing_time_sec,
    )


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    chat_repo: ChatRepoDep,
    source: Optional[str] = None,
    limit: int = 20,
):
    """List recent chat sessions."""
    sessions = await chat_repo.get_user_sessions(source=source, limit=limit)

    result = []
    for s in sessions:
        count = await chat_repo.get_message_count(s.id)
        result.append(ChatSessionResponse(
            id=s.id,
            title=s.title,
            source=s.source,
            is_active=s.is_active,
            message_count=count,
            created_at=s.created_at,
            updated_at=s.updated_at,
        ))
    return result


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailResponse)
async def get_session(
    session_id: UUID,
    chat_repo: ChatRepoDep,
):
    """Get a chat session with all messages."""
    chat_session = await chat_repo.get_session_with_messages(session_id)
    if not chat_session:
        raise HTTPException(status_code=404, detail="Sesja nie znaleziona")

    messages = [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "sources": msg.sources or [],
            "search_type": msg.search_type,
            "model_used": msg.model_used,
            "processing_time_sec": float(msg.processing_time_sec) if msg.processing_time_sec else None,
            "created_at": msg.created_at.isoformat(),
        }
        for msg in chat_session.messages
    ]

    return ChatSessionDetailResponse(
        id=chat_session.id,
        title=chat_session.title,
        source=chat_session.source,
        is_active=chat_session.is_active,
        created_at=chat_session.created_at,
        messages=messages,
    )


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: UUID,
    session: DbSession,
    chat_repo: ChatRepoDep,
):
    """Delete a chat session and all its messages."""
    deleted = await chat_repo.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sesja nie znaleziona")
    await session.commit()
    return {"status": "ok", "deleted": str(session_id)}


@router.post("/sessions/{session_id}/end")
async def end_session(
    session_id: UUID,
    session: DbSession,
    chat_repo: ChatRepoDep,
):
    """End an active chat session."""
    chat_session = await chat_repo.get_by_id(session_id)
    if not chat_session:
        raise HTTPException(status_code=404, detail="Sesja nie znaleziona")

    await chat_repo.end_session(session_id)
    await session.commit()
    return {"status": "ok", "session_id": str(session_id)}
