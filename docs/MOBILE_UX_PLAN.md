# Mobile Chat UI/UX - Plan ulepszeń

**Data analizy:** 2026-02-06
**Status:** Zakończono (Faza 1 + 2 + 3)

---

## Obecny stan

Interfejs mobilny `/m/` działa jako PWA (chat-centric) z podstronami: notatki, paragony, wiedza.
Funkcje: czat z AI, zdjęcia paragonów, nagrywanie głosu, offline queue, push notifications.

### Pliki mobilne
- `app/templates/mobile/base.html` - layout PWA (header, quick actions, bottom nav, settings sheet)
- `app/templates/mobile/chat.html` - główny widok czatu
- `app/templates/mobile/notes.html` - lista notatek
- `app/templates/mobile/receipts.html` - lista paragonów
- `app/templates/mobile/knowledge.html` - zakładki + RAG
- `app/templates/mobile/receipt_detail.html` - szczegóły paragonu
- `app/templates/mobile/note_detail.html` - szczegóły notatki
- `app/templates/mobile/partials/` - 4 partialne (receipt_list, note_list, bookmark_list, rag_results)
- `app/static/css/mobile.css` - 1060 linii, dark-only, touch-optimized
- `app/static/js/mobile.js` - MobileApp class + PushManager (811 linii)
- `app/static/js/offline-queue.js` - IndexedDB offline queue
- `app/mobile_routes.py` - FastAPI router `/m/`
- `app/static/manifest.json` - PWA manifest (standalone, share target)

---

## Faza 1 - Bezpieczeństwo (KRYTYCZNE)

### 1.1 XSS w szablonie czatu
- [x] **CRITICAL** - `app/templates/mobile/chat.html:10`: `{{ msg.content | safe }}` renderowało treść jako surowy HTML
- **Fix:** Zamieniono na `{{ msg.content | e }}` z atrybutem `data-raw` + renderowanie markdown po stronie klienta z DOMPurify
- **Done:** 2026-02-06 — wzorzec identyczny z desktop (`chat/partials/message.html`)

### 1.2 XSS w renderMarkdown()
- [x] **HIGH** - `app/static/js/mobile.js`: regex markdown → `innerHTML` bez sanityzacji
- **Fix:** Zamieniono na `marked.parse()` + `DOMPurify.sanitize()` z whitelistą tagów/atrybutów. Fallback (brak lib) escapuje HTML przed regex.
- **Done:** 2026-02-06 — dodano `renderAllMarkdown()` dla server-rendered messages

### 1.3 Self-host HTMX (usunięcie CDN dependency)
- [x] **MEDIUM** - Usunięto `unpkg.com` z mobile/base.html i desktop/base.html
- **Fix:** Pobrano htmx.min.js (v2.0.4), marked.min.js, purify.min.js do `/static/js/`. Desktop chat/index.html też zaktualizowany.
- **Done:** 2026-02-06 — desktop base.html i chat/index.html również zmienione na lokalne pliki

### 1.4 Session ID w localStorage
- [x] **MEDIUM** - `localStorage` → `sessionStorage` w mobile.js
- **Fix:** Session ID czytany z `data-session-id` atrybutu (server-rendered) + `sessionStorage` jako fallback. Ginie po zamknięciu karty.
- **Done:** 2026-02-06 — dotyczy constructor, sendMessage, setupSettings (reset)

### 1.5 Share target bez walidacji MIME
- [x] **MEDIUM** - `app/mobile_routes.py`: dodano `ALLOWED_SHARE_IMAGE_TYPES` whitelist
- **Fix:** Walidacja `image.content_type` przeciwko `{"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}`. Odrzucone typy logowane z WARNING.
- **Done:** 2026-02-06

### 1.6 CSP: usunięcie inline scripts
- [x] **LOW** - Usunięto inline `<script>` z chat.html
- **Fix:** Session ID przekazywany przez `<div id="chat-config" data-session-id="..." hidden>` zamiast `window.initialSessionId`. Mobile.js czyta z `dataset`.
- **Done:** 2026-02-06

---

## Faza 2 - Core UX

### 2.1 Streaming responses (SSE)
- [x] Nowy endpoint `POST /chat/stream` z `StreamingResponse` (SSE)
- [x] `ollama_client.post_chat_stream()` - async generator yielding tokens
- [x] `orchestrator.process_message_stream()` - yields status/token/done events
- [x] Klient JS: `fetch` + `ReadableStream` → token-by-token append do message bubble
- [x] Fallback do obecnego POST jeśli SSE niedostępne
- **Done:** 2026-02-06 — SSE protocol: session → status → token* → done

