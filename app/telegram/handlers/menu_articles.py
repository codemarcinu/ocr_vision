"""Callback handlers for articles/RSS module menu."""

import logging

from telegram import CallbackQuery
from telegram.ext import ContextTypes

from app.telegram.formatters import escape_html
from app.telegram.keyboards import get_articles_menu, get_main_keyboard

logger = logging.getLogger(__name__)


async def handle_articles_callback(
    query: CallbackQuery,
    data: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle articles:* callbacks."""
    await query.answer()
    action = data.split(":", 1)[1] if ":" in data else ""

    if action == "menu":
        await query.edit_message_text(
            "<b>📰 Artykuły i RSS</b>\n\n"
            "Wyślij URL aby podsumować artykuł.\n"
            "Wybierz opcję poniżej:",
            parse_mode="HTML",
            reply_markup=get_articles_menu(),
        )

    elif action == "feeds":
        from app.db.connection import get_session
        from app.db.repositories.rss import RssFeedRepository

        async for session in get_session():
            repo = RssFeedRepository(session)
            feeds = await repo.get_active_feeds()

            if not feeds:
                await query.edit_message_text(
                    "📰 <b>Brak subskrybowanych kanałów RSS</b>\n\n"
                    "Użyj <code>/subscribe &lt;URL&gt;</code> aby dodać kanał.",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard(),
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

            await query.edit_message_text(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=get_main_keyboard(),
            )

    elif action == "recent":
        from app.db.connection import get_session
        from app.db.repositories.rss import ArticleRepository

        async for session in get_session():
            repo = ArticleRepository(session)
            articles = await repo.get_recent(limit=10)

            if not articles:
                await query.edit_message_text(
                    "📭 Brak artykułów",
                    reply_markup=get_main_keyboard(),
                )
                return

            lines = ["📚 <b>Ostatnie artykuły:</b>\n"]
            for article in articles:
                status = "✅" if article.is_summarized else "⏳"
                source = article.feed.name if article.feed else "manual"
                date = article.fetched_date.strftime("%m-%d %H:%M")
                title_short = (
                    article.title[:50] + "..."
                    if len(article.title) > 50
                    else article.title
                )
                lines.append(f"{status} <b>{escape_html(title_short)}</b>")
                lines.append(f"   {escape_html(source)} | {date}")

            await query.edit_message_text(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=get_main_keyboard(),
            )

    elif action == "refresh":
        from app.telegram.rss_scheduler import fetch_all_feeds

        await query.edit_message_text("🔄 Pobieram nowe artykuły...")

        new_count, errors = await fetch_all_feeds()

        if errors:
            error_text = "\n".join([f"• {e}" for e in errors[:5]])
            text = (
                f"⚠️ Pobrano z błędami:\n\n"
                f"Nowych artykułów: {new_count}\n"
                f"Błędy:\n{error_text}"
            )
        else:
            text = f"✅ Pobrano {new_count} nowych artykułów"

        await query.edit_message_text(
            text,
            reply_markup=get_main_keyboard(),
        )
