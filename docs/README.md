# Dokumentacja Smart Pantry Tracker

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
│   │   ├── models.py       # Modele SQLAlchemy
│   │   ├── connection.py   # Połączenie z bazą
│   │   └── repositories/   # Repozytoria danych
│   ├── telegram/           # Bot Telegram
│   │   ├── bot.py          # Główna klasa bota
│   │   ├── handlers/       # Handlery komend
│   │   └── keyboards.py    # Klawiatury inline
│   ├── services/           # Serwisy aplikacji
│   ├── dictionaries/       # Słowniki produktów/sklepów
│   ├── ocr.py              # OCR Vision backend
│   ├── paddle_ocr.py       # OCR Paddle backend
│   ├── classifier.py       # Kategoryzacja produktów
│   └── main.py             # FastAPI endpoints
├── alembic/                # Migracje bazy danych
├── docs/                   # Dokumentacja (jesteś tutaj)
│   ├── archive/            # Stare notatki
│   └── reports/            # Raporty techniczne
├── monitoring/             # Konfiguracja Prometheus/Loki/Grafana
├── n8n-workflows/          # Workflow n8n
├── paragony/               # Paragony do przetworzenia
│   └── inbox/              # Wrzuć tutaj zdjęcia
├── scripts/                # Skrypty pomocnicze
│   ├── init-db.sql         # Schemat bazy danych
│   ├── migrate_data.py     # Migracja danych do PostgreSQL
│   ├── quick_ocr.py        # Szybki test OCR
│   └── receipt_ocr.py      # Standalone OCR
├── vault/                  # Wygenerowane pliki Obsidian
│   ├── paragony/           # Historia paragonów
│   └── logs/               # Logi i feedback
├── docker-compose.yml      # Konfiguracja Docker
├── Dockerfile              # Build aplikacji
├── CLAUDE.md               # Dokumentacja techniczna
└── README.md               # Główny README
```

## Pomoc

- Użyj `/help` w Telegram
- Sprawdź [FAQ w przewodniku](USER_GUIDE.md#najczęstsze-pytania-faq)
- Zgłoś problem administratorowi
