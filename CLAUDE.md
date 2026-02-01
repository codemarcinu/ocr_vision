# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart Pantry Tracker - OCR receipt processing system using Ollama LLMs for product extraction and categorization, with **PostgreSQL database** for data persistence and analytics. Outputs to Obsidian markdown files. Includes a Telegram bot for mobile interaction with **human-in-the-loop validation**.

## Build & Run Commands

```bash
# Start the service (FastAPI + Telegram bot)
docker-compose up -d

# Rebuild after code changes
docker-compose up -d --build

# View logs (live)
docker logs -f pantry-api

# Test API health
curl http://localhost:8000/health

# Process a receipt via API (supports PNG, JPG, JPEG, WEBP, PDF)
curl -X POST http://localhost:8000/process-receipt -F "file=@receipt.png"

# Reprocess failed receipt
curl -X POST http://localhost:8000/reprocess/filename.png
```

### Local Development (without Docker)

```bash
# Ollama must be running locally on port 11434
pip install -r requirements.txt
OLLAMA_BASE_URL=http://localhost:11434 uvicorn app.main:app --reload
```

## Architecture

### Processing Pipeline

```
Receipt (photo/PDF) → OCR → Validation → [Review?] → Categorization → Save
                              ↓
                    Total mismatch > 5zł or > 10%?
                           /              \
                         YES              NO
                          ↓                ↓
                   Telegram Review    Auto-save
```

1. **`app/main.py`** - FastAPI endpoints receive image/PDF uploads, parallel PDF processing
2. **`app/pdf_converter.py`** - Converts PDF to PNG images (one per page) using pdf2image
3. **`app/ocr.py`** / **`app/paddle_ocr.py`** / **`app/deepseek_ocr.py`** - OCR extraction backends
4. **`app/ollama_client.py`** - Shared HTTP client with connection pooling for all Ollama API calls
5. **`app/store_prompts.py`** - Store-specific LLM prompts for accurate extraction
6. **`app/price_fixer.py`** - Post-processor: detects suspicious prices (unit price vs final)
7. **`app/dictionaries/`** - Product/store name normalization using fuzzy matching (Levenshtein distance)
8. **`app/db/`** - PostgreSQL database layer with SQLAlchemy async ORM
9. **`app/classifier.py`** - Calls `qwen2.5:7b` via Ollama to categorize products
10. **`app/obsidian_writer.py`** - Generates markdown files for Obsidian vault
11. **`app/services/obsidian_sync.py`** - Regenerates vault from database

Data flow: `paragony/inbox/` → OCR → **Store Detection** → **Store-specific Prompt** → LLM → **Price Fixer** → validation → normalization → categorization → **PostgreSQL** + `vault/`

### Vision OCR Pipeline (`app/ocr.py`)

The vision backend uses `qwen2.5vl:7b` with multi-stage processing:

```
Image → Primary Extraction → Build Receipt → Check Totals
                                                  ↓
                                    Mismatch > 5 PLN AND > 10%?
                                         /              \
                                       YES              NO
                                        ↓                ↓
                               Self-Verification    Return Receipt
                                        ↓
                          Model re-analyzes with context
                                        ↓
                              Return corrected data
```

**Key features:**

1. **Primary Extraction** - Single-pass with enhanced prompt:
   - Explicit FINAL price instructions (after discounts)
   - Biedronka format: "LAST number in block = price"
   - Weighted products: "IGNORE unit price per kg"

2. **Two-Stage Fallback** - If primary finds < 2 products:
   - Stage 1: Extract raw text (`OCR_RAW_TEXT_PROMPT`)
   - Stage 2: Parse text to JSON using `qwen2.5:7b` text model
   - Skip if < 150 chars (summary page detection)

3. **Text-Only Verification** - If totals don't match:
   - Uses `qwen2.5:7b` text model (not vision) to avoid VRAM issues
   - Shows model the raw OCR text + its extraction + discrepancy
   - Asks to verify and correct mistakes
   - Uses result only if it improves the match

4. **Price Fixer Post-Processing** (`app/price_fixer.py`):
   - Detects weighted products (kg) with suspiciously high prices
   - Flags potential unit prices (per kg) instead of final prices
   - Adds warnings to products, doesn't modify prices
   - Thresholds: 40 PLN (general), 60 PLN (meat), 80 PLN (premium)

