# Smart Pantry Tracker - Przewodnik Użytkownika

> Inteligentny system śledzenia zakupów i zarządzania spiżarnią

---

## Spis treści

1. [Co to jest Smart Pantry Tracker?](#co-to-jest-smart-pantry-tracker)
2. [Jak zacząć?](#jak-zacząć)
3. [Codzienne użycie](#codzienne-użycie)
4. [Weryfikacja paragonów](#weryfikacja-paragonów)
5. [Przeglądanie danych](#przeglądanie-danych)
6. [Obsługiwane sklepy](#obsługiwane-sklepy)
7. [RSS i podsumowania stron](#rss-i-podsumowania-stron)
8. [Słownik produktów](#słownik-produktów)
9. [Najczęstsze pytania (FAQ)](#najczęstsze-pytania-faq)

---

## Co to jest Smart Pantry Tracker?

Smart Pantry Tracker to **inteligentny asystent zakupowy**, który:

| Funkcja | Opis |
|---------|------|
| Czyta paragony | Rozpoznaje produkty i ceny ze zdjęć paragonów |
| Kategoryzuje | Automatycznie sortuje produkty (nabiał, pieczywo, mięso...) |
| Zapamiętuje | Przechowuje historię wszystkich zakupów |
| Analizuje | Pokazuje statystyki wydatków i trendy cenowe |
| Zarządza spiżarnią | Śledzi co masz w domu |

### Jak to działa?

```
📸 Zdjęcie paragonu
        ↓
🤖 AI odczytuje tekst
        ↓
🏪 Rozpoznaje sklep
        ↓
📋 Wyciąga produkty i ceny
        ↓
🔍 Sprawdza poprawność
        ↓
   ┌────┴────┐
   │         │
  OK       Wątpliwości
   ↓         ↓
💾 Zapisz   📱 Zapytaj użytkownika
```

---

## Jak zacząć?

### Wymagania

- Komputer z Docker (administrator lub osoba techniczna pomoże to zainstalować)
- Konto Telegram (darmowe)
- Smartfon do robienia zdjęć paragonów

### Pierwsze uruchomienie

1. **Uruchom aplikację** - administrator uruchamia system komendą:
   ```
   docker-compose up -d
   ```

2. **Znajdź swojego bota** - w Telegram wyszukaj bota (nazwa zostanie podana przez administratora)

3. **Wyślij pierwsze zdjęcie** - zrób zdjęcie paragonu i wyślij do bota

4. **Gotowe!** - bot przetworzy paragon i zapisze dane

---

## Codzienne użycie

### Sposób 1: Przez Telegram (zalecany)

1. Otwórz Telegram na telefonie
2. Wejdź do rozmowy z botem
3. Zrób zdjęcie paragonu (lub wybierz z galerii)
4. Wyślij zdjęcie
5. Poczekaj na odpowiedź (zwykle 1-2 minuty)

**Wskazówki do robienia zdjęć:**
- Paragon powinien być dobrze oświetlony
- Unikaj cieni i odblasków
- Cały paragon powinien być widoczny
- Tekst powinien być czytelny (nie rozmazany)

### Sposób 2: Przez folder na komputerze

1. Skopiuj zdjęcie paragonu do folderu `paragony/inbox/`
2. System automatycznie je przetworzy
3. Wynik pojawi się w folderze `vault/paragony/`

### Obsługiwane formaty plików

| Format | Opis |
|--------|------|
| PNG | Zdjęcia z telefonu |
| JPG/JPEG | Zdjęcia z telefonu |
| WEBP | Zdjęcia z niektórych aplikacji |
| PDF | Zeskanowane paragony (także wielostronicowe) |

---

## Weryfikacja paragonów

Czasami AI nie jest w 100% pewna odczytu. Wtedy **poprosi Cię o pomoc** przez Telegram.

### Kiedy pojawia się weryfikacja?

- Suma produktów różni się od sumy na paragonie o więcej niż **5 zł**
- Różnica procentowa jest większa niż **10%**

### Jak wygląda prośba o weryfikację?

```
🧾 Paragon wymaga weryfikacji

📍 Sklep: Biedronka
📅 Data: 2025-01-31

📦 Produkty (5):
• Mleko Łaciate 2% | 4.99 zł
• Chleb pszenny | 5.49 zł
• Jabłka Gala | 7.20 zł
• Ser żółty | 12.99 zł
• Masło extra | 8.49 zł

💰 Suma z paragonu: 39.16 zł
📊 Suma produktów: 39.16 zł ✓

[✅ Zatwierdź] [✏️ Popraw sumę] [❌ Odrzuć]
```

### Co oznaczają przyciski?

| Przycisk | Kiedy użyć |
|----------|------------|
| ✅ **Zatwierdź** | Wszystko się zgadza, zapisz paragon |
| ✏️ **Popraw sumę** | Suma jest błędna, chcę ją poprawić |
| ❌ **Odrzuć** | Paragon jest nieczytelny lub błędny, nie zapisuj |

### Poprawianie sumy

Po kliknięciu "Popraw sumę" pojawią się opcje:

```
Jak chcesz poprawić sumę?

[📊 Użyj sumy z produktów: 39.16 zł]
[✍️ Wpisz ręcznie]
```

- **Użyj sumy z produktów** - system policzy sumę z wykrytych produktów
- **Wpisz ręcznie** - sam wpiszesz prawidłową kwotę

---

## Przeglądanie danych

### Komendy Telegram

Wpisz w rozmowie z botem:

| Komenda | Co robi |
|---------|---------|
| `/recent` | Ostatnie 5 paragonów |
| `/stats` | Statystyki zakupów |
| `/stores` | Lista sklepów i wydatki |
| `/categories` | Wydatki według kategorii |
| `/pantry` | Zawartość spiżarni |
| `/search mleko` | Szukaj produktu "mleko" |
| `/pending` | Paragony czekające na weryfikację |

### Przykładowe statystyki

```
📊 Statystyki zakupów

📅 Okres: styczeń 2025

🧾 Paragony: 23
💰 Suma wydatków: 1,847.32 zł
📦 Produktów: 156

🏪 Top sklepy:
1. Biedronka - 892.45 zł (12 wizyt)
2. Lidl - 534.20 zł (7 wizyt)
3. Żabka - 420.67 zł (4 wizyty)

📁 Top kategorie:
1. Nabiał - 312.50 zł
2. Mięso - 287.30 zł
3. Warzywa - 198.45 zł
```

### Dostęp przez przeglądarkę (zaawansowane)

Jeśli masz dostęp do komputera z aplikacją, możesz otworzyć:

- `http://localhost:8000` - główna strona API
- `http://localhost:8000/docs` - interaktywna dokumentacja

---

## Obsługiwane sklepy

System rozpoznaje i prawidłowo odczytuje paragony z następujących sklepów:

| Sklep | Status | Uwagi |
|-------|--------|-------|
| Biedronka | ✅ Pełne wsparcie | Obsługa rabatów, promocji |
| Lidl | ✅ Pełne wsparcie | - |
| Kaufland | ✅ Pełne wsparcie | - |
| Żabka | ✅ Pełne wsparcie | - |
| Auchan | ✅ Pełne wsparcie | - |
| Carrefour | ✅ Pełne wsparcie | - |
| Netto | ✅ Pełne wsparcie | - |
| Dino | ✅ Pełne wsparcie | - |

### Dlaczego różne sklepy?

Każdy sklep drukuje paragony w **innym formacie**:

**Biedronka:**
```
MLEKO UHT 2%        A
  1 x 4.99         4.99
  Rabat           -1.00
                   3.99
```

**Lidl:**
```
Mleko UHT 2%
1 x 4.99 = 4.99
```

**Żabka:**
```
MLEKO 2% 1L          4.99
```

System "wie" jak czytać każdy format i wyciąga prawidłowe ceny.

---

## RSS i podsumowania stron

System zawiera funkcję **subskrypcji kanałów RSS/Atom** oraz **podsumowywania stron internetowych** za pomocą AI.

### Co to robi?

| Funkcja | Opis |
|---------|------|
| 📰 Subskrypcje RSS | Śledź ulubione blogi i serwisy informacyjne |
| 📝 Podsumowania | AI generuje bullet points z kluczowymi informacjami |
| 🔄 Auto-fetch | Nowe artykuły pobierane automatycznie co 4 godziny |
| 💾 Zapis do Obsidian | Podsumowania zapisywane w `vault/summaries/` |

### Jak zacząć?

#### Dodaj kanał RSS

W Telegram wpisz:
```
/subscribe https://blog.example.com/rss
```

Bot odpowie:
```
✅ Dodano kanał: Example Blog
📰 Typ: RSS 2.0
🔗 https://blog.example.com/rss
```

#### Podsumuj pojedynczą stronę

Aby podsumować dowolny artykuł:
```
/summarize https://example.com/article
```

Bot przeczyta stronę i wygeneruje podsumowanie:
```
📝 Podsumowanie: Example Article

• Główny temat artykułu dotyczy...
• Kluczowe dane: 45% wzrost, 100 nowych użytkowników
• Autor rekomenduje wdrożenie rozwiązania X
• Wnioski: technologia Y zyskuje na popularności

📅 2026-02-02 | 🔗 example.com
```

### Komendy RSS

| Komenda | Co robi |
|---------|---------|
| `/feeds` | Lista subskrybowanych kanałów |
| `/subscribe <URL>` | Dodaj nowy kanał RSS/Atom |
| `/unsubscribe <ID>` | Usuń kanał (ID z listy `/feeds`) |
| `/summarize <URL>` | Podsumuj pojedynczą stronę |
| `/refresh` | Ręcznie pobierz nowe artykuły |
| `/articles` | Ostatnie pobrane artykuły |
| `/articles <feed_id>` | Artykuły z konkretnego kanału |

### Automatyczne pobieranie

System automatycznie sprawdza kanały RSS co **4 godziny** i pobiera nowe artykuły. Gdy znajdzie nowe treści, wysyła powiadomienie:

```
📬 Nowe artykuły (3)

📰 Example Blog:
  • Tytuł artykułu 1
  • Tytuł artykułu 2

📰 Another Feed:
  • Ciekawy artykuł
```

### Gdzie znajdę podsumowania?

Wszystkie podsumowania są zapisywane w folderze `vault/summaries/` jako pliki markdown. Możesz je przeglądać w Obsidian lub dowolnym edytorze tekstu.

**Przykładowy plik:**
```
vault/summaries/2026-02-02_example-article.md
```

### Obsługiwane formaty

| Format | Przykład |
|--------|----------|
| RSS 2.0 | Większość blogów i serwisów |
| Atom | Blogi na Bloggerze, niektóre serwisy |
| Strony HTML | Dowolna strona z `/summarize` |

---

## Słownik produktów

### Jak działa rozpoznawanie produktów?

Na paragonach produkty mają często **skrócone nazwy**:

| Na paragonie | System rozumie jako |
|--------------|---------------------|
| `ML.ŁAC.2%1L` | Mleko Łaciate 2% 1L |
| `CHLPSZŻ500` | Chleb pszenny żytni 500g |
| `SER.GOUD.PL` | Ser Gouda plastry |
| `JABŁ.ZŁOT.1KG` | Jabłka Golden 1kg |

### Uczenie nowych produktów

Jeśli system **nie rozpozna** produktu:

1. Zapisuje go na liście "nieznanych"
2. Po kilku wystąpieniach (3+) proponuje dodanie
3. Możesz zaakceptować lub poprawić nazwę

**Komenda do sprawdzenia nieznanych produktów:**
```
/unknown
```

---

## Najczęstsze pytania (FAQ)

### Czy moje dane są bezpieczne?

✅ **Tak.** Wszystkie dane są przechowywane **lokalnie** na Twoim komputerze. Nic nie jest wysyłane do chmury ani zewnętrznych serwisów.

### Czy potrzebuję internetu?

Potrzebujesz internetu tylko do:
- Komunikacji przez Telegram
- Pierwszego pobrania modeli AI

Po skonfigurowaniu system działa lokalnie.

### Ile czasu zajmuje przetworzenie paragonu?

| Długość paragonu | Czas |
|------------------|------|
| Krótki (do 10 produktów) | ~30-60 sekund |
| Średni (10-30 produktów) | ~1-2 minuty |
| Długi (30+ produktów) | ~2-4 minuty |

### Co jeśli paragon jest nieczytelny?

- Spróbuj zrobić lepsze zdjęcie (więcej światła, mniej cieni)
- Jeśli paragon jest zniszczony, możesz go odrzucić i wpisać dane ręcznie

### Czy mogę edytować zapisane paragony?

Obecnie edycja wymaga dostępu do plików. Funkcja edycji przez Telegram jest planowana.

### Jak usunąć błędny paragon?

Skontaktuj się z administratorem lub użyj komendy:
```
/delete [nazwa_pliku]
```

---

## Wsparcie

Jeśli masz problemy lub pytania:

1. Sprawdź sekcję [FAQ](#najczęstsze-pytania-faq)
2. Użyj komendy `/help` w Telegram
3. Skontaktuj się z administratorem systemu

---

*Ostatnia aktualizacja: luty 2026*
