"""OCR processing using PaddleOCR + LLM for structuring."""

import json
import logging
import re
from pathlib import Path
from typing import Optional

import httpx
from paddleocr import PaddleOCR

from app.config import settings
from app.models import Product, Receipt
from app.dictionaries import normalize_store_name, normalize_product
from app.store_prompts import detect_store_from_text, get_prompt_for_store, get_store_display_name
from app.receipt_parser import parse_receipt_hybrid
from app.feedback_logger import log_unmatched_product
from app.price_fixer import fix_products

logger = logging.getLogger(__name__)

# Initialize PaddleOCR once (lazy loading)
_ocr_instance: Optional[PaddleOCR] = None


def get_ocr() -> PaddleOCR:
    """Get or create PaddleOCR instance."""
    global _ocr_instance
    if _ocr_instance is None:
        logger.info("Initializing PaddleOCR...")
        _ocr_instance = PaddleOCR(
            use_angle_cls=True,
            lang='pl',
            use_gpu=False,
            show_log=False,
        )
        logger.info("PaddleOCR initialized")
    return _ocr_instance




def extract_date_from_text(text: str) -> Optional[str]:
    """Extract date from text using regex patterns."""
    patterns = [
        # ISO format: 2026-01-29
        r'(\d{4}-\d{2}-\d{2})',
        # European format: 29-01-2026 or 29.01.2026
        r'(\d{2}[-./]\d{2}[-./]\d{4})',
        # Short year: 29-01-26 or 29.01.26
        r'(\d{2}[-./]\d{2}[-./]\d{2})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            date_str = match.group(1)
            # Normalize to ISO format
            if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                return date_str
            elif re.match(r'\d{2}[-./]\d{2}[-./]\d{4}', date_str):
                # DD-MM-YYYY → YYYY-MM-DD
                parts = re.split(r'[-./]', date_str)
                return f"{parts[2]}-{parts[1]}-{parts[0]}"
            elif re.match(r'\d{2}[-./]\d{2}[-./]\d{2}', date_str):
                # DD-MM-YY → 20YY-MM-DD
                parts = re.split(r'[-./]', date_str)
                year = f"20{parts[2]}" if int(parts[2]) < 50 else f"19{parts[2]}"
                return f"{year}-{parts[1]}-{parts[0]}"

    return None


def extract_store_from_text(text: str) -> Optional[str]:
    """Extract and normalize store name from text using dictionary."""
    return normalize_store_name(text)


def extract_total_from_text(text: str) -> Optional[float]:
    """Extract final total (payment amount) from text."""
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

    # Priority 4: Last "Suma" value (often the final one after returns)
    suma_matches = re.findall(r'[Ss]uma[:\s]+(\d+[.,]\d{2})', text)
    if suma_matches:
        return float(suma_matches[-1].replace(',', '.'))

    return None


async def extract_text_from_image(image_path: Path) -> tuple[str, Optional[str]]:
    """Extract text from image using PaddleOCR."""
    if not image_path.exists():
        return "", f"File not found: {image_path}"

    try:
        ocr = get_ocr()
        result = ocr.ocr(str(image_path), cls=True)

        if not result or not result[0]:
            return "", "No text detected in image"

        lines = []
        for line in result[0]:
            if line and len(line) >= 2:
                text = line[1][0]
                confidence = line[1][1]
                if confidence > 0.5:
                    lines.append(text)

        extracted_text = "\n".join(lines)
        logger.info(f"PaddleOCR extracted {len(lines)} lines from {image_path.name}")

        return extracted_text, None

    except Exception as e:
        logger.error(f"PaddleOCR error for {image_path}: {e}")
        return "", f"OCR error: {e}"


async def structure_with_llm(raw_text: str, prompt: str) -> tuple[Optional[dict], Optional[str]]:
    """Use LLM to structure extracted text into JSON."""
    if not raw_text.strip():
        return None, "No text to structure"

    payload = {
        "model": settings.CLASSIFIER_MODEL,
        "prompt": prompt + raw_text,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 2000,  # Increased for longer receipts
        }
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json=payload
            )
            response.raise_for_status()
            result = response.json()
    except httpx.TimeoutException:
        return None, "LLM timeout"
    except httpx.HTTPError as e:
        return None, f"LLM error: {e}"

    raw_response = result.get("response", "")

    try:
        json_str = raw_response

        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]
        else:
            start = json_str.find('{"products"')
            if start == -1:
                start = json_str.find('{')
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

        return json.loads(json_str.strip()), None

    except json.JSONDecodeError as e:
        # Try fixing common Polish number format issues (comma instead of dot)
        try:
            # Fix patterns like "cena": -1,83 → "cena": -1.83
            fixed = re.sub(r'("cena":\s*-?\d+),(\d+)', r'\1.\2', json_str)
            return json.loads(fixed.strip()), None
        except json.JSONDecodeError:
            pass

        logger.error(f"Failed to parse LLM response: {e}\nRaw: {raw_response}")
        return None, f"Failed to parse response: {e}"


