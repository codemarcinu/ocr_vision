"""Mobile PWA routes for Second Brain.

Chat-centric mobile interface at /m/
Subpages: /m/notatki, /m/paragony, /m/wiedza
"""

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.dependencies import (
    BookmarkRepoDep,
    ChatRepoDep,
    DbSession,
    NoteRepoDep,
    ReceiptRepoDep,
    StoreRepoDep,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/m", tags=["mobile"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Store emoji map (shared with web_routes)
STORE_EMOJIS = {
    "biedronka": "🐞", "lidl": "🔵", "kaufland": "🔴",
    "zabka": "🐸", "auchan": "🟠", "carrefour": "🔷",
    "netto": "🟡", "dino": "🦕", "rossmann": "🩷",
    "lewiatan": "🟢", "stokrotka": "🌼",
}


def _store_emoji(name: str) -> str:
    if not name:
        return "🏪"
    key = name.lower().split(",")[0].split(" ")[0].strip()
    return STORE_EMOJIS.get(key, "🏪")


templates.env.globals.update({
    "store_emoji": _store_emoji,
})


def _htmx_trigger(message: str, msg_type: str = "success") -> dict:
    return {"HX-Trigger": json.dumps({"showToast": {"message": message, "type": msg_type}})}


# ============================================================================
# Chat (main view)
# ============================================================================

@router.get("/", response_class=HTMLResponse)
async def mobile_chat(
    request: Request,
    session_id: Optional[str] = None,
    chat_repo: ChatRepoDep = None,
):
    """Main mobile view - chat interface."""
    messages = []
    active_session_id = None

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
            "active_page": "chat",
        }
    )


# ============================================================================
# Notes
# ============================================================================

