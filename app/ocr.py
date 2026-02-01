"""OCR processing using vision model via Ollama with two-stage fallback."""

import base64
import json
import logging
import re
from pathlib import Path
from typing import Optional

import httpx

from app.config import settings
from app.models import Product, Receipt, DiscountDetail
from app.dictionaries import normalize_product
from app.store_prompts import detect_store_from_text, get_store_display_name
from app.feedback_logger import log_unmatched_product
from app.price_fixer import fix_products

logger = logging.getLogger(__name__)

# =============================================================================
# PROMPTS
# =============================================================================

# Primary prompt - optimized for Polish receipts with discount handling
OCR_PROMPT = """Analyze this Polish grocery store receipt image and extract ALL products with their FINAL prices.

═══════════════════════════════════════════════════════════════════════════════
CRITICAL: FINAL PRICE = LAST NUMBER IN PRODUCT BLOCK (after all discounts)
═══════════════════════════════════════════════════════════════════════════════

WEIGHTED PRODUCTS - PAY ATTENTION:
For products sold by weight (kg), you'll see multiple numbers. IGNORE the unit price!

┌─────────────────────────────────────────────────────────────────────────────┐
│  BoczWędz B kg       │ ← Product name with "kg" = weighted product          │
│  0.279 x 28.20   B   │ ← 0.279kg × 28.20zł/kg (IGNORE 28.20 - unit price!) │
│               7.88   │ ← THIS IS THE FINAL PRICE = 7.88 zł                  │
└─────────────────────────────────────────────────────────────────────────────┘
  ✗ WRONG: cena: 28.20 (this is price per kg, not total!)
  ✓ RIGHT: cena: 7.88  (this is what customer pays)

PRODUCTS WITH DISCOUNTS:
┌─────────────────────────────────────────────────────────────────────────────┐
│  Pomidor Malin B     │                                                      │
│  0.602 x 18.49   B   │ ← Calculation shown                                  │
│              11.13   │ ← Price before discount                              │
│  Rabat        -3.34  │ ← Discount                                           │
│               7.79   │ ← FINAL PRICE after discount = 7.79 zł               │
└─────────────────────────────────────────────────────────────────────────────┘
  ✗ WRONG: cena: 11.13 or cena: 18.49
  ✓ RIGHT: cena: 7.79, cena_przed: 11.13, rabat: 3.34

REGULAR PRODUCTS:
┌─────────────────────────────────────────────────────────────────────────────┐
│  Mleko 2% 1L    B    │                                                      │
│               3.49   │ ← FINAL PRICE = 3.49 zł                              │
└─────────────────────────────────────────────────────────────────────────────┘

EXTRACTION RULES:
1. EVERY product line = one entry in "products" array
2. "cena" = ALWAYS the LAST number in product block (after Rabat if present)
3. "cena_przed" = price BEFORE discount (optional)
4. "rabat" = discount amount as POSITIVE number (optional)
5. For weighted products: IGNORE the "× XX.XX" unit price - use calculated total

Return ONLY valid JSON (no markdown, no explanation):
{
  "products": [
    {"nazwa": "BoczWędz B", "cena": 7.88},
    {"nazwa": "Pomidor Malin", "cena": 7.79, "cena_przed": 11.13, "rabat": 3.34},
    {"nazwa": "Mleko 2% 1L", "cena": 3.49}
  ],
  "sklep": "store name",
  "data": "YYYY-MM-DD",
  "suma": 144.48
}

Field definitions:
- "nazwa": product name as shown on receipt
- "cena": FINAL price after discounts (what customer paid)
- "cena_przed": price before discount (optional)
- "rabat": discount amount as POSITIVE number (optional)
- "sklep": store name (Biedronka, Lidl, Kaufland, Żabka, etc.)
- "data": date in YYYY-MM-DD format
- "suma": TOTAL paid - look for "Suma PLN", "DO ZAPŁATY", "Karta płatnicza"

IGNORE (not products): PTU/VAT, "Sprzedaż opodatkowana", payment lines, page numbers.
Prices must use DOT as decimal (7.88 not 7,88)."""

