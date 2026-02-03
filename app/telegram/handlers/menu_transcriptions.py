"""Callback handlers for transcriptions module menu."""

import logging

from telegram import CallbackQuery
from telegram.ext import ContextTypes

from app.config import settings
from app.telegram.formatters import escape_html
from app.telegram.keyboards import get_main_keyboard, get_transcriptions_menu

logger = logging.getLogger(__name__)


async def handle_transcriptions_callback(
    query: CallbackQuery,
    action: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle transcriptions:* callbacks."""
    if action == "menu":
        await query.edit_message_text(
            "<b>🎙️ Transkrypcje</b>\n\n"
            "Wyślij URL YouTube lub plik audio aby transkrybować.\n"
            "Wybierz opcję poniżej:",
            parse_mode="HTML",
            reply_markup=get_transcriptions_menu(),
        )

    elif action == "list":
        if not settings.TRANSCRIPTION_ENABLED:
            await query.edit_message_text(
                "❌ Transkrypcja jest wyłączona",
                reply_markup=get_main_keyboard(),
            )
            return

        from app.db.connection import get_session
        from app.db.repositories.transcription import TranscriptionJobRepository

        async for session in get_session():
            repo = TranscriptionJobRepository(session)
            jobs = await repo.get_recent_jobs(limit=10)

            if not jobs:
                await query.edit_message_text(
                    "📭 <b>Brak transkrypcji</b>\n\n"
                    "Wyślij URL YouTube lub plik audio aby rozpocząć.",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard(),
                )
                return

            lines = ["🎙️ <b>Ostatnie transkrypcje:</b>\n"]

            for job in jobs:
                status_emoji = {
                    "pending": "⏳",
                    "downloading": "📥",
                    "transcribing": "🎙️",
                    "extracting": "🧠",
                    "completed": "✅",
                    "failed": "❌",
                }.get(job.status, "❓")

                title = (job.title or job.source_filename or "Untitled")[:40]
                if len(title) < len(job.title or job.source_filename or ""):
                    title += "..."

                date = job.created_at.strftime("%m-%d %H:%M")
                has_note = "📓" if job.note else ""

                lines.append(f"{status_emoji} <b>{escape_html(title)}</b> {has_note}")
                lines.append(f"   {date} | <code>{str(job.id)[:8]}</code>")

            await query.edit_message_text(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=get_main_keyboard(),
            )
