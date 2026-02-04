# Project Audit Report

**Project:** Second Brain (ocr_vision)
**Date:** 2026-02-04
**Stack detected:** Python 3.11, FastAPI 0.109, SQLAlchemy 2.0 (async), PostgreSQL 16 + pgvector, Jinja2 + HTMX (web UI), python-telegram-bot 21.0, Ollama LLMs, Docker (NVIDIA CUDA), Bootstrap 5, Chart.js

---

## Executive Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Security | 1 | 3 | 5 | 3 | 12 |
| UX/UI | 0 | 1 | 4 | 3 | 8 |
| **Total** | **1** | **4** | **9** | **6** | **20** |

**Top priorities for immediate action:**
1. **SEC-001**: No authentication on FastAPI/Web UI - all endpoints publicly accessible
2. **SEC-002**: SQL injection via f-string in embeddings repository
3. **SEC-003**: Path traversal in file upload endpoints

---

## Security Issues

### Critical

#### SEC-001: No Authentication on FastAPI API and Web UI
**Location:** `app/main.py`, `app/web_routes.py`, all `app/*_api.py` routers
**Description:** The entire FastAPI application - REST API endpoints, Web UI routes, and admin operations (delete, obsidian sync, analytics) - has zero authentication or authorization. Any network-reachable client can read, create, modify, and delete all data including receipts, notes, bookmarks, chat sessions, and dictionary entries.

The Telegram bot properly uses `@authorized_only` middleware (`app/telegram/middleware.py:18`), but the HTTP API has no equivalent protection.

**Impact:** Anyone with network access to port 8000 can:
- Read all personal financial data (receipts, spending analytics)
- Delete receipts, notes, bookmarks
- Upload arbitrary files via `/process-receipt` and `/app/paragony/upload`
- Access chat AI, search all personal content
- Trigger Obsidian sync, reindex RAG, and other admin operations
- Access Prometheus metrics at `/metrics` (information disclosure)

**Evidence:**
```python
# app/web_routes.py - NO auth check
@router.post("/app/paragony/upload", response_class=HTMLResponse)
async def receipt_upload(request: Request, file: UploadFile = File(...)):
    ...  # Anyone can upload

# app/chat_api.py - NO auth check
@router.post("/message", response_model=ChatMessageResponse)
async def send_message(request: ChatMessageRequest, ...):
    ...  # Anyone can use chat AI

# Compare with Telegram - HAS auth
@authorized_only
async def _start_command(self, update, context):
    ...
```

**Recommendation:** Add authentication middleware. Minimum viable approach for a single-user personal app:
- Add a shared API token via `AUTH_TOKEN` env var
- Create a FastAPI dependency that checks `Authorization: Bearer <token>` header
- For the Web UI, use cookie-based session auth with a login page
- Apply the dependency to all routers via `app.include_router(router, dependencies=[Depends(verify_auth)])`

**Mitigating factor:** Docker Compose binds ports to `127.0.0.1` only (`docker-compose.yml:22,98`), limiting exposure to localhost. Still exploitable by any local process or browser-based attacks (CSRF).

---

### High

#### SEC-002: SQL Injection via f-string in Embeddings Repository
**Location:** `app/db/repositories/embeddings.py:35-37`, `app/db/repositories/embeddings.py:82-84`
**Description:** The `content_types` parameter is interpolated directly into SQL using f-strings, bypassing SQLAlchemy's parameterized queries.

**Impact:** If an attacker can control the `content_types` list (e.g., via RAG search API or a future endpoint), they can inject arbitrary SQL.

**Evidence:**
```python
# app/db/repositories/embeddings.py:35-37
if content_types:
    types_str = ",".join(f"'{t}'" for t in content_types)
    where_clause = f"WHERE content_type IN ({types_str})"  # SQL INJECTION

query = text(f"""
    SELECT ... FROM document_embeddings
    {where_clause}
    ORDER BY embedding <=> :query_embedding
    LIMIT :limit
""")
```

Same pattern at line 82-84 for `search_by_keyword`.

**Recommendation:** Use parameterized queries with `ANY(:types)`:
```python
if content_types:
    where_clause = "WHERE content_type = ANY(:types)"
    params["types"] = content_types
```

---

