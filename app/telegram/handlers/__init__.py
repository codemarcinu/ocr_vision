"""Telegram bot handlers."""

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

__all__ = [
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
]
