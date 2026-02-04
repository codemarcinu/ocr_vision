"""Web content scraper using trafilatura."""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import httpx
import trafilatura
from trafilatura.settings import use_config

logger = logging.getLogger(__name__)

# Configure trafilatura for better extraction
TRAFILATURA_CONFIG = use_config()
TRAFILATURA_CONFIG.set("DEFAULT", "EXTRACTION_TIMEOUT", "30")


@dataclass
class ScrapedContent:
    """Scraped web page content."""
    title: str
    content: str
    author: Optional[str]
    date: Optional[str]
    url: str


async def scrape_url(url: str) -> Tuple[Optional[ScrapedContent], Optional[str]]:
    """
    Scrape article content from URL.

    Uses trafilatura for content extraction which:
    - Removes boilerplate (navigation, ads, footers)
    - Extracts main article text
    - Handles various website layouts

    Returns:
        Tuple of (ScrapedContent or None, error message or None)
    """
    try:
        # Validate URL to prevent SSRF
        from app.url_validator import validate_url
        try:
            validate_url(url)
        except ValueError as e:
            return None, str(e)

        # Fetch page
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; SmartPantryTracker/1.0)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                follow_redirects=True,
            )
            response.raise_for_status()
            html = response.text

        # Extract content with trafilatura
        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
            config=TRAFILATURA_CONFIG,
        )

        if not extracted:
            return None, "Could not extract content from page"

        # Get metadata
        metadata = trafilatura.extract_metadata(html)

        title = metadata.title if metadata else "Untitled"
        author = metadata.author if metadata else None
        date = metadata.date if metadata else None

        return (
            ScrapedContent(
                title=title,
                content=extracted,
                author=author,
                date=date,
                url=url,
            ),
            None,
        )

    except httpx.HTTPError as e:
        return None, f"HTTP error: {e}"
    except Exception as e:
        logger.exception(f"Error scraping {url}")
        return None, f"Error: {e}"


async def scrape_with_fallback(
    url: str, feed_content: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Try to get article content, with fallback to feed content.

    1. Try scraping the full URL
    2. Fall back to feed summary if scraping fails
    3. Return error if both fail

    Returns:
        Tuple of (content text, error or None)
    """
    # Try full scrape first
    scraped, error = await scrape_url(url)
    if scraped and scraped.content:
        # Check if content is substantial enough
        if len(scraped.content) >= 100:
            return scraped.content, None
        logger.warning(
            f"Scraped content too short ({len(scraped.content)} chars), trying fallback"
        )

    # Fall back to feed content
    if feed_content and len(feed_content) >= 50:
        # Clean HTML from feed content
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(feed_content, "lxml")
        clean_text = soup.get_text(separator=" ", strip=True)
        if clean_text:
            return clean_text, None

    return None, error or "Could not extract content"


def extract_title_from_html(html: str) -> str:
    """Extract title from HTML if trafilatura metadata fails."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    # Try og:title first
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"]

    # Try title tag
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        return title_tag.string.strip()

    # Try h1
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    return "Untitled"
