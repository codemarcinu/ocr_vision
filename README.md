# Second Brain

System zarządzania wiedzą osobistą z modułami: OCR paragonów, podsumowania RSS/stron, transkrypcje audio/wideo, notatki osobiste, zakładki, **baza wiedzy RAG** (zadawanie pytań do wszystkich zgromadzonych danych), **Chat AI** (wieloturowe rozmowy z RAG + wyszukiwanie SearXNG) i **Agent** (automatyczne akcje z języka naturalnego). Wykorzystuje Ollama LLM do ekstrakcji i kategoryzacji, **PostgreSQL + pgvector** do przechowywania danych i wyszukiwania semantycznego. Opcjonalna **synchronizacja Google Drive** umożliwia dostęp mobilny przez Gemini Custom Gem. Interfejsy: **Web UI** (HTMX), **Mobile PWA** i **REST API** z **walidacją human-in-the-loop**.

## Architektura

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Web UI (HTMX)  │     │    FastAPI      │     │     Ollama      │
│  Mobile PWA     │────▶│    Backend      │────▶│   (GPU)         │
│  REST API       │     │                 │     │                 │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                │
               ┌────────────────┼────────────────┐
               ▼                ▼                ▼
      ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐
      │ PostgreSQL  │  │   Obsidian  │  │   Google Drive  │
      │ + pgvector  │  │   vault/    │  │   (opcjonalny)  │
      └─────────────┘  └─────────────┘  └─────────────────┘

Moduły:
  OCR paragonów   - rozpoznawanie produktów i cen (5 backendów)
  RSS/Summarizer  - podsumowania artykułów
  Transkrypcje    - audio/wideo z map-reduce i Map of Content
  Notatki         - osobiste notatki z tagami + organizator
  Zakładki        - saved links
  RAG             - pytania do bazy wiedzy (/ask) + judge anty-halucynacyjny
  Chat AI         - wieloturowe rozmowy z RAG + web search (7 intencji)
  Agent           - automatyczne akcje z języka naturalnego (12 narzędzi)
  Analityka       - KPI karty, wykresy, CSV export
  Command Palette - Ctrl+K globalne wyszukiwanie i nawigacja
```

## Wymagania

- Docker z obsługą GPU (NVIDIA) lub CPU
- Docker Compose
- Ollama z modelami (patrz poniżej)

## Szybki start

### 1. Konfiguracja

Skopiuj i dostosuj plik `.env`:

```bash
cp .env.example .env
# Dostosuj zmienne środowiskowe (OCR_BACKEND, AUTH_TOKEN itp.)
```

### 2. Uruchom kontenery

```bash
docker-compose up -d
```

### 3. Pobierz modele Ollama

```bash
# Na hoście (Ollama musi być zainstalowane)
ollama pull qwen2.5:7b       # Kategoryzacja + strukturyzacja + odpowiedzi RAG (4.7GB)
ollama pull qwen2.5vl:7b     # Vision OCR + fallback (6GB)
ollama pull nomic-embed-text # Embeddingi dla bazy wiedzy RAG (274MB)

# Opcjonalnie (dla polskich treści - Chat AI, podsumowania)
ollama pull SpeakLeash/bielik-11b-v3.0-instruct:Q5_K_M  # Polski LLM (7GB)
```

### 4. Uruchom migrację bazy danych

```bash
docker exec -it pantry-api alembic upgrade head
```

### 5. Sprawdź status

```bash
curl http://localhost:8000/health
```

### 6. Otwórz interfejs

- **Web UI:** `http://localhost:8000/app/` - pełny interfejs desktopowy
- **Mobile PWA:** `http://localhost:8000/m/` - interfejs mobilny (instalowalny)
- **API docs:** `http://localhost:8000/docs` - Swagger UI

### 7. Przetwórz paragon

**Przez Web UI:**
- Otwórz dashboard → kliknij "Dodaj paragon" → wybierz zdjęcie/PDF (batch upload obsługiwany)

