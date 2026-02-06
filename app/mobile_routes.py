"""Mobile PWA routes for Second Brain.

Chat-centric mobile interface at /m/
"""

import logging
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.dependencies import ChatRepoDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/m", tags=["mobile"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def mobile_chat(
    request: Request,
    session_id: Optional[str] = None,
    chat_repo: ChatRepoDep = None,
):
    """Main mobile view - chat interface.

    Optionally loads existing session if session_id is provided.
    """
    messages = []
    active_session_id = None

    # Try to load existing session
    if session_id and chat_repo:
        try:
            session_uuid = UUID(session_id)
            chat_session = await chat_repo.get_session_with_messages(session_uuid)
            if chat_session:
                active_session_id = str(chat_session.id)
                messages = [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "sources": msg.sources or [],
                        "created_at": msg.created_at,
                    }
                    for msg in chat_session.messages
                ]
        except (ValueError, Exception) as e:
            logger.warning(f"Failed to load session {session_id}: {e}")

    return templates.TemplateResponse(
        "mobile/chat.html",
        {
            "request": request,
            "messages": messages,
            "session_id": active_session_id,
            "chat_enabled": settings.CHAT_ENABLED,
        }
    )


@router.get("/notatki", response_class=HTMLResponse)
async def mobile_notes(request: Request):
    """Notes list in mobile view (placeholder - can be expanded later)."""
    return templates.TemplateResponse(
        "mobile/chat.html",
        {
            "request": request,
            "messages": [],
            "session_id": None,
        }
    )


@router.get("/paragony", response_class=HTMLResponse)
async def mobile_receipts(request: Request):
    """Receipts list in mobile view (placeholder - can be expanded later)."""
    return templates.TemplateResponse(
        "mobile/chat.html",
        {
            "request": request,
            "messages": [],
            "session_id": None,
        }
    )


@router.get("/wiedza", response_class=HTMLResponse)
async def mobile_knowledge(request: Request):
    """Knowledge base in mobile view (placeholder - can be expanded later)."""
    return templates.TemplateResponse(
        "mobile/chat.html",
        {
            "request": request,
            "messages": [],
            "session_id": None,
        }
    )


@router.post("/share", response_class=HTMLResponse)
async def mobile_share_target(
    request: Request,
    chat_repo: ChatRepoDep = None,
):
    """Handle share target from PWA manifest.

    When user shares content (image, URL, text) to the app,
    this endpoint receives it.
    """
    form = await request.form()

    title = form.get("title", "")
    text = form.get("text", "")
    url = form.get("url", "")
    image = form.get("image")

    # Build a message from shared content
    parts = []
    if title:
        parts.append(f"**{title}**")
    if text:
        parts.append(text)
    if url:
        parts.append(f"Link: {url}")

    shared_content = "\n".join(parts) if parts else None

    # If image was shared, we could process it as a receipt
    # For now, just redirect to chat with the shared content pre-filled
    # (handled by JS on the client side)

    return templates.TemplateResponse(
        "mobile/chat.html",
        {
            "request": request,
            "messages": [],
            "session_id": None,
            "prefill_message": shared_content,
            "shared_image": image is not None,
        }
    )
