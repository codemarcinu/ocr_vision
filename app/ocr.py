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

logger = logging.getLogger(__name__)

# =============================================================================
# PROMPTS
# =============================================================================

# Primary prompt - optimized for Polish receipts with discount handling
OCR_PROMPT = """Analyze this Polish grocery store receipt image and extract ALL products with their FINAL prices.

CRITICAL RULES - READ CAREFULLY:

1. EXTRACT EVERY PRODUCT: The "products" array MUST contain ALL items from the receipt.
   - Do not skip any products, even if partially visible
   - Each product occurrence is a SEPARATE item (don't merge duplicates)

2. FINAL PRICE RULE: For each product, extract the FINAL price (after all discounts).
   - If you see "Rabat" (discount) below a product, the FINAL price is the LAST number in that block
   - Example: Product 11.17 → Rabat -3.29 → 7.88 means cena should be 7.88

3. WEIGHTED PRODUCTS (kg): For products sold by weight:
   - You'll see: ProductName kg  Qty × UnitPrice  Value
   - IGNORE the unit price per kg (e.g., 28.20/kg)
   - Use the final calculated amount (or price after discount)
   - Example: "BoczWedz 0.396 × 28.20 = 11.17, Rabat -3.29, 7.88" → cena: 7.88

4. BIEDRONKA FORMAT:
   - Line 1: ProductName  PTU  Qty×  UnitPrice  Value
   - Line 2 (optional): Rabat  -X.XX
   - Line 3 (optional): FinalPrice
   - ALWAYS take the LAST number before next product!

Return ONLY valid JSON (no markdown, no explanation):
{
  "products": [
    {"nazwa": "product name", "cena": 7.88, "cena_przed": 11.17, "rabat": 3.29}
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

# Verification prompt - model checks its own work
VERIFICATION_PROMPT = """I extracted products from this receipt but the numbers don't add up.

EXTRACTED DATA:
{extracted_data}

PROBLEM: Sum of products = {calculated_total} PLN, but receipt total = {receipt_total} PLN
Difference: {difference} PLN

Please look at the receipt image again and VERIFY/CORRECT the extraction:

1. Check each product - is the price correct? Should it be the FINAL price after "Rabat" discount?
2. For weighted products (kg), did I use unit price instead of total? Fix it.
3. Are there any products I missed or duplicated?
4. Are there fake "products" that are actually summaries/taxes?

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
    timeout: float = 300.0
) -> tuple[str, Optional[str]]:
    """Call Ollama API and return response text or error."""
    payload = {
        "model": model or settings.OCR_MODEL,
        "prompt": prompt,
        "stream": False,
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

async def extract_products_from_image(image_path: Path) -> tuple[Optional[Receipt], Optional[str]]:
    """
    Extract products from receipt image using vision model.
    Uses two-stage fallback if primary extraction fails.
    Includes self-verification step if totals don't match.
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
    if receipt.suma and receipt.calculated_total:
        difference = abs(receipt.suma - receipt.calculated_total)
        percentage = (difference / receipt.suma) * 100 if receipt.suma > 0 else 0

        # If significant mismatch (>10% or >5 PLN), run verification
        if difference > 5 and percentage > 10:
            logger.warning(f"Total mismatch detected: receipt={receipt.suma}, calculated={receipt.calculated_total}, diff={difference:.2f} ({percentage:.1f}%)")
            logger.info("Running self-verification...")

            verified_receipt = await _verify_extraction(image_base64, receipt, data)
            if verified_receipt:
                # Check if verification improved the match
                new_diff = abs(verified_receipt.suma - verified_receipt.calculated_total) if verified_receipt.suma else difference
                if new_diff < difference:
                    logger.info(f"Verification improved match: {difference:.2f} → {new_diff:.2f}")
                    return verified_receipt, None
                else:
                    logger.info("Verification didn't improve, keeping original")

    return receipt, None


async def _verify_extraction(image_base64: str, receipt: Receipt, original_data: dict) -> Optional[Receipt]:
    """Ask model to verify and correct its extraction."""
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

    verification_prompt = VERIFICATION_PROMPT.format(
        extracted_data=extracted_data,
        calculated_total=receipt.calculated_total,
        receipt_total=receipt.suma,
        difference=f"{difference:+.2f}"
    )

    response_text, error = await call_ollama(verification_prompt, image_base64)

    if error:
        logger.warning(f"Verification failed: {error}")
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
            name_base = re.sub(r'\d+$', '', name_upper)  # Remove trailing numbers
            if name_base in generic_names or any(name_upper.startswith(g) for g in generic_names):
                logger.warning(f"Skipping generic name: {name} = {price}")
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
