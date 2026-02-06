# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Second Brain - personal knowledge management system with modules: OCR receipt processing, RSS/web summarization, audio/video transcription, personal notes, bookmarks, RAG knowledge base, and Chat AI (multi-turn with RAG + SearXNG web search). Uses Ollama LLMs, PostgreSQL + pgvector, and outputs to Obsidian markdown. Web UI, mobile PWA, and REST API interfaces.

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

# HTTPS with Caddy (auto Let's Encrypt)
docker compose --profile https up -d

# Cloudflare Tunnel for external access
bash scripts/setup_cloudflare.sh
```

### Local Development (without Docker)

```bash
pip install -r requirements.txt
OLLAMA_BASE_URL=http://localhost:11434 uvicorn app.main:app --reload
```

No automated tests exist. No linting or formatting tools configured. Testing is manual via API calls and web UI. Test scripts in `scripts/` for agent tools and security (`test_agent_tools.py`, `test_agent_security.py`).

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
The ORM source of truth is `app/db/models.py`. Alembic's `env.py` is configured for async (asyncpg). 10 migrations exist in `alembic/versions/`.

## Architecture

### High-Level Data Flow

```
Inputs (API/Web UI/Mobile PWA)
    ↓
FastAPI (app/main.py) ──→ Ollama LLMs (host:11434)
    ↓
