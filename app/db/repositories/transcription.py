"""Repository for transcription jobs."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Transcription, TranscriptionJob, TranscriptionNote
from app.db.repositories.base import BaseRepository


class TranscriptionJobRepository(BaseRepository[TranscriptionJob]):
    """Repository for transcription job operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, TranscriptionJob)

    async def get_by_url(self, url: str) -> Optional[TranscriptionJob]:
        """Get job by source URL (with relations loaded)."""
        stmt = (
            select(TranscriptionJob)
            .options(
                selectinload(TranscriptionJob.transcription),
                selectinload(TranscriptionJob.note),
            )
            .where(TranscriptionJob.source_url == url)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_jobs(self, limit: int = 10) -> List[TranscriptionJob]:
        """Get jobs in pending status."""
        stmt = (
            select(TranscriptionJob)
            .where(TranscriptionJob.status == "pending")
            .order_by(TranscriptionJob.created_at)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_recent_jobs(
        self,
        limit: int = 20,
        status: Optional[str] = None,
    ) -> List[TranscriptionJob]:
        """Get recent jobs with optional status filter."""
        stmt = (
            select(TranscriptionJob)
            .options(
                selectinload(TranscriptionJob.transcription),
                selectinload(TranscriptionJob.note),
            )
            .order_by(TranscriptionJob.created_at.desc())
            .limit(limit)
        )
        if status:
            stmt = stmt.where(TranscriptionJob.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_with_transcription(self, job_id: UUID) -> Optional[TranscriptionJob]:
        """Get job with transcription and note loaded."""
        stmt = (
            select(TranscriptionJob)
            .options(
                selectinload(TranscriptionJob.transcription),
                selectinload(TranscriptionJob.note),
            )
            .where(TranscriptionJob.id == job_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        job_id: UUID,
        status: str,
        progress: Optional[int] = None,
        error: Optional[str] = None,
    ) -> Optional[TranscriptionJob]:
        """Update job status and progress."""
        job = await self.get_by_id(job_id)
        if not job:
            return None

        job.status = status
        if progress is not None:
            job.progress_percent = progress
        if error:
            job.error_message = error

        if status == "transcribing" and not job.started_at:
            job.started_at = datetime.now()
        elif status in ("completed", "failed"):
            job.completed_at = datetime.now()

        await self.session.flush()
        await self.session.refresh(job)
        return job

    async def create_job(
        self,
        source_type: str,
        source_url: Optional[str] = None,
        source_filename: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        channel_name: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
        whisper_model: Optional[str] = None,
        language: Optional[str] = None,
    ) -> TranscriptionJob:
        """Create a new transcription job."""
        from app.config import settings

        job = TranscriptionJob(
            source_type=source_type,
            source_url=source_url,
            source_filename=source_filename,
            title=title,
            description=description,
            duration_seconds=duration_seconds,
            channel_name=channel_name,
            thumbnail_url=thumbnail_url,
            whisper_model=whisper_model or settings.WHISPER_MODEL,
            language=language,
            status="pending",
            progress_percent=0,
        )
        self.session.add(job)
        await self.session.flush()
        await self.session.refresh(job)
        return job

    async def add_transcription(
        self,
        job_id: UUID,
        full_text: str,
        segments: List[dict],
        detected_language: str,
        confidence: float,
        word_count: int,
        processing_time_sec: float,
    ) -> Transcription:
        """Add transcription to job."""
        transcription = Transcription(
            job_id=job_id,
            full_text=full_text,
            segments=segments,
            detected_language=detected_language,
            confidence=Decimal(str(round(confidence, 3))),
            word_count=word_count,
            processing_time_sec=Decimal(str(round(processing_time_sec, 2))),
        )
        self.session.add(transcription)
        await self.session.flush()
        await self.session.refresh(transcription)
        return transcription

    async def add_note(
        self,
        job_id: UUID,
        summary_text: str,
        key_topics: Optional[List[str]] = None,
        key_points: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        action_items: Optional[List[str]] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        obsidian_file_path: Optional[str] = None,
        model_used: Optional[str] = None,
        processing_time_sec: float = 0.0,
    ) -> TranscriptionNote:
        """Add note to job."""
        note = TranscriptionNote(
            job_id=job_id,
            summary_text=summary_text,
            key_topics=key_topics,
            key_points=key_points or [],
            entities=entities,
            action_items=action_items or [],
            category=category,
            tags=tags,
            obsidian_file_path=obsidian_file_path,
            model_used=model_used,
            processing_time_sec=Decimal(str(round(processing_time_sec, 2))),
        )
        self.session.add(note)
        await self.session.flush()
        await self.session.refresh(note)
        return note

    async def get_jobs_for_cleanup(self, hours: int = 24) -> List[TranscriptionJob]:
        """Get completed/failed jobs older than N hours for temp file cleanup."""
        cutoff = datetime.now() - timedelta(hours=hours)
        stmt = select(TranscriptionJob).where(
            and_(
                or_(
                    TranscriptionJob.status == "completed",
                    TranscriptionJob.status == "failed",
                ),
                TranscriptionJob.completed_at < cutoff,
                TranscriptionJob.temp_audio_path.isnot(None),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_stats(self) -> dict:
        """Get transcription statistics."""
        total = await self.count()

        # Count by status
        stmt = select(
            TranscriptionJob.status,
            func.count(TranscriptionJob.id),
        ).group_by(TranscriptionJob.status)
        result = await self.session.execute(stmt)
        status_counts = {row[0]: row[1] for row in result}

        return {
            "total_jobs": total,
            "by_status": status_counts,
            "pending": status_counts.get("pending", 0),
            "completed": status_counts.get("completed", 0),
            "failed": status_counts.get("failed", 0),
        }

    async def clear_temp_path(self, job_id: UUID) -> Optional[TranscriptionJob]:
        """Clear temp file paths after cleanup."""
        job = await self.get_by_id(job_id)
        if job:
            job.temp_audio_path = None
            job.temp_video_path = None
            await self.session.flush()
            await self.session.refresh(job)
        return job
