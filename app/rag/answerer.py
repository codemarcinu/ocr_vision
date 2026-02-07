"""RAG answer generation - combines retrieval with LLM."""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app import ollama_client
from app.config import settings
from app.rag import retriever

logger = logging.getLogger(__name__)


CONTENT_TYPE_LABELS = {
    "article": "Artykuł",
    "transcription": "Transkrypcja",
    "receipt": "Paragon",
    "note": "Notatka",
    "bookmark": "Zakładka",
}


@dataclass
class SourceRef:
    """Reference to a source document."""

    content_type: str
    content_id: str
    title: str
    score: float

    @property
    def label(self) -> str:
        type_label = CONTENT_TYPE_LABELS.get(self.content_type, self.content_type)
        return f"[{type_label}] {self.title}"


@dataclass
class AskResult:
    """Result of a RAG query."""

    answer: str
    sources: list[SourceRef] = field(default_factory=list)
    model_used: str = ""
    processing_time_sec: float = 0.0
    chunks_found: int = 0
    judge_verdict: str = ""


RAG_PROMPT_PL = """Na podstawie poniższego kontekstu z osobistej bazy wiedzy, odpowiedz na pytanie użytkownika.

ZASADY:
- Odpowiadaj TYLKO na podstawie podanego kontekstu
- Jeśli kontekst nie zawiera odpowiedzi, powiedz to wprost
- Odpowiadaj zwięźle i konkretnie
- Cytuj źródła w nawiasach kwadratowych, np. [Paragon: Biedronka 2026-01-15]
- Jeśli pytanie dotyczy wydatków/cen, podaj konkretne liczby

KONTEKST:
{context}

PYTANIE: {question}

ODPOWIEDŹ:"""


RAG_PROMPT_EN = """Based on the following context from a personal knowledge base, answer the user's question.

RULES:
- Answer ONLY based on the provided context
- If the context doesn't contain the answer, say so explicitly
- Be concise and specific
- Cite sources in brackets, e.g. [Article: Title]
- If the question is about spending/prices, provide specific numbers

CONTEXT:
{context}

QUESTION: {question}

ANSWER:"""


JUDGE_PROMPT_PL = """Oceń czy ODPOWIEDŹ jest uzasadniona przez KONTEKST.

KONTEKST:
{context}

ODPOWIEDŹ:
{answer}

Odpowiedz JEDNYM słowem: PASS (zgodna) lub WARN (zawiera informacje spoza kontekstu).
Werdykt:"""


JUDGE_PROMPT_EN = """Evaluate if ANSWER is supported by CONTEXT.

CONTEXT:
{context}

ANSWER:
{answer}

Reply with ONE word: PASS (consistent) or WARN (contains info beyond context).
Verdict:"""


async def _judge_answer(answer: str, context: str, lang: str, model: str) -> str:
    """Weryfikuj odpowiedź RAG pod kątem halucynacji."""
    prompt_template = JUDGE_PROMPT_PL if lang == "pl" else JUDGE_PROMPT_EN
    prompt = prompt_template.format(context=context, answer=answer)

    response, error = await ollama_client.post_generate(
        model=model,
        prompt=prompt,
        options={"temperature": 0.0, "num_predict": 10},
        timeout=30.0,
        keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
    )

    if error:
        logger.warning(f"RAG judge error: {error}")
        return "pass"

    verdict = response.strip().lower()
    if "warn" in verdict:
        logger.info("RAG judge: WARN — odpowiedź może zawierać halucynacje")
        return "warn"
    return "pass"


def _detect_language(text: str) -> str:
    """Simple Polish vs English detection."""
    polish_chars = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
    polish_words = [" i ", " w ", " się ", " na ", " do ", " z ", " co ", " jak ", " ile "]

    indicators = sum(1 for c in text if c in polish_chars)
    indicators += sum(1 for w in polish_words if w in text.lower())

    return "pl" if indicators >= 2 else "en"


def _build_context(results: list[retriever.SearchResult]) -> str:
    """Build context string from search results."""
    context_parts = []

    for r in results:
        # Build source label
        meta = r.metadata
        title = meta.get("title", "")
        store = meta.get("store", "")
        date = meta.get("date", "")

        type_label = CONTENT_TYPE_LABELS.get(r.content_type, r.content_type)

        if r.content_type == "receipt":
            source = f"[{type_label}: {store} {date}]"
        elif title:
            source = f"[{type_label}: {title}]"
        else:
            source = f"[{type_label}]"

        context_parts.append(f"{source}\n{r.text_chunk}")

    return "\n\n---\n\n".join(context_parts)


def _extract_source_title(result: retriever.SearchResult) -> str:
    """Extract a human-readable title from a search result."""
    meta = result.metadata

    if result.content_type == "receipt":
        store = meta.get("store", "nieznany")
        date = meta.get("date", "")
        return f"{store} {date}".strip()

    return meta.get("title", result.content_id[:8])


async def ask(
    question: str,
    session: AsyncSession,
    top_k: int = None,
    content_types: Optional[list[str]] = None,
) -> AskResult:
    """Ask a question to the knowledge base.

    Args:
        question: User's question
        session: Database session
        top_k: Number of chunks to retrieve
        content_types: Filter by content types

    Returns:
        AskResult with answer, sources, and metadata.
    """
    start_time = time.time()
    model = settings.ASK_MODEL or settings.CLASSIFIER_MODEL

    # Search for relevant chunks
    results = await retriever.search(
        query=question,
        session=session,
        top_k=top_k,
        content_types=content_types,
    )

    if not results:
        return AskResult(
            answer="Nie znalazłem odpowiednich informacji w bazie wiedzy.",
            model_used=model,
            processing_time_sec=round(time.time() - start_time, 2),
            chunks_found=0,
        )

    # Build context from results
    context = _build_context(results)

    # Choose prompt language
    lang = _detect_language(question)
    prompt_template = RAG_PROMPT_PL if lang == "pl" else RAG_PROMPT_EN
    prompt = prompt_template.format(context=context, question=question)

    # Call LLM
    response, error = await ollama_client.post_generate(
        model=model,
        prompt=prompt,
        options={
            "temperature": 0.3,
            "num_predict": 2048,
        },
        timeout=120.0,
        keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
    )

    if error:
        logger.error(f"RAG LLM error: {error}")
        return AskResult(
            answer=f"Błąd generowania odpowiedzi: {error}",
            model_used=model,
            processing_time_sec=round(time.time() - start_time, 2),
            chunks_found=len(results),
        )

    answer_text = response.strip()

    # Opcjonalna walidacja odpowiedzi przez sędziego
    judge_verdict = ""
    if settings.RAG_JUDGE_ENABLED:
        judge_verdict = await _judge_answer(answer_text, context, lang, model)
        if judge_verdict == "warn":
            disclaimer = (
                "\n\n---\n*Uwaga: ta odpowiedź może zawierać informacje wykraczające poza dostarczone źródła.*"
                if lang == "pl" else
                "\n\n---\n*Note: this answer may contain information beyond the provided sources.*"
            )
            answer_text += disclaimer

    # Build unique source references
    seen_sources = set()
    sources = []
    for r in results:
        key = (r.content_type, r.content_id)
        if key not in seen_sources:
            sources.append(SourceRef(
                content_type=r.content_type,
                content_id=r.content_id,
                title=_extract_source_title(r),
                score=r.score,
            ))
            seen_sources.add(key)

    return AskResult(
        answer=answer_text,
        sources=sources,
        model_used=model,
        processing_time_sec=round(time.time() - start_time, 2),
        chunks_found=len(results),
        judge_verdict=judge_verdict,
    )
