"""Chat orchestrator - ties together intent classification, search, and LLM."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app import ollama_client
from app.chat import content_fetcher, history_manager, intent_classifier, searxng_client, weather_client
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


@dataclass
class SearchResults:
    """Aggregated search results from all sources."""

    rag_results: list[retriever.SearchResult] = field(default_factory=list)
    web_results: list[searxng_client.SearchResult] = field(default_factory=list)
    weather_data: Optional[dict] = None
    forecast_data: Optional[list[dict]] = None
    final_intent: str = "direct"
    tool_context: Optional[str] = None


# Minimum relevance score for RAG results to be included in context.
# nomic-embed-text returns ~0.7 for unrelated content, so 0.75 filters noise.
CHAT_RAG_MIN_SCORE = 0.75


def _detect_language(text: str) -> str:
    """Simple Polish vs English detection."""
    polish_chars = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")

    padded = f" {text.lower()} "
    polish_words = [
        " i ", " w ", " się ", " na ", " do ", " z ", " co ", " jak ", " ile ",
        " czy ", " jest ", " to ", " mi ", " mam ", " nie ", " tak ", " ze ",
        " jaki ", " jaka ", " jakie ", " gdzie ", " kiedy ", " dlaczego ",
        " ostatni ", " wydal ", " kupil ", " opowiedz ", " powiedz ",
    ]

    indicators = sum(1 for c in text if c in polish_chars)
    indicators += sum(1 for w in polish_words if w in padded)

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


def _format_weather_context(
    current: Optional[dict],
    forecast: Optional[list[dict]],
) -> str:
    """Format current weather + forecast into context text."""
    unit = "°C" if settings.WEATHER_UNITS == "metric" else "°F"
    speed_unit = "m/s" if settings.WEATHER_UNITS == "metric" else "mph"
    parts = []

    if current:
        parts.append(
            f"=== AKTUALNA POGODA: {current['city_name']} ===\n"
            f"Opis: {current['description']}\n"
            f"Temperatura: {current['temp']}{unit} (odczuwalna: {current['feels_like']}{unit})\n"
            f"Wilgotność: {current['humidity']}%\n"
            f"Ciśnienie: {current['pressure']} hPa\n"
            f"Wiatr: {current['wind_speed']} {speed_unit}\n"
            f"Zachmurzenie: {current['clouds']}%"
        )

    if forecast:
        city = forecast[0].get("city_name", "")
        lines = [f"=== PROGNOZA (co 3h, 5 dni): {city} ==="]
        for e in forecast:
            rain = f", deszcz: {e['rain_mm']}mm" if e.get("rain_mm") else ""
            lines.append(
                f"{e['datetime']} | {e['temp']}{unit} "
                f"({e['description']}, wiatr {e['wind_speed']}{speed_unit}{rain})"
            )
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def _format_web_context(results: list[searxng_client.SearchResult]) -> str:
    """Format web search results into context text, using full content when available."""
    parts = []
    for i, r in enumerate(results, 1):
        text = r.content if r.content else r.snippet
        source_type = "pełna treść" if r.content else "fragment"
        parts.append(
            f"[Źródło {i}: {r.title}] ({source_type})\n"
            f"URL: {r.url}\n"
            f"{text}"
        )
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


def _filter_rag_results(
    rag_results: list[retriever.SearchResult],
) -> list[retriever.SearchResult]:
    """Filter out low-relevance RAG results."""
    if not rag_results:
        return []

    before = len(rag_results)
    filtered = [r for r in rag_results if r.score >= CHAT_RAG_MIN_SCORE]
    removed = before - len(filtered)
    if removed:
        logger.info(
            f"Filtered {removed}/{before} low-relevance RAG results "
            f"(min score: {CHAT_RAG_MIN_SCORE})"
        )
    return filtered


async def _web_search(
    query: str,
    language: str = "pl",
) -> tuple[list[searxng_client.SearchResult], str | None]:
    """Run web search with optional query expansion."""
    num = settings.WEB_SEARCH_NUM_RESULTS
    if settings.WEB_SEARCH_EXPAND_NEWS:
        return await searxng_client.search_expanded(query, num_results=num, language=language)
    return await searxng_client.search(query, num_results=num, language=language)


async def _execute_search(
    intent: str,
    search_query: str,
    confidence: str,
    db_session: AsyncSession,
    language: str = "pl",
) -> SearchResults:
    """Execute search based on classified intent, with fallback chain.

    Fallback logic:
    - rag with no results + confidence != high → try web
    - web with no results → try rag
    """
    result = SearchResults(final_intent=intent)

    if intent == "rag":
        result.rag_results = await retriever.search(
            query=search_query, session=db_session, top_k=settings.RAG_TOP_K,
        )
        result.rag_results = _filter_rag_results(result.rag_results)

        # Fallback: RAG empty + not high confidence → try web
        if not result.rag_results and confidence != "high":
            logger.info("RAG returned no results, falling back to web search")
            result.web_results, web_err = await _web_search(search_query, language=language)
            if web_err:
                logger.warning(f"Web fallback error: {web_err}")
            if result.web_results:
                result.final_intent = "rag→web"

    elif intent == "weather":
        (result.weather_data, weather_err), (result.forecast_data, forecast_err) = (
            await asyncio.gather(
                weather_client.get_weather(),
                weather_client.get_forecast(),
            )
        )
        if weather_err:
            logger.warning(f"Weather API error: {weather_err}")
        if forecast_err:
            logger.warning(f"Forecast API error: {forecast_err}")

    elif intent == "web":
        result.web_results, web_err = await _web_search(search_query, language=language)
        if web_err:
            logger.warning(f"Web search error: {web_err}")

        # Fallback: web empty → try RAG
        if not result.web_results:
            logger.info("Web returned no results, falling back to RAG")
            result.rag_results = await retriever.search(
                query=search_query, session=db_session, top_k=settings.RAG_TOP_K,
            )
            result.rag_results = _filter_rag_results(result.rag_results)
            if result.rag_results:
                result.final_intent = "web→rag"

    elif intent == "both":
        rag_task = retriever.search(
            query=search_query, session=db_session, top_k=settings.RAG_TOP_K,
        )
        web_task = _web_search(search_query, language=language)
        result.rag_results, (result.web_results, web_err) = await asyncio.gather(
            rag_task, web_task,
        )
        if web_err:
            logger.warning(f"Web search error: {web_err}")
        result.rag_results = _filter_rag_results(result.rag_results)

    elif intent == "spending":
        from app.chat import data_tools
        result.tool_context = await data_tools.query_spending(search_query, db_session)
        result.final_intent = "spending"

    elif intent == "inventory":
        from app.chat import data_tools
        result.tool_context = await data_tools.query_inventory(search_query, db_session)
        result.final_intent = "inventory"

    # else: "direct" - no search

    # Fetch full page content for web results
    if result.web_results:
        await content_fetcher.fetch_content_for_results(result.web_results)

    return result


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

    # Summarize older messages if history is long
    history = await history_manager.prepare_history(history)

    # 2. Classify intent (structured JSON output)
    classified = await intent_classifier.classify_intent(message, history)
    intent = classified.intent
    search_query = classified.query or message

    # Detect language early - needed for web search language and LLM prompt
    lang = _detect_language(message)

    # 3. Execute search with fallback chain
    search = await _execute_search(
        intent=intent,
        search_query=search_query,
        confidence=classified.confidence,
        db_session=db_session,
        language=lang,
    )

    # 4. Build context from search results
    context_parts = []

    if search.tool_context:
        context_parts.append(search.tool_context)

    if search.weather_data or search.forecast_data:
        context_parts.append(
            _format_weather_context(search.weather_data, search.forecast_data)
        )
    if search.rag_results:
        context_parts.append(
            "=== OSOBISTA BAZA WIEDZY ===\n" + _format_rag_context(search.rag_results)
        )
    if search.web_results:
        context_parts.append(
            "=== WYNIKI Z INTERNETU ===\n" + _format_web_context(search.web_results)
        )

    context = "\n\n".join(context_parts)

    # If search was performed but returned no results, inform the LLM
    if not context and intent != "direct":
        if intent == "weather":
            context = "BRAK DANYCH POGODOWYCH - nie udało się pobrać pogody z OpenWeatherMap."
        elif intent == "spending":
            context = "BRAK DANYCH O WYDATKACH - nie znaleziono danych spełniających kryteria."
        elif intent == "inventory":
            context = "BRAK DANYCH O SPIŻARNI - spiżarnia jest pusta lub nie znaleziono pasujących produktów."
        elif intent in ("rag", "both"):
            context = "BRAK WYNIKÓW WYSZUKIWANIA - nie znaleziono pasujących danych w bazie wiedzy ani w internecie."
        elif intent == "web":
            context = "BRAK WYNIKÓW - wyszukiwanie internetowe nie zwróciło wyników."
        else:
            context = "BRAK WYNIKÓW - nie znaleziono pasujących danych."

    # 5. Build LLM message history
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
            search_type=search.final_intent,
            model_used=model,
            processing_time_sec=round(time.time() - start_time, 2),
        )

    # 7. Extract sources
    sources = _extract_sources(search.rag_results, search.web_results)

    return ChatResponse(
        answer=response.strip(),
        sources=sources,
        search_type=search.final_intent,
        search_query=search_query if intent != "direct" else None,
        model_used=model,
        processing_time_sec=round(time.time() - start_time, 2),
    )
