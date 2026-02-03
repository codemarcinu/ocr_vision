"""OpenAI as primary OCR backend.

Uses Google Vision for text extraction + OpenAI API for JSON structuring.
Combines best-in-class cloud OCR with OpenAI's structured output (JSON mode).

Usage:
    Set OCR_BACKEND=openai in environment
    Requires: GOOGLE_VISION_ENABLED=true, OPENAI_API_KEY set
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from app.config import settings
from app.models import Receipt, Product, DiscountDetail
from app.google_vision_ocr import ocr_with_google_vision
from app.store_prompts import detect_store_from_text, get_store_display_name
from app.ocr_prompts import get_structuring_prompt
from app.dictionaries import normalize_product
from app.feedback_logger import log_unmatched_product
from app.openai_client import get_client

logger = logging.getLogger(__name__)


async def _call_openai_structuring(
    ocr_text: str,
    detected_store: str = None,
    timeout: float = 60.0
) -> tuple[Optional[dict], Optional[str]]:
    """Call OpenAI API for JSON structuring + categorization.

    Uses response_format=json_object for guaranteed valid JSON output.
    """
    prompt_template = get_structuring_prompt(detected_store)
    prompt = prompt_template.format(ocr_text=ocr_text)

    model = settings.OPENAI_OCR_MODEL

    try:
        client = get_client()
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=4096,
            timeout=timeout,
        )

        content = response.choices[0].message.content
        if not content:
            return None, "OpenAI returned empty response"

        usage = response.usage
        if usage:
            logger.info(
                f"OpenAI {model}: {usage.prompt_tokens} in + {usage.completion_tokens} out tokens"
            )

        logger.info(f"OpenAI response ({len(content)} chars): {content[:500]}...")

        data = json.loads(content)
        return data, None

    except AuthenticationError:
        return None, "OpenAI API key invalid or missing (set OPENAI_API_KEY)"
    except RateLimitError:
        return None, "OpenAI rate limit exceeded - retry later"
    except BadRequestError as e:
        return None, f"OpenAI bad request: {e.message}"
    except APIConnectionError:
        return None, "Cannot connect to OpenAI API"
    except APIStatusError as e:
        return None, f"OpenAI API error ({e.status_code}): {e.message}"
    except json.JSONDecodeError as e:
        return None, f"OpenAI JSON parse error: {e}"
    except Exception as e:
        return None, f"OpenAI unexpected error: {type(e).__name__}: {e}"


async def _build_receipt(
    data: dict,
    raw_text: str,
    detected_store: Optional[str] = None
) -> tuple[Optional[Receipt], Optional[str]]:
    """Build Receipt object from OpenAI-structured data."""
    products_data = data.get("produkty", data.get("products", []))

    if isinstance(data, list):
        products_data = data

    if not products_data and "nazwa" in data and "cena" in data:
        products_data = [data]

    if not products_data:
        return None, "No products in OpenAI response"

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

            # Try cena_przed from response
            try:
                cena_przed = p.get("cena_przed")
                if cena_przed:
                    original_price = float(cena_przed)
                    if discount is None:
                        discount = round(original_price - price, 2)
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


async def extract_products_openai(
    image_path: Path,
    is_multi_page: bool = False
) -> tuple[Optional[Receipt], Optional[str]]:
    """Extract products using Google Vision OCR + OpenAI structuring."""
    if not settings.GOOGLE_VISION_ENABLED:
        return None, "Google Vision not enabled (set GOOGLE_VISION_ENABLED=true for OpenAI backend)"

    logger.info(f"OpenAI OCR backend: {image_path.name}")

    # Step 1: Extract text with Google Vision
    raw_text, gv_error = await ocr_with_google_vision(image_path)

    if gv_error:
        logger.error(f"Google Vision failed: {gv_error}")
        return None, f"Google Vision OCR failed: {gv_error}"

    if not raw_text or len(raw_text.strip()) < 50:
        logger.warning(f"Google Vision returned too little text: {len(raw_text) if raw_text else 0} chars")
        return None, "Google Vision returned insufficient text"

    logger.info(f"Google Vision extracted {len(raw_text)} chars")

    # Step 2: Detect store from OCR text
    detected_store = detect_store_from_text(raw_text)
    if detected_store:
        logger.info(f"Detected store: {detected_store}")

    # Step 3: Structure with OpenAI API
    data, llm_error = await _call_openai_structuring(raw_text, detected_store)

    if llm_error:
        logger.error(f"OpenAI structuring failed: {llm_error}")
        return None, f"OpenAI structuring failed: {llm_error}"

    # Step 4: Build receipt
    receipt, build_error = await _build_receipt(data, raw_text, detected_store)

    if build_error:
        logger.error(f"Receipt build failed: {build_error}")
        return None, f"Receipt build failed: {build_error}"

    return receipt, None


async def _ocr_single_page(
    image_path: Path,
    page_num: int,
    total_pages: int,
) -> tuple[int, str]:
    """OCR a single page with Google Vision (for parallel processing)."""
    logger.info(f"Google Vision: page {page_num + 1}/{total_pages}")

    raw_text, gv_error = await ocr_with_google_vision(image_path)

    if gv_error:
        logger.warning(f"Google Vision failed on page {page_num + 1}: {gv_error}")
        return page_num, f"[PAGE {page_num + 1} ERROR: {gv_error}]"
    elif raw_text and raw_text.strip():
        return page_num, f"--- STRONA {page_num + 1}/{total_pages} ---\n{raw_text}"
    else:
        return page_num, f"[PAGE {page_num + 1} EMPTY]"


async def process_multipage_pdf_openai(
    image_paths: list[Path],
    filename: str
) -> tuple[Optional[Receipt], Optional[str]]:
    """Process multi-page PDF with Google Vision OCR + OpenAI structuring."""
    if not settings.GOOGLE_VISION_ENABLED:
        return None, "Google Vision not enabled"

    logger.info(f"OpenAI OCR multipage: {filename} ({len(image_paths)} pages)")

    # Extract text from all pages in parallel
    tasks = [
        _ocr_single_page(image_path, i, len(image_paths))
        for i, image_path in enumerate(image_paths)
    ]
    results = await asyncio.gather(*tasks)

    # Sort by page number and combine
    results.sort(key=lambda x: x[0])
    page_texts = [text for _, text in results]

    combined_text = "\n\n".join(page_texts)

    if len(combined_text.strip()) < 100:
        return None, "Google Vision extracted too little text from PDF"

    logger.info(f"Google Vision: combined {len(combined_text)} chars from {len(image_paths)} pages")

    # Detect store from combined text
    detected_store = detect_store_from_text(combined_text)
    if detected_store:
        logger.info(f"Detected store: {detected_store}")

    # Structure with single OpenAI call
    data, llm_error = await _call_openai_structuring(combined_text, detected_store)

    if llm_error:
        return None, f"OpenAI structuring failed: {llm_error}"

    # Build receipt
    receipt, build_error = await _build_receipt(data, combined_text, detected_store)

    if build_error:
        return None, f"Receipt build failed: {build_error}"

    return receipt, None


def extract_total_from_text(text: str) -> Optional[float]:
    """Extract payment total from raw receipt text.

    Reuses the same logic as other backends for consistency.
    """
    import re

    patterns = [
        r'(?:SUMA|RAZEM|DO ZAPŁATY|Karta płatnicza|PŁATNOŚĆ)\s*:?\s*(\d+[.,]\d{2})',
        r'(\d+[.,]\d{2})\s*(?:PLN|zł)',
    ]

    totals = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            try:
                totals.append(float(m.replace(',', '.')))
            except ValueError:
                pass

    if totals:
        return max(totals)
    return None