5. **Product Filtering**:
   - Skip generic names: `product1`, `item2`
   - Skip short names: < 4 characters
   - Skip summary lines: `GOTÓWKA`, `RESZTA`, `PTU`, etc.
   - Skip suspicious prices: > 40 PLN with unusual cents

**Ollama options for vision:**
```python
options = {
    "temperature": 0.1,
    "top_p": 0.8,
    "top_k": 20,
    "num_predict": 4096,
    "num_ctx": 4096,  # REQUIRED for images
}
```

### Store-Specific Prompts (`app/store_prompts.py`)

Different stores have different receipt formats. The system detects the store from OCR text and uses a tailored prompt:

| Store | Format characteristics |
|-------|----------------------|
| **Biedronka** | `Product PTU Qty×Price Value` then `Rabat -X.XX` then `FinalPrice` |
| **Lidl** | Product name in separate line, then `Qty × Price = Value` |
| **Kaufland** | `PRODUCT NAME` (uppercase), price on right, rabat below |
| **Żabka** | Simple format: `Product Price` in one line |
| **Auchan** | Product name separate, details below with VAT% |
| **Carrefour** | Product + price in one line, rabat as separate line |
| **Netto** | Simple format similar to Żabka |
| **Dino** | Uppercase names, standard Polish format |

**Adding new store:**
1. Add detection patterns to `STORE_PATTERNS` dict
2. Create `PROMPT_STORENAME` with format-specific instructions
3. Add to `STORE_PROMPTS` mapping

**Key prompt elements:**
- Exact format description with examples
- How to identify final price (after discounts)
- What to ignore (VAT, PTU, deposits)
- Expected JSON output format

### Multi-page PDF Processing

For PDFs with multiple pages (e.g., long receipts):
1. Pages are converted to PNG images
2. **Parallel processing**: Pages are OCR'd concurrently (controlled by `PDF_MAX_PARALLEL_PAGES`)
3. **Per-page verification is SKIPPED** (to prevent corrupting totals with partial page sums)
4. Products from all pages are **combined** into a single Receipt
5. **Total extraction priority**:
   - Try regex extraction from combined raw text (for paddle backend)
   - Fall back to suma from last page (for vision backend)
   - Fall back to calculated sum of all products
6. Total is validated against sum of all products
7. Temp images are cleaned up after processing

**Performance**: With `PDF_MAX_PARALLEL_PAGES=2`, a 3-page PDF processes in ~2.5 min instead of ~4.5 min.

**Important**: Per-page verification is disabled for multi-page PDFs because each page only contains partial products. Verification would "fix" the total to the partial sum, which is incorrect.

### Human-in-the-Loop Validation

The system automatically flags receipts for human review when:

| Condition | Threshold | Example |
|-----------|-----------|---------|
| Absolute difference | > 5 PLN | OCR: 84.50, Products: 144.48 → Review |
| Percentage difference | > 10% | OCR: 100.00, Products: 88.00 → Review |

**Review flow (Telegram):**
- User receives message with extracted data and inline keyboard
- Options: **Zatwierdź** (approve as-is), **Popraw sumę** (correct total), **Odrzuć** (reject)
- "Popraw sumę" offers: use calculated total from products, or enter manually
- Only after approval is the receipt saved to vault

**Relevant files:**
- `app/models.py` - `Receipt.needs_review`, `Receipt.review_reasons`, `Receipt.calculated_total`
- `app/telegram/keyboards.py` - `get_review_keyboard()`, `get_total_correction_keyboard()`
- `app/telegram/formatters.py` - `format_review_receipt()`
- `app/telegram/bot.py` - `_handle_review_callback()`, `_handle_text_input()`

### Product Normalization (`app/dictionaries/`)

Dictionary-based matching with fallback chain:
1. **Exact match** - Product name in `products.json` raw_names (confidence: 0.99)
2. **Partial match** - 70%+ word overlap (confidence: 0.7-0.9)
3. **Shortcut match** - Store-specific abbreviations from `product_shortcuts.json` (confidence: 0.88-0.95)
4. **Fuzzy match** - Levenshtein distance < 0.75 threshold (confidence: 0.68-0.81)
5. **Keyword match** - Category keywords like "mleko", "chleb" (confidence: 0.6)

Files: `app/dictionaries/products.json`, `app/dictionaries/stores.json`, `app/dictionaries/product_shortcuts.json`

### Product Shortcuts (`app/dictionaries/product_shortcuts.json`)

Store-specific abbreviation mappings for thermal printer shortcuts (e.g., Biedronka):
- `"mroznkr"` → `"mrożonka krakowska"`
- `"kalafks"` → `"kalafior"`
- `"serekasztlan"` → `"ser kasztelan"`

