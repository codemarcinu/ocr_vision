"""Error handling for Telegram bot."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.obsidian_writer import clear_error_log, get_errors
from app.telegram.formatters import format_errors
from app.telegram.middleware import authorized_only

logger = logging.getLogger(__name__)


@authorized_only
async def errors_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /errors command - show error log."""
    if not update.message:
        return

    errors = get_errors()

    await update.message.reply_text(
        format_errors(errors),
        parse_mode="Markdown"
    )


@authorized_only
async def clearerrors_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clearerrors command - clear error log."""
    if not update.message:
        return

    success = clear_error_log()

    if success:
        await update.message.reply_text("✅ Log błędów został wyczyszczony.")
    else:
        await update.message.reply_text("❌ Nie udało się wyczyścić logu błędów.")