**Przez API:**
```bash
curl -X POST http://localhost:8000/process-receipt \
  -F "file=@paragon.png"
```

### 8. Zapytaj bazę wiedzy

Po zgromadzeniu danych (paragony, artykuły, transkrypcje):

**Przez Chat (Web UI / Mobile PWA):**
- Otwórz Chat → wpisz pytanie, np. "ile wydałem w Biedronce w styczniu?"

**Przez API:**
```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "ile wydałem w Biedronce?"}'
```

## Human-in-the-Loop

System automatycznie wykrywa potencjalne błędy OCR i prosi o weryfikację.

### Kiedy wymagana weryfikacja?

| Warunek | Próg | Przykład |
|---------|------|----------|
| Różnica absolutna | > 5 PLN | OCR: 84.50, Produkty: 144.48 |
| Różnica procentowa | > 10% | OCR: 100.00, Produkty: 88.00 |

### Przepływ weryfikacji

```
Paragon → OCR → Walidacja sumy
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
    Suma OK                 Suma błędna
         │                       │
         ▼                       ▼
    Auto-zapis              [Web UI Review]
                            ├─ Zatwierdź
                            ├─ Popraw sumę
                            │   ├─ Użyj sumy produktów
                            │   └─ Wpisz ręcznie
                            └─ Odrzuć
```

## Baza wiedzy (RAG)

System **Retrieval-Augmented Generation** umożliwia zadawanie pytań w języku naturalnym do całej zgromadzonej wiedzy.

### Jak to działa?

```
Pytanie użytkownika
    ↓
Embed pytania (nomic-embed-text, 768 dim)
    ↓
pgvector cosine similarity + keyword fallback (pg_trgm + Polish stems)
    ↓
Budowa kontekstu z najlepszych fragmentów
    ↓
LLM (qwen2.5:7b) generuje odpowiedź
    ↓
[opcjonalnie] Judge anty-halucynacyjny (RAG_JUDGE_ENABLED)
    ↓
Odpowiedź + lista źródeł
```

### Indeksowane typy treści

| Typ | Źródło |
|-----|--------|
| Paragony | Sklep, data, produkty, ceny |
| Artykuły | Podsumowania RSS i stron |
| Transkrypcje | Notatki z nagrań |
| Notatki | Notatki osobiste |
| Zakładki | Zapisane linki |

### Auto-indeksowanie

Nowe treści są automatycznie indeksowane w momencie tworzenia. Przy pierwszym uruchomieniu z pustą bazą embeddingów system automatycznie uruchamia pełną reindeksację w tle.

### Polish Stem Search

Wyszukiwanie keyword fallback wykorzystuje 4-znakowe stemmy polskie (np. "notatki"/"notatką" → "nota") z normalizacją diakrytyków NFD, co poprawia wyniki dla polskojęzycznych zapytań.

### Judge anty-halucynacyjny

Opcjonalny post-check (`RAG_JUDGE_ENABLED=false` domyślnie). Po wygenerowaniu odpowiedzi, osobny LLM ocenia czy odpowiedź jest wsparta kontekstem. Przy verdykcie WARN dodaje disclaimer. Podwaja liczbę wywołań LLM.

### API RAG

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/ask` | POST | Zadaj pytanie (`{"question": "..."}`) |
| `/ask/stats` | GET | Statystyki indeksu |
| `/ask/reindex` | POST | Pełna reindeksacja (w tle) |

## Chat AI

Wieloturowy asystent konwersacyjny z dostępem do bazy wiedzy (RAG) i wyszukiwania internetowego (SearXNG). Dostępny w Web UI (`/app/czat`) i Mobile PWA (`/m/`).

### Klasyfikacja intencji (7 typów)

Każda wiadomość jest klasyfikowana przez LLM do jednego z 7 typów intencji:

| Intencja | Opis | Temperatura |
|----------|------|-------------|
| `rag` | Dane osobiste (artykuły, notatki, zakładki) | 0.1 |
| `spending` | Analityka wydatków, ceny, koszty | 0.1 |
| `inventory` | Stan spiżarni, produkty, daty ważności | 0.1 |
| `weather` | Aktualna pogoda, prognoza | 0.1 |
| `web` | Wyszukiwanie internetowe, fakty | 0.3 |
| `both` | Hybryda - dane osobiste + internet | 0.3 |
| `direct` | Ogólna wiedza, rozmowa, matematyka | 0.5 |

Fallback: `rag` bez wyników → `web`; `web` bez wyników → `rag`.

### Integracja z Agentem (Tool-Calling)

Gdy `CHAT_AGENT_ENABLED=true`, chat automatycznie wykrywa intencje akcji:

```
Wiadomość użytkownika
    ↓
[Agent] Klasyfikacja: AKCJA czy ROZMOWA?
    ↓
┌───────────────┴───────────────┐
AKCJA                        ROZMOWA
(create_note, bookmark...)   (rag/web/both/direct/...)
    ↓                           ↓
Natychmiastowe wykonanie    Orchestrator + LLM
```

**Przykłady:**
- "Zanotuj: spotkanie jutro o 10" → Agent tworzy notatkę
- "Ile wydałem w Biedronce?" → Chat z RAG odpowiada
- "Jaka jest pogoda w Krakowie?" → OpenWeather API

### API Chat

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/chat/sessions` | POST | Utwórz sesję |
| `/chat/sessions` | GET | Lista sesji |
| `/chat/sessions/{id}/messages` | POST | Wyślij wiadomość |
| `/chat/sessions/{id}` | DELETE | Usuń sesję |

## Agent Tool-Calling

System automatycznego wykrywania intencji i wykonywania akcji z języka naturalnego. Obsługuje łańcuchy do 3 narzędzi (multi-tool chains) z przekazywaniem kontekstu.

### Dostępne narzędzia (12)

| Narzędzie | Opis | Przykład |
|-----------|------|----------|
| `create_note` | Tworzenie notatki | "Zanotuj: spotkanie jutro o 10" |
| `create_bookmark` | Zapisanie linku | "Zapisz ten link: https://..." |
| `summarize_url` | Podsumowanie strony | "Podsumuj ten artykuł: https://..." |
| `search_knowledge` | RAG - baza wiedzy | "Co wiem o projekcie X?" |
| `search_web` | Wyszukiwanie internetowe | "Najnowsze wiadomości o AI" |
| `get_spending` | Analityka wydatków | "Ile wydałem w Biedronce?" |
| `get_inventory` | Stan spiżarni | "Co mam w lodówce?" |
| `get_weather` | Pogoda | "Jaka jest pogoda w Krakowie?" |
| `list_recent` | Ostatnie elementy | "Pokaż ostatnie notatki" |
| `answer_directly` | Odpowiedź bez wyszukiwania | "Ile to 2+2?" |
| `ask_clarification` | Dopytanie o szczegóły | "Zapisz to" (bez kontekstu) |
| `organize_notes` | Organizacja notatek | "Zrób raport notatek" |

### Confidence scoring

Agent zwraca confidence score (0.0-1.0). Gdy confidence < `AGENT_CONFIDENCE_THRESHOLD` (domyślnie 0.6), automatycznie odpytuje użytkownika zamiast zgadywać.

### Włączenie agenta

```bash
CHAT_AGENT_ENABLED=true  # w .env
```

## Organizator notatek

Serwis zarządzania zdrowiem notatek (`app/services/notes_organizer.py`), dostępny przez agent tool `organize_notes` i API:

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/notes/organize/report` | POST | Raport zdrowia (bez tagów, bez kategorii, krótkie, duplikaty) |
| `/notes/organize/auto-tag` | POST | Auto-tagowanie LLM (batch 20, `dry_run` support) |
| `/notes/organize/duplicates` | POST | Wykrywanie duplikatów semantycznych (RAG, próg 0.85) |

## Transkrypcje audio/wideo

Transkrypcja nagrań (YouTube, pliki lokalne) z generowaniem notatek i ekstrakcją wiedzy.

### Funkcje

- **YouTube** - automatyczne pobieranie i transkrypcja filmów (yt-dlp)
- **Pliki audio** - MP3, M4A, WAV, OGG, OPUS
- **Faster-Whisper** - GPU-accelerated transkrypcja (model: medium)
- **Map-Reduce** - dla transkrypcji > 15k znaków: chunk → MAP → REDUCE
- **Map of Content** - kategoryzowany `index.md` z wiki-linkami
- **Notatki głosowe** - kolejkowanie i batch processing do daily notes
- **Auto-indeksowanie RAG** - transkrypcje automatycznie w bazie wiedzy

### Daily Notes

Voice memos są agregowane do jednego pliku dziennego z timestampami i YAML frontmatter (`app/writers/daily.py`). Konfiguracja: `VOICE_NOTE_PROCESS_INTERVAL_MINUTES=30`.

### API transkrypcji

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/transcription/jobs` | GET/POST | Lista/tworzenie zadań |
| `/transcription/jobs/upload` | POST | Upload pliku |
| `/transcription/jobs/{id}/note` | GET | Pobranie notatki |
| `/transcription/jobs/{id}/generate-note` | POST | Generowanie notatki |

## RSS/Web Summarizer

System subskrypcji kanałów RSS i podsumowywania stron internetowych za pomocą AI.

### Funkcje

- **Subskrypcje RSS/Atom** - dodawaj kanały i automatycznie pobieraj artykuły
- **Podsumowania na żądanie** - `/rss/summarize` generuje bullet points
- **Fetch on-demand** - pobieranie nowych artykułów przez API (`POST /rss/fetch`)
- **Zapis do Obsidian** - podsumowania w `vault/summaries/`
- **Auto-indeksowanie RAG** - nowe artykuły automatycznie trafiają do bazy wiedzy

### API RSS

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/rss/feeds` | GET | Lista feedów |
| `/rss/feeds` | POST | Dodaj feed |
| `/rss/summarize` | POST | Podsumuj URL |
| `/rss/articles` | GET | Lista artykułów |

## Notatki i zakładki

### Notatki osobiste

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/notes/` | GET | Lista notatek |
| `/notes/` | POST | Utwórz notatkę |
| `/notes/{id}` | GET/PUT/DELETE | CRUD notatki |

### Zakładki

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/bookmarks/` | GET | Lista zakładek |
| `/bookmarks/` | POST | Dodaj zakładkę |
| `/bookmarks/{id}` | GET/PUT/DELETE | CRUD zakładki |

## Google Drive Sync (opcjonalny)

Dwukierunkowa synchronizacja między Obsidian vault a Google Drive, umożliwiająca dostęp mobilny przez Gemini Custom Gem na Pixel.

### Architektura

- **rclone** działa na hoście jako systemd timer (co 5 min)
- Kontener Docker tylko czyta/zapisuje zamontowane wolumeny — nie ma zależności od rclone/Drive
- Opcjonalny monitor statusu (`/gdrive/status`) w kontenerze

### Co jest synchronizowane

| Folder | Kierunek | Wrażliwość |
|--------|----------|------------|
| `paragony/` | Host ↔ Drive | Średnia |
| `summaries/` | Host → Drive | Niska |
| `bookmarks/` | Host → Drive | Niska |
| `inbox/` | Drive → Host | N/A |

**Nigdy nie synchronizowane:** notes/, transcriptions/, daily/, logs/

### Setup

```bash
./scripts/setup-gdrive-sync.sh  # Interaktywna konfiguracja
```

Konfiguracja: `GDRIVE_SYNC_ENABLED` (monitoring), `FOLDER_WATCH_ENABLED` + `FOLDER_WATCH_INTERVAL_SECONDS` (auto-import z inbox).

## Prompty per sklep

System automatycznie wykrywa sklep i używa dedykowanego promptu LLM z regułami anty-halucynacyjnymi (ZAKAZANE/FORBIDDEN):

| Sklep | Obsługiwany format |
|-------|-------------------|
| **Biedronka** | `Produkt PTU Ilość×Cena Wartość` → `Rabat` → `CenaKońcowa` |
| **Lidl** | Nazwa w osobnej linii, poniżej `Ilość × Cena = Wartość` |
| **Kaufland** | Nazwa wielkimi literami, cena po prawej |
| **Żabka** | Prosty format: `Produkt Cena` |
| **Auchan** | Nazwa osobno, szczegóły poniżej |
| **Carrefour** | Produkt + cena w linii, rabat osobno |
| **Netto** | Prosty format jak Żabka |
| **Dino** | Nazwy wielkimi literami |
| **Lewiatan** | Prompt generyczny |
| **Polo Market** | Prompt generyczny |
| **Stokrotka** | Prompt generyczny |
| **Intermarché** | Prompt generyczny |

## Struktura projektu

```
ocr_vision/
├── docker-compose.yml      # Konfiguracja serwisów (pgvector, fastapi, searxng, monitoring)
├── Dockerfile              # NVIDIA CUDA + Python 3.11
├── requirements.txt        # Zależności Python
├── app/
│   ├── main.py             # Endpointy FastAPI + startup + pipeline OCR
│   ├── config.py           # Konfiguracja (env vars)
│   ├── models.py           # Modele Pydantic (Receipt, Product)
│   ├── dependencies.py     # FastAPI DI (14 repozytoriów + 1 sesja)
│   ├── model_coordinator.py # Koordynacja VRAM
│   ├── auth.py             # Uwierzytelnianie (opcjonalne)
│   ├── rate_limit.py       # Rate limiting (slowapi)
│   ├── ocr/                # Backendy OCR (8 plików)
│   │   ├── vision.py       # Vision OCR (domyślny)
│   │   ├── deepseek.py     # DeepSeek OCR
│   │   ├── google_backend.py # Google Vision OCR
│   │   ├── openai_backend.py # Google Vision + OpenAI structuring
│   │   ├── paddle.py       # PaddleOCR
│   │   ├── google_vision.py # Google Cloud Vision API (utility)
│   │   └── prompts.py      # Prompty OCR + reguły ZAKAZANE
│   ├── web/                # Web UI (HTMX + Jinja2) - 14 modułów + command palette
│   │   ├── dashboard.py    # Dashboard
│   │   ├── receipts.py     # Przeglądanie paragonów
│   │   ├── pantry.py       # Spiżarnia
│   │   ├── analytics.py    # Statystyki, KPI karty, CSV export
│   │   ├── chat.py         # Interfejs Chat AI
│   │   ├── notes.py        # Notatki
│   │   ├── bookmarks.py    # Zakładki
│   │   ├── articles.py     # Artykuły RSS
│   │   ├── transcriptions.py # Transkrypcje
│   │   ├── dictionary.py   # Słownik produktów
│   │   ├── search.py       # Wyszukiwanie
│   │   ├── ask.py          # Pytania RAG
│   │   ├── command_palette.py # Ctrl+K globalne wyszukiwanie
│   │   ├── helpers.py      # Współdzielone utility
│   │   └── redirects.py    # Przekierowania /web/* → /app/*
│   ├── writers/            # Generowanie markdown (Obsidian) - 5 writerów
│   │   ├── obsidian.py     # Paragony, spiżarnia, logi
│   │   ├── notes.py        # Notatki
│   │   ├── bookmarks.py    # Zakładki
│   │   ├── summary.py      # Podsumowania RSS
│   │   └── daily.py        # Daily notes (aggregacja voice memos)
│   ├── chat/               # Chat AI (8 plików)
│   │   ├── orchestrator.py       # Orkiestracja + per-intent temperature
│   │   ├── intent_classifier.py  # Klasyfikacja 7 intencji
│   │   ├── agent_executor.py     # Wykonawcy narzędzi agenta
│   │   ├── history_manager.py    # Historia sesji + sumaryzacja
│   │   ├── content_fetcher.py    # Pobieranie kontekstu RAG
│   │   ├── data_tools.py         # Spending, inventory, weather helpers
│   │   ├── searxng_client.py     # Klient SearXNG
│   │   └── weather_client.py     # Klient OpenWeather API
│   ├── agent/              # Agent Tool-Calling
│   │   ├── tools.py        # 12 narzędzi + modele Pydantic
│   │   ├── router.py       # Router LLM → tool dispatch + retry
│   │   └── validator.py    # Walidacja inputu, ochrona przed injection
│   ├── rag/                # Baza wiedzy RAG
│   │   ├── embedder.py     # Embeddingi via Ollama (768 dim)
│   │   ├── indexer.py      # Chunking + embedding + storage
│   │   ├── retriever.py    # Vector search + keyword + Polish stems
│   │   ├── answerer.py     # Generowanie odpowiedzi + judge
│   │   └── hooks.py        # Auto-indexing hooks (fire-and-forget)
│   ├── transcription/      # Transkrypcje Whisper
│   │   ├── transcriber.py  # Faster-Whisper (GPU)
│   │   ├── downloader.py   # yt-dlp
│   │   ├── extractor.py    # Map-reduce ekstrakcja wiedzy
│   │   └── note_writer.py  # Markdown notatki + Map of Content
│   ├── services/           # Serwisy biznesowe (5)
│   │   ├── receipt_saver.py    # Receipt → DB + Obsidian + RAG
│   │   ├── obsidian_sync.py    # Regeneracja vaulta z DB
│   │   ├── notes_organizer.py  # Raport, auto-tag, duplikaty
│   │   ├── push_service.py     # Web Push notifications
│   │   └── gdrive_sync.py     # Google Drive sync monitor (read-only)
│   ├── db/
│   │   ├── connection.py   # Async engine + session factory
│   │   ├── models.py       # SQLAlchemy ORM (26 modeli)
│   │   └── repositories/   # Repozytoria (16 plików)
│   ├── push/               # Web Push notification hooks
│   ├── dictionaries/       # Normalizacja produktów/sklepów (JSON)
│   ├── templates/          # Jinja2 szablony (60 plików)
│   │   ├── mobile/         # PWA templates (osobny base.html)
│   │   ├── components/     # Reusable: navbar, pagination, metric_card
│   │   └── [feature]/      # dashboard, receipts, pantry, analytics, ...
│   ├── static/             # CSS/JS (htmx, marked, purify, sw.js, command-palette.js)
│   ├── mobile_routes.py    # Mobile PWA (/m/)
│   ├── *_api.py            # Routery API per moduł (14 routerów)
│   ├── classifier.py       # Kategoryzacja produktów (LLM + cache)
│   └── store_prompts.py    # Prompty per sklep + reguły FORBIDDEN
├── alembic/                # Migracje bazy danych (11 wersji)
├── scripts/                # Skrypty narzędziowe (14 plików)
├── searxng/                # Konfiguracja SearXNG
├── monitoring/             # Prometheus/Grafana/Loki
├── paragony/
│   ├── inbox/              # Folder wejściowy (auto-import z GDrive)
│   └── processed/          # Archiwum
└── vault/
    ├── paragony/           # Historia paragonów (.md)
    ├── bookmarks/          # Zakładki
    ├── transcriptions/     # Transkrypcje + index.md (MoC)
    ├── daily/              # Daily notes (voice memos)
    └── logs/               # Logi i feedback
