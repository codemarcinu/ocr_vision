"""JSON receipt import handler for Telegram bot."""

import json
import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from app.models import CategorizedProduct, Receipt, Product
from app.services.receipt_saver import save_receipt_to_db, write_receipt_to_obsidian, index_receipt_in_rag

logger = logging.getLogger(__name__)


class ImportedProduct(BaseModel):
    """Product from imported JSON."""
    nazwa_oryginalna: str
    nazwa_znormalizowana: Optional[str] = None
    kategoria: Optional[str] = None
    ilosc: Optional[float] = 1.0
    cena_jednostkowa: Optional[float] = None
    cena_bazowa_linii: Optional[float] = None
    rabat: Optional[float] = 0.0
    cena_koncowa: float
    stawka_vat: Optional[str] = None


class ImportedTransaction(BaseModel):
    """Transaction info from imported JSON."""
    sklep: Optional[str] = None
    data_godzina: Optional[str] = None
    nr_paragonu: Optional[str] = None
    suma_calkowita: Optional[float] = None
    metoda_platnosci: Optional[str] = None


class ImportedReceipt(BaseModel):
    """Full imported receipt structure."""
    transakcja: ImportedTransaction
    produkty: list[ImportedProduct]
    uwagi: Optional[str] = None


def is_json_receipt(text: str) -> bool:
    """Check if text looks like a JSON receipt."""
    text = text.strip()
    if not text.startswith("{"):
        return False
    try:
        data = json.loads(text)
        # Must have transakcja and produkty keys
        return "transakcja" in data and "produkty" in data
    except json.JSONDecodeError:
        return False


def parse_json_receipt(text: str) -> tuple[Optional[ImportedReceipt], Optional[str]]:
    """
    Parse JSON text into ImportedReceipt.

    Returns:
        Tuple of (parsed_receipt, error_message)
    """
    try:
        data = json.loads(text)
        receipt = ImportedReceipt(**data)
        return receipt, None
    except json.JSONDecodeError as e:
        return None, f"Nieprawidłowy JSON: {e}"
    except ValidationError as e:
        errors = e.errors()
        error_msgs = [f"{err['loc']}: {err['msg']}" for err in errors[:3]]
        return None, f"Błąd walidacji:\n" + "\n".join(error_msgs)


def extract_store_name(full_store: str) -> str:
    """Extract short store name from full address."""
    if not full_store:
        return "nieznany"
    # Take first word/part before comma
    parts = full_store.split(",")
    return parts[0].strip()


def extract_date(date_str: Optional[str]) -> str:
    """Extract date in YYYY-MM-DD format."""
    if not date_str:
        return datetime.now().strftime("%Y-%m-%d")

    # Try common formats
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"]:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Fallback: try to extract date part
    date_part = date_str.split()[0] if " " in date_str else date_str
    return date_part


def convert_to_internal_models(
    imported: ImportedReceipt
) -> tuple[Receipt, list[CategorizedProduct]]:
    """
    Convert imported JSON receipt to internal models.

    Returns:
        Tuple of (Receipt, list of CategorizedProducts)
    """
    # Extract store name and date
    store = extract_store_name(imported.transakcja.sklep or "")
    date = extract_date(imported.transakcja.data_godzina)

    # Convert products
    products: list[Product] = []
    categorized: list[CategorizedProduct] = []

    for p in imported.produkty:
        # Use normalized name if available, otherwise original
        nazwa = p.nazwa_znormalizowana or p.nazwa_oryginalna
        kategoria = p.kategoria or "Inne"

        # Calculate discount amount (rabat in JSON is negative)
        rabat_amount = abs(p.rabat) if p.rabat else None
        cena_oryginalna = p.cena_bazowa_linii if rabat_amount else None

        product = Product(
            nazwa=nazwa,
            cena=p.cena_koncowa,
            kategoria=kategoria,
            confidence=1.0,  # JSON import = full confidence
            nazwa_oryginalna=p.nazwa_oryginalna,
            nazwa_znormalizowana=p.nazwa_znormalizowana,
            cena_oryginalna=cena_oryginalna,
            rabat=rabat_amount,
        )
        products.append(product)

        cat_product = CategorizedProduct(
            nazwa=nazwa,
            cena=p.cena_koncowa,
            kategoria=kategoria,
            confidence=1.0,
            nazwa_oryginalna=p.nazwa_oryginalna,
            nazwa_znormalizowana=p.nazwa_znormalizowana,
            cena_oryginalna=cena_oryginalna,
            rabat=rabat_amount,
        )
        categorized.append(cat_product)

    # Calculate total from products
    calculated_total = round(sum(p.cena for p in products), 2)

    # Use provided total or calculated
    total = imported.transakcja.suma_calkowita or calculated_total

    receipt = Receipt(
        products=products,
        sklep=store,
        data=date,
        suma=total,
        calculated_total=calculated_total,
        needs_review=False,
    )

    return receipt, categorized


def format_import_summary(
    receipt: Receipt,
    categorized: list[CategorizedProduct],
    filename: str
) -> str:
    """Format summary message for imported receipt."""
    lines = [
        "*Import JSON zakończony*",
        "",
        f"Sklep: {receipt.sklep or 'nieznany'}",
        f"Data: {receipt.data}",
        f"Suma: {receipt.suma:.2f} zł",
        f"Produktów: {len(categorized)}",
        "",
    ]

    # Group by category
    by_category: dict[str, list[CategorizedProduct]] = {}
    for p in categorized:
        cat = p.kategoria or "Inne"
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(p)

    # Show first few products per category
    for cat, products in sorted(by_category.items()):
        lines.append(f"*{cat}* ({len(products)})")
        for p in products[:3]:
            discount = f" (-{p.rabat:.2f})" if p.rabat else ""
            lines.append(f"  • {p.nazwa}: {p.cena:.2f} zł{discount}")
        if len(products) > 3:
            lines.append(f"  _...i {len(products) - 3} więcej_")

    return "\n".join(lines)


async def process_json_import(text: str) -> tuple[bool, str, Optional[str]]:
    """
    Process JSON receipt import.

    Returns:
        Tuple of (success, message, filename or None)
    """
    # Parse JSON
    imported, error = parse_json_receipt(text)
    if error or not imported:
        return False, error or "Nieznany błąd parsowania", None

    # Validate we have products
    if not imported.produkty:
        return False, "Brak produktów w JSON", None

    # Convert to internal models
    receipt, categorized = convert_to_internal_models(imported)

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"json_import_{timestamp}.json"

    # Save to database
    try:
        db_receipt_id = await save_receipt_to_db(receipt, categorized, filename)
        if not db_receipt_id:
            return False, "Błąd zapisu do bazy danych", None

        # Write Obsidian markdown + RAG indexing
        write_receipt_to_obsidian(receipt, categorized, filename)
        await index_receipt_in_rag(db_receipt_id)

        summary = format_import_summary(receipt, categorized, filename)
        return True, summary, filename

    except Exception as e:
        logger.exception(f"Error saving imported receipt: {e}")
        return False, f"Błąd zapisu: {e}", None
