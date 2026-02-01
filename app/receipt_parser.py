"""Hybrid receipt parser: Regex extraction + LLM name cleaning."""

import re
import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Debug flag - set to True for verbose parsing output
DEBUG_PARSER = False


@dataclass
class DiscountInfo:
    """Information about a single discount."""
    typ: str  # "kwotowy" or "procentowy"
    wartosc: float  # Amount in PLN or percentage value
    opis: str = "Rabat"  # Description (Rabat, Promocja, Zniżka, etc.)


@dataclass
class ParsedProduct:
    """Product extracted via regex."""
    nazwa: str
    cena: float  # Final price (after discount)
    cena_przed: Optional[float] = None  # Price before discount
    rabat: Optional[float] = None  # Total discount amount
    rabaty_szczegoly: Optional[list[DiscountInfo]] = None  # Detailed discounts


@dataclass
class ParsedReceipt:
    """Receipt data extracted via regex."""
    products: list[ParsedProduct]
    sklep: Optional[str] = None
    data: Optional[str] = None
    suma: Optional[float] = None
    raw_text: str = ""


@dataclass
class ProductBlock:
    """Temporary structure for collecting product data during parsing."""
    name: str
    ptu: Optional[str] = None
    quantity: Optional[float] = None
    prices: list = field(default_factory=list)
    rabat: Optional[float] = None  # Total discount (for backwards compat)
    rabaty: list = field(default_factory=list)  # List of DiscountInfo
    has_rabat_marker: bool = False
    last_rabat_type: Optional[str] = None  # Type of last seen discount marker


