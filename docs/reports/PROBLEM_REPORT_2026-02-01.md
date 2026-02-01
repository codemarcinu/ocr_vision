# Raport problemów OCR - 2026-02-01

## Podsumowanie

System OCR paragonów napotyka na **3 główne problemy** przy przetwarzaniu wielostronicowych PDF-ów z Biedronki. Pipeline działa częściowo - strona 1 przetwarza się poprawnie (9 produktów), ale strony 2 i 3 zawodzą.

---

## Problem 1: DeepSeek-OCR wchodzi w pętlę powtórzeń (strona 2)

### Symptomy
```
2026-02-01 16:45:23,319 - app.deepseek_ocr - WARNING - DeepSeek-OCR n-gram repetition detected in 9185 chars
2026-02-01 16:45:23,319 - app.deepseek_ocr - WARNING - DeepSeek-OCR failed: DeepSeek-OCR repetition detected (n-gram analysis)
```

### Przyczyna
Model `deepseek-ocr` ma znany bug - na niektórych obrazach wchodzi w nieskończoną pętlę generowania powtarzających się wzorców (np. "Backgrounds...", "...", opisy fontów).

System ma mechanizm detekcji n-gram który wykrywa powtórzenia i przerywa przetwarzanie, ale oznacza to utratę produktów z tej strony.

