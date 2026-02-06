"""Shared Ollama HTTP client with connection pooling.

This module provides a singleton httpx.AsyncClient for all Ollama API calls,
eliminating the overhead of creating new connections for each request.

Performance improvement: ~50-100ms per request (300-600ms total per receipt).
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Singleton client instance
_client: Optional[httpx.AsyncClient] = None


async def get_client() -> httpx.AsyncClient:
    """Get or create the shared Ollama HTTP client.

    Uses connection pooling with:
    - max_connections=10: Allow concurrent requests
    - max_keepalive_connections=5: Keep connections warm
    - keepalive_expiry=30s: Close idle connections after 30s
    """
    global _client

    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.OLLAMA_BASE_URL,
            timeout=httpx.Timeout(
                connect=10.0,
                read=300.0,  # Long reads for model inference
                write=30.0,
                pool=10.0,
            ),
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=30.0,
            ),
        )
        logger.debug("Created new Ollama HTTP client with connection pooling")

    return _client


async def close_client() -> None:
    """Close the shared client (call on application shutdown)."""
    global _client

    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
        logger.debug("Closed Ollama HTTP client")


async def post_generate(
    model: str,
    prompt: str,
    options: Optional[dict] = None,
    timeout: float = 180.0,
    keep_alive: Optional[str] = None,
    format: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    """Call Ollama /api/generate endpoint.

    Integrates with ModelCoordinator to manage VRAM and prevent thrashing.

    Returns:
        Tuple of (response text, error message or None)
    """
    # Import here to avoid circular dependency
    from app.model_coordinator import get_coordinator

    coordinator = get_coordinator()

    # Acquire model slot (may wait if VRAM insufficient)
    if not await coordinator.acquire_model(model, timeout=timeout):
        return "", "Model acquisition timeout - VRAM may be exhausted"

    try:
        client = await get_client()

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }

        if options:
            payload["options"] = options

        if keep_alive:
            payload["keep_alive"] = keep_alive

        if format:
            payload["format"] = format

        try:
            response = await client.post(
                "/api/generate",
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            result = response.json()

            # Mark model as loaded on successful response
            coordinator.mark_model_loaded(model)

            return result.get("response", ""), None
        except httpx.TimeoutException:
            return "", f"Timeout after {timeout}s"
        except httpx.HTTPError as e:
            return "", f"HTTP error: {e}"
    finally:
        await coordinator.release_model(model)


async def post_chat(
    model: str,
    messages: list[dict],
    options: Optional[dict] = None,
    timeout: float = 120.0,
    keep_alive: Optional[str] = None,
    format: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    """Call Ollama /api/chat endpoint.

    Integrates with ModelCoordinator to manage VRAM and prevent thrashing.

    Returns:
        Tuple of (response content, error message or None)
    """
    # Import here to avoid circular dependency
    from app.model_coordinator import get_coordinator

    coordinator = get_coordinator()

    # Acquire model slot (may wait if VRAM insufficient)
    if not await coordinator.acquire_model(model, timeout=timeout):
        return "", "Model acquisition timeout - VRAM may be exhausted"

    try:
        client = await get_client()

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }

        if options:
            payload["options"] = options

        if keep_alive:
            payload["keep_alive"] = keep_alive

        if format:
            payload["format"] = format

        try:
            response = await client.post(
                "/api/chat",
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            result = response.json()

            # Mark model as loaded on successful response
            coordinator.mark_model_loaded(model)

            return result.get("message", {}).get("content", ""), None
        except httpx.TimeoutException:
            return "", f"Timeout after {timeout}s"
        except httpx.HTTPError as e:
            return "", f"HTTP error: {e}"
    finally:
        await coordinator.release_model(model)


async def post_chat_stream(
    model: str,
    messages: list[dict],
    options: Optional[dict] = None,
    timeout: float = 120.0,
    keep_alive: Optional[str] = None,
) -> AsyncIterator[str]:
    """Stream tokens from Ollama /api/chat endpoint.

    Yields individual token strings as they arrive.
    Integrates with ModelCoordinator for VRAM management.
    """
    from app.model_coordinator import get_coordinator

    coordinator = get_coordinator()

    if not await coordinator.acquire_model(model, timeout=timeout):
        yield ""
        return

    try:
        client = await get_client()

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if options:
            payload["options"] = options
        if keep_alive:
            payload["keep_alive"] = keep_alive

        try:
            async with client.stream(
                "POST",
                "/api/chat",
                json=payload,
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            coordinator.mark_model_loaded(model)
                            break
                    except json.JSONDecodeError:
                        continue
        except httpx.TimeoutException:
            logger.error(f"Stream timeout after {timeout}s")
        except httpx.HTTPError as e:
            logger.error(f"Stream HTTP error: {e}")
    finally:
        await coordinator.release_model(model)


async def unload_model(model: str) -> None:
    """Unload a model from memory by setting keep_alive to 0.

    Note: This is the low-level unload function. For coordinated unloading
    that respects VRAM management, use coordinator.force_unload() instead.
    """
    client = await get_client()

    try:
        await client.post(
            "/api/generate",
            json={
                "model": model,
                "prompt": "",
                "keep_alive": 0,
            },
            timeout=10.0,
        )
        logger.info(f"Unloaded model: {model}")
    except Exception as e:
        logger.warning(f"Failed to unload model {model}: {e}")
