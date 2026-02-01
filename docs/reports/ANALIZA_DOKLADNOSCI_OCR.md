# Analiza Dokładności OCR - Raport

**Data analizy:** 2026-02-01
**Wersja systemu:** Po optymalizacjach OCR Vision + poprawkach accuracy

---

## Podsumowanie Wykonawcze

### Status po poprawkach

| Problem | Status | Rozwiązanie |
|---------|--------|-------------|
| Brak produktów z multi-page PDF | ✅ **NAPRAWIONY** | Wyłączono weryfikację per-strona dla multi-page |
| Sumy stron zamiast sumy całkowitej | ✅ **NAPRAWIONY** | Użycie sumy z ostatniej strony lub calculated |
| Produkty wagowe z ceną/kg | ✅ **NAPRAWIONY** | Obniżono próg price_fixer do 15 PLN dla wagowych |
| Fałszywe produkty (product1, product2) | ✅ **NAPRAWIONY** | Dodano filtr generic names (regex) |
| Produkty niezmatchowane do słownika | ⏳ Do zrobienia | Wymagane dodanie do słownika |

### Wyniki testu po poprawkach

| Metryka | Przed | Po |
|---------|-------|-----|
| Suma paragonu | 64.17 zł ❌ | **144.48 zł** ✅ |
| Produkty ekstraowane | 7 | **24** |
| BoczWędz (cena) | 28.20 (per kg) ❌ | **7.88 zł** ✅ |
| Fałszywe produkty | 2 (product1, product2) | **0** |

---

## Historia problemów (przed poprawkami)

### Problemy zidentyfikowane:

---

## Szczegółowa Analiza Logów

### Sesja: telegram_20260201_080739.pdf (3 strony)

**Timeline przetwarzania:**
```
08:07:40 - PDF converted to 3 images
08:08:40 - Page 1: 12 products, total=144.48, calculated=64.17 (MISMATCH 55.6%)
08:09:10 - Verification: total corrected to 64.17 ✓ (ale to suma strony 1!)
08:10:03 - Page 2: 9 products, total=144.48, calculated=55.82 (MISMATCH 61.4%)
08:10:25 - Verification: total corrected to 55.83 ✓ (suma strony 2!)
08:11:02 - Page 3: 3 products, total=144.48, calculated=19.16 (MISMATCH 86.7%)
08:11:25 - Verification: total corrected to 18.16 ✓ (suma strony 3!)
08:11:25 - FINAL: extracted=64.17, calculated=139.15 (MISMATCH!)
```

**Problem:** Weryfikacja "naprawia" sumę każdej strony do sumy produktów **tej strony**, ale ostatecznie system używa sumy z pierwszej strony (64.17) zamiast sumy wszystkich produktów (139.15) lub faktycznej sumy paragonu (144.48).

### Wynik końcowy

**Zapisano w pliku:** `2026-01-31_telegram_20260201_080739.md`
```
total: 64.17 zł (BŁĄD - powinno być 144.48 zł)
produkty: 7 wyświetlonych (18 pominięto jako duplikaty)
```

**Faktycznie znalezione produkty (22):**
- Strona 1: 12 produktów
- Strona 2: 9 produktów
- Strona 3: 3 produkty

**Ale paragon ma ~24 produkty!** Brakuje produktów z powodu:
1. Filtrowania jako duplikaty
2. Niskiej jakości ekstrakcji na niektórych stronach
3. Błędów parsowania JSON

---

## Zidentyfikowane Problemy

### 1. KRYTYCZNY: Suma pierwszej strony używana jako suma paragonu

**Lokalizacja:** `app/main.py` linie 294-302

**Symptom:** Po połączeniu stron, `combined_receipt.suma` ma wartość z pierwszej strony.

**Przyczyna:** Kod ustawia `combined_receipt = page_receipt` dla pierwszej strony i tylko aktualizuje `products`, nie aktualizując `suma`.

