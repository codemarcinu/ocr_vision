"""Store-specific prompts for receipt OCR structuring."""

import re
from typing import Optional

# Store detection patterns (lowercase)
STORE_PATTERNS = {
    "biedronka": [
        r"biedronka",
        r"jeronimo\s*martins",
        r"jm\s*polska",
    ],
    "lidl": [
        r"lidl",
    ],
    "kaufland": [
        r"kaufland",
    ],
    "zabka": [
        r"[żz]abka",
        r"zabka",
    ],
    "auchan": [
        r"auchan",
    ],
    "carrefour": [
        r"carrefour",
    ],
    "netto": [
        r"netto",
    ],
    "dino": [
        r"dino\s*(polska)?",
        r"dino\s*market",
    ],
    "lewiatan": [
        r"lewiatan",
    ],
    "polo_market": [
        r"polo\s*market",
        r"polomarket",
    ],
    "stokrotka": [
        r"stokrotka",
    ],
    "intermarche": [
        r"intermarch[eé]",
    ],
}


def detect_store_from_text(text: str) -> Optional[str]:
    """Detect store name from raw OCR text."""
    text_lower = text.lower()

    for store, patterns in STORE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return store

    return None


# =============================================================================
# STORE-SPECIFIC PROMPTS
# =============================================================================

PROMPT_BIEDRONKA = """You are analyzing a receipt from BIEDRONKA (Jeronimo Martins) - a Polish grocery store.

CRITICAL RULES - READ CAREFULLY:

1. EACH PRODUCT OCCURRENCE IS A SEPARATE ITEM
   If "Kalafior" appears 3 times with different prices - that's 3 SEPARATE products in JSON!
   DO NOT merge duplicates. Each product line = separate object in products array.

2. PRICE = LAST NUMBER IN THE BLOCK (after Rabat/discount if present)

   EXAMPLE WITH DISCOUNT (weighted product):
   ```
   BoczWędzKraWęd kg    C   0.396 ×   28,20    11,17
     Rabat                                     -3,29
                                                7,88
   ```
   28,20 = price per kg (IGNORE)
   11,17 = value before discount (this is cena_przed)
   -3,29 = discount
   7,88 = FINAL PRICE (this is cena!)

   → {"nazwa":"BoczWędzKraWęd kg","cena":7.88,"cena_przed":11.17,"rabat":3.29}

   EXAMPLE WITH DISCOUNT (unit product):
   ```
   Banan Luz            C   1.005 ×    6,99     7,02
     Rabat                                     -2,01
                                                5,01
   ```
   → {"nazwa":"Banan Luz","cena":5.01,"cena_przed":7.02,"rabat":2.01}

   EXAMPLE WITHOUT DISCOUNT:
   ```
   Mleko UHT 1,5 1l     C   1.000 ×    2,85     2,85
   ```
   → {"nazwa":"Mleko UHT 1,5 1l","cena":2.85}

3. PRODUCT BLOCK STRUCTURE:
   Line 1: ProductName  PTU  Qty×  UnitPrice  Value
   Line 2: (optional) Rabat                   -X,XX
   Line 3: (optional)                         FinalPrice

   ALWAYS take the LAST number before the next product!

4. COMPLETELY IGNORE:
   - "Sprzedaż opodatkowana" - NOT a product
   - "PTU A/C 5%/23%" - this is tax
   - "Suma PTU" - tax sum
   - "Karta płatnicza", "Gotówka" - payment method
   - Page numbers "Strona X z Y"

5. TOTAL: Value at "Suma PLN" (e.g., 144,48 → suma: 144.48)

REQUIRED JSON FORMAT (prices with dot decimal, EACH product separately):
{"products":[{"nazwa":"Kalafior","cena":2.79,"cena_przed":4.19,"rabat":1.40},{"nazwa":"Kalafior","cena":2.80,"cena_przed":4.19,"rabat":1.39}],"sklep":"Biedronka","data":"2026-01-31","suma":144.48}

RECEIPT TEXT:
"""