### 2.2 Cancel button
- [x] Podczas przetwarzania: przycisk Send → Stop (zmiana ikony ➤ → ⏹, kolor → czerwony)
- [x] `AbortController` na fetch z sygnałem abort
- [x] Metody `setSendButtonState('send'|'stop')` i `cancelRequest()`
- **Done:** 2026-02-06 — kliknięcie Stop anuluje request, wyświetla "Anulowano"

### 2.3 Historia sesji na mobile
- [x] Ikona 📋 w headerze → drawer z listą sesji (slide from left)
- [x] Lista: tytuł sesji + data + liczba wiadomości
- [x] Przycisk 🗑️ Usuń na sesji
- [x] "Nowa rozmowa" na górze drawera
- [x] Kliknięcie sesji → `/m/?session_id=...`
- **Done:** 2026-02-06 — korzysta z istniejącego `GET /chat/sessions` i `DELETE /chat/sessions/{id}`

### 2.4 Smart input - auto-detekcja URL
- [x] Wykrywanie wklejonego URL w textarea (regex na input + paste)
- [x] Pokazanie inline action bar nad inputem:
  ```
  🔗 domain.com  [📖 Streść] [🔖 Zakładka]
  ```
- [x] Kliknięcie akcji → prefill wiadomości i auto-wyślij do agenta
- **Done:** 2026-02-06 — URL bar pojawia się/znika dynamicznie

### 2.5 File preview przed upload
- [x] Po wybraniu zdjęcia: preview overlay z miniaturką i rozmiarem pliku
- [x] Przyciski: [🧾 Wyślij jako paragon] [Anuluj]
- [x] Progress bar podczas uploadu (XMLHttpRequest.upload.onprogress)
- **Done:** 2026-02-06 — overlay z podglądem, XHR z progress bar

### 2.6 Ulepszone kopiowanie/udostępnianie
- [x] Przycisk 📋 (kopiuj) na każdej wiadomości asystenta
- [x] Przycisk 📤 (udostępnij) na mobile z Web Share API (gdy dostępne)
- [x] Działanie zarówno na server-rendered jak i dynamicznie dodanych wiadomościach
- **Done:** 2026-02-06 — `addMessageActions()` + touch-device opacity fallback

### 2.7 Bottom nav zawsze widoczny
- [x] Bottom nav domyślnie widoczny na wszystkich stronach (w tym czat)
- [x] Quick actions bar nad bottom-nav (nie zamiast)
- [x] Opcja w settings: "Ukryj nawigację dolną" (odwrócona logika - domyślnie widoczna)
- **Done:** 2026-02-06 — localStorage key: `nav_hidden`

---

## Faza 3 - Polish

### 3.1 Inline action cards
- [x] Po akcji agenta (create_note, create_bookmark) → structured card z linkami
- [x] Paragon processed → mini receipt card z linkiem do szczegółów
- [x] CSS klasa `.action-card` w mobile.css (warianty: .note, .bookmark, .receipt)
- [x] JS: `renderActionCard()` + `addActionCardMessage()` + SSE `tool_result` event
- [x] Agent integration w `/chat/stream` i `/chat/message` (wcześniej tylko Telegram)
- [x] `AgentExecutionResult.tool_metadata` - structured data for UI cards
- [x] `ProcessingResult.receipt_id` - ID paragonu w odpowiedzi API
- [x] Shared `looks_like_action()` w agent_executor (used by web API + Telegram)
- **Done:** 2026-02-06

### 3.2 Voice recording UX
- [x] Timer nagrywania (0:00, 0:05...) widoczny w pasku input (zamienia textarea)
- [x] Waveform visualizer (Canvas API z AudioContext.analyser, frequency bars)
- [x] Haptic feedback na start/stop (navigator.vibrate)
- [x] Push-to-talk: long press (400ms) na 🎤 = nagrywaj, puść = wyślij
- [x] Animacja pulsującego kółka wokół przycisku (CSS `voice-pulse`)
- [x] Przycisk "Anuluj" w recording overlay
- **Done:** 2026-02-06

### 3.3 Kontekstowe sugestie
- [x] Zamiast statycznych 4 chipów → dynamiczne na podstawie:
  - Pora dnia: rano "Plan na dziś", wieczorem "Podsumuj dzień"
  - Ostatnia akcja: po paragonie "Ile wydałem w tym tygodniu?"
  - Nowe treści: "Mam N nieprzeczytanych zakładek"
