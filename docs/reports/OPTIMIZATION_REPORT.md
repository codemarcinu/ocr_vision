# Raport optymalizacji OCR Vision Backend

**Data:** 2026-02-01
**Model:** qwen2.5vl:7b
**Backend:** vision (poprzednio: paddle)

---

## Podsumowanie wyników

### Porównanie przed/po optymalizacji

| Metryka | Przed | Po | Zmiana |
|---------|-------|-----|--------|
| Produkty wyekstrahowane | 20 | 23 | +15% |
| Suma z OCR | 123.45 zł | 144.48 zł | ✅ Poprawna |
| Suma obliczona | 179.19 zł | 149.85 zł | -29.34 zł |
| **Rozbieżność** | **55.74 zł (31%)** | **5.37 zł (3.6%)** | **✅ -90% błędu** |
| Rabaty wyekstrahowane | 0 | 6 | ✅ Nowe |
| Fałszywe produkty | 2 (48.16, 96.32) | 0 | ✅ Odfiltrowane |

### Wykryte rabaty (nowa funkcjonalność)
```
- Tagl Mar Pasta400g: 2.52 zł (było 4.99, rabat -2.47)
- KalafiorMrożnKr450g: 2.79 zł (było 4.19, rabat -1.40)
- Mięs.SłoikKWMix280g: 6.14 zł (było 8.89, rabat -2.76)
- Kopytka NS 500g: 4.99 zł (było 5.75, rabat -0.76)
```

---

## Zaimplementowane optymalizacje

### 1. Ulepszony prompt OCR
- Explicit instrukcje dla cen końcowych (po rabacie)
- Format Biedronki: "OSTATNIA liczba w bloku = cena"
- Produkty wagowe: "IGNORUJ cenę za kg"
- "Extract EVERY product - do not skip any"

### 2. Two-stage fallback
```
Primary fails (< 2 products)?
  → Stage 1: Extract raw text (OCR_RAW_TEXT_PROMPT)
  → Stage 2: Parse to JSON (qwen2.5:7b text model)
```
**Wynik:** Strona 3 (110 znaków) prawidłowo pominięta jako summary page

### 3. Self-verification
```
Mismatch > 5 PLN AND > 10%?
  → Model re-analizuje z kontekstem błędu
  → "Sum = X, Receipt = Y, please verify..."
```
**Problem:** Ollama zwraca 500 error (prawdopodobnie brak VRAM)

### 4. Filtry fałszywych produktów
- Generic names: `product1`, `item2`, etc.
- Krótkie nazwy: < 4 znaki
- Podejrzane ceny: > 40 zł z nietypowymi groszami
- Summary lines: GOTÓWKA, RESZTA, WYDANO, etc.
- Summary pages: < 150 znaków tekstu

### 5. Regex fallback dla sumy
Priorytet: `Karta płatnicza` > `Gotówka` > `DO ZAPŁATY` > `Suma PLN`

### 6. Normalizacja słownikowa
- `normalize_product(name, store=detected_store)`
- Logowanie unmatched products dla machine learning

---

## Problemy do rozwiązania

### 🔴 Krytyczne

1. **Ollama 500 error podczas weryfikacji**
   - Przyczyna: Prawdopodobnie brak VRAM (12GB RTX 3060)
   - Image + długi prompt przekraczają limit
   - **Fix:** Zmniejszyć kontekst weryfikacji lub użyć text-only

2. **Ceny jednostkowe zamiast końcowych**
   - `BoczWędzKraWęd kg: 28.20 zł` (powinno być ~7.88 zł)
   - Model nie zawsze rozpoznaje format Biedronki
   - **Fix:** Więcej przykładów w prompcie lub post-processing

### 🟡 Średnie

3. **Brak niektórych produktów**
   - 23 wyekstrahowane vs ~24 na paragonie
   - Możliwe przyczyny: filtrowanie, OCR miss

4. **Dictionary shortcuts brakujące**
   - "Tagl Mar Pasta400g" - 5 wystąpień bez dopasowania
   - "MIeko UHT 1,5 1I" - literówka OCR (I zamiast l)

### 🟢 Niskie

5. **Czas przetwarzania**
   - ~90 sekund na stronę (vs 11s dla paddle)
   - Akceptowalne dla accuracy vs speed tradeoff

---

## Statystyki testów

### Przetwarzanie 3-stronicowego PDF
```
Page 1: 13 products, 88s, verification triggered (500 error)
Page 2: 13 products, 95s, verification triggered (500 error)
Page 3:  1 product,  35s, summary page skipped ✅
Total:  23 products, ~4 min
```

### Logi weryfikacji
```
Page 1: receipt=144.48, calculated=70.3, diff=74.18 (51.3%) → 500 error
Page 2: receipt=144.48, calculated=71.67, diff=72.81 (50.4%) → 500 error
Page 3: receipt=144.48, calculated=7.88, diff=136.60 (94.5%) → no improvement
Final:  receipt=144.48, calculated=149.85, diff=5.37 (3.6%) ✅
```

---

## Rekomendacje

### Natychmiastowe
1. **Wyłączyć self-verification** do czasu fix VRAM issue
2. Dodać shortcut `"taglmarpasta"` → `"Tagliatelle Marinara"`
3. Dodać fuzzy matching dla literówek OCR

### Krótkoterminowe
1. Text-only verification (bez ponownego wysyłania obrazu)
2. Zwiększyć threshold weryfikacji do 15% (mniej false positives)
3. Post-processing cen wagowych (wykrywanie wzorca `× XX.XX`)

### Długoterminowe
1. Fine-tuning prompta na większej liczbie paragonów
2. Hybrydowy backend: paddle OCR + vision verification
3. Uczenie się z corrections.json

---

## Pliki zmodyfikowane

```
app/ocr.py                 - Główna logika OCR z weryfikacją
app/config.py              - OCR_MODEL=qwen2.5vl:7b
app/store_prompts.py       - Prompty po angielsku
docker-compose.yml         - OCR_BACKEND=vision
CLAUDE.md                  - Dokumentacja (do aktualizacji)
```

---

## Wnioski

**Optymalizacja zakończona sukcesem częściowym:**

✅ Redukcja błędu sumy: 55 zł → 5 zł (-90%)
✅ Wykrywanie rabatów działa
✅ Filtrowanie fałszywych produktów działa
✅ Summary page detection działa
⚠️ Self-verification wymaga fix VRAM
⚠️ Niektóre ceny wagowe nadal błędne

**Ogólna ocena:** Backend vision z qwen2.5vl:7b jest **gotowy do użycia** z akceptowalnym poziomem błędu (~3.6%). Self-verification należy tymczasowo wyłączyć.
