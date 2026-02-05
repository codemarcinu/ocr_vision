#!/usr/bin/env python3
"""Test agent tool-calling capabilities of local Ollama models.

Evaluates whether models can reliably select the correct tool and extract
arguments from natural Polish-language user input.

Usage:
    python scripts/test_agent_tools.py                          # full run, all models
    python scripts/test_agent_tools.py --models qwen2.5:7b      # single model
    python scripts/test_agent_tools.py --test-ids 1 2 3 -v      # subset + verbose
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

MODELS = [
    "qwen2.5:7b",
    "qwen2.5:14b",
    "deepseek-r1:latest",
]


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

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
    },
    {
        "name": "search_knowledge",
        "description": (
            "Przeszukaj osobistą bazę wiedzy (artykuły, notatki, zakładki, transkrypcje). "
            "Użyj gdy użytkownik pyta o coś co wcześniej zapisał, przeczytał, obejrzał."
        ),
        "parameters": {
            "query": "Zapytanie do wyszukiwania (wymagane)",
            "content_types": "Opcjonalny filtr typów: 'article','note','bookmark','transcription' (lista)",
        },
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
    },
    {
        "name": "get_spending",
        "description": (
            "Pobierz dane o wydatkach, zakupach, paragonach. "
            "Użyj gdy użytkownik pyta ile wydał, gdzie kupował, "
            "porównanie wydatków, najdroższe produkty."
        ),
        "parameters": {
            "period": "Okres czasu, np. 'ten tydzień', 'styczeń', 'ostatnie 30 dni' (opcjonalne)",
            "store": "Nazwa sklepu, np. 'Biedronka', 'Lidl' (opcjonalne)",
            "category": "Kategoria produktów, np. 'nabiał', 'mięso' (opcjonalne)",
        },
    },
    {
        "name": "get_inventory",
        "description": (
            "Sprawdź stan spiżarni/lodówki - jakie produkty są w domu, "
            "co się kończy, co przeterminowane. "
            "Użyj gdy użytkownik pyta o zapasy, produkty w domu."
        ),
        "parameters": {
            "action": "Typ zapytania: 'list', 'search', 'expiring', 'stats' (opcjonalne)",
            "query": "Nazwa produktu do wyszukania (opcjonalne)",
        },
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
    },
    {
        "name": "list_recent",
        "description": (
            "Wyświetl ostatnio dodane elementy danego typu. "
            "Użyj gdy użytkownik pyta o ostatnie notatki, paragony, zakładki, artykuły, transkrypcje."
        ),
        "parameters": {
            "content_type": "Typ: 'receipts','notes','bookmarks','articles','transcriptions' (wymagane)",
            "limit": "Liczba elementów (opcjonalne, domyślnie 5)",
        },
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
    },
]


def format_tool_descriptions() -> str:
    lines = []
    for i, tool in enumerate(TOOL_DEFINITIONS, 1):
        params = ", ".join(f"{k} ({v})" for k, v in tool["parameters"].items())
        lines.append(f"{i}. {tool['name']} — {tool['description']}")
        lines.append(f"   Parametry: {params}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

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

SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE.format(
    tool_descriptions=format_tool_descriptions()
)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

TEST_CASES = [
    # ---- A: Proste wywołania ----
    {
        "id": 1,
        "input": "Zapisz notatkę: jutro spotkanie z Tomkiem o 15:00 w biurze",
        "expected_tool": "create_note",
        "acceptable_tools": [],
        "required_args": {"title": None, "content": None},
        "description": "Notatka, jawne polecenie",
    },
    {
        "id": 2,
        "input": "Ile wydałem w Biedronce w tym miesiącu?",
        "expected_tool": "get_spending",
        "acceptable_tools": [],
        "required_args": {"store": "biedronk", "period": None},
        "description": "Wydatki: sklep + okres",
    },
    {
        "id": 3,
        "input": "Jaka jest pogoda?",
        "expected_tool": "get_weather",
        "acceptable_tools": [],
        "required_args": {},
        "description": "Pogoda, proste",
    },
    {
        "id": 4,
        "input": "Podsumuj ten artykuł: https://example.com/article",
        "expected_tool": "summarize_url",
        "acceptable_tools": [],
        "required_args": {"url": "example.com"},
        "description": "Streszczenie URL",
    },
    {
        "id": 5,
        "input": "Pokaż moje ostatnie notatki",
        "expected_tool": "list_recent",
        "acceptable_tools": [],
        "required_args": {"content_type": "note"},
        "description": "Lista ostatnich notatek",
    },
    {
        "id": 6,
        "input": "Wyszukaj w internecie najnowsze wiadomości o AI",
        "expected_tool": "search_web",
        "acceptable_tools": [],
        "required_args": {"query": None},
        "description": "Web search, jawne",
    },
    {
        "id": 7,
        "input": "Zapisz ten link na później: https://blog.example.com/post",
        "expected_tool": "create_bookmark",
        "acceptable_tools": [],
        "required_args": {"url": "blog.example.com"},
        "description": "Zakładka z URL",
    },
    {
        "id": 8,
        "input": "Co miałem w moich notatkach o projekcie X?",
        "expected_tool": "search_knowledge",
        "acceptable_tools": [],
        "required_args": {"query": None},
        "description": "Szukanie w bazie wiedzy",
    },
    # ---- B: Styl głosówki ----
    {
        "id": 9,
        "input": "Hej, zapisz mi że jutro mam dentystę o 10",
        "expected_tool": "create_note",
        "acceptable_tools": [],
        "required_args": {"content": None},
        "description": "Głosówka: dentysta",
    },
    {
        "id": 10,
        "input": "Zanotuj: kupić mleko, chleb i masło",
        "expected_tool": "create_note",
        "acceptable_tools": [],
        "required_args": {"content": None},
        "description": "Głosówka: lista zakupów",
    },
    {
        "id": 11,
        "input": "Przypomnij mi żeby zadzwonić do mamy w piątek",
        "expected_tool": "create_note",
        "acceptable_tools": [],
        "required_args": {"content": None},
        "description": "Głosówka: przypomnienie",
    },
    {
        "id": 12,
        "input": "Hej, chcę zapisać linka https://news.ycombinator.com do przeczytania",
        "expected_tool": "create_bookmark",
        "acceptable_tools": [],
        "required_args": {"url": "ycombinator"},
        "description": "Głosówka: zakładka",
    },
    # ---- C: Niejednoznaczne ----
    {
        "id": 13,
        "input": "Co mam w lodówce?",
        "expected_tool": "get_inventory",
        "acceptable_tools": [],
        "required_args": {},
        "description": "Spiżarnia, potoczne",
    },
    {
        "id": 14,
        "input": "Co czytałem ostatnio o machine learning?",
        "expected_tool": "search_knowledge",
        "acceptable_tools": [],
        "required_args": {"query": None},
        "description": "RAG: co czytałem",
    },
    {
        "id": 15,
        "input": "Gdzie najczęściej robię zakupy?",
        "expected_tool": "get_spending",
        "acceptable_tools": [],
        "required_args": {},
        "description": "Wydatki: analityka sklepów",
    },
    {
        "id": 16,
        "input": "Jakie produkty mi się kończą?",
        "expected_tool": "get_inventory",
        "acceptable_tools": [],
        "required_args": {},
        "description": "Spiżarnia: kończące się",
    },
    {
        "id": 17,
        "input": "Ile kalorii ma jabłko?",
        "expected_tool": "answer_directly",
        "acceptable_tools": ["search_web"],
        "required_args": {},
        "description": "Wiedza ogólna / web",
    },
    {
        "id": 18,
        "input": "Porównaj moje wydatki z tego i poprzedniego tygodnia",
        "expected_tool": "get_spending",
        "acceptable_tools": [],
        "required_args": {"period": None},
        "description": "Wydatki: porównanie",
    },
    # ---- D: Przypadki brzegowe ----
    {
        "id": 19,
        "input": "Cześć!",
        "expected_tool": "answer_directly",
        "acceptable_tools": [],
        "required_args": {"text": None},
        "description": "Powitanie",
    },
    {
        "id": 20,
        "input": "2 + 2 * 3",
        "expected_tool": "answer_directly",
        "acceptable_tools": [],
        "required_args": {"text": None},
        "description": "Matematyka",
    },
    {
        "id": 21,
        "input": "https://arxiv.org/abs/2401.12345",
        "expected_tool": "summarize_url",
        "acceptable_tools": ["create_bookmark"],
        "required_args": {"url": None},
        "description": "Sam URL bez instrukcji",
    },
    {
        "id": 22,
        "input": "Pokaż ostatnie 3 paragony",
        "expected_tool": "list_recent",
        "acceptable_tools": ["get_spending"],
        "required_args": {},
        "description": "Ostatnie paragony z limitem",
    },
    # ---- E: Wieloaspektowe ----
    {
        "id": 23,
        "input": "Na co wydaję najwięcej pieniędzy?",
        "expected_tool": "get_spending",
        "acceptable_tools": [],
        "required_args": {},
        "description": "Wydatki: top kategorie",
    },
    {
        "id": 24,
        "input": "Jakie artykuły zapisałem w tym tygodniu?",
        "expected_tool": "list_recent",
        "acceptable_tools": ["search_knowledge"],
        "required_args": {},
        "description": "Ostatnie artykuły",
    },
    {
        "id": 25,
        "input": "Pogoda w Krakowie na weekend",
        "expected_tool": "get_weather",
        "acceptable_tools": [],
        "required_args": {"city": "krak"},
        "description": "Pogoda: konkretne miasto",
    },
    # ---- F: Długie inputy (głosówki) ----
    {
        "id": 26,
        "input": (
            "Hej, chciałem ci powiedzieć że dzisiaj miałem bardzo ciekawe spotkanie "
            "z zespołem projektowym. Rozmawialiśmy o nowej funkcjonalności w aplikacji, "
            "która pozwoli użytkownikom śledzić swoje wydatki. Tomek zaproponował żeby "
            "dodać wykresy, a Kasia chciała integrację z bankiem. Ostatecznie zdecydowaliśmy "
            "że zaczniemy od prostszej wersji bez integracji. Zapisz mi to proszę jako notatkę "
            "do późniejszego przejrzenia."
        ),
        "expected_tool": "create_note",
        "acceptable_tools": [],
        "required_args": {"content": None},
        "description": "Długa głosówka z wieloma informacjami",
    },
    {
        "id": 27,
        "input": (
            "Wczoraj byłem na zakupach w trzech sklepach: najpierw w Biedronce gdzie kupiłem "
            "mleko, chleb i ser, potem w Lidlu po owoce i warzywa, a na koniec w Żabce po "
            "napoje. Wydałem chyba ze 150 złotych łącznie ale nie jestem pewien. Czy możesz "
            "sprawdzić ile dokładnie wydałem wczoraj?"
        ),
        "expected_tool": "get_spending",
        "acceptable_tools": [],
        "required_args": {"period": None},
        "description": "Długi opis z pytaniem o wydatki",
    },
    # ---- G: Niepewne/niejasne intencje ----
    {
        "id": 28,
        "input": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "expected_tool": "summarize_url",
        "acceptable_tools": ["create_bookmark", "search_web"],
        "required_args": {},
        "description": "YouTube URL bez kontekstu",
    },
    {
        "id": 29,
        "input": "Hmm, co tam u ciebie?",
        "expected_tool": "answer_directly",
        "acceptable_tools": [],
        "required_args": {},
        "description": "Smalltalk",
    },
    {
        "id": 30,
        "input": "ok",
        "expected_tool": "answer_directly",
        "acceptable_tools": [],
        "required_args": {},
        "description": "Minimalna odpowiedź",
    },
    # ---- H: Specjalne znaki i formatowanie ----
    {
        "id": 31,
        "input": "Zapisz notatkę:\n- punkt 1\n- punkt 2\n- punkt 3\nTo jest lista rzeczy do zrobienia",
        "expected_tool": "create_note",
        "acceptable_tools": [],
        "required_args": {"content": None},
        "description": "Notatka z newlines i listą",
    },
    {
        "id": 32,
        "input": 'Szukaj w bazie "machine learning" oraz "neural networks"',
        "expected_tool": "search_knowledge",
        "acceptable_tools": ["search_web"],
        "required_args": {"query": None},
        "description": "Cudzysłowy w zapytaniu",
    },
    {
        "id": 33,
        "input": "Ile kosztował ser żółty w Biedronce? 🧀",
        "expected_tool": "get_spending",
        "acceptable_tools": [],
        "required_args": {"store": "biedronk"},
        "description": "Emoji w zapytaniu",
    },
    # ---- I: Negacje i odmowy ----
    {
        "id": 34,
        "input": "Nie zapisuj notatki, tylko pokaż mi ostatnie paragony",
        "expected_tool": "list_recent",
        "acceptable_tools": ["get_spending"],
        "required_args": {},
        "description": "Negacja + właściwe polecenie",
    },
    {
        "id": 35,
        "input": "Nie szukaj w internecie, sprawdź w mojej bazie wiedzy info o Pythonie",
        "expected_tool": "search_knowledge",
        "acceptable_tools": [],
        "required_args": {"query": None},
        "description": "Jawna preferencja RAG nad web",
    },
]


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------

def strip_think_tags(text: str) -> str:
    """Remove deepseek-r1 <think>...</think> chain-of-thought blocks."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def extract_json(raw: str) -> tuple[bool, dict | None]:
    """Parse JSON from model response, handling think tags and code fences."""
    text = strip_think_tags(raw).strip()

    # Strip markdown code fences
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
            return True, data
        return False, None
    except (json.JSONDecodeError, ValueError):
        return False, None


