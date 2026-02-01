"""Product categorization using qwen2.5:7b via Ollama with A/B testing support."""

"""Product categorization using qwen2.5:7b via Ollama with A/B testing support.

Optimizations:
- Uses connection pooling via ollama_client module
- A/B testing runs models in parallel (not sequential)
- Skips LLM categorization for products already categorized by dictionary
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import settings
from app.models import CategorizedProduct, Product
from app import ollama_client

logger = logging.getLogger(__name__)

# A/B test results log file
AB_TEST_LOG = settings.LOGS_DIR / "classifier_ab_test.jsonl"

def _log_ab_result(
    model_a: str,
    model_b: str,
    products_count: int,
    result_a: list[dict],
    result_b: list[dict],
    time_a: float,
    time_b: float,
    error_a: Optional[str],
    error_b: Optional[str],
) -> None:
    """Log A/B test results to JSONL file for later analysis."""
    try:
        AB_TEST_LOG.parent.mkdir(parents=True, exist_ok=True)

        # Calculate agreement between models
        agreement = 0
        if result_a and result_b:
            cats_a = {p.get("nazwa"): p.get("kategoria") for p in result_a}
            cats_b = {p.get("nazwa"): p.get("kategoria") for p in result_b}
            common_names = set(cats_a.keys()) & set(cats_b.keys())
            if common_names:
                agreement = sum(1 for n in common_names if cats_a[n] == cats_b[n]) / len(common_names)

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "model_a": model_a,
            "model_b": model_b,
            "products_count": products_count,
            "time_a_sec": round(time_a, 2),
            "time_b_sec": round(time_b, 2),
            "error_a": error_a,
            "error_b": error_b,
            "agreement": round(agreement, 3),
            "categories_a": [p.get("kategoria") for p in result_a] if result_a else [],
            "categories_b": [p.get("kategoria") for p in result_b] if result_b else [],
        }

        with open(AB_TEST_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        logger.info(
            f"A/B test: {model_a} vs {model_b} | "
            f"Agreement: {agreement:.1%} | "
            f"Time: {time_a:.1f}s vs {time_b:.1f}s"
        )
    except Exception as e:
        logger.warning(f"Failed to log A/B result: {e}")


async def _call_classifier_model(
    model: str,
    prompt: str,
    timeout: float = 120.0,
) -> tuple[Optional[list[dict]], float, Optional[str]]:
    """
    Call a specific classifier model using connection pooling.

    Returns:
        Tuple of (parsed products list, time in seconds, error message or None)
    """
    start_time = time.time()

    raw_response, error = await ollama_client.post_generate(
        model=model,
        prompt=prompt,
        options={"temperature": 0.1},
        timeout=timeout,
        keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
    )

    elapsed = time.time() - start_time

    if error:
        logger.error(f"Classifier error for {model}: {error}")
        return None, elapsed, error
    logger.debug(f"Raw classifier response from {model}: {raw_response}")

    try:
        json_str = raw_response
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]
        json_str = json_str.strip()
        data = json.loads(json_str)
        return data.get("products", []), elapsed, None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse classifier response from {model}: {e}")
        return None, elapsed, f"JSON parse error: {e}"


CATEGORIZATION_PROMPT = """Skategoryzuj poniższe produkty spożywcze.

Dostępne kategorie:
{categories}

Produkty do kategoryzacji:
{products}

Zwróć odpowiedź TYLKO jako poprawny JSON w formacie:
{{
  "products": [
    {{"nazwa": "nazwa produktu", "cena": 12.99, "kategoria": "Nabiał", "confidence": 0.95}},
    {{"nazwa": "inny produkt", "cena": 5.49, "kategoria": "Pieczywo", "confidence": 0.88}}
  ]
}}

