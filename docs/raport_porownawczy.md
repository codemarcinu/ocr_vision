# Raport: Analiza Pipeline'u OCR Przetwarzania Paragonów

**Data analizy:** 2026-02-01
**Wersja systemu:** Smart Pantry Tracker v1.0.0

---

## Spis treści

1. [Przegląd architektury](#1-przegląd-architektury)
2. [Porównanie backendów OCR](#2-porównanie-backendów-ocr)
3. [Ekstrakcja produktów - szczegóły](#3-ekstrakcja-produktów---szczegóły)
4. [Ekstrakcja cen - krytyczne punkty](#4-ekstrakcja-cen---krytyczne-punkty)
5. [Obsługa rabatów](#5-obsługa-rabatów)
6. [Normalizacja nazw produktów](#6-normalizacja-nazw-produktów)
7. [Walidacja i kontrola jakości](#7-walidacja-i-kontrola-jakości)
8. [Problemy i zalecenia](#8-problemy-i-zalecenia)
9. [Podsumowanie](#9-podsumowanie)

---

## 1. Przegląd architektury

### 1.1 Pipeline przetwarzania

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PRZEPŁYW PRZETWARZANIA PARAGONU                      │
└─────────────────────────────────────────────────────────────────────────────┘

      Paragon (PNG/JPG/PDF)
             │
             ▼
    ┌─────────────────┐
    │   main.py       │  Punkt wejścia: /process-receipt
    │   process_file  │
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │ PDF? → Konwersja│  pdf_converter.py: PDF → PNG (po 1 na stronę)
    │  do obrazów     │  Wielostronicowe PDF: przetwarzanie równoległe
    └────────┬────────┘
             │
             ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                    BACKEND OCR (wybierany przez OCR_BACKEND)     │
    ├─────────────────┬──────────────────────┬───────────────────────┤
    │  deepseek (def) │      vision          │        paddle         │
    │  13-17s         │      80-90s          │        11s            │
    └────────┬────────┴──────────┬───────────┴───────────┬───────────┘
             │                   │                       │
             ▼                   ▼                       ▼
    ┌─────────────────┐ ┌─────────────────┐    ┌─────────────────┐
    │ DeepSeek-OCR    │ │ qwen2.5vl:7b    │    │ PaddleOCR       │
    │ (szybka wizja)  │ │ (wizja + JSON)  │    │ (tekst lokalnie)│
    │       +         │ └────────┬────────┘    │       +         │
    │ qwen2.5:7b      │          │             │ LLM lub regex   │
    │ (strukturyzacja)│          │             │ (strukturyzacja)│
    └────────┬────────┘          │             └────────┬────────┘
             │                   │                      │
             └───────────────────┼──────────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────┐
                  │  Detekcja sklepu         │  store_prompts.py
                  │  (regex na tekst OCR)    │
                  └────────────┬─────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │  Normalizacja produktów  │  dictionaries/__init__.py
                  │  (5-poziomowe dopasow.)  │
                  └────────────┬─────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │  Price Fixer             │  price_fixer.py
                  │  (wykrycie podejrzanych  │  (NIE modyfikuje cen,
                  │   cen jednostkowych)     │   tylko dodaje ostrzeżenia)
                  └────────────┬─────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │  WALIDACJA               │
                  │  suma OCR vs suma prod.  │
                  │  >5 PLN LUB >10% → review│
                  └────────────┬─────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │  Kategoryzacja           │  classifier.py
                  │  (słownik lub LLM)       │  (pomija produkty z confidence ≥0.6)
                  └────────────┬─────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │  Zapis                   │
                  │  • Markdown → vault/     │
                  │  • PostgreSQL (opcja)    │
                  │  • Telegram review       │
                  └──────────────────────────┘
```

### 1.2 Pliki źródłowe i ich odpowiedzialność

| Plik | Odpowiedzialność |
|------|------------------|
| `app/main.py` | Punkt wejścia API, koordynacja pipeline'u |
| `app/ocr.py` | Backend "vision" - qwen2.5vl:7b |
| `app/deepseek_ocr.py` | Backend "deepseek" - DeepSeek-OCR + LLM |
| `app/paddle_ocr.py` | Backend "paddle" - PaddleOCR + LLM/regex |
| `app/store_prompts.py` | Prompty specyficzne dla sklepów |
| `app/receipt_parser.py` | Parser regex dla Biedronki |
| `app/price_fixer.py` | Detekcja podejrzanych cen |
| `app/dictionaries/__init__.py` | Normalizacja nazw produktów |
| `app/classifier.py` | Kategoryzacja produktów |
| `app/models.py` | Modele danych (Product, Receipt) |

---

## 2. Porównanie backendów OCR

### 2.1 Tabela porównawcza

| Cecha | DeepSeek (zalecany) | Vision | Paddle |
|-------|---------------------|--------|--------|
| **Czas przetwarzania** | 13-17s | 80-90s | 11s |
| **Dokładność** | ★★★★★ | ★★★★★ | ★★★☆☆ |
| **Obsługa rabatów** | ★★★★☆ | ★★★★☆ | ★★★☆☆ |
| **Produkty wagowe** | ★★★★☆ | ★★★★★ | ★★☆☆☆ |
| **VRAM** | ~7GB | ~6GB | ~5GB |
| **Fallback** | Tak (vision) | Dwuetapowy | Regex |

### 2.2 DeepSeek Backend (domyślny)

**Plik:** `app/deepseek_ocr.py`

**Pipeline:**
```
Obraz → DeepSeek-OCR (~6-10s) → Surowy tekst → qwen2.5:7b (~7s) → JSON + Kategorie
```

**Kluczowe cechy:**

1. **Ekstrakcja tekstu** (linie 161-233):
   - Prosty prompt: `"Read all text and numbers."`
   - Limit tokenów: `num_predict: 2048` (zapobiega nieskończonym pętlom)
   - Wykrywanie pętli: n-gram analysis + wzorce ("Backgrounds", "sans-serif")

2. **Strukturyzacja + kategoryzacja w jednym kroku** (linie 236-309):
   - Oszczędność ~7s dzięki połączeniu operacji
   - Polski prompt z listą kategorii
   - Format wyjściowy: `{"sklep", "data", "produkty", "suma"}`

3. **Fallback do backendu vision** (linie 344-383):
   - Automatyczny fallback gdy DeepSeek-OCR wchodzi w pętlę
   - Używa `OCR_FALLBACK_MODEL` (domyślnie: `qwen3-vl:8b`)

**Prompt strukturyzacji** (linie 38-63):
```python
STRUCTURING_PROMPT = """Tekst paragonu (OCR):

{ocr_text}

Wyekstrahuj WSZYSTKIE produkty i przypisz im kategorie. Format JSON:
{"sklep":"nazwa","data":"YYYY-MM-DD","produkty":[{"nazwa":"X","cena":0.00,"kategoria":"Nabiał","rabat":0.00}],"suma":0.00}

ZASADY EKSTRAKCJI:
- cena = cena KOŃCOWA po rabacie (ostatnia liczba w wierszu)
- rabat = wartość ujemna pod produktem (np. -1.40 → rabat: 1.40)
- suma = wartość przy "SUMA", "DO ZAPŁATY" lub "Karta płatnicza"
...
"""
```

### 2.3 Vision Backend

**Plik:** `app/ocr.py`

**Pipeline:**
```
Obraz → qwen2.5vl:7b (JSON) → Weryfikacja tekstowa (jeśli niezgodność) → Receipt
```

**Kluczowe cechy:**

1. **Główny prompt** (linie 26-89):
   - Szczegółowe instrukcje ASCII-art dla formatów Biedronki
   - Wyraźne wskazówki dla produktów wagowych
   - Przykłady z rabatami

2. **Trzyetapowy fallback** (linie 404-413):
   - Etap 1: Główna ekstrakcja
   - Etap 2: Jeśli <2 produkty → ekstrakcja surowego tekstu → parsing JSON
   - Etap 3: Weryfikacja tekstowa jeśli suma się nie zgadza

3. **Weryfikacja tekstowa** (linie 450-501):
   - Używa modelu tekstowego (`CLASSIFIER_MODEL`) zamiast wizyjnego
   - Analizuje rozbieżność i próbuje naprawić

### 2.4 Paddle Backend

**Plik:** `app/paddle_ocr.py`

**Pipeline:**
```
Obraz → PaddleOCR (lokalnie) → Regex lub LLM → Receipt
```

**Kluczowe cechy:**

1. **Hybrydowy parsing** (regex jako priorytet):
   - Najpierw regex dla Biedronki
   - Jeśli <3 produkty → LLM

2. **Parser regex** (`app/receipt_parser.py`):
   - Maszyna stanów do analizy linii
   - Obsługa wieloliniowych bloków produktów
   - Szczegółowa ekstrakcja rabatów

---

## 3. Ekstrakcja produktów - szczegóły

### 3.1 Struktura danych produktu

**Model** (`app/models.py`, linie 15-29):

```python
class Product(BaseModel):
    nazwa: str                          # Nazwa z paragonu
    cena: float                         # Cena KOŃCOWA (po rabacie)
    kategoria: Optional[str]            # Kategoria
    confidence: Optional[float]         # Pewność dopasowania (0-1)
    warning: Optional[str]              # Ostrzeżenie cenowe

    # Normalizacja
    nazwa_oryginalna: Optional[str]     # Przed normalizacją
    nazwa_znormalizowana: Optional[str] # Po normalizacji

    # Rabaty
    cena_oryginalna: Optional[float]    # Przed rabatem
    rabat: Optional[float]              # Kwota rabatu (wartość dodatnia!)
    rabaty_szczegoly: Optional[list[DiscountDetail]]  # Szczegóły rabatów
```

### 3.2 Filtrowanie produktów

**Lokalizacja:** `app/ocr.py`, linie 560-624 (vision) i `app/deepseek_ocr.py`, linie 427-450 (deepseek)

**Wzorce do pominięcia:**
```python
skip_patterns = [
    'PTU', 'VAT', 'SUMA', 'TOTAL', 'RAZEM', 'PARAGON', 'FISKALNY',
    'KAUCJ', 'ZWROT', 'OPAKOW', 'PŁATN', 'PLATN', 'KARTA', 'SPRZEDA',
    'GOTÓWKA', 'RESZTA', 'WYDANO', 'NUMER', 'TRANS', 'OPODATK'
]
```

**Kryteria walidacji:**
| Kryterium | Wartość | Plik:linia |
|-----------|---------|------------|
| Minimalna długość nazwy | 4 znaki | ocr.py:581 |
| Maksymalna cena | 500 PLN | ocr.py:612 |
| Nazwy generyczne | product\d*, item\d* | ocr.py:603-608 |
| Podejrzane grosze | >30 PLN z nietypowymi groszami | ocr.py:618-624 |

### 3.3 Ekstrakcja sumy

**Priorytet źródeł** (`app/ocr.py`, linie 152-189):

1. **Płatność kartą** (najbardziej wiarygodna):
   ```regex
   [Kk]arta\s+p[lł]atnicza\s+(\d+[.,]\d{2})
   ```

2. **Płatność gotówką**:
   ```regex
   [Gg]ot[oó]wka\s+(\d+[.,]\d{2})
   ```

3. **"DO ZAPŁATY" lub "RAZEM"**:
   ```regex
   [Dd][Oo]\s+[Zz]ap[lł]aty[:\s]+(\d+[.,]\d{2})
   ```

4. **"Suma PLN"** (ostatnie wystąpienie):
   ```regex
   [Ss]uma(?:\s+PLN)?[:\s]+(\d+[.,]\d{2})
   ```

5. **Suma produktów** (fallback)

---

## 4. Ekstrakcja cen - krytyczne punkty

### 4.1 Problem produktów wagowych

**Symptom:** OCR ekstrahuje cenę jednostkową (za kg) zamiast ceny końcowej.

**Przykład problematycznego paragonu:**
```
BoczWędzKraWęd kg    C   0.396 ×   28,20    11,17
  Rabat                                     -3,29
                                             7,88
```

**Błędna ekstrakcja:** `cena: 28.20` (cena za kg)
**Poprawna ekstrakcja:** `cena: 7.88` (cena końcowa)

**Rozwiązanie w kodzie** (`app/ocr.py`, linie 33-52):

```
WEIGHTED PRODUCTS - PAY ATTENTION:
┌─────────────────────────────────────────────────────────────────────────────┐
│  BoczWędz B kg       │ ← Product name with "kg" = weighted product          │
│  0.279 x 28.20   B   │ ← 0.279kg × 28.20zł/kg (IGNORE 28.20 - unit price!) │
│               7.88   │ ← THIS IS THE FINAL PRICE = 7.88 zł                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Price Fixer - wykrywanie błędów

**Plik:** `app/price_fixer.py`

**Progi cenowe:**
| Typ produktu | Próg | Uzasadnienie |
|--------------|------|--------------|
| Produkty wagowe (kg) | 15 PLN | Ceny jednostkowe często 15-40 PLN/kg |
| Mięso wagowe | 25 PLN | Mięso bywa droższe |
| Mięso ogólne | 60 PLN | Całe opakowania |
| Premium | 80 PLN | Alkohol, elektronika |
| Ogólne | 40 PLN | Typowy limit |

**Wzorce produktów wagowych** (linie 23-54):
```python
WEIGHTED_NAME_PATTERNS = [
    r'^bocz',      # Boczek
    r'^wedz',      # Wędlina
    r'^szyn',      # Szynka
    r'pomidor',    # Pomidory
    r'banan',      # Banany
    r'ziemniak',   # Ziemniaki
    # ... i wiele innych
]
```

**⚠️ WAŻNE:** Price Fixer NIE modyfikuje cen! Tylko dodaje ostrzeżenia:
```python
product.warning = (
    f"Likely unit price (per kg) instead of total. "
    f"Price {price:.2f} zł exceeds {threshold:.2f} zł threshold for weighted product. "
    f"Look for pattern 'X.XXX x {price:.2f}' followed by actual total."
)
```

### 4.3 Weryfikacja tekstowa

**Lokalizacja:** `app/ocr.py`, linie 450-501

Gdy suma produktów ≠ suma z paragonu:

1. Model tekstowy analizuje surowy tekst OCR
2. Sprawdza:
   - Czy wyekstrahowano cenę jednostkową zamiast końcowej?
   - Czy pominięto linię "Rabat"?
   - Czy są duplikaty lub brakujące produkty?
3. Zwraca skorygowany JSON

---

## 5. Obsługa rabatów

### 5.1 Struktura rabatu

**Model** (`app/models.py`, linie 8-12):
```python
class DiscountDetail(BaseModel):
    typ: str       # "kwotowy" lub "procentowy"
    wartosc: float # Kwota w PLN lub procent
    opis: str      # "Rabat", "Promocja", "Zniżka", "Upust"
```

### 5.2 Wzorce ekstrakcji rabatów

**Parser regex** (`app/receipt_parser.py`, linie 100-105):

| Wzorzec | Przykład | Typ |
|---------|----------|-----|
| Słowo kluczowe + kwota | `Rabat -3.29` | kwotowy |
| Samo słowo kluczowe | `Rabat` (kwota w następnej linii) | kwotowy |
| Procent | `Promocja -30%` | procentowy |
| Tylko ujemna liczba | `-3.29` | kwotowy |

**Obsługiwane słowa kluczowe:**
- Rabat
- Promocja
- Zniżka
- Upust

### 5.3 Algorytm ekstrakcji w parserze regex

**Lokalizacja:** `app/receipt_parser.py`, linie 181-268

```
ALGORYTM FINALIZACJI PRODUKTU:

1. Zbierz wszystkie ceny w tablicy `prices[]`
2. Przy finalizacji:

   JEŚLI has_discount ORAZ len(prices) >= 2:
      final_price = prices[-1]  ← OSTATNIA cena

      dla każdej ceny od końca (oprócz ostatniej):
         jeśli cena > final_price:
            cena_przed = ta cena
            break

      rabat = cena_przed - final_price

      WALIDACJA: abs((cena_przed - rabat) - final_price) <= 0.02

   JEŚLI has_discount ORAZ len(prices) == 1:
      final_price = prices[0]
      cena_przed = final_price + rabat

   INACZEJ:
      final_price = prices[-1]
      rabat = None
```

### 5.4 Przykład parsowania Biedronki

**Wejście:**
```
Kalafior        C    1.000 × 4.19    4.19
Rabat                                 -1.40
                                       2.79
```

**Przebieg:**
1. Linia "Kalafior..." → nowy blok produktu
2. "C" → PTU
3. "1.000" → ilość
4. "4.19" → prices = [4.19]
5. "4.19" → prices = [4.19, 4.19]
6. "Rabat" → has_rabat_marker = True
7. "-1.40" → rabat = 1.40, rabaty = [DiscountInfo(kwotowy, 1.40, "Rabat")]
8. "2.79" → prices = [4.19, 4.19, 2.79]

**Finalizacja:**
- final_price = 2.79 (ostatnia)
- Szukamy ceny > 2.79: znaleziono 4.19
- cena_przed = 4.19
- rabat = 1.40
- Walidacja: 4.19 - 1.40 = 2.79 ✓

**Wynik:**
```json
{
  "nazwa": "Kalafior",
  "cena": 2.79,
  "cena_przed": 4.19,
  "rabat": 1.40,
  "rabaty_szczegoly": [{"typ": "kwotowy", "wartosc": 1.40, "opis": "Rabat"}]
}
```

---

## 6. Normalizacja nazw produktów

### 6.1 Pięciopoziomowe dopasowanie

**Plik:** `app/dictionaries/__init__.py`, linie 420-535

| Poziom | Metoda | Confidence | Przykład |
|--------|--------|------------|----------|
| 1 | Dokładne dopasowanie | 0.99 | "mleko 2%" → "mleko" |
| 2 | Częściowe dopasowanie (70% słów) | 0.7-0.9 | "mleko uht 1l" → "mleko" |
| 3 | Skróty specyficzne dla sklepu | 0.88-0.95 | "MroznKr" → "mrożonka krakowska" |
| 4 | Fuzzy matching (Levenshtein) | 0.68-0.81 | "jogird" → "jogurt" |
| 5 | Słowa kluczowe | 0.6 | "ser żółty" → kategoria "nabiał" |

### 6.2 Obsługa polskich znaków

**Lokalizacja:** linie 76-86

```python
def remove_polish_diacritics(text: str) -> str:
    replacements = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        # ... wersje wielkie
    }
```

### 6.3 Skróty Biedronki

**Plik:** `app/dictionaries/product_shortcuts.json`

Biedronka używa skróconych nazw z drukarek termicznych:

| Skrót | Pełna nazwa |
|-------|-------------|
| mroznkr | mrożonka krakowska |
| kalafks | kalafior |
| serekasztlan | ser kasztelan |
| boczwedz | boczek wędzony |

**Dopasowanie skrótów** (`app/dictionaries/__init__.py`, linie 176-222):
1. Dokładne dopasowanie (bez spacji i małymi literami)
2. Dopasowanie bez polskich znaków
3. Częściowe dopasowanie (skrót zawarty w nazwie)

### 6.4 Mapa słów kluczowych

**Lokalizacja:** linie 294-417

~100+ mapowań słów kluczowych do kategorii:

```python
_KEYWORD_MAP = {
    # Nabiał
    "mleko": ("nabiał", "mleko", "NAB"),
    "jogurt": ("nabiał", "jogurt", "NAB"),
    "ser ": ("nabiał", "ser", "NAB"),  # spacja zapobiega "sernik"
    # Piekarnia
    "chleb": ("piekarnia", "chleb", "PIE"),
    "bułk": ("piekarnia", "bułki", "PIE"),
    "bulk": ("piekarnia", "bułki", "PIE"),  # bez polskich znaków
    # ...
}
```

---

## 7. Walidacja i kontrola jakości

### 7.1 Walidacja sumy

**Lokalizacja:** `app/main.py`, linie 410-424

```python
if variance > 5.0 or variance_pct > 10:
    receipt.needs_review = True
    receipt.review_reasons.append(
        f"Suma {receipt.suma:.2f} zł różni się od sumy produktów "
        f"{calculated_total:.2f} zł (różnica: {variance:.2f} zł / {variance_pct:.1f}%)"
    )
```

**Progi:**
- Różnica bezwzględna: > 5 PLN **LUB**
- Różnica procentowa: > 10%

### 7.2 Human-in-the-Loop

Gdy `needs_review = True`:

1. Telegram bot pokazuje paragon do zatwierdzenia
2. Opcje:
   - **Zatwierdź** - zapisz jak jest
   - **Popraw sumę** - użyj sumy kalkulowanej lub wpisz ręcznie
   - **Odrzuć** - nie zapisuj

### 7.3 Feedback loop

**Niezaznaczone produkty:** `vault/logs/unmatched.json`
- Produkty które nie pasują do słownika
- Zliczane wystąpienia
- Sugestie dla produktów z count ≥ 3

**Korekty review:** `vault/logs/corrections.json`
- Historia korekt sum
- Statystyki dokładności OCR

---

## 8. Problemy i zalecenia

### 8.1 Zidentyfikowane problemy

#### Problem 1: Produkty wagowe - cena jednostkowa vs końcowa

**Status:** Częściowo rozwiązany

**Obecne rozwiązania:**
- Szczegółowe instrukcje w prompcie z ASCII-art
- Price Fixer dodaje ostrzeżenia
- Weryfikacja tekstowa może skorygować

**Pozostałe luki:**
- DeepSeek nie zawsze rozpoznaje wzorzec "X.XXX × YY.YY"
- Brak automatycznej korekty (tylko ostrzeżenia)

**Zalecenie:** Rozważyć regex post-processing dla wzorca wagowego:
```regex
(\d+[.,]\d{3})\s*[x×]\s*(\d+[.,]\d{2})\s+(\d+[.,]\d{2})
```
Gdzie grupa 3 to prawdopodobna cena końcowa.

#### Problem 2: Ilości produktów

**Status:** Nieobsługiwany

Obecny model **nie przechowuje ilości** w strukturze `Product`. Ilość jest pomijana podczas ekstrakcji.

**Wpływ:**
- Niemożność śledzenia "kupiono 3 sztuki"
- Problemy z produktami wagowymi (brak masy w kg)

**Zalecenie:** Dodać pole `ilosc` do modelu:
```python
class Product(BaseModel):
    # ...
    ilosc: Optional[float] = Field(None, description="Ilość (sztuki lub kg)")
    jednostka: Optional[str] = Field(None, description="Jednostka: 'szt' lub 'kg'")
```

#### Problem 3: Wielostronicowe PDF

**Status:** Rozwiązany z zastrzeżeniami

**Działające:**
- Równoległe przetwarzanie stron
- Łączenie produktów ze wszystkich stron
- Ekstrakcja sumy z ostatniej strony

**Potencjalne problemy:**
- Jeśli suma jest na środkowej stronie (rzadkie)
- Strony z samym podsumowaniem mogą być pomijane

#### Problem 4: DeepSeek wchodzi w pętlę

**Status:** Rozwiązany (fallback do vision)

Wykrywanie:
- N-gram analysis (30% powtórzeń)
- Wzorce: "Backgrounds", "sans-serif", "..."

Po wykryciu: automatyczny fallback do `OCR_FALLBACK_MODEL`

#### Problem 5: Brak standaryzacji kategorii

**Status:** Częściowo rozwiązany

Słownik używa kategorii jak "nabiał", "piekarnia", ale LLM może zwrócić "Nabiał", "NABIAŁ".

**Obecne rozwiązanie:** Walidacja w classifier.py:
```python
if category not in settings.CATEGORIES:
    category = "Inne"
```

### 8.2 Zalecenia optymalizacyjne

#### Zalecenie 1: Automatyczna korekta cen wagowych

Dodać post-processing który:
1. Wykrywa produkty wagowe (po nazwie lub "kg" w nazwie)
2. Szuka wzorca `X.XXX × YY.YY ... ZZ.ZZ` w raw_text
3. Jeśli znaleziono i `cena == YY.YY`, zamień na `ZZ.ZZ`

#### Zalecenie 2: Ekstrakcja ilości

Rozszerzyć prompt o ekstrakcję ilości:
```json
{"nazwa": "Banany", "cena": 5.01, "ilosc": 1.005, "jednostka": "kg"}
```

#### Zalecenie 3: Confidence scoring

Dodać wagę pewności dla różnych źródeł ekstrakcji:
- Regex parser: 0.9
- DeepSeek + LLM: 0.85
- Vision single-pass: 0.8
- Two-stage fallback: 0.7

#### Zalecenie 4: Walidacja cross-check

Dla produktów z ostrzeżeniami price_fixer:
1. Wyszukaj w raw_text wzorzec ceny
2. Jeśli znajdziesz inną cenę w kontekście produktu, zasugeruj korektę

#### Zalecenie 5: Uczenie się z korekt

Wykorzystać `corrections.json` do:
1. Identyfikacji wzorców błędów
2. Dopracowania promptów dla problematycznych sklepów
3. Automatycznego dodawania skrótów do słownika

---

## 9. Podsumowanie

### 9.1 Mocne strony systemu

| Obszar | Ocena | Uzasadnienie |
|--------|-------|--------------|
| Architektura | ★★★★★ | Modułowa, łatwa do rozszerzenia |
| Obsługa rabatów | ★★★★☆ | Szczegółowa ekstrakcja, typy rabatów |
| Normalizacja nazw | ★★★★☆ | 5-poziomowe dopasowanie, skróty sklepowe |
| Walidacja | ★★★★☆ | Porównanie sum, human-in-the-loop |
| Fallbacki | ★★★★☆ | Wieloetapowe, automatyczne |
| Wydajność | ★★★★☆ | 13-17s dla DeepSeek |

### 9.2 Obszary do poprawy

| Obszar | Priorytet | Złożoność |
|--------|-----------|-----------|
| Ekstrakcja ilości | Wysoki | Średnia |
| Automatyczna korekta cen wagowych | Wysoki | Średnia |
| Uczenie z korekt | Średni | Wysoka |
| Standaryzacja kategorii | Niski | Niska |

### 9.3 Metryki do monitorowania

1. **Wskaźnik review:** % paragonów wymagających manual review
2. **Dokładność sum:** % paragonów gdzie suma = suma produktów
3. **Pokrycie słownika:** % produktów dopasowanych (nie "no_match")
4. **Czas przetwarzania:** średni czas per paragon per backend

### 9.4 Wnioski końcowe

System Smart Pantry Tracker oferuje zaawansowany pipeline przetwarzania paragonów z wieloma warstwami walidacji i normalizacji. Główne zalecenia to:

1. **Dodanie ekstrakcji ilości** - obecnie pomijana, ważna dla produktów wagowych
2. **Automatyczna korekta cen wagowych** - price_fixer tylko ostrzega, nie naprawia
3. **Wykorzystanie feedback loop** - dane z korekt i unmatched do doskonalenia

Pipeline jest gotowy do produkcyjnego użycia z obecnymi funkcjonalnościami, przy akceptacji że ~10-15% paragonów może wymagać manualnego review.

---

*Raport wygenerowany na podstawie analizy kodu źródłowego projektu ocr_vision.*
