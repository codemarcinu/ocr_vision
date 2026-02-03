"""Unified search API across all content types."""

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func, text
from sqlalchemy.orm import selectinload

from app.db.models import (
    Article, ArticleSummary, Bookmark, Note,
    ReceiptItem, Receipt, Store,
    TranscriptionJob, TranscriptionNote,
)
from app.dependencies import DbSession

router = APIRouter(tags=["search"])


@router.get("/search")
async def unified_search(
    q: str,
    session: DbSession,
    types: Optional[str] = None,
    limit: int = 5,
):
    """Search across all content types.

    Args:
        q: Search query (min 2 chars)
        types: Comma-separated content types to search (default: all)
               Options: receipt, article, note, bookmark, transcription
        limit: Max results per type (default 5)
    """
    if not q or len(q) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters")

    limit = min(limit, 20)
    allowed_types = {"receipt", "article", "note", "bookmark", "transcription"}
    search_types = allowed_types
    if types:
        search_types = {t.strip() for t in types.split(",") if t.strip() in allowed_types}

    pattern = f"%{q}%"
    results = {}

    # Run searches concurrently
    tasks = []
    if "receipt" in search_types:
        tasks.append(_search_receipts(session, pattern, limit))
    if "article" in search_types:
        tasks.append(_search_articles(session, pattern, limit))
    if "note" in search_types:
        tasks.append(_search_notes(session, pattern, limit))
    if "bookmark" in search_types:
        tasks.append(_search_bookmarks(session, pattern, limit))
    if "transcription" in search_types:
        tasks.append(_search_transcriptions(session, pattern, limit))

    # Gather results (sequential since they share a session)
    for task in tasks:
        type_name, items = await task
        if items:
            results[type_name] = items

    total_count = sum(len(v) for v in results.values())

    return {
        "query": q,
        "total": total_count,
        "results": results,
    }


async def _search_receipts(session, pattern: str, limit: int):
    """Search receipt items by product name."""
    stmt = (
        select(ReceiptItem)
        .options(
            selectinload(ReceiptItem.receipt).selectinload(Receipt.store),
            selectinload(ReceiptItem.category),
        )
        .where(
            ReceiptItem.name_raw.ilike(pattern)
            | ReceiptItem.name_normalized.ilike(pattern)
        )
        .order_by(ReceiptItem.id.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    items = result.scalars().all()

    return ("receipt", [
        {
            "id": item.id,
            "name": item.name_normalized or item.name_raw,
            "name_raw": item.name_raw,
            "price": float(item.price_final) if item.price_final else 0,
            "category": item.category.name if item.category else None,
            "store": item.receipt.store.name if item.receipt and item.receipt.store else None,
            "date": item.receipt.receipt_date.isoformat() if item.receipt and item.receipt.receipt_date else None,
            "receipt_id": str(item.receipt_id),
        }
        for item in items
    ])


async def _search_articles(session, pattern: str, limit: int):
    """Search articles by title."""
    stmt = (
        select(Article)
        .where(Article.title.ilike(pattern))
        .order_by(Article.id.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    items = result.scalars().all()

    return ("article", [
        {
            "id": item.id,
            "title": item.title,
            "url": item.url,
            "is_summarized": item.is_summarized,
            "published_date": item.published_date.isoformat() if item.published_date else None,
        }
        for item in items
    ])


async def _search_notes(session, pattern: str, limit: int):
    """Search notes by title or content."""
    stmt = (
        select(Note)
        .where(Note.title.ilike(pattern) | Note.content.ilike(pattern))
        .order_by(Note.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    items = result.scalars().all()

    return ("note", [
        {
            "id": str(item.id),
            "title": item.title,
            "category": item.category,
            "tags": item.tags,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "snippet": (item.content[:150] + "...") if item.content and len(item.content) > 150 else item.content,
        }
        for item in items
    ])


async def _search_bookmarks(session, pattern: str, limit: int):
    """Search bookmarks by title or URL."""
    stmt = (
        select(Bookmark)
        .where(Bookmark.title.ilike(pattern) | Bookmark.url.ilike(pattern))
        .order_by(Bookmark.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    items = result.scalars().all()

    return ("bookmark", [
        {
            "id": str(item.id),
            "title": item.title,
            "url": item.url,
            "status": item.status,
            "tags": item.tags,
        }
        for item in items
    ])


async def _search_transcriptions(session, pattern: str, limit: int):
    """Search transcriptions by title."""
    stmt = (
        select(TranscriptionJob)
        .where(TranscriptionJob.title.ilike(pattern))
        .order_by(TranscriptionJob.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    items = result.scalars().all()

    return ("transcription", [
        {
            "id": str(item.id),
            "title": item.title,
            "source_type": item.source_type,
            "source_url": item.source_url,
            "status": item.status,
            "duration": item.duration_seconds,
        }
        for item in items
    ])
