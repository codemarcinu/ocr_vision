"""OCR processing using DeepSeek-OCR (fast vision) + LLM for structuring.

Pipeline:
1. DeepSeek-OCR: Fast text extraction with layout preservation (~6-10s)
2. LLM (qwen2.5:7b): Combined JSON structuring + categorization (~7s)

Total: ~13-17s (optimized from ~20s by merging structuring and categorization).

Optimizations applied:
- Connection pooling via ollama_client module
- Combined structuring + categorization in single LLM call
- Reduced DeepSeek-OCR timeout to 45s (was 120s)
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional
import base64

from app.config import settings
from app import ollama_client
from app.models import Product, Receipt, DiscountDetail
from app.dictionaries import normalize_product
from app.store_prompts import detect_store_from_text, get_store_display_name
from app.feedback_logger import log_unmatched_product
from app.price_fixer import fix_products

logger = logging.getLogger(__name__)

# OCR prompt - keep it short but explicit about needing numbers
# "OCR this image" misses prices; longer prompts cause infinite loops
DEEPSEEK_OCR_PROMPT = "Read all text and numbers."

# Combined structuring + categorization prompt (saves one LLM call ~7s)
# Categories are assigned directly during extraction
STRUCTURING_PROMPT = """Tekst paragonu (OCR):

{ocr_text}

Wyekstrahuj WSZYSTKIE produkty i przypisz im kategorie. Format JSON:
{{"sklep":"nazwa","data":"YYYY-MM-DD","produkty":[{{"nazwa":"X","cena":0.00,"kategoria":"Nabiał","rabat":0.00}}],"suma":0.00}}

ZASADY EKSTRAKCJI:
- Uwzględnij KAŻDY produkt (może być 10-30 produktów!)
- cena = cena KOŃCOWA po rabacie (ostatnia liczba w wierszu)
- rabat = wartość ujemna pod produktem (np. -1.40 → rabat: 1.40)
- suma = wartość przy "SUMA", "DO ZAPŁATY" lub "Karta płatnicza"

KATEGORIE (wybierz jedną dla każdego produktu):
- Nabiał: mleko, ser, jogurt, masło, śmietana, twaróg, kefir
- Pieczywo: chleb, bułka, bagietka, rogal, drożdżówka
- Mięso i wędliny: kurczak, wołowina, wieprzowina, szynka, kiełbasa, boczek, parówki
- Warzywa i owoce: pomidor, ogórek, jabłko, banan, ziemniak, cebula, marchew
- Napoje: woda, sok, cola, piwo, wino, kawa, herbata
- Słodycze: czekolada, cukierki, ciastka, lody, wafelki
- Produkty suche: makaron, ryż, mąka, kasza, płatki, olej
- Mrożonki: lody, pizza mrożona, warzywa mrożone, ryba mrożona
- Chemia: proszek, płyn do naczyń, mydło, szampon, papier toaletowy
- Inne: wszystko co nie pasuje do powyższych

