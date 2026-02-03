"""REST API for personal notes."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dependencies import NoteRepoDep

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
        from app.notes_writer import write_note_file
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
