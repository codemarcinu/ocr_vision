"""REST API for transcription management."""

import logging
from pathlib import Path, PurePosixPath
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, HttpUrl

from app.config import settings
from app.db.connection import get_session
from app.db.repositories.transcription import TranscriptionJobRepository
from app.transcription.downloader import DownloaderService, is_youtube_url
from app.transcription.extractor import KnowledgeExtractor
from app.transcription.note_writer import TranscriptionNoteWriter
from app.transcription.transcriber import TranscriberService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/transcription", tags=["Transcription"])


# Pydantic models for API
class TranscriptionJobCreate(BaseModel):
    url: HttpUrl
    language: Optional[str] = None
    whisper_model: Optional[str] = None
    auto_generate_note: Optional[bool] = None


class TranscriptionJobResponse(BaseModel):
    id: str
    source_type: str
    source_url: Optional[str]
    source_filename: Optional[str]
    title: Optional[str]
    channel_name: Optional[str]
    duration_seconds: Optional[int]
    status: str
    progress_percent: int
    error_message: Optional[str]
    whisper_model: str
    language: Optional[str]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    has_transcription: bool
    has_note: bool


class TranscriptionResponse(BaseModel):
    job_id: str
    full_text: str
    segments: List[dict]
    detected_language: str
    word_count: int
    confidence: float
    processing_time_sec: float


class NoteResponse(BaseModel):
    job_id: str
    summary_text: str
    key_topics: List[str]
    key_points: List[str]
    entities: List[str]
    action_items: List[str]
    category: Optional[str]
    tags: List[str]
    obsidian_file_path: Optional[str]
    model_used: str
    processing_time_sec: float


class GenerateNoteRequest(BaseModel):
    include_transcription: Optional[bool] = False


class StatsResponse(BaseModel):
    total_jobs: int
    by_status: dict
    pending: int
    completed: int
    failed: int


def _job_to_response(job) -> TranscriptionJobResponse:
    """Convert job model to response."""
    # Use getattr to avoid lazy loading issues in async context
    has_transcription = getattr(job, 'transcription', None) is not None
    has_note = getattr(job, 'note', None) is not None

    return TranscriptionJobResponse(
        id=str(job.id),
        source_type=job.source_type,
        source_url=job.source_url,
        source_filename=job.source_filename,
        title=job.title,
        channel_name=job.channel_name,
        duration_seconds=job.duration_seconds,
        status=job.status,
        progress_percent=job.progress_percent,
        error_message=job.error_message,
        whisper_model=job.whisper_model,
        language=job.language,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        has_transcription=has_transcription,
        has_note=has_note,
    )


@router.get("/jobs", response_model=List[TranscriptionJobResponse])
async def list_jobs(
    status: Optional[str] = None,
    limit: int = 20,
):
    """List recent transcription jobs."""
    if not settings.TRANSCRIPTION_ENABLED:
        raise HTTPException(status_code=503, detail="Transcription is disabled")

    async for session in get_session():
        repo = TranscriptionJobRepository(session)
        jobs = await repo.get_recent_jobs(limit=limit, status=status)
        return [_job_to_response(job) for job in jobs]


@router.post("/jobs", response_model=TranscriptionJobResponse)
async def create_job_from_url(data: TranscriptionJobCreate):
    """Create a new transcription job from URL."""
    if not settings.TRANSCRIPTION_ENABLED:
        raise HTTPException(status_code=503, detail="Transcription is disabled")

    url = str(data.url)

    async for session in get_session():
        repo = TranscriptionJobRepository(session)

        # Check if already exists
        existing = await repo.get_by_url(url)
        if existing and existing.status != "failed":
            return _job_to_response(existing)

        # Detect source type
        source_type = "youtube" if is_youtube_url(url) else "url"

        # Create job
        job = await repo.create_job(
            source_type=source_type,
            source_url=url,
            whisper_model=data.whisper_model,
            language=data.language,
        )
        await session.commit()

        return _job_to_response(job)


