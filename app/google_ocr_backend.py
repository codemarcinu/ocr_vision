"""Google Cloud Vision as primary OCR backend.

Uses Google Vision for text extraction + local LLM for JSON structuring.
Best accuracy combination: cloud OCR + local structuring (no extra cost for LLM).

Usage:
    Set OCR_BACKEND=google in environment
    Requires: GOOGLE_VISION_ENABLED=true and valid service account credentials
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

from app.config import settings
from app.models import Receipt, Product, DiscountDetail
from app.google_vision_ocr import ocr_with_google_vision
from app.store_prompts import detect_store_from_text, get_store_display_name
from app.ocr_prompts import get_structuring_prompt
from app.dictionaries import normalize_product
from app.feedback_logger import log_unmatched_product
from app import ollama_client

logger = logging.getLogger(__name__)


async def _call_structuring_llm(
    ocr_text: str,
    detected_store: str = None,
    timeout: float = 120.0
) -> tuple[Optional[dict], Optional[str]]:
    """Call LLM for JSON structuring + categorization."""
    prompt_template = get_structuring_prompt(detected_store)
    prompt = prompt_template.format(ocr_text=ocr_text)

    model = getattr(settings, 'STRUCTURING_MODEL', None) or settings.CLASSIFIER_MODEL

    options = {
        "temperature": 0.1,
        "num_predict": 4096,
        "num_ctx": 8192,
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

    logger.info(f"LLM response ({len(raw_response)} chars): {raw_response[:500]}...")

    # Parse JSON from response
    try:
        json_match = re.search(r'\{[\s\S]*\}', raw_response)
        if json_match:
            data = json.loads(json_match.group())
            return data, None
        else:
            return None, "No JSON found in LLM response"
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"


async def _build_receipt(
    data: dict,
    raw_text: str,
    detected_store: Optional[str] = None
) -> tuple[Optional[Receipt], Optional[str]]:
    """Build Receipt object from LLM-structured data."""
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

        except Exception as e:
            logger.warning(f"Failed to parse product {p}: {e}")
            continue

    if not products:
        return None, "No valid products extracted"

    # Extract totals
    suma = None
    try:
        suma = float(data.get("suma") or data.get("total") or 0)
    except (ValueError, TypeError):
        pass

    sklep = data.get("sklep") or data.get("store") or get_store_display_name(detected_store)
    data_str = data.get("data") or data.get("date")

    calculated_total = round(sum(p.cena for p in products), 2)

    receipt = Receipt(
        products=products,
        sklep=sklep,
        data=data_str,
        suma=suma,
        raw_text=raw_text,
        calculated_total=calculated_total,
    )

    logger.info(f"Built receipt: {len(products)} products, store={sklep}, total={suma}, calculated={calculated_total}")
    return receipt, None


async def extract_products_google(
    image_path: Path,
    is_multi_page: bool = False
) -> tuple[Optional[Receipt], Optional[str]]:
    """
    Extract products using Google Vision OCR + local LLM structuring.
    """
    if not settings.GOOGLE_VISION_ENABLED:
        return None, "Google Vision not enabled (set GOOGLE_VISION_ENABLED=true)"

    logger.info(f"Google OCR backend: {image_path.name}")

    # Step 1: Extract text with Google Vision
    raw_text, gv_error = await ocr_with_google_vision(image_path)

    if gv_error:
        logger.error(f"Google Vision failed: {gv_error}")
        return None, f"Google Vision OCR failed: {gv_error}"

    if not raw_text or len(raw_text.strip()) < 50:
        logger.warning(f"Google Vision returned too little text: {len(raw_text) if raw_text else 0} chars")
        return None, "Google Vision returned insufficient text"

    logger.info(f"Google Vision extracted {len(raw_text)} chars")

    # Detect store from text
    detected_store = detect_store_from_text(raw_text)
    if detected_store:
        logger.info(f"Detected store: {detected_store}")

    # Step 2: Structure with local LLM
    data, llm_error = await _call_structuring_llm(raw_text, detected_store)

    if llm_error:
        logger.error(f"LLM structuring failed: {llm_error}")
        return None, f"LLM structuring failed: {llm_error}"

    # Step 3: Build receipt
    receipt, build_error = await _build_receipt(data, raw_text, detected_store)

    if build_error:
        logger.error(f"Receipt build failed: {build_error}")
        return None, f"Receipt build failed: {build_error}"

    return receipt, None


async def process_multipage_pdf_google(
    image_paths: list[Path],
    filename: str
) -> tuple[Optional[Receipt], Optional[str]]:
    """
    Process multi-page PDF with Google Vision OCR.
    """
    if not settings.GOOGLE_VISION_ENABLED:
        return None, "Google Vision not enabled"

    logger.info(f"Google OCR multipage: {filename} ({len(image_paths)} pages)")

    # Extract text from all pages
    page_texts = []
    for i, image_path in enumerate(image_paths):
        logger.info(f"Google Vision: page {i+1}/{len(image_paths)}")

        raw_text, gv_error = await ocr_with_google_vision(image_path)

        if gv_error:
            logger.warning(f"Google Vision failed on page {i+1}: {gv_error}")
            page_texts.append(f"[PAGE {i+1} ERROR: {gv_error}]")
        elif raw_text and raw_text.strip():
            page_texts.append(f"--- STRONA {i+1}/{len(image_paths)} ---\n{raw_text}")
        else:
            page_texts.append(f"[PAGE {i+1} EMPTY]")

    # Combine all pages
    combined_text = "\n\n".join(page_texts)

    if len(combined_text.strip()) < 100:
        return None, "Google Vision extracted too little text from PDF"

    logger.info(f"Google Vision: combined {len(combined_text)} chars from {len(image_paths)} pages")

    # Detect store from combined text
    detected_store = detect_store_from_text(combined_text)
    if detected_store:
        logger.info(f"Detected store: {detected_store}")

    # Structure with single LLM call
    data, llm_error = await _call_structuring_llm(combined_text, detected_store)

    if llm_error:
        return None, f"LLM structuring failed: {llm_error}"

    # Build receipt
    receipt, build_error = await _build_receipt(data, combined_text, detected_store)

    if build_error:
        return None, f"Receipt build failed: {build_error}"

    return receipt, None
