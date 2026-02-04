"""Direct data tools for chat - queries analytics and pantry repositories."""

import logging
import re
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.analytics import AnalyticsRepository
from app.db.repositories.pantry import PantryRepository

logger = logging.getLogger(__name__)

# Polish month names (all declension forms) → month number
MONTHS_PL = {
    "styczeń": 1, "styczniu": 1, "stycznia": 1, "styczen": 1,
    "luty": 2, "lutym": 2, "lutego": 2,
    "marzec": 3, "marcu": 3, "marca": 3,
    "kwiecień": 4, "kwietniu": 4, "kwietnia": 4, "kwiecien": 4,
    "maj": 5, "maju": 5, "maja": 5,
    "czerwiec": 6, "czerwcu": 6, "czerwca": 6,
    "lipiec": 7, "lipcu": 7, "lipca": 7,
    "sierpień": 8, "sierpniu": 8, "sierpnia": 8, "sierpien": 8,
    "wrzesień": 9, "wrześniu": 9, "września": 9, "wrzesien": 9, "wrzesniu": 9,
    "październik": 10, "październiku": 10, "października": 10,
    "pazdziernik": 10, "pazdzierniku": 10,
    "listopad": 11, "listopadzie": 11, "listopada": 11,
    "grudzień": 12, "grudniu": 12, "grudnia": 12, "grudzien": 12,
}

# Known store names for extraction
STORE_KEYWORDS = [
    "biedronka", "lidl", "kaufland", "żabka", "zabka",
    "auchan", "carrefour", "netto", "dino", "lewiatan",
    "rossmann", "hebe", "pepco", "action", "media expert",
    "stokrotka", "polomarket", "intermarche", "makro",
]


def _extract_date_range(query: str) -> tuple[Optional[date], Optional[date]]:
    """Extract date range from Polish query text."""
    today = date.today()
    q = query.lower()

    # "w tym miesiącu" / "ten miesiąc" / "bieżący miesiąc"
    if any(p in q for p in ("tym miesiącu", "ten miesiąc", "bieżący miesiąc", "biezacy miesiac")):
        return today.replace(day=1), today

    # "w tym tygodniu" / "ten tydzień"
    if any(p in q for p in ("tym tygodniu", "ten tydzień", "ten tydzien")):
        start = today - timedelta(days=today.weekday())
        return start, today

    # "wczoraj"
    if "wczoraj" in q:
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday

    # "dzisiaj" / "dziś"
    if any(p in q for p in ("dzisiaj", "dziś", "dzis")):
        return today, today

    # "ostatni miesiąc" / "zeszły miesiąc" / "poprzedni miesiąc"
    if any(p in q for p in ("ostatni miesiąc", "zeszły miesiąc", "poprzedni miesiąc",
                             "ostatni miesiac", "zeszly miesiac", "poprzedni miesiac")):
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev

    # "ostatnie N dni"
    m = re.search(r"ostatni[che]*\s+(\d+)\s+dni", q)
    if m:
        days = int(m.group(1))
        return today - timedelta(days=days), today

    # Named month: "w styczniu", "w lutym", etc.
    for month_name, month_num in MONTHS_PL.items():
        if month_name in q:
            year = today.year
            if month_num > today.month:
                year -= 1
            start = date(year, month_num, 1)
            if month_num == 12:
                end = date(year, 12, 31)
            else:
                end = date(year, month_num + 1, 1) - timedelta(days=1)
            return start, end

    return None, None


def _extract_store(query: str) -> Optional[str]:
    """Extract store name from query."""
    q = query.lower()
    for store in STORE_KEYWORDS:
        if store in q:
            return store
    return None


