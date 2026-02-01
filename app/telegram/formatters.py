"""Message formatters for Telegram bot."""

from datetime import datetime
from typing import Optional

from app.models import CategorizedProduct, Receipt


def format_receipt_summary(
    receipt: Receipt,
    categorized: list[CategorizedProduct],
    source_file: str
) -> str:
    """Format receipt processing result for Telegram message."""
    lines = [
        f"*Paragon przetworzony*",
        f"Sklep: {receipt.sklep or 'nieznany'}",
        f"Data: {receipt.data or 'nieznana'}",
        f"Suma: {receipt.suma or 'N/A'} zł",
        f"Produktów: {len(categorized)}",
        "",
        "*Produkty:*"
    ]

    # Group by category
    by_category: dict[str, list[CategorizedProduct]] = {}
    for product in categorized:
        category = product.kategoria or "Inne"
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(product)

    for category, products in sorted(by_category.items()):
        safe_category = escape_markdown(category)
        lines.append(f"\n_{safe_category}_:")
        for p in products:
            safe_name = escape_markdown(p.nazwa)
            safe_warning = escape_markdown(p.warning) if p.warning else ""
            warning_str = f" {safe_warning}" if safe_warning else ""
            lines.append(f"  • {safe_name} - {p.cena:.2f} zł{warning_str}")

    return "\n".join(lines)


def format_receipt_list(receipts: list[dict]) -> str:
    """Format list of receipts for Telegram message."""
    if not receipts:
        return "Brak paragonów."

    lines = ["*Ostatnie paragony:*", ""]
    for r in receipts:
        date = r.get("date", "?")
        store = r.get("store", "nieznany")
        total = r.get("total", "?")
        filename = r.get("filename", "")
        lines.append(f"• {date} | {store} | {total} zł")
        lines.append(f"  `{filename}`")

    return "\n".join(lines)


def format_pantry_contents(contents: dict[str, list[dict]], category: Optional[str] = None) -> str:
    """Format pantry contents for Telegram message."""
    if not contents:
        return "Spiżarnia jest pusta."

    lines = ["*Spiżarnia:*", ""]

    categories_to_show = [category] if category and category in contents else sorted(contents.keys())

    for cat in categories_to_show:
        if cat not in contents:
            continue
        items = contents[cat]
        if not items:
            continue

        lines.append(f"\n_{cat}_:")
        for item in items:
            checkbox = "☑️" if item.get("checked") else "⬜"
            name = item.get("name", "?")
            price = item.get("price", "?")
            date = item.get("date", "")
            lines.append(f"  {checkbox} {name} - {price} zł ({date})")

    if len(lines) == 2:
        if category:
            return f"Brak produktów w kategorii {category}."
        return "Spiżarnia jest pusta."

    return "\n".join(lines)


def format_stats(stats: dict, period: str = "week") -> str:
    """Format spending statistics for Telegram message."""
    period_name = "tydzień" if period == "week" else "miesiąc"

    lines = [
        f"*Statystyki za {period_name}:*",
        "",
        f"Suma wydatków: {stats.get('total', 0):.2f} zł",
        f"Liczba paragonów: {stats.get('receipt_count', 0)}",
        f"Liczba produktów: {stats.get('product_count', 0)}",
    ]

    if stats.get("avg_receipt"):
        lines.append(f"Średni paragon: {stats['avg_receipt']:.2f} zł")

    return "\n".join(lines)


def format_stores_stats(stores: dict[str, dict]) -> str:
    """Format store spending statistics."""
    if not stores:
        return "Brak danych o sklepach."

    lines = ["*Wydatki wg sklepów:*", ""]

    # Sort by total spent descending
    sorted_stores = sorted(stores.items(), key=lambda x: x[1].get("total", 0), reverse=True)

    for store, data in sorted_stores:
        total = data.get("total", 0)
        count = data.get("count", 0)
        lines.append(f"• {store}: {total:.2f} zł ({count} paragonów)")

    return "\n".join(lines)


def format_categories_stats(categories: dict[str, dict]) -> str:
    """Format category spending statistics."""
    if not categories:
        return "Brak danych o kategoriach."

    lines = ["*Wydatki wg kategorii:*", ""]

    # Sort by total spent descending
    sorted_cats = sorted(categories.items(), key=lambda x: x[1].get("total", 0), reverse=True)

    for category, data in sorted_cats:
        total = data.get("total", 0)
        count = data.get("count", 0)
        lines.append(f"• {category}: {total:.2f} zł ({count} produktów)")

    return "\n".join(lines)


