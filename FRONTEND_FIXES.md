# Plan naprawy frontendu

## Status: ZAKOŃCZONY

---

## KRYTYCZNE (500/404)

### 1. Brakujące szablony analytics
- **Problem:** `analytics.py:38` renderuje `analytics/partials/{tab}_chart.html` — brakuje 3 z 4 szablonów
- **Rozwiązanie:** Tabs używają zwykłych `<a href>`, nie HTMX — usunięto logikę `HX-Request` (niepotrzebna, pełna strona zawsze zawiera JS+canvas dla danego taba)
- **Plik:** `app/web/analytics.py` — linia 37
- [x] Usunięto `if request.headers.get("HX-Request")` branch, zawsze zwraca `analytics/index.html`

### 2. Brakujący endpoint `/app/spizarnia/backfill`
- **Problem:** `pantry/index.html:9` wywołuje `hx-post="/app/spizarnia/backfill"` — endpoint nie istnieje
- **Rozwiązanie:** Dodano endpoint POST importujący produkty z paragonów do spiżarni (pomija już zaimportowane)
- **Plik:** `app/web/pantry.py` — nowy endpoint `pantry_backfill()`
- [x] Endpoint: wyszukuje `ReceiptItem` bez powiązanego `PantryItem`, dodaje do spiżarni batch (limit 500)

---

## BEZPIECZEŃSTWO (XSS)

### 3. XSS w `showToast()` via innerHTML
- **Problem:** `app.js:84` — `message` wstawiany bez escapowania do innerHTML
- **Rozwiązanie:** Zmieniono na `createElement` + `textContent` — message nigdy nie jest interpretowany jako HTML
- **Plik:** `app/static/js/app.js` — linie 81-92
- [x] `textContent` zamiast innerHTML dla treści wiadomości

### 4. XSS w `upload.js` via `file.name`
- **Problem:** `upload.js:53` — nazwa pliku (kontrolowana przez użytkownika) w innerHTML
- **Rozwiązanie:** Dodano placeholder `<div id="preview-filename">` i ustawiany via `textContent`
- **Plik:** `app/static/js/upload.js` — linie 49-56
- [x] `textContent` zamiast innerHTML dla nazwy pliku

### 5. Fallback markdown w mobile.js
- **Problem:** `mobile.js:530-539` — regex fallback tworzy HTML bez DOMPurify
- **Analiza:** Fallback jest BEZPIECZNY — najpierw escapuje HTML (`&`, `<`, `>`, `"`), potem dopiero stosuje regex na escapowanym tekście. Captured groups `$1` zawierają tylko escaped content.
- [x] Zweryfikowano — brak zmiany potrzebna

---

## BŁĘDY FUNKCJONALNE

### 6. Nieaktualna wzmianka o Telegramie
- **Problem:** `bookmark_list.html:47` — "wyślij URL przez Telegram" (Telegram bot usunięty)
- **Plik:** `app/templates/bookmarks/partials/bookmark_list.html` — linia 47
- [x] Usunięto "lub wyślij URL przez Telegram"

---

## ŚREDNIE (UX/A11y)

### 7. `aria-expanded` sidebar nie aktualizowane
- **Problem:** `base.html:26` — `aria-expanded="false"` nigdy nie zmieniane dynamicznie
- **Rozwiązanie:** `app.js` toggle ustawia `aria-expanded` na true/false przy toggle i zamykaniu
- **Plik:** `app/static/js/app.js` — linie 42-45, 49-52
- [x] Toggle: `toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false')`
- [x] Backdrop close: `toggle.setAttribute('aria-expanded', 'false')`

### 8. Brakujące `for`/`id` na label+input
- **Pliki:**
- [x] `pantry/partials/add_form.html` — `for="pantry-add-name"`, `for="pantry-add-category"`
- [x] `pantry/partials/edit_form.html` — `for="pantry-edit-name"`, `for="pantry-edit-category"`

### 9. `<tr onclick>` niedostępny z klawiatury
- **Problem:** `table_rows.html:2` — `<tr onclick>` nie fokusuje się klawiszem Tab
- **Rozwiązanie:** Dodano `tabindex="0"`, `role="link"`, `onkeydown` obsługę Enter
- **Plik:** `app/templates/receipts/partials/table_rows.html` — linia 2
- [x] `<tr ... tabindex="0" role="link" onkeydown="if(event.key==='Enter')...">`

---

## NISKIE

### 10. Polskie znaki w komunikatach JS
- **Problem:** `app.js:107-110` — ASCII zamiast polskich znaków
- **Plik:** `app/static/js/app.js` — linie 109-112
- [x] `Wystąpił błąd`, `Błąd serwera`, `Brak połączenia z serwerem`

---

## Wcześniej naprawione (przed tym planem)

### 0. CSP brak `https://` prefix
- **Problem:** `main.py:85-92` — `cdn.jsdelivr.net` bez `https://` w CSP
- [x] Naprawiono na początku sesji — dodano `https://` prefix

---

## Log zmian

| # | Zmiana | Plik | Typ |
|---|--------|------|-----|
| 0 | CSP `https://` prefix | `app/main.py` | Bezpieczeństwo |
| 1 | Usunięto HX-Request branch analytics | `app/web/analytics.py` | Krytyczne |
| 2 | Dodano endpoint `/app/spizarnia/backfill` | `app/web/pantry.py` | Krytyczne |
| 3 | XSS fix showToast — textContent | `app/static/js/app.js` | Bezpieczeństwo |
| 4 | XSS fix file.name — textContent | `app/static/js/upload.js` | Bezpieczeństwo |
| 5 | mobile.js fallback — zweryfikowano OK | — | Bezpieczeństwo |
| 6 | Usunięto wzmiankę o Telegramie | `bookmarks/partials/bookmark_list.html` | Funkcjonalne |
| 7 | aria-expanded aktualizowane dynamicznie | `app/static/js/app.js` | A11y |
| 8 | label for/id w pantry forms | `pantry/partials/add_form.html`, `edit_form.html` | A11y |
| 9 | tr tabindex+role+onkeydown | `receipts/partials/table_rows.html` | A11y |
| 10 | Polskie znaki w komunikatach błędów | `app/static/js/app.js` | Kosmetyka |

## Podsumowanie

**10 zmian w 8 plikach:**
- 2 krytyczne (500/404 → naprawione)
- 3 bezpieczeństwo (2 XSS naprawione, 1 zweryfikowany OK)
- 1 funkcjonalny (nieaktualna treść)
- 3 dostępność (aria, label, keyboard nav)
- 1 kosmetyka (polskie znaki)
