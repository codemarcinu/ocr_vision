# PRD: Second Brain - Konsolidacja modułu OCR

## Problem
Jedna osoba zarządza swoimi finansami domowymi przez system OCR paragonów. Produkty często nie są rozpoznawane przez słownik (trafiają do "unmatched"), fuzzy matching czasem dopasowuje źle, skróty z drukarek termicznych nie są obsługiwane, a kategoryzacja LLM jest zbyt ogólna - produkty masowo lądują w kategorii "Inne" zamiast w konkretnych kategoriach.

## Rozwiązanie
Poprawić jakość normalizacji produktów (lepszy słownik, lepsze dopasowanie skrótów, mniej "unmatched") oraz doprecyzować kategoryzację LLM tak, żeby kategoria "Inne" była ostatecznością, nie domyślnym wyborem.

## Użytkownik
Jedna osoba, technicznie zaawansowana. Korzysta z systemu przez Telegram bota i REST API. Oczekuje, że system sam poprawnie rozpozna produkt i kategorię, a interwencja ręczna jest wyjątkiem.

## Typ aplikacji
Analizator / przetwarzanie danych (pipeline OCR z elementami ML)

## Zakres MVP

### Co robimy:
1. Poprawa normalizacji produktów - lepszy fuzzy matching, obsługa większej liczby skrótów termicznych, mniej fałszywych dopasowań
2. Rozbudowa słownika - łatwiejsze uczenie z unmatched, lepsze warianty nazw per sklep
3. Doprecyzowanie kategoryzacji LLM - konkretniejsze kategorie zamiast "Inne"
4. Daily digest z produktami w kategorii "Inne" - raz dziennie lista do przejrzenia w Telegram

### Czego NIE robimy:
- Nie zmieniamy backendu OCR (DeepSeek + qwen2.5 + Google Cloud Vision fallback zostają)
- Nie ruszamy pozostałych modułów (RSS, transkrypcje, notatki, zakładki)
- Nie budujemy nowego UI - zostajemy przy Telegram + web UI słownika
- Nie dodajemy nowych sklepów
- Nie robimy testów automatycznych
- Nie robimy migracji istniejących danych

## Jak to działa (flow)

### Krok 1: Przetwarzanie paragonu (bez zmian)
Użytkownik wysyła zdjęcie/PDF paragonu przez Telegram. System przepuszcza przez pipeline OCR i wyciąga listę produktów z cenami.

### Krok 2: Normalizacja produktów (usprawniona)
System próbuje dopasować każdy produkt do słownika w kolejności: exact match, partial match, shortcut match, fuzzy match, keyword match. Ulepszone progi i logika dopasowania zmniejszają liczbę produktów "unmatched" i fałszywych dopasowań.

### Krok 3: Kategoryzacja (usprawniona)
LLM kategoryzuje produkty używając doprecyzowanego promptu z pełną listą kategorii i przykładami. Kategoria "Inne" jest używana tylko gdy produkt naprawdę nie pasuje nigdzie indziej.

### Krok 4: Daily digest (nowe)
Codziennie o 9:00 w Telegram, obok istniejących statystyk, użytkownik dostaje listę produktów które trafiły do kategorii "Inne" z możliwością przejrzenia i skorygowania.

## Dane wejściowe
- Zdjęcia / PDF paragonów (bez zmian)
- Ręczne korekty kategorii z daily digest
- Nowe wpisy do słownika skrótów i wariantów produktów

## Dane wyjściowe
- Paragony z poprawnie znormalizowanymi nazwami produktów i trafnymi kategoriami
- Mniej produktów w "unmatched" i mniej w kategorii "Inne"
- Codzienny raport produktów wymagających uwagi

## Obsługa błędów
- Jeśli produkt trafia do kategorii "Inne" → zostaje zalogowany i pojawia się w daily digest do przejrzenia
- Jeśli fuzzy matching ma niski confidence (<0.7) → produkt trafia do "unmatched" zamiast ryzykować złe dopasowanie
- Jeśli słownik ma konflikt (dwa dopasowania o podobnym score) → system wybiera dopasowanie z wyższym confidence i loguje konflikt

## Kryteria sukcesu
- [ ] Odsetek produktów w kategorii "Inne" spada poniżej 10% (mierzone na nowych paragonach)
- [ ] Odsetek produktów "unmatched" spada poniżej 15%
- [ ] Daily digest działa i pokazuje produkty z "Inne" w porannym powiadomieniu Telegram
- [ ] Fałszywe dopasowania fuzzy matchingu są zredukowane (mniej ręcznych korekt)