#### SEC-003: Path Traversal in File Upload Endpoints
**Location:** `app/main.py:204`, `app/web_routes.py:172`
**Description:** Uploaded filenames are used directly to construct filesystem paths without sanitization. An attacker can craft a filename like `../../etc/cron.d/malicious` to write files outside the intended directory.

**Impact:** Arbitrary file write within the container filesystem.

**Evidence:**
```python
# app/main.py:204
inbox_path = settings.INBOX_DIR / file.filename  # file.filename is user-controlled
with open(inbox_path, "wb") as f:
    content = await file.read()
    f.write(content)
```

**Recommendation:** Sanitize filenames to strip path components:
```python
from pathlib import PurePosixPath
safe_name = PurePosixPath(file.filename).name
if not safe_name or safe_name.startswith('.'):
    raise HTTPException(status_code=400, detail="Invalid filename")
inbox_path = settings.INBOX_DIR / safe_name
```

---

#### SEC-004: Unsafe SQL `.replace()` Pattern in Analytics
**Location:** `app/db/repositories/analytics.py:31-33`
**Description:** Uses string `.replace()` to inject a parameter into a SQL template, which defeats parameterized query protection.

**Impact:** The `months` parameter comes from the API endpoint `GET /analytics/price-trends/{product_id}?months=6` (`app/main.py:660`). While FastAPI casts it to `int`, this pattern is fragile and error-prone. If copy-pasted to another context with string input, it becomes a direct SQL injection.

**Evidence:**
```python
# app/db/repositories/analytics.py:31-33
stmt = text("""
    ...
    AND ph.recorded_date > CURRENT_DATE - INTERVAL ':months months'
""".replace(":months", str(months)))
```

**Recommendation:** Use PostgreSQL's `INTERVAL` with proper parameterization:
```python
stmt = text("""
    AND ph.recorded_date > CURRENT_DATE - :months * INTERVAL '1 month'
""")
result = await self.session.execute(stmt, {"product_id": product_id, "months": months})
```

---

### Medium

#### SEC-005: SSRF via Web Scraper and RSS Fetcher
**Location:** `app/web_scraper.py:42-43`, `app/rss_fetcher.py:45-50`, `app/chat/content_fetcher.py:39`
**Description:** User-supplied URLs (from Telegram `/summarize`, web UI "Summarize URL", RSS feed subscriptions, and chat web search results) are fetched without validating that they don't point to internal services.

**Impact:** An attacker could:
- Probe internal Docker network services (postgres:5432, searxng:8080)
- Access cloud metadata endpoints (169.254.169.254)
- Scan the internal network

**Evidence:**
```python
# app/web_scraper.py:42-43
async with httpx.AsyncClient(timeout=30.0) as client:
    response = await client.get(url, ...)  # No URL validation
```

**Recommendation:** Add URL validation that blocks private IP ranges, localhost, and non-HTTP schemes.

---

#### SEC-006: Default/Weak Database and Grafana Credentials
**Location:** `app/config.py:13-14`, `docker-compose.yml:7,50,150`
**Description:** Default database password is `pantry123`, hardcoded in the config fallback and Docker Compose. Grafana admin password is also hardcoded as `pantry123`.

**Evidence:**
```python
# app/config.py:13-14
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://pantry:pantry123@localhost:5432/pantry"
)
```
```yaml
# docker-compose.yml:150
- GF_SECURITY_ADMIN_PASSWORD=pantry123
```

**Recommendation:** Remove default credentials from code. Use `${POSTGRES_PASSWORD}` without fallback, or fail-fast if not set.

---

#### SEC-007: Missing Security Headers
**Location:** `app/main.py`
**Description:** No security headers configured. The application does not set `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, or `Strict-Transport-Security`.

**Impact:** Increases risk of clickjacking, MIME-type confusion, and other browser-based attacks.

**Recommendation:** Add security headers middleware:
```python
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response
```

---

#### SEC-008: Missing Rate Limiting
**Location:** All API endpoints
**Description:** No rate limiting on any endpoint. Resource-intensive operations (OCR processing, LLM chat, web scraping) can be triggered without limits.

**Impact:** DoS via concurrent OCR requests (GPU exhaustion), LLM abuse, or excessive external API calls (OpenWeatherMap, SearXNG).

**Recommendation:** Add `slowapi` or similar rate limiter, especially on `/process-receipt`, `/chat/message`, and upload endpoints.

---

#### SEC-009: Weak Telegram Authorization Default
**Location:** `app/telegram/middleware.py:41-43`
**Description:** When `TELEGRAM_CHAT_ID=0` (the default), the bot allows access from any Telegram user.

**Evidence:**
```python
if settings.TELEGRAM_CHAT_ID == 0:
    logger.warning("TELEGRAM_CHAT_ID not configured, allowing all users")
    return await func(*args, **kwargs)  # Allows ALL users
