"""Chat orchestrator - ties together intent classification, search, and LLM."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app import ollama_client
from app.chat import intent_classifier, searxng_client
from app.config import settings
from app.db.repositories.chat import ChatRepository
from app.rag import retriever

logger = logging.getLogger(__name__)


CHAT_SYSTEM_PROMPT_PL = """Jesteś pomocnym asystentem osobistego systemu zarządzania wiedzą (Second Brain).
Masz dostęp do osobistej bazy wiedzy (artykuły, paragony, transkrypcje, notatki, zakładki) oraz możesz przeszukiwać internet.

ZASADY:
- ZAWSZE odpowiadaj po polsku (chyba że użytkownik pisze w innym języku)
- Odpowiadaj WYŁĄCZNIE na podstawie dostarczonych wyników wyszukiwania (KONTEKST WYSZUKIWANIA)
- NIE wymyślaj informacji, których nie ma w kontekście wyszukiwania
- NIE wymyślaj cytowań źródeł - cytuj TYLKO źródła widoczne w KONTEKŚCIE WYSZUKIWANIA
- Jeśli kontekst nie zawiera odpowiedzi na pytanie lub jest pusty, powiedz krótko po polsku: "Nie znalazłem odpowiednich danych w bazie wiedzy."
- Cytując dane osobiste, podaj źródło w [nawiasach] DOKŁADNIE tak jak występuje w kontekście
- Cytując wyniki z internetu, podaj URL z kontekstu
- Odpowiadaj zwięźle i konkretnie
- Możesz używać formatowania Markdown (listy, **bold**, *italic*)"""

CHAT_SYSTEM_PROMPT_EN = """You are a helpful assistant for a personal knowledge management system (Second Brain).
You have access to a personal knowledge base (articles, receipts, transcriptions, notes, bookmarks) and can search the internet.