# Text-only verification prompt - uses text model to avoid VRAM issues
# NOTE: This prompt does NOT require the image - it works from extracted text/data only
TEXT_VERIFICATION_PROMPT = """I extracted products from a receipt but the numbers don't add up. Help me find the errors.

RAW RECEIPT TEXT:
{raw_text}

EXTRACTED DATA:
{extracted_data}

PROBLEM: Sum of products = {calculated_total} PLN, but receipt total = {receipt_total} PLN
Difference: {difference} PLN

Analyze the raw text and find errors in my extraction:

1. WEIGHTED PRODUCTS (kg): Did I extract unit price (e.g., 28.20/kg) instead of final calculated price?
   - Pattern: "0.XXX x YY.YY" followed by a smaller number = that smaller number is the final price
   - Example: "0.279 x 28.20" then "7.88" → final price is 7.88, NOT 28.20

2. DISCOUNTS: Did I miss "Rabat" lines that reduce the price?
   - Pattern: price, then "Rabat -X.XX", then final price
   - The LAST number before next product is the final price

3. MISSING/DUPLICATE products: Are there products in raw text I missed or added twice?

4. FAKE PRODUCTS: Did I include summary lines (SUMA, PTU, RAZEM) as products?

Return CORRECTED JSON with ONLY real products and their FINAL prices:
{{"products":[{{"nazwa":"name","cena":FINAL_PRICE,"cena_przed":BEFORE_DISCOUNT,"rabat":DISCOUNT}}],"sklep":"store","data":"YYYY-MM-DD","suma":RECEIPT_TOTAL}}

Focus on making the sum of product prices match the receipt total."""

# Fallback prompt for two-stage processing - Stage 1: Extract raw text
OCR_RAW_TEXT_PROMPT = """Extract ALL text from this receipt image as plain text.
Include every product line, price, discount, and detail you can see.
Preserve the layout and structure. Focus on:
- Product names and their prices
- Discounts (Rabat) and final prices
- Total amount (Suma, DO ZAPŁATY, Karta płatnicza)
- Store name and date"""

# Fallback prompt for two-stage processing - Stage 2: Parse text to JSON
PARSE_TEXT_PROMPT = """Convert this receipt text to JSON. Extract ALL products.

TEXT:
{text}

Return ONLY JSON:
{{"products":[{{"nazwa":"product","cena":7.88,"cena_przed":11.17,"rabat":3.29}}],"sklep":"store","data":"YYYY-MM-DD","suma":144.48}}

RULES:
- "cena" = FINAL price after discount (the last number in product block)
- For weighted items (kg), ignore unit price, use total value
- Extract EVERY product - do not skip any
- Prices as numbers with dot decimal (7.88 not 7,88)"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def extract_total_from_text(text: str) -> Optional[float]:
    """Extract final total (payment amount) from text using regex."""
    # Priority 1: Card payment (definitively final amount)
    card_patterns = [
        r'[Kk]arta\s+p[lł]atnicza\s+(\d+[.,]\d{2})',
        r'[Kk]arta\s+(\d+[.,]\d{2})',
    ]
    for pattern in card_patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1).replace(',', '.'))

    # Priority 2: Cash payment
    cash_patterns = [
        r'[Gg]ot[oó]wka\s+(\d+[.,]\d{2})',
        r'[Pp][lł]atno[sś][cć]\s+(\d+[.,]\d{2})',
    ]
    for pattern in cash_patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1).replace(',', '.'))

    # Priority 3: "DO ZAPŁATY" or "RAZEM"
    final_patterns = [
        r'[Dd][Oo]\s+[Zz]ap[lł]aty[:\s]+(\d+[.,]\d{2})',
        r'[Rr]azem[:\s]+(\d+[.,]\d{2})',
    ]
    for pattern in final_patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1).replace(',', '.'))

    # Priority 4: "Suma PLN" - last occurrence
    suma_matches = re.findall(r'[Ss]uma(?:\s+PLN)?[:\s]+(\d+[.,]\d{2})', text)
    if suma_matches:
        return float(suma_matches[-1].replace(',', '.'))

    return None


def clean_json_response(response: str) -> str:
    """Clean model response from markdown and other artifacts."""
    response = response.strip()

    # Remove markdown code blocks
    if "```json" in response:
        response = response.split("```json")[1].split("```")[0]
    elif "```" in response:
        parts = response.split("```")
        if len(parts) >= 2:
            response = parts[1]

    # Remove thinking tags if present
    if "<think>" in response:
        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)

    return response.strip()


def parse_json_response(json_str: str) -> Optional[dict]:
    """Parse JSON from model response with error recovery."""
    try:
        cleaned = clean_json_response(json_str)

        # Try direct parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object
        start = cleaned.find('{"products"')
        if start == -1:
            start = cleaned.find('{')

        if start != -1:
            depth = 0
            for i, c in enumerate(cleaned[start:], start):
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        json_str = cleaned[start:i+1]
                        break

            # Fix comma decimals
            json_str = re.sub(r'("cena":\s*-?\d+),(\d+)', r'\1.\2', json_str)
            json_str = re.sub(r'("cena_przed":\s*-?\d+),(\d+)', r'\1.\2', json_str)
            json_str = re.sub(r'("rabat":\s*-?\d+),(\d+)', r'\1.\2', json_str)
            json_str = re.sub(r'("suma":\s*-?\d+),(\d+)', r'\1.\2', json_str)

            return json.loads(json_str)

        return None
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        return None


async def encode_image(image_path: Path) -> str:
    """Encode image to base64."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


