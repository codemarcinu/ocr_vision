# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Second Brain - personal knowledge management system with modules: OCR receipt processing, RSS/web summarization, audio/video transcription, personal notes, bookmarks, RAG knowledge base, and Chat AI (multi-turn with RAG + SearXNG web search). Uses Ollama LLMs, PostgreSQL + pgvector, and outputs to Obsidian markdown. Telegram bot with inline menus and human-in-the-loop validation.

Polish grocery receipts are the primary OCR target. Field names and UI text are in Polish (nazwa=name, cena=price, sklep=store, suma=total, rabat=discount, paragony=receipts, spiżarnia=pantry).

## Build & Run Commands

```bash
# Start all services (postgres, fastapi, searxng, monitoring)
docker-compose up -d

# Rebuild after code changes
docker-compose up -d --build

# View logs
docker logs -f pantry-api

# Database migrations
docker exec -it pantry-api alembic revision --autogenerate -m "description"
docker exec -it pantry-api alembic upgrade head
docker exec -it pantry-api alembic downgrade -1

# First-time data migration from JSON to PostgreSQL
docker exec -it pantry-api python scripts/migrate_data.py

# Test API
curl http://localhost:8000/health
curl http://localhost:8000/models/status   # VRAM usage and model states
curl -X POST http://localhost:8000/process-receipt -F "file=@receipt.png"

# Database shell
docker exec -it pantry-db psql -U pantry -d pantry
```

### Local Development (without Docker)

```bash
pip install -r requirements.txt
OLLAMA_BASE_URL=http://localhost:11434 uvicorn app.main:app --reload
```

No automated tests exist. No linting or formatting tools configured. Testing is manual via API calls and Telegram bot.

FastAPI auto-docs available at `http://localhost:8000/docs` (Swagger UI).

### Development Workflow

After modifying Python code:
```bash
docker-compose up -d --build          # Rebuild and restart
docker logs -f pantry-api             # Watch for startup errors
curl http://localhost:8000/health      # Verify running
```

For quick iteration on non-startup code, `uvicorn --reload` inside the container picks up changes if the source is volume-mounted. Currently, the source is baked into the Docker image, so a rebuild is needed.

### Database Schema Changes

Database initializes from `scripts/init-db.sql` on first PostgreSQL start (empty volume). For schema changes after initial setup, use Alembic migrations—**not** init-db.sql edits:
```bash
docker exec -it pantry-api alembic revision --autogenerate -m "description"
docker exec -it pantry-api alembic upgrade head
```
The ORM source of truth is `app/db/models.py`. Alembic's `env.py` is configured for async (asyncpg).

## Architecture

### High-Level Data Flow

```
Inputs (Telegram/API/Web UI)
    ↓
FastAPI (app/main.py) ──→ Ollama LLMs (host:11434)
    ↓
PostgreSQL + pgvector ──→ Obsidian vault/ markdown
```

Docker services: `postgres` (pgvector/pgvector:pg16), `fastapi` (pantry-api, CUDA GPU), `searxng` (metasearch for Chat AI), optional monitoring (prometheus/grafana/loki).

Ollama runs on the host machine, accessed from Docker via `host.docker.internal:11434`.

### Receipt OCR Pipeline

```
Receipt (photo/PDF) → OCR Backend → Store Detection → Store-Specific Prompt
    → LLM Structuring → Price Fixer → Normalization → Categorization
    → Confidence Scoring → [Human Review if needed] → PostgreSQL + Obsidian
```

**OCR backends** (set via `OCR_BACKEND` env var):

| Backend | Speed | How it works |
|---------|-------|-------------|
| `google` | ~5s | Google Cloud Vision API → raw text → qwen2.5:7b structuring. Requires API key, ~$1.50/1000 images |
| `deepseek` | ~15s | DeepSeek-OCR model → raw text → qwen2.5:7b structuring. Has fallback to qwen2.5vl:7b |
| `paddle` | ~11s | PaddleOCR → raw text → qwen2.5:7b structuring. Less accurate on complex receipts |
| `openai` | ~5s | Google Cloud Vision API → OpenAI GPT-4o-mini structuring. Requires `OPENAI_API_KEY` |
| `vision` | ~4min | qwen2.5vl:7b single model for everything. Slowest but no dependencies |

