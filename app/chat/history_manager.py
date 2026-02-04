"""Manage conversation history with summarization for long contexts."""

import logging
from typing import Optional

from app import ollama_client
from app.config import settings

logger = logging.getLogger(__name__)

SUMMARIZE_PROMPT = """Podsumuj poniższą rozmowę w 2-3 zdaniach. Zachowaj kluczowe fakty, nazwy, liczby i daty.

Rozmowa:
{conversation}

Zwięzłe podsumowanie:"""


async def prepare_history(
    messages: list[dict],
    max_recent: int = 4,
) -> list[dict]:
    """Prepare conversation history for LLM context.

    Strategy:
    - If total history fits within max_recent messages, return as-is
    - Otherwise: summarize older messages, keep last max_recent verbatim

    Args:
        messages: Full conversation history [{role, content}, ...]
        max_recent: Number of recent messages to keep verbatim

    Returns:
        Condensed message list, possibly with a summary prepended.
    """
    summarize_after = getattr(settings, "CHAT_SUMMARIZE_AFTER", 6)

    if len(messages) <= summarize_after:
        return messages

    old_messages = messages[:-max_recent]
    recent_messages = messages[-max_recent:]

    # Build conversation text from old messages
    old_text = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:300]}"
        for m in old_messages
    )

    # Skip summarization if old messages are too short
    if len(old_text) < 500:
        return messages

    prompt = SUMMARIZE_PROMPT.format(conversation=old_text[:3000])

    model = settings.CHAT_MODEL or settings.CLASSIFIER_MODEL

    summary, error = await ollama_client.post_generate(
        model=model,
        prompt=prompt,
        options={"temperature": 0.1, "num_predict": 200},
        timeout=15.0,
        keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
    )

    if error or not summary.strip():
        logger.warning(f"History summarization failed: {error}")
        return messages[-max_recent:]

    logger.info(
        f"Summarized {len(old_messages)} old messages "
        f"({len(old_text)} chars) into {len(summary.strip())} chars"
    )

    result = [
        {"role": "system", "content": f"Podsumowanie wcześniejszej rozmowy: {summary.strip()}"}
    ]
    result.extend(recent_messages)
    return result