async def call_ollama(
    prompt: str,
    image_base64: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 300.0,
    keep_alive: Optional[str] = None
) -> tuple[str, Optional[str]]:
    """Call Ollama API and return response text or error."""
    used_model = model or settings.OCR_MODEL

    # Auto-select keep_alive based on model type if not specified
    if keep_alive is None:
        if image_base64 or used_model == settings.OCR_MODEL:
            # Vision model - shorter keep-alive due to higher VRAM usage
            keep_alive = settings.VISION_MODEL_KEEP_ALIVE
        else:
            # Text model - longer keep-alive
            keep_alive = settings.TEXT_MODEL_KEEP_ALIVE

    payload = {
        "model": used_model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {
            "temperature": 0.1,
            "top_p": 0.8,
            "top_k": 20,
            "num_predict": 4096,
            "num_ctx": 4096,
        }
    }

    if image_base64:
        payload["images"] = [image_base64]

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json=payload
            )
            response.raise_for_status()
            result = response.json()
    except httpx.TimeoutException:
        return "", "Ollama timeout"
    except httpx.HTTPError as e:
        return "", f"Ollama error: {e}"

    # Check both content and thinking fields (for models with thinking mode)
    response_text = result.get("response", "")

    if not response_text.strip():
        # Some models put response in thinking field
        thinking = result.get("thinking", "")
        if thinking:
            logger.warning("Model returned response in 'thinking' field instead of 'response'")
            response_text = thinking

    return response_text, None


# =============================================================================
# MAIN OCR FUNCTIONS
# =============================================================================

