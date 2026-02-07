"""Search and retrieval for RAG queries."""

import logging
import unicodedata
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.repositories.embeddings import EmbeddingRepository
from app.rag.embedder import embed_text

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Single search result from RAG retrieval."""

    content_type: str
    content_id: str
    text_chunk: str
    metadata: dict
    score: float
    chunk_index: int = 0


async def search(
    query: str,
    session: AsyncSession,
    top_k: int = None,
    content_types: Optional[list[str]] = None,
) -> list[SearchResult]:
    """Search the knowledge base for relevant documents.

    Args:
        query: User's question or search query
        session: Database session
        top_k: Number of results to return (default from settings)
        content_types: Filter by content types (None = all)

    Returns:
        List of SearchResult sorted by relevance.
    """
    top_k = top_k or settings.RAG_TOP_K
    repo = EmbeddingRepository(session)

    # Embed the query
    query_embedding = await embed_text(query)
    if query_embedding is None:
        logger.warning("Failed to embed query, falling back to keyword search")
        return await _keyword_search(query, repo, top_k, content_types)

    # Vector search
    raw_results = await repo.search_by_vector(
        embedding=query_embedding,
        limit=top_k * 2,  # Fetch more to filter
        content_types=content_types,
    )

    # Filter by minimum score
    results = [
        SearchResult(
            content_type=r["content_type"],
            content_id=r["content_id"],
            text_chunk=r["text_chunk"],
            metadata=r["metadata"],
            score=r["score"],
            chunk_index=r["chunk_index"],
        )
        for r in raw_results
        if r["score"] >= settings.RAG_MIN_SCORE
    ]

    # If too few vector results, supplement with keyword search
    if len(results) < top_k // 2:
        keyword_results = await _keyword_search(query, repo, top_k, content_types)
        # Merge, avoiding duplicates
        seen = {(r.content_type, r.content_id, r.chunk_index) for r in results}
        for kr in keyword_results:
            key = (kr.content_type, kr.content_id, kr.chunk_index)
            if key not in seen:
                results.append(kr)
                seen.add(key)

    # Sort by score descending and limit
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]


def _polish_stems(query: str, min_word_len: int = 4) -> list[str]:
    """Generuj 4-znakowe rdzenie z normalizacją polskich znaków.

    Rozwiązuje problem odmiany: notatki/notatką/notatkę → nota
    """
    normalized = unicodedata.normalize("NFD", query.lower())
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    normalized = normalized.replace("ł", "l")

    words = normalized.split()
    stems = []
    for w in words:
        if len(w) >= min_word_len and w.isalpha():
            stems.append(w[:4])
    return list(set(stems))


async def _keyword_search(
    query: str,
    repo: EmbeddingRepository,
    top_k: int,
    content_types: Optional[list[str]] = None,
) -> list[SearchResult]:
    """Fallback keyword search using pg_trgm + Polish stem matching."""
    raw_results = await repo.search_by_keyword(
        query=query,
        limit=top_k,
        content_types=content_types,
    )

    results = [
        SearchResult(
            content_type=r["content_type"],
            content_id=r["content_id"],
            text_chunk=r["text_chunk"],
            metadata=r["metadata"],
            score=r["score"],
            chunk_index=r["chunk_index"],
        )
        for r in raw_results
    ]

    # Uzupełnij stemami polskimi jeśli za mało wyników
    if len(results) < top_k:
        stems = _polish_stems(query)
        if stems:
            stem_results = await repo.search_by_stems(
                stems=stems,
                limit=top_k,
                content_types=content_types,
            )
            seen = {(r.content_type, r.content_id, r.chunk_index) for r in results}
            for r in stem_results:
                key = (r["content_type"], r["content_id"], r["chunk_index"])
                if key not in seen:
                    results.append(SearchResult(
                        content_type=r["content_type"],
                        content_id=r["content_id"],
                        text_chunk=r["text_chunk"],
                        metadata=r["metadata"],
                        score=r["score"],
                        chunk_index=r["chunk_index"],
                    ))
                    seen.add(key)

    return results
