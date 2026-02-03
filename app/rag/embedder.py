"""Embedding generation via Ollama /api/embed endpoint."""

import logging
from typing import Optional

import httpx

from app import ollama_client
from app.config import settings

logger = logging.getLogger(__name__)


async def embed_text(text: str) -> Optional[list[float]]:
    """Generate embedding for a single text.

    Returns:
        List of floats (embedding vector) or None on error.
    """
    if not text or not text.strip():
        return None

    # Truncate to avoid excessive token usage (nomic-embed-text max ~8192 tokens)
    text = text[:8000]

    client = await ollama_client.get_client()

    try:
        response = await client.post(
            "/api/embed",
            json={
                "model": settings.EMBEDDING_MODEL,
                "input": text,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()

        embeddings = data.get("embeddings")
        if not embeddings or len(embeddings) == 0:
            logger.warning("Ollama /api/embed returned empty embeddings")
            return None

        return embeddings[0]

    except httpx.TimeoutException:
        logger.warning(f"Embedding timeout after 60s for text ({len(text)} chars)")
        return None
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.error(
                f"Embedding model '{settings.EMBEDDING_MODEL}' not found. "
                f"Run: ollama pull {settings.EMBEDDING_MODEL}"
            )
        else:
            logger.error(f"Embedding HTTP error: {e}")
        return None
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return None


async def embed_texts(texts: list[str]) -> list[Optional[list[float]]]:
    """Generate embeddings for multiple texts (sequential to avoid OOM).

    Returns:
        List of embedding vectors (None for failed ones).
    """
    results = []
    for text in texts:
        embedding = await embed_text(text)
        results.append(embedding)
    return results
