"""Telegram /ask handler for RAG knowledge base queries."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.db.connection import get_session
from app.rag import answerer
from app.telegram.middleware import authorized_only

logger = logging.getLogger(__name__)


def _format_source_emoji(content_type: str) -> str:
    """Get emoji for content type."""
    return {
        "article": "📰",
        "transcription": "🎙️",
        "receipt": "🧾",
        "note": "📝",
        "bookmark": "🔖",
    }.get(content_type, "📄")


@authorized_only
async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ask <question> command."""
    if not update.message:
        return

    if not settings.RAG_ENABLED:
        await update.message.reply_text("RAG jest wyłączony.")
        return

    if not context.args:
        await update.message.reply_text(
            "<b>🧠 Zapytaj bazę wiedzy</b>\n\n"
            "Użycie: <code>/ask &lt;pytanie&gt;</code>\n\n"
            "Przykłady:\n"
            "• <code>/ask ile wydałem w Biedronce w styczniu?</code>\n"
            "• <code>/ask co wiem o sztucznej inteligencji?</code>\n"
            "• <code>/ask jakie produkty kupuję najczęściej?</code>",
            parse_mode="HTML",
        )
        return

    question = " ".join(context.args)

    # Send "thinking" message
    status_msg = await update.message.reply_text("🤔 Szukam odpowiedzi...")

    try:
        async for session in get_session():
            result = await answerer.ask(
                question=question,
                session=session,
            )

        # Format response
        parts = [f"🧠 <b>Odpowiedź:</b>\n\n{_escape_html(result.answer)}"]

        if result.sources:
            parts.append("\n\n📚 <b>Źródła:</b>")
            for source in result.sources[:5]:
                emoji = _format_source_emoji(source.content_type)
                parts.append(f"  {emoji} {_escape_html(source.label)}")

        parts.append(
            f"\n\n<i>⏱️ {result.processing_time_sec}s | "
            f"📊 {result.chunks_found} fragmentów | "
            f"🤖 {result.model_used}</i>"
        )

        response = "\n".join(parts)

        try:
            await status_msg.edit_text(response, parse_mode="HTML")
        except Exception:
            # Fallback without HTML if formatting fails
            plain = response.replace("<b>", "").replace("</b>", "")
            plain = plain.replace("<i>", "").replace("</i>", "")
            plain = plain.replace("<code>", "").replace("</code>", "")
            await status_msg.edit_text(plain[:4096])

    except Exception as e:
        logger.error(f"Error in /ask: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Błąd: {e}")


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
