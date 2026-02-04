"""Authorization middleware for Telegram bot."""

import logging
from functools import wraps
from typing import Callable, TypeVar, ParamSpec

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


def authorized_only(func: Callable[P, T]) -> Callable[P, T]:
    """Decorator to restrict access to authorized chat_id only.

    Works with both standalone functions and class methods.
    """
    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        # Handle both standalone functions (update, context) and methods (self, update, context)
        if args and isinstance(args[0], Update):
            update = args[0]
            context = args[1]
        elif len(args) >= 2 and isinstance(args[1], Update):
            update = args[1]
            context = args[2]
        else:
            logger.error("Could not find Update in arguments")
            return None

        if not update.effective_chat:
            return None

        chat_id = update.effective_chat.id

        if settings.TELEGRAM_CHAT_ID == 0:
            logger.error("TELEGRAM_CHAT_ID not configured - denying access")
            if update.message:
                await update.message.reply_text(
                    "Bot nie skonfigurowany. Ustaw zmienną TELEGRAM_CHAT_ID."
                )
            return None

        if chat_id != settings.TELEGRAM_CHAT_ID:
            logger.warning(f"Unauthorized access attempt from chat_id: {chat_id}")
            if update.message:
                await update.message.reply_text(
                    "Brak autoryzacji. Twoje chat_id nie jest na liście dozwolonych."
                )
            return None

        return await func(*args, **kwargs)

    return wrapper


def is_authorized(chat_id: int) -> bool:
    """Check if chat_id is authorized."""
    if settings.TELEGRAM_CHAT_ID == 0:
        return False
    return chat_id == settings.TELEGRAM_CHAT_ID
