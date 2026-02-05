"""OCR processing using DeepSeek-OCR (fast vision) + LLM for structuring.

Pipeline:
1. DeepSeek-OCR: Fast text extraction with layout preservation (~6-10s)
2. LLM (qwen2.5:7b): Combined JSON structuring + categorization (~7s)

Total: ~13-17s (optimized from ~20s by merging structuring and categorization).

Optimizations applied:
- Connection pooling via ollama_client module
- Combined structuring + categorization in single LLM call
- Configurable DeepSeek-OCR timeout via DEEPSEEK_OCR_TIMEOUT (default 90s)
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
from app.ocr_prompts import (
    OCR_PROMPT_UNIVERSAL,
    get_structuring_prompt,
)
from app.confidence_scoring import calculate_confidence

logger = logging.getLogger(__name__)

# Use optimized universal OCR prompt from ocr_prompts module
DEEPSEEK_OCR_PROMPT = OCR_PROMPT_UNIVERSAL


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


async def _call_deepseek_ocr(image_base64: str, timeout: float = None) -> tuple[str, Optional[str]]:
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
    - Configurable timeout via DEEPSEEK_OCR_TIMEOUT (default 90s)
    """
    if timeout is None:
        timeout = float(settings.DEEPSEEK_OCR_TIMEOUT)
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


async def _try_google_vision_fallback(
    image_path: Path,
    previous_errors: str
) -> tuple[Optional["Receipt"], Optional[str]]:
    """
    Ultimate fallback using Google Cloud Vision API.

    Called when all local Ollama models fail. Extracts text with Google Vision,
    then structures it with local LLM.

    Args:
        image_path: Path to the image file
        previous_errors: Description of previous failures for logging

    Returns:
        Tuple (Receipt or None, error message or None)
    """
    logger.info(f"Attempting Google Vision as ultimate fallback for {image_path.name}")
    logger.info(f"Previous errors: {previous_errors}")

    try:
        from app.google_vision_ocr import ocr_with_google_vision
    except ImportError as e:
        return None, f"Google Vision module not available: {e}"

    # Step 1: OCR with Google Vision
    gv_text, gv_error = await ocr_with_google_vision(image_path)

    if gv_error:
        return None, gv_error

    if len(gv_text) < 50:
        return None, f"Google Vision returned too little text ({len(gv_text)} chars)"

    logger.info(f"Google Vision extracted {len(gv_text)} chars")
    logger.debug(f"Google Vision text preview:\n{gv_text[:500]}")

    # Step 2: Detect store from Google Vision text
    detected_store = detect_store_from_text(gv_text)
    if detected_store:
        logger.info(f"Google Vision: detected store {detected_store}")

    # Step 3: Structure with local LLM (reuse existing function)
    data, struct_error = await _call_structuring_llm(gv_text, detected_store=detected_store)

    if struct_error:
        return None, f"Google Vision OCR ok, but LLM structuring failed: {struct_error}"

    if not data:
        return None, "Google Vision OCR ok, but LLM returned no data"

    # Step 4: Build receipt (same logic as main function)
    return await _build_receipt_from_llm_data(data, gv_text, detected_store)


