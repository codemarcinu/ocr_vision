# Raport: Testy Agent Tool-Calling

**Data:** 2026-02-04
**Testowane modele:** qwen2.5:7b, qwen2.5:14b, deepseek-r1:latest
**Liczba narzędzi:** 10
**Liczba test case'ów:** 25

## Podsumowanie wyników

| Model | JSON | Tool | Args | Full Pass | Avg Time |
|-------|------|------|------|-----------|----------|
| **qwen2.5:7b** | 25/25 (100%) | 25/25 (100%) | 25/25 (100%) | **25/25 (100%)** | 4.2s |
| **qwen2.5:14b** | 25/25 (100%) | 25/25 (100%) | 25/25 (100%) | **25/25 (100%)** | 6.3s |
| deepseek-r1:latest | 11/25 (44%) | 11/25 (44%) | 10/25 (40%) | 10/25 (40%) | 8.6s |

## Wnioski

### qwen2.5:7b — **REKOMENDOWANY**
- **100% skuteczności** we wszystkich kryteriach
- Najszybszy czas odpowiedzi (średnio 4.2s)
- Doskonale radzi sobie z polskim językiem naturalnym
- Poprawnie wybiera narzędzie nawet dla niejednoznacznych przypadków (np. "co mam w lodówce?" → `get_inventory`)
- Prawidłowo ekstrahuje argumenty (sklep, okres, URL, treść notatki)

### qwen2.5:14b — alternatywa
- **100% skuteczności** — identyczna z mniejszym modelem
- Wolniejszy o ~50% (6.3s vs 4.2s)
- Brak przewagi jakościowej nad qwen2.5:7b w tym benchmarku
- **Wniosek:** Dla tool-callingu nie ma sensu używać większego modelu

### deepseek-r1:latest — **NIE NADAJE SIĘ**
- Model rozumujący (reasoning) z chain-of-thought
- Problem: **nie wspiera `format=json`** w Ollama — zwraca puste odpowiedzi
- Gdy zwraca odpowiedź, często zawiera `<think>` tagi które psują JSON
- 40% skuteczności to wyłącznie przypadki, gdzie model sam z siebie zwrócił poprawny JSON
- **Wniosek:** Nie używać do tool-callingu bez dodatkowej logiki parsowania

## Szczegółowe wyniki per kategoria

### A: Proste wywołania (8 testów)
Wszystkie modele: 100% poprawnych

| Test | Input | qwen2.5:7b | qwen2.5:14b |
|------|-------|------------|-------------|
| #1 | "Zapisz notatkę: jutro spotkanie..." | ✅ create_note | ✅ create_note |
| #2 | "Ile wydałem w Biedronce w tym miesiącu?" | ✅ get_spending | ✅ get_spending |
| #3 | "Jaka jest pogoda?" | ✅ get_weather | ✅ get_weather |
| #4 | "Podsumuj ten artykuł: https://..." | ✅ summarize_url | ✅ summarize_url |
| #5 | "Pokaż moje ostatnie notatki" | ✅ list_recent | ✅ list_recent |
| #6 | "Wyszukaj w internecie najnowsze wiadomości o AI" | ✅ search_web | ✅ search_web |
| #7 | "Zapisz ten link na później: https://..." | ✅ create_bookmark | ✅ create_bookmark |
| #8 | "Co miałem w moich notatkach o projekcie X?" | ✅ search_knowledge | ✅ search_knowledge |

### B: Styl głosówki (4 testy)
Wszystkie modele: 100% poprawnych

| Test | Input | Wynik |
|------|-------|-------|
| #9 | "Hej, zapisz mi że jutro mam dentystę o 10" | ✅ create_note |
| #10 | "Zanotuj: kupić mleko, chleb i masło" | ✅ create_note |
| #11 | "Przypomnij mi żeby zadzwonić do mamy w piątek" | ✅ create_note |
| #12 | "Hej, chcę zapisać linka https://... do przeczytania" | ✅ create_bookmark |

### C: Niejednoznaczne / wymagające rozumowania (6 testów)
Wszystkie modele: 100% poprawnych

