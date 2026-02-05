"""Tool definitions and Pydantic validation models for agent tool-calling."""

from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Tool Name Enum
# =============================================================================


class ToolName(str, Enum):
    """Valid tool names for the agent."""

    CREATE_NOTE = "create_note"
    SEARCH_KNOWLEDGE = "search_knowledge"
    SEARCH_WEB = "search_web"
    GET_SPENDING = "get_spending"
    GET_INVENTORY = "get_inventory"
    GET_WEATHER = "get_weather"
    SUMMARIZE_URL = "summarize_url"
    LIST_RECENT = "list_recent"
    CREATE_BOOKMARK = "create_bookmark"
    ANSWER_DIRECTLY = "answer_directly"
    ASK_CLARIFICATION = "ask_clarification"


TOOL_NAMES = [t.value for t in ToolName]


# =============================================================================
# Argument Models (Pydantic)
# =============================================================================


class CreateNoteArgs(BaseModel):
    """Arguments for create_note tool."""

    title: str = Field(..., min_length=1, max_length=500, description="Tytuł notatki")
    content: str = Field(..., min_length=1, max_length=50000, description="Treść notatki")
    tags: Optional[list[str]] = Field(default=None, max_length=20, description="Lista tagów")

    @field_validator("title", "content")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, v: Any) -> Optional[list[str]]:
        if v is None:
            return None
        if isinstance(v, str):
            # Handle comma-separated string
            return [t.strip() for t in v.split(",") if t.strip()]
        if isinstance(v, list):
            return [str(t).strip() for t in v if str(t).strip()]
        return None


class SearchKnowledgeArgs(BaseModel):
    """Arguments for search_knowledge tool (RAG)."""

    query: str = Field(..., min_length=1, max_length=1000, description="Zapytanie wyszukiwania")
    content_types: Optional[list[str]] = Field(
        default=None,
        description="Filtr typów: article, note, bookmark, transcription",
    )

    @field_validator("query")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    @field_validator("content_types", mode="before")
    @classmethod
    def normalize_types(cls, v: Any) -> Optional[list[str]]:
        if v is None:
            return None
        valid = {"article", "note", "bookmark", "transcription"}
        if isinstance(v, str):
            types = [t.strip().lower() for t in v.split(",")]
        elif isinstance(v, list):
            types = [str(t).strip().lower() for t in v]
        else:
            return None
        return [t for t in types if t in valid] or None


class SearchWebArgs(BaseModel):
    """Arguments for search_web tool (SearXNG)."""

    query: str = Field(..., min_length=1, max_length=500, description="Zapytanie wyszukiwania")

    @field_validator("query")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class GetSpendingArgs(BaseModel):
    """Arguments for get_spending tool."""

    period: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Okres: 'ten tydzień', 'styczeń', 'ostatnie 30 dni'",
    )
    store: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Nazwa sklepu: 'Biedronka', 'Lidl'",
    )
    category: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Kategoria: 'nabiał', 'mięso'",
    )

    @field_validator("period", "store", "category", mode="before")
    @classmethod
    def strip_or_none(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None


class GetInventoryArgs(BaseModel):
    """Arguments for get_inventory tool (pantry/spiżarnia)."""

    action: Optional[Literal["list", "search", "expiring", "stats"]] = Field(
        default="list",
        description="Typ zapytania",
    )
    query: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Nazwa produktu do wyszukania",
    )

    @field_validator("action", mode="before")
    @classmethod
    def normalize_action(cls, v: Any) -> str:
        if v is None:
            return "list"
        s = str(v).strip().lower()
        return s if s in ("list", "search", "expiring", "stats") else "list"