def parse_biedronka_receipt(raw_text: str) -> ParsedReceipt:
    """
    Parse Biedronka receipt using regex.

    Biedronka receipt format (tabular, but OCR outputs line-by-line):
    ```
    ProductName   PTU   Qty×   UnitPrice   LineTotal
      Rabat                                -Discount
                                           FinalPrice
    ```

    Key insight: Final price is the LAST number in a product block.
    When there's a Rabat, the sequence is: [prices...] → Rabat → -discount → final_price
    """
    products = []

    # Split into lines and clean
    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]

    # Store detection
    store = "Biedronka" if re.search(r'biedronka', raw_text, re.IGNORECASE) else None

    # Date extraction (DD.MM.YYYY)
    date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', raw_text)
    date = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}" if date_match else None

    # Total extraction - prioritize "Suma PLN" and "Karta płatnicza"
    suma = None
    suma_match = re.search(r'suma\s*pln\s*(\d+[\.,]\d+)', raw_text, re.IGNORECASE)
    if suma_match:
        suma = float(suma_match.group(1).replace(',', '.'))
    else:
        karta_match = re.search(r'karta\s*p[łl]atnicza\s*(\d+[\.,]\d+)', raw_text, re.IGNORECASE)
        if karta_match:
            suma = float(karta_match.group(1).replace(',', '.'))

    # Patterns - more flexible for OCR variations
    # Product name: starts with letter, 3+ chars
    product_name_pattern = re.compile(r'^[A-Za-zżźćńółęąśŻŹĆŃÓŁĘĄŚ][A-Za-zżźćńółęąśŻŹĆŃÓŁĘĄŚ0-9\s\.\,\-]+$')
    # PTU category (can have trailing space/chars from OCR)
    ptu_pattern = re.compile(r'^[AaBbCc0]\s*$')
    # Quantity line - flexible matching (e.g., "1.000 x", "0.396 x", "1,000x")
    qty_pattern = re.compile(r'^(\d+[\.,]\d{3})\s*[x×]?\s*$')
    # Price/number line - just a number (with optional minus), 1-2 decimal digits
    price_pattern = re.compile(r'^-?(\d+[\.,]\d{1,2})$')
    # Discount markers - expanded to handle Promocja, Zniżka, Upust
    rabat_pattern = re.compile(r'^([Rr]abat|[Pp]romocja|[Zz]ni[żz]ka|[Uu]pust)\s*$')
    # Percentage discount: "Promocja -30%", "Rabat 20%", "-30%"
    rabat_procent_pattern = re.compile(r'^(?:[Rr]abat|[Pp]romocja|[Zz]ni[żz]ka|[Uu]pust)?\s*-?(\d+)\s*%\s*$')
    # Amount discount with label: "Rabat -3.29", "Promocja -2.00"
    rabat_kwotowy_pattern = re.compile(r'^([Rr]abat|[Pp]romocja|[Zz]ni[żz]ka|[Uu]pust)\s*-?(\d+[\.,]\d{2})\s*$')

    # Single-line product pattern (when OCR outputs entire line together)
    # e.g., "KalafiorMroźnKr450g C 1.000 × 4,19 4,19"
    single_line_pattern = re.compile(
        r'^([A-Za-zżźćńółęąśŻŹĆŃÓŁĘĄŚ][A-Za-zżźćńółęąśŻŹĆŃÓŁĘĄŚ0-9\s\.\-]+?)\s+'  # Product name
        r'([AaCc0])\s+'  # PTU
        r'(\d+[\.,]\d{3})\s*[x×]\s*'  # Quantity
        r'(\d+[\.,]\d{2})\s+'  # Unit price
        r'(\d+[\.,]\d{2})'  # Line total
        r'(?:\s+(-?\d+[\.,]\d{2}))?'  # Optional rabat
        r'(?:\s+(\d+[\.,]\d{2}))?'  # Optional final price
        r'\s*$'
    )

    # Skip patterns - expanded with OCR artifacts
    skip_patterns = [
        r'sprzeda[żz]', r'opodatkowana', r'ptu\s', r'suma', r'karta', r'p[łl]atnicza',
        r'got[oó]wka', r'strona\s*\d', r'kasa\s*\d', r'paragon', r'fiskalny', r'niefiskalny',
        r'nip\s', r'biedronka', r'sklep\s*\d', r'jeronimo', r'martins', r'^nazwa$', r'^warto[sś][cć]$',
        r'^cena$', r'^ilo[sś][cć]$', r'kasjer', r'^io\$', r'^warto', r'^i[lo]\$',  # OCR artifacts
        r'^\d+/\d+/\d+',  # Transaction numbers like 3218/11/1086
        r'^100\d{10,}$',  # Barcodes
        r'numer\s*trans',
    ]
    skip_regex = re.compile('|'.join(skip_patterns), re.IGNORECASE)

    def try_parse_single_line(line: str) -> Optional[ParsedProduct]:
        """Try to parse a complete product from a single line."""
        match = single_line_pattern.match(line)
        if not match:
            return None

        name = match.group(1).strip()
        # Skip header lines
        if skip_regex.search(name):
            return None

        line_total = float(match.group(5).replace(',', '.'))
        rabat_str = match.group(6)
        final_str = match.group(7)

        if rabat_str and final_str:
            # Has both rabat and final price
            rabat = abs(float(rabat_str.replace(',', '.')))
            final_price = float(final_str.replace(',', '.'))
            return ParsedProduct(nazwa=name, cena=final_price, cena_przed=line_total, rabat=rabat)
        elif rabat_str:
            # Rabat but no final (final = line_total - rabat)
            rabat = abs(float(rabat_str.replace(',', '.')))
            final_price = round(line_total - rabat, 2)
            return ParsedProduct(nazwa=name, cena=final_price, cena_przed=line_total, rabat=rabat)
        else:
            # No discount
            return ParsedProduct(nazwa=name, cena=line_total)

    def is_product_name(line: str) -> bool:
        """Check if line looks like a product name."""
        if len(line) < 3:
            return False
        if skip_regex.search(line):
            return False
        if price_pattern.match(line):
            return False
        if ptu_pattern.match(line):
            return False
        if qty_pattern.match(line):
            return False
        if rabat_pattern.match(line):
            return False
        if not product_name_pattern.match(line):
            return False
        # Must contain at least 2 letters
        letter_count = sum(1 for c in line if c.isalpha())
        return letter_count >= 2

    def finalize_product(block: ProductBlock) -> Optional[ParsedProduct]:
        """Convert a product block to ParsedProduct with correct price."""
        if not block.prices:
            return None

        if DEBUG_PARSER:
            logger.info(f"Finalizing: {block.name}, prices={block.prices}, rabat={block.rabat}, rabaty={block.rabaty}")

        final_price = None
        cena_przed = None

        # Calculate total rabat from all discounts
        total_rabat = 0.0
        rabaty_szczegoly = []

        if block.rabaty:
            # Use detailed discounts
            for discount in block.rabaty:
                if discount.typ == "kwotowy":
                    total_rabat += discount.wartosc
                    rabaty_szczegoly.append(discount)
                elif discount.typ == "procentowy":
                    # Percentage discount - will be calculated after we know the base price
                    rabaty_szczegoly.append(discount)
        elif block.rabat is not None:
            # Backwards compatibility: use single rabat value
            total_rabat = block.rabat
            rabaty_szczegoly.append(DiscountInfo(typ="kwotowy", wartosc=block.rabat, opis="Rabat"))

        has_discount = total_rabat > 0 or block.rabat is not None or block.rabaty

        if has_discount and len(block.prices) >= 2:
            # Product with discount
            # Pattern: [unit_price?, line_total, final_price] with rabat in between
            # Final price is ALWAYS the last price after rabat
            final_price = block.prices[-1]

            # Find cena_przed (price before discount)
            # It's the price just before final_price that's greater than final_price
            for price in reversed(block.prices[:-1]):
                if price > final_price:
                    cena_przed = price
                    break

            # Handle percentage discounts now that we have cena_przed
            for discount in rabaty_szczegoly:
                if discount.typ == "procentowy" and cena_przed:
                    # Calculate actual amount from percentage
                    pct_amount = round(cena_przed * discount.wartosc / 100, 2)
                    total_rabat += pct_amount

            # Use single rabat for validation if no detailed discounts
            rabat_for_validation = total_rabat if total_rabat > 0 else (block.rabat or 0)

            # Validate: cena_przed - rabat should ≈ final_price
            if cena_przed and rabat_for_validation and abs((cena_przed - rabat_for_validation) - final_price) > 0.02:
                # Maybe we got wrong cena_przed, try to find correct one
                for price in block.prices[:-1]:
                    if abs((price - rabat_for_validation) - final_price) <= 0.02:
                        cena_przed = price
                        break

        elif has_discount and len(block.prices) == 1:
            # Single price with rabat - price is final, calculate original
            final_price = block.prices[0]
            rabat_for_calc = total_rabat if total_rabat > 0 else (block.rabat or 0)
            cena_przed = round(final_price + rabat_for_calc, 2)

        else:
            # No discount - last price is final (handles duplicates like 2.85, 2.85)
            final_price = block.prices[-1]
            total_rabat = 0
            cena_przed = None
            rabaty_szczegoly = None

        # Final rabat value
        rabat = total_rabat if total_rabat > 0 else block.rabat

        if final_price is not None and 0 < final_price < 500:
            if DEBUG_PARSER:
                logger.info(f"  → cena={final_price}, przed={cena_przed}, rabat={rabat}, szczegoly={rabaty_szczegoly}")
            return ParsedProduct(
                nazwa=block.name,
                cena=final_price,
                cena_przed=cena_przed,
                rabat=rabat,
                rabaty_szczegoly=rabaty_szczegoly if rabaty_szczegoly else None
            )
        return None

    # Parse line by line
    current_block: Optional[ProductBlock] = None
    i = 0

    while i < len(lines):
        line = lines[i]

        if DEBUG_PARSER:
            logger.info(f"Line {i}: '{line}'")

        # First try to parse as single-line product
        single_product = try_parse_single_line(line)
        if single_product:
            # Finalize any pending product block
            if current_block:
                product = finalize_product(current_block)
                if product:
                    products.append(product)
                current_block = None

            products.append(single_product)
            if DEBUG_PARSER:
                logger.info(f"  → Single-line product: {single_product.nazwa} = {single_product.cena}")
            i += 1
            continue

        # Check for product name (multi-line format)
        if is_product_name(line):
            # Finalize previous product if exists
            if current_block:
                product = finalize_product(current_block)
                if product:
                    products.append(product)

            # Start new product block
            current_block = ProductBlock(name=line)
            if DEBUG_PARSER:
                logger.info(f"  → New product: {line}")

        elif current_block:
            # Collecting data for current product

            # PTU category
            if ptu_pattern.match(line):
                current_block.ptu = line.strip()
                if DEBUG_PARSER:
                    logger.info(f"  → PTU: {line}")

            # Quantity
            elif qty_pattern.match(line):
                qty_match = qty_pattern.match(line)
                if qty_match:
                    current_block.quantity = float(qty_match.group(1).replace(',', '.'))
                if DEBUG_PARSER:
                    logger.info(f"  → Qty: {current_block.quantity}")

            # Percentage discount: "-30%", "Promocja -30%"
            elif rabat_procent_pattern.match(line):
                pct_match = rabat_procent_pattern.match(line)
                pct_value = float(pct_match.group(1))
                # Determine label from the line
                line_lower = line.lower()
                if "promocja" in line_lower:
                    label = "Promocja"
                elif "zniżka" in line_lower or "znizka" in line_lower:
                    label = "Zniżka"
                elif "upust" in line_lower:
                    label = "Upust"
                else:
                    label = "Rabat"
                current_block.rabaty.append(DiscountInfo(typ="procentowy", wartosc=pct_value, opis=label))
                current_block.has_rabat_marker = True
                if DEBUG_PARSER:
                    logger.info(f"  → Rabat procentowy: {pct_value}% ({label})")

            # Amount discount with label: "Rabat -3.29"
            elif rabat_kwotowy_pattern.match(line):
                kwota_match = rabat_kwotowy_pattern.match(line)
                label = kwota_match.group(1).capitalize()
                amount = float(kwota_match.group(2).replace(',', '.'))
                current_block.rabaty.append(DiscountInfo(typ="kwotowy", wartosc=amount, opis=label))
                current_block.rabat = (current_block.rabat or 0) + amount
                current_block.has_rabat_marker = True
                if DEBUG_PARSER:
                    logger.info(f"  → Rabat kwotowy: {amount} ({label})")

            # Plain rabat marker (just the word)
            elif rabat_pattern.match(line):
                current_block.has_rabat_marker = True
                # Remember the type for the next number
                line_lower = line.lower()
                if "promocja" in line_lower:
                    current_block.last_rabat_type = "Promocja"
                elif "zniżka" in line_lower or "znizka" in line_lower:
                    current_block.last_rabat_type = "Zniżka"
                elif "upust" in line_lower:
                    current_block.last_rabat_type = "Upust"
                else:
                    current_block.last_rabat_type = "Rabat"
                if DEBUG_PARSER:
                    logger.info(f"  → Rabat marker: {current_block.last_rabat_type}")

            # Price/number
            elif price_pattern.match(line):
                price_match = price_pattern.match(line)
                val = float(price_match.group(1).replace(',', '.'))

                if line.startswith('-'):
                    # Negative = discount amount
                    label = current_block.last_rabat_type or "Rabat"
                    current_block.rabaty.append(DiscountInfo(typ="kwotowy", wartosc=val, opis=label))
                    current_block.rabat = (current_block.rabat or 0) + val
                    current_block.last_rabat_type = None  # Reset after use
                    if DEBUG_PARSER:
                        logger.info(f"  → Rabat amount: {val} ({label})")
                else:
                    current_block.prices.append(val)
                    if DEBUG_PARSER:
                        logger.info(f"  → Price: {val}")

            # Stop conditions
            elif skip_regex.search(line):
                # Hit a skip pattern - finalize current product
                if current_block:
                    product = finalize_product(current_block)
                    if product:
                        products.append(product)
                    current_block = None
                if DEBUG_PARSER:
                    logger.info(f"  → Skip pattern, finalizing")

        i += 1

    # Don't forget the last product
    if current_block:
        product = finalize_product(current_block)
        if product:
            products.append(product)

    logger.info(f"Biedronka regex parser found {len(products)} products")

    return ParsedReceipt(
        products=products,
        sklep=store,
        data=date,
        suma=suma,
        raw_text=raw_text
    )