```

## Konfiguracja

Zmienne środowiskowe (w `docker-compose.yml` lub `.env`):

| Zmienna | Domyślnie | Opis |
|---------|-----------|------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | URL Ollama API |
| `OCR_MODEL` | `qwen2.5vl:7b` | Model OCR (vision) |
| `OCR_BACKEND` | `vision` | `vision`, `deepseek`, `paddle`, `google`, lub `openai` |
| `CLASSIFIER_MODEL` | `qwen2.5:7b` | Model kategoryzacji i strukturyzacji |
| `OPENAI_API_KEY` | - | Klucz API OpenAI (wymagany dla `OCR_BACKEND=openai`) |
| `RAG_ENABLED` | `true` | Włącz/wyłącz bazę wiedzy RAG |
| `RAG_JUDGE_ENABLED` | `false` | Judge anty-halucynacyjny (podwaja wywołania LLM) |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Model embeddingów |
| `CHAT_ENABLED` | `true` | Włącz/wyłącz Chat AI |
| `CHAT_MODEL` | `` | Model LLM dla chatu (pusty = CLASSIFIER_MODEL) |
| `CHAT_AGENT_ENABLED` | `true` | Agent tool-calling w Chat AI |
| `AGENT_CONFIDENCE_THRESHOLD` | `0.6` | Próg confidence (poniżej = dopytanie) |
| `AUTH_TOKEN` | - | Token uwierzytelniania (pusty = wyłączone) |
| `MODEL_COORDINATION_ENABLED` | `true` | Koordynacja VRAM |
| `MODEL_MAX_VRAM_MB` | `12000` | Budżet VRAM w MB |
| `GDRIVE_SYNC_ENABLED` | `false` | Monitor synchronizacji Google Drive |
| `FOLDER_WATCH_ENABLED` | `false` | Auto-import z folderu inbox |
| `PUSH_ENABLED` | `false` | Web Push notifications (PWA) |

Pełna lista zmiennych: patrz [CLAUDE.md](CLAUDE.md).

### Koordynacja modeli (VRAM)

System automatycznie zarządza modelami Ollama w ograniczonym VRAM:
- **LRU eviction** - zwalnia pamięć usuwając najdawniej używane modele
- **Preloading** - ładuje model przy starcie (`MODEL_PRELOAD_ON_STARTUP`)
- **Single-model OCR** - tryb `OCR_SINGLE_MODEL_MODE=true` używa jednego modelu do wszystkiego
- **Waiter counting** - unika wyładowania modeli z oczekującymi requestami

Sprawdź status modeli: `curl http://localhost:8000/models/status`

