"""Fetch full page content for web search results."""

import asyncio
import logging
from typing import Optional

from app.chat.searxng_client import SearchResult
from app.config import settings
from app.web_scraper import scrape_url

logger = logging.getLogger(__name__)


def _truncate_content(text: str, max_chars: int) -> str:
    """Truncate content at sentence boundary near max_chars."""
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    for sep in (". ", ".\n", "! ", "? "):
        last_sep = truncated.rfind(sep)
        if last_sep > max_chars * 0.6:
            return truncated[: last_sep + 1]

    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.8:
        return truncated[:last_space] + "..."

    return truncated + "..."


async def _fetch_one(
    result: SearchResult,
    timeout: float,
    max_chars: int,
) -> None:
    """Fetch content for a single search result. Mutates result.content in place."""
    try:
        scraped, error = await asyncio.wait_for(
            scrape_url(result.url),
            timeout=timeout,
        )
        if scraped and scraped.content and len(scraped.content) >= 100:
            result.content = _truncate_content(scraped.content, max_chars)
            logger.debug(f"Fetched {len(result.content)} chars from {result.url}")
        else:
            logger.debug(f"No content from {result.url}: {error}")
    except asyncio.TimeoutError:
        logger.debug(f"Timeout fetching {result.url}")
    except Exception as e:
        logger.debug(f"Error fetching {result.url}: {e}")


async def fetch_content_for_results(
    results: list[SearchResult],
    top_n: Optional[int] = None,
    max_chars: Optional[int] = None,
    timeout: Optional[float] = None,
) -> list[SearchResult]:
    """Fetch full page content for the top N search results in parallel.

    Mutates results in-place by populating the ``content`` field.
    Falls back to snippet if fetch fails (content stays None).

    Args:
        results: Search results (should already be sorted by score).
        top_n: Number of results to fetch content for. Default from config.
        max_chars: Max characters per page. Default from config.
        timeout: Per-URL timeout in seconds. Default from config.

    Returns:
        The same results list (for chaining convenience).
    """
    if not settings.WEB_FETCH_ENABLED or not results:
        return results

    n = top_n or settings.WEB_FETCH_TOP_N
    chars = max_chars or settings.WEB_FETCH_MAX_CHARS
    t = float(timeout or settings.WEB_FETCH_TIMEOUT)

    to_fetch = results[:n]
    await asyncio.gather(*[_fetch_one(r, timeout=t, max_chars=chars) for r in to_fetch])

    fetched_count = sum(1 for r in to_fetch if r.content)
    logger.info(
        f"Content fetched: {fetched_count}/{len(to_fetch)} URLs "
        f"(max {chars} chars each)"
    )

    return results
