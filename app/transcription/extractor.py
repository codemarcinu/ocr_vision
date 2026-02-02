"""Knowledge extraction from transcriptions using Ollama LLM."""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.config import settings
from app import ollama_client

logger = logging.getLogger(__name__)

# Polish prompt for transcription analysis
TRANSCRIPTION_ANALYSIS_PROMPT = """Przeanalizuj poniższą transkrypcję nagrania i zwróć wynik w formacie JSON.

INSTRUKCJE:
1. Napisz zwięzłe podsumowanie (2-3 zdania) głównej treści
2. Wylistuj główne tematy omawiane w nagraniu (max 5)
3. Wyodrębnij kluczowe punkty jako bullet points (max 10)
4. Znajdź wszystkie wymienione osoby, firmy, produkty, technologie
5. Wypisz zadania do wykonania lub rekomendacje (jeśli są)
6. Przypisz kategorię z listy: {categories}
7. Wybierz max 5 tagów tematycznych (pojedyncze słowa, małe litery)

WYMAGANY FORMAT JSON:
{{
  "summary": "Podsumowanie głównej treści nagrania...",
  "topics": ["temat1", "temat2", "temat3"],
  "key_points": [
    "Pierwszy kluczowy punkt",
    "Drugi kluczowy punkt"
  ],
  "entities": ["OpenAI", "Python", "Jan Kowalski"],
  "action_items": [
    "Sprawdzić dokumentację X",
    "Zainstalować narzędzie Y"
  ],
  "category": "Technologia",
  "tags": ["programowanie", "ai", "tutorial"]
}}

TRANSKRYPCJA:
{content}

JSON:"""

# English prompt
TRANSCRIPTION_ANALYSIS_PROMPT_EN = """Analyze the following audio/video transcription and return the result in JSON format.

INSTRUCTIONS:
1. Write a brief summary (2-3 sentences) of the main content
2. List main topics discussed (max 5)
3. Extract key points as bullet points (max 10)
4. Find all mentioned people, companies, products, technologies
5. List action items or recommendations (if any)
6. Assign category from: {categories}
7. Select max 5 topic tags (single words, lowercase)

REQUIRED JSON FORMAT:
{{
  "summary": "Summary of the main content...",
  "topics": ["topic1", "topic2", "topic3"],
  "key_points": [
    "First key point",
    "Second key point"
  ],
  "entities": ["OpenAI", "Python", "John Doe"],
  "action_items": [
    "Check documentation X",
    "Install tool Y"
  ],
  "category": "Technology",
  "tags": ["programming", "ai", "tutorial"]
}}

TRANSCRIPTION:
{content}

JSON:"""

# English categories
CATEGORIES_EN = [
    "Education",
    "Technology",
    "Business",
    "Entertainment",
    "Science",
    "Interview",
    "Podcast",
    "Tutorial",
    "Presentation",
    "Other",
]


@dataclass
class ExtractionResult:
    """Result of knowledge extraction from transcription."""

    summary_text: str
    model_used: str
    processing_time_sec: float
    topics: List[str] = field(default_factory=list)
    key_points: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    category: Optional[str] = None
    tags: List[str] = field(default_factory=list)
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


def _extract_fallback(response: str, transcription: str) -> dict:
    """
    Fallback extraction when JSON parsing fails.

    Returns minimal extracted data.
    """
    # Try to extract bullet points as key points
    lines = response.strip().split("\n")
    key_points = []
    for line in lines:
        line = line.strip()
        if line.startswith(("-", "*", "•", "·")):
            key_points.append(line.lstrip("-*•· "))

    # Use first 500 chars as summary if we have nothing
    summary = response[:500] if response else transcription[:500]

    return {
        "summary": summary,
        "topics": [],
        "key_points": key_points[:10],
        "entities": [],
        "action_items": [],
        "category": None,
        "tags": [],
    }


def detect_language(text: str) -> str:
    """
    Detect if text is Polish or English.

    Returns 'pl' or 'en'.
    """
    polish_indicators = [
        "ą", "ć", "ę", "ł", "ń", "ó", "ś", "ź", "ż",
        " i ", " w ", " z ", " na ", " do ", " nie ",
        " się ", " jest ", " że ", " to ", " dla ",
    ]

    text_lower = text.lower()
    polish_score = sum(1 for indicator in polish_indicators if indicator in text_lower)

    return "pl" if polish_score >= 3 else "en"


