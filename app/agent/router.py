"""Agent Tool Router with retry logic, fallback, and execution dispatch."""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, Awaitable
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.agent.tools import (
    TOOL_DEFINITIONS,
    TOOL_NAMES,
    ToolCall,
    ToolCallResult,
    ToolName,
    validate_tool_call,
    validate_multi_tool_call,
    MultiToolCallResult,
    MAX_TOOLS_IN_CHAIN,
    format_tool_descriptions,
    AnswerDirectlyArgs,
    AskClarificationArgs,
)
from app.agent.validator import (
    SecurityValidator,
    sanitize_url,
    InjectionCheckResult,
)
from app.ollama_client import post_chat
from app.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT_TEMPLATE = """\
Jesteś asystentem osobistego systemu zarządzania wiedzą (Second Brain).
Na podstawie wiadomości użytkownika wybierz narzędzie(a) do wywołania i podaj argumenty.

Dostępne narzędzia:
{tool_descriptions}

═══════════════════════════════════════════════════════════════════════════════
FORMATY ODPOWIEDZI:
═══════════════════════════════════════════════════════════════════════════════

### FORMAT A: Pojedyncze narzędzie (najczęstszy):
{{"tool": "nazwa_narzędzia", "arguments": {{"param1": "wartość1"}}, "confidence": 0.85}}

### FORMAT B: Wiele narzędzi (gdy użytkownik chce kilka rzeczy naraz):
{{"tools": [
    {{"tool": "summarize_url", "arguments": {{"url": "https://..."}}}},
    {{"tool": "create_bookmark", "arguments": {{"url": "https://..."}}}}
], "confidence": 0.9}}

⚠️ WAŻNE dla multi-tool:
- Max 3 narzędzia w jednym żądaniu
- Tylko ACTION tools (create_note, create_bookmark, summarize_url, list_recent) - NIE search/get tools
- Narzędzia wykonują się po kolei - wynik pierwszego może być użyty przez drugie
- Użyj gdy polecenie zawiera "i", "oraz", "a potem", "również"

⚠️ CONFIDENCE JEST OBOWIĄZKOWE - BEZ TEGO POLA ODPOWIEDŹ JEST NIEPRAWIDŁOWA!

CONFIDENCE (0.0-1.0):
- 0.9-1.0: Pewny - jasne polecenie z wszystkimi parametrami, np. "Zanotuj: spotkanie jutro o 10"
- 0.7-0.9: Dość pewny - intencja jasna, parametry z kontekstu, np. "Jaka pogoda?" (domyślne miasto)
- 0.5-0.7: Niepewny - muszę zgadywać, brakuje kluczowych info → rozważ ask_clarification
- <0.5: Bardzo niepewny → ZAWSZE użyj ask_clarification

═══════════════════════════════════════════════════════════════════════════════
PRZYKŁADY (ZAWSZE WZORUJ SIĘ NA TYCH FORMATACH):
═══════════════════════════════════════════════════════════════════════════════

### Wysokie confidence (0.9+) - jasne polecenie:
User: "Zanotuj: kupić mleko i chleb"
→ {{"tool":"create_note","arguments":{{"title":"Lista zakupów","content":"kupić mleko i chleb"}},"confidence":0.95}}

User: "Cześć!"
→ {{"tool":"answer_directly","arguments":{{"text":"Cześć! W czym mogę pomóc?"}},"confidence":0.95}}

User: "Podsumuj https://example.com/article"
→ {{"tool":"summarize_url","arguments":{{"url":"https://example.com/article"}},"confidence":0.95}}

### Średnie confidence (0.7-0.9) - intencja jasna, domyślne parametry:
User: "Jaka pogoda?"
→ {{"tool":"get_weather","arguments":{{}},"confidence":0.8}}

User: "Co jadłem wczoraj?"
→ {{"tool":"get_spending","arguments":{{"time_period":"wczoraj"}},"confidence":0.85}}

### ⚠️ NISKIE CONFIDENCE (<0.6) → UŻYJ ask_clarification:
User: "Zapisz to"
→ {{"tool":"ask_clarification","arguments":{{"question":"Co chcesz zapisać?","options":["Nową notatkę","Link/zakładkę","Poprzedni wynik"]}},"confidence":0.9}}

User: "Pokaż ostatnie" (bez typu)
→ {{"tool":"ask_clarification","arguments":{{"question":"Jakiego typu elementy pokazać?","options":["Notatki","Paragony","Zakładki","Artykuły"]}},"confidence":0.9}}

User: "Pokaż ostatnie notatki" (typ podany)
→ {{"tool":"list_recent","arguments":{{"content_type":"notes","limit":5}},"confidence":0.9}}

User: "Szukaj" (samo słowo bez tematu)
→ {{"tool":"ask_clarification","arguments":{{"question":"Czego szukasz?","options":["W mojej bazie wiedzy","W internecie","Wszędzie"]}},"confidence":0.9}}

User: "Znajdź coś o AI" (jest temat)
→ {{"tool":"search_knowledge","arguments":{{"query":"AI"}},"confidence":0.85}}

User: "Zrób coś z tym linkiem"
→ {{"tool":"ask_clarification","arguments":{{"question":"Co zrobić z linkiem?","options":["Podsumować artykuł","Zapisać jako zakładkę","Oba"]}},"confidence":0.9}}

### Z kontekstem [TOOL_RESULT] - użyj treści, NIE pytaj:
Historia: [TOOL_RESULT: summarize_url]
Artykuł o trendach AI w 2026...
User: "Zapisz to jako notatkę"
→ {{"tool":"create_note","arguments":{{"title":"Trendy AI 2026","content":"Artykuł o trendach AI w 2026..."}},"confidence":0.9}}

### ⚡ MULTI-TOOL - gdy użytkownik chce kilka rzeczy naraz:
User: "Podsumuj ten artykuł i zapisz jako zakładkę: https://example.com/ai"
→ {{"tools":[
    {{"tool":"summarize_url","arguments":{{"url":"https://example.com/ai"}}}},
    {{"tool":"create_bookmark","arguments":{{"url":"https://example.com/ai"}}}}
],"confidence":0.9}}

User: "Pokaż ostatnie notatki i paragony"
→ {{"tools":[
    {{"tool":"list_recent","arguments":{{"content_type":"notes","limit":5}}}},
    {{"tool":"list_recent","arguments":{{"content_type":"receipts","limit":5}}}}
],"confidence":0.9}}

### 🗂️ ORGANIZACJA NOTATEK:
User: "Posprzątaj notatki" / "Raport notatek" / "Stan notatek"
→ {{"tool":"organize_notes","arguments":{{"action":"report"}},"confidence":0.9}}

User: "Otaguj moje notatki" / "Dodaj tagi do notatek"
→ {{"tool":"organize_notes","arguments":{{"action":"auto_tag","dry_run":false}},"confidence":0.9}}

User: "Zaproponuj tagi" / "Jakie tagi pasują do notatek?"
→ {{"tool":"organize_notes","arguments":{{"action":"auto_tag","dry_run":true}},"confidence":0.9}}

User: "Znajdź duplikaty w notatkach" / "Czy mam powtórzone notatki?"
→ {{"tool":"organize_notes","arguments":{{"action":"find_duplicates"}},"confidence":0.9}}

═══════════════════════════════════════════════════════════════════════════════
ZASADY WYBORU:
═══════════════════════════════════════════════════════════════════════════════

WYKORZYSTANIE [TOOL_RESULT]:
- Jeśli widzisz [TOOL_RESULT: nazwa] w historii, to jest wynik poprzedniej operacji
- UŻYJ tej treści jako argument (nie pisz "to" ani "powyższe")
- Z [TOOL_RESULT] w historii → confidence 0.9, NIE używaj ask_clarification

KIEDY ask_clarification (zamiast zgadywania):
1. "Zapisz/zanotuj to" BEZ [TOOL_RESULT] w historii
2. "Pokaż ostatnie" bez typu (notatki? paragony? zakładki?)
3. "Szukaj" bez zapytania
4. Zaimki "to", "tego", "tamto" bez kontekstu w historii
5. Gdy confidence < 0.6 - lepiej zapytać niż zgadnąć źle

WYBÓR NARZĘDZIA:
- URL + streszczenie → summarize_url
- URL + zapisanie → create_bookmark
- Osobiste dane (notatki, co czytałem) → search_knowledge
- Aktualne informacje z internetu → search_web
- Powitania, smalltalk, matematyka → answer_directly
- Porządkowanie/organizacja notatek → organize_notes

KIEDY MULTI-TOOL (format B):
- "Podsumuj i zapisz" → summarize_url + create_bookmark
- "Pokaż X i Y" → list_recent(X) + list_recent(Y)
- "Zrób A, a potem B" → tool_A + tool_B
- Słowa kluczowe: "i", "oraz", "a także", "również", "potem"
- NIE używaj multi-tool dla: search_*, get_*, answer_directly

WAŻNE dla create_note:
- "title" = krótki nagłówek (3-8 słów)
- "content" = pełna treść, ZAWSZE wymagane (nie puste "to")

Zawsze odpowiadaj TYLKO JSON. ZAWSZE dodaj pole confidence.
{profile_section}"""


# Profile section template
PROFILE_SECTION_TEMPLATE = """
═══════════════════════════════════════════════════════════════════════════════
PROFIL UŻYTKOWNIKA:
═══════════════════════════════════════════════════════════════════════════════
- Domyślne miasto: {default_city}
- Strefa czasowa: {timezone}
- Ulubione sklepy: {favorite_stores}

Używaj tych informacji jako domyślnych wartości gdy użytkownik ich nie poda.
Np. "Jaka pogoda?" → użyj domyślnego miasta bez pytania."""


def get_system_prompt(user_profile: Optional[dict] = None) -> str:
    """Get the system prompt with tool descriptions.

    Args:
        user_profile: Optional dict with profile data:
            - default_city: str
            - timezone: str
            - favorite_stores: list[str]
    """
    profile_section = ""
    if user_profile:
        favorite_stores = user_profile.get("favorite_stores") or []
        stores_str = ", ".join(favorite_stores) if favorite_stores else "nie określono"
        profile_section = PROFILE_SECTION_TEMPLATE.format(
            default_city=user_profile.get("default_city", "Kraków"),
            timezone=user_profile.get("timezone", "Europe/Warsaw"),
            favorite_stores=stores_str,
        )

    return SYSTEM_PROMPT_TEMPLATE.format(
        tool_descriptions=format_tool_descriptions(),
        profile_section=profile_section,
    )


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class AgentCallLog:
    """Log entry for agent tool call (for DB persistence)."""

    id: UUID = field(default_factory=uuid4)
    user_input: str = ""
    sanitized_input: str = ""
    model_used: str = ""
    raw_response: str = ""
    parsed_tool: Optional[str] = None
    parsed_arguments: Optional[dict] = None
    validation_success: bool = False
    validation_error: Optional[str] = None
    execution_success: bool = False
    execution_error: Optional[str] = None
    execution_result: Optional[Any] = None
    confidence: Optional[float] = None  # LLM confidence score (0.0-1.0)
    retry_count: int = 0
    total_time_ms: int = 0
    injection_risk: str = "none"
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        """Convert to dict for DB insertion."""
        return {
            "id": str(self.id),
            "user_input": self.user_input,
            "sanitized_input": self.sanitized_input,
            "model_used": self.model_used,
            "raw_response": self.raw_response[:2000] if self.raw_response else None,
            "parsed_tool": self.parsed_tool,
            "parsed_arguments": self.parsed_arguments,
            "validation_success": self.validation_success,
            "validation_error": self.validation_error,
            "execution_success": self.execution_success,
            "execution_error": self.execution_error,
            "confidence": self.confidence,
            "retry_count": self.retry_count,
            "total_time_ms": self.total_time_ms,
            "injection_risk": self.injection_risk,
            "created_at": self.created_at,
        }


@dataclass
class AgentResponse:
    """Final response from agent router."""

    success: bool
    tool: Optional[str] = None
    arguments: Optional[dict] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    log: Optional[AgentCallLog] = None
    warnings: list[str] = field(default_factory=list)
    # Multi-tool support
    is_multi: bool = False
    tools: list[str] = field(default_factory=list)
    arguments_list: list[dict] = field(default_factory=list)
    validated_args_list: list = field(default_factory=list)  # List of Pydantic models


# Tool executor type
ToolExecutor = Callable[[str, BaseModel], Awaitable[Any]]


# =============================================================================
# Agent Router
# =============================================================================


class AgentRouter:
    """Routes user input to appropriate tools via LLM.

    Features:
    - Input validation and sanitization
    - Prompt injection detection
    - LLM tool selection with retry logic
    - Pydantic argument validation
    - Tool execution dispatch
    - Comprehensive logging
    """

    def __init__(
        self,
        model: Optional[str] = None,
        max_retries: int = 2,
        retry_temperature: float = 0.0,
        fallback_to_direct: bool = True,
        validate_urls: bool = True,
        log_calls: bool = True,
    ):
        """Initialize agent router.

        Args:
            model: Ollama model name (default: settings.CLASSIFIER_MODEL)
            max_retries: Max retries on parse failure
            retry_temperature: Temperature for retry attempts
            fallback_to_direct: Fall back to answer_directly on failure
            validate_urls: Validate URLs in summarize_url/create_bookmark
            log_calls: Enable call logging
        """
        self.model = model or getattr(settings, "CLASSIFIER_MODEL", "qwen2.5:7b")
        self.max_retries = max_retries
        self.retry_temperature = retry_temperature
        self.fallback_to_direct = fallback_to_direct
        self.validate_urls = validate_urls
        self.log_calls = log_calls

        self.security = SecurityValidator(
            max_input_length=10000,
            block_high_risk_injection=True,
            log_suspicious=True,
        )

        # Base system prompt (without profile)
        self.system_prompt = get_system_prompt()

        # Tool executors registry
        self._executors: dict[str, ToolExecutor] = {}

    def register_executor(self, tool_name: str, executor: ToolExecutor) -> None:
        """Register a tool executor function.

        Args:
            tool_name: Tool name (must be in TOOL_NAMES)
            executor: Async function(tool_name, validated_args) -> result
        """
        if tool_name not in TOOL_NAMES:
            raise ValueError(f"Unknown tool: {tool_name}")
        self._executors[tool_name] = executor

    def register_executors(self, executors: dict[str, ToolExecutor]) -> None:
        """Register multiple executors at once."""
        for name, executor in executors.items():
            self.register_executor(name, executor)

    async def process(
        self,
        user_input: str,
        conversation_history: Optional[list[dict]] = None,
        user_profile: Optional[dict] = None,
    ) -> AgentResponse:
        """Process user input and route to appropriate tool(s).

        Supports both single-tool and multi-tool requests.

        Args:
            user_input: Raw user message
            conversation_history: Optional recent messages [{role, content}, ...]
                                  for context awareness (e.g., "to", "tego")
            user_profile: Optional user profile dict for personalization:
                - default_city: str
                - timezone: str
                - favorite_stores: list[str]

        Returns:
            AgentResponse with tool result or error
        """
        start_time = time.time()
        log = AgentCallLog(user_input=user_input, model_used=self.model)
        warnings: list[str] = []

        # 1. Validate input
        validation = self.security.validate_input(user_input)
        log.sanitized_input = validation.sanitized_input
        log.injection_risk = validation.injection_check.risk_level

        if not validation.is_valid:
            log.validation_error = "; ".join(validation.errors)
            log.total_time_ms = int((time.time() - start_time) * 1000)
            return AgentResponse(
                success=False,
                error=validation.errors[0],
                log=log if self.log_calls else None,
                warnings=validation.warnings,
            )

        warnings.extend(validation.warnings)

        # 2. Call LLM with retries
        tool_result = await self._call_llm_with_retry(
            validation.sanitized_input, log, conversation_history, user_profile
        )

        if not tool_result.success:
            # Fallback to answer_directly
            if self.fallback_to_direct:
                log.parsed_tool = "answer_directly"
                log.validation_success = True
                warnings.append(f"Fallback do answer_directly: {tool_result.error}")

                return AgentResponse(
                    success=True,
                    tool="answer_directly",
                    arguments={"text": "Nie mogę przetworzyć tego zapytania."},
                    result=None,
                    log=log if self.log_calls else None,
                    warnings=warnings,
                )

            log.total_time_ms = int((time.time() - start_time) * 1000)
            return AgentResponse(
                success=False,
                error=tool_result.error,
                log=log if self.log_calls else None,
                warnings=warnings,
            )

        # 3. Handle multi-tool vs single-tool
        if tool_result.is_multi:
            # Multi-tool: return all tools for external execution
            tool_names = [tc.tool.value for tc in tool_result.tool_calls]
            args_list = [
                args.model_dump() if args else {}
                for args in tool_result.validated_args_list
            ]

            log.parsed_tool = ",".join(tool_names)
            log.parsed_arguments = {"tools": args_list}
            log.validation_success = True
            log.total_time_ms = int((time.time() - start_time) * 1000)

            logger.info(f"Multi-tool request: {tool_names}")

            return AgentResponse(
                success=True,
                # For backwards compatibility, first tool goes in singular fields
                tool=tool_names[0] if tool_names else None,
                arguments=args_list[0] if args_list else None,
                result=None,  # Not executed here
                log=log if self.log_calls else None,
                warnings=warnings,
                # Multi-tool specific fields
                is_multi=True,
                tools=tool_names,
                arguments_list=args_list,
                validated_args_list=tool_result.validated_args_list,
            )

        # Single tool handling (original logic)
        tool_call = tool_result.tool_calls[0]
        validated_args = tool_result.validated_args_list[0]
        tool_name = tool_call.tool.value

        # 4. Additional URL validation for url-based tools
        if self.validate_urls and tool_name in ("summarize_url", "create_bookmark"):
            url = getattr(validated_args, "url", None)
            if url:
                url_check = sanitize_url(url)
                if not url_check.is_safe:
                    log.validation_error = url_check.error
                    log.total_time_ms = int((time.time() - start_time) * 1000)
                    return AgentResponse(
                        success=False,
                        error=f"Nieprawidłowy URL: {url_check.error}",
                        log=log if self.log_calls else None,
                        warnings=warnings,
                    )
                # Update URL with sanitized version
                validated_args.url = url_check.sanitized_url

        log.parsed_tool = tool_name
        log.parsed_arguments = validated_args.model_dump() if validated_args else None
        log.validation_success = True

        # 5. Execute tool
        result = await self._execute_tool(tool_name, validated_args, log)

        log.total_time_ms = int((time.time() - start_time) * 1000)

        return AgentResponse(
            success=log.execution_success,
            tool=tool_name,
            arguments=log.parsed_arguments,
            result=result,
            error=log.execution_error,
            log=log if self.log_calls else None,
            warnings=warnings,
        )

    async def _call_llm_with_retry(
        self,
        user_input: str,
        log: AgentCallLog,
        conversation_history: Optional[list[dict]] = None,
        user_profile: Optional[dict] = None,
    ) -> MultiToolCallResult:
        """Call LLM and parse response with retry logic.

        Supports both single-tool and multi-tool responses.

        Args:
            user_input: Sanitized user input
            log: Call log to update
            conversation_history: Optional recent messages for context
            user_profile: Optional user profile for personalization

        Returns:
            MultiToolCallResult with parsed tool call(s) or error
        """
        last_error: Optional[str] = None
        temperature = 0.0

        # Generate system prompt with profile if available
        system_prompt = get_system_prompt(user_profile) if user_profile else self.system_prompt

        for attempt in range(self.max_retries + 1):
            log.retry_count = attempt

            # Build messages with conversation context
            messages = [{"role": "system", "content": system_prompt}]

            # Add conversation history for context (limit to last 4 messages)
            if conversation_history:
                for msg in conversation_history[-4:]:
                    messages.append({
                        "role": msg.get("role", "user"),
                        "content": msg.get("content", "")[:1500],  # Truncate long messages
                    })

            # Add current user input
            messages.append({"role": "user", "content": user_input})

            response, error = await post_chat(
                model=self.model,
                messages=messages,
                options={"temperature": temperature, "num_predict": 500},  # More tokens for multi-tool
                format="json",
                timeout=60.0,
            )

            if error:
                last_error = f"Ollama error: {error}"
                logger.warning(f"LLM call failed (attempt {attempt + 1}): {error}")
                temperature = self.retry_temperature
                continue

            log.raw_response = response

            # Parse JSON
            parsed = self._parse_llm_response(response)
            if parsed is None:
                last_error = "Nie można sparsować odpowiedzi JSON"
                logger.warning(f"JSON parse failed (attempt {attempt + 1}): {response[:200]}")
                temperature = self.retry_temperature
                continue

            # Extract confidence from response
            confidence = parsed.get("confidence")
            confidence_missing = confidence is None
            if confidence is not None:
                try:
                    confidence = float(confidence)
                    confidence = max(0.0, min(1.0, confidence))  # Clamp to 0.0-1.0
                    log.confidence = confidence
                except (ValueError, TypeError):
                    confidence = None
                    confidence_missing = True

            # Validate tool call(s) - handles both single and multi-tool format
            result = validate_multi_tool_call(parsed)
            if not result.success:
                last_error = result.error
                logger.warning(f"Validation failed (attempt {attempt + 1}): {result.error}")
                temperature = self.retry_temperature
                continue

            # For multi-tool, skip auto-clarification (user was explicit about wanting multiple tools)
            if result.is_multi:
                logger.info(f"Multi-tool request: {[tc.tool.value for tc in result.tool_calls]}")
                return result

            # For single-tool, apply auto-clarification logic
            tool_call = result.tool_calls[0] if result.tool_calls else None
            tool_name = tool_call.tool.value if tool_call else None
            args = result.validated_args_list[0] if result.validated_args_list else None
            should_clarify = False
            clarify_reason = ""

            # Skip clarification check for these tools (they're safe to execute)
            safe_tools = {"answer_directly", "ask_clarification", "get_weather"}

            if tool_name and tool_name not in safe_tools:
                # Case 1: Explicit low confidence
                if confidence is not None and confidence < settings.AGENT_CONFIDENCE_THRESHOLD:
                    should_clarify = True
                    clarify_reason = f"low confidence ({confidence:.2f})"

                # Case 2: Missing confidence for ambiguous-prone tools
                # These tools often fail without enough context
                ambiguous_tools = {"create_note", "create_bookmark", "list_recent"}
                if confidence_missing and tool_name in ambiguous_tools:
                    # Check if there's [TOOL_RESULT] in conversation that provides context
                    has_tool_result = False
                    if conversation_history:
                        for msg in conversation_history[-4:]:
                            if "[TOOL_RESULT:" in msg.get("content", ""):
                                has_tool_result = True
                                break

                    # Only clarify if no context available
                    if not has_tool_result:
                        # Check if user input is very short (likely ambiguous)
                        if len(user_input.strip()) < 30:
                            should_clarify = True
                            clarify_reason = f"missing confidence + short input for {tool_name}"
                            log.confidence = 0.5  # Mark as uncertain

                # Case 3: Search tools with trivial/echo query
                # If query is exactly the same as input, model didn't extract real topic
                if tool_name in ("search_knowledge", "search_web") and args:
                    query = getattr(args, "query", None)
                    if query:
                        input_lower = user_input.lower().strip()
                        query_lower = query.lower().strip()
                        # Check if query is just echoed input (exact match) or too short
                        # Note: query being PART of input is fine (extraction is working)
                        is_exact_echo = query_lower == input_lower
                        is_trivial = len(query_lower) < 4  # Very short queries like "ai" are OK
                        is_search_command = input_lower in ("szukaj", "wyszukaj", "znajdź", "search", "find")
                        if (is_exact_echo or is_search_command) and len(input_lower) < 15:
                            should_clarify = True
                            clarify_reason = f"trivial search query '{query}'"
                            log.confidence = 0.5

                # Case 4: list_recent without explicit type in short input
                if tool_name == "list_recent" and len(user_input.strip()) < 20:
                    # Check if user specified a type explicitly
                    input_lower = user_input.lower()
                    explicit_types = ["notat", "paragony", "receipt", "zakładk", "bookmark", "artykuł"]
                    has_explicit_type = any(t in input_lower for t in explicit_types)
                    if not has_explicit_type:
                        should_clarify = True
                        clarify_reason = "list_recent without explicit type"
                        log.confidence = 0.5

            if should_clarify and tool_call:
                logger.info(
                    f"Auto-clarification triggered ({clarify_reason}), "
                    f"converting '{tool_name}' to ask_clarification"
                )
                # Create ask_clarification fallback
                original_tool = tool_name or "unknown"

                # Generate contextual question based on tool
                question_map = {
                    "create_note": "Co chcesz zanotować?",
                    "create_bookmark": "Jaki link chcesz zapisać?",
                    "list_recent": "Jakiego typu elementy pokazać?",
                    "search_knowledge": "Czego szukasz w swojej bazie wiedzy?",
                    "search_web": "Czego szukasz w internecie?",
                }
                question = question_map.get(original_tool, f"Czy chodziło Ci o '{original_tool}'?")

                options_map = {
                    "create_note": None,  # Free text is better for notes
                    "create_bookmark": None,
                    "list_recent": ["Notatki", "Paragony", "Zakładki", "Artykuły"],
                    "search_knowledge": None,
                    "search_web": None,
                }
                options = options_map.get(original_tool, ["Tak, wykonaj", "Nie, chcę coś innego"])

                clarification_call = ToolCall(
                    tool=ToolName.ASK_CLARIFICATION,
                    arguments={
                        "question": question,
                        **({"options": options} if options else {}),
                        "context": f"Wykryto: {original_tool}" if confidence_missing else f"Pewność: {confidence:.0%}",
                    }
                )
                clarification_args = AskClarificationArgs.model_validate(clarification_call.arguments)
                return MultiToolCallResult(
                    success=True,
                    is_multi=False,
                    tool_calls=[clarification_call],
                    validated_args_list=[clarification_args],
                )

            return result

        return MultiToolCallResult(
            success=False,
            error=last_error or "Nieznany błąd po wszystkich próbach",
        )

    def _parse_llm_response(self, response: str) -> Optional[dict]:
        """Parse JSON from LLM response.

        Handles:
        - Clean JSON
        - JSON in markdown code blocks
        - <think> tags from reasoning models
        """
        if not response:
            return None

        text = response.strip()

        # Remove <think>...</think> tags (deepseek-r1, etc.)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # Remove markdown code fences
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 3:
                inner = parts[1]
                if inner.startswith("json"):
                    inner = inner[4:]
                text = inner.strip()

        try:
            data = json.loads(text)
            if isinstance(data, dict) and "tool" in data:
                return data
            return None
        except (json.JSONDecodeError, ValueError):
            return None

    async def _execute_tool(
        self, tool_name: str, args: BaseModel, log: AgentCallLog
    ) -> Optional[Any]:
        """Execute tool with registered executor.

        Args:
            tool_name: Tool to execute
            args: Validated arguments
            log: Call log to update

        Returns:
            Tool execution result or None
        """
        executor = self._executors.get(tool_name)

        if executor is None:
            # No executor registered - return args for external handling
            log.execution_success = True
            log.execution_result = "no_executor"
            return None

        try:
            result = await executor(tool_name, args)
            log.execution_success = True
            log.execution_result = (
                str(result)[:1000] if result is not None else None
            )
            return result
        except Exception as e:
            log.execution_success = False
            log.execution_error = str(e)
            logger.exception(f"Tool execution failed: {tool_name}")
            return None


# =============================================================================
# Default Executors (for answer_directly)
# =============================================================================


async def execute_answer_directly(tool_name: str, args: AnswerDirectlyArgs) -> str:
    """Default executor for answer_directly - just returns the text."""
    return args.text


# =============================================================================
# Factory
# =============================================================================


def create_agent_router(
    model: Optional[str] = None,
    register_default_executors: bool = True,
) -> AgentRouter:
    """Create an AgentRouter with default configuration.

    Args:
        model: Ollama model name
        register_default_executors: Register answer_directly executor

    Returns:
        Configured AgentRouter
    """
    router = AgentRouter(model=model)

    if register_default_executors:
        router.register_executor("answer_directly", execute_answer_directly)

    return router
