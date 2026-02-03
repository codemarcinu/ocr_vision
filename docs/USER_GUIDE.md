# Second Brain - Przewodnik Użytkownika

> Inteligentny system zarządzania wiedzą osobistą

---

## Spis treści

1. [Co to jest Second Brain?](#co-to-jest-second-brain)
2. [Jak zacząć?](#jak-zacząć)
3. [Codzienne użycie](#codzienne-użycie)
4. [Weryfikacja paragonów](#weryfikacja-paragonów)
5. [Przeglądanie danych](#przeglądanie-danych)
6. [Obsługiwane sklepy](#obsługiwane-sklepy)
7. [RSS i podsumowania stron](#rss-i-podsumowania-stron)
8. [Transkrypcje audio/wideo](#transkrypcje-audiowideo)
9. [Baza wiedzy (RAG)](#baza-wiedzy-rag)
10. [Chat AI](#chat-ai)
11. [Notatki osobiste](#notatki-osobiste)
12. [Słownik produktów](#słownik-produktów)
13. [Interfejs webowy](#interfejs-webowy)
14. [Najczęstsze pytania (FAQ)](#najczęstsze-pytania-faq)

---

## Co to jest Second Brain?

Second Brain to **inteligentny system zarządzania wiedzą osobistą**, który:

| Funkcja | Opis |
|---------|------|
| Czyta paragony | Rozpoznaje produkty i ceny ze zdjęć paragonów |
| Kategoryzuje | Automatycznie sortuje produkty (nabiał, pieczywo, mięso...) |
| Zapamiętuje | Przechowuje historię wszystkich zakupów |
| Analizuje | Pokazuje statystyki wydatków i trendy cenowe |
| Zarządza spiżarnią | Śledzi co masz w domu |
| Podsumowuje artykuły | Śledzi kanały RSS i generuje podsumowania |
| Transkrybuje | Zamienia nagrania audio/wideo na tekst i notatki |
| Odpowiada na pytania | Przeszukuje całą bazę wiedzy i generuje odpowiedzi (RAG) |
| Rozmawia | Wieloturowy Chat AI z dostępem do RAG i wyszukiwania internetowego |
| Notatki | Osobiste notatki z tagami i kategoriami |

### Jak to działa?

```
📸 Zdjęcie paragonu / 🔗 Link / 🎙️ Nagranie / 📝 Notatka
        ↓
🤖 AI przetwarza treść
        ↓
💾 Zapis do bazy danych + Obsidian
        ↓
🧠 Automatyczne indeksowanie w bazie wiedzy (RAG)
        ↓
❓ Możesz zadawać pytania: /ask co wiem o mleku?
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
| `/ask <pytanie>` | Zapytaj bazę wiedzy (patrz sekcja [RAG](#baza-wiedzy-rag)) |

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
| Lewiatan | ✅ Obsługiwany | Prompt generyczny |
| Polo Market | ✅ Obsługiwany | Prompt generyczny |
| Stokrotka | ✅ Obsługiwany | Prompt generyczny |
| Intermarché | ✅ Obsługiwany | Prompt generyczny |

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

### Obsługiwane formaty

| Format | Przykład |
|--------|----------|
| RSS 2.0 | Większość blogów i serwisów |
| Atom | Blogi na Bloggerze, niektóre serwisy |
| Strony HTML | Dowolna strona z `/summarize` |

---

## Transkrypcje audio/wideo

System umożliwia **transkrypcję nagrań audio i wideo** (w tym filmów z YouTube) oraz automatyczne generowanie notatek z kluczowymi informacjami.

### Co to robi?

| Funkcja | Opis |
|---------|------|
| 🎬 YouTube | Transkrybuje filmy z YouTube (z URL) |
| 🎙️ Pliki audio | Transkrybuje przesłane pliki (MP3, M4A, WAV, OGG, OPUS) |
| 📝 Notatki | AI generuje podsumowanie, tematy, encje i zadania do wykonania |
| 💾 Obsidian | Notatki zapisywane w `transcriptions/` |

### Jak używać?

#### Transkrypcja filmu z YouTube

W Telegram wpisz:
```
/transcribe https://youtube.com/watch?v=abc123
```

Bot pobierze film, transkrybuje go i wygeneruje notatkę:
```
🎙️ Transkrypcja zakończona

📹 Tytuł: Interesujący film o AI
📺 Kanał: Tech Channel
⏱️ Czas: 45:00
🗣️ Język: polski
📊 Słów: 8,500

📝 Notatka wygenerowana automatycznie.
Użyj /note <ID> aby zobaczyć.
```

#### Transkrypcja pliku audio

Wyślij plik audio (MP3, M4A, WAV, OGG, OPUS) do bota - system automatycznie go transkrybuje.

### Komendy transkrypcji

| Komenda | Co robi |
|---------|---------|
| `/transcribe <URL>` | Transkrybuj film z YouTube |
| `/transcribe` + plik audio | Transkrybuj przesłany plik |
| `/transcriptions` | Lista ostatnich transkrypcji |
| `/note <ID>` | Pokaż wygenerowaną notatkę |

### Notatki z transkrypcji

Automatycznie generowana notatka zawiera:

- **Podsumowanie** - krótki opis treści
- **Główne tematy** - lista omawianych zagadnień
- **Kluczowe punkty** - najważniejsze informacje
- **Encje** - wspomniane osoby, firmy, produkty
- **Zadania do wykonania** - jeśli w nagraniu pojawiły się akcje do podjęcia

---

## Baza wiedzy (RAG)

System posiada **inteligentną bazę wiedzy**, która pozwala zadawać pytania w języku naturalnym dotyczące wszystkich zgromadzonych danych: paragonów, artykułów, transkrypcji, notatek i zakładek.

### Jak to działa?

```
❓ Pytanie: "Ile wydałem w Biedronce w styczniu?"
        ↓
🔍 Przeszukanie bazy wiedzy (embeddingi + pgvector)
        ↓
📚 Znalezienie najlepszych fragmentów
        ↓
🤖 AI generuje odpowiedź na podstawie Twoich danych
        ↓
🧠 Odpowiedź z listą źródeł
```

### Jak używać?

W Telegram wpisz `/ask` i zadaj pytanie:

```
/ask ile wydałem w Biedronce w styczniu?
```

Bot odpowie:
```
🧠 Odpowiedź:

Na podstawie paragonów ze stycznia, w Biedronce wydałeś
łącznie 892.45 zł w 12 wizytach. Najczęściej kupowane
produkty to mleko (4.99 zł), chleb (5.49 zł) i jabłka...

📚 Źródła:
  🧾 Paragon: Biedronka | 2026-01-05 | 78.50 zł
  🧾 Paragon: Biedronka | 2026-01-12 | 92.30 zł
  🧾 Paragon: Biedronka | 2026-01-19 | 65.40 zł

⏱️ 2.3s | 📊 5 fragmentów | 🤖 qwen2.5:7b
```

### Przykłady pytań

| Pytanie | Co wyszuka |
|---------|------------|
| `/ask ile wydałem w Biedronce?` | Paragony z Biedronki |
| `/ask co wiem o sztucznej inteligencji?` | Artykuły, transkrypcje, notatki o AI |
| `/ask jakie produkty kupuję najczęściej?` | Analiza paragonów |
| `/ask co mówił prelegent o bezpieczeństwie?` | Transkrypcje wykładów |
| `/ask jakie artykuły czytałem o Pythonie?` | Podsumowania RSS |

### Jakie dane są przeszukiwane?

| Typ danych | Źródło |
|------------|--------|
| 🧾 Paragony | Sklepy, daty, produkty, ceny |
| 📰 Artykuły | Podsumowania RSS i stron |
| 🎙️ Transkrypcje | Notatki z nagrań audio/wideo |
| 📝 Notatki | Osobiste notatki |
| 🔖 Zakładki | Zapisane linki z opisami |

### Automatyczne indeksowanie

Nowe treści są **automatycznie** dodawane do bazy wiedzy zaraz po ich utworzeniu. Nie musisz nic robić - system sam indeksuje nowe paragony, artykuły, transkrypcje i notatki.

### API (zaawansowane)

Baza wiedzy dostępna jest również przez REST API:

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/ask` | POST | Zadaj pytanie (JSON: `{"question": "..."}`) |
| `/ask/stats` | GET | Statystyki indeksu |
| `/ask/reindex` | POST | Pełna reindeksacja |

---

## Chat AI

System posiada **wieloturowego asystenta konwersacyjnego**, który łączy bazę wiedzy (RAG) z wyszukiwaniem internetowym (SearXNG).

### Czym różni się od /ask?

| Funkcja | `/ask` | `/chat` |
|---------|--------|---------|
| Typ rozmowy | Jednorazowe pytanie | Wieloturowa konwersacja |
| Kontekst | Tylko aktualne pytanie | Pamięta historię rozmowy |
| Źródła | Tylko baza wiedzy (RAG) | RAG + wyszukiwanie internetowe |
| Sesje | Brak | Zarządzanie sesjami |

### Jak używać?

W Telegram wpisz:
```
/chat
```

Bot utworzy nową sesję rozmowy. Każda kolejna wiadomość trafia do tej sesji:
```
💬 Sesja utworzona. Możesz teraz rozmawiać.

Ty: Co wiesz o moich wydatkach w styczniu?
Bot: Na podstawie Twoich danych z paragonów...

Ty: A jakie są najnowsze trendy w cenach mleka?
Bot: [przeszukuje internet przez SearXNG]...
```

### Klasyfikacja intencji

System automatycznie rozpoznaje typ pytania:

| Intencja | Kiedy | Przykład |
|----------|-------|---------|
| `rag` | Pytanie o osobiste dane | "ile wydałem w Biedronce?" |
| `web` | Pytanie o informacje z internetu | "jaka jest pogoda jutro?" |
| `both` | Połączenie obu źródeł | "porównaj moje wydatki z cenami rynkowymi" |
| `direct` | Bez wyszukiwania | "przetłumacz to na angielski" |

### Komendy Chat AI

| Komenda | Co robi |
|---------|---------|
| `/chat` | Rozpocznij nową sesję rozmowy |
| `/endchat` | Zakończ bieżącą sesję |

Sesje dostępne również przez menu inline (przyciski w Telegram).

---

## Notatki osobiste

System umożliwia tworzenie i zarządzanie **notatkami osobistymi** z tagami i kategoriami.

### Jak używać?

Notatki tworzy się przez REST API:

```bash
curl -X POST http://localhost:8000/notes/ \
  -H "Content-Type: application/json" \
  -d '{"title": "Moja notatka", "content": "Treść notatki...", "tags": ["ważne"]}'
```

### Gdzie znajdę notatki?

Notatki zapisywane są w folderze `notes/` jako pliki Markdown oraz w bazie danych PostgreSQL.

### API notatek

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/notes/` | GET | Lista notatek (z wyszukiwaniem i filtrami) |
| `/notes/` | POST | Utwórz nową notatkę |
| `/notes/{id}` | GET | Pobierz notatkę |
| `/notes/{id}` | PUT | Zaktualizuj notatkę |
| `/notes/{id}` | DELETE | Usuń notatkę |

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

## Interfejs webowy

System posiada interfejs webowy dostępny pod adresem `http://localhost:8000/app/`.

### Dostępne widoki

| Widok | Opis |
|-------|------|
| Dashboard | Przegląd systemu |
| Paragony | Przeglądanie i zarządzanie paragonami |
| Spiżarnia | Stan zapasów |
| Analityka | Statystyki i wykresy wydatków |
| Artykuły | Pobrane i podsumowane artykuły |
| Transkrypcje | Lista transkrypcji z notatkami |
| Notatki | Przeglądanie i edycja notatek |
| Zakładki | Zarządzanie zakładkami |
| Chat | Interfejs Chat AI |
| Słownik | Zarządzanie słownikiem produktów |
| Wyszukiwanie | Wyszukiwanie unified po całej bazie |

---

## Najczęstsze pytania (FAQ)

### Czy moje dane są bezpieczne?

✅ **Tak.** Wszystkie dane są przechowywane **lokalnie** na Twoim komputerze. Przy użyciu lokalnych backendów OCR (`vision`, `paddle`, `deepseek`) modele AI działają lokalnie przez Ollama. Przy backendach `google` lub `openai` zdjęcia paragonów są przesyłane do zewnętrznych API (Google Vision, OpenAI) w celu przetworzenia.

### Czy potrzebuję internetu?

Potrzebujesz internetu tylko do:
- Komunikacji przez Telegram
- Pierwszego pobrania modeli AI
- Pobierania artykułów RSS i transkrypcji z YouTube

Po skonfigurowaniu przetwarzanie paragonów i pytania do bazy wiedzy działają w pełni lokalnie.

### Ile czasu zajmuje przetworzenie paragonu?

| Długość paragonu | Czas |
|------------------|------|
| Krótki (do 10 produktów) | ~30-60 sekund |
| Średni (10-30 produktów) | ~1-2 minuty |
| Długi (30+ produktów) | ~2-4 minuty |

### Ile czasu zajmuje odpowiedź na pytanie (/ask)?

Zwykle 2-5 sekund - zależy od liczby fragmentów do przeszukania i wydajności GPU.

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

### Baza wiedzy nie zwraca wyników

Jeśli `/ask` nie znajduje odpowiedzi:
1. Upewnij się, że dane zostały zindeksowane (sprawdź: `curl http://localhost:8000/ask/stats`)
2. Jeśli indeks jest pusty, uruchom reindeksację: `curl -X POST http://localhost:8000/ask/reindex`
3. Spróbuj zadać pytanie innymi słowami

---

## Wszystkie komendy Telegram

| Komenda | Opis |
|---------|------|
| `/help` | Pokaż pomoc |
| `/start` | Uruchom bota |
| `/recent [N]` | Ostatnie N paragonów |
| `/pending` | Paragony do weryfikacji |
| `/reprocess <plik>` | Ponowne przetwarzanie |
| `/pantry [kategoria]` | Zawartość spiżarni |
| `/use <produkt>` | Oznacz jako zużyty |
| `/remove <produkt>` | Usuń ze spiżarni |
| `/search <fraza>` | Szukaj produktu |
| `/q <fraza>` | Szybkie wyszukiwanie |
| `/stats [week/month]` | Statystyki wydatków |
| `/stores` | Wydatki wg sklepów |
| `/categories` | Wydatki wg kategorii |
| `/rabaty` | Raport rabatów |
| `/errors` | Lista błędów OCR |
| `/clearerrors` | Wyczyść błędy |
| `/feeds` | Lista kanałów RSS |
| `/subscribe <URL>` | Dodaj kanał RSS |
| `/unsubscribe <ID>` | Usuń kanał RSS |
| `/summarize <URL>` | Podsumuj stronę |
| `/refresh` | Pobierz nowe artykuły |
| `/articles [feed_id]` | Lista artykułów |
| `/transcribe <URL>` | Transkrybuj YouTube |
| `/transcriptions` | Lista transkrypcji |
| `/note <ID>` | Notatka z transkrypcji |
| `/n <tekst>` | Szybka notatka |
| `/ask <pytanie>` | Zapytaj bazę wiedzy |
| `/find <fraza>` | Szukaj w bazie wiedzy |
| `/chat` | Rozpocznij sesję Chat AI |
| `/endchat` | Zakończ sesję Chat AI |
| `/settings` | Ustawienia bota |

---

## Wsparcie

Jeśli masz problemy lub pytania:

1. Sprawdź sekcję [FAQ](#najczęstsze-pytania-faq)
2. Użyj komendy `/help` w Telegram
3. Skontaktuj się z administratorem systemu

---

*Ostatnia aktualizacja: luty 2026*
