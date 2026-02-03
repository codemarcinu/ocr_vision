"""Repository for personal notes."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Note
from app.db.repositories.base import BaseRepository


class NoteRepository(BaseRepository[Note]):
    """Repository for personal notes CRUD and search."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Note)

    async def get_recent(self, limit: int = 20, include_archived: bool = False) -> List[Note]:
        """Get recent notes ordered by creation date."""
        stmt = select(Note).order_by(desc(Note.created_at)).limit(limit)
        if not include_archived:
            stmt = stmt.where(Note.is_archived == False)  # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def search(self, query: str, limit: int = 20) -> List[Note]:
        """Search notes by title or content."""
        pattern = f"%{query}%"
        stmt = (
            select(Note)
            .where(
                Note.is_archived == False,  # noqa: E712
                or_(
                    Note.title.ilike(pattern),
                    Note.content.ilike(pattern),
                ),
            )
            .order_by(desc(Note.created_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_tags(self, tags: List[str], limit: int = 20) -> List[Note]:
        """Get notes containing any of the given tags."""
        stmt = (
            select(Note)
            .where(
                Note.is_archived == False,  # noqa: E712
                Note.tags.overlap(tags),
            )
            .order_by(desc(Note.created_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_today(self) -> List[Note]:
        """Get notes created today."""
        today = datetime.now().date()
        stmt = (
            select(Note)
            .where(
                Note.created_at >= datetime.combine(today, datetime.min.time()),
            )
            .order_by(desc(Note.created_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_quick(self, title: str, content: str = "") -> Note:
        """Create a quick note (from /n command)."""
        return await self.create(
            title=title,
            content=content or title,
        )

    async def archive(self, note_id: UUID) -> Optional[Note]:
        """Archive a note."""
        return await self.update(note_id, is_archived=True)