- [x] Endpoint `GET /chat/suggestions` zwracający kontekstowe sugestie
- [x] Cache suggestions w sessionStorage (odśwież co 30 min)
- [x] `loadDynamicSuggestions()` + `_renderSuggestions()` w mobile.js
- **Done:** 2026-02-06

### 3.4 Skeleton loading
- [x] Skeleton placeholder podczas ładowania sesji (szare boxy animowane)
- [x] CSS: `.skeleton` class z shimmer animation (`.skeleton-message`, `.skeleton-line`, `.skeleton-card`)
- [x] JS: `showSkeleton(container, type, count)` + `hideSkeleton()` helpers
- [x] Applied to history drawer session loading
- **Done:** 2026-02-06

### 3.5 Swipe gestures
- [x] Swipe right z lewej krawędzi (< 25px) → open history drawer
- [x] Swipe left na session items w drawer → reveal delete button (80px)
- [x] Animated item removal after delete (max-height + opacity transition)
- [x] Pull-to-refresh na wszystkich stronach (custom indicator, `overscroll-behavior-y: contain`)
- [x] Custom touch handling (zero dependencies, no Hammer.js)
- [x] CSS: `.swipe-item`, `.swipe-item-content`, `.swipe-item-actions`, `.ptr-indicator`
- [x] JS: `setupSwipeGestures()`, `_setupEdgeSwipe()`, `_setupPullToRefresh()`, `initSwipeToReveal()`
- **Done:** 2026-02-06

### 3.6 Biometric/PIN lock
- [x] WebAuthn API (Face ID / Touch ID / Fingerprint) - `navigator.credentials.create/get` z platform authenticator
- [x] 4-cyfrowy PIN z SHA-256 hashowaniem (Web Crypto API + salt)
- [x] Auto-lock po 5 min w tle (`visibilitychange` API + activity tracking)
- [x] Lockout po 5 błędnych próbach (30s cooldown)
- [x] Toggle w Settings + opcje: zmień PIN, włącz biometrię
- [x] Lock screen overlay (z-index: 999) z animowanym PIN pad
- [x] LockScreen class (~230 linii) z setup/confirm/change/unlock modes
- [x] Haptic feedback na klawiszach, shake animation na błędny PIN
- **Done:** 2026-02-06

### 3.7 Dark/Light mode na mobile
- [x] 3-way picker w Settings: 🔄 Auto / 🌙 Dark / ☀️ Light
- [x] CSS `[data-theme="light"]` overrides all CSS variables (bg, text, bubbles)
- [x] `@media (prefers-color-scheme: light)` for `[data-theme="auto"]`
- [x] Persist w localStorage (`theme_pref`), apply before paint via inline script
- [x] Dynamic `<meta name="theme-color">` update for browser chrome
- [x] Light mode adjustments for code blocks, skeleton shimmer
- **Done:** 2026-02-06

### 3.8 Quick actions rozszerzenie
- [x] Przycisk 📎 (załącznik) dodany: `[📷] [🎤] [📎] [Napisz...] [➤]`
- [x] 📎 → bottom sheet z 4 opcjami: Aparat, Galeria, PDF, Link
- [x] Long press na 📷 (400ms) → context menu: Aparat / Galeria
- [x] Long press na 🎤 → Push-to-talk (already done in 3.2)
- [x] `_showContextMenu(anchor, items)` - reusable context menu component
- [x] `openGallery()`, `openFilePicker(accept)` - dedicated file pickers
- [x] CSS: `.attach-options`, `.context-menu` z `scaleIn` animation
- **Done:** 2026-02-06

### 3.9 Uproszczenie nawigacji
- [x] Redukcja z 5 tabów do 3: 💬 Czat | 📋 Historia | ⋯ Więcej
- [x] 📋 Historia → otwiera drawer z sesjami (ten sam co header button)
- [x] ⋯ Więcej → bottom sheet z gridem: Notatki, Paragony, Wiedza, Desktop
- [x] Podstrony zachowane jako deep links (`/m/notatki`, `/m/paragony`, `/m/wiedza`)
- [x] Inline action cards (3.1) zapewniają bezpośredni dostęp z czatu
- [x] CSS: `.more-grid`, `.more-item` z ikonami i highlight dla aktywnej strony
- **Done:** 2026-02-06

