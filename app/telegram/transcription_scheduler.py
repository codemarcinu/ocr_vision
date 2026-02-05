"""Transcription scheduler for background job processing and cleanup."""

import logging
from pathlib import Path
from typing import List, Tuple

from telegram import Bot

from app.config import settings
from app.db.connection import get_session
from app.db.repositories.transcription import TranscriptionJobRepository
from app.transcription.downloader import DownloaderService
from app.transcription.extractor import KnowledgeExtractor
from app.transcription.note_writer import TranscriptionNoteWriter
from app.transcription.transcriber import TranscriberService

logger = logging.getLogger(__name__)


async def process_pending_jobs(exclude_voice: bool = True) -> Tuple[int, List[str]]:
    """
    Process pending transcription jobs.

    Args:
        exclude_voice: If True, skip voice notes (processed separately)

    Returns:
        Tuple of (completed count, list of error messages)
    """
    completed = 0
    errors = []

    if not settings.TRANSCRIPTION_ENABLED:
        return completed, errors

    async for session in get_session():
        repo = TranscriptionJobRepository(session)

        # Get pending jobs (limit to max concurrent)
        jobs = await repo.get_pending_jobs(
            limit=settings.TRANSCRIPTION_MAX_CONCURRENT_JOBS,
            exclude_source_type="voice" if exclude_voice else None,
        )

        if not jobs:
            return completed, errors

        logger.info(f"Processing {len(jobs)} pending transcription jobs")

        for job in jobs:
            try:
                # Process job
                await _process_single_job(repo, session, job)
                completed += 1

            except Exception as e:
                logger.exception(f"Failed to process job {job.id}")
                await repo.update_status(job.id, "failed", error=str(e))
                errors.append(f"{job.title or job.id}: {str(e)}")

            await session.commit()

    return completed, errors


async def process_voice_notes(bot: Bot = None) -> Tuple[int, List[str]]:
    """
    Process pending voice note jobs.

    Voice notes are processed separately to allow batch processing
    and avoid VRAM conflicts with chat models.

    Returns:
        Tuple of (completed count, list of error messages)
    """
    completed = 0
    errors = []

    if not settings.TRANSCRIPTION_ENABLED or not settings.NOTES_ENABLED:
        return completed, errors

    async for session in get_session():
        repo = TranscriptionJobRepository(session)

        # Get only voice jobs
        jobs = await repo.get_pending_jobs(
            limit=settings.TRANSCRIPTION_MAX_CONCURRENT_JOBS,
            only_source_type="voice",
        )

        if not jobs:
            return completed, errors

        logger.info(f"Processing {len(jobs)} voice notes")

        for job in jobs:
            try:
                await _process_voice_note(repo, session, job, bot)
                completed += 1

            except Exception as e:
                logger.exception(f"Failed to process voice note {job.id}")
                await repo.update_status(job.id, "failed", error=str(e))
                errors.append(f"{job.title or job.id}: {str(e)}")

            await session.commit()

    return completed, errors