async def extract_products_from_image(
    image_path: Path,
    is_multi_page: bool = False
) -> tuple[Optional[Receipt], Optional[str]]:
    """
    Extract products from receipt image using vision model.
    Uses two-stage fallback if primary extraction fails.
    Includes self-verification step if totals don't match.

    Args:
        image_path: Path to the image file
        is_multi_page: If True, skip per-page verification (will be done after combining all pages)
    """
    if not image_path.exists():
        return None, f"File not found: {image_path}"

    if image_path.suffix.lower() not in settings.SUPPORTED_FORMATS:
        return None, f"Unsupported format: {image_path.suffix}"

    try:
        image_base64 = await encode_image(image_path)
    except Exception as e:
        logger.error(f"Failed to encode image {image_path}: {e}")
        return None, f"Failed to read image: {e}"

    # Stage 1: Primary extraction (single-pass)
    logger.info(f"Vision OCR (primary): {image_path.name}")
    response_text, error = await call_ollama(OCR_PROMPT, image_base64)

    if error:
        logger.error(f"Primary OCR failed: {error}")
        return None, error

    logger.debug(f"Raw response: {response_text[:500]}...")

    # Parse JSON
    data = parse_json_response(response_text)

    # Check if we got valid products
    products_data = []
    if data:
        products_data = data if isinstance(data, list) else data.get("products", [])

    # If no products or very few, try two-stage fallback
    if not products_data or len(products_data) < 2:
        logger.warning(f"Primary extraction found only {len(products_data)} products, trying two-stage fallback")
        receipt, fallback_error = await _extract_two_stage(image_base64, image_path.name)
        if receipt and receipt.products:
            logger.info(f"Two-stage fallback succeeded: {len(receipt.products)} products")
            return receipt, None
        elif fallback_error:
            logger.warning(f"Two-stage fallback also failed: {fallback_error}")
        # Continue with primary results even if few

    if not data:
        return None, "Failed to parse OCR response"

    # Build initial receipt
    receipt, build_error = _build_receipt(data, response_text)

    if not receipt:
        return None, build_error

    # Self-verification: Check if totals match
    # Skip verification for multi-page PDFs - will be done after combining all pages
    if receipt.suma and receipt.calculated_total and not is_multi_page:
        difference = abs(receipt.suma - receipt.calculated_total)
        percentage = (difference / receipt.suma) * 100 if receipt.suma > 0 else 0

        # If significant mismatch (>10% or >5 PLN), run verification
        if difference > 5 and percentage > 10:
            logger.warning(f"Total mismatch detected: receipt={receipt.suma}, calculated={receipt.calculated_total}, diff={difference:.2f} ({percentage:.1f}%)")
            logger.info("Running text-only verification...")

            verified_receipt = await _verify_extraction(response_text, receipt, data)
            if verified_receipt:
                # Check if verification improved the match
                new_diff = abs(verified_receipt.suma - verified_receipt.calculated_total) if verified_receipt.suma else difference
                if new_diff < difference:
                    logger.info(f"Verification improved match: {difference:.2f} → {new_diff:.2f}")
                    return verified_receipt, None
                else:
                    logger.info("Verification didn't improve, keeping original")
    elif is_multi_page:
        logger.debug("Skipping per-page verification for multi-page PDF")

    return receipt, None


async def _verify_extraction(raw_text: str, receipt: Receipt, original_data: dict) -> Optional[Receipt]:
    """
    Ask text model to verify and correct extraction.

    Uses text-only model (CLASSIFIER_MODEL) instead of vision model to avoid VRAM 500 errors.
    The raw_text from OCR provides enough context for verification without re-sending the image.
    """
    # Format extracted data for verification prompt
    products_summary = "\n".join([
        f"  - {p.nazwa}: {p.cena} PLN" + (f" (było {p.cena_oryginalna}, rabat {p.rabat})" if p.rabat else "")
        for p in receipt.products
    ])

    extracted_data = f"""Store: {receipt.sklep}
Date: {receipt.data}
Products:
{products_summary}
Receipt Total (suma): {receipt.suma} PLN"""

    difference = receipt.suma - receipt.calculated_total if receipt.suma else 0

    # Truncate raw text if too long (keep first 3000 chars for context)
    truncated_raw = raw_text[:3000] if raw_text else "(no raw text available)"

    verification_prompt = TEXT_VERIFICATION_PROMPT.format(
        raw_text=truncated_raw,
        extracted_data=extracted_data,
        calculated_total=receipt.calculated_total,
        receipt_total=receipt.suma,
        difference=f"{difference:+.2f}"
    )

    # Use text model (not vision) to avoid VRAM issues
    response_text, error = await call_ollama(
        verification_prompt,
        image_base64=None,  # No image - text-only verification
        model=settings.CLASSIFIER_MODEL  # Use text model
    )

    if error:
        logger.warning(f"Text verification failed: {error}")
        return None

    # Parse verified data
    verified_data = parse_json_response(response_text)
    if not verified_data:
        logger.warning("Verification returned unparseable response")
        return None

    # Build receipt from verified data
    verified_receipt, _ = _build_receipt(verified_data, response_text)
    return verified_receipt