def check_tool(parsed: dict, expected: str, acceptable: list[str]) -> bool:
    tool = parsed.get("tool", "").lower().strip()
    valid = {expected.lower()} | {t.lower() for t in acceptable}
    return tool in valid


def check_args(parsed: dict, required_args: dict) -> tuple[bool, list[str]]:
    """Check required arguments are present and contain expected substrings."""
    if not required_args:
        return True, []

    args = parsed.get("arguments", {})
    if not isinstance(args, dict):
        return False, ["arguments is not a dict"]

    failures = []
    for key, expected_substr in required_args.items():
        val = args.get(key)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            failures.append(f"missing '{key}'")
            continue
        if expected_substr is not None:
            actual = str(val).lower()
            if expected_substr.lower() not in actual:
                failures.append(f"'{key}': expected '{expected_substr}' in '{actual[:60]}'")

    return len(failures) == 0, failures


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def ollama_chat(model: str, messages: list[dict], format_type: str = "json", options: dict = None) -> dict:
    """Call Ollama chat API using urllib (no external deps)."""
    url = f"{OLLAMA_HOST}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": format_type,
        "options": options or {},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ollama_list_models() -> list[str]:
    """Get list of available models from Ollama."""
    url = f"{OLLAMA_HOST}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def get_available_models(requested: list[str]) -> list[str]:
    """Check which requested models are available in Ollama."""
    try:
        installed = set(ollama_list_models())
    except Exception as e:
        print(f"WARNING: Cannot list Ollama models: {e}")
        return requested

    available = []
    for model in requested:
        if model in installed:
            available.append(model)
        else:
            # Try matching without tag
            base = model.split(":")[0]
            matches = [m for m in installed if m.startswith(base)]
            if matches:
                available.append(model)
            else:
                print(f"WARNING: Model '{model}' not found in Ollama, skipping")

    return available


