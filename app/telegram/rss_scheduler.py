"""RSS feed scheduler for automatic fetching."""

import logging
from typing import List, Tuple

from telegram import Bot

from app.config import settings
from app.db.connection import get_session
from app.db.repositories.rss import ArticleRepository, RssFeedRepository
from app.rss_fetcher import fetch_feed
from app.summarizer import summarize_content
from app.summary_writer import write_summary_file
from app.web_scraper import scrape_with_fallback

logger = logging.getLogger(__name__)


async def fetch_all_feeds() -> Tuple[int, List[str]]:
    """
    Fetch all feeds that are due for update.

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

                # Process entries
                for entry in feed_info.entries:
                    # Check if article already exists
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

                    # Get full content
                    content = None
                    if entry.url:
                        content, _ = await scrape_with_fallback(entry.url, entry.content)
                    if not content:
                        content = entry.content or ""

                    # Summarize only if we have content
                    summary_result = None
                    if content and len(content) >= 100:
                        summary_result, sum_error = await summarize_content(content)
                        if sum_error:
                            logger.warning(
                                f"Failed to summarize article {entry.title}: {sum_error}"
                            )

                    # Create article with or without summary
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

                        # Write Obsidian file
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
                        # Create article without summary
                        article = await article_repo.create_article(
                            title=entry.title,
                            url=entry.url,
                            content=content,
                            feed_id=feed.id,
                            external_id=entry.external_id,
                            author=entry.author,
                            published_date=entry.published_date,
                        )

                    # RAG indexing
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

    return new_articles, errors


async def send_new_articles_notification(
    bot: Bot, chat_id: int, new_count: int
) -> None:
    """Send notification about new articles."""
    if new_count > 0:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"📰 Pobrano {new_count} nowych artykułów.\n\nUżyj /articles aby zobaczyć.",
            )
        except Exception as e:
            logger.error(f"Failed to send RSS notification: {e}")


def register_rss_scheduler(scheduler, bot: Bot) -> None:
    """
    Register RSS fetch job with scheduler.

    Adds job to existing APScheduler from notifications.py.
    """
    if not settings.SUMMARIZER_ENABLED:
        logger.info("RSS scheduler disabled (SUMMARIZER_ENABLED=false)")
        return

    async def scheduled_fetch():
        """Scheduled job wrapper."""
        logger.info("Starting scheduled RSS fetch...")
        new_count, errors = await fetch_all_feeds()
        logger.info(f"RSS fetch complete: {new_count} new articles, {len(errors)} errors")

        if new_count > 0 and settings.TELEGRAM_CHAT_ID:
            await send_new_articles_notification(bot, settings.TELEGRAM_CHAT_ID, new_count)

        if errors:
            logger.warning(f"RSS fetch errors: {errors}")

    # Add job - runs every RSS_FETCH_INTERVAL_HOURS
    scheduler.add_job(
        scheduled_fetch,
        "interval",
        hours=settings.RSS_FETCH_INTERVAL_HOURS,
        id="rss_fetch",
        replace_existing=True,
    )

    logger.info(f"RSS scheduler registered (every {settings.RSS_FETCH_INTERVAL_HOURS}h)")
