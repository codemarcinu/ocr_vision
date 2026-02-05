"""Inline menu handler for Chat AI module."""

import logging
from uuid import UUID

from telegram import CallbackQuery
from telegram.ext import ContextTypes

from app.config import settings
from app.db.connection import get_session
from app.db.repositories.chat import ChatRepository
from app.telegram.formatters import escape_html
from app.telegram.keyboards import get_chat_menu, get_main_keyboard

logger = logging.getLogger(__name__)


async def handle_chat_callback(
    query: CallbackQuery,
    action: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle chat:* callbacks."""
    if action == "menu":
        if not settings.CHAT_ENABLED:
            await query.edit_message_text(
                "Chat AI jest wyłączony.",
                reply_markup=get_main_keyboard(),
            )
            return

        await query.edit_message_text(
            "<b>💬 Chat AI</b>\n\n"
            "Po prostu pisz - odpowiem z dostępem do bazy wiedzy i internetu.\n\n"
            "Możesz też użyć <code>/ask pytanie</code> dla szybkiego wyszukiwania w bazie.",
            parse_mode="HTML",
            reply_markup=get_chat_menu(),
        )

    elif action == "sessions":
        try:
            async for session in get_session():
                chat_repo = ChatRepository(session)
                sessions = await chat_repo.get_user_sessions(
                    source="telegram", limit=10
                )

                if not sessions:
                    await query.edit_message_text(
                        "<b>💬 Historia rozmów</b>\n\n"
                        "Brak zapisanych rozmów.",
                        parse_mode="HTML",
                        reply_markup=get_chat_menu(),
                    )
                    return

                lines = ["<b>💬 Historia rozmów</b>\n"]

                # Get current active session ID
                active_session_id = (
                    context.user_data.get("active_chat_session")
                    if context.user_data
                    else None
                )

                for s in sessions:
                    title = escape_html(s.title or "Bez tytułu")
                    if len(title) > 40:
                        title = title[:37] + "..."

                    # Mark active session
                    is_current = str(s.id) == active_session_id and s.is_active
                    marker = "🟢" if is_current else ("⚪" if s.is_active else "⚫")

                    date = s.created_at.strftime("%d.%m %H:%M") if s.created_at else ""
                    lines.append(f"{marker} {title}  <i>{date}</i>")

                lines.append("\n🟢 = aktualna  ⚪ = aktywna  ⚫ = zakończona")

                await query.edit_message_text(
                    "\n".join(lines),
                    parse_mode="HTML",
                    reply_markup=get_chat_menu(),
                )
        except Exception as e:
            logger.error(f"Failed to list chat sessions: {e}")
            await query.edit_message_text(
                f"Błąd pobierania historii: {e}",
                reply_markup=get_main_keyboard(),
            )

    elif action == "new":
        # End current session and start fresh
        old_session_id = (
            context.user_data.pop("active_chat_session", None)
            if context.user_data
            else None
        )

        try:
            async for session in get_session():
                chat_repo = ChatRepository(session)

                # End old session if exists
                if old_session_id:
                    await chat_repo.end_session(UUID(old_session_id))

                # Create new session
                chat_id = query.message.chat.id
                chat_session = await chat_repo.create_session(
                    source="telegram", telegram_chat_id=chat_id,
                )
                await session.commit()

                if context.user_data is None:
                    context.user_data = {}
                context.user_data["active_chat_session"] = str(chat_session.id)

            await query.edit_message_text(
                "✅ <b>Nowa rozmowa rozpoczęta!</b>\n\n"
                "Poprzednia sesja została zapisana w historii.\n"
                "Po prostu pisz - odpowiem.",
                parse_mode="HTML",
                reply_markup=get_chat_menu(),
            )
        except Exception as e:
            logger.error(f"Failed to create new chat session: {e}")
            await query.edit_message_text(
                f"Błąd tworzenia nowej rozmowy: {e}",
                reply_markup=get_main_keyboard(),
            )

    # Backward compatibility - redirect old actions
    elif action in ("start", "end"):
        # Redirect to menu with info
        await query.edit_message_text(
            "<b>💬 Chat AI</b>\n\n"
            "Chat działa teraz automatycznie - po prostu pisz!\n\n"
            "Użyj <b>Nowa rozmowa</b> aby rozpocząć od nowa.",
            parse_mode="HTML",
            reply_markup=get_chat_menu(),
        )
