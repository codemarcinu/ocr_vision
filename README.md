# Smart Pantry Tracker

System OCR paragonów z automatycznym zarządzaniem spiżarnią. Wykorzystuje Ollama (PaddleOCR + qwen2.5:7b) do rozpoznawania produktów i kategoryzacji. Zawiera bot Telegram z **walidacją human-in-the-loop**.

## Architektura

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Telegram Bot   │     │    FastAPI      │     │     Ollama      │
│  lub paragony/  │────▶│    Backend      │────▶│   (GPU)         │
│  inbox/         │     │                 │     │                 │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
           ┌─────────────────┐    ┌─────────────────┐
           │   Walidacja     │    │  Needs Review?  │
           │   sumy          │    │    > 5 PLN      │
           │                 │    │    > 10%        │
           └────────┬────────┘    └────────┬────────┘
                    │                      │
              ┌─────┴─────┐          ┌─────┴─────┐
              ▼           ▼          ▼           ▼
         Auto-save    Telegram    Approve    Correct
                      Review      as-is      total
                                │
                                ▼
                       ┌─────────────────┐
                       │     vault/      │
                       │  - paragony/    │
                       │  - spiżarnia.md │
                       │  - logs/        │
                       └─────────────────┘
```

## Wymagania

- Docker z obsługą GPU (NVIDIA) lub CPU
- Docker Compose
- Modele Ollama: `minicpm-v` (opcjonalnie), `qwen2.5:7b`
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
ollama pull qwen2.5:7b      # Kategoryzacja + strukturyzacja OCR
ollama pull minicpm-v       # Opcjonalnie: vision OCR backend
```

### 4. Sprawdź status

```bash
curl http://localhost:8000/health
```

### 5. Przetwórz paragon

**Via Telegram (zalecane):**
- Wyślij zdjęcie lub PDF do bota
- Bot przetworzy i pokaże wynik (lub poprosi o weryfikację)

**Via API:**
```bash
curl -X POST http://localhost:8000/process-receipt \
  -F "file=@paragon.png"
```

**Via folder:**
- Umieść plik w `paragony/inbox/`
- Użyj n8n workflow do automatycznego przetwarzania

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

### Przykład komunikatu weryfikacji

```
*PARAGON WYMAGA WERYFIKACJI*

*Powody:*
  - Suma 84.50 zł różni się od sumy produktów 144.48 zł

*Dane paragonu:*
Sklep: Biedronka
Data: 2026-01-31
*Suma OCR: 84.50 zł*
Suma produktów: 144.48 zł
Różnica: -59.98 zł
Produktów: 27

[Zatwierdź] [Popraw sumę] [Odrzuć]
```

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

## Struktura projektu

```
OCR_V2/
├── docker-compose.yml      # Konfiguracja serwisów
├── Dockerfile              # Build FastAPI
├── requirements.txt        # Zależności Python
├── app/
│   ├── main.py             # Endpointy FastAPI + walidacja
│   ├── ocr.py              # Vision OCR backend
│   ├── paddle_ocr.py       # PaddleOCR + LLM backend (zalecany)
│   ├── classifier.py       # Kategoryzacja (qwen2.5:7b)
│   ├── obsidian_writer.py  # Generowanie markdown
│   ├── pdf_converter.py    # Konwersja PDF → PNG
│   ├── models.py           # Modele Pydantic (Receipt, Product)
│   ├── config.py           # Konfiguracja
│   ├── dictionaries/       # Normalizacja nazw produktów/sklepów
│   │   ├── products.json
│   │   └── stores.json
│   └── telegram/
│       ├── bot.py          # Główna klasa bota + review callbacks
│       ├── middleware.py   # Autoryzacja
│       ├── keyboards.py    # Klawiatury inline (w tym review)
│       ├── formatters.py   # Formatowanie wiadomości
│       └── handlers/       # Handlery komend
│           ├── receipts.py # Zdjęcia/PDF + review flow
│           ├── pantry.py   # Spiżarnia
│           ├── stats.py    # Statystyki
│           └── errors.py   # Błędy
├── paragony/
│   ├── inbox/              # Folder monitorowany
│   └── processed/          # Archiwum
└── vault/
    ├── paragony/           # Historia paragonów (.md)
    ├── logs/
    │   └── ocr-errors.md   # Log błędów
    └── spiżarnia.md        # Agregowany widok
```

## API

### `GET /health`

Sprawdza status serwisów.

