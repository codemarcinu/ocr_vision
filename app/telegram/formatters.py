"""Message formatters for Telegram bot."""

import time
from datetime import datetime
from typing import Optional

from app.models import CategorizedProduct, Receipt


# Store emoji mapping
STORE_EMOJI = {
    "biedronka": "🐞",
    "lidl": "🔵",
    "kaufland": "🔴",
    "auchan": "🟢",
    "carrefour": "🔷",
    "żabka": "🐸",
    "zabka": "🐸",
    "netto": "🟡",
    "dino": "🦖",
    "rossmann": "💄",
    "hebe": "💅",
    "stokrotka": "🌼",
    "intermarche": "🔶",
    "makro": "📦",
    "selgros": "🏪",
    "polo market": "🛒",
    "lewiatan": "🦁",
    "freshmarket": "🥬",
    "delikatesy centrum": "🏠",
}

# Category icons
CATEGORY_ICONS = {
    "owoce": "🍎",
    "warzywa": "🥬",
    "owoce_warzywa": "🥗",
    "nabiał": "🥛",
    "nabial": "🥛",
    "mięso": "🥩",
    "mieso": "🥩",
    "wędliny": "🥓",
    "wedliny": "🥓",
    "mięso_wędliny": "🥩",
    "pieczywo": "🍞",
    "słodycze": "🍫",
    "slodycze": "🍫",
    "przekąski": "🍿",
    "przekaski": "🍿",
    "napoje": "🥤",
    "alkohol": "🍺",
    "mrożonki": "🧊",
    "mrozonki": "🧊",
    "chemia": "🧴",
    "kosmetyki": "💄",
    "higiena": "🧻",
    "dom": "🏠",
    "inne": "📦",
    "przyprawy": "🧂",
    "konserwy": "🥫",
    "makarony": "🍝",
    "kawy_herbaty": "☕",
    "zboża": "🌾",
    "zboza": "🌾",
    "oleje": "🫒",
    "ryby": "🐟",
    "jaja": "🥚",
    "sosy": "🥫",
}


def get_store_emoji(store: str | None) -> str:
    """Get emoji for store name."""
    if not store:
        return "🏪"
    store_lower = store.lower().strip()
    return STORE_EMOJI.get(store_lower, "🏪")


def get_category_icon(category: str | None) -> str:
    """Get icon for category."""
    if not category:
        return "📦"
    cat_lower = category.lower().strip().replace(" ", "_")
    # Try exact match first
    if cat_lower in CATEGORY_ICONS:
        return CATEGORY_ICONS[cat_lower]
    # Try partial match
    for key, icon in CATEGORY_ICONS.items():
        if key in cat_lower or cat_lower in key:
            return icon
    return "📦"


def escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram HTML mode."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_receipt_summary(
    receipt: Receipt,
    categorized: list[CategorizedProduct],
    source_file: str
) -> str:
    """Format receipt processing result for Telegram message (HTML mode)."""
    store = receipt.sklep or "nieznany"
    emoji = get_store_emoji(store)

    lines = [
        f"<b>{emoji} {escape_html(store.upper())}</b>",
        f"📅 <code>{receipt.data or 'nieznana'}</code>",
        f"💰 <b>{receipt.suma:.2f} zł</b> ({len(categorized)} produktów)",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    # Group by category
    by_category: dict[str, list[CategorizedProduct]] = {}
    for product in categorized:
        category = product.kategoria or "Inne"
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(product)

    for category, products in sorted(by_category.items()):
        icon = get_category_icon(category)
        lines.append(f"\n{icon} <b>{escape_html(category)}</b>")

        for p in products:
            name = escape_html(p.nazwa)

            # Format price with discount info
            if p.cena_oryginalna and p.rabat and p.rabat > 0:
                price_str = f"<s>{p.cena_oryginalna:.2f}</s> → <b>{p.cena:.2f} zł</b> 🏷️"
            else:
                price_str = f"<b>{p.cena:.2f} zł</b>"

            # Warning indicator
            warning_str = " ⚠️" if p.warning else ""

            lines.append(f"  • {name}")
            lines.append(f"    {price_str}{warning_str}")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"<i>📁 {escape_html(source_file)}</i>"
    ])

    return "\n".join(lines)


# ============================================================
# Progress bar formatting
# ============================================================

