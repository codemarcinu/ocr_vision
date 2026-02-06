"""Command Palette (Ctrl+K) - global search + quick actions."""

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.dependencies import DbSession
from app.web.helpers import templates

router = APIRouter()

# Static commands available without search query
STATIC_COMMANDS = [
    {"icon": "bi-upload", "label": "Nowy paragon", "url": "/app/paragony/upload", "section": "Akcje"},
    {"icon": "bi-journal-plus", "label": "Nowa notatka", "url": "/app/notatki/", "section": "Akcje", "hint": "formularz"},
    {"icon": "bi-bookmark-plus", "label": "Nowa zakladka", "url": "/app/zakladki/", "section": "Akcje", "hint": "formularz"},
    {"icon": "bi-grid-1x2", "label": "Dashboard", "url": "/app/", "section": "Nawigacja"},
    {"icon": "bi-receipt", "label": "Paragony", "url": "/app/paragony/", "section": "Nawigacja"},
    {"icon": "bi-box-seam", "label": "Spizarnia", "url": "/app/spizarnia/", "section": "Nawigacja"},
    {"icon": "bi-graph-up", "label": "Analityka", "url": "/app/analityka/", "section": "Nawigacja"},
    {"icon": "bi-newspaper", "label": "Artykuly", "url": "/app/artykuly/", "section": "Nawigacja"},
    {"icon": "bi-mic", "label": "Transkrypcje", "url": "/app/transkrypcje/", "section": "Nawigacja"},
    {"icon": "bi-journal-text", "label": "Notatki", "url": "/app/notatki/", "section": "Nawigacja"},
    {"icon": "bi-bookmark", "label": "Zakladki", "url": "/app/zakladki/", "section": "Nawigacja"},
    {"icon": "bi-search", "label": "Szukaj", "url": "/app/szukaj/", "section": "Nawigacja"},
    {"icon": "bi-chat-left-text", "label": "Czat AI", "url": "/app/czat/", "section": "Nawigacja"},
    {"icon": "bi-chat-dots", "label": "Zapytaj AI", "url": "/app/zapytaj/", "section": "Nawigacja"},
    {"icon": "bi-book", "label": "Slownik", "url": "/app/slownik/", "section": "Nawigacja"},
]


@router.get("/app/command-palette", response_class=HTMLResponse)
async def command_palette_search(
    request: Request,
    session: DbSession,
    q: Optional[str] = None,
):
    """Return command palette results as HTML partial."""
    items = []

    if not q or len(q) < 2:
        # Show static commands grouped by section
        return templates.TemplateResponse("components/command_palette_results.html", {
            "request": request,
            "items": STATIC_COMMANDS,
            "has_query": False,
        })

    # Filter static commands by query
    q_lower = q.lower()
    matched_commands = [
        cmd for cmd in STATIC_COMMANDS
        if q_lower in cmd["label"].lower()
    ]

    # Search content in DB
    from app.search_api import (
        _search_receipts, _search_articles, _search_notes,
        _search_bookmarks, _search_transcriptions,
    )

    pattern = f"%{q}%"
    content_items = []

    for search_func in [_search_notes, _search_receipts, _search_articles, _search_bookmarks, _search_transcriptions]:
        type_name, found = await search_func(session, pattern, 5)
        for item in found:
            content_items.append(_format_content_item(type_name, item))

    return templates.TemplateResponse("components/command_palette_results.html", {
        "request": request,
        "items": matched_commands,
        "content_items": content_items[:15],
        "has_query": True,
        "query": q,
    })


TYPE_ICONS = {
    "receipt": "bi-receipt",
    "article": "bi-newspaper",
    "note": "bi-journal-text",
    "bookmark": "bi-bookmark",
    "transcription": "bi-mic",
}

TYPE_LABELS = {
    "receipt": "Paragon",
    "article": "Artykul",
    "note": "Notatka",
    "bookmark": "Zakladka",
    "transcription": "Transkrypcja",
}

TYPE_URLS = {
    "receipt": "/app/paragony/{id}",
    "article": "/app/artykuly/{id}",
    "note": "/app/notatki/{id}",
    "bookmark": "/app/zakladki/{id}",
    "transcription": "/app/transkrypcje/{id}",
}


def _format_content_item(type_name: str, item: dict) -> dict:
    item_id = item.get("id") or item.get("receipt_id", "")
    url_template = TYPE_URLS.get(type_name, "/app/")

    # For receipt items, link to the receipt
    if type_name == "receipt":
        item_id = item.get("receipt_id", item_id)

    return {
        "icon": TYPE_ICONS.get(type_name, "bi-file-text"),
        "label": item.get("title") or item.get("name") or item.get("name_raw", ""),
        "url": url_template.format(id=item_id),
        "section": TYPE_LABELS.get(type_name, type_name),
        "hint": item.get("store") or item.get("category") or item.get("status") or "",
    }