async def _build_receipt_from_llm_data(
    data: dict,
    raw_text: str,
    detected_store: Optional[str] = None
) -> tuple[Optional["Receipt"], Optional[str]]:
    """
    Build Receipt object from LLM-structured data.

    This is extracted to be reusable by both main flow and Google Vision fallback.
    """
    products_data = data.get("produkty", data.get("products", []))

    if isinstance(data, list):
        products_data = data

    if not products_data and "nazwa" in data and "cena" in data:
        products_data = [data]

    if not products_data:
        return None, "No products in LLM response"

    skip_patterns = ['PTU', 'VAT', 'SUMA', 'TOTAL', 'RAZEM', 'PARAGON', 'FISKALNY',
                     'KAUCJ', 'ZWROT', 'OPAKOW', 'PŁATN', 'PLATN', 'KARTA', 'SPRZEDA',
                     'GOTÓWKA', 'RESZTA', 'WYDANO', 'NUMER', 'TRANS', 'OPODATK']

    products = []
    for p in products_data:
        try:
            name = str(p.get("nazwa") or p.get("name") or "").strip()
            price = float(p.get("cena") or p.get("price") or 0)

            if not name or len(name) < 3:
                continue

            name_upper = name.upper()
            if any(pat in name_upper for pat in skip_patterns):
                continue

            if price <= 0 or price > 500:
                continue

            discount = None
            original_price = None
            try:
                rabat_val = p.get("rabat")
                if rabat_val:
                    discount = abs(float(rabat_val))
                    original_price = round(price + discount, 2)
            except (ValueError, TypeError):
                pass

            category = p.get("kategoria") or p.get("category")
            norm_result = normalize_product(name, store=detected_store)

            if norm_result.method == "no_match":
                log_unmatched_product(
                    raw_name=name,
                    price=price,
                    store=detected_store,
                    confidence=norm_result.confidence
                )

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
        return None, "No valid products found"

    # Run price fixer
    products, price_warnings = fix_products(products)

    # Extract metadata
    receipt_date = data.get("data") or data.get("date")
    if not receipt_date or receipt_date == "null":
        receipt_date = extract_date_from_text(raw_text)

    if detected_store:
        receipt_store = get_store_display_name(detected_store)
    else:
        receipt_store = data.get("sklep") or data.get("store")

    receipt_total = extract_total_from_text(raw_text)
    if not receipt_total:
        try:
            receipt_total = float(data.get("suma") or data.get("total") or 0)
        except (ValueError, TypeError):
            receipt_total = None

    calculated_total = round(sum(p.cena for p in products), 2)

    if not receipt_total:
        receipt_total = calculated_total

    receipt = Receipt(
        products=products,
        sklep=receipt_store,
        data=receipt_date,
        suma=receipt_total,
        raw_text=raw_text,
        calculated_total=calculated_total,
    )

    # Calculate confidence score
    confidence_report = calculate_confidence(receipt)

    if not confidence_report.auto_save_ok:
        receipt.needs_review = True
        if confidence_report.issues:
            receipt.review_reasons.extend(confidence_report.issues)
        if not receipt.review_reasons and confidence_report.warnings:
            receipt.review_reasons.append(confidence_report.warnings[0])

    logger.info(
        f"Built receipt: {len(products)} products, store={receipt_store}, "
        f"total={receipt_total}, calculated={calculated_total}, "
        f"confidence={confidence_report.score:.2f}"
    )

    return receipt, None