**Single-model mode** (`OCR_SINGLE_MODEL_MODE=true`): Vision model performs OCR + JSON structuring in one call, reducing model switches. Useful for 12GB VRAM systems where loading both vision and text models causes thrashing.

**Category cache** (`CLASSIFIER_CACHE_TTL`): Caches product→category mappings to skip LLM calls for recently seen products. Set to 0 to disable.

**Human-in-the-loop review** triggers when extracted total vs product sum differs by >5 PLN AND >10%. User approves, corrects total, or rejects via Telegram inline keyboard.

**Multi-page PDF**: Pages processed in parallel (`PDF_MAX_PARALLEL_PAGES`), products combined, per-page verification skipped (would corrupt partial totals).

### Module Architecture

Each module follows a consistent pattern:
- **API router** (`app/*_api.py`) - FastAPI endpoints
- **Database models** (`app/db/models.py`) - SQLAlchemy ORM
- **Repository** (`app/db/repositories/*.py`) - Data access layer
- **Service** (`app/services/*.py`) - Business logic orchestration (emerging pattern)
- **Writer** (`app/*_writer.py`) - Obsidian markdown generation
- **Telegram handler** (`app/telegram/handlers/*.py`) - Bot commands
- **Telegram menu** (`app/telegram/handlers/menu_*.py`) - Inline keyboard navigation

Modules: receipts, RSS/summarizer, transcription, notes, bookmarks, RAG (/ask), chat, agent (tool-calling), analytics, dictionary, search, reports.

### Unified Search (`app/search_api.py`)

Cross-content search endpoint at `/search`. Searches receipts, articles, notes, bookmarks, and transcriptions concurrently. Filter by content type with `?types=receipt,note`. Returns results grouped by type with snippets.

### Reports (`app/reports.py`)

Analytics endpoints at `/reports/*`:
- `/reports/discounts` - Discount analysis by store, category, month
- `/reports/stores` - Spending per store with averages
- `/reports/monthly` - Monthly trends with top categories
- `/reports/categories` - Spending breakdown by category
- `/reports/summary` - Full overview with date range
- `/reports/classifier-ab` - A/B test results for classifier models

### Operational Endpoints

- `/health` - Basic health check
- `/models/status` - VRAM usage, loaded models, eviction metrics (when `MODEL_COORDINATION_ENABLED=true`)

### Docker Volume Mounts

Local paths map to `/data/` inside the container:
```
./paragony    → /data/paragony    (receipt inbox/processed)
./vault       → /data/vault       (Obsidian output: paragony, notes, bookmarks, transcriptions, summaries, logs, daily)
```
All `*_OUTPUT_DIR` settings in `config.py` default to subdirectories of `/data/vault/` so that all generated markdown is visible in Obsidian.

### Key Design Patterns

**Repository pattern** with FastAPI dependency injection via typed aliases (`app/dependencies.py`):
```python
from app.dependencies import ProductRepoDep  # = Annotated[ProductRepository, Depends(...)]
@router.get("/products")
async def list_products(repo: ProductRepoDep):
    return await repo.list_all()
```
All database operations are **async** (SQLAlchemy 2.0 + asyncpg). Repository classes accept `AsyncSession` and use `await session.execute()`. Never use synchronous SQLAlchemy calls.

**Telegram callback router** (`app/telegram/callback_router.py`): Prefix-based routing instead of monolithic if/elif. Handlers registered by prefix (e.g., `"receipts:"`, `"notes:"`).

**RAG auto-indexing** (`app/rag/hooks.py`): Fire-and-forget hooks in notes_api, bookmarks_api, rss_api, transcription_api auto-index new content for `/ask` queries. If embeddings table is empty on startup, triggers background `reindex_all()`.

**Chat AI intent classification** (`app/chat/intent_classifier.py`): LLM classifies each message as `"rag"` (personal data), `"web"` (internet search via SearXNG), `"both"`, or `"direct"` (no search needed).

