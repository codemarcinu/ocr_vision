"""Fire-and-forget RAG indexing hooks for content creation flows."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)


async def index_article_hook(article, session: AsyncSession) -> None:
    """Index an article after it's saved to the database."""
    if not settings.RAG_ENABLED or not settings.RAG_AUTO_INDEX:
        return

    try:
        from app.rag.indexer import index_document, prepare_article_text

        text = prepare_article_text(article)
        metadata = {
            "title": article.title,
            "url": article.url,
            "source": article.feed.name if hasattr(article, "feed") and article.feed else None,
        }
        await index_document("article", str(article.id), text, metadata, session)
    except Exception as e:
        logger.warning(f"RAG indexing failed for article {article.id}: {e}")


async def index_transcription_hook(job, session: AsyncSession) -> None:
    """Index a transcription after note is generated."""
    if not settings.RAG_ENABLED or not settings.RAG_AUTO_INDEX:
        return

    try:
        from app.rag.indexer import index_document, prepare_transcription_text

        text = prepare_transcription_text(job)
        metadata = {
            "title": job.title,
            "url": job.source_url,
            "channel": job.channel_name,
            "source_type": job.source_type,
        }
        await index_document("transcription", str(job.id), text, metadata, session)
    except Exception as e:
        logger.warning(f"RAG indexing failed for transcription {job.id}: {e}")


async def index_note_hook(note, session: AsyncSession) -> None:
    """Index a personal note after creation."""
    if not settings.RAG_ENABLED or not settings.RAG_AUTO_INDEX:
        return

    try:
        from app.rag.indexer import index_document, prepare_note_text

        text = prepare_note_text(note)
        metadata = {
            "title": note.title,
            "category": note.category,
            "tags": note.tags,
        }
        await index_document("note", str(note.id), text, metadata, session)
    except Exception as e:
        logger.warning(f"RAG indexing failed for note {note.id}: {e}")


async def index_bookmark_hook(bookmark, session: AsyncSession) -> None:
    """Index a bookmark after creation."""
    if not settings.RAG_ENABLED or not settings.RAG_AUTO_INDEX:
        return

    try:
        from app.rag.indexer import index_document, prepare_bookmark_text

        text = prepare_bookmark_text(bookmark)
        metadata = {
            "title": bookmark.title,
            "url": bookmark.url,
            "tags": bookmark.tags,
        }
        await index_document("bookmark", str(bookmark.id), text, metadata, session)
    except Exception as e:
        logger.warning(f"RAG indexing failed for bookmark {bookmark.id}: {e}")


async def index_receipt_hook(receipt, items, session: AsyncSession) -> None:
    """Index a receipt after it's saved to the database."""
    if not settings.RAG_ENABLED or not settings.RAG_AUTO_INDEX:
        return

    try:
        from app.rag.indexer import index_document, prepare_receipt_text

        text = prepare_receipt_text(receipt, items)
        store_name = receipt.store.name if hasattr(receipt, "store") and receipt.store else getattr(receipt, "store_raw", None)
        metadata = {
            "store": store_name,
            "date": receipt.receipt_date.isoformat() if receipt.receipt_date else None,
            "total": float(receipt.total_final or receipt.total_ocr or 0),
        }
        await index_document("receipt", str(receipt.id), text, metadata, session)
    except Exception as e:
        logger.warning(f"RAG indexing failed for receipt {receipt.id}: {e}")
