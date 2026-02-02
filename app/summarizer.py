"""Article summarizer using Ollama LLM."""

import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from app.config import settings
from app import ollama_client

logger = logging.getLogger(__name__)

SUMMARY_PROMPT_PL = """Przeanalizuj poniższy artykuł i wyodrębnij kluczowe informacje w formie bullet points (po polsku):

- Główny temat/teza
- Kluczowe fakty i dane
- Wnioski lub rekomendacje

Odpowiedz TYLKO bullet pointami, bez wprowadzenia ani podsumowania.

Artykuł:
{content}

Bullet points:"""

SUMMARY_PROMPT_EN = """Analyze the following article and extract key information as bullet points:

- Main topic/thesis
- Key facts and data
- Conclusions or recommendations

Respond ONLY with bullet points, no introduction or summary.

Article:
{content}

Bullet points:"""


@dataclass
class SummaryResult:
    """Result of summarization."""
    summary_text: str
    model_used: str
    processing_time_sec: float


async def summarize_content(
    content: str,
    language: str = "pl",
    max_content_length: int = 8000,
) -> Tuple[Optional[SummaryResult], Optional[str]]:
    """
    Generate bullet-point summary of content using LLM.

    Args:
        content: Article text to summarize
        language: 'pl' or 'en' for prompt language
        max_content_length: Truncate content if longer

    Returns:
        Tuple of (SummaryResult or None, error message or None)
    """
    if not content:
        return None, "No content to summarize"

    # Truncate if too long
    if len(content) > max_content_length:
        content = content[:max_content_length] + "..."
        logger.info(f"Truncated content to {max_content_length} chars")

    # Select prompt based on language
    prompt_template = SUMMARY_PROMPT_PL if language == "pl" else SUMMARY_PROMPT_EN
    prompt = prompt_template.format(content=content)

    # Determine model to use
    model = settings.SUMMARIZER_MODEL or settings.CLASSIFIER_MODEL

    start_time = time.time()

    try:
        response, error = await ollama_client.post_generate(
            model=model,
            prompt=prompt,
            options={
                "temperature": 0.3,  # Slightly higher than categorization for variety
                "num_predict": 1024,  # Limit output length
            },
            timeout=120.0,
            keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
        )

        elapsed = time.time() - start_time

        if error:
            return None, f"LLM error: {error}"

        if not response or not response.strip():
            return None, "Empty response from LLM"

        # Clean up response
        summary = response.strip()

        # Ensure it starts with bullet points
        if not summary.startswith("-") and not summary.startswith("*") and not summary.startswith("•"):
            # Try to find first bullet point
            for char in ["-", "*", "•"]:
                if char in summary:
                    idx = summary.index(char)
                    summary = summary[idx:]
                    break

        return (
            SummaryResult(
                summary_text=summary,
                model_used=model,
                processing_time_sec=round(elapsed, 2),
            ),
            None,
        )

    except Exception as e:
        logger.exception("Summarization error")
        return None, f"Error: {e}"


async def summarize_url(url: str) -> Tuple[Optional[SummaryResult], Optional[str]]:
    """
    Convenience function: scrape URL and summarize.

    Returns:
        Tuple of (SummaryResult or None, error message or None)
    """
    from app.web_scraper import scrape_url

    scraped, error = await scrape_url(url)
    if error or not scraped:
        return None, error or "Failed to scrape URL"

    return await summarize_content(scraped.content)


def detect_language(text: str) -> str:
    """
    Simple heuristic to detect if text is Polish or English.

    Returns 'pl' or 'en'.
    """
    # Polish-specific characters and common words
    polish_indicators = [
        "ą", "ć", "ę", "ł", "ń", "ó", "ś", "ź", "ż",
        " i ", " w ", " z ", " na ", " do ", " nie ",
        " się ", " jest ", " że ", " to ",
    ]

    text_lower = text.lower()
    polish_score = sum(1 for indicator in polish_indicators if indicator in text_lower)

    # If more than 3 Polish indicators found, assume Polish
    return "pl" if polish_score >= 3 else "en"