RULES:
- Always respond in the same language as the user's question
- Answer ONLY based on the provided search results (SEARCH CONTEXT)
- DO NOT invent information that is not in the search context
- DO NOT fabricate source citations - cite ONLY sources visible in the SEARCH CONTEXT
- If the context does not contain an answer or is empty, say briefly: "I didn't find relevant data in the knowledge base."
- When citing personal data, reference sources in [brackets] EXACTLY as they appear in the context
- When citing web results, include the URL from the context
- Be concise and helpful
- You can use Markdown formatting (lists, **bold**, *italic*)"""


@dataclass
class ChatResponse:
    """Response from the chat orchestrator."""

    answer: str
    sources: list[dict] = field(default_factory=list)
    search_type: str = "direct"
    search_query: Optional[str] = None
    model_used: str = ""
    processing_time_sec: float = 0.0


def _detect_language(text: str) -> str:
    """Simple Polish vs English detection."""
    polish_chars = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
    polish_words = [" i ", " w ", " się ", " na ", " do ", " z ", " co ", " jak ", " ile "]

    indicators = sum(1 for c in text if c in polish_chars)
    indicators += sum(1 for w in polish_words if w in text.lower())

    return "pl" if indicators >= 2 else "en"


def _format_rag_context(results: list[retriever.SearchResult]) -> str:
    """Format RAG search results into context text."""
    type_labels = {
        "article": "Artykuł",
        "transcription": "Transkrypcja",
        "receipt": "Paragon",
        "note": "Notatka",
        "bookmark": "Zakładka",
    }

    parts = []
    for r in results:
        meta = r.metadata
        label = type_labels.get(r.content_type, r.content_type)

        if r.content_type == "receipt":
            source = f"[{label}: {meta.get('store', '')} {meta.get('date', '')}]"
        elif meta.get("title"):
            source = f"[{label}: {meta['title']}]"
        else:
            source = f"[{label}]"

        parts.append(f"{source}\n{r.text_chunk}")

    return "\n\n---\n\n".join(parts)


def _format_web_context(results: list[searxng_client.SearchResult]) -> str:
    """Format web search results into context text."""
    parts = []
    for r in results:
        parts.append(f"[Web: {r.title}]\nURL: {r.url}\n{r.snippet}")
    return "\n\n---\n\n".join(parts)


def _extract_sources(
    rag_results: list[retriever.SearchResult],
    web_results: list[searxng_client.SearchResult],
) -> list[dict]:
    """Extract source references from search results."""
    sources = []
    seen = set()

    for r in rag_results:
        key = (r.content_type, r.content_id)
        if key not in seen:
            meta = r.metadata
            title = meta.get("title", "")
            if r.content_type == "receipt":
                title = f"{meta.get('store', '')} {meta.get('date', '')}".strip()
            sources.append({
                "type": "rag",
                "content_type": r.content_type,
                "content_id": r.content_id,
                "title": title or r.content_id[:8],
                "score": round(r.score, 3),
            })
            seen.add(key)

    for r in web_results:
        if r.url not in seen:
            sources.append({
                "type": "web",
                "title": r.title[:60],
                "url": r.url,
            })
            seen.add(r.url)

    return sources


async def process_message(
    message: str,
    session_id: UUID,
    db_session: AsyncSession,
    max_history: Optional[int] = None,
) -> ChatResponse:
    """Process a chat message through the full pipeline.

    Args:
        message: User's message text
        session_id: Chat session UUID
        db_session: Database session
        max_history: Max history messages to include (default from config)

    Returns:
        ChatResponse with answer, sources, and metadata.
    """
    start_time = time.time()
    model = settings.CHAT_MODEL or settings.CLASSIFIER_MODEL
    max_hist = max_history or settings.CHAT_MAX_HISTORY

    # 1. Load recent message history from DB
    chat_repo = ChatRepository(db_session)
    recent_messages = await chat_repo.get_recent_messages(session_id, limit=max_hist)

    history = [
        {"role": msg.role, "content": msg.content}
        for msg in recent_messages
    ]

    # 2. Classify intent
    intent = await intent_classifier.classify_intent(message, history)

    # 3. Execute search based on intent
    rag_results: list[retriever.SearchResult] = []
    web_results: list[searxng_client.SearchResult] = []

    # Minimum relevance score for RAG results to be included in context.
    # nomic-embed-text returns ~0.7 for unrelated content, so 0.75 filters noise.
    CHAT_RAG_MIN_SCORE = 0.75

    if intent == "rag":
        rag_results = await retriever.search(
            query=message, session=db_session, top_k=settings.RAG_TOP_K,
        )
    elif intent == "web":
        web_results, web_err = await searxng_client.search(message)
        if web_err:
            logger.warning(f"Web search error: {web_err}")
    elif intent == "both":
        rag_task = retriever.search(
            query=message, session=db_session, top_k=settings.RAG_TOP_K,
        )
        web_task = searxng_client.search(message)
        rag_results, (web_results, web_err) = await asyncio.gather(
            rag_task, web_task,
        )
        if web_err:
            logger.warning(f"Web search error: {web_err}")
    # else: "direct" - no search

    # Filter out low-relevance RAG results to prevent hallucinations
    if rag_results:
        before = len(rag_results)
        rag_results = [r for r in rag_results if r.score >= CHAT_RAG_MIN_SCORE]
        filtered = before - len(rag_results)
        if filtered:
            logger.info(f"Filtered {filtered}/{before} low-relevance RAG results (min score: {CHAT_RAG_MIN_SCORE})")

    # 4. Build context from search results
    context_parts = []
    if rag_results:
        context_parts.append(
            "=== OSOBISTA BAZA WIEDZY ===\n" + _format_rag_context(rag_results)
        )
    if web_results:
        context_parts.append(
            "=== WYNIKI Z INTERNETU ===\n" + _format_web_context(web_results)
        )

    context = "\n\n".join(context_parts)

    # If search was performed but returned no results, inform the LLM
    if intent in ("rag", "both") and not rag_results and not web_results:
        context = "BRAK WYNIKÓW WYSZUKIWANIA - nie znaleziono pasujących danych w bazie wiedzy ani w internecie."
    elif intent == "rag" and not rag_results:
        context = "BRAK WYNIKÓW - nie znaleziono pasujących danych w osobistej bazie wiedzy."
    elif intent == "web" and not web_results:
        context = "BRAK WYNIKÓW - wyszukiwanie internetowe nie zwróciło wyników."

    # 5. Build LLM message history
    lang = _detect_language(message)
    system_prompt = CHAT_SYSTEM_PROMPT_PL if lang == "pl" else CHAT_SYSTEM_PROMPT_EN

    if context:
        system_prompt += f"\n\nKONTEKST WYSZUKIWANIA:\n{context}"

    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})

    # Add current message
    messages.append({"role": "user", "content": message})

    # 6. Call LLM
    response, error = await ollama_client.post_chat(
        model=model,
        messages=messages,
        options={
            "temperature": 0.4,
            "num_predict": 2048,
        },
        timeout=120.0,
        keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
    )

    if error:
        logger.error(f"Chat LLM error: {error}")
        return ChatResponse(
            answer=f"Błąd generowania odpowiedzi: {error}",
            search_type=intent,
            model_used=model,
            processing_time_sec=round(time.time() - start_time, 2),
        )

    # 7. Extract sources
    sources = _extract_sources(rag_results, web_results)

    return ChatResponse(
        answer=response.strip(),
        sources=sources,
        search_type=intent,
        search_query=message if intent != "direct" else None,
        model_used=model,
        processing_time_sec=round(time.time() - start_time, 2),
    )
