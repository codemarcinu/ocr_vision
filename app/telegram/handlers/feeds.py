"""RSS feed management handlers for Telegram bot."""

import logging

import validators
from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.db.connection import get_session
from app.db.repositories.rss import ArticleRepository, RssFeedRepository
from app.rss_fetcher import detect_feed_type, fetch_feed
from app.summarizer import summarize_content
from app.summary_writer import write_summary_file, write_summary_file_simple
from app.telegram.formatters import escape_html
from app.telegram.middleware import authorized_only
from app.web_scraper import scrape_url

logger = logging.getLogger(__name__)


@authorized_only
async def feeds_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /feeds command - list subscribed feeds."""
    if not update.message:
        return

    async for session in get_session():
        repo = RssFeedRepository(session)
        feeds = await repo.get_active_feeds()

        if not feeds:
            await update.message.reply_text(
                "📰 <b>Brak subskrybowanych kanałów RSS</b>\n\n"
                "Użyj <code>/subscribe &lt;URL&gt;</code> aby dodać kanał.",
                parse_mode="HTML",
            )
            return

        lines = ["📰 <b>Subskrybowane kanały:</b>\n"]
        for feed in feeds:
            status = "✅" if feed.is_active else "⏸️"
            last = (
                feed.last_fetched.strftime("%Y-%m-%d %H:%M")
                if feed.last_fetched
                else "nigdy"
            )
            error_info = " ⚠️" if feed.last_error else ""
            lines.append(f"{status} <b>{escape_html(feed.name)}</b>{error_info}")
            lines.append(f"   ID: {feed.id} | Ostatnie pobr.: {last}")

        lines.append(f"\n<i>Użyj /unsubscribe &lt;ID&gt; aby usunąć</i>")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@authorized_only
async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /subscribe command - add new RSS feed."""
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Użycie: <code>/subscribe &lt;URL_RSS&gt;</code>\n\n"
            "Przykład: <code>/subscribe https://blog.example.com/rss</code>",
            parse_mode="HTML",
        )
        return

    url = context.args[0]

    # Validate URL
    if not validators.url(url):
        await update.message.reply_text("❌ Nieprawidłowy URL")
        return

    status_msg = await update.message.reply_text("🔍 Sprawdzam kanał...")

    # Detect feed type
    feed_type, error = await detect_feed_type(url)
    if error:
        await status_msg.edit_text(f"❌ Błąd: {error}")
        return

    if feed_type == "webpage":
        await status_msg.edit_text(
            "⚠️ Podany URL to strona internetowa, nie kanał RSS.\n\n"
            "Użyj <code>/summarize &lt;URL&gt;</code> aby podsumować pojedynczą stronę.",
            parse_mode="HTML",
        )
        return

    # Fetch feed to get title
    feed_info, error = await fetch_feed(url)
    if error:
        await status_msg.edit_text(f"❌ Błąd pobierania kanału: {error}")
        return

    # Save to database
    async for session in get_session():
        repo = RssFeedRepository(session)

        # Check if already exists
        existing = await repo.get_by_url(url)
        if existing:
            await status_msg.edit_text(
                f"⚠️ Kanał już istnieje: <b>{escape_html(existing.name)}</b>",
                parse_mode="HTML",
            )
            return

        feed = await repo.create(
            name=feed_info.title,
            feed_url=url,
            feed_type=feed_type,
        )
        await session.commit()

        await status_msg.edit_text(
            f"✅ <b>Dodano kanał:</b> {escape_html(feed.name)}\n\n"
            f"Typ: {feed_type.upper()}\n"
            f"Artykułów: {len(feed_info.entries)}\n\n"
            f"<i>Artykuły zostaną pobrane automatycznie.</i>",
            parse_mode="HTML",
        )


