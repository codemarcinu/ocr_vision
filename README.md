# Second Brain

System zarządzania wiedzą osobistą z modułami: OCR paragonów, podsumowania RSS/stron, transkrypcje audio/wideo, notatki osobiste, zakładki i **baza wiedzy RAG** (zadawanie pytań do wszystkich zgromadzonych danych). Wykorzystuje Ollama LLM do ekstrakcji i kategoryzacji, **PostgreSQL + pgvector** do przechowywania danych i wyszukiwania semantycznego. Bot Telegram z menu inline keyboard i **walidacją human-in-the-loop**.

## Architektura

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Telegram Bot   │     │    FastAPI      │     │     Ollama      │
│  lub paragony/  │────▶│    Backend      │────▶│   (GPU)         │
│  inbox/         │     │                 │     │                 │
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
```

## Wymagania

- Docker z obsługą GPU (NVIDIA) lub CPU
- Docker Compose
- Ollama z modelami (patrz poniżej)
- Token bota Telegram (opcjonalnie)

## Szybki start

### 1. Konfiguracja

Skopiuj i dostosuj plik `.env`:

```bash
cp .env.example .env
# Edytuj TELEGRAM_BOT_TOKEN i TELEGRAM_CHAT_ID
```

### 2. Uruchom kontenery

```bash
docker-compose up -d
```

### 3. Pobierz modele Ollama

```bash
# Na hoście (Ollama musi być zainstalowane)
ollama pull deepseek-ocr     # OCR (szybki, zalecany)
ollama pull qwen2.5:7b       # Kategoryzacja + strukturyzacja + odpowiedzi RAG
ollama pull qwen2.5vl:7b     # Fallback OCR (dla trudnych paragonów)
ollama pull nomic-embed-text # Embeddingi dla bazy wiedzy RAG (274MB)

# Opcjonalnie (dla polskich treści)
ollama pull SpeakLeash/bielik-11b-v3.0-instruct:Q5_K_M  # Polski LLM
```

### 4. Uruchom migrację bazy danych

```bash
docker exec -it pantry-api alembic upgrade head
```

### 5. Sprawdź status

```bash
curl http://localhost:8000/health
```

### 6. Przetwórz paragon

**Via Telegram (zalecane):**
- Wyślij zdjęcie lub PDF do bota
- Bot przetworzy i pokaże wynik (lub poprosi o weryfikację)

**Via API:**
```bash
curl -X POST http://localhost:8000/process-receipt \
  -F "file=@paragon.png"
```

### 7. Zapytaj bazę wiedzy

Po zgromadzeniu danych (paragony, artykuły, transkrypcje):

**Przez Telegram:**
```
/ask ile wydałem w Biedronce w styczniu?
/ask co wiem o sztucznej inteligencji?
```

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

### Przepływ weryfikacji (Telegram)

```
Paragon → OCR → Walidacja sumy
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
    Suma OK                 Suma błędna
         │                       │
         ▼                       ▼
    Auto-zapis              [Telegram Review]
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

## Telegram Bot - Komendy

| Komenda | Opis |
|---------|------|
| Wyślij zdjęcie | Przetwórz paragon |
| Wyślij PDF | Przetwórz paragon (wielostronicowy) |
| `/recent [N]` | Ostatnie N paragonów |
| `/reprocess <plik>` | Ponowne przetwarzanie |
| `/pending` | Pliki w kolejce |
| `/pantry [kategoria]` | Zawartość spiżarni |
| `/use <produkt>` | Oznacz jako zużyty |
| `/search <fraza>` | Szukaj produktu |
| `/stats [week/month]` | Statystyki wydatków |
| `/stores` | Wydatki wg sklepów |
| `/categories` | Wydatki wg kategorii |
| `/rabaty` | Raport rabatów |
| `/errors` | Lista błędów OCR |
| `/feeds` | Lista subskrybowanych kanałów RSS |
| `/subscribe <URL>` | Dodaj kanał RSS/Atom |
| `/unsubscribe <ID>` | Usuń kanał RSS |
| `/summarize <URL>` | Podsumuj stronę internetową |
| `/refresh` | Pobierz nowe artykuły |
| `/articles` | Lista ostatnich artykułów |
| `/transcribe <URL>` | Transkrybuj YouTube |
| `/transcribe` + audio | Transkrybuj przesłany plik |
| `/transcriptions` | Lista transkrypcji |
| `/note <ID>` | Notatka z transkrypcji |
| `/ask <pytanie>` | Zapytaj bazę wiedzy (RAG) |

## RSS/Web Summarizer

System zawiera agenta do subskrypcji kanałów RSS i podsumowywania stron internetowych.

