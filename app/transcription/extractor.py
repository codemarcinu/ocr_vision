"""Knowledge extraction from transcriptions using Ollama LLM.

Supports both single-pass extraction for short transcriptions and
map-reduce chunking for long transcriptions (3h+).
"""

import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Callable, List, Optional, Tuple

from app.config import settings
from app import ollama_client

logger = logging.getLogger(__name__)

# =============================================================================
# Single-pass prompts (for short transcriptions)
# =============================================================================

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

# =============================================================================
# Map-Reduce prompts (for long transcriptions)
# =============================================================================

MAP_PROMPT_PL = """Przeanalizuj FRAGMENT transkrypcji (część {chunk_num} z {total_chunks}).

KONTEKST: To jest fragment dłuższego nagrania. Wyodrębnij tylko informacje z TEGO fragmentu.

INSTRUKCJE:
1. Podsumuj główne punkty tego fragmentu (2-3 zdania)
2. Wymień tematy poruszane w tym fragmencie (max 5)
3. Wypisz kluczowe punkty (max 5)
4. Znajdź osoby, firmy, produkty, technologie (max 10)
5. Wypisz zadania/rekomendacje jeśli są (max 5)

WYMAGANY FORMAT JSON:
{{
  "chunk_summary": "Podsumowanie tego fragmentu...",
  "topics": ["temat1", "temat2"],
  "key_points": ["punkt1", "punkt2"],
  "entities": ["OpenAI", "Python"],
  "action_items": ["zadanie1"]
}}

FRAGMENT TRANSKRYPCJI:
{content}

JSON:"""

MAP_PROMPT_EN = """Analyze this FRAGMENT of transcription (part {chunk_num} of {total_chunks}).

CONTEXT: This is a fragment of a longer recording. Extract only information from THIS fragment.

INSTRUCTIONS:
1. Summarize the main points of this fragment (2-3 sentences)
2. List topics discussed in this fragment (max 5)
3. Extract key points (max 5)
4. Find people, companies, products, technologies (max 10)
5. List action items/recommendations if any (max 5)

REQUIRED JSON FORMAT:
{{
  "chunk_summary": "Summary of this fragment...",
  "topics": ["topic1", "topic2"],
  "key_points": ["point1", "point2"],
  "entities": ["OpenAI", "Python"],
  "action_items": ["task1"]
}}

TRANSCRIPTION FRAGMENT:
{content}

JSON:"""

REDUCE_PROMPT_PL = """Na podstawie analiz {num_chunks} fragmentów transkrypcji, stwórz końcowe podsumowanie całego nagrania.

STRESZCZENIA FRAGMENTÓW:
{chunk_summaries}

WSZYSTKIE ZNALEZIONE TEMATY:
{all_topics}

WSZYSTKIE KLUCZOWE PUNKTY:
{all_key_points}

WSZYSTKIE ENCJE (osoby, firmy, produkty):
{all_entities}

ZADANIA DO WYKONANIA:
{all_action_items}

INSTRUKCJE:
1. Napisz spójne podsumowanie CAŁEGO nagrania (3-5 zdań), łącząc informacje ze wszystkich fragmentów
2. Wybierz 5 najważniejszych tematów (z listy powyżej)
3. Wybierz 10 najważniejszych kluczowych punktów (z listy powyżej)
4. Wypisz max 15 unikalnych encji (osoby, firmy, produkty)
5. Wypisz wszystkie zadania do wykonania (max 10)
6. Przypisz kategorię z listy: {categories}
7. Wybierz 5 tagów tematycznych

WYMAGANY FORMAT JSON:
{{
  "summary": "Końcowe podsumowanie całego nagrania...",
  "topics": ["temat1", "temat2", "temat3", "temat4", "temat5"],
  "key_points": ["punkt1", "punkt2", "punkt3"],
  "entities": ["encja1", "encja2"],
  "action_items": ["zadanie1", "zadanie2"],
  "category": "Technologia",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}

JSON:"""