async def _process_voice_note(repo, session, job, bot: Bot = None) -> None:
    """Process a single voice note job.

    Voice notes have a simplified flow:
    1. Transcribe with Whisper
    2. Save as regular Note (not TranscriptionNote)
    3. No knowledge extraction (voice notes are usually short)
    """
    from app.db.repositories.notes import NoteRepository
    from app.notes_writer import write_note_file

    job_id = job.id
    audio_path = job.temp_audio_path

    if not audio_path:
        raise ValueError("No audio file available")

    # Step 1: Transcribe
    logger.info(f"Voice note {job_id}: Transcribing...")
    await repo.update_status(job_id, "transcribing", progress=10)
    await session.commit()

    transcriber = TranscriberService()
    full_text, segments, info = await transcriber.transcribe(
        audio_path, language=job.language
    )
    logger.info(
        f"Voice note {job_id}: Transcribed {info['word_count']} words "
        f"in {info['processing_time_sec']:.1f}s"
    )

    if not full_text or not full_text.strip():
        raise ValueError("Nie udało się rozpoznać mowy w nagraniu")

    full_text = full_text.strip()

    # Save transcription record
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

    # Step 2: Create Note (simple, no extraction)
    await repo.update_status(job_id, "extracting", progress=80)
    await session.commit()

    # Generate title from first ~50 chars
    if len(full_text) > 50:
        title = full_text[:50].rsplit(" ", 1)[0]
        if not title:
            title = full_text[:50]
    else:
        title = full_text

    note_repo = NoteRepository(session)
    note = await note_repo.create(
        title=title,
        content=full_text,
        tags=["voice"],
    )
    await session.commit()

    # Write to Obsidian
    if settings.GENERATE_OBSIDIAN_FILES:
        write_note_file(note)

    # RAG indexing
    if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
        try:
            from app.rag.hooks import index_note_hook
            await index_note_hook(note, session)
            await session.commit()
        except Exception as e:
            logger.warning(f"Voice note {job_id}: RAG indexing failed: {e}")

    # Mark completed
    await repo.update_status(job_id, "completed", progress=100)
    logger.info(f"Voice note {job_id}: Note created - {info['word_count']} words")

    # Send notification
    if bot and settings.TELEGRAM_CHAT_ID:
        try:
            text_preview = full_text[:200] + "..." if len(full_text) > 200 else full_text
            await bot.send_message(
                chat_id=settings.TELEGRAM_CHAT_ID,
                text=(
                    f"<b>Notatka głosowa zapisana!</b>\n\n"
                    f"{text_preview}\n\n"
                    f"{info['word_count']} słów\n"
                    f"<code>ID: {str(note.id)[:8]}</code>"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Failed to send voice note notification: {e}")


async def _process_single_job(repo, session, job) -> None:
    """Process a single transcription job."""
    job_id = job.id
    audio_path = None
    subtitle_path = None

    # Step 1: Download if URL
    if job.source_url:
        logger.info(f"Job {job_id}: Downloading from {job.source_url}")
        await repo.update_status(job_id, "downloading", progress=0)
        await session.commit()

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
    else:
        audio_path = job.temp_audio_path

    if not audio_path:
        raise ValueError("No audio file available")

    # Step 2: Transcribe
    logger.info(f"Job {job_id}: Transcribing...")
    await repo.update_status(job_id, "transcribing", progress=10)
    await session.commit()

    transcriber = TranscriberService()

    if subtitle_path:
        # Use existing subtitles from YouTube
        full_text, segments, info = await transcriber.transcribe_with_subtitles(
            audio_path, subtitle_path
        )
        logger.info(f"Job {job_id}: Used existing subtitles")
    else:
        # Run Whisper transcription
        full_text, segments, info = await transcriber.transcribe(
            audio_path, language=job.language
        )
        logger.info(
            f"Job {job_id}: Transcribed {info['word_count']} words "
            f"in {info['processing_time_sec']:.1f}s"
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

    # Step 3: Generate note if configured
    if settings.TRANSCRIPTION_AUTO_GENERATE_NOTE:
        logger.info(f"Job {job_id}: Extracting knowledge...")
        await repo.update_status(job_id, "extracting", progress=80)
        await session.commit()

        # Progress callback for map-reduce extraction
        def extraction_progress(percent: int, status: str) -> None:
            # Scale 0-100% to 80-99% range (extracting phase)
            scaled_progress = 80 + int(percent * 0.19)
            logger.debug(f"Job {job_id}: Extraction progress {percent}% ({status})")

        extractor = KnowledgeExtractor()
        result, error = await extractor.extract(
            full_text,
            progress_callback=extraction_progress,
        )

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

            if result.chunks_processed > 0:
                logger.info(
                    f"Job {job_id}: Note generated (map-reduce: {result.chunks_processed} chunks)"
                )
            else:
                logger.info(f"Job {job_id}: Note generated (single-pass)")
        elif error:
            logger.warning(f"Job {job_id}: Note extraction failed: {error}")

    # Mark completed
    await repo.update_status(job_id, "completed", progress=100)
    logger.info(f"Job {job_id}: Completed successfully")


async def cleanup_temp_files() -> int:
    """
    Clean up temporary files for old completed jobs.

    Returns:
        Number of jobs cleaned up
    """
    cleaned = 0

    if not settings.TRANSCRIPTION_ENABLED:
        return cleaned

    async for session in get_session():
        repo = TranscriptionJobRepository(session)

        # Get jobs older than TRANSCRIPTION_CLEANUP_HOURS
        jobs = await repo.get_jobs_for_cleanup(hours=settings.TRANSCRIPTION_CLEANUP_HOURS)

        for job in jobs:
            # Remove temp audio file
            if job.temp_audio_path:
                path = Path(job.temp_audio_path)
                if path.exists():
                    try:
                        path.unlink()
                        logger.debug(f"Cleaned up: {path.name}")
                    except OSError as e:
                        logger.warning(f"Failed to delete {path}: {e}")

            # Remove temp video file
            if job.temp_video_path:
                path = Path(job.temp_video_path)
                if path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        pass

            # Clear paths in database
            await repo.clear_temp_path(job.id)
            cleaned += 1

        if cleaned > 0:
            await session.commit()
            logger.info(f"Cleaned up temp files for {cleaned} jobs")

    return cleaned


async def send_completion_notification(
    bot: Bot,
    chat_id: int,
    job_title: str,
    word_count: int,
) -> None:
    """Send notification about completed transcription."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"<b>Transkrypcja zakończona</b>\n\n"
                f"{job_title}\n"
                f"{word_count} słów\n\n"
                f"Użyj /transcriptions aby zobaczyć szczegóły."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to send transcription notification: {e}")


def register_transcription_scheduler(scheduler, bot: Bot) -> None:
    """
    Register transcription jobs with scheduler.

    Adds jobs to existing APScheduler from notifications.py:
    - Process pending jobs every 2 minutes (excluding voice notes)
    - Process voice notes every 30 minutes (configurable)
    - Cleanup temp files every hour
    """
    if not settings.TRANSCRIPTION_ENABLED:
        logger.info("Transcription scheduler disabled (TRANSCRIPTION_ENABLED=false)")
        return

    async def scheduled_process():
        """Scheduled job wrapper for processing pending jobs (excluding voice)."""
        logger.debug("Checking for pending transcription jobs...")
        completed, errors = await process_pending_jobs(exclude_voice=True)

        if completed > 0:
            logger.info(f"Processed {completed} transcription jobs")

        if errors:
            logger.warning(f"Transcription errors: {errors}")

    async def scheduled_voice_notes():
        """Scheduled job wrapper for processing voice notes."""
        logger.debug("Checking for pending voice notes...")
        completed, errors = await process_voice_notes(bot=bot)

        if completed > 0:
            logger.info(f"Processed {completed} voice notes")

        if errors:
            logger.warning(f"Voice note errors: {errors}")

    async def scheduled_cleanup():
        """Scheduled job wrapper for cleanup."""
        logger.debug("Running transcription temp file cleanup...")
        cleaned = await cleanup_temp_files()
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} transcription temp files")

    # Add job - process YouTube/URL transcriptions at 6:00 and 18:00
    scheduler.add_job(
        scheduled_process,
        "cron",
        hour="6,18",
        minute=0,
        id="transcription_process",
        replace_existing=True,
    )

    # Add voice notes job - process every 30 minutes (configurable)
    voice_interval = settings.VOICE_NOTE_PROCESS_INTERVAL_MINUTES
    scheduler.add_job(
        scheduled_voice_notes,
        "interval",
        minutes=voice_interval,
        id="voice_notes_process",
        replace_existing=True,
    )

    # Add cleanup job - every hour
    scheduler.add_job(
        scheduled_cleanup,
        "interval",
        hours=1,
        id="transcription_cleanup",
        replace_existing=True,
    )

    logger.info(
        f"Transcription scheduler registered "
        f"(process: 6:00/18:00, voice: {voice_interval}min, cleanup: 1h)"
    )