Zwróć TYLKO JSON, bez markdown i komentarzy."""


def extract_total_from_text(text: str) -> Optional[float]:
    """Extract final total from text using regex."""
    # Priority 1: Card payment
    card_patterns = [
        r'[Kk]arta\s+p[lł]atnicza[:\s]+(\d+[.,]\d{2})',
        r'[Kk]arta[:\s]+(\d+[.,]\d{2})',
    ]
    for pattern in card_patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1).replace(',', '.'))

    # Priority 2: Cash
    cash_patterns = [
        r'[Gg]ot[oó]wka[:\s]+(\d+[.,]\d{2})',
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

    # Priority 4: "SUMA PLN" - last occurrence
    suma_matches = re.findall(r'[Ss]uma(?:\s+PLN)?[:\s]+(\d+[.,]\d{2})', text)
    if suma_matches:
        return float(suma_matches[-1].replace(',', '.'))

    return None


def extract_date_from_text(text: str) -> Optional[str]:
    """Extract date from text."""
    patterns = [
        r'(\d{4}-\d{2}-\d{2})',  # ISO: 2026-01-29
        r'(\d{2}[-./]\d{2}[-./]\d{4})',  # EU: 29-01-2026
        r'(\d{2}[-./]\d{2}[-./]\d{2})\b',  # Short: 29-01-26
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            date_str = match.group(1)
            if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                return date_str
            elif re.match(r'\d{2}[-./]\d{2}[-./]\d{4}', date_str):
                parts = re.split(r'[-./]', date_str)
                return f"{parts[2]}-{parts[1]}-{parts[0]}"
            elif re.match(r'\d{2}[-./]\d{2}[-./]\d{2}', date_str):
                parts = re.split(r'[-./]', date_str)
                year = f"20{parts[2]}" if int(parts[2]) < 50 else f"19{parts[2]}"
                return f"{year}-{parts[1]}-{parts[0]}"

    return None


def _detect_repetition(text: str, ngram_size: int = 15, threshold: float = 0.3) -> bool:
    """
    Detect repetitive text patterns using n-gram analysis.
    Returns True if text appears to be stuck in a loop.

    Tuned parameters:
    - ngram_size: 15 - catches medium-length repetition patterns
    - threshold: 0.3 - balanced between false positives and catching loops
    - Minimum text length: 800 chars - short receipts are naturally repetitive

    Note: Receipts have natural repetition (similar product line formats),
    so we use a higher threshold and minimum length to avoid false positives.
    """
    # Short texts are naturally repetitive (receipts with similar product formats)
    # Only check for loops in longer texts where infinite generation is a problem
    if len(text) < 800:
        return False

    # Split into n-grams
    ngrams = [text[i:i+ngram_size] for i in range(0, len(text) - ngram_size, ngram_size // 2)]

    if not ngrams:
        return False

    # Count unique vs total n-grams
    unique_ngrams = set(ngrams)
    repetition_ratio = 1 - (len(unique_ngrams) / len(ngrams))

    return repetition_ratio > threshold


async def _call_deepseek_ocr(image_base64: str, timeout: float = 45.0) -> tuple[str, Optional[str]]:
    """
    Call DeepSeek-OCR via Ollama chat API.

    Known issues with DeepSeek-OCR:
    - May enter infinite loops on some images
    - Repeats patterns like "Backgrounds", font descriptions, dots
    - Worse on multilingual or complex layout documents

    Mitigations:
    - Hard limit via num_predict
    - n-gram repetition detection
    - Pattern-based loop detection
    - Timeout reduced to 45s (was 120s) - normal processing takes 6-15s
    """
    messages = [
        {
            "role": "user",
            "content": DEEPSEEK_OCR_PROMPT,
            "images": [image_base64]
        }
    ]
    options = {
        "num_predict": 2048,  # Hard limit to prevent infinite generation
        "num_ctx": 4096,
        "temperature": 0.1,
    }

    content, error = await ollama_client.post_chat(
        model=settings.OCR_MODEL,
        messages=messages,
        options=options,
        timeout=timeout,
    )

    if error:
        return "", f"DeepSeek-OCR error: {error}"

    if not content:
        return "", "DeepSeek-OCR returned empty response"

    # Check for known infinite loop patterns
    loop_patterns = [
        ("Backgrounds", 10),
        ("sans-serif", 5),
        ("font size", 5),
        ("font-size", 5),
        ("...", 20),  # Series of dots - known trigger
        ("。。", 10),  # Chinese dots
    ]
    for pattern, threshold in loop_patterns:
        if content.count(pattern) > threshold:
            logger.warning(f"DeepSeek-OCR loop detected: '{pattern}' repeated {content.count(pattern)} times")
            return "", f"DeepSeek-OCR repetition loop ({pattern})"

    # n-gram repetition detection
    if _detect_repetition(content):
        logger.warning(f"DeepSeek-OCR n-gram repetition detected in {len(content)} chars")
        return "", "DeepSeek-OCR repetition detected (n-gram analysis)"

    # Clean up common artifacts
    content = content.replace("Do not remove this line.", "").strip()

    # Final validation - should have reasonable receipt content
    # Polish receipts should have prices (X.XX or X,XX patterns)
    price_pattern = re.compile(r'\d+[.,]\d{2}')
    prices_found = len(price_pattern.findall(content))

    if len(content) > 100 and prices_found < 2:
        logger.warning(f"DeepSeek-OCR output has {len(content)} chars but only {prices_found} prices - may be garbled")
        # Don't fail, but log warning - structuring LLM may still extract something

    return content, None


async def _call_structuring_llm(ocr_text: str, timeout: float = 120.0) -> tuple[Optional[dict], Optional[str]]:
    """Call LLM for combined JSON structuring + categorization.

    This is a merged step that:
    1. Extracts products with prices and discounts
    2. Assigns categories to each product
    3. Extracts store, date, and total

    By combining structuring and categorization, we save one LLM call (~7s).
    """
    prompt = STRUCTURING_PROMPT.format(ocr_text=ocr_text)

    # Use STRUCTURING_MODEL if set, otherwise fall back to CLASSIFIER_MODEL
    model = getattr(settings, 'STRUCTURING_MODEL', None) or settings.CLASSIFIER_MODEL

    options = {
        "temperature": 0.1,
        "num_predict": 4096,  # For long receipts with many products
        "num_ctx": 8192,      # Context window for long OCR text
    }

    raw_response, error = await ollama_client.post_generate(
        model=model,
        prompt=prompt,
        options=options,
        timeout=timeout,
        keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
    )

    if error:
        return None, f"Structuring LLM ({model}) error: {error}"
    logger.info(f"Raw LLM response ({len(raw_response)} chars): {raw_response[:1000]}")

    # Parse JSON from response
    try:
        json_str = raw_response

        # Remove markdown code blocks
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            parts = json_str.split("```")
            if len(parts) >= 2:
                json_str = parts[1]

        # Find JSON object - look for opening brace
        # First try to find the outermost { that starts the JSON
        start = -1
        for i, c in enumerate(json_str):
            if c == '{':
                start = i
                break

        if start != -1:
            depth = 0
            for i, c in enumerate(json_str[start:], start):
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        json_str = json_str[start:i+1]
                        break

        # Fix comma decimals (Polish format)
        json_str = re.sub(r'("cena":\s*-?\d+),(\d+)', r'\1.\2', json_str)
        json_str = re.sub(r'("suma":\s*-?\d+),(\d+)', r'\1.\2', json_str)
        json_str = re.sub(r'("rabat":\s*-?\d+),(\d+)', r'\1.\2', json_str)

        return json.loads(json_str.strip()), None

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM JSON: {e}\nRaw: {raw_response[:500]}")
        return None, f"JSON parse error: {e}"


async def extract_products_deepseek(
    image_path: Path,
    is_multi_page: bool = False,
    allow_fallback: bool = True
) -> tuple[Optional[Receipt], Optional[str]]:
    """
    Extract products using DeepSeek-OCR + LLM structuring pipeline.

    This is the fastest accurate pipeline:
    - DeepSeek-OCR: ~10-15s for text extraction
    - LLM structuring: ~7s for JSON conversion
    - Total: ~20s (vs ~80s for single vision model)

    If DeepSeek-OCR fails (loops, timeout, empty), falls back to vision backend.
    """
    if not image_path.exists():
        return None, f"File not found: {image_path}"

    if image_path.suffix.lower() not in settings.SUPPORTED_FORMATS:
        return None, f"Unsupported format: {image_path.suffix}"

    # Step 1: Encode image
    try:
        with open(image_path, "rb") as f:
            image_base64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        return None, f"Failed to read image: {e}"

    # Step 2: OCR with DeepSeek
    logger.info(f"DeepSeek-OCR: {image_path.name}")
    ocr_text, ocr_error = await _call_deepseek_ocr(image_base64)

    if ocr_error:
        logger.warning(f"DeepSeek-OCR failed: {ocr_error}")

        # Fallback to vision backend if allowed
        if allow_fallback:
            fallback_model = settings.OCR_FALLBACK_MODEL
            logger.info(f"Falling back to vision OCR backend with {fallback_model}...")
            try:
                from app.ocr import extract_products_from_image, call_ollama, parse_json_response, _build_receipt, encode_image, OCR_PROMPT

                # Use fallback model instead of default OCR_MODEL
                image_base64 = await encode_image(image_path)
                response_text, error = await call_ollama(
                    OCR_PROMPT,
                    image_base64,
                    model=fallback_model
                )

                if error:
                    logger.error(f"Fallback OCR ({fallback_model}) failed: {error}")
                    return None, f"DeepSeek failed ({ocr_error}), fallback ({fallback_model}) failed ({error})"

                logger.info(f"Fallback ({fallback_model}) response ({len(response_text)} chars): {response_text[:500]}")

                data = parse_json_response(response_text)
                if not data:
                    logger.error(f"Fallback ({fallback_model}) unparseable response: {response_text[:1000]}")
                    return None, f"DeepSeek failed ({ocr_error}), fallback ({fallback_model}) returned unparseable response"

                receipt, build_error = _build_receipt(data, response_text)
                if receipt:
                    logger.info(f"Fallback ({fallback_model}) succeeded: {len(receipt.products)} products")
                    return receipt, None
                else:
                    return None, f"DeepSeek failed ({ocr_error}), fallback ({fallback_model}) build failed ({build_error})"

            except Exception as e:
                logger.error(f"Vision fallback also failed: {e}")
                return None, f"DeepSeek failed ({ocr_error}), vision fallback failed ({e})"

        return None, ocr_error

    logger.info(f"DeepSeek-OCR extracted {len(ocr_text)} chars")
    logger.info(f"OCR text preview:\n{ocr_text[:800]}")

    # Check for minimum content
    if len(ocr_text) < 50:
        return None, f"Too little text extracted ({len(ocr_text)} chars)"

    # Step 3: Detect store from OCR text
    detected_store = detect_store_from_text(ocr_text)
    if detected_store:
        logger.info(f"Detected store: {detected_store}")

    # Step 4: Structure with LLM
    logger.info("Structuring with LLM...")
    data, struct_error = await _call_structuring_llm(ocr_text)

    if struct_error:
        logger.error(f"Structuring failed: {struct_error}")
        return None, struct_error

    if not data:
        return None, "LLM returned no data"

    logger.info(f"LLM returned: {data}")

    # Step 5: Build products list
    # Handle different response formats from LLM
    products_data = data.get("produkty", data.get("products", []))

    # If LLM returned a single product object instead of proper structure
    if not products_data and "nazwa" in data and "cena" in data:
        logger.warning("LLM returned single product instead of proper structure, wrapping it")
        products_data = [data]

    # If LLM returned a list directly
    if isinstance(data, list):
        logger.warning("LLM returned list directly instead of proper structure")
        products_data = data

    logger.info(f"Found {len(products_data)} products in LLM response")

    skip_patterns = ['PTU', 'VAT', 'SUMA', 'TOTAL', 'RAZEM', 'PARAGON', 'FISKALNY',
                     'KAUCJ', 'ZWROT', 'OPAKOW', 'PŁATN', 'PLATN', 'KARTA', 'SPRZEDA',
                     'GOTÓWKA', 'RESZTA', 'WYDANO', 'NUMER', 'TRANS', 'OPODATK']

    products = []
    for p in products_data:
        try:
            name = str(p.get("nazwa") or p.get("name") or "").strip()
            price = float(p.get("cena") or p.get("price") or 0)

            # Skip empty/short names
            if not name or len(name) < 3:
                continue

            # Skip summary lines
            name_upper = name.upper()
            if any(pat in name_upper for pat in skip_patterns):
                logger.debug(f"Skipping summary line: {name}")
                continue

            # Skip invalid prices
            if price <= 0 or price > 500:
                logger.warning(f"Skipping invalid price: {name} = {price}")
                continue

            # Extract discount
            discount = None
            original_price = None
            try:
                rabat_val = p.get("rabat")
                if rabat_val:
                    discount = abs(float(rabat_val))
                    original_price = round(price + discount, 2)
            except (ValueError, TypeError):
                pass

            # Get category from LLM (or leave for classifier)
            category = p.get("kategoria") or p.get("category")

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
                # Use LLM category if dictionary didn't match well
                kategoria=norm_result.category if norm_result.confidence >= 0.6 else category,
                confidence=norm_result.confidence if norm_result.confidence >= 0.6 else 0.7 if category else None,
                cena_oryginalna=original_price,
                rabat=discount,
                rabaty_szczegoly=rabaty_szczegoly,
            ))

        except (ValueError, TypeError) as e:
            logger.warning(f"Skipping invalid product: {p} - {e}")
            continue

    if not products:
        return None, "No products found in receipt"

    # Run price fixer
    products, price_warnings = fix_products(products)
    if price_warnings:
        logger.info(f"Price fixer found {len(price_warnings)} suspicious prices")

    # Step 6: Extract metadata
    # Date: from LLM or regex
    receipt_date = data.get("data") or data.get("date")
    if not receipt_date or receipt_date == "null":
        receipt_date = extract_date_from_text(ocr_text)

    # Store: detected or from LLM
    if detected_store:
        receipt_store = get_store_display_name(detected_store)
    else:
        receipt_store = data.get("sklep") or data.get("store")

    # Total: regex first (most reliable), then LLM
    receipt_total = extract_total_from_text(ocr_text)
    if receipt_total:
        logger.info(f"Total via regex: {receipt_total}")
    else:
        try:
            receipt_total = float(data.get("suma") or data.get("total") or 0)
        except (ValueError, TypeError):
            receipt_total = None

    # Calculate total from products
    calculated_total = round(sum(p.cena for p in products), 2)

    if not receipt_total:
        receipt_total = calculated_total
        logger.info(f"Total from sum: {receipt_total}")

    # Build receipt
    receipt = Receipt(
        products=products,
        sklep=receipt_store,
        data=receipt_date,
        suma=receipt_total,
        raw_text=ocr_text,
        calculated_total=calculated_total,
    )

    # Check for review need
    if receipt_total and calculated_total:
        variance = abs(receipt_total - calculated_total)
        variance_pct = (variance / calculated_total * 100) if calculated_total > 0 else 0

        if variance > 5.0 or variance_pct > 10:
            receipt.needs_review = True
            receipt.review_reasons.append(
                f"Suma {receipt_total:.2f} zł różni się od sumy produktów {calculated_total:.2f} zł"
            )

    logger.info(f"DeepSeek pipeline: {len(products)} products, store={receipt_store}, "
                f"total={receipt_total}, calculated={calculated_total}")

    return receipt, None