### Funkcje

- **Subskrypcje RSS/Atom** - dodawaj kanały i automatycznie pobieraj artykuły
- **Podsumowania na żądanie** - `/summarize <URL>` generuje bullet points
- **Auto-fetch** - cykliczne pobieranie nowych artykułów (co 4h)
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

Agent do transkrypcji nagrań (YouTube, pliki lokalne) z generowaniem notatek.

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
OCR_V2/
├── docker-compose.yml      # Konfiguracja serwisów (pgvector/pgvector:pg16)
├── Dockerfile              # Build FastAPI
├── requirements.txt        # Zależności Python (w tym pgvector)
├── app/
│   ├── main.py             # Endpointy FastAPI + walidacja + startup RAG
│   ├── config.py           # Konfiguracja (w tym RAG settings)
│   ├── models.py           # Modele Pydantic (Receipt, Product)
│   ├── dependencies.py     # FastAPI DI (w tym EmbeddingRepoDep)
│   ├── ocr.py              # Vision OCR backend
│   ├── deepseek_ocr.py     # DeepSeek OCR backend (zalecany)
│   ├── classifier.py       # Kategoryzacja (qwen2.5:7b)
│   ├── obsidian_writer.py  # Generowanie markdown
│   ├── ask_api.py          # RAG API (/ask, /ask/stats, /ask/reindex)
│   ├── notes_api.py        # Notatki API
│   ├── bookmarks_api.py    # Zakładki API
│   ├── rss_api.py          # RSS API
│   ├── transcription_api.py # Transkrypcje API
│   ├── rag/                # Baza wiedzy RAG
│   │   ├── embedder.py     # Embeddingi via Ollama /api/embed
│   │   ├── indexer.py      # Chunking + embedding + storage
│   │   ├── retriever.py    # Vector search + keyword fallback
│   │   ├── answerer.py     # LLM answer generation (PL/EN)
│   │   └── hooks.py        # Auto-indexing hooks
│   ├── db/
│   │   ├── models.py       # SQLAlchemy ORM (w tym DocumentEmbedding)
│   │   └── repositories/
│   │       ├── embeddings.py # pgvector repository
│   │       ├── receipts.py
│   │       ├── rss.py
│   │       └── ...
│   ├── transcription/      # Transkrypcje Whisper
│   │   ├── transcriber.py
│   │   ├── downloader.py
│   │   └── extractor.py
│   ├── telegram/
│   │   ├── bot.py          # Główna klasa bota + review callbacks
│   │   ├── handlers/
│   │   │   ├── ask.py      # /ask command (RAG)
│   │   │   ├── receipts.py # Zdjęcia/PDF + review flow
│   │   │   ├── feeds.py    # RSS commands
│   │   │   ├── transcription.py
│   │   │   └── ...
│   │   └── rss_scheduler.py
│   └── dictionaries/       # Normalizacja produktów/sklepów
├── alembic/                # Migracje bazy danych
│   └── versions/
│       ├── 001_initial.py
│       ├── ...
│       └── 004_add_rag_embeddings.py
├── paragony/
│   ├── inbox/              # Folder monitorowany
│   └── processed/          # Archiwum
└── vault/
    ├── paragony/           # Historia paragonów (.md)
    ├── summaries/          # Podsumowania artykułów (.md)
    └── logs/               # Logi i feedback
```

## Konfiguracja

Zmienne środowiskowe (w `docker-compose.yml` lub `.env`):

| Zmienna | Domyślnie | Opis |
|---------|-----------|------|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | URL Ollama API |
| `OCR_MODEL` | `deepseek-ocr` | Model OCR |
| `OCR_BACKEND` | `deepseek` | `deepseek`, `vision`, lub `paddle` |
| `CLASSIFIER_MODEL` | `qwen2.5:7b` | Model kategoryzacji |
| `RAG_ENABLED` | `true` | Włącz/wyłącz bazę wiedzy RAG |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Model embeddingów |
| `RAG_AUTO_INDEX` | `true` | Auto-indeksowanie nowej treści |
| `RAG_TOP_K` | `5` | Ilość fragmentów do wyszukania |
| `ASK_MODEL` | `` | Model LLM dla /ask (pusty = CLASSIFIER_MODEL) |
| `TELEGRAM_BOT_TOKEN` | - | Token bota Telegram |
| `TELEGRAM_CHAT_ID` | `0` | ID chatu (0 = wszyscy) |
| `BOT_ENABLED` | `true` | Włącz/wyłącz bota |

Pełna lista zmiennych: patrz [CLAUDE.md](CLAUDE.md#environment-variables).

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

## API

### `GET /health`

Sprawdza status serwisów.

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
