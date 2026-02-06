# Second Brain - Przewodnik Użytkownika

> Inteligentny system zarządzania wiedzą osobistą

---

## Spis treści

1. [Co to jest Second Brain?](#co-to-jest-second-brain)
2. [Jak zacząć?](#jak-zacząć)
3. [Interfejsy](#interfejsy)
4. [Codzienne użycie](#codzienne-użycie)
5. [Weryfikacja paragonów](#weryfikacja-paragonów)
6. [Przeglądanie danych](#przeglądanie-danych)
7. [Obsługiwane sklepy](#obsługiwane-sklepy)
8. [RSS i podsumowania stron](#rss-i-podsumowania-stron)
9. [Transkrypcje audio/wideo](#transkrypcje-audiowideo)
10. [Baza wiedzy (RAG)](#baza-wiedzy-rag)
11. [Chat AI](#chat-ai)
12. [Agent - inteligentne akcje](#agent---inteligentne-akcje)
13. [Notatki osobiste](#notatki-osobiste)
14. [Słownik produktów](#słownik-produktów)
15. [Najczęstsze pytania (FAQ)](#najczęstsze-pytania-faq)

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
| Wykonuje akcje | Agent automatycznie rozpoznaje intencje i wykonuje akcje |
| Notatki | Osobiste notatki z tagami i kategoriami |

### Jak to działa?

```
Zdjęcie paragonu / Link / Nagranie / Notatka
        |
   AI przetwarza treść
        |
   Zapis do bazy danych + Obsidian
        |
   Automatyczne indeksowanie w bazie wiedzy (RAG)
        |
   Możesz zadawać pytania w Chat AI
```

---

## Jak zacząć?

### Wymagania

- Komputer z Docker (administrator lub osoba techniczna pomoże to zainstalować)
- Przeglądarka internetowa (Chrome, Firefox, Safari)
- Smartfon do robienia zdjęć paragonów (opcjonalnie - Mobile PWA)

### Pierwsze uruchomienie

1. **Uruchom aplikację** - administrator uruchamia system komendą:
   ```
   docker-compose up -d
   ```

2. **Otwórz przeglądarkę** - wejdź na adres podany przez administratora:
   - **Desktop:** `http://localhost:8000/app/` - pełny interfejs Web UI
   - **Telefon:** `http://localhost:8000/m/` - Mobile PWA (można zainstalować)

3. **Zainstaluj na telefonie (opcjonalnie)** - otwórz `/m/` w Chrome na telefonie i wybierz "Zainstaluj aplikację" z menu. Dzięki temu Second Brain pojawi się jako osobna aplikacja z ikonką na ekranie głównym.

4. **Wyślij pierwsze zdjęcie** - na dashboardzie kliknij "Dodaj paragon" i wybierz zdjęcie

5. **Gotowe!** - system przetworzy paragon i zapisze dane

---

## Interfejsy

System oferuje trzy sposoby dostępu:

### Web UI (Desktop)

Pełny interfejs dostępny pod `http://localhost:8000/app/`:

| Widok | Opis |
|-------|------|
| Dashboard | Przegląd systemu, szybkie akcje |
| Paragony | Przeglądanie i zarządzanie paragonami |
| Spiżarnia | Stan zapasów |
| Analityka | Statystyki i wykresy wydatków |
| Artykuły | Pobrane i podsumowane artykuły RSS |
| Transkrypcje | Lista transkrypcji z notatkami |
| Notatki | Przeglądanie i edycja notatek |
| Zakładki | Zarządzanie zakładkami |
| Chat | Interfejs Chat AI |
| Słownik | Zarządzanie słownikiem produktów |
| Wyszukiwanie | Wyszukiwanie po całej bazie |

### Mobile PWA (Telefon)

Interfejs mobilny pod `http://localhost:8000/m/`:

- Chat-centryczny design zoptymalizowany pod telefon
- Możliwość instalacji jako aplikacja (PWA)
- Obsługa offline z kolejką żądań
- Web Share Target - udostępniaj zdjęcia i linki z innych aplikacji
- Skróty: aparat (paragon), notatka, dyktafon

### REST API

Programistyczny dostęp do wszystkich funkcji:
- Dokumentacja Swagger: `http://localhost:8000/docs`
- Wszystkie endpointy opisane w sekcjach poniżej

---

## Codzienne użycie

### Sposób 1: Przez telefon (Mobile PWA)

1. Otwórz aplikację Second Brain na telefonie
2. Zrób zdjęcie paragonu aparatem lub wybierz z galerii
3. Wyślij przez dashboard lub udostępnij z galerii zdjęć
4. Poczekaj na przetworzenie (zwykle 30s-2min)

### Sposób 2: Przez przeglądarkę (Web UI)

1. Otwórz `http://localhost:8000/app/` w przeglądarce
2. Na dashboardzie kliknij "Dodaj paragon"
3. Wybierz zdjęcie lub PDF
4. System przetworzy i wyświetli wynik

### Sposób 3: Przez folder na komputerze

1. Skopiuj zdjęcie paragonu do folderu `paragony/inbox/`
2. System automatycznie je przetworzy
3. Wynik pojawi się w folderze `vault/paragony/`

**Wskazówki do robienia zdjęć:**
- Paragon powinien być dobrze oświetlony
- Unikaj cieni i odblasków
- Cały paragon powinien być widoczny
- Tekst powinien być czytelny (nie rozmazany)

### Obsługiwane formaty plików

| Format | Opis |
|--------|------|
| PNG | Zdjęcia z telefonu |
| JPG/JPEG | Zdjęcia z telefonu |
| WEBP | Zdjęcia z niektórych aplikacji |
| PDF | Zeskanowane paragony (także wielostronicowe) |

---

## Weryfikacja paragonów

Czasami AI nie jest w 100% pewna odczytu. Wtedy **poprosi Cię o pomoc** przez Web UI.

### Kiedy pojawia się weryfikacja?

- Suma produktów różni się od sumy na paragonie o więcej niż **5 zł**
- Różnica procentowa jest większa niż **10%**

### Jak wygląda prośba o weryfikację?

W interfejsie webowym paragon wyświetli się ze statusem "Do weryfikacji":

```
Paragon wymaga weryfikacji

Sklep: Biedronka
Data: 2026-01-31

Produkty (5):
  Mleko Łaciate 2%  | 4.99 zł
  Chleb pszenny     | 5.49 zł
  Jabłka Gala       | 7.20 zł
  Ser żółty         | 12.99 zł
  Masło extra       | 8.49 zł

Suma z paragonu:  39.16 zł
Suma produktów:   39.16 zł

[Zatwierdź] [Popraw sumę] [Odrzuć]
```

### Co oznaczają przyciski?

| Przycisk | Kiedy użyć |
|----------|------------|
| **Zatwierdź** | Wszystko się zgadza, zapisz paragon |
| **Popraw sumę** | Suma jest błędna, chcę ją poprawić |
| **Odrzuć** | Paragon jest nieczytelny lub błędny, nie zapisuj |

### Poprawianie sumy

Po kliknięciu "Popraw sumę" pojawią się opcje:
- **Użyj sumy z produktów** - system policzy sumę z wykrytych produktów
- **Wpisz ręcznie** - sam wpiszesz prawidłową kwotę

---

## Przeglądanie danych

### Web UI

W interfejsie webowym (`/app/`) dostępne są widoki:

| Widok | Co pokazuje |
|-------|-------------|
| Dashboard | Przegląd: ostatnie paragony, statystyki |
| Paragony | Lista paragonów z filtrowaniem i wyszukiwaniem |
| Spiżarnia | Aktualne zapasy z kategoriami |
| Analityka | Wykresy wydatków, trendy, porównania |
| Wyszukiwanie | Szukanie po całej bazie (paragony, notatki, artykuły...) |

### Przykładowe statystyki (Analityka)

```
Statystyki zakupów

Okres: styczeń 2026

Paragony: 23
Suma wydatków: 1,847.32 zł
Produktów: 156

Top sklepy:
1. Biedronka - 892.45 zł (12 wizyt)
2. Lidl - 534.20 zł (7 wizyt)
3. Żabka - 420.67 zł (4 wizyty)

Top kategorie:
1. Nabiał - 312.50 zł
2. Mięso - 287.30 zł
3. Warzywa - 198.45 zł
```

---

## Obsługiwane sklepy

System rozpoznaje i prawidłowo odczytuje paragony z następujących sklepów:

| Sklep | Status | Uwagi |
|-------|--------|-------|
| Biedronka | Pełne wsparcie | Obsługa rabatów, promocji |
| Lidl | Pełne wsparcie | - |
| Kaufland | Pełne wsparcie | - |
| Żabka | Pełne wsparcie | - |
| Auchan | Pełne wsparcie | - |
| Carrefour | Pełne wsparcie | - |
| Netto | Pełne wsparcie | - |
| Dino | Pełne wsparcie | - |
| Lewiatan | Obsługiwany | Prompt generyczny |
| Polo Market | Obsługiwany | Prompt generyczny |
| Stokrotka | Obsługiwany | Prompt generyczny |
| Intermarché | Obsługiwany | Prompt generyczny |

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

System umożliwia **subskrypcję kanałów RSS/Atom** oraz **podsumowywanie stron internetowych** za pomocą AI.

### Co to robi?

| Funkcja | Opis |
|---------|------|
| Subskrypcje RSS | Śledź ulubione blogi i serwisy informacyjne |
| Podsumowania | AI generuje bullet points z kluczowymi informacjami |
| Zapis do Obsidian | Podsumowania zapisywane jako pliki markdown |
| Auto-indeksowanie RAG | Nowe artykuły automatycznie trafiają do bazy wiedzy |

### Jak używać?

#### Przez Web UI

W sekcji **Artykuły** (`/app/articles`):
- Przeglądaj pobrane artykuły
- Dodawaj nowe kanały RSS
- Podsumowuj pojedyncze strony wklejając URL

#### Przez API

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/rss/feeds` | GET | Lista kanałów |
| `/rss/feeds` | POST | Dodaj kanał RSS |
| `/rss/summarize` | POST | Podsumuj URL |
| `/rss/articles` | GET | Lista artykułów |
| `/rss/fetch` | POST | Pobierz nowe artykuły |

### Gdzie znajdę podsumowania?

Wszystkie podsumowania są zapisywane w folderze konfigurowanym w ustawieniach (domyślnie `vault/summaries/`) jako pliki markdown. Możesz je przeglądać w Obsidian lub dowolnym edytorze tekstu.

### Obsługiwane formaty

| Format | Przykład |
|--------|----------|
| RSS 2.0 | Większość blogów i serwisów |
| Atom | Blogi na Bloggerze, niektóre serwisy |
| Strony HTML | Dowolna strona przez podsumowywanie URL |

---

## Transkrypcje audio/wideo

System umożliwia **transkrypcję nagrań audio i wideo** (w tym filmów z YouTube) oraz automatyczne generowanie notatek z kluczowymi informacjami.

### Co to robi?

| Funkcja | Opis |
|---------|------|
| YouTube | Transkrybuje filmy z YouTube (z URL) |
| Pliki audio | Transkrybuje przesłane pliki (MP3, M4A, WAV, OGG, OPUS) |
| Notatki | AI generuje podsumowanie, tematy, encje i zadania do wykonania |
| Obsidian | Notatki zapisywane w `transcriptions/` |

### Jak używać?

#### Przez Web UI

W sekcji **Transkrypcje** (`/app/transcriptions`):
- Wklej URL filmu z YouTube
- Lub prześlij plik audio
- System automatycznie transkrybuje i wygeneruje notatkę

#### Przez API

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/transcription/jobs` | GET/POST | Lista/tworzenie zadań |
| `/transcription/jobs/upload` | POST | Upload pliku audio |
| `/transcription/jobs/{id}/note` | GET | Pobranie notatki |
| `/transcription/jobs/{id}/generate-note` | POST | Generowanie notatki |

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
Pytanie: "Ile wydałem w Biedronce w styczniu?"
        |
   Przeszukanie bazy wiedzy (embeddingi + pgvector)
        |
   Znalezienie najlepszych fragmentów
        |
   AI generuje odpowiedź na podstawie Twoich danych
        |
   Odpowiedź z listą źródeł
```

### Jak używać?

#### Przez Chat (zalecany sposób)

Otwórz Chat (`/app/chat` lub `/m/chat`) i po prostu zadaj pytanie:

```
Ty: Ile wydałem w Biedronce w styczniu?
AI: Na podstawie paragonów ze stycznia, w Biedronce wydałeś
    łącznie 892.45 zł w 12 wizytach...
```

#### Przez sekcję "Zapytaj" w Web UI

W sekcji **Zapytaj** (`/app/ask`) wpisz pytanie - system przeszuka bazę wiedzy i wygeneruje odpowiedź.

#### Przez API

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "ile wydałem w Biedronce?"}'
```

### Przykłady pytań

| Pytanie | Co wyszuka |
|---------|------------|
| "Ile wydałem w Biedronce?" | Paragony z Biedronki |
| "Co wiem o sztucznej inteligencji?" | Artykuły, transkrypcje, notatki o AI |
| "Jakie produkty kupuję najczęściej?" | Analiza paragonów |
| "Co mówił prelegent o bezpieczeństwie?" | Transkrypcje wykładów |
| "Jakie artykuły czytałem o Pythonie?" | Podsumowania RSS |

### Jakie dane są przeszukiwane?

| Typ danych | Źródło |
|------------|--------|
| Paragony | Sklepy, daty, produkty, ceny |
| Artykuły | Podsumowania RSS i stron |
| Transkrypcje | Notatki z nagrań audio/wideo |
| Notatki | Osobiste notatki |
| Zakładki | Zapisane linki z opisami |

### Automatyczne indeksowanie

Nowe treści są **automatycznie** dodawane do bazy wiedzy zaraz po ich utworzeniu. Nie musisz nic robić - system sam indeksuje nowe paragony, artykuły, transkrypcje i notatki.

---

## Chat AI

System posiada **wieloturowego asystenta konwersacyjnego**, który łączy bazę wiedzy (RAG) z wyszukiwaniem internetowym (SearXNG).

### Jak używać?

Otwórz Chat w Web UI (`/app/chat`) lub Mobile PWA (`/m/chat`) i po prostu napisz wiadomość:

```
Ty: Ile wydałem w Biedronce w tym miesiącu?
AI: Na podstawie Twoich paragonów, w tym miesiącu wydałeś...

Ty: A jakie produkty kupuję najczęściej?
AI: Według danych z zakupów, najczęściej kupujesz...
```

System automatycznie utworzy sesję rozmowy i będzie pamiętać kontekst.

### Czym różni się od "Zapytaj" (/ask)?

| Funkcja | Zapytaj (/ask) | Chat |
|---------|----------------|------|
| Typ rozmowy | Jednorazowe pytanie | Wieloturowa konwersacja |
| Kontekst | Tylko aktualne pytanie | Pamięta historię rozmowy |
| Źródła | Tylko baza wiedzy (RAG) | RAG + wyszukiwanie internetowe |
| Akcje | Tylko odpowiedzi | Może wykonywać akcje (notatki, zakładki...) |

### Inteligentne akcje

Chat automatycznie rozpoznaje, gdy chcesz coś zrobić, a nie tylko zapytać:

```
Ty: Zanotuj że jutro mam spotkanie o 10
AI: Utworzono notatkę: "Spotkanie o 10"

Ty: Zapisz ten link https://example.com
AI: Dodano zakładkę: example.com
```

Więcej o automatycznych akcjach: [Agent - inteligentne akcje](#agent---inteligentne-akcje)

### Klasyfikacja intencji

System automatycznie rozpoznaje typ pytania:

| Intencja | Kiedy | Przykład |
|----------|-------|---------|
| `rag` | Pytanie o osobiste dane | "ile wydałem w Biedronce?" |
| `web` | Pytanie o informacje z internetu | "jaka jest pogoda jutro?" |
| `both` | Połączenie obu źródeł | "porównaj moje wydatki z cenami rynkowymi" |
| `direct` | Bez wyszukiwania | "przetłumacz to na angielski" |

---

## Agent - inteligentne akcje

System posiada **agenta AI**, który automatycznie rozpoznaje intencje w wiadomościach i wykonuje odpowiednie akcje.

### Jak to działa?

Gdy piszesz w Chat, agent analizuje wiadomość:
- **Pytanie o dane?** → Przeszukuje bazę wiedzy
- **Polecenie akcji?** → Wykonuje natychmiast

```
Wiadomość: "Zanotuj że jutro mam dentystę o 10"
    |
Agent rozpoznaje: create_note
    |
Tworzy notatkę automatycznie
```

### Co potrafi agent?

| Powiedz | Agent zrobi |
|---------|-------------|
| "Zanotuj: spotkanie jutro o 10" | Utworzy notatkę |
| "Zapisz link https://..." | Doda zakładkę |
| "Podsumuj artykuł https://..." | Wygeneruje podsumowanie |
| "Co mam w lodówce?" | Pokaże stan spiżarni |
| "Ile wydałem w Biedronce?" | Pokaże wydatki |
| "Jaka jest pogoda?" | Sprawdzi pogodę |
| "Pokaż ostatnie notatki" | Wyświetli listę |
| "Wyszukaj w internecie..." | Przeszuka internet |

### Przykłady użycia naturalnym językiem

Agent świetnie rozumie naturalny, potoczny język:

```
"Hej, zapisz mi że jutro mam dentystę o 10"
→ Utworzy notatkę

"Zanotuj: kupić mleko, chleb i masło"
→ Utworzy listę zakupów

"Przypomnij mi żeby zadzwonić do mamy"
→ Utworzy notatkę-przypomnienie

"Chcę zapisać tego linka do przeczytania https://..."
→ Doda zakładkę
```

### Kiedy agent działa?

Agent jest zintegrowany z Chat AI i działa automatycznie przy każdej wiadomości. Nie musisz używać żadnych specjalnych komend - po prostu pisz w Chat.

---

## Notatki osobiste

System umożliwia tworzenie i zarządzanie **notatkami osobistymi** z tagami i kategoriami.

### Jak używać?

#### Przez Chat (najłatwiejszy sposób)

W Chat napisz:
```
Zanotuj: jutro spotkanie z klientem o 14:00
```

Agent automatycznie utworzy notatkę.

#### Przez Web UI

W sekcji **Notatki** (`/app/notes`):
- Przeglądaj istniejące notatki
- Twórz nowe notatki z tytułem, treścią i tagami
- Edytuj i usuwaj notatki

#### Przez API

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/notes/` | GET | Lista notatek (z wyszukiwaniem i filtrami) |
| `/notes/` | POST | Utwórz nową notatkę |
| `/notes/{id}` | GET | Pobierz notatkę |
| `/notes/{id}` | PUT | Zaktualizuj notatkę |
| `/notes/{id}` | DELETE | Usuń notatkę |

### Gdzie znajdę notatki?

Notatki zapisywane są w bazie danych PostgreSQL oraz opcjonalnie jako pliki Markdown w folderze `notes/` (Obsidian).

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

### Zarządzanie słownikiem

W Web UI sekcja **Słownik** (`/app/dictionary`) umożliwia:
- Przeglądanie znanych produktów i ich mapowań
- Dodawanie nowych skrótów i produktów
- Edycję istniejących wpisów

### Uczenie nowych produktów

Jeśli system **nie rozpozna** produktu:

1. Zapisuje go na liście "nieznanych"
2. Po kilku wystąpieniach (3+) proponuje dodanie
3. Możesz zaakceptować lub poprawić nazwę w słowniku

---

## Najczęstsze pytania (FAQ)

### Czy moje dane są bezpieczne?

**Tak.** Wszystkie dane są przechowywane **lokalnie** na Twoim komputerze. Przy użyciu lokalnych backendów OCR (`vision`, `paddle`, `deepseek`) modele AI działają lokalnie przez Ollama. Przy backendach `google` lub `openai` zdjęcia paragonów są przesyłane do zewnętrznych API (Google Vision, OpenAI) w celu przetworzenia.

### Czy potrzebuję internetu?

Potrzebujesz internetu tylko do:
- Pierwszego pobrania modeli AI
- Pobierania artykułów RSS i transkrypcji z YouTube
- Wyszukiwania internetowego w Chat AI (SearXNG)

Po skonfigurowaniu przetwarzanie paragonów i pytania do bazy wiedzy działają w pełni lokalnie.

### Ile czasu zajmuje przetworzenie paragonu?

| Długość paragonu | Czas |
|------------------|------|
| Krótki (do 10 produktów) | ~30-60 sekund |
| Średni (10-30 produktów) | ~1-2 minuty |
| Długi (30+ produktów) | ~2-4 minuty |

### Ile czasu zajmuje odpowiedź na pytanie?

Zwykle 2-5 sekund - zależy od liczby fragmentów do przeszukania i wydajności GPU.

### Co jeśli paragon jest nieczytelny?

- Spróbuj zrobić lepsze zdjęcie (więcej światła, mniej cieni)
- Jeśli paragon jest zniszczony, możesz go odrzucić i wpisać dane ręcznie

### Czy mogę edytować zapisane paragony?

Tak - w Web UI w sekcji **Paragony** (`/app/receipts`) możesz przeglądać szczegóły paragonów.

### Baza wiedzy nie zwraca wyników

Jeśli Chat lub "Zapytaj" nie znajduje odpowiedzi:
1. Upewnij się, że dane zostały zindeksowane (sprawdź: `http://localhost:8000/ask/stats`)
2. Jeśli indeks jest pusty, uruchom reindeksację przez API: `POST /ask/reindex`
3. Spróbuj zadać pytanie innymi słowami

### Agent nie wykonuje akcji

Jeśli agent nie rozpoznaje Twoich poleceń:
1. Upewnij się, że `CHAT_AGENT_ENABLED=true` jest ustawione w konfiguracji
2. Spróbuj bardziej bezpośredniego polecenia: "Zanotuj: ..." zamiast "może warto by zapisać..."
3. Sprawdź logi systemu czy nie ma błędów

### Jak uzyskać dostęp z telefonu?

Otwórz `http://<adres-serwera>:8000/m/` w przeglądarce na telefonie. Możesz zainstalować aplikację jako PWA - wybierz "Dodaj do ekranu głównego" w menu przeglądarki.

### Jak zabezpieczyć dostęp?

Ustaw zmienną `AUTH_TOKEN` w konfiguracji. Po włączeniu:
- Web UI wymaga logowania (sesja 8h)
- API wymaga nagłówka `Authorization: Bearer <token>`

---

## Wsparcie

Jeśli masz problemy lub pytania:

1. Sprawdź sekcję [FAQ](#najczęstsze-pytania-faq)
2. Zajrzyj do dokumentacji API: `http://localhost:8000/docs`
3. Skontaktuj się z administratorem systemu

---

*Ostatnia aktualizacja: luty 2026*