class GetWeatherArgs(BaseModel):
    """Arguments for get_weather tool."""

    city: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Nazwa miasta",
    )

    @field_validator("city", mode="before")
    @classmethod
    def strip_or_none(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None


class SummarizeUrlArgs(BaseModel):
    """Arguments for summarize_url tool."""

    url: str = Field(..., min_length=10, max_length=2000, description="URL artykułu")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        # Basic URL validation
        if not v.startswith(("http://", "https://")):
            # Try to fix common issues
            if v.startswith("www."):
                v = "https://" + v
            elif "." in v and "/" in v:
                v = "https://" + v
            else:
                raise ValueError("Nieprawidłowy URL - brak protokołu http/https")
        return v


class ListRecentArgs(BaseModel):
    """Arguments for list_recent tool."""

    content_type: str = Field(
        ...,
        description="Typ: receipts, notes, bookmarks, articles, transcriptions",
    )
    limit: Optional[int] = Field(
        default=5,
        ge=1,
        le=50,
        description="Liczba elementów",
    )

    @field_validator("content_type", mode="before")
    @classmethod
    def normalize_type(cls, v: Any) -> str:
        if v is None:
            raise ValueError("content_type jest wymagany")
        s = str(v).strip().lower()
        # Normalize common variations
        mappings = {
            "receipt": "receipts",
            "paragon": "receipts",
            "paragony": "receipts",
            "note": "notes",
            "notatka": "notes",
            "notatki": "notes",
            "bookmark": "bookmarks",
            "zakładka": "bookmarks",
            "zakładki": "bookmarks",
            "article": "articles",
            "artykuł": "articles",
            "artykuły": "articles",
            "transcription": "transcriptions",
            "transkrypcja": "transcriptions",
            "transkrypcje": "transcriptions",
        }
        return mappings.get(s, s)

    @field_validator("limit", mode="before")
    @classmethod
    def parse_limit(cls, v: Any) -> int:
        if v is None:
            return 5
        if isinstance(v, int):
            return max(1, min(v, 50))
        try:
            return max(1, min(int(v), 50))
        except (ValueError, TypeError):
            return 5


class CreateBookmarkArgs(BaseModel):
    """Arguments for create_bookmark tool."""

    url: str = Field(..., min_length=10, max_length=2000, description="URL do zapisania")
    tags: Optional[list[str]] = Field(default=None, max_length=20, description="Lista tagów")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            if v.startswith("www."):
                v = "https://" + v
            elif "." in v:
                v = "https://" + v
            else:
                raise ValueError("Nieprawidłowy URL")
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, v: Any) -> Optional[list[str]]:
        if v is None:
            return None
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        if isinstance(v, list):
            return [str(t).strip() for t in v if str(t).strip()]
        return None


class AnswerDirectlyArgs(BaseModel):
    """Arguments for answer_directly tool."""

    text: str = Field(..., min_length=1, max_length=10000, description="Treść odpowiedzi")

    @field_validator("text")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class AskClarificationArgs(BaseModel):
    """Arguments for ask_clarification tool - ask user for more details."""

    question: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Pytanie do użytkownika",
    )
    options: Optional[list[str]] = Field(
        default=None,
        description="Sugerowane odpowiedzi (max 5)",
    )
    context: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Kontekst dlaczego pytasz",
    )

    @field_validator("question")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    @field_validator("options", mode="before")
    @classmethod
    def limit_options(cls, v: Any) -> Optional[list[str]]:
        if v is None:
            return None
        if isinstance(v, list):
            # Limit to 5 options, each max 50 chars
            return [str(o).strip()[:50] for o in v[:5] if str(o).strip()]
        return None

    @field_validator("context", mode="before")
    @classmethod
    def strip_context(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s[:200] if s else None


# =============================================================================
# Tool Call Model
# =============================================================================


# Union of all argument types
ToolArguments = Union[
    CreateNoteArgs,
    SearchKnowledgeArgs,
    SearchWebArgs,
    GetSpendingArgs,
    GetInventoryArgs,
    GetWeatherArgs,
    SummarizeUrlArgs,
    ListRecentArgs,
    CreateBookmarkArgs,
    AnswerDirectlyArgs,
    AskClarificationArgs,
]

# Mapping from tool name to argument model
TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "create_note": CreateNoteArgs,
    "search_knowledge": SearchKnowledgeArgs,
    "search_web": SearchWebArgs,
    "get_spending": GetSpendingArgs,
    "get_inventory": GetInventoryArgs,
    "get_weather": GetWeatherArgs,
    "summarize_url": SummarizeUrlArgs,
    "list_recent": ListRecentArgs,
    "create_bookmark": CreateBookmarkArgs,
    "answer_directly": AnswerDirectlyArgs,
    "ask_clarification": AskClarificationArgs,
}


