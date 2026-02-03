"""OpenAI API client for OCR pipeline.

Singleton AsyncOpenAI client used ONLY for receipt OCR processing
(when OCR_BACKEND=openai). Other modules (chat, RAG, summarizer)
continue using Ollama via ollama_client.py.
"""

import logging
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None


def get_client() -> AsyncOpenAI:
    """Get or create the shared OpenAI client.

    Uses built-in retry logic (exponential backoff for 429/500/503).
    """
    global _client

    if _client is None:
        if not settings.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY is required when OCR_BACKEND=openai. "
                "Set it in environment variables."
            )
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=120.0,
            max_retries=2,
        )
        logger.debug("Created OpenAI client")

    return _client


async def close_client() -> None:
    """Close the shared client (call on application shutdown)."""
    global _client

    if _client is not None:
        await _client.close()
        _client = None
        logger.debug("Closed OpenAI client")