def format_errors(errors: list[dict]) -> str:
    """Format error list for Telegram message."""
    if not errors:
        return "Brak błędów w logu."

    lines = ["*Błędy przetwarzania:*", ""]

    for error in errors[-10:]:  # Last 10 errors
        date = error.get("date", "?")
        filename = error.get("filename", "?")
        message = error.get("message", "?")[:50]
        lines.append(f"• {date}")
        lines.append(f"  Plik: `{filename}`")
        lines.append(f"  Błąd: {message}...")
        lines.append("")

    if len(errors) > 10:
        lines.append(f"_...i {len(errors) - 10} więcej_")

    return "\n".join(lines)


def format_pending_files(files: list[str]) -> str:
    """Format list of pending files in inbox."""
    if not files:
        return "Brak plików w kolejce (inbox)."

    lines = ["*Pliki w kolejce:*", ""]
    for f in files:
        lines.append(f"• `{f}`")

    lines.append("")
    lines.append(f"_Łącznie: {len(files)} plików_")

    return "\n".join(lines)


def format_search_results(results: list[dict], query: str) -> str:
    """Format search results for Telegram message."""
    if not results:
        return f"Nie znaleziono produktów pasujących do: '{query}'"

    lines = [f"*Wyniki wyszukiwania dla '{query}':*", ""]

    for item in results[:20]:
        checkbox = "☑️" if item.get("checked") else "⬜"
        name = item.get("name", "?")
        price = item.get("price", "?")
        category = item.get("category", "?")
        date = item.get("date", "")
        lines.append(f"{checkbox} {name} - {price} zł")
        lines.append(f"   _{category}_ | {date}")

    if len(results) > 20:
        lines.append(f"\n_...i {len(results) - 20} więcej_")

    return "\n".join(lines)


def escape_markdown(text: str) -> str:
    """Remove special markdown characters that break Telegram formatting."""
    # For Markdown v1, we can't escape - just remove problematic chars
    special_chars = ['_', '*', '`', '[', ']']
    for char in special_chars:
        text = text.replace(char, '')
    return text


def format_review_receipt(
    receipt: Receipt,
    categorized: list[CategorizedProduct],
    source_file: str
) -> str:
    """Format receipt for human review with warnings highlighted."""
    lines = [
        "*PARAGON WYMAGA WERYFIKACJI*",
        "",
    ]

    # Show review reasons
    if receipt.review_reasons:
        lines.append("*Powody:*")
        for reason in receipt.review_reasons:
            safe_reason = escape_markdown(reason)
            lines.append(f"  - {safe_reason}")
        lines.append("")

    # Basic info
    lines.extend([
        f"*Dane paragonu:*",
        f"Sklep: {receipt.sklep or 'nieznany'}",
        f"Data: {receipt.data or 'nieznana'}",
        f"*Suma OCR: {receipt.suma or 'N/A'} zł*",
    ])

    # Show calculated total for comparison
    if receipt.calculated_total:
        lines.append(f"Suma produktów: {receipt.calculated_total:.2f} zł")
        if receipt.suma:
            diff = receipt.suma - receipt.calculated_total
            lines.append(f"Różnica: {diff:+.2f} zł")

    lines.extend([
        f"Produktów: {len(categorized)}",
        "",
        "*Produkty:*"
    ])

    # Group by category
    by_category: dict[str, list[CategorizedProduct]] = {}
    for product in categorized:
        category = product.kategoria or "Inne"
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(product)

    for category, products in sorted(by_category.items()):
        safe_category = escape_markdown(category)
        lines.append(f"\n_{safe_category}_:")
        for p in products:
            safe_name = escape_markdown(p.nazwa)
            price_str = f"{p.cena:.2f} zł"
            # Show discount info if present
            if p.cena_oryginalna and p.rabat:
                price_str = f"{p.cena:.2f} zł (było {p.cena_oryginalna:.2f}, rabat -{p.rabat:.2f})"
            lines.append(f"  • {safe_name} - {price_str}")

    lines.extend([
        "",
        f"Plik: `{source_file}`",
        "",
        "_Wybierz akcję poniżej:_"
    ])

    return "\n".join(lines)
