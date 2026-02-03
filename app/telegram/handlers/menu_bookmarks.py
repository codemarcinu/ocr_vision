"""Callback handlers for bookmarks module menu."""

import logging

from telegram import CallbackQuery
from telegram.ext import ContextTypes

from app.config import settings
from app.telegram.formatters import escape_html
from app.telegram.keyboards import get_bookmarks_menu, get_main_keyboard

logger = logging.getLogger(__name__)


async def handle_bookmarks_callback(
    query: CallbackQuery,
    action: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle bookmarks:* callbacks."""
    if action == "menu":
        await query.edit_message_text(
            "<b>🔖 Zakładki</b>\n\n"
            "Wyślij link aby go zapisać, podsumować lub transkrybować.\n"
            "Wybierz opcję poniżej:",
            parse_mode="HTML",
            reply_markup=get_bookmarks_menu(),
        )

    elif action == "list":
        await _show_bookmarks(query, status=None)

    elif action == "pending":
        await _show_bookmarks(query, status="pending")


async def _show_bookmarks(query: CallbackQuery, status: str | None) -> None:
    """Show bookmarks list."""
    if not settings.BOOKMARKS_ENABLED:
        await query.edit_message_text(
            "❌ Moduł zakładek jest wyłączony",
            reply_markup=get_main_keyboard(),
        )
        return

    from app.db.connection import get_session
    from app.db.repositories.bookmarks import BookmarkRepository

    async for session in get_session():
        repo = BookmarkRepository(session)

        if status:
            bookmarks = await repo.get_by_status(status, limit=15)
            title = "Oczekujące zakładki" if status == "pending" else f"Zakładki ({status})"
        else:
            bookmarks = await repo.get_recent(limit=15)
            title = "Wszystkie zakładki"

        if not bookmarks:
            await query.edit_message_text(
                f"📭 <b>Brak zakładek</b>\n\n"
                "Wyślij link aby go zapisać.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard(),
            )
            return

        lines = [f"🔖 <b>{title}:</b>\n"]

        for b in bookmarks:
            status_emoji = {
                "pending": "⏳",
                "read": "✅",
                "archived": "📦",
            }.get(b.status, "❓")

            title_short = b.title or b.url[:50]
            if len(title_short) > 50:
                title_short = title_short[:50] + "..."

            date = b.created_at.strftime("%m-%d %H:%M")

            lines.append(f"{status_emoji} <b>{escape_html(title_short)}</b>")
            lines.append(f"   {date} | <code>{str(b.id)[:8]}</code>")

        stats = await repo.stats()
        lines.append(f"\n<i>Łącznie: {stats['total']} (oczekujące: {stats['pending']})</i>")

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )
