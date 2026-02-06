# Second Brain

System zarządzania wiedzą osobistą z modułami: OCR paragonów, podsumowania RSS/stron, transkrypcje audio/wideo, notatki osobiste, zakładki, **baza wiedzy RAG** (zadawanie pytań do wszystkich zgromadzonych danych) i **Chat AI** (wieloturowe rozmowy z RAG + wyszukiwanie SearXNG). Wykorzystuje Ollama LLM do ekstrakcji i kategoryzacji, **PostgreSQL + pgvector** do przechowywania danych i wyszukiwania semantycznego. Interfejsy: **Web UI** (HTMX), **Mobile PWA** i **REST API** z **walidacją human-in-the-loop**.

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
      │ PostgreSQL  │  │   Obsidian  │  │  pgvector RAG   │
      │ + pgvector  │  │   vault/    │  │  embeddingi     │
      └─────────────┘  └─────────────┘  └─────────────────┘

Moduły:
📸 OCR paragonów  → rozpoznawanie produktów i cen
📰 RSS/Summarizer → podsumowania artykułów
🎙️ Transkrypcje   → audio/wideo → notatki
📝 Notatki        → osobiste notatki z tagami
🔖 Zakładki       → saved links
🧠 RAG            → pytania do bazy wiedzy (/ask)
💬 Chat AI        → wieloturowe rozmowy z RAG + web search
🤖 Agent          → automatyczne akcje z języka naturalnego
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
- Otwórz dashboard → kliknij "Dodaj paragon" → wybierz zdjęcie/PDF

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
pgvector cosine similarity search (top-K)
    ↓
Budowa kontekstu z najlepszych fragmentów
    ↓
LLM (qwen2.5:7b) generuje odpowiedź
    ↓
Odpowiedź + lista źródeł
```

### Indeksowane typy treści

| Typ | Źródło |
|-----|--------|
| 🧾 Paragony | Sklep, data, produkty, ceny |
| 📰 Artykuły | Podsumowania RSS i stron |
| 🎙️ Transkrypcje | Notatki z nagrań |
| 📝 Notatki | Notatki osobiste |
| 🔖 Zakładki | Zapisane linki |

### Auto-indeksowanie

Nowe treści są automatycznie indeksowane w momencie tworzenia. Przy pierwszym uruchomieniu z pustą bazą embeddingów system automatycznie uruchamia pełną reindeksację w tle.

### API RAG

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/ask` | POST | Zadaj pytanie (`{"question": "..."}`) |
| `/ask/stats` | GET | Statystyki indeksu |
| `/ask/reindex` | POST | Pełna reindeksacja (w tle) |

## Chat AI

Wieloturowy asystent konwersacyjny z dostępem do bazy wiedzy (RAG) i wyszukiwania internetowego (SearXNG). Dostępny w Web UI (`/app/chat`) i Mobile PWA (`/m/chat`).

### Integracja z Agentem (Tool-Calling)

Gdy `CHAT_AGENT_ENABLED=true`, chat automatycznie wykrywa intencje akcji:

```
Wiadomość użytkownika
    ↓
[Agent] Klasyfikacja: AKCJA czy ROZMOWA?
    ↓
┌───────────────┴───────────────┐
AKCJA                        ROZMOWA
(create_note, bookmark...)   (rag/web/both/direct)
    ↓                           ↓
Natychmiastowe wykonanie    Orchestrator + LLM
```

**Przykłady:**
- "Zanotuj: spotkanie jutro o 10" → Agent tworzy notatkę
- "Ile wydałem w Biedronce?" → Chat z RAG odpowiada

### API Chat

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/chat/sessions` | POST | Utwórz sesję |
| `/chat/sessions` | GET | Lista sesji |
| `/chat/sessions/{id}/messages` | POST | Wyślij wiadomość |
| `/chat/sessions/{id}` | DELETE | Usuń sesję |

## Agent Tool-Calling

System automatycznego wykrywania intencji i wykonywania akcji z języka naturalnego.

### Dostępne narzędzia

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

### Włączenie agenta

```bash
CHAT_AGENT_ENABLED=true  # w .env
```

Agent jest zintegrowany z Chat AI i działa automatycznie jako pre-procesor wiadomości.

## RSS/Web Summarizer

System umożliwia subskrypcję kanałów RSS i podsumowywanie stron internetowych za pomocą AI.

### Funkcje

- **Subskrypcje RSS/Atom** - dodawaj kanały i automatycznie pobieraj artykuły
- **Podsumowania na żądanie** - `/summarize <URL>` generuje bullet points
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

## Transkrypcje audio/wideo

Transkrypcja nagrań (YouTube, pliki lokalne) z generowaniem notatek.

### Funkcje

- **YouTube** - automatyczne pobieranie i transkrypcja filmów
- **Pliki audio** - MP3, M4A, WAV, OGG, OPUS
- **Faster-Whisper** - GPU-accelerated transkrypcja
- **Notatki AI** - podsumowanie, tematy, encje, zadania
- **Auto-indeksowanie RAG** - transkrypcje automatycznie w bazie wiedzy

### API transkrypcji

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/transcription/jobs` | GET/POST | Lista/tworzenie zadań |
| `/transcription/jobs/upload` | POST | Upload pliku |
| `/transcription/jobs/{id}/note` | GET | Pobranie notatki |
| `/transcription/jobs/{id}/generate-note` | POST | Generowanie notatki |

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
│   ├── dependencies.py     # FastAPI DI (repozytoria)
│   ├── model_coordinator.py # Koordynacja VRAM
│   ├── auth.py             # Uwierzytelnianie (opcjonalne)
│   ├── ocr/                # Backendy OCR
│   │   ├── vision.py       # Vision OCR (domyślny)
│   │   ├── deepseek.py     # DeepSeek OCR
│   │   ├── google_backend.py # Google Vision OCR
│   │   ├── openai_backend.py # Google Vision + OpenAI structuring
│   │   ├── paddle.py       # PaddleOCR
│   │   ├── google_vision.py # Google Cloud Vision API (utility)
│   │   └── prompts.py      # Prompty OCR
│   ├── web/                # Web UI (HTMX + Jinja2) - 14 modułów
│   │   ├── dashboard.py    # Dashboard
│   │   ├── receipts.py     # Przeglądanie paragonów
│   │   ├── pantry.py       # Spiżarnia
│   │   ├── analytics.py    # Statystyki i wykresy
│   │   ├── chat.py         # Interfejs Chat AI
│   │   ├── notes.py        # Notatki
│   │   ├── bookmarks.py    # Zakładki
│   │   ├── articles.py     # Artykuły RSS
│   │   ├── transcriptions.py # Transkrypcje
│   │   ├── dictionary.py   # Słownik produktów
│   │   ├── search.py       # Wyszukiwanie
│   │   ├── ask.py          # Pytania RAG
│   │   ├── helpers.py      # Współdzielone utility
│   │   └── redirects.py    # Przekierowania
│   ├── writers/            # Generowanie markdown (Obsidian)
│   │   ├── obsidian.py     # Paragony, spiżarnia, logi
│   │   ├── notes.py        # Notatki
│   │   ├── bookmarks.py    # Zakładki
│   │   └── summary.py      # Podsumowania RSS
│   ├── chat/               # Chat AI
│   │   ├── intent_classifier.py  # Klasyfikacja intencji (rag/web/both/direct)
│   │   ├── orchestrator.py       # Orkiestracja rozmowy
│   │   ├── agent_executor.py     # Wykonawcy narzędzi agenta
│   │   └── searxng_client.py     # Klient SearXNG
│   ├── agent/              # Agent Tool-Calling
│   │   ├── tools.py        # Definicje narzędzi (11 narzędzi)
│   │   ├── router.py       # Router LLM → tool dispatch
│   │   └── validator.py    # Walidacja inputu, ochrona przed injection
│   ├── rag/                # Baza wiedzy RAG
│   │   ├── embedder.py     # Embeddingi via Ollama
│   │   ├── indexer.py      # Chunking + embedding + storage
│   │   ├── retriever.py    # Vector search (pgvector)
│   │   ├── answerer.py     # Generowanie odpowiedzi (PL/EN)
│   │   └── hooks.py        # Auto-indexing hooks
│   ├── db/
│   │   ├── models.py       # SQLAlchemy ORM
│   │   └── repositories/   # Repozytoria (16 plików)
│   ├── transcription/      # Transkrypcje Whisper
│   │   ├── transcriber.py  # Faster-Whisper (GPU)
│   │   ├── downloader.py   # yt-dlp
│   │   └── extractor.py    # Map-reduce ekstrakcja wiedzy
│   ├── services/           # Serwisy (receipt_saver, push, obsidian_sync)
│   ├── push/               # Web Push notifications
│   ├── dictionaries/       # Normalizacja produktów/sklepów
│   ├── templates/          # Jinja2 szablony (Web UI + Mobile)
│   ├── static/             # CSS/JS (htmx, marked, purify, sw.js)
│   ├── mobile_routes.py    # Mobile PWA (/m/)
│   ├── *_api.py            # Routery API per moduł
│   ├── classifier.py       # Kategoryzacja produktów (LLM + cache)
│   └── store_prompts.py    # Prompty per sklep (12 sklepów)
├── alembic/                # Migracje bazy danych
├── searxng/                # Konfiguracja SearXNG
├── monitoring/             # Prometheus/Grafana/Loki
├── paragony/
│   ├── inbox/              # Folder wejściowy
│   └── processed/          # Archiwum
└── vault/
    ├── paragony/           # Historia paragonów (.md)
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
| `OPENAI_OCR_MODEL` | `gpt-4o-mini` | Model OpenAI do strukturyzacji |
| `RAG_ENABLED` | `true` | Włącz/wyłącz bazę wiedzy RAG |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Model embeddingów |
| `RAG_AUTO_INDEX` | `true` | Auto-indeksowanie nowej treści |
| `RAG_TOP_K` | `5` | Ilość fragmentów do wyszukania |
| `CHAT_ENABLED` | `true` | Włącz/wyłącz Chat AI |
| `CHAT_MODEL` | `` | Model LLM dla chatu (pusty = CLASSIFIER_MODEL) |
| `SEARXNG_URL` | `http://searxng:8080` | URL instancji SearXNG |
| `AUTH_TOKEN` | - | Token uwierzytelniania API/Web (pusty = wyłączone) |
| `CHAT_AGENT_ENABLED` | `true` | Agent tool-calling w Chat AI |
| `MODEL_COORDINATION_ENABLED` | `true` | Koordynacja VRAM (zarządzanie modelami) |
| `MODEL_MAX_VRAM_MB` | `12000` | Budżet VRAM w MB |

