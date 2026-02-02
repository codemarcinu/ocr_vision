"""Transcription handlers for Telegram bot."""

import logging
from pathlib import Path
from uuid import UUID

import validators
from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.db.connection import get_session
from app.db.repositories.transcription import TranscriptionJobRepository
from app.telegram.formatters import escape_html
from app.telegram.middleware import authorized_only
from app.transcription.downloader import DownloaderService, is_youtube_url
from app.transcription.extractor import KnowledgeExtractor
from app.transcription.note_writer import TranscriptionNoteWriter
from app.transcription.transcriber import TranscriberService

logger = logging.getLogger(__name__)


def _format_duration(seconds: int) -> str:
    """Format duration as H:MM:SS or MM:SS."""
    if not seconds:
        return "?"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


@authorized_only
async def transcribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /transcribe command - transcribe YouTube video or audio file."""
    if not update.message:
        return

    if not settings.TRANSCRIPTION_ENABLED:
        await update.message.reply_text("❌ Transkrypcja jest wyłączona")
        return

    # Check if URL provided
    if context.args:
        url = context.args[0]

        if not validators.url(url):
            await update.message.reply_text("❌ Nieprawidłowy URL")
            return

        await _transcribe_url(update, url)
    else:
        # Check for audio file attachment
        if update.message.audio or update.message.voice or update.message.document:
            await _transcribe_file(update)
        else:
            await update.message.reply_text(
                "📝 <b>Transkrypcja audio/wideo</b>\n\n"
                "Użycie:\n"
                "<code>/transcribe &lt;URL_YouTube&gt;</code>\n"
                "lub wyślij plik audio z komendą /transcribe\n\n"
                "Przykład:\n"
                "<code>/transcribe https://youtube.com/watch?v=xxx</code>",
                parse_mode="HTML",
            )


async def _transcribe_url(update: Update, url: str) -> None:
    """Transcribe from YouTube or other URL."""
    status_msg = await update.message.reply_text("🔍 Analizuję URL...")

    source_type = "youtube" if is_youtube_url(url) else "url"

    async for session in get_session():
        repo = TranscriptionJobRepository(session)

        # Check if already exists
        existing = await repo.get_by_url(url)
        if existing and existing.status == "completed":
            await status_msg.edit_text(
                f"✅ <b>Transkrypcja już istnieje!</b>\n\n"
                f"📄 {escape_html(existing.title or 'Untitled')}\n"
                f"Użyj <code>/note {existing.id}</code> aby wygenerować notatkę.",
                parse_mode="HTML",
            )
            return
        elif existing and existing.status in ("pending", "downloading", "transcribing", "extracting"):
            await status_msg.edit_text(
                f"⏳ <b>Transkrypcja w toku</b>\n\n"
                f"Status: {existing.status} ({existing.progress_percent}%)",
                parse_mode="HTML",
            )
            return

        # Create job
        job = await repo.create_job(
            source_type=source_type,
            source_url=url,
        )
        await session.commit()
        job_id = job.id

    # Process in background (for long videos, consider moving to scheduler)
    await _process_transcription_job(update, status_msg, job_id)


async def _transcribe_file(update: Update) -> None:
    """Transcribe from uploaded audio file."""
    # Get file from message
    file = update.message.audio or update.message.voice or update.message.document
    if not file:
        await update.message.reply_text("❌ Nie znaleziono pliku audio")
        return

    # Validate file type
    file_name = file.file_name or "audio.ogg"
    allowed_extensions = {".mp3", ".m4a", ".wav", ".ogg", ".webm", ".mp4", ".opus"}
    file_ext = Path(file_name).suffix.lower()
    if file_ext not in allowed_extensions:
        await update.message.reply_text(
            f"❌ Nieobsługiwany format: {file_ext}\n\n"
            f"Obsługiwane: {', '.join(allowed_extensions)}"
        )
        return

    status_msg = await update.message.reply_text("📥 Pobieram plik...")

    # Download file
    settings.TRANSCRIPTION_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = settings.TRANSCRIPTION_TEMP_DIR / file_name

    try:
        tg_file = await file.get_file()
        await tg_file.download_to_drive(str(temp_path))
    except Exception as e:
        await status_msg.edit_text(f"❌ Błąd pobierania pliku: {e}")
        return

    async for session in get_session():
        repo = TranscriptionJobRepository(session)

        job = await repo.create_job(
            source_type="file",
            source_filename=file_name,
            title=Path(file_name).stem,
        )
        job.temp_audio_path = str(temp_path)
        await session.commit()
        job_id = job.id

    await _process_transcription_job(update, status_msg, job_id)


async def _process_transcription_job(update: Update, status_msg, job_id: UUID) -> None:
    """Process transcription job with progress updates."""
    try:
        async for session in get_session():
            repo = TranscriptionJobRepository(session)
            job = await repo.get_by_id(job_id)

            if not job:
                await status_msg.edit_text("❌ Zadanie nie zostało znalezione")
                return

            audio_path = None
            subtitle_path = None

            # Step 1: Download if URL
            if job.source_url:
                await status_msg.edit_text("📥 Pobieram audio...")
                await repo.update_status(job_id, "downloading", progress=0)
                await session.commit()

                try:
                    downloader = DownloaderService()
                    result = await downloader.download(job.source_url)

                    # Update job with metadata
                    job.title = result.title
                    job.channel_name = result.channel_name
                    job.duration_seconds = result.duration_seconds
                    job.thumbnail_url = result.thumbnail_url
                    job.description = result.description
                    job.temp_audio_path = result.audio_path
                    audio_path = result.audio_path
                    subtitle_path = result.subtitle_path
                    await session.commit()

                    await status_msg.edit_text(
                        f"✅ Pobrano: <b>{escape_html(result.title)}</b>\n"
                        f"⏱️ {_format_duration(result.duration_seconds or 0)}",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    await repo.update_status(job_id, "failed", error=str(e))
                    await session.commit()
                    await status_msg.edit_text(f"❌ Błąd pobierania: {e}")
                    return
            else:
                audio_path = job.temp_audio_path

            if not audio_path:
                await status_msg.edit_text("❌ Brak pliku audio")
                return

            # Step 2: Transcribe
            if subtitle_path:
                await status_msg.edit_text("📝 Używam istniejących napisów...")
            else:
                await status_msg.edit_text(
                    "🎙️ Transkrybuję...\n"
                    f"<i>Model: {settings.WHISPER_MODEL}</i>",
                    parse_mode="HTML",
                )

            await repo.update_status(job_id, "transcribing", progress=10)
            await session.commit()

            try:
                transcriber = TranscriberService()

                if subtitle_path:
                    full_text, segments, info = await transcriber.transcribe_with_subtitles(
                        audio_path, subtitle_path
                    )
                else:
                    full_text, segments, info = await transcriber.transcribe(
                        audio_path, language=job.language
                    )

                # Save transcription
                await repo.add_transcription(
                    job_id=job_id,
                    full_text=full_text,
                    segments=segments,
                    detected_language=info["detected_language"],
                    confidence=info["confidence"],
                    word_count=info["word_count"],
                    processing_time_sec=info["processing_time_sec"],
                )
                await session.commit()

            except Exception as e:
                await repo.update_status(job_id, "failed", error=str(e))
                await session.commit()
                await status_msg.edit_text(f"❌ Błąd transkrypcji: {e}")
                return

            # Step 3: Generate note if enabled
            note_path = None
            if settings.TRANSCRIPTION_AUTO_GENERATE_NOTE:
                await status_msg.edit_text("🧠 Generuję notatkę...")
                await repo.update_status(job_id, "extracting", progress=80)
                await session.commit()

                try:
                    extractor = KnowledgeExtractor()
                    result, error = await extractor.extract(full_text)

                    if result:
                        note = await repo.add_note(
                            job_id=job_id,
                            summary_text=result.summary_text,
                            key_topics=result.topics,
                            key_points=result.key_points,
                            entities=result.entities,
                            action_items=result.action_items,
                            category=result.category,
                            tags=result.tags,
                            model_used=result.model_used,
                            processing_time_sec=result.processing_time_sec,
                        )

                        # Write to Obsidian
                        if settings.GENERATE_OBSIDIAN_FILES:
                            writer = TranscriptionNoteWriter()
                            file_path = writer.write_note(
                                title=job.title or "Untitled",
                                extraction=result,
                                source_type=job.source_type,
                                source_url=job.source_url,
                                channel_name=job.channel_name,
                                duration_seconds=job.duration_seconds,
                            )
                            note.obsidian_file_path = str(file_path)
                            note_path = file_path

                        await session.commit()
                except Exception as e:
                    logger.warning(f"Note generation failed: {e}")
                    # Continue - transcription is still valid

            # Mark completed
            await repo.update_status(job_id, "completed", progress=100)
            await session.commit()

            # Build completion message
            title = job.title or "Untitled"
            duration = _format_duration(job.duration_seconds or 0)
            word_count = info["word_count"]
            lang = info["detected_language"]

            msg_lines = [
                f"✅ <b>Transkrypcja zakończona!</b>",
                "",
                f"📄 <b>{escape_html(title)}</b>",
                f"⏱️ {duration} | 📝 {word_count} słów | 🌍 {lang}",
            ]

            if note_path:
                msg_lines.append(f"\n📓 Notatka zapisana do Obsidian")

            msg_lines.append(f"\n<code>ID: {job_id}</code>")

            await status_msg.edit_text("\n".join(msg_lines), parse_mode="HTML")

    except Exception as e:
        logger.exception(f"Transcription job {job_id} failed")
        async for session in get_session():
            repo = TranscriptionJobRepository(session)
            await repo.update_status(job_id, "failed", error=str(e))
            await session.commit()
        await status_msg.edit_text(f"❌ Błąd: {e}")


@authorized_only
async def transcriptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /transcriptions command - list recent transcriptions."""
    if not update.message:
        return

    if not settings.TRANSCRIPTION_ENABLED:
        await update.message.reply_text("❌ Transkrypcja jest wyłączona")
        return

    limit = 10
    if context.args:
        try:
            limit = min(int(context.args[0]), 20)
        except ValueError:
            pass

    async for session in get_session():
        repo = TranscriptionJobRepository(session)
        jobs = await repo.get_recent_jobs(limit=limit)

        if not jobs:
            await update.message.reply_text(
                "📭 <b>Brak transkrypcji</b>\n\n"
                "Użyj <code>/transcribe &lt;URL&gt;</code> aby rozpocząć.",
                parse_mode="HTML",
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

        lines.append(f"\n<i>Użyj /note &lt;ID&gt; aby wygenerować notatkę</i>")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@authorized_only
async def note_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /note command - generate note from transcription."""
    if not update.message:
        return

    if not settings.TRANSCRIPTION_ENABLED:
        await update.message.reply_text("❌ Transkrypcja jest wyłączona")
        return

    if not context.args:
        await update.message.reply_text(
            "Użycie: <code>/note &lt;ID_transkrypcji&gt;</code>\n\n"
            "Użyj <code>/transcriptions</code> aby zobaczyć listę.",
            parse_mode="HTML",
        )
        return

    try:
        job_id = UUID(context.args[0])
    except ValueError:
        # Try partial UUID match
        partial = context.args[0]
        async for session in get_session():
            repo = TranscriptionJobRepository(session)
            jobs = await repo.get_recent_jobs(limit=50)
            matching = [j for j in jobs if str(j.id).startswith(partial)]

            if len(matching) == 1:
                job_id = matching[0].id
            elif len(matching) > 1:
                await update.message.reply_text("❌ Znaleziono wiele pasujących ID. Podaj pełne UUID.")
                return
            else:
                await update.message.reply_text("❌ Nie znaleziono transkrypcji")
                return

    status_msg = await update.message.reply_text("🧠 Generuję notatkę...")

    async for session in get_session():
        repo = TranscriptionJobRepository(session)
        job = await repo.get_with_transcription(job_id)

        if not job:
            await status_msg.edit_text("❌ Nie znaleziono transkrypcji")
            return

        if not job.transcription:
            await status_msg.edit_text("❌ Transkrypcja nie jest gotowa")
            return

        if job.note:
            # Note already exists - show it
            n = job.note
            summary_short = n.summary_text[:500] + "..." if len(n.summary_text) > 500 else n.summary_text

            lines = [
                f"📓 <b>Notatka:</b> {escape_html(job.title or 'Untitled')}",
                "",
                f"<b>Podsumowanie:</b>",
                escape_html(summary_short),
                "",
            ]

            if n.key_topics:
                lines.append(f"<b>Tematy:</b> {', '.join(n.key_topics[:5])}")

            if n.category:
                lines.append(f"<b>Kategoria:</b> {n.category}")

            if n.obsidian_file_path:
                lines.append(f"\n📄 Zapisano w Obsidian")

            await status_msg.edit_text("\n".join(lines), parse_mode="HTML")
            return

        # Generate new note
        try:
            extractor = KnowledgeExtractor()
            result, error = await extractor.extract(job.transcription.full_text)

            if error or not result:
                await status_msg.edit_text(f"❌ Błąd: {error}")
                return

            note = await repo.add_note(
                job_id=job_id,
                summary_text=result.summary_text,
                key_topics=result.topics,
                key_points=result.key_points,
                entities=result.entities,
                action_items=result.action_items,
                category=result.category,
                tags=result.tags,
                model_used=result.model_used,
                processing_time_sec=result.processing_time_sec,
            )

            # Write to Obsidian
            if settings.GENERATE_OBSIDIAN_FILES:
                writer = TranscriptionNoteWriter()
                file_path = writer.write_note(
                    title=job.title or "Untitled",
                    extraction=result,
                    source_type=job.source_type,
                    source_url=job.source_url,
                    channel_name=job.channel_name,
                    duration_seconds=job.duration_seconds,
                )
                note.obsidian_file_path = str(file_path)

            await session.commit()

            # Format response
            summary_short = result.summary_text[:500] + "..." if len(result.summary_text) > 500 else result.summary_text

            lines = [
                f"✅ <b>Notatka wygenerowana!</b>",
                "",
                f"📓 <b>{escape_html(job.title or 'Untitled')}</b>",
                "",
                f"<b>Podsumowanie:</b>",
                escape_html(summary_short),
                "",
            ]

            if result.topics:
                lines.append(f"<b>Tematy:</b> {', '.join(result.topics[:5])}")

            if result.category:
                lines.append(f"<b>Kategoria:</b> {result.category}")

            lines.append(f"\n⏱️ {result.processing_time_sec:.1f}s | 🤖 {result.model_used}")

            await status_msg.edit_text("\n".join(lines), parse_mode="HTML")

        except Exception as e:
            logger.exception("Note generation failed")
            await status_msg.edit_text(f"❌ Błąd: {e}")
