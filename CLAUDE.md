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
curl -X POST http://localhost:8000/process-receipt -F "file=@receipt.png"

# Database shell
docker exec -it pantry-db psql -U pantry -d pantry
```

### Local Development (without Docker)

```bash
pip install -r requirements.txt
OLLAMA_BASE_URL=http://localhost:11434 uvicorn app.main:app --reload
```

No automated tests exist. Testing is manual via API calls and Telegram bot.

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

**Human-in-the-loop review** triggers when extracted total vs product sum differs by >5 PLN AND >10%. User approves, corrects total, or rejects via Telegram inline keyboard.

**Multi-page PDF**: Pages processed in parallel (`PDF_MAX_PARALLEL_PAGES`), products combined, per-page verification skipped (would corrupt partial totals).

### Module Architecture

Each module follows a consistent pattern:
- **API router** (`app/*_api.py`) - FastAPI endpoints
- **Database models** (`app/db/models.py`) - SQLAlchemy ORM
- **Repository** (`app/db/repositories/*.py`) - Data access layer
- **Writer** (`app/*_writer.py`) - Obsidian markdown generation
- **Telegram handler** (`app/telegram/handlers/*.py`) - Bot commands
- **Telegram menu** (`app/telegram/handlers/menu_*.py`) - Inline keyboard navigation

Modules: receipts, RSS/summarizer, transcription, notes, bookmarks, RAG (/ask), chat, analytics, dictionary, search.

### Key Design Patterns

**Repository pattern** with FastAPI dependency injection:
```python
from app.dependencies import ProductRepoDep
@router.get("/products")
async def list_products(repo: ProductRepoDep):
    return await repo.list_all()
```

**Telegram callback router** (`app/telegram/callback_router.py`): Prefix-based routing instead of monolithic if/elif. Handlers registered by prefix (e.g., `"receipts:"`, `"notes:"`).

**RAG auto-indexing** (`app/rag/hooks.py`): Fire-and-forget hooks in notes_api, bookmarks_api, rss_api, transcription_api auto-index new content for `/ask` queries. If embeddings table is empty on startup, triggers background `reindex_all()`.

**Chat AI intent classification** (`app/chat/intent_classifier.py`): LLM classifies each message as `"rag"` (personal data), `"web"` (internet search via SearXNG), `"both"`, or `"direct"` (no search needed).

**Language detection**: Multiple modules auto-detect Polish vs English based on Polish characters (ą,ć,ę...) and keyword matching. Polish → Bielik 11B model, English → qwen2.5:7b.

### Product Normalization Chain (`app/dictionaries/`)

1. **Exact match** → `products.json` raw_names
2. **Partial match** → 70%+ word overlap
3. **Shortcut match** → `product_shortcuts.json` (thermal printer abbreviations per store)
4. **Fuzzy match** → Levenshtein distance < 0.75
5. **Keyword match** → Category keywords

### Transcription Map-Reduce (`app/transcription/extractor.py`)

For transcriptions > 15k chars: split into 10k char chunks at sentence boundaries with 1k overlap → MAP phase extracts from each chunk → REDUCE phase deduplicates and synthesizes. Configurable via `MAPREDUCE_*` env vars.

### Store-Specific OCR Prompts (`app/store_prompts.py`)

Each store (Biedronka, Lidl, Kaufland, Żabka, etc.) has a tailored extraction prompt matching its receipt format. To add a new store:
1. Add detection patterns to `STORE_PATTERNS`
2. Create `PROMPT_STORENAME` with format-specific instructions
3. Add to `STORE_PROMPTS` mapping

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

# Feature flags
USE_DB_DICTIONARIES=true
USE_DB_RECEIPTS=true
GENERATE_OBSIDIAN_FILES=true
RAG_ENABLED=true
CHAT_ENABLED=true
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
```

### Ollama Models Required

```bash
ollama pull qwen2.5:7b        # Structuring + categorization (4.7GB)
ollama pull qwen2.5vl:7b      # Vision OCR fallback (6GB)
ollama pull nomic-embed-text   # RAG embeddings (274MB)
# For Polish content:
ollama pull SpeakLeash/bielik-11b-v3.0-instruct:Q5_K_M  # Chat + summaries (7GB)
```

## Web UI

HTMX + Jinja2 templates at `http://localhost:8000/app/`. Templates in `app/templates/` organized by feature with `partials/` subdirectories for HTMX partial responses. Toast notifications via HX-Trigger headers.

## Output Files

- `vault/paragony/*.md` - Receipt markdown with YAML frontmatter
- `vault/spiżarnia.md` - Aggregated pantry view
- `vault/logs/` - Error log, unmatched products JSON, corrections JSON
- Feature-specific output dirs configured via `*_OUTPUT_DIR` env vars

## Database

PostgreSQL 16 with `pg_trgm` (fuzzy text) and `pgvector` (embeddings) extensions. Schema in `scripts/init-db.sql`, ORM in `app/db/models.py`, migrations in `alembic/versions/`.

Set all feature flags to `false` to revert to file-only mode (no database).
