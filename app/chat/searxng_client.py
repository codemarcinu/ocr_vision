"""SearXNG web search client."""

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Domains that typically return irrelevant results for knowledge queries
_BLOCKED_DOMAINS = {
    "apps.apple.com",
    "play.google.com",
    "facebook.com",
    "www.facebook.com",
    "instagram.com",
    "www.instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "www.tiktok.com",
}


@dataclass
class SearchResult:
    """Single web search result."""

    title: str
    url: str
    snippet: str
    engine: str


async def search(
    query: str,
    num_results: int = 5,
    language: str = "pl",
    categories: str = "general",
) -> tuple[list[SearchResult], Optional[str]]:
    """Search the web via SearXNG JSON API.

    Returns:
        Tuple of (results, error message or None).
    """
    try:
        async with httpx.AsyncClient(timeout=settings.SEARXNG_TIMEOUT) as client:
            response = await client.get(
                f"{settings.SEARXNG_URL}/search",
                params={
                    "q": query,
                    "format": "json",
                    "language": language,
                    "categories": categories,
                },
            )
            response.raise_for_status()
            data = response.json()

        results = []
        domain_counts: dict[str, int] = {}
        for item in data.get("results", []):
            if len(results) >= num_results:
                break

            title = item.get("title", "")
            url = item.get("url", "")
            snippet = item.get("content", "")

            # Skip results without meaningful content
            if not snippet or len(snippet) < 20:
                continue

            # Filter by domain
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                if domain in _BLOCKED_DOMAINS:
                    continue
                # Limit to 2 results per domain to increase diversity
                if domain_counts.get(domain, 0) >= 2:
                    continue
                domain_counts[domain] = domain_counts.get(domain, 0) + 1
            except Exception:
                pass

            results.append(SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                engine=item.get("engine", ""),
            ))

        return results, None

    except httpx.TimeoutException:
        logger.warning(f"SearXNG timeout for query: {query}")
        return [], f"Timeout po {settings.SEARXNG_TIMEOUT}s"
    except httpx.HTTPError as e:
        logger.error(f"SearXNG HTTP error: {e}")
        return [], f"Błąd HTTP: {e}"
    except Exception as e:
        logger.error(f"SearXNG error: {e}")
        return [], f"Błąd wyszukiwania: {e}"