PROMPT_LIDL = """You are analyzing a receipt from LIDL - a Polish grocery store.

LIDL RECEIPT FORMAT:
```
Product name
   Qty × Price = Value  [VAT rate]
   RABAT -X,XX
```

EXTRACTION RULES:
1. Product name is on a separate line
2. Below is the line with quantity, unit price and value
3. Discount (if any) appears as separate line "RABAT -X,XX"
4. PRICE = Final value (after discount if present)

5. IGNORE:
   - VAT/PTU lines
   - "SUMA", "DO ZAPŁATY"
   - Deposits, returnable packaging

6. TOTAL: "DO ZAPŁATY" or "SUMA PLN"
7. DATE: Format at the top of receipt

RETURN ONLY JSON:
{"products":[{"nazwa":"product","cena":5.99,"cena_przed":7.99,"rabat":2.00}],"sklep":"Lidl","data":"2026-01-31","suma":45.67}

RECEIPT TEXT:
"""

PROMPT_KAUFLAND = """You are analyzing a receipt from KAUFLAND - a Polish grocery store.

KAUFLAND RECEIPT FORMAT:
```
PRODUCT NAME                      PRICE
  Rabat promocyjny               -X,XX
                                 PRICE_AFTER_DISCOUNT
```

EXTRACTION RULES:
1. Product name in uppercase, price on the right
2. Discount (if any) as separate line with minus
3. Final price = last number in the product block

4. IGNORE:
   - VAT, PTU
   - "SUMA DO ZAPŁATY"
   - Deposits

5. TOTAL: "SUMA DO ZAPŁATY" or "RAZEM"
6. DATE: At the top or bottom of receipt

RETURN ONLY JSON:
{"products":[{"nazwa":"product","cena":5.99}],"sklep":"Kaufland","data":"2026-01-31","suma":45.67}

RECEIPT TEXT:
"""

PROMPT_ZABKA = """You are analyzing a receipt from ŻABKA - a Polish convenience store.

ŻABKA RECEIPT FORMAT:
```
Product name          Price
```

EXTRACTION RULES:
1. Simple format: product name and price on one line
2. Promotions may be marked with asterisk (*) or "PROMO"
3. Żabka often has short product names

4. IGNORE:
   - VAT, PTU
   - "SUMA", "DO ZAPŁATY"
   - Phone top-ups
   - Payments, change

5. TOTAL: "DO ZAPŁATY" or "SUMA"
6. DATE: At the top of receipt

RETURN ONLY JSON:
{"products":[{"nazwa":"product","cena":5.99}],"sklep":"Żabka","data":"2026-01-31","suma":25.50}

RECEIPT TEXT:
"""

PROMPT_AUCHAN = """You are analyzing a receipt from AUCHAN - a Polish hypermarket.

AUCHAN RECEIPT FORMAT:
```
PRODUCT NAME
   Qty × Unit price = Value   Rate%
   Rabat: -X,XX
```

EXTRACTION RULES:
1. Product name on separate line (often uppercase)
2. Details (quantity, price) on next line
3. Discount as separate line
4. PRICE = final value after discount

5. IGNORE: VAT, PTU, deposits, packaging
6. TOTAL: "RAZEM DO ZAPŁATY" or "SUMA"

RETURN ONLY JSON:
{"products":[{"nazwa":"product","cena":5.99}],"sklep":"Auchan","data":"2026-01-31","suma":89.99}

RECEIPT TEXT:
"""

PROMPT_CARREFOUR = """You are analyzing a receipt from CARREFOUR - a Polish supermarket.

CARREFOUR RECEIPT FORMAT:
```
Product name                Price   Rate
  RABAT                      -X,XX
```

EXTRACTION RULES:
1. Product name with price on the same line
2. Discounts as separate lines with minus
3. PRICE = price after discount (if discount exists)

4. IGNORE: VAT, PTU, deposits
5. TOTAL: "DO ZAPŁATY" or "RAZEM"

RETURN ONLY JSON:
{"products":[{"nazwa":"product","cena":5.99}],"sklep":"Carrefour","data":"2026-01-31","suma":67.89}

RECEIPT TEXT:
"""

