"""Chat AI web routes."""

import json
import logging
from uuid import UUID

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.dependencies import ChatRepoDep, DbSession
from app.web.helpers import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/app/czat/", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse("chat/index.html", {"request": request})


@router.post("/app/czat/send", response_class=HTMLResponse)
async def chat_send(
    request: Request,
    session: DbSession,
    chat_repo: ChatRepoDep,
    message: str = Form(...),
    session_id: str = Form(""),
):
    if not settings.CHAT_ENABLED:
        return templates.TemplateResponse("chat/partials/message.html", {
            "request": request, "error": "Chat jest wylaczony",
        })

    try:
        from app.chat import orchestrator

        # Create or get session
        new_session = False
        if session_id:
            from uuid import UUID as _UUID
            chat_session = await chat_repo.get_by_id(_UUID(session_id))
        else:
            chat_session = None

        if not chat_session:
            chat_session = await chat_repo.create_session(source="web")
            await session.commit()
            new_session = True

        # Save user message
        await chat_repo.add_message(
            session_id=chat_session.id,
            role="user",
            content=message,
        )
        await session.commit()

        # Process through orchestrator
        response = await orchestrator.process_message(
            message=message,
            session_id=chat_session.id,
            db_session=session,
        )

        # Save assistant message
        await chat_repo.add_message(
            session_id=chat_session.id,
            role="assistant",
            content=response.answer,
            sources=response.sources,
            search_type=response.search_type,
            search_query=response.search_query,
            model_used=response.model_used,
            processing_time_sec=response.processing_time_sec,
        )

        # Auto-generate title
        if not chat_session.title:
            await chat_repo.generate_title(chat_session.id)

        await session.commit()

        resp = templates.TemplateResponse("chat/partials/message.html", {
            "request": request,
            "user_message": message,
            "answer": response.answer,
            "sources": response.sources,
            "search_type": response.search_type,
            "processing_time": response.processing_time_sec,
        })

        # If new session, trigger client-side update
        # Reload session to get the generated title
        if new_session:
            await session.refresh(chat_session)
            resp.headers["HX-Trigger"] = json.dumps({
                "newChatSession": {
                    "session_id": str(chat_session.id),
                    "title": chat_session.title or "",
                }
            })

        return resp

    except Exception as e:
        logger.error(f"Chat error: {e}")
        return templates.TemplateResponse("chat/partials/message.html", {
            "request": request, "user_message": message, "error": "Wystąpił błąd podczas przetwarzania wiadomości",
        })


@router.get("/app/czat/sessions", response_class=HTMLResponse)
async def chat_sessions_list(request: Request, chat_repo: ChatRepoDep):
    sessions = await chat_repo.get_user_sessions(limit=30)
    active_id = request.query_params.get("active", "")
    return templates.TemplateResponse("chat/partials/session_list.html", {
        "request": request,
        "sessions": sessions,
        "active_session_id": active_id,
    })


@router.get("/app/czat/sessions/{session_id}", response_class=HTMLResponse)
async def chat_load_session(request: Request, session_id: UUID, chat_repo: ChatRepoDep):
    chat_session = await chat_repo.get_session_with_messages(session_id)
    if not chat_session:
        return HTMLResponse("<div class='text-danger'>Sesja nie znaleziona</div>", status_code=404)

    resp = templates.TemplateResponse("chat/partials/messages.html", {
        "request": request,
        "messages": chat_session.messages,
    })
    resp.headers["HX-Trigger"] = json.dumps({
        "sessionLoaded": {"title": chat_session.title or "Nowy czat"}
    })
    return resp


@router.delete("/app/czat/sessions", response_class=HTMLResponse)
async def chat_delete_all_sessions(
    request: Request,
    session: DbSession,
    chat_repo: ChatRepoDep,
):
    await chat_repo.delete_all_sessions()
    await session.commit()
    return templates.TemplateResponse("chat/partials/session_list.html", {
        "request": request, "sessions": [], "active_session_id": "",
    })


@router.delete("/app/czat/sessions/{session_id}", response_class=HTMLResponse)
async def chat_delete_session(
    request: Request,
    session_id: UUID,
    session: DbSession,
    chat_repo: ChatRepoDep,
):
    await chat_repo.delete(session_id)
    await session.commit()
    sessions = await chat_repo.get_user_sessions(limit=30)
    return templates.TemplateResponse("chat/partials/session_list.html", {
        "request": request, "sessions": sessions, "active_session_id": "",
    })