REDUCE_PROMPT_EN = """Based on analyses of {num_chunks} transcription fragments, create a final summary of the entire recording.

FRAGMENT SUMMARIES:
{chunk_summaries}

ALL FOUND TOPICS:
{all_topics}

ALL KEY POINTS:
{all_key_points}

ALL ENTITIES (people, companies, products):
{all_entities}

ACTION ITEMS:
{all_action_items}

INSTRUCTIONS:
1. Write a coherent summary of the ENTIRE recording (3-5 sentences), combining information from all fragments
2. Select 5 most important topics (from the list above)
3. Select 10 most important key points (from the list above)
4. List max 15 unique entities (people, companies, products)
5. List all action items (max 10)
6. Assign category from: {categories}
7. Select 5 topic tags

REQUIRED JSON FORMAT:
{{
  "summary": "Final summary of the entire recording...",
  "topics": ["topic1", "topic2", "topic3", "topic4", "topic5"],
  "key_points": ["point1", "point2", "point3"],
  "entities": ["entity1", "entity2"],
  "action_items": ["task1", "task2"],
  "category": "Technology",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}

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

# =============================================================================
# Data classes
# =============================================================================


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
    chunks_processed: int = 0  # 0 = single-pass, >0 = map-reduce


@dataclass
class ChunkInfo:
    """Information about a text chunk for map-reduce processing."""

    index: int
    total: int
    text: str
    start_char: int
    end_char: int


@dataclass
class ChunkResult:
    """Result from processing a single chunk in map phase."""

    chunk_index: int
    summary: str
    topics: List[str] = field(default_factory=list)
    key_points: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    error: Optional[str] = None


# =============================================================================
# Utility functions
# =============================================================================


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
    lines = response.strip().split("\n")
    key_points = []
    for line in lines:
        line = line.strip()
        if line.startswith(("-", "*", "•", "·")):
            key_points.append(line.lstrip("-*•· "))

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


# =============================================================================
# Chunking functions
# =============================================================================


def split_into_chunks(
    text: str,
    chunk_size: int = None,
    overlap: int = None,
    max_chunks: int = None,
) -> List[ChunkInfo]:
    """
    Split text into overlapping chunks at sentence boundaries.

    Args:
        text: Full text to split
        chunk_size: Target size per chunk in characters (default from settings)
        overlap: Overlap between chunks in characters (default from settings)
        max_chunks: Maximum number of chunks (default from settings)

    Returns:
        List of ChunkInfo objects
    """
    chunk_size = chunk_size or settings.MAPREDUCE_CHUNK_SIZE
    overlap = overlap or settings.MAPREDUCE_OVERLAP
    max_chunks = max_chunks or settings.MAPREDUCE_MAX_CHUNKS

    # Split on sentence boundaries (Polish and English aware)
    # Match: . ! ? followed by space and uppercase letter
    sentence_pattern = r'(?<=[.!?])\s+(?=[A-ZŻŹĆĄŚĘŁÓŃ])'
    sentences = re.split(sentence_pattern, text)

    # If regex didn't split well (e.g., no proper punctuation), fall back to paragraphs
    if len(sentences) <= 1:
        sentences = text.split('\n\n')
    if len(sentences) <= 1:
        sentences = text.split('\n')

    chunks = []
    current_text = ""
    current_start = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Check if adding this sentence would exceed chunk_size
        if current_text and len(current_text) + len(sentence) + 1 > chunk_size:
            # Save current chunk
            chunks.append(ChunkInfo(
                index=len(chunks),
                total=0,  # Will be updated later
                text=current_text.strip(),
                start_char=current_start,
                end_char=current_start + len(current_text),
            ))

            # Start new chunk with overlap from end of previous
            overlap_text = current_text[-overlap:] if len(current_text) > overlap else current_text
            # Find sentence boundary in overlap
            overlap_start = overlap_text.rfind('. ')
            if overlap_start > 0:
                overlap_text = overlap_text[overlap_start + 2:]

            current_start = current_start + len(current_text) - len(overlap_text)
            current_text = overlap_text + " " + sentence
        else:
            if current_text:
                current_text += " " + sentence
            else:
                current_text = sentence

    # Don't forget the last chunk
    if current_text.strip():
        chunks.append(ChunkInfo(
            index=len(chunks),
            total=0,
            text=current_text.strip(),
            start_char=current_start,
            end_char=current_start + len(current_text),
        ))

    # Update total count
    total = len(chunks)
    for chunk in chunks:
        chunk.total = total

    # Apply max_chunks limit
    if len(chunks) > max_chunks:
        logger.warning(
            f"Transcription would create {len(chunks)} chunks, "
            f"limiting to {max_chunks} (some content will be lost)"
        )
        # Keep evenly distributed chunks
        step = len(chunks) / max_chunks
        selected_indices = [int(i * step) for i in range(max_chunks)]
        chunks = [chunks[i] for i in selected_indices]
        # Re-index
        for i, chunk in enumerate(chunks):
            chunk.index = i
            chunk.total = max_chunks

    logger.info(f"Split transcription into {len(chunks)} chunks")
    return chunks


# =============================================================================
# Deduplication functions
# =============================================================================


def dedupe_entities(entities: List[str], similarity_threshold: float = 0.85) -> List[str]:
    """
    Deduplicate similar entities using fuzzy matching.

    Args:
        entities: List of entity strings (may contain duplicates)
        similarity_threshold: Minimum similarity ratio to consider as duplicate

    Returns:
        List of unique entities, sorted by frequency
    """
    if not entities:
        return []

    # Normalize and count occurrences
    normalized = Counter()
    original_forms = {}  # normalized -> original with highest count

    for entity in entities:
        entity_clean = entity.strip()
        if not entity_clean:
            continue

        norm = entity_clean.lower()
        normalized[norm] += 1

        # Keep track of original form
        if norm not in original_forms:
            original_forms[norm] = entity_clean

    # Group similar entities
    groups = []
    processed = set()

    for norm_entity in normalized:
        if norm_entity in processed:
            continue

        group = [norm_entity]
        processed.add(norm_entity)

        for other_entity in normalized:
            if other_entity in processed:
                continue
            # Check similarity
            ratio = SequenceMatcher(None, norm_entity, other_entity).ratio()
            if ratio >= similarity_threshold:
                group.append(other_entity)
                processed.add(other_entity)

        groups.append(group)

    # For each group, return the most frequent form in original case
    result = []
    for group in groups:
        # Sum up counts for the group
        total_count = sum(normalized[e] for e in group)
        # Find the entity with highest individual count
        best_norm = max(group, key=lambda e: normalized[e])
        result.append((original_forms[best_norm], total_count))

    # Sort by frequency (descending) and return just the entities
    result.sort(key=lambda x: -x[1])
    return [e for e, _ in result]


def dedupe_topics(topics: List[str], similarity_threshold: float = 0.8) -> List[str]:
    """
    Deduplicate similar topics.

    Similar to dedupe_entities but with lower threshold since topics
    can be more varied in phrasing.
    """
    return dedupe_entities(topics, similarity_threshold)


def dedupe_key_points(key_points: List[str], similarity_threshold: float = 0.75) -> List[str]:
    """
    Deduplicate similar key points.

    Lower threshold since key points can be rephrased differently.
    """
    if not key_points:
        return []

    # Normalize for comparison
    normalized = {}
    for point in key_points:
        point_clean = point.strip()
        if not point_clean:
            continue
        norm = point_clean.lower()
        if norm not in normalized:
            normalized[norm] = point_clean

    # Group similar points
    groups = []
    processed = set()

    for norm_point in normalized:
        if norm_point in processed:
            continue

        group = [norm_point]
        processed.add(norm_point)

        for other_point in normalized:
            if other_point in processed:
                continue
            ratio = SequenceMatcher(None, norm_point, other_point).ratio()
            if ratio >= similarity_threshold:
                group.append(other_point)
                processed.add(other_point)

        groups.append(group)

    # Return first (usually longest) point from each group
    result = []
    for group in groups:
        best = max(group, key=len)
        result.append(normalized[best])

    return result


# =============================================================================
# Main extractor class
# =============================================================================


class KnowledgeExtractor:
    """Service for extracting structured knowledge from transcriptions."""

    def __init__(self):
        """Initialize extractor with model from settings."""
        self.model = (
            settings.TRANSCRIPTION_NOTE_MODEL
            or settings.SUMMARIZER_MODEL_PL
            or settings.CLASSIFIER_MODEL
        )

    async def extract(
        self,
        transcription_text: str,
        language: str = "auto",
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Tuple[Optional[ExtractionResult], Optional[str]]:
        """
        Extract structured knowledge from transcription text.

        Automatically selects single-pass or map-reduce based on text length.

        Args:
            transcription_text: Full transcription text
            language: 'pl', 'en', or 'auto' for auto-detection
            progress_callback: Optional callback(percent, status) for progress updates

        Returns:
            Tuple of (ExtractionResult or None, error message or None)
        """
        if not transcription_text:
            return None, "No transcription text to analyze"

        # Auto-detect language
        if language == "auto":
            language = detect_language(transcription_text)

        text_length = len(transcription_text)

        # Decide: single-pass or map-reduce
        if not settings.MAPREDUCE_ENABLED or text_length <= settings.MAPREDUCE_THRESHOLD:
            logger.info(
                f"Using single-pass extraction ({text_length} chars, "
                f"threshold: {settings.MAPREDUCE_THRESHOLD})"
            )
            return await self._extract_single_pass(
                transcription_text, language, progress_callback
            )
        else:
            logger.info(
                f"Using map-reduce extraction ({text_length} chars, "
                f"threshold: {settings.MAPREDUCE_THRESHOLD})"
            )
            return await self._extract_map_reduce(
                transcription_text, language, progress_callback
            )

    async def _extract_single_pass(
        self,
        transcription_text: str,
        language: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Tuple[Optional[ExtractionResult], Optional[str]]:
        """
        Original single-pass extraction for short transcriptions.

        Truncates to 12000 chars if needed.
        """
        max_content_length = 12000

        if progress_callback:
            progress_callback(10, "analyzing")

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

        if progress_callback:
            progress_callback(20, "extracting")

        try:
            response, error = await ollama_client.post_generate(
                model=self.model,
                prompt=prompt,
                options={
                    "temperature": 0.3,
                    "num_predict": 3000,
                },
                timeout=300.0,
                keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
            )

            elapsed = time.time() - start_time
            logger.info(f"Knowledge extraction completed in {elapsed:.1f}s")

            if error:
                return None, f"LLM error: {error}"

            if not response or not response.strip():
                return None, "Empty response from LLM"

            if progress_callback:
                progress_callback(90, "parsing")

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

            if progress_callback:
                progress_callback(100, "completed")

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
                    chunks_processed=0,
                ),
                None,
            )

        except Exception as e:
            logger.exception("Knowledge extraction error")
            return None, f"Error: {e}"

    async def _extract_map_reduce(
        self,
        transcription_text: str,
        language: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Tuple[Optional[ExtractionResult], Optional[str]]:
        """
        Map-reduce extraction for long transcriptions.

        1. Split into chunks
        2. Process each chunk (MAP phase)
        3. Aggregate and deduplicate results
        4. Final synthesis (REDUCE phase)
        """
        start_time = time.time()

        if progress_callback:
            progress_callback(5, "chunking")

        # Step 1: Split into chunks
        chunks = split_into_chunks(transcription_text)
        total_chunks = len(chunks)

        logger.info(f"Map-reduce: processing {total_chunks} chunks")

        # Step 2: MAP phase - process each chunk
        chunk_results: List[ChunkResult] = []
        failed_chunks = []

        for i, chunk in enumerate(chunks):
            # Progress: 10-80% for MAP phase
            progress = 10 + int(70 * i / total_chunks)
            if progress_callback:
                progress_callback(progress, f"processing_chunk_{i + 1}_of_{total_chunks}")

            try:
                result = await self._extract_from_chunk(chunk, language)
                chunk_results.append(result)
                logger.debug(f"Chunk {i + 1}/{total_chunks} processed successfully")
            except Exception as e:
                logger.warning(f"Chunk {i + 1}/{total_chunks} failed: {e}")
                failed_chunks.append(i)
                # Create empty result for failed chunk
                chunk_results.append(ChunkResult(
                    chunk_index=i,
                    summary="",
                    error=str(e),
                ))

        # Check if we have any successful results
        successful_results = [r for r in chunk_results if not r.error]
        if not successful_results:
            return None, f"All {total_chunks} chunks failed to process"

        if failed_chunks:
            logger.warning(
                f"Map-reduce: {len(successful_results)}/{total_chunks} chunks succeeded, "
                f"failed chunks: {failed_chunks}"
            )

        if progress_callback:
            progress_callback(85, "aggregating")

        # Step 3: Aggregate results
        all_summaries = [r.summary for r in successful_results if r.summary]
        all_topics = []
        all_key_points = []
        all_entities = []
        all_action_items = []

        for result in successful_results:
            all_topics.extend(result.topics)
            all_key_points.extend(result.key_points)
            all_entities.extend(result.entities)
            all_action_items.extend(result.action_items)

        # Deduplicate
        deduped_topics = dedupe_topics(all_topics)
        deduped_key_points = dedupe_key_points(all_key_points)
        deduped_entities = dedupe_entities(all_entities)
        deduped_action_items = dedupe_key_points(all_action_items)  # Use same logic

        if progress_callback:
            progress_callback(90, "synthesizing")

        # Step 4: REDUCE phase - final synthesis
        try:
            final_result = await self._synthesize_final(
                chunk_summaries=all_summaries,
                topics=deduped_topics,
                key_points=deduped_key_points,
                entities=deduped_entities,
                action_items=deduped_action_items,
                language=language,
                num_chunks=len(successful_results),
            )
        except Exception as e:
            logger.exception("REDUCE phase failed")
            # Fallback: use aggregated data without final synthesis
            elapsed = time.time() - start_time
            summary = " | ".join(all_summaries[:5])
            if len(all_summaries) > 5:
                summary += f" | ... (+{len(all_summaries) - 5} more sections)"

            final_result = ExtractionResult(
                summary_text=summary,
                model_used=self.model,
                processing_time_sec=round(elapsed, 2),
                topics=deduped_topics[:5],
                key_points=deduped_key_points[:10],
                entities=deduped_entities[:15],
                action_items=deduped_action_items[:10],
                category="Inne" if language == "pl" else "Other",
                tags=[],
                language=language,
                chunks_processed=len(successful_results),
            )

        elapsed = time.time() - start_time
        final_result.processing_time_sec = round(elapsed, 2)
        final_result.chunks_processed = len(successful_results)

        if progress_callback:
            progress_callback(100, "completed")

        logger.info(
            f"Map-reduce extraction completed: {len(successful_results)} chunks, "
            f"{elapsed:.1f}s total"
        )

        return final_result, None

    async def _extract_from_chunk(
        self,
        chunk: ChunkInfo,
        language: str,
    ) -> ChunkResult:
        """
        Extract knowledge from a single chunk (MAP phase).
        """
        # Select prompt based on language
        if language == "pl":
            prompt = MAP_PROMPT_PL.format(
                chunk_num=chunk.index + 1,
                total_chunks=chunk.total,
                content=chunk.text,
            )
        else:
            prompt = MAP_PROMPT_EN.format(
                chunk_num=chunk.index + 1,
                total_chunks=chunk.total,
                content=chunk.text,
            )

        response, error = await ollama_client.post_generate(
            model=self.model,
            prompt=prompt,
            options={
                "temperature": 0.3,
                "num_predict": 2000,  # Smaller output for chunks
            },
            timeout=180.0,  # Shorter timeout for chunks
            keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
        )

        if error:
            raise RuntimeError(f"LLM error: {error}")

        if not response or not response.strip():
            raise RuntimeError("Empty response from LLM")

        # Parse JSON response
        parsed = _parse_json_response(response)

        if not parsed:
            # Fallback: extract what we can
            logger.warning(f"Chunk {chunk.index + 1}: JSON parsing failed, using fallback")
            return ChunkResult(
                chunk_index=chunk.index,
                summary=response[:500],
                topics=[],
                key_points=[],
                entities=[],
                action_items=[],
            )

        return ChunkResult(
            chunk_index=chunk.index,
            summary=parsed.get("chunk_summary", ""),
            topics=[str(t).strip() for t in parsed.get("topics", []) if t],
            key_points=[str(p).strip() for p in parsed.get("key_points", []) if p],
            entities=[str(e).strip() for e in parsed.get("entities", []) if e],
            action_items=[str(a).strip() for a in parsed.get("action_items", []) if a],
        )

    async def _synthesize_final(
        self,
        chunk_summaries: List[str],
        topics: List[str],
        key_points: List[str],
        entities: List[str],
        action_items: List[str],
        language: str,
        num_chunks: int,
    ) -> ExtractionResult:
        """
        Final synthesis of aggregated chunk results (REDUCE phase).
        """
        # Format summaries with chunk numbers
        formatted_summaries = "\n".join(
            f"Fragment {i + 1}: {summary}"
            for i, summary in enumerate(chunk_summaries)
            if summary
        )

        # Format lists
        formatted_topics = ", ".join(topics[:20])
        formatted_key_points = "\n".join(f"- {p}" for p in key_points[:20])
        formatted_entities = ", ".join(entities[:30])
        formatted_action_items = "\n".join(f"- {a}" for a in action_items[:15])

        # Select prompt and categories based on language
        if language == "pl":
            categories = ", ".join(settings.TRANSCRIPTION_CATEGORIES)
            prompt = REDUCE_PROMPT_PL.format(
                num_chunks=num_chunks,
                chunk_summaries=formatted_summaries,
                all_topics=formatted_topics,
                all_key_points=formatted_key_points,
                all_entities=formatted_entities,
                all_action_items=formatted_action_items,
                categories=categories,
            )
        else:
            categories = ", ".join(CATEGORIES_EN)
            prompt = REDUCE_PROMPT_EN.format(
                num_chunks=num_chunks,
                chunk_summaries=formatted_summaries,
                all_topics=formatted_topics,
                all_key_points=formatted_key_points,
                all_entities=formatted_entities,
                all_action_items=formatted_action_items,
                categories=categories,
            )

        logger.info(f"REDUCE phase: synthesizing {num_chunks} chunk summaries")

        response, error = await ollama_client.post_generate(
            model=self.model,
            prompt=prompt,
            options={
                "temperature": 0.3,
                "num_predict": 3000,
            },
            timeout=300.0,
            keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
        )

        if error:
            raise RuntimeError(f"LLM error: {error}")

        if not response or not response.strip():
            raise RuntimeError("Empty response from LLM")

        # Parse JSON response
        parsed = _parse_json_response(response)

        if not parsed:
            raise RuntimeError("Failed to parse REDUCE phase JSON response")

        # Extract and validate fields
        summary_text = parsed.get("summary", "")
        final_topics = [str(t).strip() for t in parsed.get("topics", []) if t][:5]
        final_key_points = [str(p).strip() for p in parsed.get("key_points", []) if p][:10]
        final_entities = [str(e).strip() for e in parsed.get("entities", []) if e][:15]
        final_action_items = [str(a).strip() for a in parsed.get("action_items", []) if a][:10]
        tags = [str(t).lower().strip() for t in parsed.get("tags", []) if t][:5]
        category = parsed.get("category")

        # Validate category
        valid_categories = (
            settings.TRANSCRIPTION_CATEGORIES if language == "pl" else CATEGORIES_EN
        )
        if category not in valid_categories:
            category = "Inne" if language == "pl" else "Other"

        # Fallback for empty summary
        if not summary_text:
            summary_text = " ".join(chunk_summaries[:3])

        return ExtractionResult(
            summary_text=summary_text,
            model_used=self.model,
            processing_time_sec=0.0,  # Will be updated by caller
            topics=final_topics,
            key_points=final_key_points,
            entities=final_entities,
            action_items=final_action_items,
            category=category,
            tags=tags,
            language=language,
            chunks_processed=num_chunks,
        )


# =============================================================================
# Convenience function
# =============================================================================


async def extract_knowledge(
    transcription_text: str,
    language: str = "auto",
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Tuple[Optional[ExtractionResult], Optional[str]]:
    """
    Extract knowledge from transcription text.

    Args:
        transcription_text: Full transcription text
        language: 'pl', 'en', or 'auto'
        progress_callback: Optional callback(percent, status) for progress updates

    Returns:
        Tuple of (ExtractionResult or None, error message or None)
    """
    extractor = KnowledgeExtractor()
    return await extractor.extract(transcription_text, language, progress_callback)
