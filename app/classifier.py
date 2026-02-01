"""Product categorization using qwen2.5:7b via Ollama."""

import json
import logging
from typing import Optional

import httpx

from app.config import settings
from app.models import CategorizedProduct, Product

logger = logging.getLogger(__name__)

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
    Categorize products using qwen2.5:7b.

    Returns:
        Tuple of (list of CategorizedProduct, error message or None)
    """
    if not products:
        return [], None

    products_text = "\n".join([
        f"- {p.nazwa} ({p.cena} zł)"
        for p in products
    ])

    categories_text = "\n".join([f"- {c}" for c in settings.CATEGORIES])

    prompt = CATEGORIZATION_PROMPT.format(
        categories=categories_text,
        products=products_text
    )

    payload = {
        "model": settings.CLASSIFIER_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1
        }
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json=payload
            )
            response.raise_for_status()
            result = response.json()
    except httpx.TimeoutException:
        logger.error("Classifier timeout")
        # Fallback: return products with "Inne" category
        return _fallback_categorization(products), "Classifier timeout - using fallback"
    except httpx.HTTPError as e:
        logger.error(f"Classifier HTTP error: {e}")
        return _fallback_categorization(products), f"Classifier error: {e}"

    raw_response = result.get("response", "")
    logger.debug(f"Raw classifier response: {raw_response}")

    try:
        json_str = raw_response

        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]

        json_str = json_str.strip()
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse classifier response: {e}")
        return _fallback_categorization(products), f"Failed to parse response: {e}"

    # Build categorized products
    categorized = []
    original_map = {p.nazwa: p for p in products}

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

            # Use dictionary category if available with high confidence
            if original and original.kategoria and original.confidence and original.confidence >= 0.6:
                # Dictionary has higher priority than LLM for known products
                category = original.kategoria
                confidence = max(confidence, original.confidence)

            categorized.append(CategorizedProduct(
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

    # Add any missing products with fallback category
    categorized_names = {p.nazwa for p in categorized}
    for product in products:
        if product.nazwa not in categorized_names:
            # Use dictionary category if available
            category = product.kategoria if product.kategoria else "Inne"
            confidence = product.confidence if product.confidence else 0.0
            categorized.append(CategorizedProduct(
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

    return categorized, None


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
