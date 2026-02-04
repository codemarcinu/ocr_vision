"""Voice note handler - transcribe voice messages and save as notes."""

import logging
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings

logger = logging.getLogger(__name__)


async def handle_voice_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe a Telegram voice message and save as a quick note.

    Authorization is handled by the caller (_handle_audio_input in bot.py).
    """
    if not update.message or not update.message.voice:
        return

    if not settings.NOTES_ENABLED:
        await update.message.reply_text("❌ Notatki są wyłączone")
        return

    if not settings.TRANSCRIPTION_ENABLED:
        await update.message.reply_text("❌ Transkrypcja jest wyłączona")
        return

    status_msg = await update.message.reply_text("🎙️ Transkrybuję notatkę głosową...")

    voice = update.message.voice
    temp_path = settings.TRANSCRIPTION_TEMP_DIR / f"voice_{voice.file_unique_id}.ogg"

    try:
        # Download voice file
        settings.TRANSCRIPTION_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        tg_file = await voice.get_file()
        await tg_file.download_to_drive(str(temp_path))

        # Transcribe with Whisper
        from app.transcription.transcriber import TranscriberService

        transcriber = TranscriberService()
        full_text, segments, info = await transcriber.transcribe(str(temp_path))

        if not full_text or not full_text.strip():
            await status_msg.edit_text(
                "❌ Nie udało się rozpoznać mowy w nagraniu"
            )
            return

        full_text = full_text.strip()

        # Generate title from first ~50 chars
        if len(full_text) > 50:
            title = full_text[:50].rsplit(" ", 1)[0]
            if not title:
                title = full_text[:50]
        else:
            title = full_text

        # Save as Note
        from app.db.connection import get_session
        from app.db.repositories.notes import NoteRepository
        from app.telegram.formatters import escape_html

        async for session in get_session():
            repo = NoteRepository(session)
            note = await repo.create(
                title=title,
                content=full_text,
                tags=["voice"],
            )
            await session.commit()

            # Write to Obsidian
            if settings.GENERATE_OBSIDIAN_FILES:
                from app.notes_writer import write_note_file
                write_note_file(note)

            # RAG indexing
            if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
                try:
                    from app.rag.hooks import index_note_hook
                    await index_note_hook(note, session)
                    await session.commit()
                except Exception:
                    pass

            # Confirmation
            text_preview = full_text[:200] + "..." if len(full_text) > 200 else full_text
            word_count = info.get("word_count", len(full_text.split()))

            await status_msg.edit_text(
                f"✅ <b>Notatka głosowa zapisana!</b>\n\n"
                f"📌 {escape_html(text_preview)}\n\n"
                f"📝 {word_count} słów\n"
                f"<code>ID: {str(note.id)[:8]}</code>",
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception("Voice note processing failed")
        await status_msg.edit_text(f"❌ Błąd przetwarzania notatki głosowej: {e}")

    finally:
        # Cleanup temp file
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