class KnowledgeExtractor:
    """Service for extracting structured knowledge from transcriptions."""

    def __init__(self):
        """Initialize extractor with model from settings."""
        # Use dedicated transcription model or fall back to classifier model
        self.model = (
            settings.TRANSCRIPTION_NOTE_MODEL
            or settings.SUMMARIZER_MODEL_PL
            or settings.CLASSIFIER_MODEL
        )

    async def extract(
        self,
        transcription_text: str,
        language: str = "auto",
        max_content_length: int = 12000,
    ) -> Tuple[Optional[ExtractionResult], Optional[str]]:
        """
        Extract structured knowledge from transcription text.

        Args:
            transcription_text: Full transcription text
            language: 'pl', 'en', or 'auto' for auto-detection
            max_content_length: Truncate if longer

        Returns:
            Tuple of (ExtractionResult or None, error message or None)
        """
        if not transcription_text:
            return None, "No transcription text to analyze"

        # Auto-detect language
        if language == "auto":
            language = detect_language(transcription_text)

        # Truncate if too long
        original_length = len(transcription_text)
        if original_length > max_content_length:
            transcription_text = transcription_text[:max_content_length] + "..."
            logger.info(
                f"Truncated transcription from {original_length} to {max_content_length} chars"
            )

        # Select prompt based on language
        if language == "pl":
            categories = ", ".join(settings.TRANSCRIPTION_CATEGORIES)
            prompt = TRANSCRIPTION_ANALYSIS_PROMPT.format(
                content=transcription_text,
                categories=categories,
            )
        else:
            categories = ", ".join(CATEGORIES_EN)
            prompt = TRANSCRIPTION_ANALYSIS_PROMPT_EN.format(
                content=transcription_text,
                categories=categories,
            )

        logger.info(f"Extracting knowledge with model: {self.model}, language: {language}")
        start_time = time.time()

        try:
            response, error = await ollama_client.post_generate(
                model=self.model,
                prompt=prompt,
                options={
                    "temperature": 0.3,
                    "num_predict": 3000,
                },
                timeout=300.0,  # Longer timeout for large transcriptions
                keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
            )

            elapsed = time.time() - start_time
            logger.info(f"Knowledge extraction completed in {elapsed:.1f}s")

            if error:
                return None, f"LLM error: {error}"

            if not response or not response.strip():
                return None, "Empty response from LLM"

            # Parse JSON response
            parsed = _parse_json_response(response)

            if not parsed:
                logger.warning("JSON parsing failed, using fallback extraction")
                parsed = _extract_fallback(response, transcription_text)

            # Extract and validate fields
            summary_text = parsed.get("summary", "")
            topics = [str(t).strip() for t in parsed.get("topics", []) if t][:5]
            key_points = [str(p).strip() for p in parsed.get("key_points", []) if p][:10]
            entities = [str(e).strip() for e in parsed.get("entities", []) if e][:15]
            action_items = [str(a).strip() for a in parsed.get("action_items", []) if a][:10]
            tags = [str(t).lower().strip() for t in parsed.get("tags", []) if t][:5]
            category = parsed.get("category")

            # Validate category
            valid_categories = (
                settings.TRANSCRIPTION_CATEGORIES if language == "pl" else CATEGORIES_EN
            )
            if category not in valid_categories:
                category = "Inne" if language == "pl" else "Other"

            if not summary_text:
                summary_text = transcription_text[:500]

            return (
                ExtractionResult(
                    summary_text=summary_text,
                    model_used=self.model,
                    processing_time_sec=round(elapsed, 2),
                    topics=topics,
                    key_points=key_points,
                    entities=entities,
                    action_items=action_items,
                    category=category,
                    tags=tags,
                    language=language,
                ),
                None,
            )

        except Exception as e:
            logger.exception("Knowledge extraction error")
            return None, f"Error: {e}"


# Convenience function for direct use
async def extract_knowledge(
    transcription_text: str,
    language: str = "auto",
) -> Tuple[Optional[ExtractionResult], Optional[str]]:
    """
    Extract knowledge from transcription text.

    Args:
        transcription_text: Full transcription text
        language: 'pl', 'en', or 'auto'

    Returns:
        Tuple of (ExtractionResult or None, error message or None)
    """
    extractor = KnowledgeExtractor()
    return await extractor.extract(transcription_text, language)
