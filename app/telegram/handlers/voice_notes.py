"""Voice note handler - queue voice messages for batch transcription.

Voice notes are queued and processed periodically (default: every 30 min)
to avoid VRAM conflicts with chat models. The scheduler processes queued
voice notes, transcribes them with Whisper, and saves as Notes.
"""

import logging
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings

logger = logging.getLogger(__name__)

# Directory for queued voice notes (persisted until processed)
VOICE_QUEUE_DIR = settings.TRANSCRIPTION_TEMP_DIR / "voice_queue"


async def handle_voice_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Queue a Telegram voice message for batch transcription.

    Authorization is handled by the caller (_handle_audio_input in bot.py).
    """
    if not update.message or not update.message.voice:
        return

    if not settings.NOTES_ENABLED:
        await update.message.reply_text("Notatki są wyłączone")
        return

    if not settings.TRANSCRIPTION_ENABLED:
        await update.message.reply_text("Transkrypcja jest wyłączona")
        return

    voice = update.message.voice

    # Calculate next processing time
    interval = settings.VOICE_NOTE_PROCESS_INTERVAL_MINUTES
    next_process = f"~{interval} min"

    status_msg = await update.message.reply_text(
        f"Notatka głosowa dodana do kolejki.\n"
        f"Zostanie przetworzona w ciągu {next_process}."
    )

    try:
        # Ensure queue directory exists
        VOICE_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

        # Download voice file to queue directory (persistent)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"voice_{timestamp}_{voice.file_unique_id}.ogg"
        audio_path = VOICE_QUEUE_DIR / filename

        tg_file = await voice.get_file()
        await tg_file.download_to_drive(str(audio_path))

        # Create transcription job in database queue
        from app.db.connection import get_session
        from app.db.repositories.transcription import TranscriptionJobRepository

        async for session in get_session():
            repo = TranscriptionJobRepository(session)
            job = await repo.create_job(
                source_type="voice",
                source_filename=filename,
                title=f"Notatka głosowa {timestamp}",
                duration_seconds=voice.duration,
                temp_audio_path=str(audio_path),
            )
            await session.commit()

            logger.info(f"Voice note queued: {job.id} ({voice.duration}s)")

            await status_msg.edit_text(
                f"Notatka głosowa ({voice.duration}s) dodana do kolejki.\n"
                f"Zostanie przetworzona w ciągu {next_process}.\n\n"
                f"<code>ID: {str(job.id)[:8]}</code>",
                parse_mode="HTML",
            )

    except Exception as e:
        logger.exception("Failed to queue voice note")
        await status_msg.edit_text(f"Błąd kolejkowania notatki głosowej: {e}")

        # Cleanup on failure
        try:
            if audio_path.exists():
                audio_path.unlink()
        except Exception:
            pass