@router.post("/jobs/upload", response_model=TranscriptionJobResponse)
async def create_job_from_file(
    file: UploadFile = File(...),
    language: Optional[str] = None,
    whisper_model: Optional[str] = None,
):
    """Create a new transcription job from uploaded audio file."""
    if not settings.TRANSCRIPTION_ENABLED:
        raise HTTPException(status_code=503, detail="Transcription is disabled")

    # Validate file type
    allowed_extensions = {".mp3", ".m4a", ".wav", ".ogg", ".webm", ".mp4", ".opus"}
    file_ext = Path(file.filename).suffix.lower() if file.filename else ""
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file_ext}. Allowed: {', '.join(allowed_extensions)}"
        )

    # Save file to temp directory (sanitize filename to prevent path traversal)
    safe_filename = PurePosixPath(file.filename).name if file.filename else ""
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    settings.TRANSCRIPTION_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = settings.TRANSCRIPTION_TEMP_DIR / safe_filename
    with open(temp_path, "wb") as f:
        content = await file.read()
        f.write(content)

    async for session in get_session():
        repo = TranscriptionJobRepository(session)

        job = await repo.create_job(
            source_type="file",
            source_filename=file.filename,
            whisper_model=whisper_model,
            language=language,
        )
        job.temp_audio_path = str(temp_path)
        await session.commit()

        return _job_to_response(job)


