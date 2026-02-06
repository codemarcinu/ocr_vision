# Plan napraw bezpieczeństwa - Second Brain

**Data audytu:** 2026-02-06
**Status:** Zrealizowano wszystkie 11 kroków (2026-02-06)

---

## Krok 1: Path Traversal w upload transkrypcji [KRYTYCZNY]

**Plik:** `app/transcription_api.py:181`

**Problem:** `file.filename` jest użyte bezpośrednio bez sanityzacji. Atakujący może wysłać plik o nazwie `../../../etc/cron.d/evil` i zapisać go poza docelowym katalogiem.

**Obecny kod (linia 181):**
```python
temp_path = settings.TRANSCRIPTION_TEMP_DIR / file.filename
```

**Naprawa:** Dodać sanityzację identyczną jak w `app/main.py:330-331`:
```python
from pathlib import PurePosixPath

safe_filename = PurePosixPath(file.filename).name if file.filename else ""
if not safe_filename:
    raise HTTPException(status_code=400, detail="Invalid filename")
temp_path = settings.TRANSCRIPTION_TEMP_DIR / safe_filename
```

**Import do dodania:** `from pathlib import PurePosixPath` (Path już importowany, ale PurePosixPath nie)

---

## Krok 2: Brak walidacji SSRF w bookmarks [KRYTYCZNY]

**Plik:** `app/bookmarks_api.py:58-68`

**Problem:** URL bookmarki nie jest walidowany przed scrapingiem. Atakujący może podać URL `http://169.254.169.254/latest/meta-data/` (AWS metadata) lub `http://192.168.1.1/admin`.

**Obecny kod:**
```python
@router.post("/")
async def create_bookmark(bookmark: BookmarkCreate, repo: BookmarkRepoDep):
    existing = await repo.get_by_url(bookmark.url)
    ...
```

**Naprawa:** Dodać walidację URL przed jakimkolwiek przetwarzaniem:
```python
from app.url_validator import validate_url

@router.post("/")
async def create_bookmark(bookmark: BookmarkCreate, repo: BookmarkRepoDep):
    try:
        validate_url(bookmark.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Nieprawidłowy URL: {e}")

    existing = await repo.get_by_url(bookmark.url)
    ...
```

**Import do dodania:** `from app.url_validator import validate_url`

---

## Krok 3: Brak walidacji SSRF w transcription downloader [KRYTYCZNY]

**Plik:** `app/transcription/downloader.py:49-60`

**Problem:** URL transkrypcji trafia bezpośrednio do yt-dlp bez walidacji. Można skanować sieć wewnętrzną.

**Obecny kod:**
```python
async def download(self, url: str) -> DownloadResult:
    import yt_dlp
    logger.info(f"Downloading from: {url}")
    self.progress_callback(0, "analyzing")
    info = await self._extract_info(url)
```

**Naprawa:** Dodać walidację na początku metody:
```python
async def download(self, url: str) -> DownloadResult:
    from app.url_validator import validate_url
    try:
        validate_url(url)
    except ValueError as e:
        raise ValueError(f"Nieprawidłowy URL: {e}")

    import yt_dlp
    logger.info(f"Downloading from: {url}")
    ...
```

---

## Krok 4: SQL Injection via `.replace()` [WYSOKI]

**Plik:** `app/db/repositories/receipts.py:336-346`

**Problem:** Użycie `.replace(":months", str(months))` zamiast parametryzacji SQL. Choć `months` to int, wzorzec jest niebezpieczny.

**Obecny kod:**
```python
stmt = text("""
    SELECT
        DATE_TRUNC('month', receipt_date) as month,
        COUNT(*) as receipt_count,
        COALESCE(SUM(total_final), 0) as total_spent
    FROM receipts
    WHERE receipt_date >= NOW() - INTERVAL ':months months'
    GROUP BY DATE_TRUNC('month', receipt_date)
    ORDER BY month DESC
""".replace(":months", str(months)))
result = await self.session.execute(stmt)
```

