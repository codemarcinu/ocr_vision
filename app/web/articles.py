"""Articles/RSS web routes."""

import logging
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.dependencies import ArticleRepoDep, FeedRepoDep
from app.web.helpers import _htmx_trigger, templates

logger = logging.getLogger(__name__)

router = APIRouter()


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
    response.headers.update(_htmx_trigger("Feed usunięty"))
    return response


@router.post("/app/artykuly/refresh", response_class=HTMLResponse)
async def refresh_feeds(request: Request, article_repo: ArticleRepoDep, feed_repo: FeedRepoDep):
    from app.rss_fetcher import fetch_feed
    from app.web_scraper import scrape_url
    from app.summarizer import summarize_content
    from app.writers.summary import write_summary_file_simple

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
    response.headers.update(_htmx_trigger(f"Odświeżono - {new_count} nowych artykułów"))
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
                "error": scrape_error or "Nie udało się pobrać treści",
            })

        result, sum_error = await summarize_content(scraped.content)
        if not result:
            return templates.TemplateResponse("articles/partials/summarize_result.html", {
                "request": request, "success": False,
                "error": sum_error or "Podsumowanie nie powiodło się",
            })
        return templates.TemplateResponse("articles/partials/summarize_result.html", {
            "request": request, "success": True, "result": result,
            "title": scraped.title or url, "url": url,
        })
    except Exception as e:
        logger.error(f"Summarize URL failed: {e}")
        return templates.TemplateResponse("articles/partials/summarize_result.html", {
            "request": request, "success": False, "error": "Wystąpił błąd podczas podsumowywania",
        })