def run_single_test(model: str, test_case: dict) -> dict:
    """Run one test case against one model."""
    start = time.time()

    try:
        response = ollama_chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": test_case["input"]},
            ],
            format_type="json",
            options={"temperature": 0.0, "num_predict": 300},
        )
        raw = response["message"]["content"]
    except Exception as e:
        raw = ""
        return {
            "model": model,
            "test_id": test_case["id"],
            "raw_response": str(e)[:200],
            "parsed_tool": None,
            "is_json": False,
            "is_tool_correct": False,
            "is_args_ok": False,
            "arg_failures": [f"ollama error: {e}"],
            "elapsed_sec": round(time.time() - start, 1),
        }

    elapsed = round(time.time() - start, 1)

    is_json, parsed = extract_json(raw)

    if parsed:
        is_tool = check_tool(parsed, test_case["expected_tool"], test_case["acceptable_tools"])
        is_args, arg_fails = check_args(parsed, test_case["required_args"])
        parsed_tool = parsed.get("tool", "?")
    else:
        is_tool = False
        is_args = False
        arg_fails = ["no valid JSON"]
        parsed_tool = None

    return {
        "model": model,
        "test_id": test_case["id"],
        "raw_response": raw[:300],
        "parsed_tool": parsed_tool,
        "is_json": is_json,
        "is_tool_correct": is_tool,
        "is_args_ok": is_args,
        "arg_failures": arg_fails,
        "elapsed_sec": elapsed,
    }