@authorized_only
async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unsubscribe command - remove RSS feed."""
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Użycie: <code>/unsubscribe &lt;ID&gt;</code>\n\n"
            "Użyj <code>/feeds</code> aby zobaczyć ID kanałów.",
            parse_mode="HTML",
        )
        return

    try:
        feed_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID musi być liczbą")
        return

    async for session in get_session():
        repo = RssFeedRepository(session)
        feed = await repo.get_by_id(feed_id)

        if not feed:
            await update.message.reply_text("❌ Nie znaleziono kanału o podanym ID")
            return

        name = feed.name
        await repo.delete(feed_id)
        await session.commit()

        await update.message.reply_text(
            f"✅ Usunięto kanał: <b>{escape_html(name)}</b>", parse_mode="HTML"
        )


@authorized_only
async def summarize_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /summarize command - summarize single URL on demand."""
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Użycie: <code>/summarize &lt;URL&gt;</code>\n\n"
            "Przykład: <code>/summarize https://example.com/article</code>",
            parse_mode="HTML",
        )
        return

    url = context.args[0]

    if not validators.url(url):
        await update.message.reply_text("❌ Nieprawidłowy URL")
        return

    status_msg = await update.message.reply_text("📖 Pobieram artykuł...")

    # Scrape content
    scraped, error = await scrape_url(url)
    if error or not scraped:
        await status_msg.edit_text(f"❌ Błąd pobierania: {error}")
        return

    await status_msg.edit_text("🤖 Generuję podsumowanie...")

    # Summarize
    result, error = await summarize_content(scraped.content)
    if error or not result:
        await status_msg.edit_text(f"❌ Błąd podsumowania: {error}")
        return

    # Format response
    summary = result.summary_text
    if len(summary) > 3500:
        summary = summary[:3500] + "..."

    response = (
        f"📰 <b>{escape_html(scraped.title)}</b>\n\n"
        f"{escape_html(summary)}\n\n"
        f"---\n"
        f"🔗 <a href=\"{url}\">Źródło</a> | "
        f"⏱️ {result.processing_time_sec}s | "
        f"🤖 {result.model_used}"
    )

    try:
        await status_msg.edit_text(
            response, parse_mode="HTML", disable_web_page_preview=True
        )
    except Exception:
        # Fallback without HTML if parsing fails
        await status_msg.edit_text(
            response.replace("<b>", "").replace("</b>", "").replace("<a href=\"", "").replace("\">", " ").replace("</a>", "")
        )

    # Save to database (optional - on-demand summaries)
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

            # Write Obsidian file
            if settings.GENERATE_OBSIDIAN_FILES:
                write_summary_file(article, result.summary_text, result.model_used)
    elif settings.GENERATE_OBSIDIAN_FILES:
        # Save only to Obsidian without database
        write_summary_file_simple(
            title=scraped.title,
            url=url,
            summary_text=result.summary_text,
            model_used=result.model_used,
            author=scraped.author,
        )


@authorized_only
async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /refresh command - manually trigger feed fetch."""
    if not update.message:
        return

    status_msg = await update.message.reply_text("🔄 Pobieram nowe artykuły...")

    # Import and run the fetch job
    from app.telegram.rss_scheduler import fetch_all_feeds

    new_count, errors = await fetch_all_feeds()

    if errors:
        error_text = "\n".join([f"• {e}" for e in errors[:5]])
        await status_msg.edit_text(
            f"⚠️ Pobrano z błędami:\n\n"
            f"Nowych artykułów: {new_count}\n"
            f"Błędy:\n{error_text}",
        )
    else:
        await status_msg.edit_text(f"✅ Pobrano {new_count} nowych artykułów")


@authorized_only
async def articles_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /articles command - list recent articles."""
    if not update.message:
        return

    feed_id = None
    if context.args:
        try:
            feed_id = int(context.args[0])
        except ValueError:
            pass

    async for session in get_session():
        repo = ArticleRepository(session)
        articles = await repo.get_recent(feed_id=feed_id, limit=10)

        if not articles:
            await update.message.reply_text("📭 Brak artykułów")
            return

        lines = ["📚 <b>Ostatnie artykuły:</b>\n"]
        for article in articles:
            status = "✅" if article.is_summarized else "⏳"
            source = article.feed.name if article.feed else "manual"
            date = article.fetched_date.strftime("%m-%d %H:%M")
            title_short = article.title[:50] + "..." if len(article.title) > 50 else article.title
            lines.append(f"{status} <b>{escape_html(title_short)}</b>")
            lines.append(f"   {escape_html(source)} | {date}")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
