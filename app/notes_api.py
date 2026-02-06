"""REST API for personal notes."""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dependencies import DbSession, NoteRepoDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notes", tags=["Notes"])


class NoteCreate(BaseModel):
    title: str
    content: str = ""
    category: Optional[str] = None
    tags: Optional[list[str]] = None


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None


class NoteResponse(BaseModel):
    id: UUID
    title: str
    content: str
    category: Optional[str]
    tags: Optional[list[str]]
    is_archived: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


@router.get("/")
async def list_notes(
    repo: NoteRepoDep,
    search: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 20,
):
    """List notes with optional search and tag filtering."""
    if search:
        notes = await repo.search(search, limit=limit)
    elif tag:
        notes = await repo.get_by_tags([tag], limit=limit)
    else:
        notes = await repo.get_recent(limit=limit)

    return {
        "notes": [
            {
                "id": str(n.id),
                "title": n.title,
                "content": n.content[:200],
                "category": n.category,
                "tags": n.tags,
                "created_at": n.created_at.isoformat(),
            }
            for n in notes
        ],
        "count": len(notes),
    }


@router.post("/")
async def create_note(note: NoteCreate, repo: NoteRepoDep):
    """Create a new note."""
    n = await repo.create(
        title=note.title,
        content=note.content or note.title,
        category=note.category,
        tags=note.tags,
    )
    from app.db.connection import get_session

    async for session in get_session():
        await session.commit()

    # Write to Obsidian
    from app.config import settings
    if settings.GENERATE_OBSIDIAN_FILES:
        from app.writers.notes import write_note_file
        write_note_file(n)

    # RAG indexing
    if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
        try:
            from app.rag.hooks import index_note_hook
            async for session in get_session():
                await index_note_hook(n, session)
                await session.commit()
        except Exception:
            pass

    # Push notification
    try:
        from app.push.hooks import push_note_created
        await push_note_created(title=n.title, note_id=str(n.id))
    except Exception:
        pass

    return {"id": str(n.id), "title": n.title}


@router.get("/{note_id}")
async def get_note(note_id: UUID, repo: NoteRepoDep):
    """Get a single note."""
    n = await repo.get_by_id(note_id)
    if not n:
        raise HTTPException(status_code=404, detail="Note not found")
    return {
        "id": str(n.id),
        "title": n.title,
        "content": n.content,
        "category": n.category,
        "tags": n.tags,
        "source_refs": n.source_refs,
        "is_archived": n.is_archived,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
    }


@router.put("/{note_id}")
async def update_note(note_id: UUID, update: NoteUpdate, repo: NoteRepoDep):
    """Update a note."""
    kwargs = {k: v for k, v in update.model_dump().items() if v is not None}
    if not kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")

    n = await repo.update(note_id, **kwargs)
    if not n:
        raise HTTPException(status_code=404, detail="Note not found")

    from app.db.connection import get_session
    async for session in get_session():
        await session.commit()

    return {"id": str(n.id), "title": n.title}


@router.delete("/{note_id}")
async def delete_note(note_id: UUID, repo: NoteRepoDep):
    """Delete a note."""
    deleted = await repo.delete(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")

    from app.db.connection import get_session
    async for session in get_session():
        await session.commit()

    return {"deleted": True}


# =============================================================================
# Notes Organizer Endpoints
# =============================================================================


@router.post("/organize/report")
async def organize_report(session: DbSession):
    """Generate a health report on notes — tags, categories, duplicates."""
    from app.services.notes_organizer import generate_report

    report = await generate_report(session)
    return report.to_dict()


@router.post("/organize/auto-tag")
async def organize_auto_tag(session: DbSession, dry_run: bool = True, limit: int = 20):
    """Auto-tag notes without tags using LLM.

    Args:
        dry_run: If true, only suggest tags without saving (default: true)
        limit: Max notes to process (default: 20)
    """
    from app.services.notes_organizer import auto_tag

    limit = max(1, min(limit, 50))
    suggestions = await auto_tag(session, dry_run=dry_run, limit=limit)
    return {
        "dry_run": dry_run,
        "processed": len(suggestions),
        "suggestions": [
            {
                "note_id": s.note_id,
                "title": s.title,
                "suggested_tags": s.suggested_tags,
                "applied": s.applied,
            }
            for s in suggestions
        ],
    }


@router.post("/organize/duplicates")
async def organize_duplicates(session: DbSession, threshold: float = 0.85):
    """Find potentially duplicate notes using embedding similarity."""
    from app.services.notes_organizer import find_duplicates

    threshold = max(0.7, min(threshold, 0.99))
    pairs = await find_duplicates(session, threshold=threshold)
    return {
        "threshold": threshold,
        "duplicate_pairs": len(pairs),
        "pairs": [
            {
                "note_a_id": p.note_a_id,
                "note_a_title": p.note_a_title,
                "note_b_id": p.note_b_id,
                "note_b_title": p.note_b_title,
                "similarity": p.similarity,
            }
            for p in pairs
        ],
    }