**Naprawa:** Użyć `make_interval()` z parametryzacją:
```python
stmt = text("""
    SELECT
        DATE_TRUNC('month', receipt_date) as month,
        COUNT(*) as receipt_count,
        COALESCE(SUM(total_final), 0) as total_spent
    FROM receipts
    WHERE receipt_date >= NOW() - make_interval(months => :months)
    GROUP BY DATE_TRUNC('month', receipt_date)
    ORDER BY month DESC
""")
result = await self.session.execute(stmt, {"months": months})
```

**Uwaga:** PostgreSQL `make_interval(months => N)` akceptuje parametr bindowany, w przeciwieństwie do `INTERVAL ':N months'`.

---

## Krok 5: Sesje bez wygaśnięcia [WYSOKI]

**Plik:** `app/auth.py:15-16, 89-93`

**Problem:** `_active_sessions` to `set[str]` bez timestampów. Sesje nigdy nie wygasają po stronie serwera. Cookie ustawione na 30 dni.

**Naprawa - zmiana struktury sesji:**

```python
# Linia 1-6: dodać import
from datetime import datetime, timedelta

# Linia 16: zmienić typ
SESSION_MAX_AGE = 8 * 3600  # 8 godzin
_active_sessions: dict[str, datetime] = {}  # token -> czas utworzenia

# Linia 89-93: create_session z timestampem
def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _active_sessions[token] = datetime.utcnow()
    return token

# Linia 96-98: destroy_session
def destroy_session(token: str) -> None:
    _active_sessions.pop(token, None)

# Linia 43-44: weryfikacja z TTL
def _is_session_valid(token: str) -> bool:
    if token not in _active_sessions:
        return False
    created = _active_sessions[token]
    if (datetime.utcnow() - created).total_seconds() > SESSION_MAX_AGE:
        _active_sessions.pop(token, None)
        return False
    return True

# Użyć _is_session_valid() zamiast `token in _active_sessions` w:
# - verify_web_session() (linia 44)
# - web_auth_middleware() (linia 82)
```

**Naprawa - zmniejszyć max_age cookie:**

Plik `app/main.py:117`:
```python
# Zmienić z:
max_age=86400 * 30,  # 30 days
# Na:
max_age=8 * 3600,  # 8 godzin (zsynchronizowane z SESSION_MAX_AGE)
```

---

## Krok 6: Endpointy push bez autentykacji [WYSOKI]

**Plik:** `app/push_api.py`

**Problem:** `/api/push/test` i `/api/push/status` nie wymagają autentykacji. Test wysyła push do WSZYSTKICH subskrybentów.

**Naprawa - dodać auth do wrażliwych endpointów:**

```python
# Dodać import:
from app.auth import verify_api_token, verify_web_session
from fastapi import Depends

# /test (linia 101-104) - wymagać autentykacji:
@router.post("/test", dependencies=[Depends(verify_web_session)])
async def send_test_notification(
    data: TestNotificationRequest,
    session: DbSession,
):

# /status (linia 147-148) - wymagać autentykacji:
@router.get("/status", dependencies=[Depends(verify_web_session)])
async def get_push_status(session: DbSession):
```

**Uwaga:** Używamy `verify_web_session` bo push API jest wywoływane z PWA (cookies), nie z zewnętrznego API (Bearer token). Middleware `web_auth_middleware` już chroni `/api/push/` paths (linia 68 auth.py), ale explicit Depends jest bezpieczniejsze.

---

## Krok 7: XSS przez `|safe` w szablonie [ŚREDNI]

**Plik:** `app/templates/analytics/partials/trends_chart.html:8`

**Problem:** `{{ trends_json|safe }}` wyłącza escaping Jinja2. Dane pochodzą z `json.dumps(trends, default=str)` w `web_routes.py:486`, ale jeśli nazwy produktów zawierają `</script><script>alert(1)`, zostanie to wstrzyknięte.

**Obecny kod:**
```html
var data = {{ trends_json|safe }};
```

**Naprawa:** Zastąpić `|safe` filtrem `|tojson`:
```html
var data = {{ trends_json|tojson }};
```

`|tojson` jest wbudowanym filtrem Jinja2, który poprawnie escapuje dane do kontekstu JavaScript (escapuje `</script>`, `&`, `<`, `>` itp.).