def format_progress_bar(
    step: int,
    total: int,
    status: str,
    elapsed_seconds: float = 0,
    filename: str | None = None
) -> str:
    """Render ASCII progress bar with ETA (HTML mode).

    Args:
        step: Current step number (1-indexed)
        total: Total number of steps
        status: Current status message
        elapsed_seconds: Time elapsed since start
        filename: Optional filename being processed

    Returns:
        Formatted progress message
    """
    progress = step / total if total > 0 else 0
    bar_length = 20
    filled = int(bar_length * progress)
    bar = "█" * filled + "░" * (bar_length - filled)
    percentage = int(progress * 100)

    # Estimate remaining time
    eta_text = ""
    if elapsed_seconds > 0 and step > 0:
        avg_time_per_step = elapsed_seconds / step
        remaining_steps = total - step
        eta_seconds = int(avg_time_per_step * remaining_steps)
        if eta_seconds > 0:
            eta_text = f" | ETA: ~{eta_seconds}s"

    lines = ["<b>🔄 Przetwarzanie paragonu</b>"]

    if filename:
        lines.append(f"<i>📁 {escape_html(filename)}</i>")

    lines.append("")
    lines.append(f"<code>[{bar}] {percentage}%</code>")
    lines.append("")
    lines.append(f"<i>{escape_html(status)}</i>{eta_text}")

    return "\n".join(lines)


def format_progress_step(step: int, total: int, status: str) -> str:
    """Simple progress format without ETA (for quick operations)."""
    step_icons = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    icon = step_icons[step - 1] if step <= len(step_icons) else f"{step}."

    return f"{icon} <b>Krok {step}/{total}:</b> {escape_html(status)}"


# ============================================================
# List formatters
# ============================================================

def format_receipt_list(receipts: list[dict]) -> str:
    """Format list of receipts for Telegram message (HTML mode)."""
    if not receipts:
        return "Brak paragonów."

    lines = ["<b>🧾 Ostatnie paragony:</b>", ""]
    for r in receipts:
        date = r.get("date", "?")
        store = r.get("store", "nieznany")
        total = r.get("total", "?")
        filename = r.get("filename", "")
        emoji = get_store_emoji(store)
        lines.append(f"{emoji} {date} | <b>{escape_html(store)}</b> | {total} zł")
        lines.append(f"    <code>{escape_html(filename)}</code>")

    return "\n".join(lines)


def format_pantry_contents(contents: dict[str, list[dict]], category: Optional[str] = None) -> str:
    """Format pantry contents for Telegram message (HTML mode)."""
    if not contents:
        return "🏠 Spiżarnia jest pusta."

    lines = ["<b>🏠 Spiżarnia:</b>", ""]

    categories_to_show = [category] if category and category in contents else sorted(contents.keys())

    for cat in categories_to_show:
        if cat not in contents:
            continue
        items = contents[cat]
        if not items:
            continue

        icon = get_category_icon(cat)
        lines.append(f"\n{icon} <b>{escape_html(cat)}</b>")
        for item in items:
            checkbox = "☑️" if item.get("checked") else "⬜"
            name = escape_html(item.get("name", "?"))
            price = item.get("price", "?")
            date = item.get("date", "")
            lines.append(f"  {checkbox} {name} - {price} zł <i>({date})</i>")

    if len(lines) == 2:
        if category:
            return f"Brak produktów w kategorii {escape_html(category)}."
        return "🏠 Spiżarnia jest pusta."

    return "\n".join(lines)


def format_stats(stats: dict, period: str = "week") -> str:
    """Format spending statistics for Telegram message (HTML mode)."""
    period_name = "tydzień" if period == "week" else "miesiąc"

    lines = [
        f"<b>📊 Statystyki za {period_name}:</b>",
        "",
        f"💰 Suma wydatków: <b>{stats.get('total', 0):.2f} zł</b>",
        f"🧾 Liczba paragonów: <b>{stats.get('receipt_count', 0)}</b>",
        f"📦 Liczba produktów: <b>{stats.get('product_count', 0)}</b>",
    ]

    if stats.get("avg_receipt"):
        lines.append(f"📈 Średni paragon: <b>{stats['avg_receipt']:.2f} zł</b>")

    return "\n".join(lines)


def format_stores_stats(stores: dict[str, dict]) -> str:
    """Format store spending statistics (HTML mode)."""
    if not stores:
        return "Brak danych o sklepach."

    lines = ["<b>🏪 Wydatki wg sklepów:</b>", ""]

    # Sort by total spent descending
    sorted_stores = sorted(stores.items(), key=lambda x: x[1].get("total", 0), reverse=True)

    for store, data in sorted_stores:
        total = data.get("total", 0)
        count = data.get("count", 0)
        emoji = get_store_emoji(store)
        lines.append(f"{emoji} <b>{escape_html(store)}</b>: {total:.2f} zł ({count} paragonów)")

    return "\n".join(lines)


def format_categories_stats(categories: dict[str, dict]) -> str:
    """Format category spending statistics (HTML mode)."""
    if not categories:
        return "Brak danych o kategoriach."

    lines = ["<b>📂 Wydatki wg kategorii:</b>", ""]

    # Sort by total spent descending
    sorted_cats = sorted(categories.items(), key=lambda x: x[1].get("total", 0), reverse=True)

    for category, data in sorted_cats:
        total = data.get("total", 0)
        count = data.get("count", 0)
        icon = get_category_icon(category)
        lines.append(f"{icon} <b>{escape_html(category)}</b>: {total:.2f} zł ({count} produktów)")

    return "\n".join(lines)


