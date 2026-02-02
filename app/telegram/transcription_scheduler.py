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


async def process_pending_jobs() -> Tuple[int, List[str]]:
    """
    Process pending transcription jobs.

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
        jobs = await repo.get_pending_jobs(limit=settings.TRANSCRIPTION_MAX_CONCURRENT_JOBS)

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

            logger.info(f"Job {job_id}: Note generated")
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
                f"✅ <b>Transkrypcja zakończona</b>\n\n"
                f"📄 {job_title}\n"
                f"📝 {word_count} słów\n\n"
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
    - Process pending jobs every 2 minutes
    - Cleanup temp files every hour
    """
    if not settings.TRANSCRIPTION_ENABLED:
        logger.info("Transcription scheduler disabled (TRANSCRIPTION_ENABLED=false)")
        return

    async def scheduled_process():
        """Scheduled job wrapper for processing pending jobs."""
        logger.debug("Checking for pending transcription jobs...")
        completed, errors = await process_pending_jobs()

        if completed > 0:
            logger.info(f"Processed {completed} transcription jobs")
            # Optionally send notification
            if settings.TELEGRAM_CHAT_ID:
                # Could send summary notification here
                pass

        if errors:
            logger.warning(f"Transcription errors: {errors}")

    async def scheduled_cleanup():
        """Scheduled job wrapper for cleanup."""
        logger.debug("Running transcription temp file cleanup...")
        cleaned = await cleanup_temp_files()
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} transcription temp files")

    # Add job - process pending every 2 minutes
    scheduler.add_job(
        scheduled_process,
        "interval",
        minutes=2,
        id="transcription_process",
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

    logger.info("Transcription scheduler registered (process: 2min, cleanup: 1h)")