### Uwierzytelnianie (opcjonalne)

Ustaw `AUTH_TOKEN` aby włączyć ochronę API i Web UI:
- API wymaga nagłówka `Authorization: Bearer <token>`
- Web UI używa sesji z `/login` i `/logout`
- Publiczne endpointy nie wymagające auth: `/health`, `/metrics`, `/gdrive/status`, `/login`, `/logout`, `/static`, `/sw.js`, `/manifest.json`, `/favicon.ico`
- Mobile PWA obsługuje offline caching i request queue

## Endpointy operacyjne

| Endpoint | Opis |
|----------|------|
| `GET /health` | Sprawdza status serwisów |
| `GET /models/status` | VRAM, załadowane modele, metryki eviction |
| `GET /gdrive/status` | Status synchronizacji Google Drive |
| `GET /metrics` | Metryki Prometheus |
| `GET /docs` | Swagger UI (auto-docs) |

## Monitorowanie

Opcjonalny stack Prometheus + Grafana + Loki:

```bash
http://localhost:3000   # Grafana (admin/pantry123)
http://localhost:9090   # Prometheus
http://localhost:3100   # Loki
```

Metryki FastAPI: `GET /metrics`

## Dokumentacja

- [docs/QUICK_START.md](docs/QUICK_START.md) - Szybki start
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) - Przewodnik użytkownika
- [CLAUDE.md](CLAUDE.md) - Pełna dokumentacja techniczna
