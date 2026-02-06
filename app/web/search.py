"""Search web routes."""

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.dependencies import DbSession
from app.web.helpers import templates

router = APIRouter()


@router.get("/app/szukaj/", response_class=HTMLResponse)
async def search_page(
    request: Request,
    session: DbSession,
    q: Optional[str] = None,
    types: Optional[str] = None,
):
    results = {}
    total = 0

    if q and len(q) >= 2:
        # Reuse existing search logic
        from app.search_api import (
            _search_receipts, _search_articles, _search_notes,
            _search_bookmarks, _search_transcriptions,
        )

        pattern = f"%{q}%"
        allowed_types = {"receipt", "article", "note", "bookmark", "transcription"}
        search_types = allowed_types
        if types:
            search_types = {t.strip() for t in types.split(",") if t.strip() in allowed_types}

        for search_func in [_search_receipts, _search_articles, _search_notes, _search_bookmarks, _search_transcriptions]:
            type_name, items = await search_func(session, pattern, 10)
            if type_name in search_types and items:
                results[type_name] = items

        total = sum(len(v) for v in results.values())

    ctx = {
        "request": request, "q": q or "", "results": results,
        "total": total, "types": types or "",
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("search/partials/results.html", ctx)
    return templates.TemplateResponse("search/index.html", ctx)