**Telegram chat always-on** (`app/telegram/bot.py`): Chat sessions are created automatically when user sends a text message. No explicit `/chat` command needed—just type and the bot responds with RAG + web search context. Message routing priority: (1) manual total input, (2) URL → action picker, (3) note creation flow, (4) fallback to chat. The `_ensure_chat_session()` helper creates or retrieves active sessions on demand. `/endchat` resets the conversation (archives old session, creates new one) rather than disabling chat.

**Language detection**: Multiple modules auto-detect Polish vs English based on Polish characters (ą,ć,ę...) and keyword matching. Polish → Bielik 11B model, English → qwen2.5:7b.

**Model coordination** (`app/model_coordinator.py`): Centralized VRAM management to minimize thrashing from model switches. The coordinator tracks loaded models, enforces a VRAM budget, and uses LRU eviction when space is needed. Enable with `MODEL_COORDINATION_ENABLED=true`. Key features:
- Per-model locking to prevent concurrent load/unload
- VRAM budget tracking (default 12GB)
- LRU eviction policy for automatic model unloading
- Waiter counting to avoid unloading models with pending requests

**OCR backend conditional imports** (`app/main.py`): Backend selection happens at import time via `settings.OCR_BACKEND`, loading the appropriate module (paddle_ocr, deepseek_ocr, google_ocr_backend, openai_ocr_backend, or default vision ocr).

**Error messages in Polish**: User-facing error text uses Polish (e.g., "Wystąpił błąd"). Keep this convention in Telegram handlers and web UI.

**Authentication** (`app/auth.py`): Optional token-based auth controlled by `AUTH_TOKEN` env var. When set:
- API endpoints require `Authorization: Bearer <token>` header
- Web UI uses session cookies with `/login` and `/logout` routes
- Telegram bot has separate `@authorized_only` decorator based on `TELEGRAM_CHAT_ID`
- Public paths (`/health`, `/docs`, `/metrics`) bypass auth

### Product Normalization Chain (`app/dictionaries/`)

1. **Exact match** → `products.json` raw_names
2. **Partial match** → 70%+ word overlap
3. **Shortcut match** → `product_shortcuts.json` (thermal printer abbreviations per store)
4. **Fuzzy match** → Levenshtein distance < 0.75
5. **Keyword match** → Category keywords

### Transcription Map-Reduce (`app/transcription/extractor.py`)

For transcriptions > 15k chars: split into 10k char chunks at sentence boundaries with 1k overlap → MAP phase extracts from each chunk → REDUCE phase deduplicates and synthesizes. Configurable via `MAPREDUCE_*` env vars.

### Store-Specific OCR Prompts (`app/store_prompts.py`)

Each store (Biedronka, Lidl, Kaufland, Żabka, etc.) has a tailored extraction prompt matching its receipt format. See "Adding a New Store for OCR" below for extension instructions.

### Agent Tool-Calling (`app/agent/`)

LLM-based natural language routing to system tools. User sends a message (text or voice transcription), LLM selects the appropriate tool and extracts arguments, then the tool is executed.

**Chat Integration (`CHAT_AGENT_ENABLED=true`):**
Agent is integrated with chat as a pre-processor. When user sends a message:
1. Agent classifies: is this an ACTION or a SEARCH/CONVERSATION?
2. **Action tools** (`create_note`, `create_bookmark`, `summarize_url`, `list_recent`) → execute immediately
3. **Search tools** (`search_knowledge`, `search_web`, `get_weather`, `get_spending`, `get_inventory`, `answer_directly`) → fall through to orchestrator with conversation history

```
User: "Zanotuj: spotkanie jutro o 10"
        ↓
    [Agent] → create_note → "Utworzono notatkę: Spotkanie"

User: "Co jadłem w tym tygodniu?"
        ↓
    [Agent] → get_spending → [Orchestrator] → "W tym tygodniu kupiłeś..."
```

**Components:**
- `tools.py` - Tool definitions (10 tools), Pydantic argument models, validation
- `router.py` - AgentRouter class: LLM call with retry, tool dispatch, logging
- `validator.py` - Input sanitization, prompt injection detection (low/medium/high risk)
- `app/chat/agent_executor.py` - Tool executors connecting to notes/bookmarks/RSS APIs

