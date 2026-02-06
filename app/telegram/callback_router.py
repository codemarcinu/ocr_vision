"""Prefix-based callback query router for Telegram bot.

Routes callback queries to module-specific handlers based on prefix.
Automatically answers the query and strips the prefix before dispatching.
"""

import logging
from typing import Callable, Awaitable

from telegram import CallbackQuery
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Handler receives: (query, action, context) where action is data with prefix stripped
CallbackHandler = Callable[
    [CallbackQuery, str, ContextTypes.DEFAULT_TYPE],
    Awaitable[None],
]


class CallbackRouter:
    """Route callback queries by prefix to module handlers."""

    def __init__(self):
        self._handlers: dict[str, CallbackHandler] = {}

    def register(self, prefix: str, handler: CallbackHandler) -> None:
        """Register handler for callback prefix.

        Args:
            prefix: Callback data prefix (e.g., "receipts:", "notes:")
            handler: Async function(query, action, context)
                     where action is the data with the prefix stripped.
        """
        self._handlers[prefix] = handler

    async def route(
        self,
        query: CallbackQuery,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        """Route callback query to appropriate handler.

        Answers the query, strips the prefix, and passes the remaining
        action string to the matched handler.

        Returns True if a handler was found, False otherwise.
        """
        data = query.data or ""

        for prefix, handler in self._handlers.items():
            if data.startswith(prefix):
                await query.answer()
                action = data[len(prefix):]
                try:
                    await handler(query, action, context)
                except Exception as e:
                    logger.error(f"Callback handler error for {prefix}: {e}", exc_info=True)
                    try:
                        await query.edit_message_text("Wystąpił błąd. Spróbuj ponownie później.")
                    except Exception:
                        pass
                return True

        return False