@router.get("/jobs/{job_id}", response_model=TranscriptionJobResponse)
async def get_job(job_id: UUID):
    """Get transcription job details."""
    if not settings.TRANSCRIPTION_ENABLED:
        raise HTTPException(status_code=503, detail="Transcription is disabled")

    async for session in get_session():
        repo = TranscriptionJobRepository(session)
        job = await repo.get_with_transcription(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return _job_to_response(job)


@router.get("/jobs/{job_id}/transcription", response_model=TranscriptionResponse)
async def get_transcription(job_id: UUID):
    """Get transcription text and segments."""
    if not settings.TRANSCRIPTION_ENABLED:
        raise HTTPException(status_code=503, detail="Transcription is disabled")

    async for session in get_session():
        repo = TranscriptionJobRepository(session)
        job = await repo.get_with_transcription(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if not job.transcription:
            raise HTTPException(status_code=404, detail="Transcription not ready")

        t = job.transcription
        return TranscriptionResponse(
            job_id=str(job_id),
            full_text=t.full_text,
            segments=t.segments or [],
            detected_language=t.detected_language or "unknown",
            word_count=t.word_count or 0,
            confidence=float(t.confidence or 0),
            processing_time_sec=float(t.processing_time_sec or 0),
        )


@router.get("/jobs/{job_id}/note", response_model=NoteResponse)
async def get_note(job_id: UUID):
    """Get generated note for transcription."""
    if not settings.TRANSCRIPTION_ENABLED:
        raise HTTPException(status_code=503, detail="Transcription is disabled")

    async for session in get_session():
        repo = TranscriptionJobRepository(session)
        job = await repo.get_with_transcription(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if not job.note:
            raise HTTPException(status_code=404, detail="Note not generated")

        n = job.note
        return NoteResponse(
            job_id=str(job_id),
            summary_text=n.summary_text,
            key_topics=n.key_topics or [],
            key_points=n.key_points or [],
            entities=n.entities or [],
            action_items=n.action_items or [],
            category=n.category,
            tags=n.tags or [],
            obsidian_file_path=n.obsidian_file_path,
            model_used=n.model_used or "unknown",
            processing_time_sec=float(n.processing_time_sec or 0),
        )


@router.post("/jobs/{job_id}/generate-note", response_model=NoteResponse)
async def generate_note(job_id: UUID, data: GenerateNoteRequest = None):
    """Generate note from existing transcription."""
    if not settings.TRANSCRIPTION_ENABLED:
        raise HTTPException(status_code=503, detail="Transcription is disabled")

    data = data or GenerateNoteRequest()

    async for session in get_session():
        repo = TranscriptionJobRepository(session)
        job = await repo.get_with_transcription(job_id)

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if not job.transcription:
            raise HTTPException(status_code=400, detail="Transcription not ready")
        if job.note:
            # Return existing note
            n = job.note
            return NoteResponse(
                job_id=str(job_id),
                summary_text=n.summary_text,
                key_topics=n.key_topics or [],
                key_points=n.key_points or [],
                entities=n.entities or [],
                action_items=n.action_items or [],
                category=n.category,
                tags=n.tags or [],
                obsidian_file_path=n.obsidian_file_path,
                model_used=n.model_used or "unknown",
                processing_time_sec=float(n.processing_time_sec or 0),
            )

        # Extract knowledge
        extractor = KnowledgeExtractor()
        result, error = await extractor.extract(job.transcription.full_text)

        if error or not result:
            raise HTTPException(status_code=500, detail=f"Extraction failed: {error}")

        # Save note to database
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

        # Write to Obsidian if enabled
        if settings.GENERATE_OBSIDIAN_FILES:
            writer = TranscriptionNoteWriter()
            file_path = writer.write_note(
                title=job.title or "Untitled",
                extraction=result,
                source_type=job.source_type,
                source_url=job.source_url,
                channel_name=job.channel_name,
                duration_seconds=job.duration_seconds,
                transcription_text=(
                    job.transcription.full_text if data.include_transcription else None
                ),
                include_transcription=data.include_transcription,
            )
            note.obsidian_file_path = str(file_path)

        await session.commit()

        # RAG indexing
        if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
            try:
                from app.rag.hooks import index_transcription_hook
                await index_transcription_hook(job, session)
                await session.commit()
            except Exception:
                pass

        return NoteResponse(
            job_id=str(job_id),
            summary_text=result.summary_text,
            key_topics=result.topics,
            key_points=result.key_points,
            entities=result.entities,
            action_items=result.action_items,
            category=result.category,
            tags=result.tags,
            obsidian_file_path=note.obsidian_file_path,
            model_used=result.model_used,
            processing_time_sec=result.processing_time_sec,
        )


@router.post("/jobs/{job_id}/process")
async def process_job(job_id: UUID):
    """
    Process a pending transcription job immediately.

    This triggers the full pipeline: download → transcribe → generate note.
    """
    if not settings.TRANSCRIPTION_ENABLED:
        raise HTTPException(status_code=503, detail="Transcription is disabled")

    from app.transcription.transcriber import TranscriberService
    from app.transcription.downloader import DownloaderService
    from app.transcription.extractor import KnowledgeExtractor
    from app.transcription.note_writer import TranscriptionNoteWriter

    async for session in get_session():
        repo = TranscriptionJobRepository(session)
        job = await repo.get_with_transcription(job_id)

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status == "completed":
            return {"status": "already_completed"}
        if job.status in ("downloading", "transcribing", "extracting"):
            return {"status": "in_progress"}

        try:
            # Update status to downloading
            await repo.update_status(job_id, "downloading", progress=0)
            await session.commit()

            audio_path = None
            subtitle_path = None

            # Step 1: Download if URL
            if job.source_url:
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
                # Use uploaded file
                audio_path = job.temp_audio_path

            if not audio_path:
                raise ValueError("No audio file available")

            # Step 2: Transcribe
            await repo.update_status(job_id, "transcribing", progress=10)
            await session.commit()

            transcriber = TranscriberService()

            if subtitle_path:
                # Use existing subtitles
                full_text, segments, info = await transcriber.transcribe_with_subtitles(
                    audio_path, subtitle_path
                )
            else:
                # Run Whisper transcription
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

            # Step 3: Generate note if configured
            if settings.TRANSCRIPTION_AUTO_GENERATE_NOTE:
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

                    await session.commit()

                    # RAG indexing
                    if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
                        try:
                            from app.rag.hooks import index_transcription_hook
                            await index_transcription_hook(job, session)
                            await session.commit()
                        except Exception:
                            pass

            # Mark completed
            await repo.update_status(job_id, "completed", progress=100)
            await session.commit()

            return {"status": "completed"}

        except Exception as e:
            logger.exception(f"Job {job_id} failed: {e}")
            await repo.update_status(job_id, "failed", error=str(e))
            await session.commit()
            raise HTTPException(status_code=500, detail=str(e))


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: UUID):
    """Delete transcription job and associated data."""
    if not settings.TRANSCRIPTION_ENABLED:
        raise HTTPException(status_code=503, detail="Transcription is disabled")

    async for session in get_session():
        repo = TranscriptionJobRepository(session)
        job = await repo.get_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Clean up temp files
        if job.temp_audio_path:
            path = Path(job.temp_audio_path)
            if path.exists():
                path.unlink()
        if job.temp_video_path:
            path = Path(job.temp_video_path)
            if path.exists():
                path.unlink()

        await repo.delete(job_id)
        await session.commit()

        return {"success": True}


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get transcription statistics."""
    if not settings.TRANSCRIPTION_ENABLED:
        raise HTTPException(status_code=503, detail="Transcription is disabled")

    async for session in get_session():
        repo = TranscriptionJobRepository(session)
        stats = await repo.get_stats()
        return StatsResponse(**stats)