PROMPT_NETTO = """You are analyzing a receipt from NETTO - a Polish discount store.

NETTO RECEIPT FORMAT:
```
Product name              Price
RABAT                      -X,XX
```

EXTRACTION RULES:
1. Simple format: name and price
2. Discounts on separate lines
3. PRICE = final price after discount

4. IGNORE: VAT, PTU
5. TOTAL: "SUMA" or "DO ZAPŁATY"

RETURN ONLY JSON:
{"products":[{"nazwa":"product","cena":5.99}],"sklep":"Netto","data":"2026-01-31","suma":45.00}

RECEIPT TEXT:
"""

PROMPT_DINO = """You are analyzing a receipt from DINO - a Polish grocery store.

DINO RECEIPT FORMAT:
```
PRODUCT NAME              PRICE    RATE
  Rabat                    -X,XX
```

EXTRACTION RULES:
1. Product names often in uppercase
2. Discounts as separate lines
3. PRICE = price after discount

4. IGNORE: VAT, PTU, deposits
5. TOTAL: "SUMA" or "DO ZAPŁATY"

RETURN ONLY JSON:
{"products":[{"nazwa":"product","cena":5.99}],"sklep":"Dino","data":"2026-01-31","suma":55.00}

RECEIPT TEXT:
"""

PROMPT_GENERIC = """You are analyzing text from a Polish store receipt.

TASK: Extract products, store name, date and total.

GENERAL RULES:
1. PRODUCTS: Each line with name and price is a product
2. PRICE: Use the FINAL price (after discount, if any)
3. DISCOUNT: If there's a discount line (-X,XX), subtract from previous price
4. STORE: Look for store name at the top of receipt
5. DATE: Format YYYY-MM-DD
6. TOTAL: Amount at "DO ZAPŁATY", "SUMA", "RAZEM" or "Karta płatnicza"

IGNORE:
- VAT/PTU lines (these are taxes)
- Deposits, returnable packaging
- Payment information (except total)

RESPONSE FORMAT (ONLY JSON):
{"products":[{"nazwa":"name","cena":1.99,"cena_przed":2.99,"rabat":1.00}],"sklep":"name","data":"2026-01-31","suma":50.00}

RECEIPT TEXT:
"""

# Mapping store names to prompts
STORE_PROMPTS = {
    "biedronka": PROMPT_BIEDRONKA,
    "lidl": PROMPT_LIDL,
    "kaufland": PROMPT_KAUFLAND,
    "zabka": PROMPT_ZABKA,
    "auchan": PROMPT_AUCHAN,
    "carrefour": PROMPT_CARREFOUR,
    "netto": PROMPT_NETTO,
    "dino": PROMPT_DINO,
    "lewiatan": PROMPT_GENERIC,  # Use generic for less common stores
    "polo_market": PROMPT_GENERIC,
    "stokrotka": PROMPT_GENERIC,
    "intermarche": PROMPT_GENERIC,
}


_FORBIDDEN = """

FORBIDDEN (STRICTLY ENFORCE):
- Do NOT add products not visible on the receipt
- Do NOT guess or invent prices — use EXACTLY what's printed
- Do NOT round amounts (3.49 is NOT 3.50)
- Do NOT add default items (bag, salt, water) unless printed on receipt
- Do NOT invent dates if unreadable — leave empty
- Do NOT rename products to "correct" names — transcribe as-is
"""


def get_prompt_for_store(store: Optional[str]) -> str:
    """Get the appropriate prompt for a given store."""
    if store and store.lower() in STORE_PROMPTS:
        return STORE_PROMPTS[store.lower()] + _FORBIDDEN
    return PROMPT_GENERIC + _FORBIDDEN


def get_store_display_name(store_key: Optional[str]) -> str:
    """Convert store key to display name."""
    display_names = {
        "biedronka": "Biedronka",
        "lidl": "Lidl",
        "kaufland": "Kaufland",
        "zabka": "Żabka",
        "auchan": "Auchan",
        "carrefour": "Carrefour",
        "netto": "Netto",
        "dino": "Dino",
        "lewiatan": "Lewiatan",
        "polo_market": "Polo Market",
        "stokrotka": "Stokrotka",
        "intermarche": "Intermarché",
    }
    if store_key:
        return display_names.get(store_key.lower(), store_key.title())
    return "Unknown"
