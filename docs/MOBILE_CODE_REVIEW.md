# Mobile PWA - Code Review & Fixes

**Data:** 2026-02-06
**Status:** Zakończono

---

## Krytyczne (Security)

### CR-1. XSS w `showToast()` — mobile.js:2046
- **Problem:** `message` wstawiany przez `innerHTML` bez escaping
- **Fix:** Użyto `textContent` + DOM API zamiast `innerHTML`
- [x] Done

### CR-2. XSS w `_showContextMenu()` — mobile.js:779
- **Problem:** `item.label` wstawiany bez escaping do `innerHTML`
- **Fix:** Użyto `textContent` + `createElement` dla label
- [x] Done

### CR-3. XSS w status phase SSE — mobile.js:310
- **Problem:** `innerHTML` z danymi z serwera (choć fallback bezpieczny)
- **Fix:** Użyto `textContent` + DOM API dla tekstu statusu
- [x] Done

### CR-4. Brak try/catch w SSE JSON.parse — mobile.js:300
- **Problem:** Uszkodzona linia SSE crashuje cały stream
- **Fix:** Wrap w try/catch, skip malformed lines z console.warn
- [x] Done

---

## Wysokie (Bugs / Memory leaks)

### CR-5. Memory leak w waveform canvas — mobile.js:1179-1182
- **Problem:** `ctx.scale()` kumuluje się co klatkę requestAnimationFrame
- **Fix:** Zamieniono `ctx.scale()` na `ctx.setTransform(dpr, 0, 0, dpr, 0, 0)` — resetuje transformację
- [x] Done

### CR-6. Duplikacja empty-state HTML — mobile.js:1325 i 1398
- **Problem:** Ten sam HTML empty-state zduplikowany 2x, hardcoded sugestie
- **Fix:** Wydzielono `_createEmptyStateHTML()` helper, obie lokalizacje go używają. Sugestie ładowane dynamicznie przez `loadDynamicSuggestions()`
- [x] Done

### CR-7. Race condition w `file-input` — mobile.js:838-854
- **Problem:** Ponowne otwarcie tego samego pliku nie triggeruje `onchange`
- **Fix:** Dodano `input.value = ''` przed `click()` aby reset wartości
- [x] Done

### CR-8. Brak `rel="noopener noreferrer"` w dynamicznych linkach — mobile.js:460
- **Problem:** Source links tworzone w `addMessage()` bez `rel`
- **Fix:** Dodano `link.rel = 'noopener noreferrer'`
- [x] Done

---

## Średnie (Performance / UX)

### CR-9. `scrollToBottom()` na każdy token SSE — mobile.js:342
- **Problem:** Setki timerów scroll przy szybkim streamingu
- **Fix:** Throttle co 80ms — markdown render + scroll w jednym cyklu
- [x] Done

### CR-10. `renderMarkdown()` na każdy token — mobile.js:341
- **Problem:** O(n²) — cały tekst re-parsowany przez marked+DOMPurify przy każdym tokenie
- **Fix:** Debounce render co 80ms z `setTimeout`. Timer czyszczony na `done` event.
- [x] Done

### CR-11. Brak `rel` w action card links — mobile.js:556-572
- **Problem:** Przegląd wykazał, że bookmark link JUŻ miał `rel`. Linki wewnętrzne (`/m/...`) nie potrzebują.
- [x] OK (already correct)

### CR-12. Inline theme script w base.html:3
- **Problem:** Inline `<script>` — sprzeczne z CSP (plan 1.6)
- **Decyzja:** Zostawić — zapobiega FOUC, CSP nonce byłby overengineering
- [x] Skip (by design)

### CR-13. Shadowed `data` variable w chat_api.py:268
- **Problem:** Analiza wykazała, że zmienna już nazywa się `done_data` — brak faktycznego shadowingu
- [x] OK (false alarm)

---

## Niskie (Accessibility / Code quality)

### CR-14. Brak `aria-label` na ikonowych przyciskach
- **Problem:** Screen readers nie czytają emoji
- **Fix:** Dodano `aria-label` + `aria-hidden="true"` na emoji span do: history-btn, settings-btn, push-toggle, camera, voice, attach, send, bottom-nav
- [x] Done

### CR-15. Hardcoded rgba(255,255,255) w light mode
- **Problem:** Białe bordery niewidoczne w light mode
- **Fix:** Dodano `--border-subtle` CSS variable (dark: `rgba(255,255,255,0.1)`, light: `rgba(0,0,0,0.1)`). Zamieniono 3 wystąpienia w `.message-sources`, `.msg-action-btn:active`, `.url-action-bar`
- [x] Done

### CR-16. `user-scalable=no` w viewport
- **Problem:** Blokuje zoom — WCAG 1.4.4
- **Fix:** Zamieniono na `viewport-fit=cover` (bez `maximum-scale` i `user-scalable=no`)
- [x] Done

---

## Log napraw

| # | Severity | Status | Notatki |
|---|----------|--------|---------|
| CR-1 | CRITICAL | ✅ Done | XSS showToast → textContent |
| CR-2 | CRITICAL | ✅ Done | XSS contextMenu → createElement |
| CR-3 | CRITICAL | ✅ Done | XSS SSE status → textContent |
| CR-4 | CRITICAL | ✅ Done | JSON.parse → try/catch |
| CR-5 | HIGH | ✅ Done | ctx.scale → ctx.setTransform |
| CR-6 | HIGH | ✅ Done | _createEmptyStateHTML() |
| CR-7 | HIGH | ✅ Done | input.value = '' reset |
| CR-8 | HIGH | ✅ Done | rel=noopener noreferrer |
| CR-9 | MEDIUM | ✅ Done | Throttle scroll 80ms |
| CR-10 | MEDIUM | ✅ Done | Debounce markdown 80ms |
| CR-11 | MEDIUM | ✅ OK | Already had rel |
| CR-12 | MEDIUM | ⏭️ Skip | Inline theme (FOUC prevention) |
| CR-13 | MEDIUM | ✅ OK | False alarm (already done_data) |
| CR-14 | LOW | ✅ Done | aria-label + aria-hidden |
| CR-15 | LOW | ✅ Done | --border-subtle CSS var |
| CR-16 | LOW | ✅ Done | viewport-fit=cover |

**Pliki zmodyfikowane:**
- `app/static/js/mobile.js` — CR-1,2,3,4,5,6,7,8,9,10
- `app/static/css/mobile.css` — CR-15
- `app/templates/mobile/base.html` — CR-14,16