Shortcuts are checked after partial match but before fuzzy match. Store name must be passed to `normalize_product()`.

**Adding new shortcuts:**
```bash
curl -X POST http://localhost:8000/dictionary/shortcuts/add \
  -H "Content-Type: application/json" \
  -d '{"shortcut": "MroznKr", "full_name": "mrożonka krakowska", "store": "biedronka"}'
```

### Feedback Loop (`app/feedback_logger.py`)

System learns from OCR corrections and unmatched products:

**Unmatched products** (`vault/logs/unmatched.json`):
- Products that failed to match any dictionary entry are logged
- Tracks count, first_seen, last_seen, store, price
- Products with count >= 3 are suggested for learning

**Review corrections** (`vault/logs/corrections.json`):
- Logs all receipt review actions (approved, calculated, manual)
- Tracks original vs corrected totals, store, product count
- Used for analyzing OCR accuracy patterns

**Relevant endpoints:**
- `GET /dictionary/unmatched` - All unmatched products (sorted by count)
- `GET /dictionary/unmatched/suggestions` - Products with count >= 3
- `GET /dictionary/corrections/stats` - Correction statistics
- `POST /dictionary/learn/{raw_name}` - Learn product and remove from unmatched

### Discount Extraction (`app/receipt_parser.py`)

Enhanced discount handling:

| Pattern | Example | Type |
|---------|---------|------|
| Keyword + amount | `Rabat -3.29` | kwotowy |
| Plain negative | `-3.29` | kwotowy |
| Percentage | `Promocja -30%` | procentowy |
| Just percentage | `-30%` | procentowy |

**Supported keywords:** Rabat, Promocja, Zniżka, Upust

**Multiple discounts:** Products can have multiple discounts (e.g., Rabat + Promocja), stored in `rabaty_szczegoly` field.

```python
class Product(BaseModel):
    rabat: Optional[float]  # Total discount amount
    rabaty_szczegoly: Optional[list[DiscountDetail]]  # Detailed breakdown
    # DiscountDetail: {typ: "kwotowy"|"procentowy", wartosc: float, opis: str}
```

### Telegram Bot (`app/telegram/`)

- **`bot.py`** - Main bot orchestrator with `PantryBot` class, starts/stops with FastAPI lifespan
  - `_handle_review_callback()` - Human-in-the-loop review actions
  - `_handle_text_input()` - Manual total entry handler
- **`middleware.py`** - Authorization decorator (`@authorized_only`) checks `TELEGRAM_CHAT_ID`
- **`keyboards.py`** - Inline keyboard builders for UI
  - `get_review_keyboard()` - Approve/Edit/Reject buttons
  - `get_total_correction_keyboard()` - Total correction options
- **`formatters.py`** - Message formatting utilities
  - `format_review_receipt()` - Format receipt for human review with warnings
- **`notifications.py`** - Scheduled notifications with APScheduler
  - Daily digest at 9:00 AM with pending files, unmatched products, weekly stats
  - `start_scheduler(bot)` / `stop_scheduler()` for lifecycle management
- **`handlers/`** - Command handlers:
  - `receipts.py` - Photo/PDF processing with review flow, `/recent`, `/reprocess`, `/pending`
  - `pantry.py` - `/pantry`, `/use`, `/remove`, `/search`
  - `stats.py` - `/stats`, `/stores`, `/categories`, `/rabaty` (alias: `/discounts`)
  - `errors.py` - `/errors`, `/clearerrors`
  - `json_import.py` - Import receipts from JSON text (paste structured JSON into chat)

**All Telegram commands:**
| Command | Description |
|---------|-------------|
| `/start`, `/help` | Show help message |
| `/recent [N]` | Last N receipts (default: 5) |
| `/reprocess <file>` | Reprocess failed receipt |
| `/pending` | Files waiting in inbox |
| `/pantry [category]` | View pantry contents |
| `/use <product>` | Mark product as consumed |
| `/remove <product>` | Remove from pantry |
| `/search <query>` | Search products |
| `/stats [week/month]` | Spending statistics |
| `/stores` | Spending by store |
| `/categories` | Spending by category |
| `/rabaty`, `/discounts` | Discount report |
| `/errors` | OCR error log |
| `/clearerrors` | Clear error log |

### JSON Import via Telegram

Send JSON directly to the bot to import pre-structured receipts:

