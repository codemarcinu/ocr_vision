# Dokumentacja Second Brain

## Dla użytkowników

| Dokument | Opis |
|----------|------|
| [QUICK_START.md](QUICK_START.md) | Szybki start - zacznij w 5 minut |
| [USER_GUIDE.md](USER_GUIDE.md) | Pełny przewodnik użytkownika |

## Dla administratorów i deweloperów

| Dokument | Opis |
|----------|------|
| [../CLAUDE.md](../CLAUDE.md) | Dokumentacja techniczna (architektura, API, konfiguracja) |
| [../README.md](../README.md) | Główny README projektu |

## Raporty techniczne

| Dokument | Opis |
|----------|------|
| [reports/OPTIMIZATION_REPORT.md](reports/OPTIMIZATION_REPORT.md) | Raport optymalizacji OCR Vision |
| [reports/ANALIZA_DOKLADNOSCI_OCR.md](reports/ANALIZA_DOKLADNOSCI_OCR.md) | Analiza dokładności OCR |

## Archiwum

Folder `archive/` zawiera stare notatki i specyfikacje projektowe.

## Struktura projektu

```
OCR_V2/
├── app/                    # Kod aplikacji
│   ├── db/                 # Warstwa bazy danych
│   │   ├── models.py       # Modele SQLAlchemy (w tym DocumentEmbedding)
│   │   ├── connection.py   # Połączenie z bazą
│   │   └── repositories/   # Repozytoria danych
│   │       ├── receipts.py  # Paragony
│   │       ├── products.py  # Produkty
│   │       ├── rss.py       # RSS/artykuły
│   │       ├── notes.py     # Notatki
│   │       ├── bookmarks.py # Zakładki
│   │       └── embeddings.py # Embeddingi RAG (pgvector)
│   ├── rag/                # Baza wiedzy RAG
│   │   ├── embedder.py     # Generowanie embeddingów (Ollama)
│   │   ├── indexer.py      # Indeksowanie treści (chunking + embedding)
│   │   ├── retriever.py    # Wyszukiwanie (vector + keyword)
│   │   ├── answerer.py     # Generowanie odpowiedzi (LLM)
│   │   └── hooks.py        # Hooki auto-indeksowania
│   ├── telegram/           # Bot Telegram
│   │   ├── bot.py          # Główna klasa bota
│   │   ├── handlers/       # Handlery komend
│   │   │   ├── receipts.py # Zdjęcia/PDF + review flow
│   │   │   ├── pantry.py   # Spiżarnia
│   │   │   ├── stats.py    # Statystyki
│   │   │   ├── feeds.py    # RSS/Summarizer
│   │   │   ├── transcription.py # Transkrypcje
│   │   │   ├── ask.py      # RAG: /ask
│   │   │   └── errors.py   # Błędy
│   │   ├── keyboards.py    # Klawiatury inline
│   │   └── rss_scheduler.py # Scheduler auto-fetch RSS
│   ├── transcription/      # Transkrypcje audio/wideo
│   │   ├── transcriber.py  # Faster-Whisper
│   │   ├── downloader.py   # yt-dlp
│   │   ├── extractor.py    # LLM knowledge extraction
│   │   └── note_writer.py  # Obsidian output
│   ├── services/           # Serwisy aplikacji
│   ├── dictionaries/       # Słowniki produktów/sklepów
│   ├── main.py             # FastAPI endpoints
│   ├── ask_api.py          # RAG API (/ask)
│   ├── notes_api.py        # Notatki API
│   ├── bookmarks_api.py    # Zakładki API
│   ├── rss_api.py          # RSS API
│   ├── transcription_api.py # Transkrypcje API
│   ├── ocr.py              # OCR Vision backend
│   ├── deepseek_ocr.py     # OCR DeepSeek backend
│   ├── classifier.py       # Kategoryzacja produktów
│   └── config.py           # Konfiguracja
├── alembic/                # Migracje bazy danych
│   └── versions/           # Wersje migracji (w tym 004_add_rag_embeddings)
├── docs/                   # Dokumentacja (jesteś tutaj)
│   ├── archive/            # Stare notatki
│   └── reports/            # Raporty techniczne
├── monitoring/             # Konfiguracja Prometheus/Loki/Grafana
├── n8n-workflows/          # Workflow n8n
├── paragony/               # Paragony do przetworzenia
│   └── inbox/              # Wrzuć tutaj zdjęcia
├── scripts/                # Skrypty pomocnicze
│   ├── init-db.sql         # Schemat bazy danych (z pgvector)
│   ├── migrate_data.py     # Migracja danych do PostgreSQL
│   └── quick_ocr.py        # Szybki test OCR
├── vault/                  # Wygenerowane pliki Obsidian
│   ├── paragony/           # Historia paragonów
│   ├── summaries/          # Podsumowania artykułów
│   └── logs/               # Logi i feedback
├── notes/                  # Notatki osobiste
├── transcriptions/         # Notatki z transkrypcji
├── docker-compose.yml      # Konfiguracja Docker (pgvector/pgvector:pg16)
├── Dockerfile              # Build aplikacji
├── CLAUDE.md               # Dokumentacja techniczna
└── README.md               # Główny README
```

## Pomoc

- Użyj `/help` w Telegram
- Sprawdź [FAQ w przewodniku](USER_GUIDE.md#najczęstsze-pytania-faq)
- Zgłoś problem administratorowi