```

**Recommendation:** Default to deny-all when `TELEGRAM_CHAT_ID` is not configured.

---

### Low

#### SEC-010: Information Disclosure in Error Responses
**Location:** `app/main.py:211`, `app/web_routes.py:596-597`, multiple files
**Description:** Exception details are returned to clients in HTTP responses.

**Evidence:**
```python
# app/main.py:211
raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
# app/web_routes.py:597
"error": str(e),  # Full exception string sent to client
```

**Recommendation:** Log full errors server-side, return generic messages to clients.

---

#### SEC-011: Missing CSRF Protection on Web UI Forms
**Location:** `app/web_routes.py` (all POST handlers), `app/templates/**/*.html`
**Description:** HTMX forms submit without CSRF tokens. Since no auth exists (SEC-001), this is lower priority, but should be addressed when auth is added.

**Recommendation:** Implement CSRF tokens when adding authentication.

---

#### SEC-012: XSS Risk in `data_json|safe` Template Filter
**Location:** `app/templates/analytics/index.html:125`
**Description:** The `|safe` filter disables Jinja2 autoescaping for JSON data injected into a `<script>` tag.

**Evidence:**
```html
<script>
var data = {{ data_json|safe }};  <!-- Bypasses autoescaping -->
</script>
```

**Impact:** Low - the data comes from analytics repository (numeric aggregations), not user-provided text. However, if store names or categories ever contain `</script>` sequences, XSS is possible.

**Recommendation:** Use `json.dumps()` with HTML-safe encoding or a dedicated `tojson` filter.

---

## UX/UI Issues

### High

#### UX-001: Inconsistent Polish Text - Missing Diacritics
**Location:** Multiple templates and UI strings throughout the codebase
**Description:** The web UI inconsistently uses Polish characters. Labels, toast messages, and headings mix accented and unaccented Polish (e.g., "Wydatki (miesiac)" instead of "miesiąc", "Spizarnia" instead of "Spiżarnia", "Zuzytych produktow" instead of "Zużytych produktów", "Nieobslugiwany" instead of "Nieobsługiwany").

**Evidence:**
```python
# app/web_routes.py:305
_htmx_trigger(f"Zuzytych produktow: {len(ids)}")

# app/templates/dashboard/index.html:14
<div class="metric-label">Wydatki (miesiac)</div>