### Dotknięte pliki
- [deepseek_ocr.py:114-132](app/deepseek_ocr.py#L114-L132) - funkcja `_detect_repetition()`
- [deepseek_ocr.py:135-189](app/deepseek_ocr.py#L135-L189) - funkcja `_call_deepseek_ocr()`

### Skala problemu
- **Częstość**: Powtarza się przy każdym przetwarzaniu tego samego PDF
- **Strony dotknięte**: Strona 2 z 3 (środkowa część paragonu)
- **Utracone produkty**: Nieznana liczba (produkty ze środkowej części paragonu)

---

## Problem 2: Fallback na vision backend kończy się błędem 500 (strona 2)

### Symptomy
```
2026-02-01 16:45:23,319 - app.deepseek_ocr - INFO - Falling back to vision OCR backend...
2026-02-01 16:45:23,319 - app.ocr - INFO - Vision OCR (primary): telegram_20260201_164444_page2.png
2026-02-01 16:45:26,304 - httpx - HTTP Request: POST http://host.docker.internal:11434/api/generate "HTTP/1.1 500 Internal Server Error"
2026-02-01 16:45:26,304 - app.ocr - ERROR - Primary OCR failed: Ollama error: Server error '500 Internal Server Error'
```

### Przyczyna
Gdy DeepSeek-OCR zawodzi, system próbuje fallback na backend `vision` który wymaga modelu **`qwen2.5vl:7b`**. Jednak ten model **nie jest zainstalowany** w systemie:

**Zainstalowane modele:**
```
gpt-oss:latest       17052f91a42e    13 GB
qwen2.5:14b          7cdf5a0187d5    9.0 GB
mistral-nemo:latest  e7e06d107c6c    7.1 GB
deepseek-ocr:latest  0e7b018b8a22    6.7 GB
qwen3-vl:8b          901cae732162    6.1 GB
deepseek-r1:latest   6995872bfe4c    5.2 GB
qwen2.5:7b           845dbda0ea48    4.7 GB
```

**Brak modelu:** `qwen2.5vl:7b` (domyślny dla vision backend w `config.py:26`)

### Dotknięte pliki
- [config.py:26](app/config.py#L26) - `OCR_MODEL: str = os.getenv("OCR_MODEL", "qwen2.5vl:7b")`
- [ocr.py:266](app/ocr.py#L266) - `used_model = model or settings.OCR_MODEL`
- [deepseek_ocr.py](app/deepseek_ocr.py) - fallback logika

### Rozwiązania

**Opcja A - Zainstalować brakujący model:**
```bash
ollama pull qwen2.5vl:7b
```
Model zajmuje ~6GB VRAM.

**Opcja B - Zmienić fallback na `qwen3-vl:8b` (już zainstalowany):**
Wymaga zmiany kodu w `deepseek_ocr.py` aby używał innego modelu przy fallback.

**Opcja C - Użyć PaddleOCR jako fallback zamiast vision:**
PaddleOCR nie wymaga modelu vision, tylko tekstowego LLM.

---

## Problem 3: Strona 3 - zbyt mało tekstu (strona podsumowania)

### Symptomy
```
2026-02-01 16:45:27,631 - app.deepseek_ocr - INFO - DeepSeek-OCR extracted 21 chars
2026-02-01 16:45:27,631 - app.deepseek_ocr - INFO - OCR text preview:
Numer transakcji 1086
2026-02-01 16:45:27,631 - app.telegram.handlers.receipts - WARNING - Page 3/3 has no products, skipping: Too little text extracted (21 chars)
```

### Przyczyna
Strona 3 to strona podsumowania paragonu zawierająca tylko numer transakcji i ewentualnie informacje o płatności. System prawidłowo pomija tę stronę (threshold 150 znaków), jednak:

1. **Suma paragonu** często znajduje się na ostatniej stronie (np. "Karta płatnicza 144.48")
2. System nie znajduje sumy w 21 znakach wyekstrahowanych

### Wpływ
```
2026-02-01 16:45:27,631 - app.telegram.handlers.receipts - WARNING - Total mismatch: extracted=39.21, calculated=56.88
```

- **extracted=39.21** - suma z 9 produktów strony 1 (niepełna)
- **calculated=56.88** - suma obliczona z produktów (tylko strona 1)
- **Rzeczywista suma** - nieznana (brak strony 2 i 3)

### Dotknięte pliki
- [deepseek_ocr.py:50-86](app/deepseek_ocr.py#L50-L86) - `extract_total_from_text()`

---

## Problem 4 (dodatkowy): Telegram daily digest URL error

### Symptomy
```
2026-02-01 16:46:58,996 - app.telegram.notifications - ERROR - Failed to send daily digest: Inline keyboard button url 'http://localhost:8000/web/dictionary' is invalid: wrong http url
```

### Przyczyna
Telegram API nie akceptuje `localhost` URLs w przyciskach inline keyboard - wymaga publicznych HTTPS URLs.

### Dotknięte pliki
- `app/telegram/notifications.py` - funkcja wysyłająca daily digest

---

## Aktualny stan przetwarzania

| Strona | Status | Produkty | Problem |
|--------|--------|----------|---------|
| 1/3 | ✅ OK | 9 | - |
| 2/3 | ❌ FAIL | 0 | DeepSeek-OCR pętla + brak modelu vision |
| 3/3 | ⚠️ SKIP | 0 | Zbyt mało tekstu (strona podsumowania) |

**Wynik:** System ekstrahuje tylko ~40% produktów z paragonu (tylko strona 1).

---

## Rekomendowane działania

### Priorytet 1 - Naprawić fallback (szybka naprawa)

```bash
# Zainstalować model vision jako fallback
ollama pull qwen2.5vl:7b

# LUB zmienić fallback na już zainstalowany model
# (wymaga zmiany kodu)
```

### Priorytet 2 - Zbadać przyczynę pętli DeepSeek-OCR

Problematyczny obraz: `telegram_20260201_164444_page2.png`

Możliwe podejścia:
1. Sprawdzić jakość obrazu strony 2 (może być nieostry/zniekształcony)
2. Przetestować z różnymi ustawieniami OCR prompt
3. Rozważyć użycie PaddleOCR dla wielostronicowych PDF-ów

### Priorytet 3 - Poprawić ekstrakcję sumy dla wielostronicowych PDF

System powinien próbować ekstrahować sumę z raw OCR tekstu wszystkich stron, nie tylko ostatniej.

---

## Konfiguracja systemu

```yaml
# docker-compose.yml
OCR_MODEL: deepseek-ocr
OCR_BACKEND: deepseek
STRUCTURING_MODEL: qwen2.5:7b
CLASSIFIER_MODEL: qwen2.5:7b
```

## Wersje

- Ollama: (sprawdzić)
- DeepSeek-OCR: latest (6.7GB)
- qwen2.5:7b: latest (4.7GB)
- GPU: RTX 3060 12GB (zakładane)

---

*Raport wygenerowany: 2026-02-01 16:47 UTC*