async def query_spending(
    query: str,
    session: AsyncSession,
) -> str:
    """Handle spending/analytics queries. Returns formatted context string."""
    analytics = AnalyticsRepository(session)
    q = query.lower()

    start_date, end_date = _extract_date_range(query)
    store_name = _extract_store(query)

    parts = []

    try:
        if any(kw in q for kw in ("kategori", "na co", "na czym")):
            data = await analytics.get_spending_by_category(start_date, end_date)
            if data:
                lines = ["Wydatki wg kategorii:"]
                for d in data[:15]:
                    lines.append(
                        f"- {d['category']}: {d['total_spent']:.2f} PLN "
                        f"({d['item_count']} szt., śr. {d['avg_price']:.2f} PLN)"
                    )
                parts.append("\n".join(lines))

        elif any(kw in q for kw in ("sklep", "gdzie")) or store_name:
            if store_name:
                data = await analytics.get_spending_by_store(start_date, end_date)
                store_data = [
                    d for d in data if store_name in d["store"].lower()
                ]
                if store_data:
                    d = store_data[0]
                    parts.append(
                        f"Sklep {d['store']}:\n"
                        f"- Wydano: {d['total_spent']:.2f} PLN\n"
                        f"- Paragonów: {d['receipt_count']}\n"
                        f"- Średni paragon: {d['avg_receipt']:.2f} PLN"
                    )
                else:
                    parts.append(f"Brak danych dla sklepu '{store_name}'.")
            else:
                data = await analytics.get_spending_by_store(start_date, end_date)
                if data:
                    lines = ["Wydatki wg sklepów:"]
                    for d in data[:10]:
                        lines.append(
                            f"- {d['store']}: {d['total_spent']:.2f} PLN "
                            f"({d['receipt_count']} wizyt)"
                        )
                    parts.append("\n".join(lines))

        elif any(kw in q for kw in ("porówn", "porown", "tydzień", "tydzien", "tygodni")):
            data = await analytics.get_weekly_comparison()
            if data:
                tw = data["this_week"]
                pw = data["prev_week"]
                parts.append(
                    f"Porównanie tygodniowe:\n"
                    f"- Ten tydzień: {tw['total']:.2f} PLN "
                    f"({tw['receipts']} paragonów, {tw['products']} produktów)\n"
                    f"- Poprzedni: {pw['total']:.2f} PLN "
                    f"({pw['receipts']} paragonów, {pw['products']} produktów)\n"
                    f"- Różnica: {data['diff']:+.2f} PLN ({data['diff_pct']:+.1f}%)"
                )
                if data.get("top_categories"):
                    lines = ["Top kategorie tego tygodnia:"]
                    for cat in data["top_categories"]:
                        lines.append(f"  - {cat['category']}: {cat['total']:.2f} PLN")
                    parts.append("\n".join(lines))

        elif any(kw in q for kw in ("top", "najczęś", "najczes", "najdroż", "najdroz",
                                     "najwięcej", "najwiecej", "ranking")):
            by = "spending" if any(kw in q for kw in ("najdroż", "najdroz", "kosztow",
                                                       "wydal", "wydał")) else "count"
            data = await analytics.get_top_products(limit=10, by=by)
            if data:
                label = "najdroższe" if by == "spending" else "najczęściej kupowane"
                lines = [f"Top 10 {label} produktów:"]
                for d in data:
                    lines.append(
                        f"- {d['product']} ({d['category']}): "
                        f"{d['total_spent']:.2f} PLN (x{d['purchase_count']}, "
                        f"śr. {d['avg_price']:.2f} PLN)"
                    )
                parts.append("\n".join(lines))

        elif any(kw in q for kw in ("rabat", "zniżk", "znizk", "oszczęd", "oszczed",
                                     "promocj")):
            data = await analytics.get_discount_summary(start_date, end_date)
            if data:
                parts.append(
                    f"Podsumowanie rabatów:\n"
                    f"- Produkty z rabatem: {data['discounted_items']}/{data['total_items']}\n"
                    f"- Łączna oszczędność: {data['total_savings']:.2f} PLN\n"
                    f"- Średni rabat: {data['avg_discount']:.2f} PLN\n"
                    f"- % z rabatem: {data['discount_percentage']:.1f}%"
                )

        elif any(kw in q for kw in ("anomali", "drożej", "drozej", "podrożał", "podrozal")):
            data = await analytics.get_price_anomalies()
            if data:
                lines = ["Anomalie cenowe (ostatnie 14 dni):"]
                for d in data:
                    lines.append(
                        f"- {d['product']}: {d['latest_price']:.2f} PLN "
                        f"(śr. {d['avg_price']:.2f}, +{d['diff_pct']:.0f}%, "
                        f"{d['store']}, {d['date']})"
                    )
                parts.append("\n".join(lines))

        else:
            # Default: general spending summary for the period
            by_store = await analytics.get_spending_by_store(start_date, end_date)
            by_cat = await analytics.get_spending_by_category(start_date, end_date)

            total = sum(d["total_spent"] for d in by_store) if by_store else 0
            receipts = sum(d["receipt_count"] for d in by_store) if by_store else 0
            parts.append(f"Łączne wydatki: {total:.2f} PLN ({receipts} paragonów)")

            if by_store:
                lines = ["Wg sklepów:"]
                for d in by_store[:5]:
                    lines.append(
                        f"- {d['store']}: {d['total_spent']:.2f} PLN "
                        f"({d['receipt_count']} wizyt)"
                    )
                parts.append("\n".join(lines))

            if by_cat:
                lines = ["Wg kategorii:"]
                for d in by_cat[:5]:
                    lines.append(f"- {d['category']}: {d['total_spent']:.2f} PLN")
                parts.append("\n".join(lines))

    except Exception as e:
        logger.error(f"Spending query error: {e}", exc_info=True)
        return f"=== DANE O WYDATKACH ===\nBłąd pobierania danych o wydatkach: {e}"

    if not parts:
        return ""

    context = "=== DANE O WYDATKACH ===\n" + "\n\n".join(parts)
    if start_date and end_date:
        context += f"\n\n(Okres: {start_date} — {end_date})"
    return context


