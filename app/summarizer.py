"""Article summarizer using Ollama LLM with structured JSON output."""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.config import settings
from app import ollama_client

logger = logging.getLogger(__name__)

# Polish prompt with JSON output for Bielik model
SUMMARY_PROMPT_PL = """Przeanalizuj poniższy artykuł i zwróć wynik w formacie JSON.

INSTRUKCJE:
1. Wyodrębnij kluczowe informacje jako bullet points (po polsku)
2. Wybierz max 5 tagów tematycznych (pojedyncze słowa, małe litery)
3. Przypisz kategorię z listy: {categories}
4. Wylistuj wspomniane osoby, firmy, produkty, technologie

WYMAGANY FORMAT JSON:
{{
  "summary": "- punkt pierwszy\\n- punkt drugi\\n- punkt trzeci",
  "tags": ["tag1", "tag2", "tag3"],
  "category": "Technologia",
  "entities": ["OpenAI", "GPT-5", "Sam Altman"]
}}

ARTYKUŁ:
{content}

JSON:"""

# English prompt
SUMMARY_PROMPT_EN = """Analyze the following article and return the result in JSON format.

INSTRUCTIONS:
1. Extract key information as bullet points
2. Select max 5 topic tags (single words, lowercase)
3. Assign category from: {categories}
4. List mentioned people, companies, products, technologies

REQUIRED JSON FORMAT:
{{
  "summary": "- first point\\n- second point\\n- third point",
  "tags": ["tag1", "tag2", "tag3"],
  "category": "Technology",
  "entities": ["OpenAI", "GPT-5", "Sam Altman"]
}}

ARTICLE:
{content}

JSON:"""

# Category mapping for English
CATEGORIES_EN = [
    "Technology",
    "Business",
    "Science",
    "Politics",
    "Culture",
    "Sport",
    "Health",
    "Other",
]


@dataclass
class SummaryResult:
    """Result of summarization with metadata."""

    summary_text: str
    model_used: str
    processing_time_sec: float
    tags: List[str] = field(default_factory=list)
    category: Optional[str] = None
    entities: List[str] = field(default_factory=list)
    language: str = "pl"


def _parse_json_response(response: str) -> Optional[dict]:
    """
    Parse JSON from LLM response.

    Handles cases where LLM wraps JSON in markdown code blocks.
    """
    text = response.strip()

    # Try to extract JSON from markdown code block
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)

    # Try to find JSON object in text
    json_start = text.find("{")
    json_end = text.rfind("}") + 1
    if json_start != -1 and json_end > json_start:
        text = text[json_start:json_end]

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON: {e}")
        logger.debug(f"Raw response: {response[:500]}")
        return None


def _extract_summary_fallback(response: str) -> str:
    """
    Extract summary from non-JSON response as fallback.

    Looks for bullet points in the response.
    """
    lines = response.strip().split("\n")
    bullet_lines = []

    for line in lines:
        line = line.strip()
        if line.startswith(("-", "*", "•", "·")):
            bullet_lines.append(line)

    if bullet_lines:
        return "\n".join(bullet_lines)

    # Return first 500 chars as last resort
    return response[:500] if response else ""


async def summarize_content(
    content: str,
    language: str = "auto",
    max_content_length: int = 8000,
) -> Tuple[Optional[SummaryResult], Optional[str]]:
    """
    Generate structured summary of content using LLM.

    Args:
        content: Article text to summarize
        language: 'pl', 'en', or 'auto' for auto-detection
        max_content_length: Truncate content if longer

    Returns:
        Tuple of (SummaryResult or None, error message or None)
    """
    if not content:
        return None, "No content to summarize"

    # Auto-detect language
    if language == "auto":
        language = detect_language(content)

    # Truncate if too long
    original_length = len(content)
    if original_length > max_content_length:
        content = content[:max_content_length] + "..."
        logger.info(f"Truncated content from {original_length} to {max_content_length} chars")

    # Select prompt and model based on language
    if language == "pl":
        categories = ", ".join(settings.ARTICLE_CATEGORIES)
        prompt = SUMMARY_PROMPT_PL.format(content=content, categories=categories)
        model = settings.SUMMARIZER_MODEL_PL
    else:
        categories = ", ".join(CATEGORIES_EN)
        prompt = SUMMARY_PROMPT_EN.format(content=content, categories=categories)
        model = settings.SUMMARIZER_MODEL or settings.CLASSIFIER_MODEL

    logger.info(f"Summarizing with model: {model}, language: {language}")
    start_time = time.time()

    try:
        response, error = await ollama_client.post_generate(
            model=model,
            prompt=prompt,
            options={
                "temperature": 0.3,
                "num_predict": 2048,
            },
            timeout=180.0,  # Longer timeout for larger model
            keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
        )

        elapsed = time.time() - start_time
        logger.info(f"Summarization completed in {elapsed:.1f}s")

        if error:
            return None, f"LLM error: {error}"

        if not response or not response.strip():
            return None, "Empty response from LLM"

        # Parse JSON response
        parsed = _parse_json_response(response)

        if parsed:
            summary_text = parsed.get("summary", "")
            tags = parsed.get("tags", [])
            category = parsed.get("category")
            entities = parsed.get("entities", [])

            # Validate and clean tags
            tags = [str(t).lower().strip() for t in tags if t][:5]

            # Validate category
            valid_categories = (
                settings.ARTICLE_CATEGORIES if language == "pl" else CATEGORIES_EN
            )
            if category not in valid_categories:
                category = "Inne" if language == "pl" else "Other"

            # Clean entities
            entities = [str(e).strip() for e in entities if e][:10]

        else:
            # Fallback: extract bullet points from raw response
            logger.warning("JSON parsing failed, using fallback extraction")
            summary_text = _extract_summary_fallback(response)
            tags = []
            category = "Inne" if language == "pl" else "Other"
            entities = []

        if not summary_text:
            return None, "Could not extract summary from response"

        return (
            SummaryResult(
                summary_text=summary_text,
                model_used=model,
                processing_time_sec=round(elapsed, 2),
                tags=tags,
                category=category,
                entities=entities,
                language=language,
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
    Detect if text is Polish or English.

    Returns 'pl' or 'en'.
    """
    # Polish-specific characters and common words
    polish_indicators = [
        "ą", "ć", "ę", "ł", "ń", "ó", "ś", "ź", "ż",
        " i ", " w ", " z ", " na ", " do ", " nie ",
        " się ", " jest ", " że ", " to ", " dla ",
        " od ", " przy ", " przez ", " po ",
    ]

    text_lower = text.lower()
    polish_score = sum(1 for indicator in polish_indicators if indicator in text_lower)

    # If more than 3 Polish indicators found, assume Polish
    return "pl" if polish_score >= 3 else "en"
