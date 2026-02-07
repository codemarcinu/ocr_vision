"""REST API for RAG knowledge base queries."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.db.connection import get_session
from app.db.repositories.embeddings import EmbeddingRepository
from app.rag import answerer, indexer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ask", tags=["RAG"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    top_k: int = 5
    content_types: Optional[list[str]] = None


class SourceResponse(BaseModel):
    content_type: str
    content_id: str
    title: str
    score: float


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]
    model_used: str
    processing_time_sec: float
    chunks_found: int
    judge_verdict: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=AskResponse)
async def ask_question(request: AskRequest):
    """Ask a question to the knowledge base."""
    if not settings.RAG_ENABLED:
        raise HTTPException(status_code=400, detail="RAG is disabled")

    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question is empty")

    async for session in get_session():
        result = await answerer.ask(
            question=request.question,
            session=session,
            top_k=request.top_k,
            content_types=request.content_types,
        )

        return AskResponse(
            answer=result.answer,
            sources=[
                SourceResponse(
                    content_type=s.content_type,
                    content_id=s.content_id,
                    title=s.title,
                    score=s.score,
                )
                for s in result.sources
            ],
            model_used=result.model_used,
            processing_time_sec=result.processing_time_sec,
            chunks_found=result.chunks_found,
            judge_verdict=result.judge_verdict,
        )


@router.get("/stats")
async def get_stats():
    """Get embedding index statistics."""
    if not settings.RAG_ENABLED:
        raise HTTPException(status_code=400, detail="RAG is disabled")

    async for session in get_session():
        repo = EmbeddingRepository(session)
        stats = await repo.get_stats()
        return {
            "enabled": settings.RAG_ENABLED,
            "embedding_model": settings.EMBEDDING_MODEL,
            "dimensions": settings.EMBEDDING_DIMENSIONS,
            "ask_model": settings.ASK_MODEL or settings.CLASSIFIER_MODEL,
            **stats,
        }


@router.post("/reindex")
async def trigger_reindex():
    """Trigger full re-indexing of all content (runs in background)."""
    if not settings.RAG_ENABLED:
        raise HTTPException(status_code=400, detail="RAG is disabled")

    async def _reindex_background():
        try:
            async for session in get_session():
                stats = await indexer.reindex_all(session)
                logger.info(f"Background reindex completed: {stats}")
        except Exception as e:
            logger.error(f"Background reindex failed: {e}")

    asyncio.create_task(_reindex_background())

    return {
        "status": "started",
        "message": "Re-indexing started in background. Check logs for progress.",
    }
