"""Repository for bookmarks / read later."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bookmark
from app.db.repositories.base import BaseRepository


class BookmarkRepository(BaseRepository[Bookmark]):
    """Repository for bookmark CRUD and queries."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Bookmark)

    async def get_recent(self, limit: int = 20) -> List[Bookmark]:
        """Get recent bookmarks."""
        stmt = (
            select(Bookmark)
            .order_by(desc(Bookmark.created_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_status(self, status: str, limit: int = 50) -> List[Bookmark]:
        """Get bookmarks by status (pending, read, archived)."""
        stmt = (
            select(Bookmark)
            .where(Bookmark.status == status)
            .order_by(desc(Bookmark.created_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending(self, limit: int = 50) -> List[Bookmark]:
        """Get pending bookmarks."""
        return await self.get_by_status("pending", limit)

    async def get_by_url(self, url: str) -> Optional[Bookmark]:
        """Get bookmark by URL (check for duplicates)."""
        stmt = select(Bookmark).where(Bookmark.url == url)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_from_url(
        self,
        url: str,
        title: Optional[str] = None,
        source: str = "api",
        tags: Optional[List[str]] = None,
    ) -> Bookmark:
        """Create bookmark from URL."""
        return await self.create(
            url=url,
            title=title,
            source=source,
            tags=tags,
        )

    async def mark_read(self, bookmark_id: UUID) -> Optional[Bookmark]:
        """Mark bookmark as read."""
        return await self.update(
            bookmark_id,
            status="read",
            processed_at=datetime.utcnow(),
        )

    async def mark_archived(self, bookmark_id: UUID) -> Optional[Bookmark]:
        """Archive a bookmark."""
        return await self.update(bookmark_id, status="archived")

    async def link_article(self, bookmark_id: UUID, article_id: int) -> Optional[Bookmark]:
        """Link bookmark to a summarized article."""
        return await self.update(
            bookmark_id,
            article_id=article_id,
            status="read",
            processed_at=datetime.utcnow(),
        )

    async def link_transcription(self, bookmark_id: UUID, job_id: UUID) -> Optional[Bookmark]:
        """Link bookmark to a transcription job."""
        return await self.update(
            bookmark_id,
            transcription_job_id=job_id,
            status="read",
            processed_at=datetime.utcnow(),
        )

    async def stats(self) -> dict:
        """Get bookmark statistics."""
        from sqlalchemy import func

        total = await self.count()
        stmt_pending = select(func.count()).select_from(Bookmark).where(
            Bookmark.status == "pending"
        )
        result = await self.session.execute(stmt_pending)
        pending = result.scalar() or 0

        return {
            "total": total,
            "pending": pending,
            "read": total - pending,
        }
