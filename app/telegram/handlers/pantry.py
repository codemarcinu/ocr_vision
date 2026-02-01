"""Pantry management handlers for Telegram bot."""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.obsidian_writer import (
    get_pantry_contents,
    mark_product_used,
    remove_product_from_pantry,
    search_pantry,
)
from app.telegram.formatters import format_pantry_contents, format_search_results
from app.telegram.keyboards import get_pantry_category_keyboard
from app.telegram.middleware import authorized_only

logger = logging.getLogger(__name__)


@authorized_only
async def pantry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pantry command - show pantry contents."""
    if not update.message:
        return

    # Check for category argument
    category: Optional[str] = None
    if context.args:
        category = " ".join(context.args)

    contents = get_pantry_contents()

    if not contents:
        await update.message.reply_text("Spiżarnia jest pusta.")
        return

    # If no category specified, show category keyboard
    if not category:
        available_categories = [c for c in settings.CATEGORIES if c in contents and contents[c]]

        if len(available_categories) > 3:
            await update.message.reply_text(
                "Wybierz kategorię:",
                reply_markup=get_pantry_category_keyboard(available_categories)
            )
            return

    await update.message.reply_text(
        format_pantry_contents(contents, category),
        parse_mode="Markdown"
    )


@authorized_only
async def use_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /use command - mark product as used."""
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Użycie: `/use <nazwa_produktu>`\n\n"
            "Przykład: `/use mleko`\n"
            "Oznacza pierwszy pasujący produkt jako zużyty.",
            parse_mode="Markdown"
        )
        return

    query = " ".join(context.args)
    success, message = mark_product_used(query)

    if success:
        await update.message.reply_text(f"✅ {message}")
    else:
        await update.message.reply_text(f"❌ {message}")


@authorized_only
async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /remove command - remove product from pantry."""
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Użycie: `/remove <nazwa_produktu>`\n\n"
            "Przykład: `/remove mleko`\n"
            "Usuwa pierwszy pasujący produkt ze spiżarni.",
            parse_mode="Markdown"
        )
        return

    query = " ".join(context.args)
    success, message = remove_product_from_pantry(query)

    if success:
        await update.message.reply_text(f"🗑️ {message}")
    else:
        await update.message.reply_text(f"❌ {message}")


@authorized_only
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search command - search products in pantry."""
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Użycie: `/search <fraza>`\n\n"
            "Przykład: `/search ser`\n"
            "Wyszukuje produkty zawierające podaną frazę.",
            parse_mode="Markdown"
        )
        return

    query = " ".join(context.args)
    results = search_pantry(query)

    await update.message.reply_text(
        format_search_results(results, query),
        parse_mode="Markdown"
    )
