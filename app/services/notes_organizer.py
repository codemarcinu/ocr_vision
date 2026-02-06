"""Notes organizer service — report, auto-tagging, duplicate detection."""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Note
from app.db.repositories.notes import NoteRepository
from app import ollama_client

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 20

AUTO_TAG_PROMPT = """\
Przeanalizuj poniższą notatkę i zaproponuj 2-5 tagów w języku polskim.
Tagi powinny być krótkie (1-2 słowa), pisane małymi literami, bez #.
Kategorie tagów: temat, typ (lista, przepis, pomysł, reminder), kontekst.

Tytuł: {title}
Treść: {content}

Odpowiedz TYLKO JSON: {{"tags": ["tag1", "tag2", ...]}}"""

DUPLICATE_THRESHOLD = 0.85


@dataclass
class NoteReport:
    """Report on notes health."""

    total: int = 0
    without_tags: int = 0
    without_category: int = 0
    short_content: int = 0
    archived: int = 0
    duplicate_pairs: int = 0
    sample_untagged: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "without_tags": self.without_tags,
            "without_category": self.without_category,
            "short_content": self.short_content,
            "archived": self.archived,
            "duplicate_pairs": self.duplicate_pairs,
            "sample_untagged": self.sample_untagged,
        }

    def to_text(self) -> str:
        lines = [
            f"Notatki: {self.total} (w tym {self.archived} zarchiwizowanych)",
            f"Bez tagów: {self.without_tags}",
            f"Bez kategorii: {self.without_category}",
            f"Krótkie (<20 znaków): {self.short_content}",
            f"Potencjalne duplikaty: {self.duplicate_pairs} par",
        ]
        if self.sample_untagged:
            lines.append("Przykłady bez tagów:")
            for n in self.sample_untagged[:5]:
                lines.append(f"  - {n['title']}")
        return "\n".join(lines)


@dataclass
class TagSuggestion:
    """Auto-tag suggestion for a single note."""

    note_id: str
    title: str
    suggested_tags: list[str]
    applied: bool = False


@dataclass
class DuplicatePair:
    """A pair of potentially duplicate notes."""

    note_a_id: str
    note_a_title: str
    note_b_id: str
    note_b_title: str
    similarity: float


async def generate_report(session: AsyncSession) -> NoteReport:
    """Generate a health report on all notes."""
    report = NoteReport()

    # Total count (including archived)
    result = await session.execute(select(func.count(Note.id)))
    report.total = result.scalar() or 0

    # Archived
    result = await session.execute(
        select(func.count(Note.id)).where(Note.is_archived == True)  # noqa: E712
    )
    report.archived = result.scalar() or 0

    # Without tags (active only)
    result = await session.execute(
        select(func.count(Note.id)).where(
            Note.is_archived == False,  # noqa: E712
            or_(Note.tags == None, Note.tags == []),  # noqa: E711
        )
    )
    report.without_tags = result.scalar() or 0

    # Without category
    result = await session.execute(
        select(func.count(Note.id)).where(
            Note.is_archived == False,  # noqa: E712
            or_(Note.category == None, Note.category == ""),  # noqa: E711
        )
    )
    report.without_category = result.scalar() or 0

    # Short content
    result = await session.execute(
        select(func.count(Note.id)).where(
            Note.is_archived == False,  # noqa: E712
            func.length(Note.content) < 20,
        )
    )
    report.short_content = result.scalar() or 0

    # Sample untagged notes
    result = await session.execute(
        select(Note)
        .where(
            Note.is_archived == False,  # noqa: E712
            or_(Note.tags == None, Note.tags == []),  # noqa: E711
        )
        .order_by(Note.created_at.desc())
        .limit(5)
    )
    for n in result.scalars().all():
        report.sample_untagged.append({
            "id": str(n.id),
            "title": n.title,
            "created_at": n.created_at.isoformat(),
        })

    # Duplicate count (quick — uses find_duplicates)
    try:
        dupes = await find_duplicates(session)
        report.duplicate_pairs = len(dupes)
    except Exception as e:
        logger.warning(f"Duplicate detection failed in report: {e}")
        report.duplicate_pairs = 0

    return report