async def _call_structuring_llm(
    ocr_text: str,
    detected_store: str = None,
    timeout: float = 120.0
) -> tuple[Optional[dict], Optional[str]]:
    """Call LLM for combined JSON structuring + categorization.

    This is a merged step that:
    1. Extracts products with prices and discounts
    2. Assigns categories to each product
    3. Extracts store, date, and total

    Uses store-specific prompts for better accuracy.
    By combining structuring and categorization, we save one LLM call (~7s).
    """
    # Get store-specific prompt (or generic if store unknown)
    prompt_template = get_structuring_prompt(detected_store)
    prompt = prompt_template.format(ocr_text=ocr_text)

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

                    # Ultimate fallback: Google Cloud Vision
                    if settings.GOOGLE_VISION_ENABLED:
                        gv_receipt, gv_error = await _try_google_vision_fallback(
                            image_path, f"DeepSeek: {ocr_error}, Vision: {error}"
                        )
                        if gv_receipt:
                            return gv_receipt, None
                        logger.error(f"Google Vision also failed: {gv_error}")
                        return None, f"All OCR failed - DeepSeek: {ocr_error}, Vision: {error}, Google: {gv_error}"

                    return None, f"DeepSeek failed ({ocr_error}), fallback ({fallback_model}) failed ({error})"

                logger.info(f"Fallback ({fallback_model}) response ({len(response_text)} chars): {response_text[:500]}")

                data = parse_json_response(response_text)
                if not data:
                    logger.error(f"Fallback ({fallback_model}) unparseable response: {response_text[:1000]}")

                    # Ultimate fallback: Google Cloud Vision
                    if settings.GOOGLE_VISION_ENABLED:
                        gv_receipt, gv_error = await _try_google_vision_fallback(
                            image_path, f"DeepSeek: {ocr_error}, Vision: unparseable"
                        )
                        if gv_receipt:
                            return gv_receipt, None
                        logger.error(f"Google Vision also failed: {gv_error}")
                        return None, f"All OCR failed - DeepSeek: {ocr_error}, Vision: unparseable, Google: {gv_error}"

                    return None, f"DeepSeek failed ({ocr_error}), fallback ({fallback_model}) returned unparseable response"

                receipt, build_error = _build_receipt(data, response_text)
                if receipt:
                    logger.info(f"Fallback ({fallback_model}) succeeded: {len(receipt.products)} products")
                    return receipt, None
                else:
                    # Ultimate fallback: Google Cloud Vision
                    if settings.GOOGLE_VISION_ENABLED:
                        gv_receipt, gv_error = await _try_google_vision_fallback(
                            image_path, f"DeepSeek: {ocr_error}, Vision build: {build_error}"
                        )
                        if gv_receipt:
                            return gv_receipt, None
                        logger.error(f"Google Vision also failed: {gv_error}")
                        return None, f"All OCR failed - DeepSeek: {ocr_error}, Vision: {build_error}, Google: {gv_error}"

                    return None, f"DeepSeek failed ({ocr_error}), fallback ({fallback_model}) build failed ({build_error})"

            except Exception as e:
                logger.error(f"Vision fallback also failed: {e}")
                vision_error = str(e)

                # Ultimate fallback: Google Cloud Vision
                if settings.GOOGLE_VISION_ENABLED:
                    gv_receipt, gv_error = await _try_google_vision_fallback(
                        image_path, f"DeepSeek: {ocr_error}, Vision: {vision_error}"
                    )
                    if gv_receipt:
                        return gv_receipt, None
                    logger.error(f"Google Vision also failed: {gv_error}")
                    return None, f"All OCR failed - DeepSeek: {ocr_error}, Vision: {vision_error}, Google: {gv_error}"

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

    # Step 4: Structure with LLM (using store-specific prompt)
    logger.info(f"Structuring with LLM (store: {detected_store or 'generic'})...")
    data, struct_error = await _call_structuring_llm(ocr_text, detected_store=detected_store)

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

    # Calculate confidence score
    confidence_report = calculate_confidence(receipt)

    # Decide if review is needed based on confidence
    if not confidence_report.auto_save_ok:
        receipt.needs_review = True
        if confidence_report.issues:
            receipt.review_reasons.extend(confidence_report.issues)
        if not receipt.review_reasons and confidence_report.warnings:
            # Add first warning as reason if no issues
            receipt.review_reasons.append(confidence_report.warnings[0])

    logger.info(
        f"DeepSeek pipeline: {len(products)} products, store={receipt_store}, "
        f"total={receipt_total}, calculated={calculated_total}, "
        f"confidence={confidence_report.score:.2f}"
    )

    return receipt, None


# =============================================================================
# MULTIPAGE PDF PROCESSING (OCR all pages first, then single LLM call)
# =============================================================================