**Rozwiązanie:** Po przetworzeniu wszystkich stron, użyć:
- `suma` z ostatenij strony (tam jest "Karta płatnicza")
- lub `extract_total_from_text()` na połączonym raw_text (już zaimplementowane ale nie działa dla vision backend)

### 2. KRYTYCZNY: Weryfikacja naprawia do złej wartości

**Lokalizacja:** `app/ocr.py` `_verify_extraction()`

**Symptom:** Weryfikacja zmienia `suma` z 144.48 na 64.17 dla strony 1.

**Przyczyna:** Weryfikacja działa na pojedynczej stronie i "naprawia" sumę do sumy produktów tej strony, ignorując że to tylko część paragonu.

**Rozwiązanie:** Dla multi-page PDF, wyłączyć weryfikację per-strona lub przekazać kontekst że to część większego dokumentu.

### 3. WYSOKI: Produkty wagowe z ceną/kg

**Przykład z logów:**
```json
{
  "raw_name": "BoczWedzKraWed kg",
  "price": 28.2  // To jest cena za kg, nie cena końcowa!
}
```

**Faktyczna linia paragonu:**
```
BoczWędzKraWęd kg
0.279 x 28.20
        7.88   ← TO jest cena końcowa
```

**Status price_fixer:** NIE zadziałał - produkt nie pojawił się w ostrzeżeniach.

**Przyczyna:**
- OCR wyekstrahował cenę/kg (28.20) zamiast ceny końcowej (7.88)
- price_fixer wymaga ceny > 40 PLN dla mięsa, a 28.20 < 40

**Rozwiązanie:**
- Obniżyć próg dla produktów wagowych (np. 15 PLN)
- Lub wykrywać wzorzec "x XX.XX" w nazwie/kontekście

### 4. ŚREDNI: Fałszywe produkty z podsumowania

**Przykład:**
```json
{
  "raw_name": "product1",
  "price": 48.16
},
{
  "raw_name": "product2",
  "price": 96.32
}
```

**Źródło:** Strona podsumowania z "SUMA PTU A" = 48.16 i "SUMA PTU B" = 96.32

**Status filtra:** Powinien był odrzucić "product1", "product2" (< 5 znaków, generic names)

**Przyczyna:** Filtr w `_build_receipt()` sprawdza `len(name) < 4`, a "product1" ma 8 znaków.

**Rozwiązanie:** Dodać "product" do SKIP_PATTERNS w `app/ocr.py`

### 5. NISKI: Produkty niezmatchowane do słownika

**Statystyki z unmatched.json:**
| Produkt | Wystąpienia | Problem |
|---------|-------------|---------|
| Tagl Mar Pasta400g | 7 | Brak w słowniku |
| Kopytka NS 500g | 6 | Brak w słowniku |
| Mięs.SłoikKWMix280g | 6 | Brak w słowniku |
| ChŻytnMaśla400gKR | 4 | OCR błąd (Ż zamiast Ch) |
| SałatkaGyros500g | 4 | Brak w słowniku |

**Rozwiązanie:** Dodać te produkty do słownika:
```bash
curl -X POST "http://localhost:8000/dictionary/learn/Tagl%20Mar%20Pasta400g?normalized_name=makaron tagliatelle&category=Produkty suche"
```

---

## Metryki Dokładności

### Na podstawie 5 przetworzonych paragonów:

| Metryka | Wartość | Cel |
|---------|---------|-----|
| Poprawna suma | 2/5 (40%) | >95% |
| Kompletność produktów | ~60% | >95% |
| Produkty wagowe poprawne | 0/4 (0%) | >90% |
| Fałszywe produkty | 2 (product1, product2) | 0 |
| Czas przetwarzania 3-str PDF | ~4 min | <2 min |

---

## Rekomendowane Poprawki (Priorytet)

### P0 - Natychmiastowe (Multi-page PDF)