**Available tools:** `create_note`, `search_knowledge`, `search_web`, `get_spending`, `get_inventory`, `get_weather`, `summarize_url`, `list_recent`, `create_bookmark`, `answer_directly`

**Usage (standalone):**
```python
from app.agent.router import create_agent_router

router = create_agent_router()
router.register_executor("create_note", my_note_handler)
response = await router.process("Zapisz notatkę: jutro spotkanie o 10")
# response.tool = "create_note", response.arguments = {"title": "...", "content": "..."}
```

All agent calls are logged to `agent_call_logs` table (AgentCallLog model) for debugging and security monitoring.

## Key Configuration

All settings in `app/config.py` via `Settings` class, overridable with env vars. See `.env.example` for the full list.

**Critical env vars:**

```bash
# OCR
OCR_BACKEND=google|deepseek|vision|paddle|openai
OCR_MODEL=qwen2.5vl:7b               # Default vision model
OCR_FALLBACK_MODEL=qwen2.5vl:7b
CLASSIFIER_MODEL=qwen2.5:7b
STRUCTURING_MODEL=                    # For deepseek backend (empty = CLASSIFIER_MODEL)
OPENAI_API_KEY=                       # Required for OCR_BACKEND=openai
OPENAI_OCR_MODEL=gpt-4o-mini         # OpenAI model for structuring

# Database
DATABASE_URL=postgresql+asyncpg://pantry:pantry123@postgres:5432/pantry

# Telegram
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=123456  # 0 = allow all users

# Authentication (optional)
AUTH_TOKEN=                           # Set to enable API/Web auth (empty = no auth)

# Feature flags
USE_DB_DICTIONARIES=true
USE_DB_RECEIPTS=true
GENERATE_OBSIDIAN_FILES=true
RAG_ENABLED=true
CHAT_ENABLED=true
CHAT_AGENT_ENABLED=true              # Agent tool-calling in chat (auto-detect actions)
TRANSCRIPTION_ENABLED=true
NOTES_ENABLED=true
BOOKMARKS_ENABLED=true

# Models (empty string = falls back to CLASSIFIER_MODEL)
CHAT_MODEL=                                               # Empty = CLASSIFIER_MODEL; typically Bielik for Polish
EMBEDDING_MODEL=nomic-embed-text                          # RAG embeddings (768 dim)
SUMMARIZER_MODEL_PL=SpeakLeash/bielik-11b-v3.0-instruct:Q5_K_M

# A/B testing for classifier
CLASSIFIER_MODEL_B=                   # Set to enable A/B testing
CLASSIFIER_AB_MODE=primary            # primary|secondary|both

# GPU memory
VISION_MODEL_KEEP_ALIVE=10m
TEXT_MODEL_KEEP_ALIVE=30m
UNLOAD_MODELS_AFTER_USE=false         # Set true for low VRAM systems
WHISPER_UNLOAD_AFTER_USE=true         # Free VRAM after transcription

# Model coordination (VRAM management)
MODEL_COORDINATION_ENABLED=true       # Enable centralized VRAM coordination
MODEL_MAX_VRAM_MB=12000               # VRAM budget in MB
MODEL_PRELOAD_ON_STARTUP=qwen2.5:7b   # Comma-separated models to preload
MODEL_SWITCH_QUEUE_TIMEOUT=300        # Max wait for model load (seconds)
OCR_SINGLE_MODEL_MODE=false           # Vision model does OCR+structuring (fewer switches)
CLASSIFIER_CACHE_TTL=3600             # Category cache TTL (seconds, 0=disabled)
DEEPSEEK_OCR_TIMEOUT=90               # DeepSeek timeout (increased for slow GPUs)

# Web search (SearXNG)
WEB_SEARCH_NUM_RESULTS=6              # Results per search query
WEB_SEARCH_EXPAND_NEWS=false          # Expand news categories in search
```

### Ollama Models Required

```bash
ollama pull qwen2.5:7b        # Structuring + categorization (~4.7GB VRAM)
ollama pull qwen2.5vl:7b      # Vision OCR (~6GB VRAM)
ollama pull nomic-embed-text   # RAG embeddings (~274MB VRAM)
# For Polish content:
ollama pull SpeakLeash/bielik-11b-v3.0-instruct:Q5_K_M  # Chat + summaries (~7GB VRAM)
```

