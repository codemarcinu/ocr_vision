"""Statistics handlers for Telegram bot."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.telegram.formatters import format_categories_stats, format_stats, format_stores_stats
from app.telegram.keyboards import get_stats_keyboard
from app.telegram.middleware import authorized_only

logger = logging.getLogger(__name__)


# ============================================================
# Discount report functions
# ============================================================

def _calculate_discount_stats() -> dict:
    """Calculate discount statistics from receipts."""
    receipts_dir = settings.RECEIPTS_DIR

    if not receipts_dir.exists():
        return {
            "total_discount": 0,
            "discount_count": 0,
            "by_store": {},
            "recent_items": []
        }

    total_discount = 0.0
    discount_count = 0
    by_store = defaultdict(float)
    recent_items = []

    for file_path in receipts_dir.glob("*.md"):
        if file_path.name.startswith("ERROR_"):
            continue

        receipt_data = _parse_receipt_for_discounts(file_path)
        if not receipt_data:
            continue

        store = receipt_data.get("store", "nieznany")
        date = receipt_data.get("date", "")

        for item in receipt_data.get("discounts", []):
            total_discount += item["discount"]
            discount_count += 1
            by_store[store] += item["discount"]
            recent_items.append({
                "name": item["name"],
                "discount": item["discount"],
                "store": store,
                "date": date
            })

    # Sort recent items by date (newest first) and limit to 10
    recent_items.sort(key=lambda x: x["date"], reverse=True)
    recent_items = recent_items[:10]

    return {
        "total_discount": total_discount,
        "discount_count": discount_count,
        "by_store": dict(sorted(by_store.items(), key=lambda x: x[1], reverse=True)),
        "recent_items": recent_items
    }


def _parse_receipt_for_discounts(file_path: Path) -> Optional[dict]:
    """Parse receipt file for discount information."""
    import re

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        frontmatter = yaml.safe_load(parts[1])
        body = parts[2]

        discounts = []

        for line in body.split("\n"):
            line = line.strip()
            if not line.startswith("- "):
                continue

            # Look for strikethrough price pattern: ~~15.99~~ or (-3.00)
            discount_match = re.search(r'\(-([\d.]+)\)', line)
            if discount_match:
                discount_amount = float(discount_match.group(1))

                # Extract product name
                name_match = re.match(r'- (.+?) \|', line)
                name = name_match.group(1) if name_match else "Produkt"

                discounts.append({
                    "name": name,
                    "discount": discount_amount
                })

        return {
            "date": frontmatter.get("date"),
            "store": frontmatter.get("store", "nieznany"),
            "discounts": discounts
        }

    except Exception as e:
        logger.warning(f"Failed to parse receipt for discounts {file_path}: {e}")
        return None


def format_discount_stats(stats: dict) -> str:
    """Format discount statistics for Telegram message."""
    if stats["discount_count"] == 0:
        return "📊 *Raport rabatów*\n\nNie znaleziono żadnych rabatów."

    lines = [
        "📊 *Raport rabatów*\n",
        f"💰 *Łączne oszczędności:* {stats['total_discount']:.2f} zł",
        f"🏷️ *Liczba rabatów:* {stats['discount_count']}",
        f"📈 *Średni rabat:* {stats['total_discount']/stats['discount_count']:.2f} zł",
        ""
    ]

    if stats["by_store"]:
        lines.append("*Rabaty wg sklepu:*")
        for store, amount in list(stats["by_store"].items())[:5]:
            lines.append(f"  • {store}: {amount:.2f} zł")
        lines.append("")

    if stats["recent_items"]:
        lines.append("*Ostatnie rabaty:*")
        for item in stats["recent_items"][:5]:
            lines.append(f"  • {item['name']}: -{item['discount']:.2f} zł ({item['store']})")

    return "\n".join(lines)


@authorized_only
async def discounts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /rabaty or /discounts command - show discount statistics."""
    if not update.message:
        return

    stats = _calculate_discount_stats()

    await update.message.reply_text(
        format_discount_stats(stats),
        parse_mode="Markdown"
    )