def parse_generic_receipt(raw_text: str) -> ParsedReceipt:
    """
    Parse generic receipt format using simple patterns.
    Falls back to basic extraction.
    """
    products = []

    # Simple pattern: name followed by price
    # Look for lines with a price at the end
    price_pattern = re.compile(r'^(.+?)\s+(\d+[\.,]\d{2})\s*$')

    lines = raw_text.split('\n')

    skip_patterns = [
        r'suma', r'total', r'razem', r'ptu', r'vat', r'kaucja',
        r'płatność', r'karta', r'gotówka', r'reszta', r'paragon',
        r'nip', r'nr\s*trans', r'data', r'godzina'
    ]
    skip_regex = re.compile('|'.join(skip_patterns), re.IGNORECASE)

    for line in lines:
        line = line.strip()
        if not line or skip_regex.search(line):
            continue

        match = price_pattern.match(line)
        if match:
            name = match.group(1).strip()
            price = float(match.group(2).replace(',', '.'))

            # Basic validation
            if len(name) >= 3 and price > 0 and price < 1000:
                products.append(ParsedProduct(nazwa=name, cena=price))

    # Extract store, date, total with simple patterns
    store = None
    for pattern, store_name in [
        (r'lidl', 'Lidl'),
        (r'biedronka', 'Biedronka'),
        (r'kaufland', 'Kaufland'),
        (r'[żz]abka', 'Żabka'),
        (r'auchan', 'Auchan'),
        (r'carrefour', 'Carrefour'),
        (r'netto', 'Netto'),
        (r'dino', 'Dino'),
    ]:
        if re.search(pattern, raw_text, re.IGNORECASE):
            store = store_name
            break

    date_match = re.search(r'(\d{2})[-./](\d{2})[-./](\d{4})', raw_text)
    date = None
    if date_match:
        date = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"

    suma_match = re.search(r'(?:suma|total|razem|do\s*zap[łl]aty)\s*:?\s*(\d+[\.,]\d+)', raw_text, re.IGNORECASE)
    suma = float(suma_match.group(1).replace(',', '.')) if suma_match else None

    return ParsedReceipt(
        products=products,
        sklep=store,
        data=date,
        suma=suma,
        raw_text=raw_text
    )


def parse_receipt_hybrid(raw_text: str, store: Optional[str] = None) -> ParsedReceipt:
    """
    Main entry point for hybrid parsing.
    Selects the appropriate parser based on detected store.
    """
    # Detect store if not provided
    if not store:
        text_lower = raw_text.lower()
        if 'biedronka' in text_lower or 'jeronimo martins' in text_lower:
            store = 'biedronka'
        elif 'lidl' in text_lower:
            store = 'lidl'
        # Add more store detection as needed

    # Use store-specific parser
    if store and store.lower() == 'biedronka':
        logger.info("Using Biedronka-specific regex parser")
        return parse_biedronka_receipt(raw_text)

    # Fall back to generic parser
    logger.info("Using generic regex parser")
    return parse_generic_receipt(raw_text)