```json
{
  "transakcja": {
    "sklep": "Biedronka, ul. Przykładowa 1",
    "data_godzina": "2026-01-31 14:30",
    "suma_calkowita": 45.99
  },
  "produkty": [
    {
      "nazwa_oryginalna": "MLEKO 3.2%",
      "nazwa_znormalizowana": "mleko",
      "kategoria": "Nabiał",
      "cena_koncowa": 4.99,
      "rabat": -0.50
    }
  ]
}
```

### Web UI (`app/web/`)

- **`dictionary.html`** - Single-page web app for dictionary management
  - Access via: `http://localhost:8000/web/dictionary`
  - Tabs: Unmatched products, Dictionary browser, Shortcuts management
  - Features: Learn products, add shortcuts, browse by category

## Key Configuration

- `app/config.py` - All settings with env var overrides via `Settings` class
- `app/models.py` - Pydantic models: `Receipt`, `Product`, `ProcessingResult`, `HealthStatus`
- Container paths: `/data/paragony/` and `/data/vault/` (mounted from `./paragony` and `./vault`)
- Ollama runs on host machine, accessed via `host.docker.internal:11434`

### Data Models (`app/models.py`)

```python
class Receipt(BaseModel):
    products: list[Product]
    sklep: Optional[str]           # Store name
    data: Optional[str]            # Date (YYYY-MM-DD)
    suma: Optional[float]          # Total from OCR
    raw_text: Optional[str]        # Raw OCR text for debugging
    # Validation fields
    needs_review: bool = False     # Flag for human review
    review_reasons: list[str]      # Why review is needed
    calculated_total: Optional[float]  # Sum of product prices

class Product(BaseModel):
    nazwa: str                     # Product name
    cena: float                    # Final price (after discount)
    kategoria: Optional[str]       # Category
    confidence: Optional[float]    # OCR confidence
    warning: Optional[str]         # Price warning
    nazwa_oryginalna: Optional[str]      # Original OCR name
    nazwa_znormalizowana: Optional[str]  # Normalized name
    cena_oryginalna: Optional[float]     # Price before discount
    rabat: Optional[float]               # Total discount amount
    rabaty_szczegoly: Optional[list[DiscountDetail]]  # Detailed discounts

class DiscountDetail(BaseModel):
    typ: str        # "kwotowy" or "procentowy"
    wartosc: float  # Amount in PLN or percentage
    opis: str       # "Rabat", "Promocja", "Zniżka", "Upust"
```

### Environment Variables

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434  # Ollama API
OCR_MODEL=deepseek-ocr                              # Vision model for OCR (deepseek-ocr recommended)
OCR_BACKEND=deepseek                                # "deepseek" (recommended), "vision", or "paddle"
OCR_FALLBACK_MODEL=qwen2.5vl:7b                     # Fallback vision model when DeepSeek-OCR fails
STRUCTURING_MODEL=qwen2.5:7b                        # LLM for JSON structuring (deepseek backend)
CLASSIFIER_MODEL=qwen2.5:7b                         # Categorization model (primary)
CLASSIFIER_MODEL_B=gpt-oss:20b                      # A/B test model (optional)
CLASSIFIER_AB_MODE=primary                          # "primary", "secondary", or "both"
TELEGRAM_BOT_TOKEN=xxx                              # From .env file
TELEGRAM_CHAT_ID=123456                             # Authorized user ID (0 = allow all)
BOT_ENABLED=true                                    # Enable/disable Telegram bot

# PostgreSQL Database
DATABASE_URL=postgresql+asyncpg://pantry:pantry123@postgres:5432/pantry
DATABASE_POOL_SIZE=5                                # Connection pool size
DATABASE_MAX_OVERFLOW=10                            # Max overflow connections
USE_DB_DICTIONARIES=true                            # Use DB for product/store dictionaries
USE_DB_RECEIPTS=true                                # Store receipts in DB
GENERATE_OBSIDIAN_FILES=true                        # Generate markdown files alongside DB

# Performance tuning
VISION_MODEL_KEEP_ALIVE=10m                         # How long vision model stays in VRAM (default: 10m)
TEXT_MODEL_KEEP_ALIVE=30m                           # How long text model stays in VRAM (default: 30m)
UNLOAD_MODELS_AFTER_USE=false                       # Force unload after each use (for low VRAM)
PDF_MAX_PARALLEL_PAGES=2                            # Concurrent pages for multi-page PDF
```

## Ollama Models Required

```bash
# Recommended (deepseek pipeline - fastest + accurate)
ollama pull deepseek-ocr    # Fast OCR extraction (6.7GB)
ollama pull qwen2.5:7b      # Structuring + categorization (4.7GB)
ollama pull qwen2.5vl:7b    # Fallback for when DeepSeek-OCR fails (6GB)