class ToolCall(BaseModel):
    """Validated tool call from LLM."""

    tool: ToolName = Field(..., description="Nazwa narzędzia")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Argumenty narzędzia")

    @field_validator("tool", mode="before")
    @classmethod
    def normalize_tool(cls, v: Any) -> str:
        if v is None:
            raise ValueError("tool jest wymagany")
        # Handle ToolName enum
        if isinstance(v, ToolName):
            return v.value
        s = str(v).strip().lower()
        if s not in TOOL_NAMES:
            raise ValueError(f"Nieznane narzędzie: {s}")
        return s


class ToolCallResult(BaseModel):
    """Result of tool call validation."""

    success: bool
    tool_call: Optional[ToolCall] = None
    validated_args: Optional[BaseModel] = None
    error: Optional[str] = None
    raw_response: Optional[str] = None


class MultiToolCallResult(BaseModel):
    """Result of multi-tool call validation."""

    success: bool
    is_multi: bool = False  # True if multiple tools, False if single tool
    tool_calls: list[ToolCall] = []
    validated_args_list: list[BaseModel] = []
    error: Optional[str] = None
    raw_response: Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}


def _fix_create_note_args(args: dict[str, Any]) -> dict[str, Any]:
    """Fix common issues with create_note arguments.

    Handles cases where:
    - content is missing but title contains the actual content
    - content is empty but there's useful info in title
    """
    title = args.get("title", "")
    content = args.get("content", "")

    # If content is empty/missing but title has meaningful text
    if (not content or not str(content).strip()) and title:
        title_str = str(title).strip()
        # If title is long (>50 chars or has multiple lines), it's probably content
        if len(title_str) > 50 or "\n" in title_str or "," in title_str:
            args["content"] = title_str
            # Generate a short title from content
            words = title_str.split()[:5]
            args["title"] = " ".join(words) + ("..." if len(words) < len(title_str.split()) else "")
        else:
            # Just copy title to content
            args["content"] = title_str

    return args


def validate_tool_call(raw_json: dict[str, Any]) -> ToolCallResult:
    """Validate raw JSON from LLM into typed ToolCall with validated arguments.

    Args:
        raw_json: Dict with 'tool' and 'arguments' keys from LLM

    Returns:
        ToolCallResult with validated data or error message
    """
    try:
        # First validate the basic structure
        tool_call = ToolCall.model_validate(raw_json)

        # Get the argument model for this tool
        arg_model = TOOL_ARG_MODELS.get(tool_call.tool.value)
        if arg_model is None:
            return ToolCallResult(
                success=False,
                error=f"Brak modelu argumentów dla: {tool_call.tool}",
                raw_response=str(raw_json),
            )

        # Apply tool-specific fixes before validation
        args = tool_call.arguments.copy()
        if tool_call.tool.value == "create_note":
            args = _fix_create_note_args(args)

        # Validate arguments with the specific model
        validated_args = arg_model.model_validate(args)

        return ToolCallResult(
            success=True,
            tool_call=tool_call,
            validated_args=validated_args,
        )

    except Exception as e:
        return ToolCallResult(
            success=False,
            error=str(e),
            raw_response=str(raw_json),
        )


# =============================================================================
# Tool Definitions (for system prompt)
# =============================================================================