def format_errors(errors: list[dict]) -> str:
    """Format error list for Telegram message (HTML mode)."""
    if not errors:
        return "✅ Brak błędów w logu."

    lines = ["<b>❌ Błędy przetwarzania:</b>", ""]

    for error in errors[-10:]:  # Last 10 errors
        date = error.get("date", "?")
        filename = error.get("filename", "?")
        message = error.get("message", "?")[:50]
        lines.append(f"• {date}")
        lines.append(f"  📁 <code>{escape_html(filename)}</code>")
        lines.append(f"  ⚠️ {escape_html(message)}...")
        lines.append("")

    if len(errors) > 10:
        lines.append(f"<i>...i {len(errors) - 10} więcej</i>")

    return "\n".join(lines)


def format_pending_files(files: list[str]) -> str:
    """Format list of pending files in inbox (HTML mode)."""
    if not files:
        return "📭 Brak plików w kolejce (inbox)."

    lines = ["<b>📬 Pliki w kolejce:</b>", ""]
    for f in files:
        lines.append(f"• <code>{escape_html(f)}</code>")

    lines.append("")
    lines.append(f"<i>Łącznie: {len(files)} plików</i>")

    return "\n".join(lines)


def format_search_results(results: list[dict], query: str) -> str:
    """Format search results for Telegram message (HTML mode)."""
    if not results:
        return f"🔍 Nie znaleziono produktów pasujących do: '{escape_html(query)}'"

    lines = [f"<b>🔍 Wyniki wyszukiwania dla '{escape_html(query)}':</b>", ""]

    for item in results[:20]:
        checkbox = "☑️" if item.get("checked") else "⬜"
        name = escape_html(item.get("name", "?"))
        price = item.get("price", "?")
        category = item.get("category", "?")
        date = item.get("date", "")
        icon = get_category_icon(category)
        lines.append(f"{checkbox} <b>{name}</b> - {price} zł")
        lines.append(f"   {icon} <i>{escape_html(category)}</i> | {date}")

    if len(results) > 20:
        lines.append(f"\n<i>...i {len(results) - 20} więcej</i>")

    return "\n".join(lines)


def escape_markdown(text: str) -> str:
    """Remove special markdown characters that break Telegram formatting.

    DEPRECATED: Use escape_html() with parse_mode='HTML' instead.
    """
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
    """Format receipt for human review with warnings highlighted (HTML mode)."""
    store = receipt.sklep or "nieznany"
    emoji = get_store_emoji(store)

    lines = [
        "⚠️ <b>PARAGON WYMAGA WERYFIKACJI</b> ⚠️",
        "",
    ]

    # Show review reasons
    if receipt.review_reasons:
        lines.append("<b>Powody:</b>")
        for reason in receipt.review_reasons:
            lines.append(f"  ❗ {escape_html(reason)}")
        lines.append("")

    # Basic info with visual hierarchy
    lines.extend([
        f"{emoji} <b>{escape_html(store.upper())}</b>",
        f"📅 <code>{receipt.data or 'nieznana'}</code>",
        "",
        f"💵 Suma OCR: <b>{receipt.suma:.2f} zł</b>" if receipt.suma else "💵 Suma OCR: <i>brak</i>",
    ])

    # Show calculated total for comparison
    if receipt.calculated_total:
        lines.append(f"🧮 Suma produktów: <b>{receipt.calculated_total:.2f} zł</b>")
        if receipt.suma:
            diff = receipt.suma - receipt.calculated_total
            diff_icon = "🔴" if abs(diff) > 5 else "🟡"
            lines.append(f"{diff_icon} Różnica: <b>{diff:+.2f} zł</b>")

    lines.extend([
        f"📦 Produktów: {len(categorized)}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ])

    # Group by category
    by_category: dict[str, list[CategorizedProduct]] = {}
    for product in categorized:
        category = product.kategoria or "Inne"
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(product)

    for category, products in sorted(by_category.items()):
        icon = get_category_icon(category)
        lines.append(f"\n{icon} <b>{escape_html(category)}</b>")

        for p in products:
            name = escape_html(p.nazwa)
            # Format price with discount info
            if p.cena_oryginalna and p.rabat and p.rabat > 0:
                price_str = f"<s>{p.cena_oryginalna:.2f}</s> → <b>{p.cena:.2f} zł</b> 🏷️"
            else:
                price_str = f"<b>{p.cena:.2f} zł</b>"

            warning_str = " ⚠️" if p.warning else ""
            lines.append(f"  • {name}")
            lines.append(f"    {price_str}{warning_str}")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"<i>📁 {escape_html(source_file)}</i>",
        "",
        "<i>👇 Wybierz akcję poniżej:</i>"
    ])

    return "\n".join(lines)