async def ocr_page_only(image_path: Path) -> tuple[str, Optional[str]]:
    """Wykonaj tylko OCR na stronie, bez strukturyzacji LLM.

    Używane do przetwarzania wielostronicowych PDF-ów gdzie:
    1. OCR wszystkich stron (równolegle)
    2. Połączenie tekstów
    3. Jeden LLM na cały tekst

    Jeśli DeepSeek-OCR zawiedzie, używa fallback modelu (qwen2.5vl:7b).

    Returns:
        Tuple (surowy tekst OCR, błąd jeśli wystąpił)
    """
    if not image_path.exists():
        return "", f"File not found: {image_path}"

    try:
        with open(image_path, "rb") as f:
            image_base64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        return "", f"Failed to read image: {e}"

    logger.info(f"OCR-only: {image_path.name}")
    ocr_text, ocr_error = await _call_deepseek_ocr(image_base64)

    if ocr_error:
        logger.warning(f"OCR-only DeepSeek failed for {image_path.name}: {ocr_error}")

        # Fallback to vision model for raw text extraction
        fallback_model = settings.OCR_FALLBACK_MODEL
        logger.info(f"OCR-only falling back to {fallback_model} for {image_path.name}...")

        try:
            from app.ocr import call_ollama

            # Simple prompt for raw text extraction (not JSON)
            raw_text_prompt = """Odczytaj CAŁY tekst z tego polskiego paragonu.
Zachowaj oryginalny układ z cenami po prawej stronie.
Nie formatuj jako JSON - zwróć surowy tekst paragonu."""

            response_text, error = await call_ollama(
                raw_text_prompt,
                image_base64,
                model=fallback_model
            )

            if error:
                logger.error(f"OCR-only fallback ({fallback_model}) failed: {error}")
                return "", f"DeepSeek failed ({ocr_error}), fallback ({fallback_model}) failed ({error})"

            if response_text and len(response_text) > 50:
                logger.info(f"OCR-only fallback ({fallback_model}): {image_path.name} → {len(response_text)} chars")
                return response_text, None
            else:
                logger.warning(f"OCR-only fallback ({fallback_model}) returned too short response")
                return "", f"DeepSeek failed ({ocr_error}), fallback too short"

        except Exception as e:
            logger.error(f"OCR-only fallback exception: {e}")
            return "", f"DeepSeek failed ({ocr_error}), fallback exception ({e})"

    logger.info(f"OCR-only: {image_path.name} → {len(ocr_text)} chars")
    return ocr_text, None