PostgreSQL + pgvector ──→ Obsidian vault/ markdown
```

Docker services: `postgres` (pgvector/pgvector:pg16), `fastapi` (pantry-api, CUDA GPU), `searxng` (metasearch for Chat AI), optional `caddy` (HTTPS reverse proxy with auto-SSL, `--profile https`), optional monitoring (prometheus/grafana/loki).

Ollama runs on the host machine, accessed from Docker via `host.docker.internal:11434`.

### Project Structure

```
app/
├── main.py                     # FastAPI app entry point, router registration
├── config.py                   # Settings class (all env vars)
├── models.py                   # Pydantic data models
├── dependencies.py             # FastAPI DI aliases (14 repo + 1 session)
├── auth.py                     # Token + session auth
├── rate_limit.py               # slowapi rate limiting
│
├── web/                        # Web UI routes (split from monolithic web_routes.py)
│   ├── __init__.py             # Composite router
│   ├── helpers.py              # Shared: templates(), emojis, _htmx_trigger()
│   ├── dashboard.py            # GET /app/
│   ├── receipts.py             # /app/paragony/*
│   ├── pantry.py               # /app/spizarnia/*
│   ├── analytics.py            # /app/analityka/*
│   ├── articles.py             # /app/artykuly/*
│   ├── transcriptions.py       # /app/transkrypcje/*
│   ├── notes.py                # /app/notatki/*
│   ├── bookmarks.py            # /app/zakladki/*
│   ├── dictionary.py           # /app/slownik/*
│   ├── search.py               # /app/szukaj/*
│   ├── ask.py                  # /app/zapytaj/*
│   ├── chat.py                 # /app/czat/*
│   ├── command_palette.py      # GET /app/command-palette (Ctrl+K search)
│   └── redirects.py            # Legacy /web/* → /app/* redirects
│
├── ocr/                        # OCR backends
│   ├── __init__.py             # Re-exports from vision.py (backward compat)
│   ├── vision.py               # Default: qwen2.5vl single model
│   ├── deepseek.py             # DeepSeek-OCR + text structuring
│   ├── paddle.py               # PaddleOCR + text structuring
│   ├── google_backend.py       # Google Cloud Vision + text structuring
│   ├── google_vision.py        # Google Vision API utility
│   ├── openai_backend.py       # Google Vision + OpenAI GPT-4o-mini
│   └── prompts.py              # Shared OCR prompts
│
├── writers/                    # Obsidian markdown generators
│   ├── __init__.py             # Re-exports all writers
│   ├── obsidian.py             # Receipt + pantry + error logs
│   ├── notes.py                # Personal notes markdown
│   ├── bookmarks.py            # Bookmarks index
│   ├── summary.py              # RSS article summaries
│   └── daily.py                # Daily notes (voice memo aggregation)
│
├── agent/                      # LLM tool-calling agent
│   ├── tools.py                # 12 tool definitions + Pydantic models
│   ├── router.py               # AgentRouter: LLM call, retry, dispatch
│   └── validator.py            # Input sanitization, prompt injection detection
│
├── chat/                       # Chat AI orchestrator
│   ├── orchestrator.py         # Main pipeline coordination
│   ├── intent_classifier.py    # 7-intent classification (rag/web/both/direct/weather/spending/inventory)
│   ├── agent_executor.py       # Tool executors for agent integration
│   ├── history_manager.py      # Session history + summarization
│   ├── content_fetcher.py      # RAG content retrieval for chat
│   ├── data_tools.py           # Spending, inventory, weather helpers
│   ├── searxng_client.py       # SearXNG web search integration
│   └── weather_client.py       # OpenWeather API client
│
├── rag/                        # RAG knowledge base
│   ├── embedder.py             # nomic-embed-text (768 dim)
│   ├── indexer.py              # Chunking + embedding pipeline
│   ├── retriever.py            # Vector search + keyword fallback
│   ├── answerer.py             # Q&A with retrieved context
│   └── hooks.py                # Fire-and-forget auto-indexing hooks
│
├── transcription/              # Audio/video processing
│   ├── transcriber.py          # Faster-Whisper service
│   ├── downloader.py           # yt-dlp for YouTube
│   ├── extractor.py            # Map-reduce knowledge extraction
│   └── note_writer.py          # Transcription markdown + Map of Content
│
├── services/                   # Business logic orchestration
│   ├── receipt_saver.py        # Receipt → DB + Obsidian + RAG
│   ├── obsidian_sync.py        # Vault regeneration from DB
│   ├── notes_organizer.py      # Report, auto-tag, duplicate detection
│   └── push_service.py         # Web Push notification sender
│
├── db/                         # Database layer
│   ├── connection.py           # Async engine + session factory
│   ├── models.py               # SQLAlchemy ORM (25 models)
│   └── repositories/           # Data access (16 repos)
│       ├── base.py, receipts.py, products.py, pantry.py, stores.py
│       ├── analytics.py, rss.py, transcription.py, notes.py, bookmarks.py
│       ├── embeddings.py, chat.py, agent.py, feedback.py
│       ├── user_profile.py, push.py
│
├── push/                       # Push notification hooks
│   └── hooks.py                # Auto-notify on content creation
│
├── dictionaries/               # Product normalization data
│   ├── products.json           # Canonical product names + categories
│   ├── product_shortcuts.json  # Store-specific abbreviations
│   └── stores.json             # Store metadata
│
├── API routers (REST)
│   ├── receipts_api.py         # /receipts/*
│   ├── pantry_api.py           # /pantry/*
│   ├── rss_api.py              # /rss/*
│   ├── transcription_api.py    # /transcription/*
│   ├── notes_api.py            # /notes/*
│   ├── bookmarks_api.py        # /bookmarks/*
│   ├── dictionary_api.py       # /dictionary/*
│   ├── search_api.py           # /search
│   ├── ask_api.py              # /ask
│   ├── chat_api.py             # /chat/*
│   ├── profile_api.py          # /profile/*
│   ├── push_api.py             # /api/push/*
│   ├── mobile_routes.py        # /m/*
│   └── reports.py              # /reports/*
│
├── Core processing
│   ├── receipt_parser.py       # Receipt parsing pipeline
│   ├── classifier.py           # Product categorization + cache
│   ├── price_fixer.py          # Price validation + correction
│   ├── confidence_scoring.py   # Receipt confidence metrics
│   ├── store_prompts.py        # Store-specific OCR prompts
│   ├── summarizer.py           # RSS/web summarization
│   ├── web_scraper.py          # Trafilatura web extraction
│   ├── rss_fetcher.py          # Feedparser client
│   ├── image_preprocessing.py  # OpenCV preprocessing
│   ├── pdf_converter.py        # pdf2image wrapper
│   ├── ollama_client.py        # Ollama API client + coordinator
│   ├── openai_client.py        # OpenAI API client
│   ├── model_coordinator.py    # VRAM management + LRU eviction
│   ├── feedback_logger.py      # User feedback tracking
│   └── url_validator.py        # SSRF protection
│
├── templates/                  # Jinja2 (55+ files, organized by feature)
│   ├── base.html, login.html, offline.html
│   ├── mobile/                 # PWA templates (separate base.html)
│   ├── dashboard/, receipts/, pantry/, analytics/
│   ├── articles/, transcriptions/, notes/, bookmarks/
│   ├── dictionary/, search/, ask/, chat/
│   └── components/             # Reusable: navbar, pagination, metric_card
│
└── static/                     # Frontend assets
    ├── css/custom.css, css/mobile.css
    ├── js/app.js, js/command-palette.js, js/upload.js
    ├── js/mobile.js, js/offline-queue.js, js/charts.js
    ├── js/htmx.min.js, js/marked.min.js, js/purify.min.js
    ├── icons/                  # PWA icons (72-512px)
    ├── manifest.json           # PWA manifest
    └── sw.js                   # Service worker (offline caching)
