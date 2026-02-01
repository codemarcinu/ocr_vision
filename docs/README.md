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

## Struktura projektu

```
OCR_V2/
├── app/                    # Kod aplikacji
│   ├── db/                 # Warstwa bazy danych
│   ├── telegram/           # Bot Telegram
│   └── ...
├── docs/                   # Dokumentacja (jesteś tutaj)
├── paragony/               # Paragony do przetworzenia
│   └── inbox/              # Wrzuć tutaj zdjęcia
├── vault/                  # Wygenerowane pliki
│   ├── paragony/           # Historia paragonów
│   └── logs/               # Logi i feedback
├── scripts/                # Skrypty pomocnicze
├── docker-compose.yml      # Konfiguracja Docker
└── CLAUDE.md               # Dokumentacja techniczna
```

## Pomoc

- Użyj `/help` w Telegram
- Sprawdź [FAQ w przewodniku](USER_GUIDE.md#najczęstsze-pytania-faq)
- Zgłoś problem administratorowi
