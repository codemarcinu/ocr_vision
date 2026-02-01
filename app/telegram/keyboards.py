"""Inline keyboards for Telegram bot."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Get main menu keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("Spiżarnia", callback_data="pantry"),
            InlineKeyboardButton("Statystyki", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("Ostatnie paragony", callback_data="recent"),
            InlineKeyboardButton("Błędy", callback_data="errors"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_stats_keyboard() -> InlineKeyboardMarkup:
    """Get stats options keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("Tydzień", callback_data="stats_week"),
            InlineKeyboardButton("Miesiąc", callback_data="stats_month"),
        ],
        [
            InlineKeyboardButton("Sklepy", callback_data="stores"),
            InlineKeyboardButton("Kategorie", callback_data="categories"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_pantry_category_keyboard(categories: list[str]) -> InlineKeyboardMarkup:
    """Get pantry category selection keyboard."""
    keyboard = []
    row = []
    for i, category in enumerate(categories):
        row.append(InlineKeyboardButton(category, callback_data=f"pantry_{category}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("Wszystkie", callback_data="pantry_all")])
    return InlineKeyboardMarkup(keyboard)


def get_confirm_keyboard(action: str, item_id: str) -> InlineKeyboardMarkup:
    """Get confirmation keyboard for actions."""
    keyboard = [
        [
            InlineKeyboardButton("Tak", callback_data=f"confirm_{action}_{item_id}"),
            InlineKeyboardButton("Nie", callback_data="cancel"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_review_keyboard(receipt_id: str) -> InlineKeyboardMarkup:
    """Get keyboard for receipt review (human-in-the-loop)."""
    keyboard = [
        [
            InlineKeyboardButton("Zatwierdź", callback_data=f"review_approve_{receipt_id}"),
            InlineKeyboardButton("Popraw sumę", callback_data=f"review_edit_{receipt_id}"),
        ],
        [
            InlineKeyboardButton("Odrzuć", callback_data=f"review_reject_{receipt_id}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_total_correction_keyboard(receipt_id: str, calculated_total: float) -> InlineKeyboardMarkup:
    """Get keyboard for total correction options."""
    keyboard = [
        [
            InlineKeyboardButton(
                f"Użyj sumy produktów ({calculated_total:.2f} zł)",
                callback_data=f"review_use_calculated_{receipt_id}"
            ),
        ],
        [
            InlineKeyboardButton("Wpisz ręcznie", callback_data=f"review_manual_{receipt_id}"),
        ],
        [
            InlineKeyboardButton("Anuluj", callback_data=f"review_cancel_{receipt_id}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)
