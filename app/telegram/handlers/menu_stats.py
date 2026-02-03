"""Callback handlers for statistics module menu."""

import logging

from telegram import CallbackQuery
from telegram.ext import ContextTypes

from app.telegram.formatters import (
    format_categories_stats,
    format_stats,
    format_stores_stats,
)
from app.telegram.keyboards import get_main_keyboard, get_stats_menu

logger = logging.getLogger(__name__)


async def handle_stats_callback(
    query: CallbackQuery,
    action: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle stats:* callbacks."""
    if action == "menu":
        await query.edit_message_text(
            "<b>📊 Statystyki</b>\n\nWybierz zakres:",
            parse_mode="HTML",
            reply_markup=get_stats_menu(),
        )

    elif action == "week":
        from app.telegram.handlers.stats import _calculate_stats

        stats = _calculate_stats("week")
        await query.edit_message_text(
            format_stats(stats, "week"),
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )

    elif action == "month":
        from app.telegram.handlers.stats import _calculate_stats

        stats = _calculate_stats("month")
        await query.edit_message_text(
            format_stats(stats, "month"),
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )

    elif action == "stores":
        from app.telegram.handlers.stats import _calculate_stores_stats

        stores = _calculate_stores_stats()
        await query.edit_message_text(
            format_stores_stats(stores),
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )

    elif action == "categories":
        from app.telegram.handlers.stats import _calculate_categories_stats

        categories = _calculate_categories_stats()
        await query.edit_message_text(
            format_categories_stats(categories),
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )

    elif action == "discounts":
        from app.telegram.handlers.stats import _calculate_discount_stats, format_discount_stats

        stats = _calculate_discount_stats()
        await query.edit_message_text(
            format_discount_stats(stats),
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )
