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
    format_tool_descriptions,
    AnswerDirectlyArgs,
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
Na podstawie wiadomości użytkownika wybierz JEDNO narzędzie do wywołania i podaj argumenty.

Dostępne narzędzia:
{tool_descriptions}

Odpowiedz WYŁĄCZNIE poprawnym JSON w formacie:
{{"tool": "nazwa_narzędzia", "arguments": {{"param1": "wartość1"}}}}

WAŻNE dla create_note:
- "title" = krótki tytuł/nagłówek (3-8 słów), np. "Lista zakupów", "Spotkanie z Tomkiem"
- "content" = pełna treść notatki, ZAWSZE wymagane, skopiuj tekst użytkownika

Przykłady create_note:
- "Zanotuj: kupić mleko" → {{"tool":"create_note","arguments":{{"title":"Lista zakupów","content":"kupić mleko"}}}}
- "Zapisz że jutro dentysta" → {{"tool":"create_note","arguments":{{"title":"Przypomnienie dentysta","content":"jutro wizyta u dentysty"}}}}

Zasady:
- Wybierz DOKŁADNIE JEDNO narzędzie najlepiej pasujące do zapytania
- Podaj tylko argumenty istotne dla zapytania (pomiń opcjonalne jeśli nie podano)
- Jeśli użytkownik podaje URL i prosi o streszczenie → summarize_url
- Jeśli użytkownik podaje URL i prosi o zapisanie → create_bookmark
- Jeśli pytanie dotyczy osobistych danych (co czytałem, moje notatki) → search_knowledge
- Jeśli pytanie dotyczy aktualnych wiadomości/informacji z internetu → search_web
- answer_directly: powitania (cześć, hej), smalltalk (co u ciebie, co tam), matematyka, wiedza ogólna
- Zawsze odpowiadaj TYLKO JSON, bez dodatkowego tekstu"""


def get_system_prompt() -> str:
    """Get the system prompt with tool descriptions."""
    return SYSTEM_PROMPT_TEMPLATE.format(tool_descriptions=format_tool_descriptions())


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

    async def process(self, user_input: str) -> AgentResponse:
        """Process user input and route to appropriate tool.

        Args:
            user_input: Raw user message

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
            validation.sanitized_input, log
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

        # 3. Additional URL validation for url-based tools
        tool_name = tool_result.tool_call.tool.value
        validated_args = tool_result.validated_args

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

        # 4. Execute tool
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
        self, user_input: str, log: AgentCallLog
    ) -> ToolCallResult:
        """Call LLM and parse response with retry logic.

        Args:
            user_input: Sanitized user input
            log: Call log to update

        Returns:
            ToolCallResult with parsed tool call or error
        """
        last_error: Optional[str] = None
        temperature = 0.0

        for attempt in range(self.max_retries + 1):
            log.retry_count = attempt

            # Call Ollama
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_input},
            ]

            response, error = await post_chat(
                model=self.model,
                messages=messages,
                options={"temperature": temperature, "num_predict": 300},
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

            # Validate tool call
            result = validate_tool_call(parsed)
            if not result.success:
                last_error = result.error
                logger.warning(f"Validation failed (attempt {attempt + 1}): {result.error}")
                temperature = self.retry_temperature
                continue

            return result

        return ToolCallResult(
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