**Alternatywa:** Jeśli `trends_json` jest już stringiem JSON (z `json.dumps`), można zmienić na przekazywanie surowej listy i użycie `{{ trends|tojson }}` w szablonie (usuwając `json.dumps` z `web_routes.py:486`).

---

## Krok 8: Wyciek informacji w callback_router [ŚREDNI]

**Plik:** `app/telegram/callback_router.py:61`

**Problem:** Pełny komunikat wyjątku jest wyświetlany użytkownikowi. Może zawierać ścieżki plików, nazwy modeli, connection stringi.

**Obecny kod:**
```python
await query.edit_message_text(f"Wystąpił błąd: {e}")
```

**Naprawa:**
```python
await query.edit_message_text("Wystąpił błąd. Spróbuj ponownie później.")
```

Szczegóły błędu już są logowane w linii 59: `logger.error(...)`.

---

## Krok 9: Rate limiting na wrażliwych endpointach [ŚREDNI]

**Plik:** `app/main.py`

**Problem:** Tylko `/process-receipt` ma rate limit. Brak na `/login`, chat, search.

**Naprawa - dodać limity w istniejących routerach:**

```python
# app/main.py - endpoint /login (linia 103):
@app.post("/login")
@limiter.limit("5/minute")
async def login_submit(request: Request, token: str = Form(...)):

# app/chat_api.py - endpoint /message:
@router.post("/message")
@limiter.limit("20/minute")
async def send_message(...):

# app/push_api.py - endpoint /test (linia 101):
@router.post("/test")
@limiter.limit("3/minute")
async def send_test_notification(...):
```

**Uwaga:** `limiter` z `app/main.py` musi być importowalny lub użyty przez middleware. Sprawdzić czy `slowapi` obsługuje limitowanie na sub-routerach.

---

## Krok 10: Brak nagłówka Content-Security-Policy [ŚREDNI]

**Plik:** `app/main.py:79-87` (middleware `security_headers`)

**Problem:** Brakuje CSP, który ograniczyłby ładowanie skryptów z zewnętrznych domen.

**Naprawa - dodać CSP:**
```python
response.headers["Content-Security-Policy"] = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
    "img-src 'self' data: https:; "
    "font-src 'self' cdn.jsdelivr.net; "
    "connect-src 'self'"
)
```

**Uwaga:** `'unsafe-inline'` jest wymagane bo szablony używają inline `<script>` i `<style>`. Docelowo warto przenieść skrypty do zewnętrznych plików i użyć nonce.

---

## Krok 11: `/metrics` publicznie dostępny [ŚREDNI]

**Plik:** `app/auth.py:60`

**Problem:** `/metrics` jest na liście public_paths. Ujawnia informacje o aplikacji.

**Naprawa - usunąć z public_paths:**
```python
public_paths = (
    "/health", "/login", "/logout", "/static",
    "/sw.js", "/offline.html", "/manifest.json",
    "/api/push/vapid-key"
)
# Usunięto "/metrics" - wymaga teraz autentykacji
```

---

## Podsumowanie kolejności

| Krok | Priorytet | Plik | Opis | Status |
|------|-----------|------|------|--------|
| 1 | KRYTYCZNY | `transcription_api.py` | Path traversal - sanityzacja nazwy pliku | DONE |
| 2 | KRYTYCZNY | `bookmarks_api.py` | SSRF - walidacja URL bookmarków | DONE |
| 3 | KRYTYCZNY | `downloader.py` | SSRF - walidacja URL transkrypcji | DONE |
| 4 | WYSOKI | `receipts.py` | SQL injection - parametryzacja | DONE |
| 5 | WYSOKI | `auth.py` + `main.py` | Sesje z TTL (8h) | DONE |
| 6 | WYSOKI | `push_api.py` | Auth na push endpointach | DONE |
| 7 | ŚREDNI | `trends_chart.html` | XSS - `\|tojson` zamiast `\|safe` | DONE |
| 8 | ŚREDNI | `callback_router.py` | Wyciek info w błędach | DONE |
| 9 | ŚREDNI | `main.py` + routery | Rate limiting (login, chat, push) | DONE |
| 10 | ŚREDNI | `main.py` | CSP header | DONE |
| 11 | ŚREDNI | `auth.py` | `/metrics` za auth | DONE |