**Odpowiedź:**
```json
{
  "status": "healthy",
  "ollama_available": true,
  "ocr_model_loaded": true,
  "classifier_model_loaded": true,
  "inbox_path": "/data/paragony/inbox",
  "vault_path": "/data/vault"
}
```

### `POST /process-receipt`

Przetwarza paragon (zdjęcie lub PDF).

**Request:**
- `file`: Plik obrazu (PNG, JPG, JPEG, WEBP) lub PDF

**Odpowiedź:**
```json
{
  "success": true,
  "needs_review": false,
  "receipt": {
    "products": [
      {"nazwa": "Mleko 3.2% 1L", "cena": 4.99, "kategoria": "Nabiał"}
    ],
    "sklep": "Biedronka",
    "data": "2026-01-31",
    "suma": 144.48,
    "calculated_total": 144.48,
    "needs_review": false,
    "review_reasons": []
  },
  "source_file": "paragon.png",
  "output_file": "/data/vault/paragony/2026-01-31_paragon.md"
}
```

### `POST /reprocess/{filename}`

Ponowne przetwarzanie pliku z inbox lub processed.

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

Prompty znajdują się w `app/store_prompts.py`. Każdy prompt zawiera:
- Dokładny opis formatu paragonu danego sklepu
- Jak identyfikować cenę końcową (po rabacie)
- Co ignorować (VAT, PTU, kaucje)
- Przykłady ekstrakcji

## Wielostronicowe PDF

System prawidłowo obsługuje paragony rozłożone na wiele stron:

1. PDF jest konwertowany na osobne obrazy PNG
2. Każda strona jest przetwarzana przez OCR
3. Produkty ze wszystkich stron są **łączone**
4. Tekst ze wszystkich stron jest **scalany** do ekstrakcji sumy
5. Informacja o płatności (np. "Karta płatnicza 144.48") zwykle na ostatniej stronie
6. Walidacja sumy względem sumy produktów
7. Jeśli rozbieżność > 5 PLN lub > 10% → review

## Konfiguracja

Zmienne środowiskowe (w `docker-compose.yml` lub `.env`):

| Zmienna | Domyślnie | Opis |
|---------|-----------|------|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | URL Ollama API |
| `OCR_MODEL` | `minicpm-v` | Model vision (dla OCR_BACKEND=vision) |
| `OCR_BACKEND` | `paddle` | `paddle` (szybki) lub `vision` (LLM) |
| `CLASSIFIER_MODEL` | `qwen2.5:7b` | Model kategoryzacji |
| `TELEGRAM_BOT_TOKEN` | - | Token bota Telegram |
| `TELEGRAM_CHAT_ID` | `0` | ID chatu (0 = wszyscy) |
| `BOT_ENABLED` | `true` | Włącz/wyłącz bota |

## Walidacja

- **Suma vs produkty**: różnica > 5 PLN lub > 10% → wymaga review
- **Cena > 100 zł**: flaga `⚠️` (możliwy błąd OCR)
- **Brak daty**: fallback do timestamp pliku
- **OCR fail**: `ERROR.md` + wpis w `ocr-errors.md`

## Rozwiązywanie problemów

### Paragon zawsze wymaga weryfikacji

Sprawdź czy OCR prawidłowo ekstrahuje sumę:
```bash
docker logs -f pantry-api | grep -i "total\|suma\|extracted"
```

Progi walidacji można dostosować w `app/main.py` i `app/telegram/handlers/receipts.py`.

### Wielostronicowy PDF pokazuje złą sumę

- Upewnij się, że informacja o płatności jest na ostatniej stronie
- System szuka wzorców: "Karta płatnicza", "Gotówka", "DO ZAPŁATY"
- Użyj weryfikacji Telegram do ręcznej korekty

### Dane review wygasły w Telegram

- Dane są przechowywane w `context.user_data`
- Mogą wygasnąć po restarcie bota
- Rozwiązanie: `/reprocess <nazwa_pliku>`

### Ollama nie odpowiada

```bash
# Sprawdź czy Ollama działa
ollama list
ollama ps

# Sprawdź logi
docker logs pantry-api
```

### Błędy OCR

Sprawdź log: `vault/logs/ocr-errors.md`

```bash
# Ponowne przetwarzanie
curl -X POST http://localhost:8000/reprocess/paragon.png

# Lub przez Telegram
/reprocess paragon.png
```

## Monitorowanie

Opcjonalny stack Prometheus + Grafana + Loki:

```bash
http://localhost:3000   # Grafana (admin/pantry123)
http://localhost:9090   # Prometheus
http://localhost:3100   # Loki
```

Metryki FastAPI: `GET /metrics`
