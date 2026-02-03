"""Callback handlers for receipts module menu."""

import logging

from telegram import CallbackQuery
from telegram.ext import ContextTypes

from app.telegram.formatters import (
    escape_html,
    format_errors,
    format_pantry_contents,
    format_pending_files,
    format_receipt_list,
)
from app.telegram.keyboards import (
    get_main_keyboard,
    get_pantry_quick_actions,
    get_receipts_menu,
)

logger = logging.getLogger(__name__)


async def handle_receipts_callback(
    query: CallbackQuery,
    action: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle receipts:* callbacks."""
    if action == "menu":
        await query.edit_message_text(
            "<b>🧾 Paragony</b>\n\n"
            "Wyślij zdjęcie paragonu lub PDF aby przetworzyć.\n"
            "Wybierz opcję poniżej:",
            parse_mode="HTML",
            reply_markup=get_receipts_menu(),
        )

    elif action == "recent":
        from app.telegram.handlers.receipts import _get_recent_receipts

        receipts = _get_recent_receipts(5)
        await query.edit_message_text(
            format_receipt_list(receipts),
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )

    elif action == "pending":
        from app.config import settings

        inbox = settings.INBOX_DIR
        files = []
        if inbox.exists():
            extensions = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}
            files = [
                f.name
                for f in inbox.iterdir()
                if f.suffix.lower() in extensions
            ]
            files.sort()

        await query.edit_message_text(
            format_pending_files(files),
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )

    elif action == "pantry":
        from app.obsidian_writer import get_pantry_contents

        contents = get_pantry_contents()
        await query.edit_message_text(
            format_pantry_contents(contents),
            parse_mode="HTML",
            reply_markup=get_pantry_quick_actions(),
        )

    elif action == "errors":
        from app.obsidian_writer import get_errors

        errors = get_errors()
        await query.edit_message_text(
            format_errors(errors),
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )
