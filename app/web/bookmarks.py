"""Bookmarks web routes."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.dependencies import BookmarkRepoDep
from app.web.helpers import _htmx_trigger, templates

router = APIRouter()


@router.get("/app/zakladki/", response_class=HTMLResponse)
async def bookmarks_page(
    request: Request, repo: BookmarkRepoDep,
    status: Optional[str] = None,
):
    if status:
        bookmarks = await repo.get_by_status(status, limit=50)
    else:
        bookmarks = await repo.get_recent(limit=50)

    ctx = {"request": request, "bookmarks": bookmarks, "status": status or "all"}

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("bookmarks/partials/bookmark_list.html", ctx)
    return templates.TemplateResponse("bookmarks/index.html", ctx)


@router.post("/app/zakladki/add", response_class=HTMLResponse)
async def bookmark_add(
    request: Request, repo: BookmarkRepoDep,
    url: str = Form(...), title: str = Form(""),
):
    existing = await repo.get_by_url(url)
    if existing:
        bookmarks = await repo.get_recent(limit=50)
        response = templates.TemplateResponse("bookmarks/partials/bookmark_list.html", {
            "request": request, "bookmarks": bookmarks, "status": "all",
        })
        response.headers.update(_htmx_trigger("Zakladka juz istnieje", "warning"))
        return response

    await repo.create_from_url(url=url, title=title or url, source="web")
    from app.db.connection import get_session
    async for session in get_session():
        await session.commit()

    bookmarks = await repo.get_recent(limit=50)
    response = templates.TemplateResponse("bookmarks/partials/bookmark_list.html", {
        "request": request, "bookmarks": bookmarks, "status": "all",
    })
    response.headers.update(_htmx_trigger("Zakladka dodana"))
    return response


@router.post("/app/zakladki/{bookmark_id}/status", response_class=HTMLResponse)
async def bookmark_status(
    request: Request, bookmark_id: UUID, repo: BookmarkRepoDep,
    status: str = Form(...),
):
    await repo.update(bookmark_id, status=status)
    from app.db.connection import get_session
    async for session in get_session():
        await session.commit()

    bookmarks = await repo.get_recent(limit=50)
    response = templates.TemplateResponse("bookmarks/partials/bookmark_list.html", {
        "request": request, "bookmarks": bookmarks, "status": "all",
    })
    response.headers.update(_htmx_trigger("Status zmieniony"))
    return response


@router.post("/app/zakladki/{bookmark_id}/delete", response_class=HTMLResponse)
async def bookmark_delete(request: Request, bookmark_id: UUID, repo: BookmarkRepoDep):
    await repo.delete(bookmark_id)
    from app.db.connection import get_session
    async for session in get_session():
        await session.commit()

    bookmarks = await repo.get_recent(limit=50)
    response = templates.TemplateResponse("bookmarks/partials/bookmark_list.html", {
        "request": request, "bookmarks": bookmarks, "status": "all",
    })
    response.headers.update(_htmx_trigger("Zakładka usunięta"))
    return response
