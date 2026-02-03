"""Intent classifier for chat queries - decides RAG, web, both, or direct."""

import logging
from typing import Optional

from app import ollama_client
from app.config import settings

logger = logging.getLogger(__name__)


CLASSIFY_PROMPT = """Classify the user's question intent. Respond with ONLY one word.

Categories:
- "rag" - question about personal data: receipts, spending, shopping, articles read, saved notes, bookmarks, transcriptions, pantry
- "weather" - question about current weather, temperature, forecast, rain, wind
- "web" - question requiring current internet information: news, current prices, recent events, facts to look up
- "both" - question needing both personal data and internet context
- "direct" - general knowledge, greeting, math, continuation of conversation, opinion request

Conversation history:
{history}

Current question: {question}

INTENT:"""


async def classify_intent(
    question: str,
    history: list[dict],
) -> str:
    """Classify question intent to determine search strategy.

    Args:
        question: Current user message
        history: Recent conversation messages [{role, content}, ...]

    Returns:
        One of: "rag", "web", "both", "direct", "weather"
    """
    model = settings.CHAT_MODEL or settings.CLASSIFIER_MODEL

    # Format history for prompt
    history_text = ""
    if history:
        history_lines = []
        for msg in history[-4:]:  # Last 4 messages for context
            role = "User" if msg["role"] == "user" else "Assistant"
            content = msg["content"][:200]
            history_lines.append(f"{role}: {content}")
        history_text = "\n".join(history_lines)
    else:
        history_text = "(no previous messages)"

    prompt = CLASSIFY_PROMPT.format(
        history=history_text,
        question=question,
    )

    response, error = await ollama_client.post_generate(
        model=model,
        prompt=prompt,
        options={
            "temperature": 0.0,
            "num_predict": 10,
        },
        timeout=15.0,
        keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
    )

    if error:
        logger.warning(f"Intent classification error: {error}, defaulting to 'direct'")
        return "direct"

    # Parse response - extract the first valid intent word
    intent = response.strip().lower().split()[0] if response.strip() else "direct"

    # Remove quotes/punctuation
    intent = intent.strip('"\'.,;:')

    valid_intents = {"rag", "web", "both", "direct", "weather"}
    if intent not in valid_intents:
        logger.warning(f"Unknown intent '{intent}', defaulting to 'direct'")
        return "direct"

    logger.info(f"Intent classified as '{intent}' for: {question[:80]}")
    return intent