```

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

OCR backend code is in `app/ocr/`. The `__init__.py` re-exports from `vision.py` for backward compatibility (`from app.ocr import ...` works).

**Single-model mode** (`OCR_SINGLE_MODEL_MODE=true`): Vision model performs OCR + JSON structuring in one call, reducing model switches. Useful for 12GB VRAM systems where loading both vision and text models causes thrashing.

**Category cache** (`CLASSIFIER_CACHE_TTL`): Caches product→category mappings to skip LLM calls for recently seen products. Set to 0 to disable.

**Human-in-the-loop review** triggers when extracted total vs product sum differs by >5 PLN AND >10%. User approves, corrects total, or rejects via web UI.

**Multi-page PDF**: Pages processed in parallel (`PDF_MAX_PARALLEL_PAGES`), products combined, per-page verification skipped (would corrupt partial totals).

### Module Architecture

Each module follows a consistent pattern:
- **API router** (`app/*_api.py`) - FastAPI endpoints
- **Database models** (`app/db/models.py`) - SQLAlchemy ORM (25 models)
- **Repository** (`app/db/repositories/*.py`) - Data access layer (16 repos)
- **Service** (`app/services/*.py`) - Business logic orchestration (4 services)
- **Writer** (`app/writers/*.py`) - Obsidian markdown generation (5 writers)
- **Web route** (`app/web/*.py`) - HTMX UI (14 feature modules)

Modules: receipts, RSS/summarizer, transcription, notes, bookmarks, RAG (/ask), chat, agent (tool-calling), analytics, dictionary, search, reports, user profiles, push notifications, mobile PWA.

### Unified Search (`app/search_api.py`)

Cross-content search endpoint at `/search`. Searches receipts, articles, notes, bookmarks, and transcriptions concurrently. Filter by content type with `?types=receipt,note`. Returns results grouped by type with snippets.

### Command Palette (`app/web/command_palette.py`)

Global search + quick actions triggered by Ctrl+K. Searches across all content types dynamically. Provides static navigation shortcuts (all major pages) and dynamic content results (notes, receipts, bookmarks, articles). Frontend in `app/static/js/command-palette.js`.

### Reports (`app/reports.py`)

Analytics endpoints at `/reports/*`:
- `/reports/discounts` - Discount analysis by store, category, month
- `/reports/stores` - Spending per store with averages
- `/reports/monthly` - Monthly trends with top categories
- `/reports/categories` - Spending breakdown by category
- `/reports/summary` - Full overview with date range
- `/reports/classifier-ab` - A/B test results for classifier models

### Notes Organizer (`app/services/notes_organizer.py`)

Service for notes health management, accessible via agent tool `organize_notes` and API endpoints:
- `POST /notes/organize/report` - Health report (total, without tags, without category, short content, duplicates)
- `POST /notes/organize/auto-tag` - LLM-generated tags for notes without tags (batch of 20, supports `dry_run`)
- `POST /notes/organize/duplicates` - Semantic duplicate detection via RAG embeddings (threshold: 0.85)

### User Profiles (`app/profile_api.py`)

Per-user preferences stored in `UserProfile` model: preferred stores, city (for weather), display settings. API at `/profile/*`.

### Operational Endpoints

- `/health` - Basic health check
- `/models/status` - VRAM usage, loaded models, eviction metrics (when `MODEL_COORDINATION_ENABLED=true`)
- `/metrics` - Prometheus metrics (via `prometheus-fastapi-instrumentator`)
- `/docs` - Swagger UI (FastAPI auto-docs)

### Docker Volume Mounts

Default paths in `docker-compose.yml` map to `/data/` inside the container:
```
./paragony    → /data/paragony    (receipt inbox/processed)
./vault       → /data/vault       (Obsidian: paragony, bookmarks, transcriptions, logs, daily)
```

**Production override** (`docker-compose.override.yml`) maps to actual Obsidian vault:
```yaml
volumes:
  - /home/marcin/Dokumenty/sejf/2brain/zakupy:/data/vault      # receipts
  - /home/marcin/Dokumenty/sejf/2brain/artykuly:/data/summaries # RSS summaries
  - /home/marcin/Dokumenty/sejf/2brain/0-inbox:/data/notes      # personal notes
```

Container runs as `user: "1000:1000"` so files have correct ownership (marcin:marcin).

All `*_OUTPUT_DIR` settings in `config.py` can be overridden via env vars (e.g., `NOTES_OUTPUT_DIR=/data/notes`).

### Key Design Patterns

**Repository pattern** with FastAPI dependency injection via typed aliases (`app/dependencies.py`):
```python
from app.dependencies import ProductRepoDep  # = Annotated[ProductRepository, Depends(...)]
@router.get("/products")
async def list_products(repo: ProductRepoDep):
    return await repo.list_all()
```
All database operations are **async** (SQLAlchemy 2.0 + asyncpg). Repository classes accept `AsyncSession` and use `await session.execute()`. Never use synchronous SQLAlchemy calls.

**RAG auto-indexing** (`app/rag/hooks.py`): Fire-and-forget hooks in notes_api, bookmarks_api, rss_api, transcription_api auto-index new content for `/ask` queries. If embeddings table is empty on startup, triggers background `reindex_all()`.

**Chat AI intent classification** (`app/chat/intent_classifier.py`): LLM classifies each message into 7 intent types:
- `rag` - personal data (articles, notes, bookmarks, transcriptions)
- `spending` - receipt analytics, prices, shopping costs
- `inventory` - pantry queries, food stock, expiring items
- `weather` - current weather, forecast
- `web` - internet search, current events, facts
- `both` - hybrid personal + web search
- `direct` - general knowledge, greetings, math, conversation

Fallback chain: `rag` with no results → try `web`; `web` with no results → try `rag`.

**3-layer Polish language detection**: Used in chat, summarizer, and transcription to select models (Bielik for Polish, qwen2.5 for English):
1. Polish-specific characters (ą, ć, ę, ł, ń, ó, ś, ź, ż)
2. Distinctly Polish keywords (się, jak, ile, czy)
3. Weak indicator counting (i, w, na, do)

**Model coordination** (`app/model_coordinator.py`): Centralized VRAM management to minimize thrashing from model switches. The coordinator tracks loaded models, enforces a VRAM budget, and uses LRU eviction when space is needed. Enable with `MODEL_COORDINATION_ENABLED=true`. Key features:
- Per-model locking to prevent concurrent load/unload
- VRAM budget tracking (default 12GB)
- LRU eviction policy for automatic model unloading
- Waiter counting to avoid unloading models with pending requests

**OCR backend conditional imports** (`app/main.py`): Backend selection happens at import time via `settings.OCR_BACKEND`, loading the appropriate module from `app/ocr/` (paddle, deepseek, google_backend, openai_backend, or default vision).

**Error messages in Polish**: User-facing error text uses Polish (e.g., "Wystąpił błąd"). Keep this convention in web UI.

### Product Normalization Chain (`app/dictionaries/`)

1. **Exact match** → `products.json` raw_names
2. **Partial match** → 70%+ word overlap
3. **Shortcut match** → `product_shortcuts.json` (thermal printer abbreviations per store)
4. **Fuzzy match** → Levenshtein distance < 0.75
5. **Keyword match** → Category keywords

### Transcription System (`app/transcription/`)

**Map-Reduce** (`app/transcription/extractor.py`): For transcriptions > 15k chars: split into 10k char chunks at sentence boundaries with 1k overlap → MAP phase extracts from each chunk → REDUCE phase deduplicates and synthesizes. Configurable via `MAPREDUCE_*` env vars.

**Map of Content** (`app/transcription/note_writer.py`): Generates categorized `index.md` in transcription output directory. Groups transcriptions by category (Edukacja, Technologia, Biznes, etc.) with wiki-links, duration metadata, and per-category counts.

**Voice Message Queuing**: Voice messages (`source_type=voice`) are queued and batch-processed at configurable intervals (`VOICE_NOTE_PROCESS_INTERVAL_MINUTES`, default 30) to avoid VRAM conflicts with chat. Transcribed voice memos are aggregated into daily notes via `app/writers/daily.py`.

**Daily Notes** (`app/writers/daily.py`): `DailyNoteWriter` aggregates voice memos into one file per day with timestamped sections and YAML frontmatter. Output to `DAILY_OUTPUT_DIR` (default `/data/vault/daily/`).

### Store-Specific OCR Prompts (`app/store_prompts.py`)

Each store (Biedronka, Lidl, Kaufland, Żabka, etc.) has a tailored extraction prompt matching its receipt format. See "Adding a New Store for OCR" below for extension instructions.

### Agent Tool-Calling (`app/agent/`)

LLM-based natural language routing to system tools. User sends a message (text or voice transcription), LLM selects the appropriate tool and extracts arguments, then the tool is executed.

**Chat Integration (`CHAT_AGENT_ENABLED=true`):**
Agent is integrated with chat as a pre-processor. When user sends a message:
1. Agent classifies: is this an ACTION or a SEARCH/CONVERSATION?
2. **Action tools** (`create_note`, `create_bookmark`, `summarize_url`, `list_recent`, `ask_clarification`, `organize_notes`) → execute immediately
3. **Search tools** (`search_knowledge`, `search_web`, `get_weather`, `get_spending`, `get_inventory`, `answer_directly`) → fall through to orchestrator with `search_strategy` hint (skips IntentClassifier)

**Tool Result Memory:**
When action tools execute, their results are saved to conversation history with `[TOOL_RESULT: tool_name]` prefix. This allows agent to reference previous tool outputs in follow-up requests (e.g., "zapisz to jako notatkę" after `summarize_url`).

**Summarize-to-Note backlinks:** When `summarize_url` chains to `create_note`, the note content includes a backlink to the original URL.

**Clarification Tool:**
`ask_clarification` allows agent to ask user for more details when intent is unclear (e.g., "zapisz to" without context). Returns formatted question with optional suggested options.

**Confidence Scoring:**
Agent returns confidence score (0.0-1.0) with each tool selection. When confidence < `AGENT_CONFIDENCE_THRESHOLD` (default 0.6), auto-fallback to `ask_clarification` instead of guessing. Confidence logged to `agent_call_logs` table for analytics.

```
User: "Zanotuj: spotkanie jutro o 10"
        ↓
    [Agent] → create_note → "Utworzono notatkę: Spotkanie"

User: "Co jadłem w tym tygodniu?"
        ↓
    [Agent] → get_spending → [Orchestrator] → "W tym tygodniu kupiłeś..."
```

**Components:**
- `tools.py` - Tool definitions (12 tools), Pydantic argument models, validation
- `router.py` - AgentRouter class: LLM call with retry, tool dispatch, logging
- `validator.py` - Input sanitization, prompt injection detection (low/medium/high risk)
- `app/chat/agent_executor.py` - Tool executors connecting to notes/bookmarks/RSS APIs

**Available tools:** `create_note`, `search_knowledge`, `search_web`, `get_spending`, `get_inventory`, `get_weather`, `summarize_url`, `list_recent`, `create_bookmark`, `answer_directly`, `ask_clarification`, `organize_notes`

**Usage (standalone):**
```python
from app.agent.router import create_agent_router

router = create_agent_router()
router.register_executor("create_note", my_note_handler)
response = await router.process("Zapisz notatkę: jutro spotkanie o 10")
# response.tool = "create_note", response.arguments = {"title": "...", "content": "..."}
```

**Multi-tool chains**: Agent supports chaining up to 3 action tools (`MAX_TOOLS_IN_CHAIN`). LLM returns Format B with `"tools": [...]` array. `execute_tool_chain()` runs tools sequentially, passing context via `ToolChainContext`. `_inject_chain_context()` maps outputs between tools (e.g., `summarize_url` → `create_note`: summary → content). Only `ACTION_TOOLS` can chain; `ORCHESTRATOR_TOOLS` break the chain and delegate to orchestrator.

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

# Authentication (optional)
AUTH_TOKEN=                           # Set to enable API/Web auth (empty = no auth)

# Feature flags
USE_DB_DICTIONARIES=true
USE_DB_RECEIPTS=true
GENERATE_OBSIDIAN_FILES=true          # Global: notes, bookmarks, transcriptions, summaries
GENERATE_RECEIPT_OBSIDIAN=false       # Separate flag for receipt markdown (independent of above)
RAG_ENABLED=true
CHAT_ENABLED=true
CHAT_AGENT_ENABLED=true              # Agent tool-calling in chat (auto-detect actions)
AGENT_CONFIDENCE_THRESHOLD=0.6       # Auto-fallback to ask_clarification below this
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

# Transcription
WHISPER_MODEL=medium                  # tiny, base, small, medium, large-v3
WHISPER_DEVICE=cuda                   # cuda, cpu, auto
WHISPER_COMPUTE_TYPE=float16          # float16, int8, int8_float16
VOICE_NOTE_PROCESS_INTERVAL_MINUTES=30  # Voice memo batch interval (avoids VRAM conflict)

# Map-reduce for long transcriptions
MAPREDUCE_ENABLED=true
MAPREDUCE_THRESHOLD=15000             # chars threshold
MAPREDUCE_CHUNK_SIZE=10000
MAPREDUCE_OVERLAP=1000
MAPREDUCE_MAX_CHUNKS=30

# RAG
RAG_TOP_K=5
RAG_CHUNK_SIZE=1500
RAG_CHUNK_OVERLAP=200
RAG_MIN_SCORE=0.3
RAG_AUTO_INDEX=true

# Web search (SearXNG)
WEB_SEARCH_NUM_RESULTS=6              # Results per search query
WEB_SEARCH_EXPAND_NEWS=false          # Expand news categories in search

# Receipt batching (group receipts to minimize model switches)
RECEIPT_BATCH_ENABLED=false
RECEIPT_BATCH_MAX_WAIT_SEC=30
RECEIPT_BATCH_MAX_SIZE=5

# Push notifications (Web Push API for PWA)
PUSH_ENABLED=false
PUSH_VAPID_PUBLIC_KEY=                # Generate with scripts/generate_vapid_keys.py
PUSH_VAPID_PRIVATE_KEY=
PUSH_VAPID_SUBJECT=mailto:admin@localhost

# Weather (for agent get_weather tool)
OPENWEATHER_API_KEY=
WEATHER_CITY=Kraków
WEATHER_UNITS=metric

# Database pool
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10

# Base URL for notification links
BASE_URL=http://localhost:8000
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

HTMX + Jinja2 templates at `http://localhost:8000/app/`. Templates in `app/templates/` organized by feature with `partials/` subdirectories for HTMX partial responses. Toast notifications via HX-Trigger headers. Static JS libs: `htmx.min.js`, `marked.min.js` (markdown), `purify.min.js` (XSS sanitization). Command palette (Ctrl+K) for global search and navigation via `command-palette.js`.

Web UI routes are split into 14 feature modules in `app/web/` (imported as composite router in `app/web/__init__.py`, registered in `main.py` as `from app.web import router as web_router`).

### Mobile PWA (`app/mobile_routes.py`)

Chat-centric mobile interface at `/m/` with offline support:
- `/m/` - Chat interface (main mobile view)
- `/m/notatki` - Notes browser, `/m/notatki/{id}` - Note detail
- `/m/paragony` - Receipts browser, `/m/paragony/{id}` - Receipt detail
- `/m/wiedza` - Knowledge base (bookmarks + RAG search)
- `/m/share` - Web Share Target API (share images/text from other apps)
- Service worker (`app/static/sw.js`) with offline caching and request queue (`app/static/js/offline-queue.js`)
- PWA installable via `manifest.json` with shortcuts (camera, note, voice)
- Templates in `app/templates/mobile/` with separate `base.html`

### Push Notifications (`app/push/`)

Web Push API via `pywebpush` with VAPID key authentication:
- `app/push_api.py` - Subscribe/unsubscribe endpoints at `/api/push/*`
- `app/services/push_service.py` - Notification sender hooked into content creation flows
- `app/push/hooks.py` - Auto-notify on new content
- Generate VAPID keys: `python scripts/generate_vapid_keys.py`
- Config: `PUSH_ENABLED`, `PUSH_VAPID_PUBLIC_KEY`, `PUSH_VAPID_PRIVATE_KEY`, `PUSH_VAPID_SUBJECT`

## Output Files

Output goes to Obsidian vault (paths via `docker-compose.override.yml`):

| Content | Container Path | Obsidian Path (production) |
|---------|---------------|---------------------------|
| Receipts | `/data/vault/paragony/*.md` | `2brain/zakupy/paragony/` |
| Pantry view | `/data/vault/spiżarnia.md` | `2brain/zakupy/` |
| Logs | `/data/vault/logs/` | `2brain/zakupy/logs/` |
| **Notes** | `/data/notes/*.md` | `2brain/0-inbox/` |
| Bookmarks | `/data/vault/bookmarks/` | `2brain/zakupy/bookmarks/` |
| Transcriptions | `/data/vault/transcriptions/` | `2brain/zakupy/transcriptions/` |
| Transcription index | `/data/vault/transcriptions/index.md` | Map of Content (categorized) |
| RSS summaries | `/data/summaries/*.md` | `2brain/artykuly/` |
| Daily notes | `/data/vault/daily/*.md` | `2brain/zakupy/daily/` (voice memos) |

## Database

PostgreSQL 16 with `pg_trgm` (fuzzy text) and `pgvector` (embeddings) extensions. Schema in `scripts/init-db.sql`, ORM in `app/db/models.py` (25 models), migrations in `alembic/versions/` (10 versions).

Set all feature flags to `false` to revert to file-only mode (no database).

### Key Models

| Model | Table | Purpose |
|-------|-------|---------|
| Receipt, ReceiptItem | receipts, receipt_items | OCR'd receipt data |
| Product, ProductVariant | products, product_variants | Product dictionary |
| ProductShortcut | product_shortcuts | Store-specific abbreviations |
| PantryItem | pantry_items | Food inventory |
| Store, StoreAlias | stores, store_aliases | Store normalization |
| PriceHistory | price_history | Price trends |
| Category | categories | Product categories |
| UnmatchedProduct | unmatched_products | Learning system |
| ReviewCorrection | review_corrections | Human-in-the-loop |
| RssFeed, Article, ArticleSummary | rss_feeds, articles, article_summaries | RSS pipeline |
| TranscriptionJob, Transcription, TranscriptionNote | transcription_* | Audio/video pipeline |
| Note | notes | Personal notes |
| Bookmark | bookmarks | Read-later links |
| DocumentEmbedding | document_embeddings | RAG vectors (pgvector) |
| ChatSession, ChatMessage | chat_sessions, chat_messages | Chat history |
| AgentCallLog | agent_call_logs | Agent analytics + security |
| UserProfile | user_profiles | Per-user preferences |
| PushSubscription | push_subscriptions | Web Push API |

## Security

**Authentication** (`app/auth.py`): Optional, controlled by `AUTH_TOKEN` env var. When set:
- API: `Authorization: Bearer <token>` header
- Web UI: session cookies (8h expiry) with `/login` and `/logout` routes
- Public paths bypassing auth: `/health`, `/docs`, `/metrics`, `/login`, `/logout`, `/sw.js`, `/manifest.json`

**Rate limiting**: `slowapi` on login (5/min), receipt upload (10/min), chat (20/min), push test (3/min).

**Security headers middleware** (`app/main.py`): CSP, X-Frame-Options, X-Content-Type-Options, Strict-Transport-Security, Referrer-Policy.

**SSRF protection** (`app/url_validator.py`): URL validation blocks private IP ranges for web scraper/RSS fetcher.

**Agent input validation** (`app/agent/validator.py`): Prompt injection detection with low/medium/high risk classification. Logs suspicious inputs to `agent_call_logs`.

**Known issues** (see `PROJECT_AUDIT.md`):
- **SEC-002**: SQL injection via f-string in `app/db/repositories/embeddings.py` (use parameterized queries)
- **SEC-003**: Path traversal in file uploads (sanitize with `PurePosixPath(filename).name`)

**Mitigating factor:** Docker Compose binds ports to `127.0.0.1` only, limiting exposure to localhost.

When adding new endpoints: use parameterized queries, sanitize user-provided filenames, validate external URLs, apply `verify_api_token` or `verify_web_session` dependencies.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/init-db.sql` | PostgreSQL schema (initial setup) |
| `scripts/migrate_data.py` | JSON → PostgreSQL migration |
| `scripts/generate_vapid_keys.py` | Web Push VAPID key generator |
| `scripts/setup_cloudflare.sh` | Cloudflare Tunnel setup |
| `scripts/test_agent_tools.py` | Agent tool-calling tests (35 test cases) |
| `scripts/test_agent_security.py` | Prompt injection tests (60+ tests) |
| `scripts/test_mobile_pwa.sh` | Mobile PWA smoke tests |
| `scripts/quick_ocr.py` | Standalone OCR test utility |
| `scripts/receipt_ocr.py` | Standalone receipt OCR utility |

## Extending the Codebase

### Adding a New API Module

Follow the existing module pattern:
1. Create repository in `app/db/repositories/` (extend `BaseRepository`)
2. Add ORM model to `app/db/models.py`, create Alembic migration
3. Create API router as `app/<module>_api.py` with FastAPI `APIRouter`
4. Add dependency alias to `app/dependencies.py` (typed `Annotated` alias)
5. Register router in `app/main.py`
6. Optionally: add Obsidian writer in `app/writers/`, Web UI route in `app/web/`, RAG auto-indexing hook

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

### Adding a New Web UI Module

1. Create `app/web/<module>.py` with `router = APIRouter()`
2. Add HTMX templates in `app/templates/<module>/` (with `partials/` subdirectory)
3. Import and include router in `app/web/__init__.py`
4. Use shared helpers from `app/web/helpers.py` (templates, emojis, _htmx_trigger)
