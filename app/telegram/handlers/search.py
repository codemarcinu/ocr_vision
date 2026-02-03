"""Telegram /find handler for unified cross-module search."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.db.connection import get_session
from app.search_api import (
    _search_receipts,
    _search_articles,
    _search_notes,
    _search_bookmarks,
    _search_transcriptions,
)
from app.telegram.formatters import escape_html
from app.telegram.middleware import authorized_only

logger = logging.getLogger(__name__)

TYPE_EMOJI = {
    "receipt": "\U0001f9fe",      # receipt
    "article": "\U0001f4f0",      # newspaper
    "note": "\U0001f4dd",         # memo
    "bookmark": "\U0001f516",     # bookmark
    "transcription": "\U0001f3a4", # microphone
}

TYPE_LABELS = {
    "receipt": "Paragony",
    "article": "Artykuły",
    "note": "Notatki",
    "bookmark": "Zakładki",
    "transcription": "Transkrypcje",
}


@authorized_only
async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /find <query> - unified search across all modules."""
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "<b>\U0001f50d Szukaj w bazie wiedzy</b>\n\n"
            "Użycie: <code>/find &lt;fraza&gt;</code>\n\n"
            "Przeszukuje paragony, artykuły, notatki, zakładki i transkrypcje.",
            parse_mode="HTML",
        )
        return

    query = " ".join(context.args)
    if len(query) < 2:
        await update.message.reply_text("Fraza musi mieć co najmniej 2 znaki.")
        return

    status_msg = await update.message.reply_text("\U0001f50d Szukam...")

    try:
        pattern = f"%{query}%"
        results = {}

        async for session in get_session():
            searches = [
                _search_receipts(session, pattern, 3),
                _search_articles(session, pattern, 3),
                _search_notes(session, pattern, 3),
                _search_bookmarks(session, pattern, 3),
                _search_transcriptions(session, pattern, 3),
            ]
            for search_coro in searches:
                type_name, items = await search_coro
                if items:
                    results[type_name] = items

        total = sum(len(v) for v in results.values())

        if not total:
            await status_msg.edit_text(
                f"\U0001f50d Brak wyników dla: <b>{escape_html(query)}</b>",
                parse_mode="HTML",
            )
            return

        parts = [f"\U0001f50d Wyniki dla: <b>{escape_html(query)}</b> ({total})\n"]

        order = ["receipt", "article", "note", "bookmark", "transcription"]
        for type_name in order:
            items = results.get(type_name)
            if not items:
                continue

            emoji = TYPE_EMOJI.get(type_name, "\U0001f4c4")
            label = TYPE_LABELS.get(type_name, type_name)
            parts.append(f"\n{emoji} <b>{label}</b>")

            for item in items[:3]:
                line = _format_item(type_name, item)
                parts.append(f"  • {line}")

        response = "\n".join(parts)
        try:
            await status_msg.edit_text(response[:4096], parse_mode="HTML")
        except Exception:
            plain = response.replace("<b>", "").replace("</b>", "")
            plain = plain.replace("<code>", "").replace("</code>", "")
            await status_msg.edit_text(plain[:4096])

    except Exception as e:
        logger.error(f"Error in /find: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Błąd: {e}")


def _format_item(type_name: str, item: dict) -> str:
    """Format a search result item for Telegram."""
    if type_name == "receipt":
        name = escape_html(item.get("name", ""))
        price = item.get("price", 0)
        store = item.get("store", "")
        date = item.get("date", "")
        meta = f" ({store}, {date})" if store else ""
        return f"{name} — {price:.2f} zł{meta}"

    elif type_name == "article":
        title = escape_html(item.get("title", ""))
        return title

    elif type_name == "note":
        title = escape_html(item.get("title", ""))
        cat = item.get("category", "")
        return f"{title}" + (f" [{cat}]" if cat else "")

    elif type_name == "bookmark":
        title = escape_html(item.get("title", item.get("url", "")))
        status = item.get("status", "")
        icon = "✅" if status == "read" else "⏳"
        return f"{icon} {title}"

    elif type_name == "transcription":
        title = escape_html(item.get("title", "Transkrypcja"))
        return title

    return escape_html(str(item))