VRAM estimates are used by the ModelCoordinator for intelligent model switching. The coordinator can fit ~2 large models (e.g., qwen2.5:7b + qwen2.5vl:7b) in 12GB VRAM.

## Web UI

HTMX + Jinja2 templates at `http://localhost:8000/app/`. Templates in `app/templates/` organized by feature with `partials/` subdirectories for HTMX partial responses. Toast notifications via HX-Trigger headers.

## Output Files

All output goes to `vault/` (Obsidian vault):
- `vault/paragony/*.md` - Receipt markdown with YAML frontmatter
- `vault/spiżarnia.md` - Aggregated pantry view
- `vault/logs/` - Error log, unmatched products JSON, corrections JSON
- `vault/notes/*.md` - Personal notes + index
- `vault/bookmarks/index.md` - Bookmarks index
- `vault/transcriptions/*.md` - Transcription notes + index
- `vault/summaries/*.md` - RSS article summaries + index
- `vault/daily/*.md` - Daily summaries

## Database

PostgreSQL 16 with `pg_trgm` (fuzzy text) and `pgvector` (embeddings) extensions. Schema in `scripts/init-db.sql`, ORM in `app/db/models.py`, migrations in `alembic/versions/`.

Set all feature flags to `false` to revert to file-only mode (no database).

## Security Considerations

See `PROJECT_AUDIT.md` for full security audit. Key known issues:

**Critical/High:**
- **SEC-001**: No authentication on FastAPI/Web UI (Telegram bot has `@authorized_only`)
- **SEC-002**: SQL injection via f-string in `app/db/repositories/embeddings.py` (use parameterized queries with `ANY(:types)`)
- **SEC-003**: Path traversal in file uploads (sanitize with `PurePosixPath(filename).name`)
- **SEC-005**: SSRF in web scraper/RSS fetcher (validate URLs, block private IP ranges)

**Mitigating factor:** Docker Compose binds ports to `127.0.0.1` only, limiting exposure to localhost.

When adding new endpoints: use FastAPI's parameterized queries, sanitize user-provided filenames, validate external URLs.

## Extending the Codebase

### Adding a New API Module

Follow the existing module pattern:
1. Create repository in `app/db/repositories/` (extend base pattern)
2. Add ORM model to `app/db/models.py`, create Alembic migration
3. Create API router as `app/<module>_api.py` with FastAPI `APIRouter`
4. Add dependency alias to `app/dependencies.py` (typed `Annotated` alias)
5. Register router in `app/main.py`
6. Optionally: add Obsidian writer (`app/<module>_writer.py`), Telegram handler, RAG auto-indexing hook

### Adding a New Telegram Handler

1. Create handler in `app/telegram/handlers/`
2. For inline keyboard menus: create `menu_<module>.py`, register callback prefix in `app/telegram/bot.py` via `CallbackRouter.register("<prefix>:", handler_function)`
3. Handler signature for callbacks: `async def handler(query: CallbackQuery, action: str, context: ContextTypes.DEFAULT_TYPE)`
4. For command handlers: register in `bot.py` using `application.add_handler(CommandHandler(...))`

### Adding a New Store for OCR

Documented in `app/store_prompts.py`:
1. Add detection patterns to `STORE_PATTERNS`
2. Create `PROMPT_STORENAME` with format-specific instructions
3. Add to `STORE_PROMPTS` mapping

### Adding a New Agent Tool

1. Add tool name to `ToolName` enum in `app/agent/tools.py`
2. Create Pydantic argument model (e.g., `MyToolArgs(BaseModel)`) with validators
3. Add to `TOOL_ARG_MODELS` mapping
4. Add tool definition to `TOOL_DEFINITIONS` list (name, description, parameters)
5. Register executor in your router: `router.register_executor("my_tool", my_handler)`

Tool arguments are validated with Pydantic before execution. Use `@field_validator` for input normalization (strip whitespace, normalize Polish variations like "notatka"/"notatki"→"notes").