@router.get("/notatki", response_class=HTMLResponse)
async def mobile_notes(
    request: Request,
    repo: NoteRepoDep,
    search: Optional[str] = None,
):
    """Notes list in mobile view."""
    if search:
        notes = await repo.search(search, limit=50)
    else:
        notes = await repo.get_recent(limit=50)

    ctx = {
        "request": request,
        "notes": notes,
        "search": search or "",
        "active_page": "notes",
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("mobile/partials/note_list.html", ctx)
    return templates.TemplateResponse("mobile/notes.html", ctx)


@router.get("/notatki/{note_id}", response_class=HTMLResponse)
async def mobile_note_detail(request: Request, note_id: UUID, repo: NoteRepoDep):
    """Note detail view."""
    note = await repo.get_by_id(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Notatka nie znaleziona")
    return templates.TemplateResponse("mobile/note_detail.html", {
        "request": request,
        "note": note,
        "active_page": "notes",
    })


@router.post("/notatki/create", response_class=HTMLResponse)
async def mobile_note_create(
    request: Request,
    repo: NoteRepoDep,
    session: DbSession,
    title: str = Form(...),
    content: str = Form(""),
):
    """Create a new note."""
    await repo.create(title=title, content=content or title)
    await session.commit()

    # Write to Obsidian
    if settings.GENERATE_OBSIDIAN_FILES:
        try:
            from app.notes_writer import write_note_file
            note = await repo.get_recent(limit=1)
            if note:
                write_note_file(note[0])
        except Exception:
            pass

    # Push notification
    try:
        from app.push.hooks import push_note_created
        note = await repo.get_recent(limit=1)
        if note:
            await push_note_created(title=note[0].title, note_id=str(note[0].id))
    except Exception:
        pass

    notes = await repo.get_recent(limit=50)
    response = templates.TemplateResponse("mobile/partials/note_list.html", {
        "request": request,
        "notes": notes,
        "search": "",
    })
    response.headers.update(_htmx_trigger("Notatka utworzona"))
    return response


@router.post("/notatki/{note_id}/update", response_class=HTMLResponse)
async def mobile_note_update(
    request: Request,
    note_id: UUID,
    repo: NoteRepoDep,
    session: DbSession,
    title: Optional[str] = Form(None),
    content: Optional[str] = Form(None),
):
    """Update a note."""
    kwargs = {}
    if title:
        kwargs["title"] = title
    if content is not None:
        kwargs["content"] = content
    if kwargs:
        await repo.update(note_id, **kwargs)
        await session.commit()

    note = await repo.get_by_id(note_id)
    response = templates.TemplateResponse("mobile/note_detail.html", {
        "request": request,
        "note": note,
        "active_page": "notes",
    })
    response.headers.update(_htmx_trigger("Notatka zapisana"))
    return response


@router.post("/notatki/{note_id}/delete")
async def mobile_note_delete(
    note_id: UUID,
    repo: NoteRepoDep,
    session: DbSession,
):
    """Delete a note."""
    await repo.delete(note_id)
    await session.commit()
    return RedirectResponse(url="/m/notatki", status_code=303)


# ============================================================================
# Receipts
# ============================================================================

@router.get("/paragony", response_class=HTMLResponse)
async def mobile_receipts(
    request: Request,
    repo: ReceiptRepoDep,
    store_repo: StoreRepoDep,
    store_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    offset: int = 0,
    limit: int = 20,
):
    """Receipts list in mobile view."""
    sid = int(store_id) if store_id and store_id.strip() else None
    d_from = date.fromisoformat(date_from) if date_from and date_from.strip() else None
    d_to = date.fromisoformat(date_to) if date_to and date_to.strip() else None

    receipts, total = await repo.get_recent_paginated(
        limit=limit, offset=offset, store_id=sid,
        date_from=d_from, date_to=d_to,
    )
    stores = await store_repo.get_all_with_aliases()

    ctx = {
        "request": request,
        "receipts": receipts,
        "total": total,
        "stores": stores,
        "filters": {"store_id": sid or "", "date_from": date_from or "", "date_to": date_to or ""},
        "offset": offset,
        "limit": limit,
        "active_page": "receipts",
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("mobile/partials/receipt_list.html", ctx)
    return templates.TemplateResponse("mobile/receipts.html", ctx)


@router.get("/paragony/{receipt_id}", response_class=HTMLResponse)
async def mobile_receipt_detail(request: Request, receipt_id: UUID, repo: ReceiptRepoDep):
    """Receipt detail view with items."""
    receipt = await repo.get_with_items(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Paragon nie znaleziony")
    return templates.TemplateResponse("mobile/receipt_detail.html", {
        "request": request,
        "receipt": receipt,
        "active_page": "receipts",
    })


# ============================================================================
# Knowledge (Bookmarks + RAG)
# ============================================================================

@router.get("/wiedza", response_class=HTMLResponse)
async def mobile_knowledge(
    request: Request,
    repo: BookmarkRepoDep,
    tab: str = "bookmarks",
    status: Optional[str] = None,
):
    """Knowledge base - bookmarks and RAG search."""
    bookmarks = []
    if tab == "bookmarks":
        if status and status != "all":
            bookmarks = await repo.get_by_status(status, limit=50)
        else:
            bookmarks = await repo.get_recent(limit=50)

    ctx = {
        "request": request,
        "bookmarks": bookmarks,
        "tab": tab,
        "status": status or "all",
        "active_page": "knowledge",
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("mobile/partials/bookmark_list.html", ctx)
    return templates.TemplateResponse("mobile/knowledge.html", ctx)


@router.post("/wiedza/{bookmark_id}/status", response_class=HTMLResponse)
async def mobile_bookmark_status(
    request: Request,
    bookmark_id: UUID,
    repo: BookmarkRepoDep,
    session: DbSession,
    status: str = Form(...),
):
    """Update bookmark status."""
    await repo.update(bookmark_id, status=status)
    await session.commit()

    bookmarks = await repo.get_recent(limit=50)
    response = templates.TemplateResponse("mobile/partials/bookmark_list.html", {
        "request": request,
        "bookmarks": bookmarks,
        "status": "all",
    })
    response.headers.update(_htmx_trigger("Status zmieniony"))
    return response


@router.post("/wiedza/szukaj", response_class=HTMLResponse)
async def mobile_rag_search(
    request: Request,
    session: DbSession,
    question: str = Form(...),
):
    """RAG search."""
    if not settings.RAG_ENABLED:
        return templates.TemplateResponse("mobile/partials/rag_results.html", {
            "request": request,
            "error": "Wyszukiwanie wiedzy jest wyłączone",
        })

    try:
        from app.rag import answerer

        result = await answerer.ask(question=question, session=session)
        return templates.TemplateResponse("mobile/partials/rag_results.html", {
            "request": request,
            "question": question,
            "answer": result.answer,
            "sources": result.sources,
            "model_used": result.model_used,
            "processing_time": result.processing_time_sec,
        })
    except Exception as e:
        logger.error(f"Mobile RAG search error: {e}")
        return templates.TemplateResponse("mobile/partials/rag_results.html", {
            "request": request,
            "error": "Wystąpił błąd podczas wyszukiwania",
        })


# ============================================================================
# Share target
# ============================================================================

ALLOWED_SHARE_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}


@router.post("/share", response_class=HTMLResponse)
async def mobile_share_target(
    request: Request,
    chat_repo: ChatRepoDep = None,
):
    """Handle share target from PWA manifest."""
    form = await request.form()

    title = form.get("title", "")
    text = form.get("text", "")
    url = form.get("url", "")
    image = form.get("image")

    # Validate image MIME type if present
    has_valid_image = False
    if image and hasattr(image, "content_type"):
        if image.content_type in ALLOWED_SHARE_IMAGE_TYPES:
            has_valid_image = True
        else:
            logger.warning(f"Share target: rejected image with content_type={image.content_type}")

    parts = []
    if title:
        parts.append(f"**{title}**")
    if text:
        parts.append(text)
    if url:
        parts.append(f"Link: {url}")

    shared_content = "\n".join(parts) if parts else None

    return templates.TemplateResponse(
        "mobile/chat.html",
        {
            "request": request,
            "messages": [],
            "session_id": None,
            "prefill_message": shared_content,
            "shared_image": has_valid_image,
            "active_page": "chat",
        }
    )