# Alternative (vision backend - slower but single model)
ollama pull qwen2.5vl:7b    # OCR extraction (6GB, requires num_ctx=4096)
```

Models stay loaded in VRAM for faster subsequent requests (vision: 10m, text: 30m by default). Set `UNLOAD_MODELS_AFTER_USE=true` for low VRAM systems.

### OCR Backend Comparison

| Backend | Speed | Accuracy | Notes |
|---------|-------|----------|-------|
| **`deepseek`** (DeepSeek-OCR + LLM) | **~15s** | **Best** | **Recommended.** Fast + accurate. Combined structuring + categorization. Has fallback if loops |
| `vision` (qwen2.5vl:7b) | ~4 min | Best | Single model, slower but accurate |
| `paddle` (PaddleOCR + LLM) | ~11s | Good | Fastest but less accurate for complex receipts |

Set via `OCR_BACKEND=deepseek` (recommended), `OCR_BACKEND=vision`, or `OCR_BACKEND=paddle` in docker-compose.yml.

### DeepSeek Pipeline (OCR_BACKEND=deepseek)

The `deepseek` backend uses a two-model pipeline for optimal speed and accuracy:

```
Image → DeepSeek-OCR (~6-10s) → Raw Text → qwen2.5:7b (~7s) → JSON + Categories
                                    ↓
                         Preserve layout prompt
                         (keeps prices with products)
```

**Configuration:**
```bash
OCR_MODEL=deepseek-ocr          # Fast vision model for text extraction
OCR_BACKEND=deepseek            # Enable deepseek pipeline
STRUCTURING_MODEL=qwen2.5:7b    # LLM for JSON structuring (optional, defaults to CLASSIFIER_MODEL)
OCR_FALLBACK_MODEL=qwen2.5vl:7b # Fallback when DeepSeek-OCR fails (default: qwen2.5vl:7b)
```

**Key features:**
- Uses `/api/chat` endpoint for DeepSeek-OCR (not `/api/generate`)
- "Preserve layout" prompt keeps product names and prices together
- **Combined structuring + categorization** in single LLM call (saves ~7s)
- **Connection pooling** via `ollama_client.py` (saves ~100ms per request)
- Output limited with `num_predict=2048` to prevent infinite loops
- Automatic **fallback to vision backend** when DeepSeek-OCR fails (loops, timeout)

**Performance comparison:**
| Pipeline | Time | Notes |
|----------|------|-------|
| DeepSeek-OCR + qwen2.5:7b | **13-17s** | Recommended (optimized with combined structuring + categorization) |
| DeepSeek-OCR + gpt-oss | 95s | More accurate but much slower |
| qwen3-vl:8b (single model) | 80s | Slower, thinking mode issues |

### Vision Model Notes (OCR_BACKEND=vision)

| Model | Size | Status | Notes |
|-------|------|--------|-------|
| **`qwen2.5vl:7b`** | 6.0GB | **Best** | Default. 3/3 success, requires num_ctx=4096. 76% GPU + 24% CPU offload on 12GB |
| `qwen2.5vl:3b` | 3.2GB | Partial | Niestabilny, błędy GGML na niektórych obrazach |
| `llama3.2-vision` | 7.8GB | Partial | 2/3 success, może odmówić przetwarzania |
| `qwen3-vl:8b` | 6.1GB | Avoid | Thinking mode - odpowiedź w polu `thinking` zamiast `content` (obsługa dodana w app/ocr.py) |
| `minicpm-v` | 5.5GB | Fallback | Działa, ale mniej dokładny niż qwen2.5vl |
| `deepseek-ocr` | 6.7GB | Issues | Ollama 0.15+: czasami zwraca puste odpowiedzi dla obrazów, fallback do qwen2.5vl:7b |

### Classifier A/B Testing

Compare classifier models (e.g., `qwen2.5:7b` vs `gpt-oss:20b`) to evaluate accuracy and performance.

**Configuration:**
```bash
CLASSIFIER_MODEL=qwen2.5:7b      # Primary model (always available)
CLASSIFIER_MODEL_B=gpt-oss:20b   # Secondary model for A/B testing
CLASSIFIER_AB_MODE=primary       # Testing mode (see below)
```

**Modes:**
| Mode | Behavior | Use case |
|------|----------|----------|
| `primary` | Use model A, also run B in background and log comparison | Production with logging |
| `secondary` | Use model B as primary | Switch to new model |
| `both` | Run both, use A, log comparison | Full comparison testing |

**Results:**
- Logged to `vault/logs/classifier_ab_test.jsonl`
- View via API: `GET /reports/classifier-ab`
- Metrics: agreement rate, timing, error rates

**Example test:**
```bash
# Enable A/B testing
export CLASSIFIER_MODEL_B=gpt-oss:20b
export CLASSIFIER_AB_MODE=both