| Test | Input | Wynik | Komentarz |
|------|-------|-------|-----------|
| #13 | "Co mam w lodówce?" | ✅ get_inventory | Potoczne wyrażenie → spiżarnia |
| #14 | "Co czytałem ostatnio o machine learning?" | ✅ search_knowledge | Osobista baza wiedzy |
| #15 | "Gdzie najczęściej robię zakupy?" | ✅ get_spending | Analityka wydatków |
| #16 | "Jakie produkty mi się kończą?" | ✅ get_inventory | Stan spiżarni |
| #17 | "Ile kalorii ma jabłko?" | ✅ answer_directly | Wiedza ogólna |
| #18 | "Porównaj moje wydatki z tego i poprzedniego tygodnia" | ✅ get_spending | Z argumentem period |

### D: Przypadki brzegowe (4 testy)
Wszystkie modele: 100% poprawnych

| Test | Input | Wynik |
|------|-------|-------|
| #19 | "Cześć!" | ✅ answer_directly |
| #20 | "2 + 2 * 3" | ✅ answer_directly |
| #21 | "https://arxiv.org/abs/2401.12345" (sam URL) | ✅ summarize_url |
| #22 | "Pokaż ostatnie 3 paragony" | ✅ list_recent (z limit=3) |

### E: Wieloaspektowe (3 testy)
Wszystkie modele: 100% poprawnych

| Test | Input | Wynik |
|------|-------|-------|
| #23 | "Na co wydaję najwięcej pieniędzy?" | ✅ get_spending |
| #24 | "Jakie artykuły zapisałem w tym tygodniu?" | ✅ list_recent (14b) / search_knowledge (7b) — oba akceptowalne |
| #25 | "Pogoda w Krakowie na weekend" | ✅ get_weather (z city=Kraków) |

## Rekomendacje do implementacji

### 1. Użyć qwen2.5:7b jako "mózg" agenta
- Najlepszy stosunek jakości do szybkości
- Zużywa ~4.7GB VRAM
- 100% skuteczności w benchmarku

### 2. System prompt już działa dobrze
Użyty prompt:
```
Jesteś asystentem osobistego systemu zarządzania wiedzą (Second Brain).
Na podstawie wiadomości użytkownika wybierz JEDNO narzędzie do wywołania i podaj argumenty.

Dostępne narzędzia:
[lista 10 narzędzi z opisami po polsku]

Odpowiedz WYŁĄCZNIE poprawnym JSON w formacie:
{"tool": "nazwa_narzędzia", "arguments": {"param1": "wartość1"}}
```

### 3. Opcja `format="json"` w Ollama jest kluczowa
- Wymusza output w formacie JSON
- Eliminuje problemy z parsowaniem
- deepseek-r1 jej nie wspiera — nie używać tego modelu

### 4. Architektura agenta
Proponowany przepływ:
```
User Input (tekst/głosówka)
    ↓
qwen2.5:7b + format=json
    ↓
{"tool": "...", "arguments": {...}}
    ↓
Tool Router (switch/match na nazwie narzędzia)
    ↓
Wykonanie akcji (create_note, search_knowledge, etc.)
    ↓
Wynik do użytkownika
```

### 5. Co dalej?
1. **Zaimplementować Tool Router** — dispatcher wywołujący odpowiednie funkcje systemu
2. **Dodać walidację argumentów** — przed wykonaniem sprawdzić typy/wymagane pola
3. **Obsługa błędów** — co jeśli narzędzie nie istnieje lub argumenty są niepoprawne
4. **Multi-step agents** — pozwolić na łańcuch wywołań narzędzi
5. **Integracja z Telegram** — nowy handler `/agent` lub zamiana istniejącego `/chat`

## Testowane narzędzia

| # | Narzędzie | Opis |
|---|-----------|------|
| 1 | `create_note` | Tworzenie notatki |
| 2 | `search_knowledge` | RAG - przeszukiwanie bazy wiedzy |
| 3 | `search_web` | Wyszukiwanie w internecie (SearXNG) |
| 4 | `get_spending` | Analityka wydatków |
| 5 | `get_inventory` | Stan spiżarni |
| 6 | `get_weather` | Pogoda |
| 7 | `summarize_url` | Streszczenie artykułu |
| 8 | `list_recent` | Lista ostatnich elementów |
| 9 | `create_bookmark` | Tworzenie zakładki |
| 10 | `answer_directly` | Bezpośrednia odpowiedź |

## Pliki

- Test script: `scripts/test_agent_tools.py`
- Ten raport: `docs/agent_tool_calling_report.md`