TOOL_DEFINITIONS = [
    {
        "name": "create_note",
        "description": (
            "Utwórz nową notatkę w bazie wiedzy. "
            "Użyj gdy użytkownik chce coś zapisać, zapamiętać, zanotować."
        ),
        "parameters": {
            "title": "Krótki tytuł/nagłówek 3-8 słów (wymagane)",
            "content": "Pełna treść notatki - SKOPIUJ tekst użytkownika (wymagane)",
            "tags": "Lista tagów (opcjonalne)",
        },
        "required": ["title", "content"],
    },
    {
        "name": "search_knowledge",
        "description": (
            "Przeszukaj osobistą bazę wiedzy (artykuły, notatki, zakładki, transkrypcje). "
            "Użyj gdy użytkownik pyta o coś co wcześniej zapisał, przeczytał, obejrzał."
        ),
        "parameters": {
            "query": "Zapytanie do wyszukiwania (wymagane)",
            "content_types": "Filtr typów: article, note, bookmark, transcription (opcjonalne)",
        },
        "required": ["query"],
    },
    {
        "name": "search_web",
        "description": (
            "Wyszukaj informacje w internecie. "
            "Użyj gdy pytanie dotyczy aktualnych wiadomości, bieżących wydarzeń, "
            "informacji których nie ma w osobistej bazie."
        ),
        "parameters": {
            "query": "Zapytanie wyszukiwania (wymagane)",
        },
        "required": ["query"],
    },
    {
        "name": "get_spending",
        "description": (
            "Pobierz dane o wydatkach, zakupach, paragonach. "
            "Użyj gdy użytkownik pyta ile wydał, gdzie kupował, "
            "porównanie wydatków, najdroższe produkty."
        ),
        "parameters": {
            "period": "Okres czasu: 'ten tydzień', 'styczeń', 'ostatnie 30 dni' (opcjonalne)",
            "store": "Nazwa sklepu: 'Biedronka', 'Lidl' (opcjonalne)",
            "category": "Kategoria produktów: 'nabiał', 'mięso' (opcjonalne)",
        },
        "required": [],
    },
    {
        "name": "get_inventory",
        "description": (
            "Sprawdź stan spiżarni/lodówki - jakie produkty są w domu, "
            "co się kończy, co przeterminowane. "
            "Użyj gdy użytkownik pyta o zapasy, produkty w domu."
        ),
        "parameters": {
            "action": "Typ zapytania: list, search, expiring, stats (opcjonalne)",
            "query": "Nazwa produktu do wyszukania (opcjonalne)",
        },
        "required": [],
    },
    {
        "name": "get_weather",
        "description": (
            "Pobierz aktualną pogodę i prognozę. "
            "Użyj gdy użytkownik pyta o pogodę, temperaturę, opady, wiatr."
        ),
        "parameters": {
            "city": "Nazwa miasta (opcjonalne, domyślnie miasto użytkownika)",
        },
        "required": [],
    },
    {
        "name": "summarize_url",
        "description": (
            "Podsumuj artykuł ze strony internetowej pod podanym URL. "
            "Użyj gdy użytkownik podaje link i prosi o streszczenie."
        ),
        "parameters": {
            "url": "Pełny URL artykułu (wymagane)",
        },
        "required": ["url"],
    },
    {
        "name": "list_recent",
        "description": (
            "Wyświetl ostatnio dodane elementy danego typu. "
            "Użyj gdy użytkownik pyta o ostatnie notatki, paragony, zakładki, artykuły."
        ),
        "parameters": {
            "content_type": "Typ: receipts, notes, bookmarks, articles, transcriptions (wymagane)",
            "limit": "Liczba elementów 1-50 (opcjonalne, domyślnie 5)",
        },
        "required": ["content_type"],
    },
    {
        "name": "create_bookmark",
        "description": (
            "Zapisz zakładkę (link do przeczytania później). "
            "Użyj gdy użytkownik chce zapisać link, URL, stronę na później."
        ),
        "parameters": {
            "url": "URL strony do zapisania (wymagane)",
            "tags": "Lista tagów (opcjonalne)",
        },
        "required": ["url"],
    },
    {
        "name": "answer_directly",
        "description": (
            "Odpowiedz bezpośrednio bez użycia narzędzi. "
            "Użyj przy: powitaniach (cześć, hej), smalltalk (co u ciebie, co tam, ok), "
            "prostych pytaniach z wiedzy ogólnej, matematyce, prośbie o opinię."
        ),
        "parameters": {
            "text": "Treść odpowiedzi (wymagane)",
        },
        "required": ["text"],
    },
    {
        "name": "ask_clarification",
        "description": (
            "Dopytaj użytkownika gdy brakuje kluczowych informacji lub intencja jest niejasna. "
            "Użyj gdy: "
            "1) użytkownik mówi 'to', 'tamto', 'tego' bez kontekstu w historii [TOOL_RESULT]; "
            "2) brak wymaganego parametru (np. 'zapisz' bez treści do zapisania); "
            "3) wieloznaczne polecenie (np. 'pokaż ostatnie' - jakiego typu?); "
            "4) niepełna informacja (np. 'wydatki' bez okresu/sklepu gdy kontekst niejasny)."
        ),
        "parameters": {
            "question": "Pytanie do użytkownika (wymagane)",
            "options": "Lista sugerowanych odpowiedzi, max 5 (opcjonalne)",
            "context": "Krótki kontekst dlaczego pytasz (opcjonalne)",
        },
        "required": ["question"],
    },
]


