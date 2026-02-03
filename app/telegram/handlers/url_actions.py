"""Callback handlers for URL actions (bookmark, summarize, transcribe)."""

import logging

from telegram import CallbackQuery
from telegram.ext import ContextTypes

from app.config import settings
from app.telegram.formatters import escape_html
from app.telegram.keyboards import get_main_keyboard

logger = logging.getLogger(__name__)


async def handle_url_callback(
    query: CallbackQuery,
    action: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle url:* callbacks.

    Action format: "verb:url_key" (e.g., "bookmark:a1b2c3d4").
    """
    parts = action.split(":", 1)
    if len(parts) < 2:
        return

    verb, url_key = parts

    url = context.user_data.get(f"url_{url_key}") if context.user_data else None
    if not url:
        await query.edit_message_text("Link wygasł. Wyślij ponownie.")
        return

    if verb == "bookmark":
        await _bookmark_url(query, url)
    elif verb == "summarize":
        await _summarize_url(query, url)
    elif verb == "transcribe":
        await _transcribe_url(query, url)


async def _bookmark_url(query: CallbackQuery, url: str) -> None:
    """Save URL as bookmark."""
    from app.db.connection import get_session
    from app.db.repositories.bookmarks import BookmarkRepository

    try:
        title = None
        try:
            from app.web_scraper import scrape_url
            scraped, _ = await scrape_url(url)
            if scraped:
                title = scraped.title
        except Exception:
            pass

        async for session in get_session():
            repo = BookmarkRepository(session)

            existing = await repo.get_by_url(url)
            if existing:
                await query.edit_message_text(
                    f"⚠️ <b>Zakładka już istnieje</b>\n\n"
                    f"📌 {escape_html(existing.title or url[:60])}\n"
                    f"Status: {existing.status}",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard(),
                )
                return

            bookmark = await repo.create_from_url(
                url=url, title=title, source="telegram",
            )
            await session.commit()

            display_title = title or url[:60]
            await query.edit_message_text(
                f"🔖 <b>Zakładka zapisana!</b>\n\n"
                f"📌 {escape_html(display_title)}\n"
                f"<code>ID: {str(bookmark.id)[:8]}</code>",
                parse_mode="HTML",
                reply_markup=get_main_keyboard(),
            )
    except Exception as e:
        logger.error(f"Error saving bookmark: {e}")
        await query.edit_message_text(f"❌ Błąd: {e}")


async def _summarize_url(query: CallbackQuery, url: str) -> None:
    """Summarize article at URL."""
    await query.edit_message_text("📖 Pobieram artykuł...")

    from app.web_scraper import scrape_url
    from app.summarizer import summarize_content

    scraped, error = await scrape_url(url)
    if error or not scraped:
        await query.edit_message_text(f"❌ Błąd pobierania: {error}")
        return

    await query.edit_message_text("🤖 Generuję podsumowanie...")

    result, error = await summarize_content(scraped.content)
    if error or not result:
        await query.edit_message_text(f"❌ Błąd podsumowania: {error}")
        return

    summary = result.summary_text
    if len(summary) > 3000:
        summary = summary[:3000] + "..."

    meta_parts = []
    if result.category:
        meta_parts.append(f"📂 {result.category}")
    if result.tags:
        tags_str = " ".join(f"#{t}" for t in result.tags[:5])
        meta_parts.append(tags_str)
    meta_line = " | ".join(meta_parts) if meta_parts else ""

    response = (
        f"📰 <b>{escape_html(scraped.title)}</b>\n\n"
        f"{escape_html(summary)}\n\n"
    )
    if meta_line:
        response += f"{escape_html(meta_line)}\n\n"
    response += (
        f"---\n"
        f'🔗 <a href="{url}">Źródło</a> | '
        f"⏱️ {result.processing_time_sec}s | "
        f"🤖 {result.model_used}"
    )

    try:
        await query.edit_message_text(
            response, parse_mode="HTML", disable_web_page_preview=True,
        )
    except Exception:
        await query.edit_message_text(
            response.replace("<b>", "").replace("</b>", "")
            .replace('<a href="', "").replace('">', " ").replace("</a>", "")
        )

    # Save to DB and Obsidian
    if settings.USE_DB_RECEIPTS:
        from app.db.connection import get_session
        from app.db.repositories.rss import ArticleRepository
        from app.summary_writer import write_summary_file

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

            if settings.GENERATE_OBSIDIAN_FILES:
                write_summary_file(
                    article,
                    result.summary_text,
                    result.model_used,
                    tags=result.tags,
                    category=result.category,
                    entities=result.entities,
                )
    elif settings.GENERATE_OBSIDIAN_FILES:
        from app.summary_writer import write_summary_file_simple

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


async def _transcribe_url(query: CallbackQuery, url: str) -> None:
    """Create transcription job for URL."""
    if not settings.TRANSCRIPTION_ENABLED:
        await query.edit_message_text("❌ Transkrypcja jest wyłączona")
        return

    await query.edit_message_text("🎙️ Rozpoczynam transkrypcję...")

    from app.transcription.downloader import is_youtube_url
    from app.db.connection import get_session
    from app.db.repositories.transcription import TranscriptionJobRepository

    source_type = "youtube" if is_youtube_url(url) else "url"

    msg = await query.message.reply_text("🔍 Analizuję URL...")

    async for session in get_session():
        repo = TranscriptionJobRepository(session)
        existing = await repo.get_by_url(url)
        if existing and existing.status == "completed":
            await msg.edit_text(
                f"✅ <b>Transkrypcja już istnieje!</b>\n\n"
                f"📄 {url[:60]}",
                parse_mode="HTML",
            )
            return

        job = await repo.create_job(
            source_type=source_type,
            source_url=url,
        )
        await session.commit()

        await msg.edit_text(
            f"✅ <b>Zadanie transkrypcji utworzone</b>\n\n"
            f"ID: <code>{str(job.id)[:8]}</code>\n"
            f"Zostanie przetworzone w tle.",
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )
