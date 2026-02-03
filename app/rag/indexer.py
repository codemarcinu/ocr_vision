"""Content indexing pipeline for RAG."""

import logging
import re
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import (
    Article,
    ArticleSummary,
    Bookmark,
    DocumentEmbedding,
    Note,
    Receipt,
    ReceiptItem,
    Transcription,
    TranscriptionJob,
    TranscriptionNote,
)
from app.db.repositories.embeddings import EmbeddingRepository
from app.rag.embedder import embed_text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text preparation per content type
# ---------------------------------------------------------------------------

def prepare_article_text(article, summary=None) -> str:
    """Build text representation for an article."""
    parts = [f"Artykuł: {article.title}"]

    if hasattr(article, "feed") and article.feed:
        parts.append(f"Źródło: {article.feed.name}")
    if article.url:
        parts.append(f"URL: {article.url}")
    if article.author:
        parts.append(f"Autor: {article.author}")

    parts.append("")

    if summary and hasattr(summary, "summary_text"):
        parts.append(summary.summary_text)
    elif hasattr(article, "summary") and article.summary:
        parts.append(article.summary.summary_text)

    if article.content:
        content_snippet = article.content[:3000]
        parts.append(f"\n{content_snippet}")

    return "\n".join(parts)


def prepare_receipt_text(receipt, items=None) -> str:
    """Build text representation for a receipt."""
    store = "nieznany"
    if hasattr(receipt, "store") and receipt.store:
        store = receipt.store.name
    elif receipt.store_raw:
        store = receipt.store_raw

    date_str = ""
    if receipt.receipt_date:
        date_str = receipt.receipt_date.isoformat()

    total = ""
    if receipt.total_final:
        total = f"{receipt.total_final:.2f}"
    elif receipt.total_ocr:
        total = f"{receipt.total_ocr:.2f}"

    parts = [f"Paragon: {store} | Data: {date_str} | Suma: {total} zł"]
    parts.append("\nProdukty:")

    item_list = items or (receipt.items if hasattr(receipt, "items") else [])
    for item in item_list:
        name = item.name_normalized or item.name_raw
        price = f"{item.price_final:.2f}" if item.price_final else "?"
        cat = ""
        if hasattr(item, "category") and item.category:
            cat = f" ({item.category.name})"
        parts.append(f"- {name}: {price} zł{cat}")

    return "\n".join(parts)


def prepare_transcription_text(job, transcription=None, note=None) -> str:
    """Build text representation for a transcription."""
    parts = [f"Transkrypcja: {job.title or 'Bez tytułu'}"]

    if job.channel_name:
        parts.append(f"Kanał: {job.channel_name}")
    if job.source_url:
        parts.append(f"URL: {job.source_url}")

    parts.append("")

    note_obj = note or (job.note if hasattr(job, "note") else None)
    if note_obj:
        parts.append(note_obj.summary_text)

        if note_obj.key_topics:
            parts.append("\nGłówne tematy:")
            for topic in note_obj.key_topics:
                parts.append(f"- {topic}")

        if note_obj.key_points:
            points = note_obj.key_points if isinstance(note_obj.key_points, list) else []
            if points:
                parts.append("\nKluczowe punkty:")
                for point in points:
                    parts.append(f"- {point}")

        if note_obj.entities:
            parts.append(f"\nEncje: {', '.join(note_obj.entities)}")
    elif transcription:
        # Fallback: use raw transcription text
        parts.append(transcription.full_text[:5000])

    return "\n".join(parts)


def prepare_note_text(note) -> str:
    """Build text representation for a personal note."""
    parts = [f"Notatka: {note.title}"]

    if note.category:
        parts.append(f"Kategoria: {note.category}")
    if note.tags:
        parts.append(f"Tagi: {', '.join(note.tags)}")

    parts.append(f"\n{note.content}")
    return "\n".join(parts)


def prepare_bookmark_text(bookmark) -> str:
    """Build text representation for a bookmark."""
    parts = [f"Zakładka: {bookmark.title or bookmark.url}"]

    parts.append(f"URL: {bookmark.url}")
    if bookmark.tags:
        parts.append(f"Tagi: {', '.join(bookmark.tags)}")
    if bookmark.description:
        parts.append(f"\n{bookmark.description}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    chunk_size: int = None,
    overlap: int = None,
) -> list[str]:
    """Split text into overlapping chunks at sentence boundaries.

    For short texts (< chunk_size), returns [text] as single chunk.
    """
    chunk_size = chunk_size or settings.RAG_CHUNK_SIZE
    overlap = overlap or settings.RAG_CHUNK_OVERLAP

    if len(text) <= chunk_size:
        return [text]

    # Split on sentence boundaries
    sentence_pattern = r'(?<=[.!?])\s+(?=[A-ZŻŹĆĄŚĘŁÓŃ])'
    sentences = re.split(sentence_pattern, text)

    if len(sentences) <= 1:
        sentences = text.split('\n\n')
    if len(sentences) <= 1:
        sentences = text.split('\n')

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) > chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            # Keep overlap from the end of previous chunk
            overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
            current_chunk = overlap_text + " " + sentence
        else:
            current_chunk = current_chunk + " " + sentence if current_chunk else sentence

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


# ---------------------------------------------------------------------------
# Core indexing functions
# ---------------------------------------------------------------------------

async def index_document(
    content_type: str,
    content_id: str,
    text: str,
    metadata: dict,
    session: AsyncSession,
) -> int:
    """Index a document: chunk, embed, store.

    Returns number of chunks indexed.
    """
    if not text or not text.strip():
        return 0

    repo = EmbeddingRepository(session)

    # Delete existing embeddings for this document
    deleted = await repo.delete_by_content(content_type, content_id)
    if deleted:
        logger.debug(f"Deleted {deleted} old embeddings for {content_type}:{content_id}")

    # Chunk the text
    chunks = chunk_text(text)

    indexed = 0
    for i, chunk in enumerate(chunks):
        embedding = await embed_text(chunk)
        if embedding is None:
            logger.warning(f"Failed to embed chunk {i} for {content_type}:{content_id}")
            continue

        doc = DocumentEmbedding(
            content_type=content_type,
            content_id=content_id,
            chunk_index=i,
            text_chunk=chunk,
            embedding=embedding,
            metadata_=metadata,
        )
        session.add(doc)
        indexed += 1

    if indexed > 0:
        await session.flush()
        logger.info(f"Indexed {indexed}/{len(chunks)} chunks for {content_type}:{content_id}")

    return indexed


async def reindex_all(
    session: AsyncSession,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> dict:
    """Re-index all existing content.

    Args:
        session: Database session
        progress_callback: Optional callback(content_type, current, total)

    Returns:
        Stats dict with counts per content type.
    """
    stats = {
        "articles": 0,
        "transcriptions": 0,
        "receipts": 0,
        "notes": 0,
        "bookmarks": 0,
        "errors": 0,
    }

    # 1. Articles with summaries
    logger.info("RAG reindex: indexing articles...")
    result = await session.execute(
        select(Article)
        .options(selectinload(Article.summary), selectinload(Article.feed))
        .where(Article.is_summarized == True)
    )
    articles = list(result.scalars().all())
    for i, article in enumerate(articles):
        try:
            text = prepare_article_text(article)
            metadata = {
                "title": article.title,
                "url": article.url,
                "source": article.feed.name if article.feed else None,
            }
            count = await index_document("article", str(article.id), text, metadata, session)
            if count > 0:
                stats["articles"] += 1
            if progress_callback:
                progress_callback("articles", i + 1, len(articles))
        except Exception as e:
            logger.warning(f"Failed to index article {article.id}: {e}")
            stats["errors"] += 1

    # 2. Transcriptions with notes
    logger.info("RAG reindex: indexing transcriptions...")
    result = await session.execute(
        select(TranscriptionJob)
        .options(
            selectinload(TranscriptionJob.transcription),
            selectinload(TranscriptionJob.note),
        )
        .where(TranscriptionJob.status == "completed")
    )
    jobs = list(result.scalars().all())
    for i, job in enumerate(jobs):
        try:
            text = prepare_transcription_text(job)
            metadata = {
                "title": job.title,
                "url": job.source_url,
                "channel": job.channel_name,
                "source_type": job.source_type,
            }
            count = await index_document("transcription", str(job.id), text, metadata, session)
            if count > 0:
                stats["transcriptions"] += 1
            if progress_callback:
                progress_callback("transcriptions", i + 1, len(jobs))
        except Exception as e:
            logger.warning(f"Failed to index transcription {job.id}: {e}")
            stats["errors"] += 1

    # 3. Receipts with items
    logger.info("RAG reindex: indexing receipts...")
    result = await session.execute(
        select(Receipt)
        .options(
            selectinload(Receipt.store),
            selectinload(Receipt.items).selectinload(ReceiptItem.category),
        )
    )
    receipts = list(result.scalars().all())
    for i, receipt in enumerate(receipts):
        try:
            text = prepare_receipt_text(receipt)
            store_name = receipt.store.name if receipt.store else receipt.store_raw
            metadata = {
                "store": store_name,
                "date": receipt.receipt_date.isoformat() if receipt.receipt_date else None,
                "total": float(receipt.total_final or receipt.total_ocr or 0),
            }
            count = await index_document("receipt", str(receipt.id), text, metadata, session)
            if count > 0:
                stats["receipts"] += 1
            if progress_callback:
                progress_callback("receipts", i + 1, len(receipts))
        except Exception as e:
            logger.warning(f"Failed to index receipt {receipt.id}: {e}")
            stats["errors"] += 1

    # 4. Notes
    logger.info("RAG reindex: indexing notes...")
    result = await session.execute(
        select(Note).where(Note.is_archived == False)
    )
    notes = list(result.scalars().all())
    for i, note in enumerate(notes):
        try:
            text = prepare_note_text(note)
            metadata = {
                "title": note.title,
                "category": note.category,
                "tags": note.tags,
            }
            count = await index_document("note", str(note.id), text, metadata, session)
            if count > 0:
                stats["notes"] += 1
            if progress_callback:
                progress_callback("notes", i + 1, len(notes))
        except Exception as e:
            logger.warning(f"Failed to index note {note.id}: {e}")
            stats["errors"] += 1

    # 5. Bookmarks
    logger.info("RAG reindex: indexing bookmarks...")
    result = await session.execute(select(Bookmark))
    bookmarks = list(result.scalars().all())
    for i, bookmark in enumerate(bookmarks):
        try:
            text = prepare_bookmark_text(bookmark)
            metadata = {
                "title": bookmark.title,
                "url": bookmark.url,
                "tags": bookmark.tags,
            }
            count = await index_document("bookmark", str(bookmark.id), text, metadata, session)
            if count > 0:
                stats["bookmarks"] += 1
            if progress_callback:
                progress_callback("bookmarks", i + 1, len(bookmarks))
        except Exception as e:
            logger.warning(f"Failed to index bookmark {bookmark.id}: {e}")
            stats["errors"] += 1

    await session.commit()
    logger.info(f"RAG reindex complete: {stats}")
    return stats