async def query_inventory(
    query: str,
    session: AsyncSession,
) -> str:
    """Handle pantry/inventory queries. Returns formatted context string."""
    pantry = PantryRepository(session)
    q = query.lower()

    parts = []

    try:
        if any(kw in q for kw in ("przetermin", "kończy", "konczy", "wygasa",
                                    "expir", "termin")):
            items = await pantry.get_expiring_soon(days=7)
            if items:
                lines = ["Produkty z kończącym się terminem (7 dni):"]
                for item in items:
                    exp = item.expiry_date.isoformat() if item.expiry_date else "?"
                    cat = item.category.name if item.category else ""
                    lines.append(f"- {item.name} (termin: {exp}, kat: {cat})")
                parts.append("\n".join(lines))
            else:
                parts.append("Brak produktów z kończącym się terminem ważności w ciągu 7 dni.")

        elif any(kw in q for kw in ("statyst", "ile mam", "podsumow", "przegląd",
                                     "przeglad")):
            stats = await pantry.get_stats()
            cat_summary = await pantry.get_category_summary()

            parts.append(
                f"Statystyki spiżarni:\n"
                f"- Aktywne produkty: {stats['active_items']}\n"
                f"- Zużyte: {stats['consumed_items']}\n"
                f"- Kategorii: {stats['category_count']}\n"
                f"- Kończący się termin: {stats['expiring_soon']}"
            )

            if cat_summary:
                lines = ["Wg kategorii:"]
                for cs in cat_summary[:10]:
                    lines.append(f"- {cs['category']}: {cs['item_count']} szt.")
                parts.append("\n".join(lines))

        elif any(kw in q for kw in ("szukaj", "znajdź", "znajdz", "jest", "mam")):
            # Try to extract a search term — use the query minus common words
            search_term = q
            for remove in ("szukaj", "znajdź", "znajdz", "czy", "mam", "jest",
                           "w", "spiżarni", "spizarni", "pantry"):
                search_term = search_term.replace(remove, "")
            search_term = search_term.strip()

            if search_term and len(search_term) >= 2:
                items = await pantry.search(search_term, limit=10)
                if items:
                    lines = [f"Wyniki szukania '{search_term}' w spiżarni:"]
                    for item in items:
                        cat = item.category.name if item.category else ""
                        store = item.store.name if item.store else ""
                        lines.append(f"- {item.name} (kat: {cat}, sklep: {store})")
                    parts.append("\n".join(lines))
                else:
                    parts.append(f"Nie znaleziono '{search_term}' w spiżarni.")
            else:
                # Fall through to default
                pass

        if not parts:
            # Default: show grouped items + stats
            stats = await pantry.get_stats()
            grouped = await pantry.get_grouped_by_category()

            parts.append(f"Spiżarnia ({stats['active_items']} produktów):")

            if grouped:
                for category, items in grouped.items():
                    lines = [f"\n{category}:"]
                    for item in items[:10]:
                        lines.append(f"  - {item.name}")
                    if len(items) > 10:
                        lines.append(f"  ... i {len(items) - 10} więcej")
                    parts.append("\n".join(lines))

    except Exception as e:
        logger.error(f"Inventory query error: {e}", exc_info=True)
        return f"=== SPIŻARNIA ===\nBłąd pobierania danych spiżarni: {e}"

    if not parts:
        return ""

    return "=== SPIŻARNIA ===\n" + "\n".join(parts)