# Process some receipts, then check results
curl http://localhost:8000/reports/classifier-ab
```

**Note:** `gpt-oss:20b` (13 GB) won't fit alongside vision model on 12 GB GPU. Models will swap, increasing latency. Consider using `CLASSIFIER_AB_MODE=primary` for production.

## Output Files

- `vault/paragony/*.md` - Individual receipt history with YAML frontmatter
- `vault/spiżarnia.md` - Aggregated pantry view with checkboxes by category
- `vault/logs/ocr-errors.md` - Error log
- `vault/logs/unmatched.json` - Products that failed dictionary matching (for learning)
- `vault/logs/corrections.json` - Receipt review corrections history
- `vault/paragony/ERROR_*.md` - Per-receipt error files

## Additional API Endpoints

### Dictionary Management (`/dictionary/*`)
- `GET /dictionary/stats` - Dictionary statistics
- `GET /dictionary/categories` - List categories with product counts
- `GET /dictionary/products?category=&search=` - List/search products
- `POST /dictionary/products/add` - Add product variant
- `GET /dictionary/stores` - List stores with aliases
- `POST /dictionary/stores/add` - Add store alias
- `GET /dictionary/shortcuts?store=` - List product shortcuts
- `POST /dictionary/shortcuts/add` - Add product shortcut
- `DELETE /dictionary/shortcuts/{store}/{shortcut}` - Delete shortcut
- `GET /dictionary/unmatched` - Products that failed to match (sorted by count)
- `GET /dictionary/unmatched/suggestions?min_count=3` - High-frequency unmatched products
- `POST /dictionary/learn/{raw_name}` - Learn from unmatched
- `GET /dictionary/corrections/stats` - Review correction statistics

### Reports (`/reports/*`)
- `GET /reports/summary` - Overall stats (receipts, spending, discounts)
- `GET /reports/discounts` - Discount summary by store/category/month
- `GET /reports/stores` - Spending per store
- `GET /reports/monthly` - Monthly spending breakdown
- `GET /reports/categories` - Spending by category

### Obsidian Sync (`/obsidian/*`) - requires `USE_DB_RECEIPTS=true`
- `POST /obsidian/sync/receipt/{id}` - Regenerate markdown for one receipt
- `POST /obsidian/sync/pantry` - Regenerate spiżarnia.md from database
- `POST /obsidian/sync/all` - Full vault regeneration from database

### Analytics (`/analytics/*`) - requires `USE_DB_RECEIPTS=true`
- `GET /analytics/price-trends/{product_id}?months=6` - Price history
- `GET /analytics/store-comparison?product_ids=1,2,3` - Compare prices across stores
- `GET /analytics/spending/by-category?start=&end=` - Spending by category
- `GET /analytics/spending/by-store?start=&end=` - Spending by store
- `GET /analytics/basket-analysis?min_support=0.1` - Frequently bought together
- `GET /analytics/top-products?limit=20&by=count|spending` - Top products
- `GET /analytics/discounts?start=&end=` - Discount statistics
- `GET /analytics/yearly-comparison` - Year-over-year comparison

### Database Stats (`/db/*`) - requires `USE_DB_RECEIPTS=true`
- `GET /db/receipts/stats` - Receipt statistics
- `GET /db/receipts/pending` - Receipts pending review
- `GET /db/pantry/stats` - Pantry statistics
- `GET /db/feedback/stats` - Unmatched products and corrections stats

### Metrics
- `GET /metrics` - Prometheus metrics (via `prometheus_fastapi_instrumentator`)

### Web Interface
- `GET /web/dictionary` - Dictionary management UI (HTML page)

## Monitoring Stack

Optional Prometheus + Loki + Grafana stack in docker-compose:

```bash
# Access dashboards
http://localhost:3000   # Grafana (admin/pantry123)
http://localhost:9090   # Prometheus
http://localhost:3100   # Loki
```

Logs are collected from Docker containers via Promtail. FastAPI exposes `/metrics` for Prometheus scraping.

## n8n Integration

Optional workflow in `n8n-workflows/folder-watch.json` for automatic processing of files dropped in `paragony/inbox/`.

## Database Setup

### First-time Setup

```bash
# Start services (PostgreSQL + FastAPI)
docker-compose up -d

# Check PostgreSQL is ready
docker exec -it pantry-db psql -U pantry -d pantry -c "\dt"

# Run data migration from JSON/Markdown to PostgreSQL
docker exec -it pantry-api python scripts/migrate_data.py

# Verify migration
curl http://localhost:8000/db/receipts/stats
```

### Database Schema

The database uses PostgreSQL 16 with `pg_trgm` extension for fuzzy text matching.

Key tables:
- `categories` - Product categories
- `stores`, `store_aliases` - Stores with OCR alias matching
- `products`, `product_variants` - Normalized products with raw name variants
- `product_shortcuts` - Store-specific abbreviations (thermal printer)
- `receipts`, `receipt_items` - Receipt data
- `pantry_items` - Current pantry state
- `price_history` - Price tracking for analytics
- `unmatched_products`, `review_corrections` - Feedback loop

Files:
- `scripts/init-db.sql` - Initial schema
- `app/db/models.py` - SQLAlchemy ORM models
- `app/db/repositories/` - Data access layer (repository pattern)
- `app/dependencies.py` - FastAPI dependency injection for repositories

**Repository pattern usage:**
```python
from app.dependencies import ProductRepoDep, ReceiptRepoDep

@router.get("/products")
async def list_products(repo: ProductRepoDep):
    return await repo.list_all()
```

### Alembic Migrations

```bash
# Create new migration
docker exec -it pantry-api alembic revision --autogenerate -m "description"

# Apply migrations
docker exec -it pantry-api alembic upgrade head

# Rollback
docker exec -it pantry-api alembic downgrade -1
```

### Feature Flags

Control database usage via environment variables:
- `USE_DB_DICTIONARIES=true` - Use PostgreSQL for product/store lookup (with pg_trgm fuzzy search)
- `USE_DB_RECEIPTS=true` - Store receipts in database
- `GENERATE_OBSIDIAN_FILES=true` - Also generate markdown files

Set all to `false` to revert to file-only mode.

## Testing

No automated tests currently. Manual testing via:
```bash
# Test full pipeline
curl -X POST http://localhost:8000/process-receipt -F "file=@test_receipt.png"

# Test dictionary normalization (check logs)
docker logs -f pantry-api | grep -i "normalized\|fuzzy\|shortcut\|match"

# Test human-in-the-loop (send receipt via Telegram with mismatched total)
# Bot should show review interface instead of auto-saving

# Test shortcuts
curl http://localhost:8000/dictionary/shortcuts
curl http://localhost:8000/dictionary/shortcuts?store=biedronka

# Test feedback loop
curl http://localhost:8000/dictionary/unmatched
curl http://localhost:8000/dictionary/unmatched/suggestions?min_count=2
curl http://localhost:8000/dictionary/corrections/stats

# Test learning from unmatched
curl -X POST "http://localhost:8000/dictionary/learn/UNKNOWN_PRODUCT?normalized_name=mleko&category=nabiał"

# Check discount details in response
curl -X POST http://localhost:8000/process-receipt -F "file=@receipt.jpg" | jq '.receipt.products[] | select(.rabaty_szczegoly != null)'

# Test database analytics
curl http://localhost:8000/analytics/spending/by-category
curl http://localhost:8000/analytics/top-products?limit=10
curl http://localhost:8000/analytics/price-trends/1?months=3

# Test Obsidian sync
curl -X POST http://localhost:8000/obsidian/sync/all
```

## Troubleshooting

### Multi-page PDF shows wrong total
- Check if "Karta płatnicza" or payment info is on the last page
- System extracts total from combined raw text of all pages
- If still wrong, use Telegram review to correct manually

### Receipt always triggers review
- Check if OCR is extracting total correctly (review `raw_text` in logs)
- Validation thresholds: >5 PLN or >10% variance triggers review
- Consider adjusting thresholds in `main.py` if needed

### Review data expired in Telegram
- Pending review data is stored in `context.user_data`
- Data may expire if bot restarts or after long delay
- Solution: reprocess the receipt with `/reprocess <filename>`

### Vision OCR: Ollama 500 errors during verification
- **Status:** FIXED - Verification now uses text-only model
- **Cause:** Was VRAM exhaustion when re-sending image for verification
- **Solution:** `_verify_extraction()` uses `qwen2.5:7b` text model with raw OCR text

### Vision OCR: Unit prices instead of final prices
- **Status:** FIXED - Lower threshold for weighted products
- **Symptom:** Weighted products (kg) show per-kg price, not total
- **Solution 1:** OCR prompt has ASCII-art examples showing correct price extraction
- **Solution 2:** `price_fixer.py` flags suspicious prices with lower threshold (15 PLN) for weighted products
- **Check logs:** `grep -i "price warning\|Likely unit price" pantry-api`

### Vision OCR: Summary page products
- **Status:** FIXED - Generic names filter
- **Symptom:** Fake products like `product1: 48.16 zł`
- **Cause:** Last page (payment summary) being parsed as products
- **Solution 1:** Summary page detection (< 150 chars) skips these pages
- **Solution 2:** Generic names filter (regex) catches `product\d*`, `item\d*`, etc.

### Vision OCR: Multi-page PDF wrong total
- **Status:** FIXED - Per-page verification disabled
- **Symptom:** Total shows first page sum (e.g., 64.17) instead of full receipt (144.48)
- **Cause:** Was running verification per-page, which "fixed" total to partial sum
- **Solution:** `is_multi_page=True` skips per-page verification; uses last page suma

### Vision OCR: Slow processing (~90s/page)
- **Status:** IMPROVED - Parallel processing for multi-page PDFs
- **Expected:** ~2.5 min for 3-page PDF (was ~4.5 min) on RTX 3060 12GB
- **Config:** `PDF_MAX_PARALLEL_PAGES=2` (default)
- **Alternative:** Use `paddle` backend for faster (but less accurate) processing

### Models loading slowly (cold start)
- **Status:** FIXED - Models now stay loaded with keep-alive
- **Cause:** Was models unloaded after every request
- **Solution:** `VISION_MODEL_KEEP_ALIVE=10m`, `TEXT_MODEL_KEEP_ALIVE=30m`
- **Low VRAM:** Set `UNLOAD_MODELS_AFTER_USE=true` to revert to old behavior

### DeepSeek-OCR returns empty response
- **Status:** FIXED - Automatic fallback to qwen2.5vl:7b
- **Symptom:** Logs show "DeepSeek-OCR returned empty response" with `eval_count: 1`
- **Cause:** Bug in deepseek-ocr model (Ollama 0.15+) - generates only 1 token for images
- **Solution:** System automatically falls back to `qwen2.5vl:7b` for both single images and multipage PDFs
- **Fallback model:** `ollama pull qwen2.5vl:7b` (must be installed)
- **Relevant code:** `app/deepseek_ocr.py:ocr_page_only()` and `extract_products_deepseek()`

### DeepSeek-OCR enters infinite repetition loop
- **Status:** MITIGATED - System detects and falls back to vision backend
- **Symptom:** Logs show "DeepSeek-OCR n-gram repetition detected" or patterns like "Backgrounds" repeated many times
- **Cause:** Known DeepSeek-OCR bug on some images (complex layouts, multilingual text)
- **Solution:** Ensure fallback model is installed: `ollama pull qwen2.5vl:7b`
- **Relevant code:** `app/deepseek_ocr.py:_detect_repetition()` detects loops, triggers fallback

### qwen3-vl:8b returns empty content
- **Status:** FIXED - System reads from `thinking` field
- **Symptom:** `response.message.content` is empty, but `response.message.thinking` contains the answer
- **Cause:** qwen3-vl uses "thinking mode" by default
- **Solution:** Code in `app/ocr.py:call_ollama()` now reads from `thinking` field when `content` is empty
- **Recommendation:** Use `qwen2.5vl:7b` instead (no thinking mode issues)

### DeepSeek fallback returns 500 error
- **Symptom:** "Ollama error: Server error '500 Internal Server Error'" in fallback
- **Cause:** Fallback model not installed (default: `qwen2.5vl:7b`)
- **Solution:** Install the fallback model: `ollama pull qwen2.5vl:7b`
- **Solution:** Install the fallback model: `ollama pull qwen3-vl:8b`
- **Alternative:** Change fallback to installed model: `OCR_FALLBACK_MODEL=minicpm-v`