async def _extract_two_stage(image_base64: str, filename: str) -> tuple[Optional[Receipt], Optional[str]]:
    """Two-stage extraction: OCR raw text → Parse to JSON."""
    logger.info("Two-stage extraction: Stage 1 (raw text)")

    # Stage 1: Extract raw text
    raw_text, error = await call_ollama(OCR_RAW_TEXT_PROMPT, image_base64)

    if error or not raw_text.strip():
        return None, f"Stage 1 failed: {error or 'empty response'}"

    logger.info(f"Stage 1 extracted {len(raw_text)} chars")
    logger.debug(f"Raw text: {raw_text[:300]}...")

    # Skip if too little text (likely a summary/payment page, not products)
    if len(raw_text) < 150:
        logger.warning(f"Stage 1 extracted only {len(raw_text)} chars - likely summary page, skipping")
        return None, "Too little text for product extraction (summary page?)"

    # Stage 2: Parse text to JSON using text model
    logger.info("Two-stage extraction: Stage 2 (parse JSON)")
    parse_prompt = PARSE_TEXT_PROMPT.format(text=raw_text[:3000])

    json_response, error = await call_ollama(
        parse_prompt,
        image_base64=None,  # No image for stage 2
        model=settings.CLASSIFIER_MODEL  # Use text model
    )

    if error:
        return None, f"Stage 2 failed: {error}"

    data = parse_json_response(json_response)
    if not data:
        return None, "Stage 2 failed to parse JSON"

    # Build receipt, including raw_text from stage 1
    receipt, build_error = _build_receipt(data, raw_text)
    if receipt:
        logger.info(f"Two-stage extracted {len(receipt.products)} products")

    return receipt, build_error