Zasady:
- Użyj TYLKO kategorii z podanej listy
- confidence to pewność przypisania (0.0-1.0)
- Jeśli produkt nie pasuje do żadnej kategorii, użyj "Inne"
- Zachowaj oryginalne nazwy i ceny produktów
- Zwróć TYLKO JSON, bez dodatkowego tekstu"""


async def categorize_products(products: list[Product]) -> tuple[list[CategorizedProduct], Optional[str]]:
    """
    Categorize products using configured classifier model(s).

    Supports A/B testing when CLASSIFIER_MODEL_B is set:
    - "primary" mode: use CLASSIFIER_MODEL, optionally log B results
    - "secondary" mode: use CLASSIFIER_MODEL_B as primary
    - "both" mode: run both models, use primary, log comparison

    Returns:
        Tuple of (list of CategorizedProduct, error message or None)
    """
    if not products:
        return [], None

    # Optimization: separate products that need LLM categorization from already-categorized
    # Products with dictionary category (confidence >= 0.6) don't need LLM
    needs_llm = []
    already_categorized = []

    for p in products:
        if p.kategoria and p.confidence and p.confidence >= 0.6:
            # Already has good category from dictionary - skip LLM
            already_categorized.append(CategorizedProduct(
                nazwa=p.nazwa,
                cena=p.cena,
                kategoria=p.kategoria,
                confidence=p.confidence,
                warning=p.warning,
                nazwa_oryginalna=p.nazwa_oryginalna,
                nazwa_znormalizowana=p.nazwa_znormalizowana,
                cena_oryginalna=p.cena_oryginalna,
                rabat=p.rabat,
            ))
        else:
            needs_llm.append(p)

    # If all products are already categorized, skip LLM entirely
    if not needs_llm:
        logger.info(f"All {len(already_categorized)} products already categorized by dictionary - skipping LLM")
        return already_categorized, None

    logger.info(f"Categorizing {len(needs_llm)} products with LLM ({len(already_categorized)} already categorized)")

    products_text = "\n".join([
        f"- {p.nazwa} ({p.cena} zł)"
        for p in needs_llm
    ])

    categories_text = "\n".join([f"- {c}" for c in settings.CATEGORIES])

    prompt = CATEGORIZATION_PROMPT.format(
        categories=categories_text,
        products=products_text
    )

    # Determine which model(s) to use
    model_a = settings.CLASSIFIER_MODEL
    model_b = settings.CLASSIFIER_MODEL_B
    ab_mode = settings.CLASSIFIER_AB_MODE

    # Select primary model based on mode
    if ab_mode == "secondary" and model_b:
        primary_model = model_b
    else:
        primary_model = model_a

    # A/B testing: run both models in PARALLEL if configured
    result_b = None
    time_b = 0.0
    error_b = None

    if model_b and ab_mode in ("primary", "both"):
        secondary_model = model_b if ab_mode == "primary" else model_a
        if secondary_model != primary_model:
            # Run BOTH models in parallel for A/B testing (saves ~7-30s)
            logger.info(f"A/B test: running {primary_model} and {secondary_model} in parallel")
            results = await asyncio.gather(
                _call_classifier_model(primary_model, prompt),
                _call_classifier_model(secondary_model, prompt),
            )
            result_a, time_a, error_a = results[0]
            result_b, time_b, error_b = results[1]

            # Log comparison
            _log_ab_result(
                model_a=primary_model,
                model_b=secondary_model,
                products_count=len(products),
                result_a=result_a or [],
                result_b=result_b or [],
                time_a=time_a,
                time_b=time_b,
                error_a=error_a,
                error_b=error_b,
            )
        else:
            # Same model for A and B - just call once
            result_a, time_a, error_a = await _call_classifier_model(primary_model, prompt)
    else:
        # No A/B testing - just call primary model
        result_a, time_a, error_a = await _call_classifier_model(primary_model, prompt)

    # Handle primary model failure
    if error_a or result_a is None:
        logger.error(f"Classifier error: {error_a}")
        # Return already_categorized + fallback for needs_llm
        return already_categorized + _fallback_categorization(needs_llm), f"Classifier error: {error_a}"

    data = {"products": result_a}

    # Build categorized products from LLM response
    llm_categorized = []
    original_map = {p.nazwa: p for p in needs_llm}

    for p in data.get("products", []):
        try:
            name = str(p.get("nazwa", "")).strip()
            category = str(p.get("kategoria", "Inne")).strip()
            confidence = float(p.get("confidence", 0.5))

            # Validate category
            if category not in settings.CATEGORIES:
                category = "Inne"
                confidence = 0.5

            # Get original product data
            original = original_map.get(name)
            price = float(p.get("cena", original.cena if original else 0))
            warning = original.warning if original else None

            llm_categorized.append(CategorizedProduct(
                nazwa=name,
                cena=price,
                kategoria=category,
                confidence=confidence,
                warning=warning,
                # Pass through normalization and discount fields
                nazwa_oryginalna=original.nazwa_oryginalna if original else None,
                nazwa_znormalizowana=original.nazwa_znormalizowana if original else None,
                cena_oryginalna=original.cena_oryginalna if original else None,
                rabat=original.rabat if original else None,
            ))
        except (ValueError, TypeError) as e:
            logger.warning(f"Skipping invalid categorized product: {p} - {e}")
            continue

    # Add any missing products from needs_llm with fallback category
    categorized_names = {p.nazwa for p in llm_categorized}
    for product in needs_llm:
        if product.nazwa not in categorized_names:
            # Use dictionary category if available, otherwise "Inne"
            category = product.kategoria if product.kategoria else "Inne"
            confidence = product.confidence if product.confidence else 0.0
            llm_categorized.append(CategorizedProduct(
                nazwa=product.nazwa,
                cena=product.cena,
                kategoria=category,
                confidence=confidence,
                warning=product.warning,
                nazwa_oryginalna=product.nazwa_oryginalna,
                nazwa_znormalizowana=product.nazwa_znormalizowana,
                cena_oryginalna=product.cena_oryginalna,
                rabat=product.rabat,
            ))

    # Combine already_categorized (from dictionary) + llm_categorized
    return already_categorized + llm_categorized, None


def _fallback_categorization(products: list[Product]) -> list[CategorizedProduct]:
    """Fallback categorization when classifier fails. Uses dictionary category if available."""
    return [
        CategorizedProduct(
            nazwa=p.nazwa,
            cena=p.cena,
            kategoria=p.kategoria if p.kategoria else "Inne",
            confidence=p.confidence if p.confidence else 0.0,
            warning=p.warning,
            nazwa_oryginalna=p.nazwa_oryginalna,
            nazwa_znormalizowana=p.nazwa_znormalizowana,
            cena_oryginalna=p.cena_oryginalna,
            rabat=p.rabat,
        )
        for p in products
    ]
