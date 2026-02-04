"""RSS/Atom feed fetcher using feedparser."""

import logging
from dataclasses import dataclass
from datetime import datetime
from time import mktime
from typing import List, Optional, Tuple

import feedparser
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class FeedEntry:
    """Parsed feed entry."""
    title: str
    url: str
    external_id: Optional[str]  # guid
    author: Optional[str]
    published_date: Optional[datetime]
    content: Optional[str]  # summary/description from feed


@dataclass
class FeedInfo:
    """Parsed feed metadata."""
    title: str
    feed_type: str  # 'rss' or 'atom'
    entries: List[FeedEntry]


async def fetch_feed(feed_url: str) -> Tuple[Optional[FeedInfo], Optional[str]]:
    """
    Fetch and parse RSS/Atom feed.

    Returns:
        Tuple of (FeedInfo or None, error message or None)
    """
    try:
        # Validate URL to prevent SSRF
        from app.url_validator import validate_url
        try:
            validate_url(feed_url)
        except ValueError as e:
            return None, str(e)

        # Fetch feed content
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                feed_url,
                headers={"User-Agent": "SmartPantryTracker/1.0"},
                follow_redirects=True,
            )
            response.raise_for_status()
            content = response.text

        # Parse with feedparser
        parsed = feedparser.parse(content)

        if parsed.bozo and not parsed.entries:
            return None, f"Feed parse error: {parsed.bozo_exception}"

        # Determine feed type
        feed_type = "atom" if parsed.version.startswith("atom") else "rss"

        # Extract entries
        entries = []
        for entry in parsed.entries[: settings.RSS_MAX_ARTICLES_PER_FEED]:
            # Extract published date
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime.fromtimestamp(mktime(entry.published_parsed))
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published = datetime.fromtimestamp(mktime(entry.updated_parsed))

            # Extract content/summary
            content = None
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            elif hasattr(entry, "summary"):
                content = entry.summary

            entries.append(
                FeedEntry(
                    title=entry.get("title", "Untitled"),
                    url=entry.get("link", ""),
                    external_id=entry.get("id") or entry.get("guid"),
                    author=entry.get("author"),
                    published_date=published,
                    content=content,
                )
            )

        feed_title = parsed.feed.get("title", feed_url)

        return (
            FeedInfo(
                title=feed_title,
                feed_type=feed_type,
                entries=entries,
            ),
            None,
        )

    except httpx.HTTPError as e:
        return None, f"HTTP error: {e}"
    except Exception as e:
        logger.exception(f"Error fetching feed {feed_url}")
        return None, f"Error: {e}"


async def detect_feed_type(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Detect if URL is RSS/Atom feed or regular webpage.

    Returns:
        Tuple of (feed_type or None, error or None)
        feed_type: 'rss', 'atom', or 'webpage'
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "SmartPantryTracker/1.0"},
                follow_redirects=True,
            )
            content_type = response.headers.get("content-type", "").lower()

            # Check content type
            if (
                "xml" in content_type
                or "rss" in content_type
                or "atom" in content_type
            ):
                parsed = feedparser.parse(response.text)
                if parsed.version.startswith("atom"):
                    return "atom", None
                elif parsed.version:
                    return "rss", None

            # Check for feed content even with HTML content type
            if "html" not in content_type:
                # Try to parse as feed
                parsed = feedparser.parse(response.text)
                if parsed.version:
                    if parsed.version.startswith("atom"):
                        return "atom", None
                    else:
                        return "rss", None

            return "webpage", None

    except Exception as e:
        return None, f"Error detecting feed type: {e}"


async def find_feed_url(page_url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Try to find RSS/Atom feed URL from a webpage.

    Looks for <link rel="alternate" type="application/rss+xml"> in HTML.

    Returns:
        Tuple of (feed URL or None, error or None)
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                page_url,
                headers={"User-Agent": "SmartPantryTracker/1.0"},
                follow_redirects=True,
            )

            content_type = response.headers.get("content-type", "").lower()
            if "html" not in content_type:
                return None, "Not an HTML page"

            # Parse HTML for feed links
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(response.text, "lxml")

            # Look for RSS/Atom link tags
            for link_type in [
                "application/rss+xml",
                "application/atom+xml",
                "application/xml",
            ]:
                link = soup.find("link", rel="alternate", type=link_type)
                if link and link.get("href"):
                    feed_url = link["href"]
                    # Handle relative URLs
                    if not feed_url.startswith("http"):
                        from urllib.parse import urljoin

                        feed_url = urljoin(page_url, feed_url)
                    return feed_url, None

            return None, "No feed link found in page"

    except Exception as e:
        return None, f"Error finding feed: {e}"
