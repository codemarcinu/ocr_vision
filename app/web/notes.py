"""Notes web routes."""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.dependencies import NoteRepoDep
from app.web.helpers import _htmx_trigger, templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/app/notatki/", response_class=HTMLResponse)
async def notes_page(
    request: Request, repo: NoteRepoDep,
    search: Optional[str] = None,
):
    if search:
        notes = await repo.search(search, limit=50)
    else:
        notes = await repo.get_recent(limit=50)

    ctx = {"request": request, "notes": notes, "search": search or ""}

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("notes/partials/note_list.html", ctx)
    return templates.TemplateResponse("notes/index.html", ctx)


@router.get("/app/notatki/{note_id}/detail", response_class=HTMLResponse)
async def note_detail(request: Request, note_id: UUID, repo: NoteRepoDep):
    note = await repo.get_by_id(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Notatka nie znaleziona")
    return templates.TemplateResponse("notes/partials/note_detail.html", {
        "request": request, "note": note,
    })


@router.post("/app/notatki/create", response_class=HTMLResponse)
async def note_create(
    request: Request, repo: NoteRepoDep,
    title: str = Form(...), content: str = Form(""),
):
    note = await repo.create(title=title, content=content or title)
    from app.db.connection import get_session
    async for session in get_session():
        await session.commit()

    # Write to Obsidian
    if settings.GENERATE_OBSIDIAN_FILES:
        from app.writers.notes import write_note_file
        write_note_file(note)

    # RAG indexing
    if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
        try:
            from app.rag.hooks import index_note_hook
            async for session in get_session():
                await index_note_hook(note, session)
                await session.commit()
        except Exception:
            pass

    notes = await repo.get_recent(limit=50)
    response = templates.TemplateResponse("notes/partials/note_list.html", {
        "request": request, "notes": notes,
    })
    response.headers.update(_htmx_trigger("Notatka utworzona"))
    return response


@router.post("/app/notatki/{note_id}/update", response_class=HTMLResponse)
async def note_update(
    request: Request, note_id: UUID, repo: NoteRepoDep,
    title: Optional[str] = Form(None),
    content: Optional[str] = Form(None),
):
    kwargs = {}
    if title:
        kwargs["title"] = title
    if content is not None:
        kwargs["content"] = content
    if kwargs:
        await repo.update(note_id, **kwargs)
        from app.db.connection import get_session
        async for session in get_session():
            await session.commit()

    note = await repo.get_by_id(note_id)
    response = templates.TemplateResponse("notes/partials/note_detail.html", {
        "request": request, "note": note,
    })
    response.headers.update(_htmx_trigger("Notatka zapisana"))
    return response


@router.post("/app/notatki/{note_id}/delete", response_class=HTMLResponse)
async def note_delete(request: Request, note_id: UUID, repo: NoteRepoDep):
    await repo.delete(note_id)
    from app.db.connection import get_session
    async for session in get_session():
        await session.commit()

    notes = await repo.get_recent(limit=50)
    response = templates.TemplateResponse("notes/partials/note_list.html", {
        "request": request, "notes": notes,
    })
    response.headers.update(_htmx_trigger("Notatka usunięta"))
    return response
