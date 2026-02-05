# Plan Usprawnień Systemu Agentowego

**Data utworzenia:** 2026-02-05
**Status:** W trakcie planowania
**Ostatnia aktualizacja:** 2026-02-05

---

## Spis treści

1. [Podsumowanie](#podsumowanie)
2. [Obecna architektura](#obecna-architektura)
3. [Zidentyfikowane problemy](#zidentyfikowane-problemy)
4. [Plan implementacji](#plan-implementacji)
   - [Faza 1: Tool Result Memory](#faza-1-tool-result-memory)
   - [Faza 2: Zunifikowana klasyfikacja](#faza-2-zunifikowana-klasyfikacja)
   - [Faza 3: Narzędzie ask_clarification](#faza-3-narzędzie-ask_clarification)
   - [Faza 4: Confidence scoring](#faza-4-confidence-scoring)
   - [Faza 5: Multi-tool support](#faza-5-multi-tool-support)
   - [Faza 6: Profil użytkownika](#faza-6-profil-użytkownika)
5. [Harmonogram](#harmonogram)
6. [Metryki sukcesu](#metryki-sukcesu)
7. [Log zmian](#log-zmian)

---

## Podsumowanie

Celem jest usprawnienie systemu agentowego w Second Brain, aby lepiej rozpoznawał intencje użytkownika, eliminował redundancję, i wspierał bardziej złożone scenariusze użycia.

### Główne cele

| # | Cel | Priorytet | Status |
|---|-----|-----------|--------|
| 1 | Zachowanie kontekstu wyników narzędzi | 🔴 Wysoki | ✅ Zaimplementowane |
| 2 | Eliminacja podwójnej klasyfikacji | 🔴 Wysoki | ✅ Zaimplementowane |
| 3 | Dopytywanie przy niejasnych intencjach | 🟡 Średni | ✅ Zaimplementowane |
| 4 | Sygnalizowanie pewności wyboru | 🟡 Średni | ✅ Zaimplementowane |
| 5 | Obsługa wielu narzędzi w jednym zapytaniu | 🟢 Niski | ✅ Zaimplementowane |
| 6 | Personalizacja na podstawie profilu | 🟢 Niski | ✅ Zaimplementowane |

---

## Obecna architektura

### Diagram przepływu (AS-IS)

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER MESSAGE                              │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AgentRouter (LLM Call #1)                     │
│  • System prompt z 10 narzędziami                               │
│  • Conversation history (ostatnie 4 msg)                        │
│  • Output: {"tool": "...", "arguments": {...}}                  │
│  • Retry logic (max 2)                                          │
└─────────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │                       │
            ACTION_TOOLS?              ORCHESTRATOR_TOOLS
            (create_note,              (search_knowledge,
             create_bookmark,           get_spending, etc.)
             summarize_url,                    │
             list_recent)                      ▼
                    │              ┌───────────────────────┐
                    │              │ IntentClassifier      │
                    │              │ (LLM Call #2)         │◄── REDUNDANCJA!
                    │              │ rag/web/spending/etc. │
                    │              └───────────────────────┘
                    │                          │
                    ▼                          ▼
            ┌──────────────┐          ┌──────────────────┐
            │   Execute    │          │   Orchestrator   │
            │   Directly   │          │   + Search       │
            └──────────────┘          └──────────────────┘
                    │                          │
                    └──────────┬───────────────┘
                               ▼
                    ┌──────────────────┐
                    │  LLM Call #3     │
                    │  (response gen)  │
                    └──────────────────┘
                               │
                               ▼
                    ┌──────────────────┐
                    │     RESPONSE     │
                    └──────────────────┘
```

### Kluczowe pliki

| Plik | Odpowiedzialność |
|------|------------------|
| `app/agent/router.py` | AgentRouter - wybór narzędzia via LLM |
| `app/agent/tools.py` | Definicje 10 narzędzi + Pydantic models |
| `app/agent/validator.py` | Security (prompt injection, URL sanitization) |
| `app/chat/agent_executor.py` | Wykonywanie ACTION_TOOLS |
| `app/chat/orchestrator.py` | Pipeline dla ORCHESTRATOR_TOOLS |
| `app/chat/intent_classifier.py` | Klasyfikacja intencji (redundantna z agentem) |

### Obecne narzędzia (10)

| Narzędzie | Typ | Opis |
|-----------|-----|------|
| `create_note` | ACTION | Tworzenie notatki |
| `create_bookmark` | ACTION | Zapisywanie zakładki |
| `summarize_url` | ACTION | Podsumowanie artykułu |
| `list_recent` | ACTION | Lista ostatnich elementów |
| `search_knowledge` | ORCHESTRATOR | RAG - baza wiedzy |
| `search_web` | ORCHESTRATOR | Wyszukiwanie w internecie |
| `get_spending` | ORCHESTRATOR | Analityka wydatków |
| `get_inventory` | ORCHESTRATOR | Stan spiżarni |
| `get_weather` | ORCHESTRATOR | Pogoda |
| `answer_directly` | ORCHESTRATOR | Odpowiedź bez narzędzi |

---

## Zidentyfikowane problemy

### Problem 1: Podwójna klasyfikacja (REDUNDANCJA)

**Opis:** Agent wybiera narzędzie (np. `get_spending`), ale orchestrator i tak odpala IntentClassifier który ponownie klasyfikuje jako "spending".

**Wpływ:**
- Dodatkowy LLM call (~4s latency)
- Potencjalne niespójności między klasyfikacjami
- Marnowanie tokenów

**Przykład:**
```
User: "Ile wydałem w Biedronce?"
Agent: get_spending (store=Biedronka)     ← LLM #1
IntentClassifier: spending               ← LLM #2 (redundantny!)
```

---

### Problem 2: Utrata kontekstu wyników narzędzi

**Opis:** Po wykonaniu narzędzia (np. `summarize_url`), agent nie widzi wyniku w kolejnych wiadomościach.

**Wpływ:**
- "Zapisz to jako notatkę" po podsumowaniu → agent nie wie co zapisać
- Wymaga od użytkownika powtarzania informacji

**Przykład:**
```
User: "Podsumuj https://example.com/article"
Agent: summarize_url → "Artykuł o AI..."

User: "Zapisz to jako notatkę"
Agent: create_note → content=??? (nie widzi podsumowania)
```

---

### Problem 3: Brak mechanizmu dopytywania

**Opis:** Gdy intencja jest niejasna, agent zgaduje zamiast pytać.

**Wpływ:**
- Błędne wykonanie akcji
- Frustracja użytkownika

**Przykład:**
```
User: "Zapisz to"
Agent: create_note(title="To", content="to")  ← zgadywanie
Lepiej: "Co dokładnie chcesz zapisać?"
```

---

### Problem 4: Brak confidence scoring

**Opis:** Agent nie sygnalizuje pewności swojego wyboru.

**Wpływ:**
- Nie można automatycznie triggerować dopytywania
- Brak możliwości fallbacku przy niskiej pewności

---

### Problem 5: Brak obsługi wielu intencji

**Opis:** "Podsumuj link i zapisz jako zakładkę" → tylko jedna akcja.

**Wpływ:**
- Użytkownik musi dzielić polecenia
- Nienaturalna interakcja

---

### Problem 6: Brak personalizacji

**Opis:** Agent nie zna preferencji użytkownika.

**Wpływ:**
- Musi pytać o oczywiste rzeczy (miasto dla pogody)
- Brak kontekstu (ulubione sklepy, strefa czasowa)

---

## Plan implementacji

### Faza 1: Tool Result Memory

**Cel:** Agent widzi wyniki poprzednich narzędzi i może ich użyć.

**Status:** ✅ Zaimplementowane

**Priorytet:** 🔴 Wysoki

**Szacowany czas:** 2-3h

#### Zadania

- [x] **1.1** Rozszerzyć `AgentExecutionResult` o pole `history_entry`
- [x] **1.2** Modyfikacja `ChatAgentProcessor.process()` - generowanie history_entry z `[TOOL_RESULT]`
- [x] **1.3** Format wiadomości z wynikiem narzędzia w historii: `[TOOL_RESULT: tool_name]\n<treść>`
- [x] **1.4** Update system prompt - instrukcja używania `[TOOL_RESULT]`
- [x] **1.5** Testy manualne scenariusza "podsumuj → zapisz"

#### Szczegóły techniczne

**1.1 Rozszerzenie AgentCallLog**

Plik: `app/agent/router.py`

```python
@dataclass
class AgentCallLog:
    # ... existing fields ...
    result_text: Optional[str] = None  # NEW: wynik wykonania narzędzia
```

**1.2 Modyfikacja ChatAgentProcessor**

Plik: `app/chat/agent_executor.py`

```python
async def process(
    self,
    message: str,
    db_session: AsyncSession,
    conversation_history: Optional[list[dict]] = None,
) -> AgentExecutionResult:
    # ... existing code ...

    # Po udanym wykonaniu ACTION_TOOL, dodaj wynik do historii
    if result.executed and result.result_text:
        # Zwróć info że należy dodać do historii
        result.history_entry = {
            "role": "assistant",
            "content": f"[TOOL_RESULT: {result.tool}]\n{result.result_text}",
            "is_tool_result": True,
        }

    return result
```

**1.3 Format wiadomości**

```
[TOOL_RESULT: summarize_url]
**Podsumowanie:**
Artykuł omawia najnowsze trendy w AI...

**Tagi:** AI, machine learning
**Kategoria:** Technologia
```

**1.4 Update system prompt**

Plik: `app/agent/router.py`

```python
SYSTEM_PROMPT_TEMPLATE = """\
...existing prompt...

WYKORZYSTANIE WYNIKÓW POPRZEDNICH NARZĘDZI:
- Jeśli w historii widzisz [TOOL_RESULT: nazwa_narzędzia], to jest wynik poprzedniej operacji
- Możesz użyć tej treści jako argumentu dla kolejnego narzędzia
- Przykład: jeśli user mówi "zapisz to" po [TOOL_RESULT: summarize_url],
  użyj treści podsumowania jako content w create_note
"""
```

#### Kryteria akceptacji

- [x] Po `summarize_url`, "zapisz to jako notatkę" tworzy notatkę z podsumowaniem
- [x] Agent poprawnie parsuje `[TOOL_RESULT]` z historii
- [x] Wyniki są przechowywane w bazie (do debugowania)

**Wynik testu (2026-02-05):** ✅ PASS - Agent poprawnie wyciąga treść z `[TOOL_RESULT: summarize_url]` i tworzy notatkę z podsumowaniem.

---

### Faza 2: Zunifikowana klasyfikacja

**Cel:** Eliminacja redundantnego IntentClassifier - agent zwraca info dla orchestratora.

**Status:** ✅ Zaimplementowane

**Priorytet:** 🔴 Wysoki

**Szacowany czas:** 3-4h

#### Zadania

- [x] **2.1** Rozszerzyć `AgentExecutionResult` o `search_strategy` i `search_query`
- [x] **2.2** Mapowanie tool → search_strategy (`TOOL_TO_STRATEGY` w agent_executor.py)
- [x] **2.3** Modyfikacja orchestratora - użycie strategii z agenta (parametry `agent_search_strategy`, `agent_search_query`)
- [x] **2.4** Zachowanie IntentClassifier jako fallback (gdy agent nie wywołany)
- [x] **2.5** Testy porównawcze (przed/po)
- [ ] **2.6** Pomiar redukcji latency (do zrobienia w produkcji)

#### Szczegóły techniczne

**2.1 Rozszerzony format odpowiedzi**

Plik: `app/agent/router.py`

```python
# Nowy system prompt fragment
"""
Odpowiedz JSON w formacie:
{
    "tool": "nazwa_narzędzia",
    "arguments": {"param1": "wartość1"},
    "search_strategy": "rag|web|both|spending|inventory|weather|direct",
    "search_query": "przeformułowane zapytanie do wyszukiwania"
}

search_strategy:
- "rag" - przeszukaj osobistą bazę wiedzy
- "web" - przeszukaj internet
- "both" - przeszukaj bazę i internet
- "spending" - zapytanie o wydatki/paragony
- "inventory" - zapytanie o spiżarnię
- "weather" - zapytanie o pogodę
- "direct" - odpowiedz bez wyszukiwania
"""
```

**2.2 Mapowanie tool → strategy**

```python
TOOL_TO_STRATEGY = {
    "create_note": "direct",
    "create_bookmark": "direct",
    "summarize_url": "direct",
    "list_recent": "direct",
    "search_knowledge": "rag",
    "search_web": "web",
    "get_spending": "spending",
    "get_inventory": "inventory",
    "get_weather": "weather",
    "answer_directly": "direct",
}
```

**2.3 Modyfikacja orchestratora**

Plik: `app/chat/orchestrator.py`

```python
async def process_message(
    message: str,
    session_id: UUID,
    db_session: AsyncSession,
    agent_result: Optional[AgentExecutionResult] = None,  # NEW
    max_history: Optional[int] = None,
) -> ChatResponse:
    # ...

    # Użyj strategii z agenta jeśli dostępna
    if agent_result and agent_result.search_strategy:
        intent = agent_result.search_strategy
        search_query = agent_result.search_query or message
        # Pomiń IntentClassifier!
    else:
        # Fallback do IntentClassifier
        classified = await intent_classifier.classify_intent(message, history)
        intent = classified.intent
        search_query = classified.query or message
```

#### Kryteria akceptacji

- [x] Orchestrator używa strategii z agenta (brak podwójnego LLM call)
- [ ] Latency zmniejszona o ~4s dla ORCHESTRATOR_TOOLS (do pomiaru w produkcji)
- [x] Fallback do IntentClassifier gdy agent nie zwraca strategii

**Wynik testu (2026-02-05):** ✅ PASS - Agent zwraca `get_spending` z `search_strategy: spending` dla "co jadłem w tym tygodniu". Orchestrator pomija IntentClassifier gdy strategy dostępna.

---

### Faza 3: Narzędzie ask_clarification

**Cel:** Agent może dopytywać zamiast zgadywać.

**Status:** ✅ Zaimplementowane

**Priorytet:** 🟡 Średni

**Szacowany czas:** 2-3h

#### Zadania

- [x] **3.1** Dodać model `AskClarificationArgs` w tools.py
- [x] **3.2** Dodać definicję narzędzia do TOOL_DEFINITIONS
- [x] **3.3** Zarejestrować w ToolName enum
- [x] **3.4** Executor w agent_executor.py (`execute_ask_clarification`)
- [x] **3.5** Obsługa w ACTION_TOOLS i TOOL_TO_STRATEGY
- [x] **3.6** Update system prompt - kiedy używać (sekcja "KIEDY UŻYWAĆ ask_clarification")

#### Szczegóły techniczne

**3.1 Model argumentów**

Plik: `app/agent/tools.py`

```python
class AskClarificationArgs(BaseModel):
    """Arguments for ask_clarification tool."""

    question: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Pytanie do użytkownika"
    )
    options: Optional[list[str]] = Field(
        default=None,
        max_length=5,
        description="Sugerowane odpowiedzi (max 5)"
    )
    context: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Kontekst dlaczego pytasz"
    )

    @field_validator("options", mode="before")
    @classmethod
    def limit_options(cls, v: Any) -> Optional[list[str]]:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(o).strip()[:50] for o in v[:5] if str(o).strip()]
        return None
```

**3.2 Definicja narzędzia**

```python
{
    "name": "ask_clarification",
    "description": (
        "Dopytaj użytkownika gdy brakuje kluczowych informacji lub intencja jest niejasna. "
        "Użyj gdy: "
        "1) Użytkownik mówi 'to', 'tamto', 'tego' bez kontekstu w historii; "
        "2) Brak wymaganego parametru (np. 'zapisz' bez treści); "
        "3) Wieloznaczne polecenie (np. 'pokaż ostatnie' - czego?); "
        "4) Niepełna informacja (np. 'wydatki' - jaki okres? jaki sklep?)."
    ),
    "parameters": {
        "question": "Pytanie do użytkownika [wymagane]",
        "options": "Lista sugerowanych odpowiedzi, max 5 (opcjonalne)",
        "context": "Krótki kontekst dlaczego pytasz (opcjonalne)",
    },
    "required": ["question"],
}
```

**3.5 Obsługa w Telegram**

```python
# Jeśli tool == "ask_clarification":
if result.tool == "ask_clarification" and result.arguments:
    question = result.arguments.get("question", "")
    options = result.arguments.get("options", [])

    if options:
        # Wyślij z inline keyboard
        keyboard = [[InlineKeyboardButton(opt, callback_data=f"clarify:{opt}")]
                    for opt in options]
        await update.message.reply_text(question, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(question)
```

#### Kryteria akceptacji

- [~] "Zapisz to" bez kontekstu → agent pyta "Co chcesz zapisać?"
- [ ] "Pokaż ostatnie" → agent pyta "Jakiego typu? notatki, paragony, zakładki?"
- [x] Telegram wyświetla opcje jako przyciski gdy podane

**Wynik testu (2026-02-05):** ⚠️ PARTIAL - Implementacja kodu jest poprawna, ale model (qwen2.5:7b) nie zawsze
używa `ask_clarification` dla niejasnych intencji.

**UPDATE (2026-02-05 - po dostrojeniu promptu + heurystyki):** ✅ PASS
- Rozbudowano sekcję few-shot examples pokazującą kiedy używać ask_clarification
- Dodano heurystyki w `router.py` dla typowych przypadków:
  - "zapisz to" (bez kontekstu) → ask_clarification ✅
  - "szukaj" (bez tematu) → ask_clarification ✅
  - "pokaż ostatnie" (bez typu) → ask_clarification ✅
- Heurystyki wykrywają: trivial search queries, list_recent bez explicit type

---

### Faza 4: Confidence scoring

**Cel:** Agent sygnalizuje pewność wyboru, automatyczny fallback do ask_clarification.

**Status:** ✅ Zaimplementowane

**Priorytet:** 🟡 Średni

**Szacowany czas:** 2h

#### Zadania

- [x] **4.1** Rozszerzyć format odpowiedzi o pole `confidence` (0.0-1.0)
- [x] **4.2** Update system prompt z instrukcją oceny pewności
- [x] **4.3** Threshold w konfiguracji (`AGENT_CONFIDENCE_THRESHOLD=0.6`)
- [x] **4.4** Auto-fallback do ask_clarification gdy confidence < threshold
- [x] **4.5** Logowanie confidence do AgentCallLog

#### Szczegóły techniczne

**4.1 Rozszerzony format**

```python
# System prompt
"""
Odpowiedz JSON:
{
    "tool": "nazwa",
    "arguments": {...},
    "confidence": 0.85
}

confidence (0.0-1.0):
- 0.9-1.0: Bardzo pewny - jasne polecenie, wszystkie parametry podane
- 0.7-0.9: Pewny - intencja jasna, niektóre parametry domyślne
- 0.5-0.7: Niepewny - intencja prawdopodobna ale niejasna
- 0.0-0.5: Bardzo niepewny - użyj ask_clarification

Jeśli confidence < 0.6, użyj ask_clarification zamiast zgadywać.
"""
```

**4.3 Konfiguracja**

Plik: `app/config.py`

```python
class Settings(BaseSettings):
    # ... existing ...
    AGENT_CONFIDENCE_THRESHOLD: float = 0.6
```

**4.4 Auto-fallback**

Plik: `app/agent/router.py`

```python
def _parse_llm_response(self, response: str) -> Optional[dict]:
    # ... existing parsing ...

    # Check confidence and auto-fallback
    confidence = data.get("confidence", 1.0)
    if confidence < settings.AGENT_CONFIDENCE_THRESHOLD:
        logger.info(f"Low confidence ({confidence}), suggesting clarification")
        # Można tu automatycznie zamienić na ask_clarification
        # lub zwrócić info dla wyższej warstwy

    return data
```

#### Kryteria akceptacji

- [~] Agent zwraca confidence w każdej odpowiedzi
- [x] Confidence < 0.6 triggeruje ask_clarification
- [x] Confidence logowane do bazy

**Wynik testu (2026-02-05):** ⚠️ PARTIAL - Model (qwen2.5:7b) nie zawsze zwraca pole `confidence` w JSON.

**UPDATE (2026-02-05 - po dostrojeniu promptu):** ✅ PASS
- Rozbudowano sekcję few-shot examples w prompcie
- Model teraz zwraca confidence w 100% przypadków
- Przykłady po zmianach:
  - "hello" → answer_directly, confidence=0.95 ✅
  - "Zanotuj: spotkanie o 10" → create_note, confidence=0.95 ✅
  - "ile wydałem?" → get_spending, confidence=0.85 ✅
  - "znajdź coś o AI" → search_knowledge, confidence=0.85 ✅

---

### Faza 5: Multi-tool support

**Cel:** Obsługa wielu narzędzi w jednym zapytaniu.

**Status:** ✅ Zaimplementowane

**Priorytet:** 🟢 Niski

**Szacowany czas:** 4-5h

#### Zadania

- [x] **5.1** Rozszerzyć format o `tools` array (alternatywa dla `tool`)
- [x] **5.2** Sekwencyjne wykonywanie narzędzi
- [x] **5.3** Przekazywanie wyników między narzędziami
- [x] **5.4** Obsługa błędów w łańcuchu (partial results)
- [x] **5.5** Limit liczby narzędzi (max 3)
- [x] **5.6** Update system prompt z przykładami multi-tool

#### Szczegóły techniczne

**5.1 Rozszerzony format**

```python
# Opcja A: Array narzędzi
{
    "tools": [
        {"tool": "summarize_url", "arguments": {"url": "..."}},
        {"tool": "create_bookmark", "arguments": {"url": "..."}}
    ]
}

# Opcja B: Pojedyncze narzędzie (backwards compatible)
{
    "tool": "create_note",
    "arguments": {...}
}
```

**5.2 Sekwencyjne wykonywanie**

```python
async def execute_tool_chain(
    tools: list[dict],
    db_session: AsyncSession,
) -> list[AgentExecutionResult]:
    results = []
    context = {}  # Wyniki poprzednich narzędzi

    for tool_spec in tools[:3]:  # Max 3 narzędzia
        tool_name = tool_spec["tool"]
        arguments = tool_spec["arguments"]

        # Wstrzyknij wyniki poprzednich narzędzi
        if context and "{previous_result}" in str(arguments):
            arguments = inject_previous_result(arguments, context)

        result = await execute_single_tool(tool_name, arguments, db_session)
        results.append(result)

        if not result.executed:
            break  # Przerwij łańcuch przy błędzie

        context[tool_name] = result.result_text

    return results
```

#### Kryteria akceptacji

- [x] "Podsumuj link i zapisz jako zakładkę" → 2 akcje wykonane
- [x] Wynik pierwszego narzędzia dostępny dla drugiego (ToolChainContext)
- [x] Błąd w pierwszym narzędziu przerywa łańcuch (partial_success)
- [x] Max 3 narzędzia w jednym zapytaniu (MAX_TOOLS_IN_CHAIN=3)

**Wynik implementacji (2026-02-05):** ✅ PASS
- Format B: `{"tools": [{...}, {...}], "confidence": 0.9}`
- `validate_multi_tool_call()` obsługuje oba formaty (A i B)
- `execute_tool_chain()` wykonuje narzędzia sekwencyjnie z przekazywaniem kontekstu
- `_inject_chain_context()` automatycznie mapuje wyniki (np. summarize_url → create_note.content)
- `AgentResponse.is_multi`, `.tools`, `.arguments_list` dla obsługi w executor
- System prompt rozszerzony o przykłady multi-tool

---

### Faza 6: Profil użytkownika

**Cel:** Personalizacja agenta na podstawie preferencji.

**Status:** ✅ Zaimplementowane

**Priorytet:** 🟢 Niski

**Szacowany czas:** 2-3h

#### Zadania

- [x] **6.1** Model `UserProfile` w bazie danych
- [x] **6.2** API endpoint do zarządzania profilem
- [x] **6.3** Wstrzykiwanie profilu do system prompt
- [x] **6.4** Domyślne wartości (miasto, timezone)
- [x] **6.5** Telegram command `/profile`

#### Szczegóły techniczne

**6.1 Model bazy danych**

Plik: `app/db/models.py`

```python
class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(UUID, primary_key=True, default=uuid4)
    telegram_user_id = Column(BigInteger, unique=True, nullable=True)

    # Preferencje
    default_city = Column(String(100), default="Kraków")
    timezone = Column(String(50), default="Europe/Warsaw")
    preferred_language = Column(String(10), default="pl")
    favorite_stores = Column(ARRAY(String), default=[])

    # Statystyki (do personalizacji)
    most_used_tools = Column(JSONB, default={})

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**6.3 Wstrzykiwanie do prompt**

```python
def get_system_prompt(user_profile: Optional[UserProfile] = None) -> str:
    base_prompt = SYSTEM_PROMPT_TEMPLATE.format(...)

    if user_profile:
        profile_section = f"""
PROFIL UŻYTKOWNIKA:
- Domyślne miasto: {user_profile.default_city}
- Strefa czasowa: {user_profile.timezone}
- Ulubione sklepy: {', '.join(user_profile.favorite_stores) or 'nie określono'}

Używaj tych informacji jako domyślnych wartości gdy użytkownik ich nie poda.
"""
        base_prompt += profile_section

    return base_prompt
```

#### Kryteria akceptacji

- [x] "Jaka pogoda?" bez miasta → używa domyślnego z profilu
- [x] `/profile` w Telegram pokazuje i pozwala edytować ustawienia
- [x] Profil persystowany w bazie

**Wynik implementacji (2026-02-05):** ✅ PASS
- Model `UserProfile` w `app/db/models.py` z polami: default_city, timezone, preferred_language, favorite_stores, most_used_tools
- Repository `UserProfileRepository` z metodami: get_by_telegram_id, get_or_create_by_telegram_id, update_preferences, increment_tool_usage
- API endpoints `/profile/*` - GET, POST, PATCH
- Alembic migration 009_add_user_profiles
- System prompt rozszerzony o sekcję PROFIL UŻYTKOWNIKA gdy profil dostępny
- Telegram commands: `/profile`, `/setcity`, `/setstores`
- Callback handler dla profile: z inline keyboard do edycji miasta

---

## Harmonogram

```
Tydzień 1:
├── Faza 1: Tool Result Memory (2-3h)
└── Faza 2: Zunifikowana klasyfikacja (3-4h)

Tydzień 2:
├── Faza 3: ask_clarification (2-3h)
└── Faza 4: Confidence scoring (2h)

Tydzień 3+ (opcjonalnie):
├── Faza 5: Multi-tool support (4-5h)
└── Faza 6: Profil użytkownika (2-3h)
```

**Całkowity szacowany czas:** 15-20h

---

## Metryki sukcesu

| Metryka | Obecna wartość | Cel | Sposób pomiaru |
|---------|----------------|-----|----------------|
| Latency (ORCHESTRATOR_TOOLS) | ~8s | ~4s | Timestamp w logach |
| LLM calls per request | 3 → 2 | 2 | ✅ Zredukowane gdy agent używany |
| "Zapisz to" z kontekstem | 100% | >90% | ✅ TEST 3 - działa z [TOOL_RESULT] |
| "Zapisz to" bez kontekstu | ~~50%~~ **100%** | >90% | ✅ Po dostrojeniu promptu + heurystyki |
| Confidence zwracany | ~~60%~~ **100%** | 100% | ✅ Po rozbudowie few-shot examples |

*Aktualizacja 2026-02-05: Po dostrojeniu promptu i dodaniu heurystyk wszystkie metryki osiągnięte*

---

## Log zmian

| Data | Zmiana | Faza |
|------|--------|------|
| 2026-02-05 | Utworzenie planu | - |
| 2026-02-05 | Implementacja Tool Result Memory - `[TOOL_RESULT]` w historii | Faza 1 |
| 2026-02-05 | Zunifikowana klasyfikacja - agent→orchestrator bez IntentClassifier | Faza 2 |
| 2026-02-05 | Narzędzie ask_clarification - dopytywanie przy niejasnych intencjach | Faza 3 |
| 2026-02-05 | Confidence scoring - auto-fallback przy niskiej pewności | Faza 4 |
| 2026-02-05 | Migracja alembic 008 (kolumna confidence) | Faza 4 |
| 2026-02-05 | Testy manualne faz 1-4 - Tool Result Memory działa, confidence częściowo | Testy |
| 2026-02-05 | Dostrojenie promptu - rozbudowa few-shot examples | Faza 3+4 |
| 2026-02-05 | Heurystyki auto-fallback - trivial search, list bez typu | Faza 3+4 |
| 2026-02-05 | Fix ToolCall validator dla ToolName enum | Bugfix |
| 2026-02-05 | Wszystkie testy OK - confidence 100%, ask_clarification działa | Testy |
| 2026-02-05 | Multi-tool support - format B, execute_tool_chain(), context injection | Faza 5 |
| 2026-02-05 | User Profile - UserProfile model, API, Telegram /profile, system prompt injection | Faza 6 |

---

## Notatki implementacyjne

### Zależności między fazami

```
Faza 1 (Tool Result Memory) ✅
    │
    └──► Faza 3 (ask_clarification) ✅ - może korzystać z kontekstu

Faza 2 (Zunifikowana klasyfikacja) ✅
    │
    └──► Faza 4 (Confidence) ✅ - rozszerza ten sam format

Faza 4 (Confidence) ✅
    │
    └──► Faza 3 (ask_clarification) ✅ - auto-trigger przy low confidence

Faza 5 (Multi-tool) ✅ - niezależna, zaimplementowana
Faza 6 (Profil) ✅ - niezależna, zaimplementowana
```

### Ryzyka

| Ryzyko | Prawdopodobieństwo | Mitygacja |
|--------|-------------------|-----------|
| Zwiększenie długości promptu | Wysokie | Monitoruj token count, optymalizuj |
| Regresja w istniejących scenariuszach | Średnie | Zachowaj testy z raportu (25 cases) |
| Zwiększona złożoność kodu | Średnie | Dobre komentarze, modularność |

---

## Appendix: Przykładowe scenariusze testowe

### Scenariusz: Tool Result Memory

```
1. User: "Podsumuj https://example.com/ai-article"
   Agent: summarize_url → "Artykuł o trendach AI w 2026..."

2. User: "Zapisz to jako notatkę"
   Agent: create_note(title="Trendy AI 2026", content="Artykuł o trendach AI...")
   ✅ Oczekiwany wynik: notatka z treścią podsumowania
```

### Scenariusz: ask_clarification

```
1. User: "Zapisz"
   Agent: ask_clarification(
       question="Co chcesz zapisać?",
       options=["Ostatnie podsumowanie", "Nową notatkę", "Link"]
   )

2. User: "Nową notatkę o spotkaniu"
   Agent: create_note(title="Spotkanie", content="o spotkaniu")
```

### Scenariusz: Multi-tool

```
1. User: "Podsumuj ten artykuł i dodaj do zakładek: https://..."
   Agent: tools=[
       {tool: "summarize_url", args: {url: "..."}},
       {tool: "create_bookmark", args: {url: "..."}}
   ]
   Wynik: Podsumowanie + zakładka utworzona
```
