"""Prefix-based callback query router for Telegram bot.

Routes callback queries to module-specific handlers based on prefix.
Replaces the monolithic if/elif chain in bot.py.
"""

import logging
from typing import Callable, Awaitable

from telegram import CallbackQuery
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Type for callback handler functions
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
            handler: Async function(query, data, context)
        """
        self._handlers[prefix] = handler
        logger.debug(f"Registered callback handler for prefix: {prefix}")

    async def route(
        self,
        query: CallbackQuery,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        """Route callback query to appropriate handler.

        Returns True if a handler was found, False otherwise.
        """
        data = query.data or ""

        for prefix, handler in self._handlers.items():
            if data.startswith(prefix):
                try:
                    await handler(query, data, context)
                except Exception as e:
                    logger.error(f"Callback handler error for {prefix}: {e}", exc_info=True)
                    try:
                        await query.edit_message_text(f"Wystąpił błąd: {e}")
                    except Exception:
                        pass
                return True

        return False