def run_test_suite(
    models: list[str],
    test_cases: list[dict],
    verbose: bool = False,
) -> list[dict]:
    """Run all test cases against all models."""
    all_results = []
    total = len(test_cases)

    for tc in test_cases:
        desc = tc["input"][:55]
        print(f"\n[{tc['id']:>2}/{total}] \"{desc}...\"" if len(tc["input"]) > 55 else f"\n[{tc['id']:>2}/{total}] \"{tc['input']}\"")

        for model in models:
            result = run_single_test(model, tc)
            all_results.append(result)

            # Status symbols
            sj = "\033[32m✓\033[0m" if result["is_json"] else "\033[31m✗\033[0m"
            st = "\033[32m✓\033[0m" if result["is_tool_correct"] else "\033[31m✗\033[0m"
            sa = "\033[32m✓\033[0m" if result["is_args_ok"] else "\033[31m✗\033[0m"

            tool_str = (result["parsed_tool"] or "???")[:20]
            line = f"  {model:<22s} → {tool_str:<20s} {sj}JSON {st}Tool {sa}Args  ({result['elapsed_sec']}s)"

            if result["arg_failures"] and not result["is_args_ok"]:
                line += f"  [{', '.join(result['arg_failures'][:2])}]"

            print(line)

            if verbose and result["raw_response"]:
                print(f"    RAW: {result['raw_response'][:150]}")

    return all_results


