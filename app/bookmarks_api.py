"""REST API for bookmarks / read later."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.dependencies import BookmarkRepoDep

router = APIRouter(prefix="/bookmarks", tags=["Bookmarks"])


class BookmarkCreate(BaseModel):
    url: str
    title: Optional[str] = None
    tags: Optional[list[str]] = None
    source: str = "api"


class BookmarkUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = None


@router.get("/")
async def list_bookmarks(
    repo: BookmarkRepoDep,
    status: Optional[str] = None,
    limit: int = 20,
):
    """List bookmarks, optionally filtered by status."""
    if status:
        bookmarks = await repo.get_by_status(status, limit=limit)
    else:
        bookmarks = await repo.get_recent(limit=limit)

    return {
        "bookmarks": [
            {
                "id": str(b.id),
                "url": b.url,
                "title": b.title,
                "status": b.status,
                "tags": b.tags,
                "created_at": b.created_at.isoformat(),
            }
            for b in bookmarks
        ],
        "count": len(bookmarks),
    }


@router.post("/")
async def create_bookmark(bookmark: BookmarkCreate, repo: BookmarkRepoDep):
    """Create a new bookmark."""
    # Check for duplicates
    existing = await repo.get_by_url(bookmark.url)
    if existing:
        return {
            "id": str(existing.id),
            "title": existing.title,
            "status": existing.status,
            "duplicate": True,
        }

    b = await repo.create_from_url(
        url=bookmark.url,
        title=bookmark.title,
        source=bookmark.source,
        tags=bookmark.tags,
    )

    from app.db.connection import get_session
    async for session in get_session():
        await session.commit()

    # RAG indexing
    if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
        try:
            from app.rag.hooks import index_bookmark_hook
            async for session in get_session():
                await index_bookmark_hook(b, session)
                await session.commit()
        except Exception:
            pass

    # Update Obsidian bookmarks index
    if settings.GENERATE_OBSIDIAN_FILES:
        try:
            all_bookmarks = await repo.get_all(limit=1000)
            from app.bookmarks_writer import write_bookmarks_index
            write_bookmarks_index(all_bookmarks)
        except Exception:
            pass

    return {"id": str(b.id), "url": b.url}


@router.get("/stats")
async def bookmark_stats(repo: BookmarkRepoDep):
    """Get bookmark statistics."""
    return await repo.stats()


@router.get("/{bookmark_id}")
async def get_bookmark(bookmark_id: UUID, repo: BookmarkRepoDep):
    """Get a single bookmark."""
    b = await repo.get_by_id(bookmark_id)
    if not b:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {
        "id": str(b.id),
        "url": b.url,
        "title": b.title,
        "description": b.description,
        "status": b.status,
        "tags": b.tags,
        "article_id": b.article_id,
        "transcription_job_id": str(b.transcription_job_id) if b.transcription_job_id else None,
        "created_at": b.created_at.isoformat(),
        "processed_at": b.processed_at.isoformat() if b.processed_at else None,
    }


@router.put("/{bookmark_id}")
async def update_bookmark(bookmark_id: UUID, update: BookmarkUpdate, repo: BookmarkRepoDep):
    """Update a bookmark."""
    kwargs = {k: v for k, v in update.model_dump().items() if v is not None}
    if not kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")

    b = await repo.update(bookmark_id, **kwargs)
    if not b:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    from app.db.connection import get_session
    async for session in get_session():
        await session.commit()

    return {"id": str(b.id), "status": b.status}


@router.delete("/{bookmark_id}")
async def delete_bookmark(bookmark_id: UUID, repo: BookmarkRepoDep):
    """Delete a bookmark."""
    deleted = await repo.delete(bookmark_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    from app.db.connection import get_session
    async for session in get_session():
        await session.commit()

    return {"deleted": True}