async def process_multipage_pdf(
    image_paths: list[Path],
    filename: str = "multipage.pdf"
) -> tuple[Optional[Receipt], Optional[str]]:
    """Przetwórz wielostronicowy PDF: OCR równolegle → jeden LLM.

    Nowe podejście (zamiast per-page LLM):
    1. OCR wszystkich stron równolegle
    2. Połącz teksty z separatorami stron
    3. Jeden prompt LLM na cały tekst
    4. LLM widzi pełny kontekst (rabaty, suma na końcu)

    Args:
        image_paths: Lista ścieżek do obrazów stron (PNG z pdf2image)
        filename: Nazwa pliku do logów

    Returns:
        Tuple (Receipt, błąd)
    """
    import asyncio

    if not image_paths:
        return None, "No pages to process"

    total_pages = len(image_paths)
    logger.info(f"Multipage PDF: {filename} ({total_pages} stron)")

    # Step 1: OCR wszystkich stron równolegle
    logger.info(f"Step 1: OCR {total_pages} stron równolegle...")

    async def ocr_with_index(idx: int, path: Path) -> tuple[int, str, Optional[str]]:
        text, error = await ocr_page_only(path)
        return idx, text, error

    tasks = [ocr_with_index(i, path) for i, path in enumerate(image_paths)]
    results = await asyncio.gather(*tasks)

    # Posortuj po indeksie i zbierz teksty
    results_sorted = sorted(results, key=lambda x: x[0])

    page_texts = []
    ocr_errors = []

    for idx, text, error in results_sorted:
        if error:
            ocr_errors.append(f"Strona {idx+1}: {error}")
            page_texts.append(f"[STRONA {idx+1} - BŁĄD OCR]")
        elif text.strip():
            page_texts.append(f"--- STRONA {idx+1}/{total_pages} ---\n{text}")
        else:
            page_texts.append(f"[STRONA {idx+1} - PUSTA]")

    # Jeśli wszystkie strony zawiodły, zwróć błąd
    successful_pages = sum(1 for _, text, error in results_sorted if not error and text.strip())
    if successful_pages == 0:
        return None, f"OCR failed for all {total_pages} pages: {ocr_errors}"

    logger.info(f"OCR sukces: {successful_pages}/{total_pages} stron")

    # Step 2: Połącz teksty
    combined_text = "\n\n".join(page_texts)
    logger.info(f"Step 2: Połączony tekst: {len(combined_text)} chars")

    # Step 3: Wykryj sklep z połączonego tekstu
    detected_store = detect_store_from_text(combined_text)
    if detected_store:
        logger.info(f"Wykryto sklep: {detected_store}")

    # Step 4: JEDEN LLM na cały tekst
    logger.info(f"Step 3: Strukturyzacja LLM (store: {detected_store or 'generic'})...")
    data, struct_error = await _call_structuring_llm(combined_text, detected_store=detected_store)

    if struct_error:
        logger.error(f"Strukturyzacja failed: {struct_error}")
        return None, struct_error

    if not data:
        return None, "LLM returned no data"

    # Step 5: Budowanie Receipt (taki sam kod jak w extract_products_deepseek)
    products_data = data.get("produkty", data.get("products", []))

    if isinstance(data, list):
        products_data = data

    if not products_data and "nazwa" in data and "cena" in data:
        products_data = [data]

    logger.info(f"LLM zwrócił {len(products_data)} produktów")

    skip_patterns = ['PTU', 'VAT', 'SUMA', 'TOTAL', 'RAZEM', 'PARAGON', 'FISKALNY',
                     'KAUCJ', 'ZWROT', 'OPAKOW', 'PŁATN', 'PLATN', 'KARTA', 'SPRZEDA',
                     'GOTÓWKA', 'RESZTA', 'WYDANO', 'NUMER', 'TRANS', 'OPODATK', 'STRONA']

    products = []
    for p in products_data:
        try:
            name = str(p.get("nazwa") or p.get("name") or "").strip()
            price = float(p.get("cena") or p.get("price") or 0)

            if not name or len(name) < 3:
                continue

            name_upper = name.upper()
            if any(pat in name_upper for pat in skip_patterns):
                continue

            if price <= 0 or price > 500:
                continue

            # Discount
            discount = None
            original_price = None
            try:
                rabat_val = p.get("rabat")
                if rabat_val:
                    discount = abs(float(rabat_val))
                    original_price = round(price + discount, 2)
            except (ValueError, TypeError):
                pass

            category = p.get("kategoria") or p.get("category")
            norm_result = normalize_product(name, store=detected_store)

            if norm_result.method == "no_match":
                log_unmatched_product(
                    raw_name=name,
                    price=price,
                    store=detected_store,
                    confidence=norm_result.confidence
                )

            rabaty_szczegoly = None
            if discount:
                rabaty_szczegoly = [
                    DiscountDetail(typ="kwotowy", wartosc=discount, opis="Rabat")
                ]

            products.append(Product(
                nazwa=name,
                cena=price,
                warning=None,
                nazwa_oryginalna=name,
                nazwa_znormalizowana=norm_result.normalized_name,
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
        return None, "No products found in multipage PDF"

    # Price fixer
    products, price_warnings = fix_products(products)

    # Metadata
    receipt_date = data.get("data") or data.get("date")
    if not receipt_date:
        receipt_date = extract_date_from_text(combined_text)

    if detected_store:
        receipt_store = get_store_display_name(detected_store)
    else:
        receipt_store = data.get("sklep") or data.get("store")

    # Total - z LLM lub regex z połączonego tekstu
    receipt_total = extract_total_from_text(combined_text)
    if not receipt_total:
        try:
            receipt_total = float(data.get("suma") or data.get("total") or 0)
        except (ValueError, TypeError):
            receipt_total = None

    calculated_total = round(sum(p.cena for p in products), 2)

    if not receipt_total:
        receipt_total = calculated_total

    # Build receipt
    receipt = Receipt(
        products=products,
        sklep=receipt_store,
        data=receipt_date,
        suma=receipt_total,
        raw_text=combined_text,
        calculated_total=calculated_total,
    )

    # Confidence
    confidence_report = calculate_confidence(receipt)

    if not confidence_report.auto_save_ok:
        receipt.needs_review = True
        if confidence_report.issues:
            receipt.review_reasons.extend(confidence_report.issues)
        if not receipt.review_reasons and confidence_report.warnings:
            receipt.review_reasons.append(confidence_report.warnings[0])

    logger.info(
        f"Multipage PDF done: {len(products)} products, store={receipt_store}, "
        f"total={receipt_total}, calculated={calculated_total}, "
        f"confidence={confidence_report.score:.2f}"
    )

    return receipt, None