def _build_receipt(data: dict, raw_response: str) -> tuple[Optional[Receipt], Optional[str]]:
    """Build Receipt object from parsed data."""
    metadata = data if isinstance(data, dict) else {}
    products_data = data if isinstance(data, list) else data.get("products", [])

    # Detect store
    store_from_model = metadata.get("sklep") or metadata.get("store_name") or ""
    detected_store = detect_store_from_text(store_from_model) or detect_store_from_text(raw_response)

    if detected_store:
        logger.info(f"Detected store: {detected_store}")

    # Skip patterns for summary/tax lines
    skip_patterns = ['PTU', 'VAT', 'SUMA', 'TOTAL', 'RAZEM', 'PARAGON', 'FISKALNY',
                     'KAUCJ', 'ZWROT', 'OPAKOW', 'PŁATN', 'PLATN', 'KARTA', 'SPRZEDA',
                     'GOTÓWKA', 'RESZTA', 'WYDANO', 'NUMER', 'TRANS', 'OPODATK']

    # Generic/placeholder names to skip (from bad OCR or summary pages)
    generic_names = ['PRODUCT', 'ITEM', 'PRODUKT', 'POZYCJA', 'ARTYKUŁ', 'TOWAR']

    # Build products
    products = []
    for p in products_data:
        try:
            # Support multiple key formats
            name = str(
                p.get("nazwa") or p.get("name") or p.get("product") or ""
            ).strip()

            price = float(
                p.get("cena") or p.get("total_price") or p.get("price") or 0
            )

            # Skip empty or too short names (real products have at least 4 chars)
            if not name or len(name) < 4:
                logger.debug(f"Skipping short name: '{name}'")
                continue

            name_upper = name.upper()

            # Skip non-product lines (tax, summary, etc.)
            if any(pat in name_upper for pat in skip_patterns):
                logger.debug(f"Skipping summary line: {name}")
                continue

            # Skip generic/placeholder names (e.g., "product1", "item2")
            # Use both list check and regex for robustness
            name_base = re.sub(r'\d+$', '', name_upper)  # Remove trailing numbers
            name_lower = name.lower()

            # Check against generic names list (uppercase)
            if name_base in generic_names or any(name_upper.startswith(g) for g in generic_names):
                logger.warning(f"Skipping generic name: {name} = {price}")
                continue

            # Regex patterns for generic names (case-insensitive backup)
            generic_patterns = [
                r'^product\d*$', r'^item\d*$', r'^produkt\d*$',
                r'^pozycja\d*$', r'^artykul\d*$', r'^towar\d*$'
            ]
            if any(re.match(p, name_lower) for p in generic_patterns):
                logger.warning(f"Skipping generic name (regex): {name} = {price}")
                continue

            # Skip invalid prices
            if price <= 0 or price > 500:
                logger.warning(f"Skipping invalid price: {name} = {price}")
                continue

            # Skip suspiciously round prices that look like subtotals (e.g., 48.16, 96.32)
            # Real product prices in Poland are usually X.X9, X.X5, X.X0, or X.99
            if price > 30:
                price_cents = int(round(price * 100)) % 100
                if price_cents not in (0, 5, 9, 10, 15, 19, 20, 25, 29, 30, 39, 40, 45, 49, 50, 55, 59, 69, 79, 89, 90, 95, 99):
                    # Check if it might be a subtotal (often multiples or sums)
                    if price > 40:
                        logger.warning(f"Skipping suspicious price (possible subtotal): {name} = {price}")
                        continue

            # Extract discount info
            original_price = None
            discount = None

            try:
                original_price = float(p.get("cena_przed") or p.get("cena_oryginalna") or 0) or None
            except (ValueError, TypeError):
                pass

            try:
                discount = abs(float(p.get("rabat") or 0)) or None
            except (ValueError, TypeError):
                pass

            # Calculate missing values
            if original_price and not discount and original_price > price:
                discount = round(original_price - price, 2)
            if discount and not original_price:
                original_price = round(price + discount, 2)

            # Normalize product
            norm_result = normalize_product(name, store=detected_store)

            if norm_result.method == "no_match":
                log_unmatched_product(
                    raw_name=name,
                    price=price,
                    store=detected_store,
                    confidence=norm_result.confidence
                )

            # Build discount details
            rabaty_szczegoly = None
            if discount:
                rabaty_szczegoly = [
                    DiscountDetail(typ="kwotowy", wartosc=discount, opis="Rabat")
                ]

            warning = None
            if price > settings.PRICE_WARNING_THRESHOLD:
                warning = f"Price > {settings.PRICE_WARNING_THRESHOLD} PLN"

            products.append(Product(
                nazwa=name,
                cena=price,
                warning=warning,
                nazwa_oryginalna=name,
                nazwa_znormalizowana=norm_result.normalized_name,
                kategoria=norm_result.category if norm_result.confidence >= 0.6 else None,
                confidence=norm_result.confidence if norm_result.confidence >= 0.6 else None,
                cena_oryginalna=original_price,
                rabat=discount,
                rabaty_szczegoly=rabaty_szczegoly,
            ))

        except (ValueError, TypeError) as e:
            logger.warning(f"Skipping invalid product: {p} - {e}")
            continue

    if not products:
        return None, "No products found"

    # Run price fixer post-processing to flag suspicious prices
    products, price_warnings = fix_products(products)
    if price_warnings:
        logger.info(f"Price fixer found {len(price_warnings)} suspicious prices")

    # Extract date
    receipt_date = metadata.get("data") or metadata.get("date")
    if receipt_date in ("null", None, ""):
        receipt_date = None

    # Extract store name
    if detected_store:
        receipt_store = get_store_display_name(detected_store)
    else:
        receipt_store = store_from_model if store_from_model not in ("null", None, "") else None

    # Extract total with regex fallback
    receipt_total = None

    # Try regex first (most reliable)
    regex_total = extract_total_from_text(raw_response)
    if regex_total:
        receipt_total = regex_total
        logger.info(f"Total via regex: {receipt_total}")
    else:
        # Try model's value
        try:
            model_total = metadata.get("suma") or metadata.get("total")
            if model_total and model_total != "null":
                receipt_total = float(model_total)
                logger.info(f"Total from model: {receipt_total}")
        except (ValueError, TypeError):
            pass

    # Fallback: sum of products
    calculated_total = round(sum(p.cena for p in products), 2)
    if not receipt_total:
        receipt_total = calculated_total
        logger.info(f"Total from sum: {receipt_total}")

    receipt = Receipt(
        products=products,
        sklep=receipt_store,
        data=receipt_date,
        suma=receipt_total,
        raw_text=raw_response,
        calculated_total=calculated_total,
    )

    logger.info(f"Built receipt: {len(products)} products, store={receipt_store}, "
                f"total={receipt_total}, calculated={calculated_total}")

    return receipt, None


async def unload_model(model_name: str) -> None:
    """Unload model from Ollama to free memory."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": model_name,
                    "keep_alive": 0
                }
            )
            logger.debug(f"Unloaded model: {model_name}")
    except Exception as e:
        logger.warning(f"Failed to unload model {model_name}: {e}")