@authorized_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command - show spending statistics."""
    if not update.message:
        return

    # Check for period argument
    period = "week"
    if context.args:
        arg = context.args[0].lower()
        if arg in ("month", "miesiąc", "miesiac"):
            period = "month"

    stats = _calculate_stats(period)

    await update.message.reply_text(
        format_stats(stats, period),
        parse_mode="Markdown"
    )


@authorized_only
async def stores_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stores command - show spending by store."""
    if not update.message:
        return

    stores = _calculate_stores_stats()

    await update.message.reply_text(
        format_stores_stats(stores),
        parse_mode="Markdown"
    )


@authorized_only
async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /categories command - show spending by category."""
    if not update.message:
        return

    categories = _calculate_categories_stats()

    await update.message.reply_text(
        format_categories_stats(categories),
        parse_mode="Markdown"
    )


def _calculate_stats(period: str = "week") -> dict:
    """Calculate spending statistics for given period."""
    receipts_dir = settings.RECEIPTS_DIR

    if not receipts_dir.exists():
        return {"total": 0, "receipt_count": 0, "product_count": 0}

    # Determine date cutoff
    now = datetime.now()
    if period == "week":
        cutoff = now - timedelta(days=7)
    else:  # month
        cutoff = now - timedelta(days=30)

    total = 0.0
    receipt_count = 0
    product_count = 0

    for file_path in receipts_dir.glob("*.md"):
        if file_path.name.startswith("ERROR_"):
            continue

        receipt_data = _parse_receipt_file(file_path)
        if not receipt_data:
            continue

        # Check date
        receipt_date = receipt_data.get("date")
        if receipt_date:
            try:
                rd = datetime.strptime(receipt_date, "%Y-%m-%d")
                if rd < cutoff:
                    continue
            except ValueError:
                pass

        receipt_count += 1
        total += receipt_data.get("total", 0) or 0
        product_count += receipt_data.get("product_count", 0)

    avg_receipt = total / receipt_count if receipt_count > 0 else 0

    return {
        "total": total,
        "receipt_count": receipt_count,
        "product_count": product_count,
        "avg_receipt": avg_receipt
    }


def _calculate_stores_stats() -> dict[str, dict]:
    """Calculate spending by store."""
    receipts_dir = settings.RECEIPTS_DIR

    if not receipts_dir.exists():
        return {}

    stores: dict[str, dict] = {}

    for file_path in receipts_dir.glob("*.md"):
        if file_path.name.startswith("ERROR_"):
            continue

        receipt_data = _parse_receipt_file(file_path)
        if not receipt_data:
            continue

        store = receipt_data.get("store", "nieznany")
        total = receipt_data.get("total", 0) or 0

        if store not in stores:
            stores[store] = {"total": 0, "count": 0}

        stores[store]["total"] += total
        stores[store]["count"] += 1

    return stores


def _calculate_categories_stats() -> dict[str, dict]:
    """Calculate spending by category from pantry file."""
    from app.obsidian_writer import get_pantry_contents

    contents = get_pantry_contents()

    if not contents:
        return {}

    categories: dict[str, dict] = {}

    for category, items in contents.items():
        total = sum(item.get("price", 0) for item in items)
        count = len(items)

        categories[category] = {
            "total": total,
            "count": count
        }

    return categories


def _parse_receipt_file(file_path: Path) -> Optional[dict]:
    """Parse receipt file and extract metadata."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        frontmatter = yaml.safe_load(parts[1])

        # Count products (lines starting with "- " after frontmatter)
        body = parts[2]
        product_count = sum(1 for line in body.split("\n") if line.strip().startswith("- "))

        return {
            "date": frontmatter.get("date"),
            "store": frontmatter.get("store", "nieznany"),
            "total": frontmatter.get("total"),
            "product_count": product_count
        }
    except Exception as e:
        logger.warning(f"Failed to parse receipt {file_path}: {e}")
        return None