def print_summary(results: list[dict], models: list[str]) -> None:
    """Print per-model summary table and failure details."""
    total_tests = len(set(r["test_id"] for r in results))

    print("\n")
    print("=" * 85)
    print("PODSUMOWANIE")
    print("=" * 85)

    # Header
    print(f"{'Model':<24s} {'JSON':>7s} {'Tool':>7s} {'Args':>7s} {'Full Pass':>12s} {'Avg Time':>10s}")
    print("-" * 85)

    for model in models:
        model_results = [r for r in results if r["model"] == model]
        n = len(model_results)
        if n == 0:
            continue

        json_ok = sum(1 for r in model_results if r["is_json"])
        tool_ok = sum(1 for r in model_results if r["is_tool_correct"])
        args_ok = sum(1 for r in model_results if r["is_args_ok"])
        full_ok = sum(
            1 for r in model_results
            if r["is_json"] and r["is_tool_correct"] and r["is_args_ok"]
        )
        avg_time = sum(r["elapsed_sec"] for r in model_results) / n

        pct = f"{full_ok}/{n} {full_ok * 100 // n}%"
        print(
            f"{model:<24s} {json_ok:>3d}/{n:<3d} {tool_ok:>3d}/{n:<3d} "
            f"{args_ok:>3d}/{n:<3d} {pct:>12s} {avg_time:>8.1f}s"
        )

    print("-" * 85)

    # Failure details per model
    for model in models:
        model_results = [r for r in results if r["model"] == model]
        failures = [
            r for r in model_results
            if not (r["is_json"] and r["is_tool_correct"] and r["is_args_ok"])
        ]

        if not failures:
            print(f"\n{model}: Brak błędów!")
            continue

        print(f"\n=== Błędy: {model} ===")
        for r in failures:
            tc = next(t for t in TEST_CASES if t["id"] == r["test_id"])
            issues = []
            if not r["is_json"]:
                issues.append("invalid JSON")
            if not r["is_tool_correct"]:
                issues.append(f"got {r['parsed_tool']}, expected {tc['expected_tool']}")
            if not r["is_args_ok"]:
                issues.extend(r["arg_failures"][:2])
            print(f"  #{r['test_id']:>2d} \"{tc['input'][:50]}\" → {', '.join(issues)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Test agent tool-calling with Ollama models"
    )
    parser.add_argument(
        "--models", nargs="+", default=MODELS,
        help="Models to test (default: all three)",
    )
    parser.add_argument(
        "--test-ids", nargs="+", type=int, default=None,
        help="Run only specific test IDs",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show raw model responses",
    )
    args = parser.parse_args()

    print("=" * 85)
    print("  AGENT TOOL-CALLING TEST")
    print(f"  Narzędzi: {len(TOOL_DEFINITIONS)}  |  Test case'ów: {len(TEST_CASES)}")
    print("=" * 85)

    # Check model availability
    models = get_available_models(args.models)
    if not models:
        print("ERROR: No models available")
        sys.exit(1)

    print(f"  Modele: {', '.join(models)}")

    # Filter test cases if needed
    test_cases = TEST_CASES
    if args.test_ids:
        test_cases = [tc for tc in TEST_CASES if tc["id"] in args.test_ids]
        if not test_cases:
            print(f"ERROR: No test cases match IDs {args.test_ids}")
            sys.exit(1)

    print(f"  Testy:  {len(test_cases)}")

    # Run
    results = run_test_suite(models, test_cases, verbose=args.verbose)
    print_summary(results, models)


if __name__ == "__main__":
    main()