# app/templates/dashboard/index.html:42
<div class="metric-label">Spizarnia</div>
```

**Impact:** The application targets Polish users. Missing diacritics make the interface look unprofessional and harder to read.

**Recommendation:** Audit all user-visible strings and use proper Polish characters consistently.

---

### Medium

#### UX-002: No Loading/Error States for Long-Running Operations
**Location:** `app/templates/receipts/upload.html`, `app/templates/ask/index.html`
**Description:** OCR processing can take 5-240 seconds depending on the backend. The upload page shows a spinner, but there's no progress indication or timeout message. The "Ask AI" page similarly has no feedback during potentially long RAG queries.

**Recommendation:** Add progress indicators with estimated wait messages. Consider using SSE or polling for long-running operations.

---

#### UX-003: Chat UI Missing Session Management UX
**Location:** `app/templates/chat/index.html`
**Description:** The chat interface lacks visual cues for:
- Active session indicator
- Session creation timestamp
- Confirmation dialog before deleting all sessions
- Keyboard shortcut to submit messages (Enter key)

**Recommendation:** Add confirmation dialogs for destructive actions and visual session status indicators.

---

#### UX-004: Dashboard Polish Currency Symbol
**Location:** `app/templates/dashboard/index.html:13`, `app/templates/analytics/index.html`
**Description:** Currency shown as "zl" instead of "zł" throughout the web UI.

**Evidence:**
```html
<div class="metric-value">{{ "%.2f"|format(...) }} zl</div>
```

**Recommendation:** Use "zł" consistently.

---

#### UX-005: No Confirmation for Destructive Actions
**Location:** `app/web_routes.py:253-256` (receipt delete), `app/web_routes.py:731-743` (note delete), `app/web_routes.py:812-824` (bookmark delete)
**Description:** Delete operations execute immediately without confirmation dialogs.

**Recommendation:** Add JavaScript confirmation or a modal before destructive actions.

---

### Low

#### UX-006: Missing Accessibility Attributes
**Location:** `app/templates/base.html`, multiple templates
**Description:** The sidebar toggle button has `aria-label="Menu"` (good), but many interactive elements lack ARIA attributes. The data tables lack proper `scope` attributes. Chart canvases have no accessible alternatives.

**Recommendation:** Add `aria-label` to icon-only buttons, `scope` to table headers, and text alternatives for charts.

---

#### UX-007: No Empty State for Bookmarks and Dictionary
**Location:** `app/templates/bookmarks/index.html`, `app/templates/dictionary/index.html`
**Description:** When no data exists, the pages show empty content without guidance on how to add the first item.

**Recommendation:** Add empty state illustrations with CTAs (e.g., "No bookmarks yet. Send a URL via Telegram or add one here.").

---

#### UX-008: Localhost URL in Notification Button
**Location:** `app/telegram/notifications.py:251`
**Description:** Daily digest notification contains a hardcoded `localhost` URL.

**Evidence:**
```python
InlineKeyboardButton("Mapuj produkty", url=f"http://localhost:8000/web/dictionary"),
```

**Impact:** This link doesn't work from mobile devices or when the user is not on the same machine.

**Recommendation:** Use a configurable base URL from settings.

---

## Remediation Plan

### Phase 1: Critical Issues (Immediate)

| ID | Issue | Files affected |
|----|-------|----------------|
| SEC-001 | Add authentication to FastAPI/Web UI | `app/main.py`, `app/web_routes.py`, all `*_api.py` |
| SEC-002 | Fix SQL injection in embeddings repository | `app/db/repositories/embeddings.py` |
| SEC-003 | Sanitize uploaded filenames | `app/main.py`, `app/web_routes.py` |

### Phase 2: High Priority (Short-term)

| ID | Issue | Files affected |
|----|-------|----------------|
| SEC-004 | Fix SQL `.replace()` pattern | `app/db/repositories/analytics.py` |
| UX-001 | Fix Polish diacritics across UI | `app/web_routes.py`, `app/templates/**/*.html` |
| SEC-005 | Add SSRF protection to URL fetching | `app/web_scraper.py`, `app/rss_fetcher.py` |
| SEC-006 | Remove default credentials | `app/config.py`, `docker-compose.yml` |

### Phase 3: Medium Priority (Medium-term)

| ID | Issue | Files affected |
|----|-------|----------------|
| SEC-007 | Add security headers | `app/main.py` |
| SEC-008 | Add rate limiting | `app/main.py` |
| SEC-009 | Change Telegram auth default to deny | `app/telegram/middleware.py` |
| UX-002 | Add loading states for long operations | `app/templates/receipts/upload.html`, `app/templates/ask/index.html` |
| UX-003 | Improve chat session management UX | `app/templates/chat/index.html` |
| UX-004 | Fix currency symbol (zl -> zl) | `app/templates/**/*.html` |
| UX-005 | Add confirmation dialogs for deletes | `app/templates/**/*.html`, `app/static/js/app.js` |

### Phase 4: Low Priority (When convenient)

| ID | Issue | Files affected |
|----|-------|----------------|
| SEC-010 | Sanitize error responses | Multiple files |
| SEC-011 | Add CSRF protection | `app/web_routes.py`, templates |
| SEC-012 | Fix `data_json\|safe` XSS risk | `app/templates/analytics/index.html` |
| UX-006 | Add accessibility attributes | Templates |
| UX-007 | Add empty states | Templates |
| UX-008 | Fix hardcoded localhost URL | `app/telegram/notifications.py` |

---

## Next Steps

Awaiting your approval to proceed with remediation.
Please reply with:
- "Proceed with Phase 1" - to fix critical issues
- "Proceed with Phase 1-2" - to fix critical and high priority
- "Proceed with all" - to fix everything
- Or specify individual issue IDs to fix (e.g., "Fix SEC-001, UX-003")