def format_tool_descriptions() -> str:
    """Format tool definitions for system prompt."""
    lines = []
    for i, tool in enumerate(TOOL_DEFINITIONS, 1):
        required = tool.get("required", [])
        params = []
        for k, v in tool["parameters"].items():
            req_marker = " [wymagane]" if k in required else ""
            params.append(f"{k}: {v}{req_marker}")
        params_str = "; ".join(params)
        lines.append(f"{i}. {tool['name']} — {tool['description']}")
        lines.append(f"   Parametry: {params_str}")
    return "\n".join(lines)


# Maximum number of tools in a multi-tool chain
MAX_TOOLS_IN_CHAIN = 3


def validate_multi_tool_call(raw_json: dict[str, Any]) -> MultiToolCallResult:
    """Validate raw JSON from LLM - handles both single tool and multi-tool format.

    Single tool format:
        {"tool": "create_note", "arguments": {...}, "confidence": 0.9}

    Multi-tool format:
        {"tools": [
            {"tool": "summarize_url", "arguments": {"url": "..."}},
            {"tool": "create_bookmark", "arguments": {"url": "..."}}
        ], "confidence": 0.9}

    Args:
        raw_json: Dict from LLM response

    Returns:
        MultiToolCallResult with validated tools or error
    """
    # Check which format we have
    if "tools" in raw_json and isinstance(raw_json["tools"], list):
        # Multi-tool format
        tools_list = raw_json["tools"]

        if len(tools_list) == 0:
            return MultiToolCallResult(
                success=False,
                error="Pusta lista narzędzi",
                raw_response=str(raw_json),
            )

        if len(tools_list) > MAX_TOOLS_IN_CHAIN:
            return MultiToolCallResult(
                success=False,
                error=f"Za dużo narzędzi ({len(tools_list)}), max {MAX_TOOLS_IN_CHAIN}",
                raw_response=str(raw_json),
            )

        validated_calls: list[ToolCall] = []
        validated_args: list[BaseModel] = []

        for i, tool_spec in enumerate(tools_list):
            if not isinstance(tool_spec, dict):
                return MultiToolCallResult(
                    success=False,
                    error=f"Narzędzie #{i+1} nie jest obiektem",
                    raw_response=str(raw_json),
                )

            # Validate single tool call
            result = validate_tool_call(tool_spec)
            if not result.success:
                return MultiToolCallResult(
                    success=False,
                    error=f"Narzędzie #{i+1} ({tool_spec.get('tool', '?')}): {result.error}",
                    raw_response=str(raw_json),
                )

            validated_calls.append(result.tool_call)
            validated_args.append(result.validated_args)

        return MultiToolCallResult(
            success=True,
            is_multi=True,
            tool_calls=validated_calls,
            validated_args_list=validated_args,
        )

    elif "tool" in raw_json:
        # Single tool format (backwards compatible)
        result = validate_tool_call(raw_json)

        if not result.success:
            return MultiToolCallResult(
                success=False,
                error=result.error,
                raw_response=result.raw_response,
            )

        return MultiToolCallResult(
            success=True,
            is_multi=False,
            tool_calls=[result.tool_call],
            validated_args_list=[result.validated_args],
        )

    else:
        return MultiToolCallResult(
            success=False,
            error="Brak 'tool' lub 'tools' w odpowiedzi",
            raw_response=str(raw_json),
        )
