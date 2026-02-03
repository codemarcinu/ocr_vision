"""Web UI routes using Jinja2 templates + HTMX."""

import json
import logging
import shutil
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.dependencies import (
    AnalyticsRepoDep,
    ArticleRepoDep,
    BookmarkRepoDep,
    DbSession,
    FeedbackRepoDep,
    FeedRepoDep,
    NoteRepoDep,
    PantryRepoDep,
    ProductRepoDep,
    ReceiptRepoDep,
    StoreRepoDep,
    EmbeddingRepoDep,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Web UI"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Store emoji map
STORE_EMOJIS = {
    "biedronka": "🐞", "lidl": "🔵", "kaufland": "🔴",
    "zabka": "🐸", "auchan": "🟠", "carrefour": "🔷",
    "netto": "🟡", "dino": "🦕", "rossmann": "🩷",
    "lewiatan": "🟢", "stokrotka": "🌼",
}

# Category emoji map
CATEGORY_EMOJIS = {
    "Nabial": "🥛", "Nabiał": "🥛", "Pieczywo": "🍞", "Mieso": "🥩", "Mięso": "🥩",
    "Wedliny": "🥓", "Wędliny": "🥓", "Ryby": "🐟", "Warzywa": "🥬",
    "Owoce": "🍎", "Napoje": "🥤", "Alkohol": "🍺",
    "Napoje gorace": "☕", "Napoje gorące": "☕", "Slodycze": "🍫", "Słodycze": "🍫",
    "Przekaski": "🥨", "Przekąski": "🥨", "Produkty sypkie": "🌾",
    "Przyprawy": "🧂", "Konserwy": "🥫", "Mrozonki": "🧊", "Mrożonki": "🧊",
    "Dania gotowe": "🍲", "Chemia": "🧴", "Kosmetyki": "💄",
    "Dla dzieci": "👶", "Dla zwierzat": "🐾", "Dla zwierząt": "🐾",
    "Inne": "📦",
}


def _store_emoji(name: str) -> str:
    if not name:
        return "🏪"
    key = name.lower().split(",")[0].split(" ")[0].strip()
    return STORE_EMOJIS.get(key, "🏪")


def _category_emoji(name: str) -> str:
    return CATEGORY_EMOJIS.get(name, "📦")


def _htmx_trigger(message: str, msg_type: str = "success") -> dict:
    return {"HX-Trigger": json.dumps({"showToast": {"message": message, "type": msg_type}})}


# Register template globals
templates.env.globals.update({
    "store_emoji": _store_emoji,
    "category_emoji": _category_emoji,
})


# ============================================================================
# Dashboard
# ============================================================================

@router.get("/app/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    receipt_repo: ReceiptRepoDep,
    pantry_repo: PantryRepoDep,
    feedback_repo: FeedbackRepoDep,
    article_repo: ArticleRepoDep,
):
    receipt_stats = await receipt_repo.get_summary_stats()
    pantry_stats = await pantry_repo.get_stats()
    unmatched_stats = await feedback_repo.get_unmatched_stats()
    recent_receipts = await receipt_repo.get_recent(limit=5)
    recent_articles = await article_repo.get_recent(limit=5)
    unread_count = await article_repo.get_unread_count()

    return templates.TemplateResponse("dashboard/index.html", {
        "request": request,
        "receipt_stats": receipt_stats,
        "pantry_stats": pantry_stats,
        "unmatched_count": unmatched_stats.get("total", 0) if isinstance(unmatched_stats, dict) else 0,
        "unread_articles": unread_count,
        "recent_receipts": recent_receipts,
        "recent_articles": recent_articles,
    })


# ============================================================================
# Receipts
# ============================================================================

@router.get("/app/paragony/", response_class=HTMLResponse)
async def receipt_list(
    request: Request,
    repo: ReceiptRepoDep,
    store_repo: StoreRepoDep,
    store_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    offset: int = 0,
    limit: int = 20,
):
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
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("receipts/partials/table_rows.html", ctx)
    return templates.TemplateResponse("receipts/list.html", ctx)


@router.get("/app/paragony/upload", response_class=HTMLResponse)
async def receipt_upload_page(request: Request):
    return templates.TemplateResponse("receipts/upload.html", {"request": request})


@router.post("/app/paragony/upload", response_class=HTMLResponse)
async def receipt_upload(request: Request, file: UploadFile = File(...)):
    if not file.filename:
        return templates.TemplateResponse("receipts/partials/upload_result.html", {
            "request": request, "success": False, "error": "Brak nazwy pliku",
        })

    suffix = Path(file.filename).suffix.lower()
    if suffix not in settings.SUPPORTED_FORMATS:
        return templates.TemplateResponse("receipts/partials/upload_result.html", {
            "request": request, "success": False,
            "error": f"Nieobslugiwany format. Dozwolone: {', '.join(settings.SUPPORTED_FORMATS)}",
        })

    settings.ensure_directories()
    inbox_path = settings.INBOX_DIR / file.filename
    with open(inbox_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Process using the existing pipeline
    from app.main import _process_file
    result = await _process_file(inbox_path)

    return templates.TemplateResponse("receipts/partials/upload_result.html", {
        "request": request,
        "success": result.success,
        "result": result,
        "error": result.error,
    })


@router.get("/app/paragony/{receipt_id}", response_class=HTMLResponse)
async def receipt_detail(request: Request, receipt_id: UUID, repo: ReceiptRepoDep):
    receipt = await repo.get_with_items(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Paragon nie znaleziony")
    return templates.TemplateResponse("receipts/detail.html", {
        "request": request, "receipt": receipt,
    })


@router.post("/app/paragony/{receipt_id}/update", response_class=HTMLResponse)
async def receipt_update(
    request: Request,
    receipt_id: UUID,
    repo: ReceiptRepoDep,
    store_raw: Optional[str] = Form(None),
    receipt_date: Optional[str] = Form(None),
    total_final: Optional[str] = Form(None),
):
    kwargs = {}
    if store_raw:
        kwargs["store_raw"] = store_raw
    if receipt_date:
        kwargs["receipt_date"] = date.fromisoformat(receipt_date)
    if total_final:
        kwargs["total_final"] = Decimal(total_final)

    if kwargs:
        await repo.update(receipt_id, **kwargs)

    receipt = await repo.get_with_items(receipt_id)
    response = templates.TemplateResponse("receipts/detail.html", {
        "request": request, "receipt": receipt,
    })
    response.headers.update(_htmx_trigger("Paragon zaktualizowany"))
    return response


@router.post("/app/paragony/{receipt_id}/items/{item_id}/update", response_class=HTMLResponse)
async def receipt_item_update(
    request: Request,
    receipt_id: UUID,
    item_id: int,
    repo: ReceiptRepoDep,
    name_normalized: Optional[str] = Form(None),
    price_final: Optional[str] = Form(None),
):
    kwargs = {}
    if name_normalized:
        kwargs["name_normalized"] = name_normalized
    if price_final:
        kwargs["price_final"] = Decimal(price_final)

    if kwargs:
        await repo.update_item(item_id, **kwargs)

    receipt = await repo.get_with_items(receipt_id)
    response = templates.TemplateResponse("receipts/partials/table_rows.html", {
        "request": request, "receipt": receipt,
    })
    response.headers.update(_htmx_trigger("Produkt zaktualizowany"))
    return response


@router.post("/app/paragony/{receipt_id}/delete")
async def receipt_delete(receipt_id: UUID, repo: ReceiptRepoDep):
    await repo.delete(receipt_id)
    return RedirectResponse(url="/app/paragony/", status_code=303)


# ============================================================================
# Pantry
# ============================================================================

@router.get("/app/spizarnia/", response_class=HTMLResponse)
async def pantry_page(
    request: Request,
    repo: PantryRepoDep,
    q: Optional[str] = None,
    include_consumed: bool = False,
):
    stats = await repo.get_stats()

    if q:
        items = await repo.search(q, include_consumed=include_consumed)
        grouped = {}
        for item in items:
            cat = item.category.name if item.category else "Inne"
            grouped.setdefault(cat, []).append(item)
    else:
        grouped = await repo.get_grouped_by_category()

    ctx = {
        "request": request,
        "stats": stats,
        "grouped": grouped,
        "q": q or "",
        "include_consumed": include_consumed,
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("pantry/partials/items_grouped.html", ctx)
    return templates.TemplateResponse("pantry/index.html", ctx)


@router.post("/app/spizarnia/consume", response_class=HTMLResponse)
async def pantry_consume(request: Request, repo: PantryRepoDep, item_ids: str = Form("")):
    ids = [int(x) for x in item_ids.split(",") if x.strip().isdigit()]
    if ids:
        await repo.consume_items_batch(ids)

    grouped = await repo.get_grouped_by_category()
    stats = await repo.get_stats()
    response = templates.TemplateResponse("pantry/partials/items_grouped.html", {
        "request": request, "grouped": grouped, "stats": stats, "q": "",
    })
    response.headers.update(_htmx_trigger(f"Zuzytych produktow: {len(ids)}"))
    return response


@router.post("/app/spizarnia/add", response_class=HTMLResponse)
async def pantry_add(
    request: Request,
    repo: PantryRepoDep,
    name: str = Form(...),
    category: Optional[str] = Form(None),
):
    from app.db.models import Category
    from sqlalchemy import select

    category_id = None
    if category:
        result = await repo.session.execute(select(Category).where(Category.name == category))
        cat = result.scalar_one_or_none()
        if cat:
            category_id = cat.id

    await repo.add_from_receipt(
        receipt_item_id=None, product_id=None,
        name=name, category_id=category_id,
        store_id=None, purchase_date=date.today(),
        quantity=Decimal("1"),
    )

    grouped = await repo.get_grouped_by_category()
    stats = await repo.get_stats()
    response = templates.TemplateResponse("pantry/partials/items_grouped.html", {
        "request": request, "grouped": grouped, "stats": stats, "q": "",
    })
    response.headers.update(_htmx_trigger(f"Dodano: {name}"))
    return response


@router.get("/app/spizarnia/partials/add-form", response_class=HTMLResponse)
async def pantry_add_form(request: Request):
    return templates.TemplateResponse("pantry/partials/add_form.html", {
        "request": request, "categories": settings.CATEGORIES,
    })


# ============================================================================
# Analytics
# ============================================================================

@router.get("/app/analityka/", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    repo: AnalyticsRepoDep,
    tab: str = "spending",
):
    data = {}

    if tab == "spending":
        data["monthly"] = await repo.get_monthly_breakdown()
        data["by_category"] = await repo.get_spending_by_category()
    elif tab == "stores":
        data["by_store"] = await repo.get_spending_by_store()
    elif tab == "categories":
        data["by_category"] = await repo.get_spending_by_category()
    elif tab == "trends":
        data["top_products"] = await repo.get_top_products(limit=20, by="count")

    ctx = {
        "request": request, "tab": tab, "data": data,
        "data_json": json.dumps(data, default=str),
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(f"analytics/partials/{tab}_chart.html", ctx)
    return templates.TemplateResponse("analytics/index.html", ctx)


@router.get("/app/analityka/trends/{product_id}", response_class=HTMLResponse)
async def analytics_trends(
    request: Request, product_id: int, repo: AnalyticsRepoDep,
    months: int = 6,
):
    trends = await repo.get_price_trends(product_id, months)
    return templates.TemplateResponse("analytics/partials/trends_chart.html", {
        "request": request, "product_id": product_id,
        "trends": trends, "trends_json": json.dumps(trends, default=str),
    })


# ============================================================================
# Articles
# ============================================================================

@router.get("/app/artykuly/", response_class=HTMLResponse)
async def articles_page(
    request: Request,
    article_repo: ArticleRepoDep,
    feed_repo: FeedRepoDep,
    tab: str = "articles",
):
    articles = await article_repo.get_recent(limit=30)
    feeds = await feed_repo.get_all()
    unread = await article_repo.get_unread_count()

    ctx = {
        "request": request, "articles": articles, "feeds": feeds,
        "unread_count": unread, "tab": tab,
    }

    if request.headers.get("HX-Request"):
        tpl = "articles/partials/article_list.html" if tab == "articles" else "articles/partials/feed_list.html"
        return templates.TemplateResponse(tpl, ctx)
    return templates.TemplateResponse("articles/index.html", ctx)


@router.post("/app/artykuly/feeds/add", response_class=HTMLResponse)
async def add_feed(request: Request, feed_repo: FeedRepoDep, url: str = Form(...), name: str = Form("")):
    from app.rss_fetcher import detect_feed_type
    feed_type = detect_feed_type(url)
    feed = await feed_repo.create(name=name or url, feed_url=url, feed_type=feed_type)

    feeds = await feed_repo.get_all()
    response = templates.TemplateResponse("articles/partials/feed_list.html", {
        "request": request, "feeds": feeds,
    })
    response.headers.update(_htmx_trigger("Feed dodany"))
    return response


@router.post("/app/artykuly/feeds/{feed_id}/delete", response_class=HTMLResponse)
async def delete_feed(request: Request, feed_id: int, feed_repo: FeedRepoDep):
    await feed_repo.delete(feed_id)
    feeds = await feed_repo.get_all()
    response = templates.TemplateResponse("articles/partials/feed_list.html", {
        "request": request, "feeds": feeds,
    })
    response.headers.update(_htmx_trigger("Feed usuniety"))
    return response


@router.post("/app/artykuly/refresh", response_class=HTMLResponse)
async def refresh_feeds(request: Request, article_repo: ArticleRepoDep, feed_repo: FeedRepoDep):
    from app.rss_fetcher import fetch_feed
    from app.web_scraper import scrape_url
    from app.summarizer import summarize_content
    from app.summary_writer import write_summary_file_simple

    feeds = await feed_repo.get_all()
    new_count = 0

    for feed in feeds:
        if not feed.is_active:
            continue
        try:
            entries = await fetch_feed(feed.feed_url)
            for entry in entries[:settings.RSS_MAX_ARTICLES_PER_FEED]:
                existing = await article_repo.get_by_url(entry.get("link", ""))
                if existing:
                    continue
                article = await article_repo.create_article(
                    feed_id=feed.id,
                    title=entry.get("title", ""),
                    url=entry.get("link", ""),
                    external_id=entry.get("id", ""),
                    published_date=None,
                )
                new_count += 1
            await feed_repo.update_last_fetched(feed.id)
        except Exception as e:
            logger.warning(f"Failed to fetch feed {feed.name}: {e}")

    articles = await article_repo.get_recent(limit=30)
    response = templates.TemplateResponse("articles/partials/article_list.html", {
        "request": request, "articles": articles,
    })
    response.headers.update(_htmx_trigger(f"Odswiezono - {new_count} nowych artykulow"))
    return response


@router.post("/app/artykuly/summarize", response_class=HTMLResponse)
async def summarize_url(request: Request, url: str = Form(...)):
    from app.web_scraper import scrape_url
    from app.summarizer import summarize_content

    try:
        scraped, scrape_error = await scrape_url(url)
        if not scraped or not scraped.content:
            return templates.TemplateResponse("articles/partials/summarize_result.html", {
                "request": request, "success": False,
                "error": scrape_error or "Nie udalo sie pobrac tresci",
            })

        result, sum_error = await summarize_content(scraped.content)
        if not result:
            return templates.TemplateResponse("articles/partials/summarize_result.html", {
                "request": request, "success": False,
                "error": sum_error or "Podsumowanie nie powiodlo sie",
            })
        return templates.TemplateResponse("articles/partials/summarize_result.html", {
            "request": request, "success": True, "result": result,
            "title": scraped.title or url, "url": url,
        })
    except Exception as e:
        return templates.TemplateResponse("articles/partials/summarize_result.html", {
            "request": request, "success": False, "error": str(e),
        })


# ============================================================================
# Transcriptions
# ============================================================================

@router.get("/app/transkrypcje/", response_class=HTMLResponse)
async def transcriptions_page(request: Request, session: DbSession):
    from app.db.repositories.transcription import TranscriptionJobRepository
    repo = TranscriptionJobRepository(session)
    jobs = await repo.get_recent_jobs(limit=20)
    return templates.TemplateResponse("transcriptions/list.html", {
        "request": request, "jobs": jobs,
    })


@router.get("/app/transkrypcje/{job_id}", response_class=HTMLResponse)
async def transcription_detail(request: Request, job_id: UUID, session: DbSession):
    from app.db.repositories.transcription import TranscriptionJobRepository
    repo = TranscriptionJobRepository(session)
    job = await repo.get_with_transcription(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job nie znaleziony")
    return templates.TemplateResponse("transcriptions/detail.html", {
        "request": request, "job": job,
    })


@router.post("/app/transkrypcje/new", response_class=HTMLResponse)
async def transcription_new(request: Request, session: DbSession, url: str = Form(...)):
    from app.db.repositories.transcription import TranscriptionJobRepository
    repo = TranscriptionJobRepository(session)
    job = await repo.create_job(source_type="youtube", source_url=url, title=url)
    await session.commit()

    jobs = await repo.get_recent_jobs(limit=20)
    response = templates.TemplateResponse("transcriptions/partials/job_list.html", {
        "request": request, "jobs": jobs,
    })
    response.headers.update(_htmx_trigger("Transkrypcja dodana do kolejki"))
    return response


# ============================================================================
# Notes
# ============================================================================

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
    response.headers.update(_htmx_trigger("Notatka usunieta"))
    return response


# ============================================================================
# Bookmarks
# ============================================================================

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
    response.headers.update(_htmx_trigger("Zakladka usunieta"))
    return response


# ============================================================================
# Dictionary
# ============================================================================

@router.get("/app/slownik/", response_class=HTMLResponse)
async def dictionary_page(
    request: Request,
    feedback_repo: FeedbackRepoDep,
    tab: str = "unmatched",
):
    ctx = {"request": request, "tab": tab}

    if tab == "unmatched":
        ctx["unmatched"] = await feedback_repo.get_unmatched(limit=50)
    # Products and shortcuts are loaded via HTMX partials

    return templates.TemplateResponse("dictionary/index.html", ctx)


@router.get("/app/slownik/partials/unmatched", response_class=HTMLResponse)
async def dictionary_unmatched(request: Request, feedback_repo: FeedbackRepoDep):
    unmatched = await feedback_repo.get_unmatched(limit=50)
    return templates.TemplateResponse("dictionary/partials/unmatched_list.html", {
        "request": request, "unmatched": unmatched,
    })


@router.post("/app/slownik/learn/{raw_name}", response_class=HTMLResponse)
async def dictionary_learn(
    request: Request,
    raw_name: str,
    feedback_repo: FeedbackRepoDep,
    product_repo: ProductRepoDep,
    normalized_name: str = Form(...),
    category: str = Form("Inne"),
):
    # Create or find the product, then mark unmatched as learned
    product = await product_repo.get_by_normalized_name(normalized_name)
    if not product:
        product = await product_repo.create_with_variant(
            normalized_name=normalized_name,
            raw_name=raw_name,
        )
    else:
        await product_repo.add_variant(product.id, raw_name)
    await feedback_repo.learn_product(raw_name, product.id)

    unmatched = await feedback_repo.get_unmatched(limit=50)
    response = templates.TemplateResponse("dictionary/partials/unmatched_list.html", {
        "request": request, "unmatched": unmatched,
    })
    response.headers.update(_htmx_trigger(f"Nauczone: {raw_name}"))
    return response


# ============================================================================
# Search
# ============================================================================

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


# ============================================================================
# Ask AI
# ============================================================================

@router.get("/app/zapytaj/", response_class=HTMLResponse)
async def ask_page(request: Request):
    return templates.TemplateResponse("ask/index.html", {"request": request})


@router.post("/app/zapytaj/", response_class=HTMLResponse)
async def ask_submit(request: Request, question: str = Form(...)):
    if not settings.RAG_ENABLED:
        return templates.TemplateResponse("ask/partials/answer.html", {
            "request": request, "error": "RAG jest wylaczony",
        })

    try:
        from app.db.connection import get_session
        from app.rag import answerer

        async for session in get_session():
            result = await answerer.ask(question=question, session=session)
            return templates.TemplateResponse("ask/partials/answer.html", {
                "request": request,
                "question": question,
                "answer": result.answer,
                "sources": result.sources,
                "model_used": result.model_used,
                "processing_time": result.processing_time_sec,
                "chunks_found": result.chunks_found,
            })
    except Exception as e:
        logger.error(f"Ask error: {e}")
        return templates.TemplateResponse("ask/partials/answer.html", {
            "request": request, "question": question, "error": str(e),
        })


# ============================================================================
# Redirects from old URLs
# ============================================================================

@router.get("/web/dictionary")
async def redirect_dictionary():
    return RedirectResponse(url="/app/slownik/", status_code=301)

@router.get("/web/pantry")
async def redirect_pantry():
    return RedirectResponse(url="/app/spizarnia/", status_code=301)

@router.get("/web/receipts")
async def redirect_receipts():
    return RedirectResponse(url="/app/paragony/", status_code=301)

@router.get("/web/search")
async def redirect_search():
    return RedirectResponse(url="/app/szukaj/", status_code=301)