async def auto_tag(
    session: AsyncSession,
    dry_run: bool = True,
    limit: int = MAX_BATCH_SIZE,
) -> list[TagSuggestion]:
    """Auto-tag notes that have no tags using LLM.

    Args:
        session: Database session
        dry_run: If True, only suggest tags without saving
        limit: Max notes to process in one batch

    Returns:
        List of tag suggestions (applied=True if saved)
    """
    # Get untagged notes
    result = await session.execute(
        select(Note)
        .where(
            Note.is_archived == False,  # noqa: E712
            or_(Note.tags == None, Note.tags == []),  # noqa: E711
        )
        .order_by(Note.created_at.desc())
        .limit(limit)
    )
    notes = list(result.scalars().all())

    if not notes:
        return []

    suggestions: list[TagSuggestion] = []
    repo = NoteRepository(session)

    for note in notes:
        content_preview = note.content[:500] if note.content else note.title
        prompt = AUTO_TAG_PROMPT.format(title=note.title, content=content_preview)

        start = time.time()
        raw, error = await ollama_client.post_generate(
            model=settings.CLASSIFIER_MODEL,
            prompt=prompt,
            options={"temperature": 0.1},
            timeout=30.0,
            keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
        )
        elapsed = time.time() - start

        if error:
            logger.warning(f"Auto-tag LLM error for '{note.title}': {error}")
            continue

        # Parse tags from JSON response
        tags = _parse_tags_response(raw)
        if not tags:
            logger.warning(f"No tags parsed for '{note.title}', raw: {raw[:200]}")
            continue

        suggestion = TagSuggestion(
            note_id=str(note.id),
            title=note.title,
            suggested_tags=tags,
        )

        if not dry_run:
            existing = note.tags or []
            merged = list(set(existing + tags))
            await repo.update(note.id, tags=merged)
            suggestion.applied = True
            logger.info(f"Auto-tagged '{note.title}': {tags} ({elapsed:.1f}s)")

        suggestions.append(suggestion)

    if not dry_run:
        await session.commit()

    return suggestions


async def find_duplicates(
    session: AsyncSession,
    threshold: float = DUPLICATE_THRESHOLD,
) -> list[DuplicatePair]:
    """Find potentially duplicate notes using embedding similarity.

    Uses existing RAG embeddings to compare notes pairwise.
    """
    from app.rag import retriever

    # Get all active notes
    result = await session.execute(
        select(Note)
        .where(Note.is_archived == False)  # noqa: E712
        .order_by(Note.created_at.desc())
        .limit(200)
    )
    notes = list(result.scalars().all())

    if len(notes) < 2:
        return []

    pairs: list[DuplicatePair] = []
    seen_pairs: set[tuple[str, str]] = set()

    for note in notes:
        query = f"{note.title} {note.content[:300]}"
        try:
            results = await retriever.search(
                query=query,
                session=session,
                top_k=5,
                content_types=["note"],
            )
        except Exception as e:
            logger.warning(f"Duplicate search failed for '{note.title}': {e}")
            continue

        for r in results:
            if r.content_id == str(note.id):
                continue
            if r.score < threshold:
                continue

            # Deduplicate pairs (A,B) == (B,A)
            pair_key = tuple(sorted([str(note.id), r.content_id]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            other_title = r.metadata.get("title", r.text_chunk[:50])
            pairs.append(DuplicatePair(
                note_a_id=str(note.id),
                note_a_title=note.title,
                note_b_id=r.content_id,
                note_b_title=other_title,
                similarity=round(r.score, 3),
            ))

    # Sort by similarity descending
    pairs.sort(key=lambda p: p.similarity, reverse=True)
    return pairs


def _parse_tags_response(raw: str) -> list[str]:
    """Parse tags from LLM JSON response."""
    try:
        # Strip markdown fences if present
        text = raw.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        text = text.strip()

        data = json.loads(text)
        tags = data.get("tags", [])
        if isinstance(tags, list):
            # Clean: lowercase, strip, remove empty, limit length
            return [
                t.strip().lower().lstrip("#")
                for t in tags
                if isinstance(t, str) and t.strip()
            ][:5]
    except (json.JSONDecodeError, IndexError, KeyError):
        pass
    return []
