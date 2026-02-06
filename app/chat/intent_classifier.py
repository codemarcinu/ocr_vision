"""Intent classifier for chat queries - decides search strategy via structured JSON output."""

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from app import ollama_client
from app.config import settings

logger = logging.getLogger(__name__)

# Matches http(s) URLs in text
_URL_RE = re.compile(r'https?://\S+')


@dataclass
class ClassifiedIntent:
    """Structured classification result."""

    intent: str  # rag, web, both, direct, weather, spending, inventory
    query: str  # Reformulated standalone search query
    confidence: str  # high, medium, low


CLASSIFY_PROMPT = """Classify the user's question and reformulate it as a standalone search query.
Respond in JSON: {{"intent": "...", "query": "...", "confidence": "..."}}

Intent categories:
- "rag" - question about personal data: articles read, saved notes, bookmarks, transcriptions
- "spending" - question about spending, prices, shopping costs, store comparison, receipts, discounts, how much spent
- "inventory" - question about pantry, food stock, expiring items, what is at home, spiżarnia
- "weather" - question about current weather, temperature, forecast, rain, wind
- "web" - question requiring current internet information: news, current prices, recent events, facts to look up
- "both" - question needing both personal data and internet context
- "direct" - general knowledge, greeting, math, continuation of conversation, opinion request

Query rules:
- Reformulate the question into a standalone search query (resolve pronouns like "it", "that", "this" using conversation history)
- For "direct" intent, set query to empty string ""
- For "spending" or "inventory", extract the key entity (product name, store, time period)

Confidence: "high" if clearly one category, "medium" if ambiguous, "low" if unsure.

Conversation history:
{history}

Current question: {question}

JSON:"""


def _format_history(history: list[dict]) -> str:
    """Format conversation history for the classification prompt."""
    if not history:
        return "(no previous messages)"

    lines = []
    for msg in history[-4:]:
        role = "User" if msg["role"] == "user" else "Assistant"
        content = msg["content"][:200]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def classify_intent(
    question: str,
    history: list[dict],
) -> ClassifiedIntent:
    """Classify question intent with structured JSON output.

    Args:
        question: Current user message
        history: Recent conversation messages [{role, content}, ...]

    Returns:
        ClassifiedIntent with intent, reformulated query, and confidence.
    """
    # Fast-path: if message is primarily a URL, classify as "web" without LLM
    stripped = question.strip()
    urls = _URL_RE.findall(stripped)
    if urls:
        non_url_text = _URL_RE.sub("", stripped).strip()
        if len(non_url_text) < 10:
            # Message is just a URL (or URL + a few words) -> web search/summarize
            logger.info(f"Intent: 'web' (fast-path URL detection) for: {stripped[:80]}")
            return ClassifiedIntent(intent="web", query=urls[0], confidence="high")

    model = settings.CHAT_MODEL or settings.CLASSIFIER_MODEL

    history_text = _format_history(history)

    prompt = CLASSIFY_PROMPT.format(
        history=history_text,
        question=question,
    )

    response, error = await ollama_client.post_generate(
        model=model,
        prompt=prompt,
        options={
            "temperature": 0.0,
            "num_predict": 150,
        },
        timeout=15.0,
        keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
        format="json",
    )

    if error:
        logger.warning(f"Intent classification error: {error}, defaulting to 'direct'")
        return ClassifiedIntent(intent="direct", query=question, confidence="low")

    # Parse JSON response
    try:
        data = json.loads(response.strip())
        intent = data.get("intent", "direct").lower().strip("\"'")
        query = data.get("query", question) or question
        confidence = data.get("confidence", "medium")
    except (json.JSONDecodeError, AttributeError):
        # Fallback: try to extract intent from raw text (backward compat)
        raw = response.strip().lower()
        intent = raw.split()[0].strip("\"'.,;:") if raw else "direct"
        query = question
        confidence = "low"
        logger.warning(f"JSON parse failed, raw response: {response[:100]}")

    valid_intents = {"rag", "web", "both", "direct", "weather", "spending", "inventory"}
    if intent not in valid_intents:
        logger.warning(f"Unknown intent '{intent}', defaulting to 'direct'")
        return ClassifiedIntent(intent="direct", query=question, confidence="low")

    logger.info(
        f"Intent: '{intent}' (conf={confidence}), "
        f"query: '{query[:60]}' for: {question[:80]}"
    )
    return ClassifiedIntent(intent=intent, query=query, confidence=confidence)
