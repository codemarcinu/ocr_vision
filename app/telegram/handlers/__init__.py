"""Telegram bot handlers."""

from app.telegram.handlers.ask import (
    ask_command,
)
from app.telegram.handlers.receipts import (
    handle_document,
    handle_photo,
    recent_command,
    reprocess_command,
    pending_command,
)
from app.telegram.handlers.pantry import (
    pantry_command,
    use_command,
    remove_command,
    search_command,
)
from app.telegram.handlers.stats import (
    stats_command,
    stores_command,
    categories_command,
    discounts_command,
)
from app.telegram.handlers.errors import (
    errors_command,
    clearerrors_command,
)
from app.telegram.handlers.json_import import (
    is_json_receipt,
    process_json_import,
)
from app.telegram.handlers.feeds import (
    feeds_command,
    subscribe_command,
    unsubscribe_command,
    summarize_command,
    refresh_command,
    articles_command,
)
from app.telegram.handlers.transcription import (
    transcribe_command,
    transcriptions_command,
    note_command,
)
from app.telegram.handlers.search import (
    find_command,
)
from app.telegram.handlers.settings import (
    settings_command,
)
from app.telegram.handlers.chat import (
    chat_command,
    endchat_command,
    handle_chat_message,
)
from app.telegram.handlers.voice_notes import (
    handle_voice_note,
)
from app.telegram.handlers.daily import (
    daily_command,
)
from app.telegram.handlers.profile import (
    profile_command,
    setstores_command,
    setcity_command,
    handle_profile_callback,
)

__all__ = [
    "ask_command",
    "handle_document",
    "handle_photo",
    "recent_command",
    "reprocess_command",
    "pending_command",
    "pantry_command",
    "use_command",
    "remove_command",
    "search_command",
    "stats_command",
    "stores_command",
    "categories_command",
    "discounts_command",
    "errors_command",
    "clearerrors_command",
    "is_json_receipt",
    "process_json_import",
    "feeds_command",
    "subscribe_command",
    "unsubscribe_command",
    "summarize_command",
    "refresh_command",
    "articles_command",
    "transcribe_command",
    "transcriptions_command",
    "note_command",
    "find_command",
    "settings_command",
    "chat_command",
    "endchat_command",
    "handle_chat_message",
    "handle_voice_note",
    "daily_command",
    "profile_command",
    "setstores_command",
    "setcity_command",
    "handle_profile_callback",
]
