"""REST API endpoints for Chat AI."""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
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

    # Try agent action first
    agent_result = None
    if settings.CHAT_AGENT_ENABLED:
        from app.chat.agent_executor import looks_like_action, process_with_agent

        if looks_like_action(data.message):
            try:
                agent_result = await process_with_agent(data.message, session)
            except Exception as e:
                logger.warning(f"Agent processing failed: {e}")

    if agent_result and agent_result.executed and agent_result.result_text:
        # Tool executed - save and return result
        history_content = (
            agent_result.history_entry["content"]
            if agent_result.history_entry
            else agent_result.result_text
        )
        assistant_msg = await chat_repo.add_message(
            session_id=chat_session.id,
            role="assistant",
            content=history_content,
            search_type="agent",
        )
        if not chat_session.title:
            await chat_repo.generate_title(chat_session.id)
        await session.commit()

        return ChatMessageResponse(
            session_id=chat_session.id,
            message_id=assistant_msg.id,
            answer=agent_result.result_text,
            sources=[],
            search_type="agent",
            model_used="agent",
            processing_time_sec=0,
        )

    # Fall through to orchestrator (with agent search strategy hint)
    response = await orchestrator.process_message(
        message=data.message,
        session_id=chat_session.id,
        db_session=session,
        agent_search_strategy=agent_result.search_strategy if agent_result else None,
        agent_search_query=agent_result.search_query if agent_result else None,
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


@router.post("/stream")
@limiter.limit("20/minute")
async def stream_message(
    request: Request,
    data: ChatMessageRequest,
    session: DbSession,
    chat_repo: ChatRepoDep,
):
    """Stream a chat response as Server-Sent Events.

    SSE events:
    - status: {"phase": "classifying|searching|generating", ...}
    - token: {"text": "..."} - individual LLM tokens
    - done: {"answer": "...", "sources": [...], ...} - final response
    """
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

    async def event_generator():
        """Generate SSE events, then save assistant message at the end."""
        import json as _json
        import time as _time

        # Send session_id immediately so client can store it
        yield f"event: session\ndata: {_json.dumps({'session_id': str(chat_session.id)})}\n\n"

        full_answer = ""
        sources = []
        search_type = "direct"
        model_used = ""
        processing_time = 0.0
        agent_history_content = None

        # Try agent action first (create_note, bookmark, summarize, list)
        agent_result = None
        if settings.CHAT_AGENT_ENABLED:
            from app.chat.agent_executor import looks_like_action, process_with_agent

            if looks_like_action(data.message):
                yield f"event: status\ndata: {_json.dumps({'phase': 'agent'})}\n\n"
                start = _time.time()
                try:
                    agent_result = await process_with_agent(data.message, session)
                except Exception as e:
                    logger.warning(f"Agent processing failed: {e}")

        if agent_result and agent_result.executed and agent_result.result_text:
            # Tool executed - emit tool_result event with structured metadata
            tool_data = {
                "tool": agent_result.tool,
                "text": agent_result.result_text,
                "metadata": agent_result.tool_metadata,
            }
            yield f"event: tool_result\ndata: {_json.dumps(tool_data, ensure_ascii=False)}\n\n"

            full_answer = agent_result.result_text
            search_type = "agent"
            agent_history_content = (
                agent_result.history_entry["content"]
                if agent_result.history_entry
                else agent_result.result_text
            )

            # Emit done event
            yield f"event: done\ndata: {_json.dumps({'answer': full_answer, 'sources': [], 'search_type': 'agent', 'model_used': 'agent', 'processing_time_sec': 0, 'tool_result': tool_data}, ensure_ascii=False)}\n\n"

        else:
            # Fall through to orchestrator (with agent search strategy hint)
            agent_strategy = agent_result.search_strategy if agent_result else None
            agent_query = agent_result.search_query if agent_result else None

            async for event in orchestrator.process_message_stream(
                message=data.message,
                session_id=chat_session.id,
                db_session=session,
                agent_search_strategy=agent_strategy,
                agent_search_query=agent_query,
            ):
                yield event

                # Parse done event to capture final data for DB save
                if event.startswith("event: done"):
                    data_line = event.split("data: ", 1)[1].split("\n")[0]
                    done_data = _json.loads(data_line)
                    full_answer = done_data.get("answer", "")
                    sources = done_data.get("sources", [])
                    search_type = done_data.get("search_type", "direct")
                    model_used = done_data.get("model_used", "")
                    processing_time = done_data.get("processing_time_sec", 0.0)

        # Save assistant message after streaming completes
        if full_answer:
            save_content = agent_history_content or full_answer
            await chat_repo.add_message(
                session_id=chat_session.id,
                role="assistant",
                content=save_content,
                sources=sources,
                search_type=search_type,
                model_used=model_used,
                processing_time_sec=processing_time,
            )
            if not chat_session.title:
                await chat_repo.generate_title(chat_session.id)
            await session.commit()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
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


@router.get("/suggestions")
async def get_suggestions(
    session: DbSession,
    chat_repo: ChatRepoDep,
):
    """Get contextual chat suggestions based on time of day and recent activity."""
    from datetime import datetime, timedelta

    now = datetime.now()
    hour = now.hour
    suggestions = []

    # Time-based suggestions
    if 5 <= hour < 12:
        suggestions.append({"text": "Plan na dzisiaj", "icon": "☀️"})
    elif 12 <= hour < 14:
        suggestions.append({"text": "Co mam na obiad?", "icon": "🍽️"})
    elif 17 <= hour < 22:
        suggestions.append({"text": "Podsumuj dzień", "icon": "📊"})
    elif hour >= 22 or hour < 5:
        suggestions.append({"text": "Zanotuj na jutro", "icon": "🌙"})

    # Recent activity suggestions
    try:
        # Check for recent receipts
        from app.db.repositories.receipts import ReceiptRepository
        receipt_repo = ReceiptRepository(session)
        recent_receipts = await receipt_repo.get_recent(limit=1, include_items=False)
        if recent_receipts:
            last = recent_receipts[0]
            if last.created_at and (now - last.created_at) < timedelta(hours=24):
                suggestions.append({"text": "Ile wydałem w tym tygodniu?", "icon": "💰"})
    except Exception:
        pass

    try:
        # Check for recent notes
        from app.db.repositories.notes import NoteRepository
        note_repo = NoteRepository(session)
        recent_notes = await note_repo.get_recent(limit=1)
        if recent_notes:
            last = recent_notes[0]
            if last.created_at and (now - last.created_at) < timedelta(hours=24):
                suggestions.append({"text": "Pokaż ostatnie notatki", "icon": "📝"})
    except Exception:
        pass

    try:
        # Check for unread bookmarks
        from app.db.repositories.bookmarks import BookmarkRepository
        bm_repo = BookmarkRepository(session)
        pending = await bm_repo.get_by_status("pending", limit=3)
        if pending:
            suggestions.append({"text": f"Mam {len(pending)} nieprzeczytanych zakładek", "icon": "📚"})
    except Exception:
        pass

    # Always include a general suggestion
    if len(suggestions) < 4:
        defaults = [
            {"text": "Co nowego w AI?", "icon": "🤖"},
            {"text": "Zanotuj: kupić mleko", "icon": "📝"},
            {"text": "Ile wydałem w tym miesiącu?", "icon": "💰"},
            {"text": "Podsumuj ostatnie artykuły", "icon": "📰"},
        ]
        for d in defaults:
            if len(suggestions) >= 4:
                break
            if not any(s["text"] == d["text"] for s in suggestions):
                suggestions.append(d)

    return suggestions[:4]
