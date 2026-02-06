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
| [agent_tool_calling_report.md](agent_tool_calling_report.md) | Testy Agent Tool-Calling (modele, benchmark) |
| [reports/OPTIMIZATION_REPORT.md](reports/OPTIMIZATION_REPORT.md) | Raport optymalizacji OCR Vision |
| [reports/ANALIZA_DOKLADNOSCI_OCR.md](reports/ANALIZA_DOKLADNOSCI_OCR.md) | Analiza dokładności OCR |

## Archiwum

Folder `archive/` zawiera stare notatki i specyfikacje projektowe.

## Struktura projektu

```
ocr_vision/
├── app/                    # Kod aplikacji
│   ├── ocr/                # Backendy OCR (vision, deepseek, google, openai, paddle)
│   ├── web/                # Web UI - 14 modułów per feature (HTMX + Jinja2)
│   ├── writers/            # Generatory markdown (Obsidian)
│   ├── db/                 # Warstwa bazy danych
│   │   ├── models.py       # Modele SQLAlchemy
│   │   ├── connection.py   # Połączenie z bazą
│   │   └── repositories/   # Repozytoria danych (16 plików)
│   ├── rag/                # Baza wiedzy RAG
│   │   ├── embedder.py     # Generowanie embeddingów (Ollama)
│   │   ├── indexer.py      # Indeksowanie treści
│   │   ├── retriever.py    # Wyszukiwanie (vector + keyword)
│   │   ├── answerer.py     # Generowanie odpowiedzi
│   │   └── hooks.py        # Hooki auto-indeksowania
│   ├── chat/               # Chat AI
│   │   ├── intent_classifier.py  # Klasyfikacja intencji
│   │   ├── orchestrator.py       # Orkiestracja rozmowy
│   │   ├── agent_executor.py     # Wykonawcy narzędzi agenta
│   │   └── searxng_client.py     # Klient SearXNG
│   ├── agent/              # Agent Tool-Calling
│   │   ├── tools.py        # Definicje narzędzi (11 narzędzi)
│   │   ├── router.py       # Router LLM → tool dispatch
│   │   └── validator.py    # Walidacja inputu
│   ├── transcription/      # Transkrypcje audio/wideo
│   ├── services/           # Serwisy aplikacji
│   ├── push/               # Web Push notifications
│   ├── dictionaries/       # Słowniki produktów/sklepów
│   ├── main.py             # FastAPI endpoints
│   ├── model_coordinator.py # Koordynacja VRAM
│   ├── mobile_routes.py    # Mobile PWA (/m/)
│   ├── auth.py             # Uwierzytelnianie (opcjonalne)
│   └── config.py           # Konfiguracja
├── alembic/                # Migracje bazy danych
├── docs/                   # Dokumentacja (jesteś tutaj)
│   ├── archive/            # Stare notatki
│   └── reports/            # Raporty techniczne
├── monitoring/             # Prometheus/Loki/Grafana
├── paragony/               # Paragony do przetworzenia
├── scripts/                # Skrypty pomocnicze
├── vault/                  # Wygenerowane pliki Obsidian
├── docker-compose.yml      # Konfiguracja Docker
├── Dockerfile              # Build aplikacji
├── CLAUDE.md               # Dokumentacja techniczna
└── README.md               # Główny README
```

## Pomoc

- Sprawdź [FAQ w przewodniku](USER_GUIDE.md#najczęstsze-pytania-faq)
- Dokumentacja API: `http://localhost:8000/docs`
- Zgłoś problem administratorowi
