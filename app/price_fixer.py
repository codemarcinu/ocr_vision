"""Post-processor for detecting and flagging suspicious product prices.

This module detects products that may have incorrect prices extracted by OCR,
particularly weighted products where the unit price (per kg) was extracted
instead of the final calculated price.
"""

import logging
import re
from typing import Optional

from app.models import Product

logger = logging.getLogger(__name__)

# Patterns that indicate weighted products (sold by kg)
WEIGHTED_PRODUCT_PATTERNS = [
    r'\bkg\b',           # Contains "kg"
    r'\b\d+[.,]\d{3}\b', # Contains weight like 0.279, 1.234
]

# Product name patterns that are typically sold by weight
WEIGHTED_NAME_PATTERNS = [
    r'^bocz',      # Boczek, BoczWędz
    r'^wedz',      # Wędlina, Wędzony
    r'^wedl',      # Wędlina
    r'^szyn',      # Szynka
    r'^ser\b',     # Ser (cheese)
    r'^serek',     # Serek
    r'pomidor',    # Pomidory
    r'ogórek|ogorek',  # Ogórki
    r'jabłk|jablk',    # Jabłka
    r'banan',      # Banany
    r'ziemniak',   # Ziemniaki
    r'marchew',    # Marchew
    r'cebul',      # Cebula
    r'kapust',     # Kapusta
    r'sałat|salat',    # Sałata
    r'papryka',    # Papryka
    r'cytry',      # Cytryny
    r'pomarańcz|pomarancz',  # Pomarańcze
    r'gruszk',     # Gruszki
    r'śliwk|sliwk',    # Śliwki
    r'winogrono',  # Winogrona
    r'kiwi',       # Kiwi
    r'mięs|mies',  # Mięso
    r'kurczak',    # Kurczak
    r'filet',      # Filet
    r'schab',      # Schab
    r'kark[oó]wka|karkowka',  # Karkówka
    r'żeber|zeber',    # Żeberka
    r'kiełbas|kielbas',  # Kiełbasa
    r'parówk|parowk',  # Parówki
]

# Price thresholds for flagging suspicious prices
GENERAL_PRICE_THRESHOLD = 40.0   # Most grocery items are below this
MEAT_PRICE_THRESHOLD = 60.0      # Meat products can be more expensive
PREMIUM_PRICE_THRESHOLD = 80.0   # Very few items exceed this

# Meat-related patterns (allow higher prices)
MEAT_PATTERNS = [
    r'^bocz',
    r'^wedz',
    r'^wedl',
    r'^szyn',
    r'mięs|mies',
    r'kurczak',
    r'filet',
    r'schab',
    r'kark[oó]wka|karkowka',
    r'żeber|zeber',
    r'kiełbas|kielbas',
    r'wołow|wolow',
    r'wieprz',
    r'indyk',
    r'kaczk',
    r'łosos|losos',
    r'dorsz',
    r'pstrąg|pstrag',
]


def is_weighted_product(product: Product) -> bool:
    """Check if product is likely sold by weight (kg)."""
    name_lower = product.nazwa.lower()

    # Check name patterns
    for pattern in WEIGHTED_NAME_PATTERNS:
        if re.search(pattern, name_lower, re.IGNORECASE):
            return True

    # Check if name contains "kg" indicator
    for pattern in WEIGHTED_PRODUCT_PATTERNS:
        if re.search(pattern, name_lower, re.IGNORECASE):
            return True

    return False


def is_meat_product(product: Product) -> bool:
    """Check if product is a meat product (allows higher price threshold)."""
    name_lower = product.nazwa.lower()

    for pattern in MEAT_PATTERNS:
        if re.search(pattern, name_lower, re.IGNORECASE):
            return True

    return False


def get_price_threshold(product: Product) -> float:
    """Get appropriate price threshold for product type."""
    if is_meat_product(product):
        return MEAT_PRICE_THRESHOLD
    return GENERAL_PRICE_THRESHOLD


def check_suspicious_price(product: Product) -> Optional[str]:
    """
    Check if product price looks suspicious (possibly unit price instead of total).

    Returns warning message if suspicious, None otherwise.
    """
    price = product.cena
    threshold = get_price_threshold(product)

    # Check if price exceeds threshold
    if price <= threshold:
        return None

    # Weighted products with high prices are most suspicious
    if is_weighted_product(product):
        if price > threshold:
            return (
                f"Possible unit price (per kg) instead of total. "
                f"Price {price:.2f} zł exceeds threshold {threshold:.2f} zł for weighted product."
            )

    # Non-weighted products with very high prices
    if price > PREMIUM_PRICE_THRESHOLD:
        return (
            f"Unusually high price {price:.2f} zł. "
            f"Verify this is correct and not a subtotal or unit price."
        )

    return None


def fix_products(products: list[Product]) -> tuple[list[Product], list[str]]:
    """
    Process products and add warnings for suspicious prices.

    This function does NOT modify prices - it only adds warnings.
    Human review can then decide if correction is needed.

    Args:
        products: List of Product objects from OCR

    Returns:
        Tuple of (processed products, list of warning messages)
    """
    warnings = []

    for product in products:
        warning = check_suspicious_price(product)

        if warning:
            # Add warning to product
            if product.warning:
                product.warning = f"{product.warning}; {warning}"
            else:
                product.warning = warning

            logger.warning(f"Price warning for '{product.nazwa}': {warning}")
            warnings.append(f"{product.nazwa}: {warning}")

    if warnings:
        logger.info(f"Price fixer flagged {len(warnings)} suspicious prices")

    return products, warnings