1. **Naprawić ekstrakcję sumy dla multi-page**
   - Plik: `app/main.py`
   - Użyć sumy z ostatniej strony lub `extract_total_from_text()` na całym raw_text
   - Nie nadpisywać `suma` podczas weryfikacji per-strona

2. **Wyłączyć weryfikację per-strona dla multi-page**
   - Plik: `app/main.py` lub `app/ocr.py`
   - Dodać parametr `is_multi_page=True` do `extract_products_from_image()`
   - Pominąć weryfikację jeśli `is_multi_page=True`

### P1 - Wysoki (Produkty wagowe)

3. **Obniżyć próg price_fixer dla produktów wagowych**
   - Plik: `app/price_fixer.py`
   - Zmienić `GENERAL_PRICE_THRESHOLD = 40.0` na `15.0` dla produktów z "kg" w nazwie
   - Lub dodać osobny próg `WEIGHTED_PRICE_THRESHOLD = 15.0`

4. **Wykrywać wzorzec "ilość x cena" w OCR**
   - Plik: `app/ocr.py` prompt
   - Dodać explicit: "If you see pattern '0.XXX x YY.YY' followed by a number, the FINAL number is the price"

### P2 - Średni (Filtrowanie)

5. **Dodać "product" do SKIP_PATTERNS**
   - Plik: `app/ocr.py` linia ~150
   - Dodać: `r'^product\d*$'`

6. **Dodać produkty do słownika**
   - Użyć API `/dictionary/learn/`
   - Lub edytować `app/dictionaries/products.json`

---

## Testy Weryfikacyjne

Po wdrożeniu poprawek:

```bash
# Test multi-page PDF (suma powinna być 144.48, nie 64.17)
curl -X POST http://localhost:8000/reprocess/telegram_20260201_080739.pdf

# Sprawdź logi
docker logs pantry-api --tail 100 | grep -E "Total|calculated|Verification"

# Sprawdź wynik
cat vault/paragony/2026-01-31_telegram_20260201_080739.md
```

**Oczekiwany wynik:**
- `total: 144.48 zł`
- ~24 produkty (nie 7)
- Brak "product1", "product2"
- BoczWędz z ceną ~7.88 zł (nie 28.20 zł)

---

## Załączniki

### A. Pełne logi przetwarzania

```
2026-02-01 08:07:40 - PDF converted to 3 image(s)
2026-02-01 08:08:40 - Built receipt: 12 products, store=Biedronka, total=144.48, calculated=64.17
2026-02-01 08:08:40 - WARNING - Total mismatch detected: receipt=144.48, calculated=64.17, diff=80.31 (55.6%)
2026-02-01 08:09:10 - Verification improved match: 80.31 → 0.00
2026-02-01 08:10:03 - Built receipt: 9 products, store=Biedronka, total=144.48, calculated=55.82
2026-02-01 08:10:03 - WARNING - Total mismatch detected: receipt=144.48, calculated=55.82, diff=88.66 (61.4%)
2026-02-01 08:10:25 - Verification improved match: 88.66 → 0.01
2026-02-01 08:11:02 - Built receipt: 3 products, store=Biedronka, total=144.48, calculated=19.16
2026-02-01 08:11:02 - WARNING - Total mismatch detected: receipt=144.48, calculated=19.16, diff=125.32 (86.7%)
2026-02-01 08:11:25 - Verification improved match: 125.32 → 1.00
2026-02-01 08:11:25 - WARNING - Total mismatch: extracted=64.17, calculated=139.15
```

### B. Zawartość unmatched.json

14 produktów niezmatchowanych, w tym:
- 7x `Tagl Mar Pasta400g`
- 6x `Kopytka NS 500g`
- 6x `Mięs.SłoikKWMix280g`
- 4x `ChŻytnMaśla400gKR`
- 4x `SałatkaGyros500g`
- 1x `BoczWedzKraWed kg` (cena 28.2 - błąd!)
- 1x `product1` (48.16 - fałszywy!)
- 1x `product2` (96.32 - fałszywy!)
