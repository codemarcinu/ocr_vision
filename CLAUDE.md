# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart Pantry Tracker - OCR receipt processing system using Ollama LLMs for product extraction and categorization, outputting to Obsidian markdown files. Includes a Telegram bot for mobile interaction with **human-in-the-loop validation**.

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
3. **`app/ocr.py`** / **`app/paddle_ocr.py`** - OCR extraction (vision model or PaddleOCR hybrid)
4. **`app/store_prompts.py`** - Store-specific LLM prompts for accurate extraction
5. **`app/price_fixer.py`** - Post-processor: detects suspicious prices (unit price vs final)
6. **`app/dictionaries/`** - Product/store name normalization using fuzzy matching (Levenshtein distance)
7. **`app/classifier.py`** - Calls `qwen2.5:7b` via Ollama to categorize products
8. **`app/obsidian_writer.py`** - Generates markdown files for Obsidian vault

Data flow: `paragony/inbox/` → OCR → **Store Detection** → **Store-specific Prompt** → LLM → **Price Fixer** → validation → normalization → categorization → `paragony/processed/` + `vault/`

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
3. Products from all pages are **combined** into a single Receipt
4. **Raw text from all pages is merged** to extract the final payment total
5. Payment info (e.g., "Karta płatnicza 144.48") is typically on the last page
6. Total is validated against sum of all products
7. Temp images are cleaned up after processing

**Performance**: With `PDF_MAX_PARALLEL_PAGES=2`, a 3-page PDF processes in ~2.5 min instead of ~4.5 min.

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
- **`handlers/`** - Command handlers:
  - `receipts.py` - Photo/PDF processing with review flow, `/recent`, `/reprocess`, `/pending`
  - `pantry.py` - `/pantry`, `/use`, `/remove`, `/search`
  - `stats.py` - `/stats`, `/stores`, `/categories`
  - `errors.py` - `/errors`, `/clearerrors`

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
OCR_MODEL=qwen2.5vl:7b                              # Vision model for OCR
OCR_BACKEND=vision                                  # "vision" (LLM-based) or "paddle" (PaddleOCR + LLM)
CLASSIFIER_MODEL=qwen2.5:7b                         # Categorization model
TELEGRAM_BOT_TOKEN=xxx                              # From .env file
TELEGRAM_CHAT_ID=123456                             # Authorized user ID (0 = allow all)
BOT_ENABLED=true                                    # Enable/disable Telegram bot

# Performance tuning
VISION_MODEL_KEEP_ALIVE=10m                         # How long vision model stays in VRAM (default: 10m)
TEXT_MODEL_KEEP_ALIVE=30m                           # How long text model stays in VRAM (default: 30m)
UNLOAD_MODELS_AFTER_USE=false                       # Force unload after each use (for low VRAM)
PDF_MAX_PARALLEL_PAGES=2                            # Concurrent pages for multi-page PDF
```

## Ollama Models Required

```bash
ollama pull qwen2.5vl:7b    # OCR extraction (recommended, 6GB, requires num_ctx=4096)
ollama pull qwen2.5:7b      # Product categorization
```

Models stay loaded in VRAM for faster subsequent requests (vision: 10m, text: 30m by default). Set `UNLOAD_MODELS_AFTER_USE=true` for low VRAM systems.

### OCR Backend Comparison

| Backend | Speed | Accuracy | Notes |
|---------|-------|----------|-------|
| `vision` (qwen2.5vl:7b) | **~4 min** | Best | Recommended. 3/3 success, 24 products extracted |
| `paddle` (PaddleOCR + LLM) | ~11s | Good | Faster but less accurate for complex receipts |

Set via `OCR_BACKEND=vision` or `OCR_BACKEND=paddle` in docker-compose.yml.

### Vision Model Notes (OCR_BACKEND=vision)

| Model | Size | Status | Notes |
|-------|------|--------|-------|
| **`qwen2.5vl:7b`** | 6.0GB | **Best** | Default. 3/3 success, requires num_ctx=4096. 76% GPU + 24% CPU offload on 12GB |
| `qwen2.5vl:3b` | 3.2GB | Partial | Niestabilny, błędy GGML na niektórych obrazach |
| `llama3.2-vision` | 7.8GB | Partial | 2/3 success, może odmówić przetwarzania |
| `qwen3-vl:8b` | 6.1GB | Avoid | Thinking mode - odpowiedź w polu `thinking` zamiast `content` |
| `minicpm-v` | 5.5GB | Fallback | Działa, ale mniej dokładny niż qwen2.5vl |
| `deepseek-ocr` | 6.7GB | Broken | Ollama 0.14+ bug: "SameBatch" error |

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

### Metrics
- `GET /metrics` - Prometheus metrics (via `prometheus_fastapi_instrumentator`)

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
- **Status:** IMPROVED - Enhanced prompts + price fixer
- **Symptom:** Weighted products (kg) show per-kg price, not total
- **Solution 1:** OCR prompt has ASCII-art examples showing correct price extraction
- **Solution 2:** `price_fixer.py` flags suspicious prices (>40 PLN) with warnings
- **Check logs:** `grep -i "price warning" pantry-api`

### Vision OCR: Summary page products
- **Symptom:** Fake products like `product1: 48.16 zł`
- **Cause:** Last page (payment summary) being parsed as products
- **Fix:** Summary page detection (< 150 chars) should skip these
- **Fallback:** Filter catches generic names and suspicious prices

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