async def extract_products_paddle(image_path: Path) -> tuple[Optional[Receipt], Optional[str]]:
    """
    Extract products from receipt using PaddleOCR + LLM.

    Hybrid approach with fallback extraction:
    1. PaddleOCR: Fast, accurate text extraction
    2. LLM: Intelligent structuring into JSON
    3. Regex fallback: Extract date/store/total if LLM misses them
    """
    # Step 1: Extract text with PaddleOCR
    raw_text, ocr_error = await extract_text_from_image(image_path)
    if ocr_error:
        return None, ocr_error

    logger.debug(f"Extracted text:\n{raw_text}")

    # Step 2: Detect store
    detected_store = detect_store_from_text(raw_text)
    if detected_store:
        logger.info(f"Detected store: {detected_store}")
    else:
        logger.info("Store not detected")

    # Step 3: Try REGEX parsing first (more reliable for structured receipts)
    parsed = parse_receipt_hybrid(raw_text, detected_store)

    if parsed.products and len(parsed.products) >= 3:
        # Regex parsing successful - use these results
        logger.info(f"Regex parser extracted {len(parsed.products)} products - using regex results")

        products = []
        for p in parsed.products:
            # Normalize product name using dictionary (pass store for shortcut matching)
            norm_result = normalize_product(p.nazwa, store=detected_store)

            # Log unmatched products for learning
            if norm_result.method == "no_match":
                log_unmatched_product(
                    raw_name=p.nazwa,
                    price=p.cena,
                    store=detected_store,
                    confidence=norm_result.confidence
                )

            # Convert discount details to model format
            rabaty_szczegoly = None
            if p.rabaty_szczegoly:
                from app.models import DiscountDetail
                rabaty_szczegoly = [
                    DiscountDetail(typ=d.typ, wartosc=d.wartosc, opis=d.opis)
                    for d in p.rabaty_szczegoly
                ]

            products.append(Product(
                nazwa=p.nazwa,
                cena=p.cena,
                warning=None,
                nazwa_oryginalna=p.nazwa,
                nazwa_znormalizowana=norm_result.normalized_name,
                kategoria=norm_result.category if norm_result.confidence >= 0.6 else None,
                confidence=norm_result.confidence if norm_result.confidence >= 0.6 else None,
                cena_oryginalna=p.cena_przed,
                rabat=p.rabat,
                rabaty_szczegoly=rabaty_szczegoly,
            ))

        # Run price fixer post-processing to flag suspicious prices
        products, price_warnings = fix_products(products)
        if price_warnings:
            logger.info(f"Price fixer found {len(price_warnings)} suspicious prices")

        receipt = Receipt(
            products=products,
            sklep=parsed.sklep or get_store_display_name(detected_store),
            data=parsed.data,
            suma=parsed.suma,
            raw_text=raw_text
        )

        return receipt, None

    # Step 4: Fall back to LLM parsing if regex failed
    logger.info(f"Regex parser found only {len(parsed.products) if parsed.products else 0} products - falling back to LLM")

    store_prompt = get_prompt_for_store(detected_store)
    data, llm_error = await structure_with_llm(raw_text, store_prompt)
    if llm_error:
        return None, llm_error

    # Step 5: Build products list from LLM response
    products_data = data if isinstance(data, list) else data.get("products", [])
    skip_patterns = ['PTU', 'VAT', 'SUMA', 'TOTAL', 'RAZEM', 'PARAGON', 'FISKALNY',
                     'KAUCJ', 'ZWROT', 'OPAKOW', 'PŁATN', 'PLATN', 'KARTA', 'SPRZEDA',
                     'GOTÓWKA', 'RESZTA', 'WYDANO', 'NUMER', 'TRANS', 'OPODATK']

    # Generic/placeholder names to skip (from bad OCR or summary pages)
    generic_names = ['PRODUCT', 'ITEM', 'PRODUKT', 'POZYCJA', 'ARTYKUŁ', 'TOWAR']

    products = []
    for p in products_data:
        try:
            name = str(p.get("nazwa") or p.get("product") or p.get("name") or "").strip()
            price = float(p.get("cena") or p.get("price") or 0)

            # Skip empty or too short names (real products have at least 4 chars)
            if not name or len(name) < 4:
                logger.debug(f"Skipping short name: '{name}'")
                continue

            name_upper = name.upper()
            if any(pat in name_upper for pat in skip_patterns):
                logger.debug(f"Skipping summary line: {name}")
                continue

            # Skip generic/placeholder names (e.g., "product1", "item2")
            name_base = re.sub(r'\d+$', '', name_upper)  # Remove trailing numbers
            if name_base in generic_names or any(name_upper.startswith(g) for g in generic_names):
                logger.warning(f"Skipping generic name: {name} = {price}")
                continue

            # Skip if price is suspiciously high or zero
            if price <= 0 or price > 1000:
                continue

            warning = None
            if price > settings.PRICE_WARNING_THRESHOLD:
                warning = f"⚠️ Cena > {settings.PRICE_WARNING_THRESHOLD} zł"

            # Normalize product name using dictionary (pass store for shortcut matching)
            norm_result = normalize_product(name, store=detected_store)

            # Log unmatched products for learning
            if norm_result.method == "no_match":
                log_unmatched_product(
                    raw_name=name,
                    price=price,
                    store=detected_store,
                    confidence=norm_result.confidence
                )

            # Extract discount info if present
            original_price = None
            discount = None
            if "cena_przed" in p or "cena_oryginalna" in p:
                try:
                    original_price = float(p.get("cena_przed") or p.get("cena_oryginalna"))
                except (ValueError, TypeError):
                    pass
            if "rabat" in p:
                try:
                    discount = abs(float(p.get("rabat")))  # Always positive
                except (ValueError, TypeError):
                    pass
            # If we have original price but no discount, calculate it
            if original_price and not discount:
                discount = round(original_price - price, 2)
            # If we have discount but no original price, calculate it
            if discount and not original_price:
                original_price = round(price + discount, 2)

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
            ))
        except (ValueError, TypeError) as e:
            logger.warning(f"Skipping invalid product: {p} - {e}")
            continue

    if not products:
        return None, "No products found in receipt"

    # Run price fixer post-processing to flag suspicious prices
    products, price_warnings = fix_products(products)
    if price_warnings:
        logger.info(f"Price fixer found {len(price_warnings)} suspicious prices")

    # Step 6: Extract metadata with fallbacks
    metadata = data if isinstance(data, dict) else {}

    # Date: LLM result or regex fallback
    receipt_date = metadata.get("data") or metadata.get("date")
    if not receipt_date or receipt_date == "null":
        receipt_date = extract_date_from_text(raw_text)
        if receipt_date:
            logger.info(f"Date extracted via regex: {receipt_date}")

    # Store: Use detected store (most reliable), then LLM, then regex fallback
    if detected_store:
        receipt_store = get_store_display_name(detected_store)
        logger.info(f"Using detected store: {receipt_store}")
    else:
        receipt_store = metadata.get("sklep") or metadata.get("store")
        if receipt_store:
            # Clean up store name (extract just the brand)
            clean_store = extract_store_from_text(receipt_store)
            if clean_store:
                receipt_store = clean_store
        if not receipt_store or receipt_store == "null":
            receipt_store = extract_store_from_text(raw_text)
            if receipt_store:
                logger.info(f"Store extracted via regex: {receipt_store}")

    # Total: ALWAYS try regex first (more accurate for final payment)
    # Card/cash payment is definitively the final amount paid
    receipt_total = extract_total_from_text(raw_text)
    if receipt_total:
        logger.info(f"Total extracted via regex: {receipt_total}")
    else:
        # Fallback to LLM result
        llm_total = metadata.get("suma") or metadata.get("total")
        if llm_total:
            try:
                receipt_total = float(llm_total)
            except (ValueError, TypeError):
                receipt_total = None

    # Final fallback for total: sum of products
    if not receipt_total:
        receipt_total = sum(p.cena for p in products)

    receipt = Receipt(
        products=products,
        sklep=receipt_store,
        data=receipt_date,
        suma=receipt_total,
        raw_text=raw_text
    )

    return receipt, None