Pełna lista zmiennych: patrz [CLAUDE.md](CLAUDE.md).

### Koordynacja modeli (VRAM)

System automatycznie zarządza modelami Ollama w ograniczonym VRAM:
- **LRU eviction** - zwalnia pamięć usuwając najdawniej używane modele
- **Preloading** - ładuje model przy starcie (`MODEL_PRELOAD_ON_STARTUP`)
- **Single-model OCR** - tryb `OCR_SINGLE_MODEL_MODE=true` używa jednego modelu do wszystkiego

Sprawdź status modeli: `curl http://localhost:8000/models/status`

### Uwierzytelnianie (opcjonalne)

Ustaw `AUTH_TOKEN` aby włączyć ochronę API i Web UI:
- API wymaga nagłówka `Authorization: Bearer <token>`
- Web UI używa sesji z `/login` i `/logout`
- Publiczne endpointy (`/health`, `/docs`, `/metrics`) nie wymagają auth
- Mobile PWA obsługuje offline caching i request queue

## Prompty per sklep

System automatycznie wykrywa sklep i używa dedykowanego promptu LLM:

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

## API

### `GET /health`

Sprawdza status serwisów.

### `GET /models/status`

Status koordynatora modeli: VRAM, załadowane modele, metryki eviction.

### `POST /process-receipt`

Przetwarza paragon (zdjęcie lub PDF).

### `POST /ask`

Zadaj pytanie do bazy wiedzy.

**Request:**
```json
{"question": "ile wydałem w Biedronce w styczniu?"}
```

**Odpowiedź:**
```json
{
  "answer": "Na podstawie paragonów...",
  "sources": [
    {"content_type": "receipt", "label": "Paragon: Biedronka | 2026-01-05"}
  ],
  "model_used": "qwen2.5:7b",
  "chunks_found": 5,
  "processing_time_sec": 2.3
}
```

### `GET /ask/stats`

Statystyki indeksu embeddingów (ilość per typ treści).

### `POST /ask/reindex`

Pełna reindeksacja całej bazy wiedzy (uruchamiana w tle).

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
