"""REST API for RSS feed management."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl

from typing import Tuple

from app.config import settings
from app.db.connection import get_session
from app.db.repositories.rss import ArticleRepository, RssFeedRepository
from app.rss_fetcher import detect_feed_type, fetch_feed
from app.summarizer import summarize_content
from app.writers.summary import write_summary_file, write_summary_file_simple
from app.web_scraper import scrape_url, scrape_with_fallback

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rss", tags=["RSS"])


# Pydantic models for API
class FeedCreate(BaseModel):
    url: HttpUrl
    name: Optional[str] = None


class FeedResponse(BaseModel):
    id: int
    name: str
    feed_url: str
    feed_type: Optional[str]
    is_active: bool
    last_fetched: Optional[str]
    last_error: Optional[str]


class ArticleResponse(BaseModel):
    id: int
    title: str
    url: Optional[str]
    summary: Optional[str]
    source: Optional[str]
    fetched_date: str
    is_read: bool


class SummarizeRequest(BaseModel):
    url: HttpUrl


class SummarizeResponse(BaseModel):
    title: str
    url: str
    summary: str
    model_used: str
    processing_time_sec: float
    tags: List[str] = []
    category: Optional[str] = None
    entities: List[str] = []


class RefreshResponse(BaseModel):
    new_articles: int
    errors: List[str]


@router.get("/feeds", response_model=List[FeedResponse])
async def list_feeds():
    """List all RSS feeds."""
    async for session in get_session():
        repo = RssFeedRepository(session)
        feeds = await repo.get_active_feeds()
        return [
            FeedResponse(
                id=f.id,
                name=f.name,
                feed_url=f.feed_url,
                feed_type=f.feed_type,
                is_active=f.is_active,
                last_fetched=f.last_fetched.isoformat() if f.last_fetched else None,
                last_error=f.last_error,
            )
            for f in feeds
        ]


@router.get("/feeds/{feed_id}", response_model=FeedResponse)
async def get_feed(feed_id: int):
    """Get single feed by ID."""
    async for session in get_session():
        repo = RssFeedRepository(session)
        feed = await repo.get_by_id(feed_id)
        if not feed:
            raise HTTPException(status_code=404, detail="Feed not found")
        return FeedResponse(
            id=feed.id,
            name=feed.name,
            feed_url=feed.feed_url,
            feed_type=feed.feed_type,
            is_active=feed.is_active,
            last_fetched=feed.last_fetched.isoformat() if feed.last_fetched else None,
            last_error=feed.last_error,
        )


@router.post("/feeds", response_model=FeedResponse)
async def add_feed(data: FeedCreate):
    """Add new RSS feed subscription."""
    url = str(data.url)

    async for session in get_session():
        repo = RssFeedRepository(session)

        # Check if exists
        existing = await repo.get_by_url(url)
        if existing:
            raise HTTPException(status_code=400, detail="Feed already exists")

        # Detect type and fetch info
        feed_type, error = await detect_feed_type(url)
        if error:
            raise HTTPException(status_code=400, detail=error)

        if feed_type == "webpage":
            raise HTTPException(status_code=400, detail="URL is not an RSS/Atom feed")

        feed_info, error = await fetch_feed(url)
        if error:
            raise HTTPException(status_code=400, detail=error)

        name = data.name or feed_info.title
        feed = await repo.create(name=name, feed_url=url, feed_type=feed_type)
        await session.commit()

        return FeedResponse(
            id=feed.id,
            name=feed.name,
            feed_url=feed.feed_url,
            feed_type=feed.feed_type,
            is_active=feed.is_active,
            last_fetched=None,
            last_error=None,
        )


@router.delete("/feeds/{feed_id}")
async def delete_feed(feed_id: int):
    """Delete RSS feed subscription."""
    async for session in get_session():
        repo = RssFeedRepository(session)
        success = await repo.delete(feed_id)
        if not success:
            raise HTTPException(status_code=404, detail="Feed not found")
        await session.commit()
        return {"success": True}


@router.patch("/feeds/{feed_id}")
async def update_feed(feed_id: int, is_active: Optional[bool] = None, name: Optional[str] = None):
    """Update feed settings."""
    async for session in get_session():
        repo = RssFeedRepository(session)
        updates = {}
        if is_active is not None:
            updates["is_active"] = is_active
        if name is not None:
            updates["name"] = name

        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")

        feed = await repo.update(feed_id, **updates)
        if not feed:
            raise HTTPException(status_code=404, detail="Feed not found")

        await session.commit()
        return FeedResponse(
            id=feed.id,
            name=feed.name,
            feed_url=feed.feed_url,
            feed_type=feed.feed_type,
            is_active=feed.is_active,
            last_fetched=feed.last_fetched.isoformat() if feed.last_fetched else None,
            last_error=feed.last_error,
        )


@router.get("/articles", response_model=List[ArticleResponse])
async def list_articles(
    feed_id: Optional[int] = None,
    limit: int = 20,
):
    """List recent articles."""
    async for session in get_session():
        repo = ArticleRepository(session)
        articles = await repo.get_recent(feed_id=feed_id, limit=limit)
        return [
            ArticleResponse(
                id=a.id,
                title=a.title,
                url=a.url,
                summary=a.summary.summary_text if a.summary else None,
                source=a.feed.name if a.feed else None,
                fetched_date=a.fetched_date.isoformat(),
                is_read=a.is_read,
            )
            for a in articles
        ]


@router.get("/articles/{article_id}", response_model=ArticleResponse)
async def get_article(article_id: int):
    """Get single article by ID."""
    async for session in get_session():
        repo = ArticleRepository(session)
        articles = await repo.get_recent(limit=1000)  # Workaround - load with relations
        article = next((a for a in articles if a.id == article_id), None)
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        return ArticleResponse(
            id=article.id,
            title=article.title,
            url=article.url,
            summary=article.summary.summary_text if article.summary else None,
            source=article.feed.name if article.feed else None,
            fetched_date=article.fetched_date.isoformat(),
            is_read=article.is_read,
        )


@router.post("/articles/{article_id}/read")
async def mark_article_read(article_id: int):
    """Mark article as read."""
    async for session in get_session():
        repo = ArticleRepository(session)
        article = await repo.mark_as_read(article_id)
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        await session.commit()
        return {"success": True}


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_single_url(data: SummarizeRequest):
    """Summarize a single URL on demand."""
    url = str(data.url)

    scraped, error = await scrape_url(url)
    if error or not scraped:
        raise HTTPException(status_code=400, detail=f"Failed to scrape: {error}")

    result, error = await summarize_content(scraped.content)
    if error or not result:
        raise HTTPException(status_code=500, detail=f"Summarization failed: {error}")

    # Save to Obsidian if enabled
    if settings.GENERATE_OBSIDIAN_FILES:
        write_summary_file_simple(
            title=scraped.title,
            url=url,
            summary_text=result.summary_text,
            model_used=result.model_used,
            author=scraped.author,
            tags=result.tags,
            category=result.category,
            entities=result.entities,
        )

    # Optionally save to database
    article = None
    if settings.USE_DB_RECEIPTS:
        async for session in get_session():
            article_repo = ArticleRepository(session)
            article = await article_repo.create_with_summary(
                title=scraped.title,
                url=url,
                content=scraped.content,
                summary_text=result.summary_text,
                model_used=result.model_used,
                processing_time=result.processing_time_sec,
                author=scraped.author,
            )
            await session.commit()

    # RAG indexing
    if article and settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
        try:
            from app.rag.hooks import index_article_hook
            async for session in get_session():
                await index_article_hook(article, session)
                await session.commit()
        except Exception:
            pass

    # Push notification
    try:
        from app.push.hooks import push_articles_fetched
        await push_articles_fetched(1)
    except Exception:
        pass

    return SummarizeResponse(
        title=scraped.title,
        url=url,
        summary=result.summary_text,
        model_used=result.model_used,
        processing_time_sec=result.processing_time_sec,
        tags=result.tags,
        category=result.category,
        entities=result.entities,
    )


async def fetch_all_feeds() -> Tuple[int, List[str]]:
    """Fetch all feeds that are due for update.

    Returns:
        Tuple of (new article count, list of error messages)
    """
    new_articles = 0
    errors = []

    async for session in get_session():
        feed_repo = RssFeedRepository(session)
        article_repo = ArticleRepository(session)

        feeds = await feed_repo.get_feeds_due_for_fetch()
        logger.info(f"Fetching {len(feeds)} feeds due for update")

        for feed in feeds:
            try:
                feed_info, error = await fetch_feed(feed.feed_url)

                if error:
                    await feed_repo.update_last_fetched(feed.id, error=error)
                    errors.append(f"{feed.name}: {error}")
                    continue

                for entry in feed_info.entries:
                    if entry.external_id:
                        existing = await article_repo.get_by_external_id(
                            feed.id, entry.external_id
                        )
                        if existing:
                            continue
                    elif entry.url:
                        existing = await article_repo.get_by_url(entry.url)
                        if existing:
                            continue

                    content = None
                    if entry.url:
                        content, _ = await scrape_with_fallback(entry.url, entry.content)
                    if not content:
                        content = entry.content or ""

                    summary_result = None
                    if content and len(content) >= 100:
                        summary_result, sum_error = await summarize_content(content)
                        if sum_error:
                            logger.warning(
                                f"Failed to summarize article {entry.title}: {sum_error}"
                            )

                    if summary_result:
                        article = await article_repo.create_with_summary(
                            title=entry.title,
                            url=entry.url,
                            content=content,
                            summary_text=summary_result.summary_text,
                            model_used=summary_result.model_used,
                            processing_time=summary_result.processing_time_sec,
                            feed_id=feed.id,
                            external_id=entry.external_id,
                            author=entry.author,
                            published_date=entry.published_date,
                        )

                        if settings.GENERATE_OBSIDIAN_FILES:
                            write_summary_file(
                                article,
                                summary_result.summary_text,
                                summary_result.model_used,
                                tags=summary_result.tags,
                                category=summary_result.category,
                                entities=summary_result.entities,
                            )
                    else:
                        article = await article_repo.create_article(
                            title=entry.title,
                            url=entry.url,
                            content=content,
                            feed_id=feed.id,
                            external_id=entry.external_id,
                            author=entry.author,
                            published_date=entry.published_date,
                        )

                    if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
                        try:
                            from app.rag.hooks import index_article_hook
                            await index_article_hook(article, session)
                        except Exception as e:
                            logger.warning(f"RAG indexing failed for article: {e}")

                    new_articles += 1
                    logger.info(f"Added article: {entry.title[:50]}")

                await feed_repo.update_last_fetched(feed.id)

            except Exception as e:
                logger.exception(f"Error processing feed {feed.name}")
                errors.append(f"{feed.name}: {str(e)}")

        await session.commit()

    if new_articles > 0:
        try:
            from app.push.hooks import push_articles_fetched
            await push_articles_fetched(new_articles)
        except Exception:
            pass

    return new_articles, errors


@router.post("/refresh", response_model=RefreshResponse)
async def trigger_refresh():
    """Manually trigger feed refresh."""
    new_count, errors = await fetch_all_feeds()
    return RefreshResponse(
        new_articles=new_count,
        errors=errors,
    )


@router.get("/stats")
async def get_rss_stats():
    """Get RSS statistics."""
    async for session in get_session():
        feed_repo = RssFeedRepository(session)
        article_repo = ArticleRepository(session)

        feeds = await feed_repo.get_all()
        active_feeds = [f for f in feeds if f.is_active]
        articles = await article_repo.get_recent(limit=1000)
        unread = await article_repo.get_unread_count()

        return {
            "total_feeds": len(feeds),
            "active_feeds": len(active_feeds),
            "total_articles": len(articles),
            "unread_articles": unread,
        }