### 3.10 Offline improvements
- [x] Auto-retry z exponential backoff (5s, 15s, 30s, 60s, 120s) + auto-retry timer
- [x] Ikona ⏳ przy niesynchronizowanych wiadomościach (`pending` class + `message-pending-badge`)
- [x] Pending badge → "Wysłano" po `offlinequeue:itemsynced`, auto-usunięcie po 3s
- [x] Message cache w localStorage (max 50 wiadomości, auto-save on send/receive)
- [x] `_cacheCurrentMessages()` - cache server-rendered messages na load
- [x] `_restoreCachedMessages()` - restore from cache when offline + no server messages
- [x] CSS: `.message.pending`, `.message-pending-badge`, `.message.cached`, `@keyframes pendingPulse`
- [x] `queueOfflineAction()` returns queue item ID (for pending badge tracking)
- **Done:** 2026-02-06

---

## Log postępów

| Data | Faza | Zadanie | Status | Notatki |
|------|------|---------|--------|---------|
| 2026-02-06 | - | Analiza UI/UX | ✅ Done | Pełna analiza 62 szablonów, CSS, JS, routing, security |
| 2026-02-06 | 1.1 | XSS chat.html `\|safe` → `\|e` + data-raw | ✅ Done | + rel="noopener noreferrer" na linkach źródeł |
| 2026-02-06 | 1.2 | renderMarkdown() → marked + DOMPurify | ✅ Done | + renderAllMarkdown() + HTML escape fallback |
| 2026-02-06 | 1.3 | Self-host HTMX, marked, DOMPurify | ✅ Done | mobile + desktop base.html + chat/index.html |
| 2026-02-06 | 1.4 | Session ID: localStorage → sessionStorage | ✅ Done | + data attribute zamiast window.initialSessionId |
| 2026-02-06 | 1.5 | Share target MIME validation | ✅ Done | ALLOWED_SHARE_IMAGE_TYPES whitelist |
| 2026-02-06 | 1.6 | Usunięcie inline script (CSP) | ✅ Done | div#chat-config z data-session-id |
| 2026-02-06 | 2.7 | Bottom nav zawsze widoczny | ✅ Done | Odwrócona logika toggle: `nav_hidden` |
| 2026-02-06 | 2.6 | Kopiowanie/udostępnianie wiadomości | ✅ Done | 📋 copy + 📤 Web Share API na touch |
| 2026-02-06 | 2.5 | File preview przed upload | ✅ Done | Overlay z miniaturką + XHR progress |
| 2026-02-06 | 2.2 | Cancel button | ✅ Done | Send→Stop + AbortController |
| 2026-02-06 | 2.1 | Streaming SSE | ✅ Done | POST /chat/stream + ollama streaming |
| 2026-02-06 | 2.3 | Historia sesji drawer | ✅ Done | Slide-from-left, /chat/sessions API |
| 2026-02-06 | 2.4 | Smart input URL detection | ✅ Done | Regex + action bar + auto-prefill |
| 2026-02-06 | 3.1 | Inline action cards | ✅ Done | .action-card CSS + renderActionCard() JS + tool_result SSE + agent w web API |
| 2026-02-06 | 3.2 | Voice recording UX | ✅ Done | Timer + waveform + haptic + push-to-talk + pulsing circle + cancel |
| 2026-02-06 | 3.3 | Kontekstowe sugestie | ✅ Done | GET /chat/suggestions + sessionStorage cache 30min + dynamic chips |
| 2026-02-06 | 3.4 | Skeleton loading | ✅ Done | .skeleton shimmer + showSkeleton/hideSkeleton JS + history drawer |
| 2026-02-06 | 3.5 | Swipe gestures | ✅ Done | Edge swipe→drawer + swipe-to-delete + pull-to-refresh + zero deps |
| 2026-02-06 | 3.6 | Biometric/PIN lock | ✅ Done | LockScreen class + WebAuthn + SHA-256 PIN + auto-lock 5min + settings UI |
| 2026-02-06 | 3.7 | Dark/Light mode | ✅ Done | 3-way picker (auto/dark/light) + CSS vars + prefers-color-scheme + localStorage |
| 2026-02-06 | 3.8 | Quick actions rozszerzenie | ✅ Done | 📎 attach sheet + long press camera context menu + openGallery/openFilePicker |
| 2026-02-06 | 3.9 | Uproszczenie nawigacji | ✅ Done | 5→3 taby + "Więcej" sheet + nav-history binds drawer |
| 2026-02-06 | 3.10 | Offline improvements | ✅ Done | Exponential backoff + pending badges + message cache localStorage |
