"""Inline keyboards for Telegram bot."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ============================================================
# Main menu
# ============================================================

def get_main_keyboard() -> InlineKeyboardMarkup:
    """Get main menu keyboard with all modules."""
    keyboard = [
        [
            InlineKeyboardButton("📝 Notatki", callback_data="notes:menu"),
            InlineKeyboardButton("🧾 Paragony", callback_data="receipts:menu"),
        ],
        [
            InlineKeyboardButton("📰 Artykuły", callback_data="articles:menu"),
            InlineKeyboardButton("🎙️ Transkrypcje", callback_data="transcriptions:menu"),
        ],
        [
            InlineKeyboardButton("🔖 Zakładki", callback_data="bookmarks:menu"),
            InlineKeyboardButton("📊 Statystyki", callback_data="stats:menu"),
        ],
        [
            InlineKeyboardButton("💬 Chat AI", callback_data="chat:menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_button() -> list[InlineKeyboardButton]:
    """Get back-to-menu button row."""
    return [InlineKeyboardButton("◀️ Menu", callback_data="main_menu")]


# ============================================================
# Module sub-menus
# ============================================================

def get_receipts_menu() -> InlineKeyboardMarkup:
    """Receipt management sub-menu."""
    keyboard = [
        [
            InlineKeyboardButton("🧾 Ostatnie", callback_data="receipts:recent"),
            InlineKeyboardButton("⏳ Oczekujące", callback_data="receipts:pending"),
        ],
        [
            InlineKeyboardButton("🏠 Spiżarnia", callback_data="receipts:pantry"),
            InlineKeyboardButton("❌ Błędy", callback_data="receipts:errors"),
        ],
        get_back_button(),
    ]
    return InlineKeyboardMarkup(keyboard)


def get_articles_menu() -> InlineKeyboardMarkup:
    """Articles/RSS sub-menu."""
    keyboard = [
        [
            InlineKeyboardButton("📡 Feedy", callback_data="articles:feeds"),
            InlineKeyboardButton("📋 Ostatnie", callback_data="articles:recent"),
        ],
        [
            InlineKeyboardButton("🔄 Odśwież", callback_data="articles:refresh"),
        ],
        get_back_button(),
    ]
    return InlineKeyboardMarkup(keyboard)


def get_transcriptions_menu() -> InlineKeyboardMarkup:
    """Transcription sub-menu."""
    keyboard = [
        [
            InlineKeyboardButton("📋 Lista", callback_data="transcriptions:list"),
        ],
        get_back_button(),
    ]
    return InlineKeyboardMarkup(keyboard)


def get_stats_menu() -> InlineKeyboardMarkup:
    """Statistics sub-menu."""
    keyboard = [
        [
            InlineKeyboardButton("Tydzień", callback_data="stats:week"),
            InlineKeyboardButton("Miesiąc", callback_data="stats:month"),
        ],
        [
            InlineKeyboardButton("Sklepy", callback_data="stats:stores"),
            InlineKeyboardButton("Kategorie", callback_data="stats:categories"),
        ],
        [
            InlineKeyboardButton("🏷️ Rabaty", callback_data="stats:discounts"),
        ],
        get_back_button(),
    ]
    return InlineKeyboardMarkup(keyboard)


def get_notes_menu() -> InlineKeyboardMarkup:
    """Personal notes sub-menu."""
    keyboard = [
        [
            InlineKeyboardButton("✏️ Nowa notatka", callback_data="notes:new"),
            InlineKeyboardButton("📋 Lista", callback_data="notes:list"),
        ],
        get_back_button(),
    ]
    return InlineKeyboardMarkup(keyboard)


def get_bookmarks_menu() -> InlineKeyboardMarkup:
    """Bookmarks sub-menu."""
    keyboard = [
        [
            InlineKeyboardButton("📋 Wszystkie", callback_data="bookmarks:list"),
            InlineKeyboardButton("⏳ Oczekujące", callback_data="bookmarks:pending"),
        ],
        get_back_button(),
    ]
    return InlineKeyboardMarkup(keyboard)


def get_chat_menu(has_active_session: bool = False) -> InlineKeyboardMarkup:
    """Chat AI sub-menu."""
    if has_active_session:
        keyboard = [
            [
                InlineKeyboardButton("⏹️ Zakończ czat", callback_data="chat:end"),
            ],
            [
                InlineKeyboardButton("📋 Sesje", callback_data="chat:sessions"),
            ],
            get_back_button(),
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("▶️ Rozpocznij czat", callback_data="chat:start"),
            ],
            [
                InlineKeyboardButton("📋 Sesje", callback_data="chat:sessions"),
            ],
            get_back_button(),
        ]
    return InlineKeyboardMarkup(keyboard)


def get_url_action_keyboard(url_key: str) -> InlineKeyboardMarkup:
    """Get action picker for a received URL.

    Args:
        url_key: Short key to reference stored URL in user_data.
    """
    keyboard = [
        [
            InlineKeyboardButton("🔖 Zapisz", callback_data=f"url:bookmark:{url_key}"),
            InlineKeyboardButton("📝 Podsumuj", callback_data=f"url:summarize:{url_key}"),
        ],
        [
            InlineKeyboardButton("🎙️ Transkrybuj", callback_data=f"url:transcribe:{url_key}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# Existing keyboards (unchanged)
# ============================================================

def get_receipt_actions_keyboard(receipt_id: str, has_discounts: bool = False) -> InlineKeyboardMarkup:
    """Get contextual actions for processed receipt."""
    keyboard = [
        [
            InlineKeyboardButton("📊 Statystyki", callback_data="stats:menu"),
            InlineKeyboardButton("🏠 Spiżarnia", callback_data="receipts:pantry"),
        ],
    ]

    if has_discounts:
        keyboard.append([
            InlineKeyboardButton("🏷️ Zobacz rabaty", callback_data=f"receipt_discounts_{receipt_id}"),
        ])

    keyboard.append(get_back_button())

    return InlineKeyboardMarkup(keyboard)


def get_pantry_quick_actions() -> InlineKeyboardMarkup:
    """Quick actions for pantry management."""
    keyboard = [
        [
            InlineKeyboardButton("🔍 Szukaj", callback_data="pantry_search"),
            InlineKeyboardButton("📊 Statystyki", callback_data="stats:menu"),
        ],
        [
            InlineKeyboardButton("🧾 Paragony", callback_data="receipts:recent"),
            InlineKeyboardButton("📋 Menu", callback_data="main_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_stats_keyboard() -> InlineKeyboardMarkup:
    """Get stats options keyboard (legacy, used by /stats command)."""
    return get_stats_menu()


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
