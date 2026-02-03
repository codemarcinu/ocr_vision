"""Inline menu handler for Chat AI module."""

import logging
from uuid import UUID

from telegram import CallbackQuery
from telegram.ext import ContextTypes

from app.config import settings
from app.db.connection import get_session
from app.db.repositories.chat import ChatRepository
from app.telegram.keyboards import get_chat_menu, get_main_keyboard

logger = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


async def handle_chat_callback(
    query: CallbackQuery,
    data: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle chat:* callbacks."""
    await query.answer()
    action = data.split(":", 1)[1] if ":" in data else ""

    if action == "menu":
        if not settings.CHAT_ENABLED:
            await query.edit_message_text(
                "Chat AI jest wyłączony.",
                reply_markup=get_main_keyboard(),
            )
            return

        has_active = bool(
            context.user_data and context.user_data.get("active_chat_session")
        )

        status = "aktywna" if has_active else "brak"
        await query.edit_message_text(
            f"<b>💬 Chat AI</b>\n\n"
            f"Wieloturowa konwersacja z dostępem do bazy wiedzy i internetu.\n\n"
            f"Sesja: <b>{status}</b>",
            parse_mode="HTML",
            reply_markup=get_chat_menu(has_active_session=has_active),
        )

    elif action == "start":
        if not settings.CHAT_ENABLED:
            await query.edit_message_text(
                "Chat AI jest wyłączony.",
                reply_markup=get_main_keyboard(),
            )
            return

        # Check if already active
        if context.user_data and context.user_data.get("active_chat_session"):
            await query.edit_message_text(
                "💬 <b>Sesja czatu jest już aktywna!</b>\n\n"
                "Pisz wiadomości, a ja odpowiem.\n"
                "Użyj przycisku poniżej aby zakończyć.",
                parse_mode="HTML",
                reply_markup=get_chat_menu(has_active_session=True),
            )
            return

        chat_id = query.message.chat.id

        try:
            async for session in get_session():
                chat_repo = ChatRepository(session)
                chat_session = await chat_repo.create_session(
                    source="telegram", telegram_chat_id=chat_id,
                )
                await session.commit()

                if context.user_data is None:
                    context.user_data = {}
                context.user_data["active_chat_session"] = str(chat_session.id)

            await query.edit_message_text(
                "💬 <b>Sesja czatu rozpoczęta!</b>\n\n"
                "Pisz wiadomości - odpowiem z dostępem do Twojej bazy wiedzy i internetu.\n\n"
                "Aby zakończyć, użyj /endchat lub przycisk w menu.",
                parse_mode="HTML",
                reply_markup=get_chat_menu(has_active_session=True),
            )
        except Exception as e:
            logger.error(f"Failed to create chat session: {e}")
            await query.edit_message_text(
                f"Błąd tworzenia sesji: {e}",
                reply_markup=get_main_keyboard(),
            )

    elif action == "end":
        session_id = (
            context.user_data.pop("active_chat_session", None)
            if context.user_data
            else None
        )

        if session_id:
            try:
                async for session in get_session():
                    chat_repo = ChatRepository(session)
                    await chat_repo.end_session(UUID(session_id))
                    await session.commit()
            except Exception as e:
                logger.error(f"Failed to end chat session: {e}")

            await query.edit_message_text(
                "✅ <b>Sesja czatu zakończona.</b>",
                parse_mode="HTML",
                reply_markup=get_chat_menu(has_active_session=False),
            )
        else:
            await query.edit_message_text(
                "Brak aktywnej sesji czatu.",
                reply_markup=get_chat_menu(has_active_session=False),
            )

    elif action == "sessions":
        try:
            async for session in get_session():
                chat_repo = ChatRepository(session)
                sessions = await chat_repo.get_user_sessions(
                    source="telegram", limit=5
                )

                if not sessions:
                    await query.edit_message_text(
                        "<b>💬 Sesje czatu</b>\n\n"
                        "Brak zapisanych sesji.",
                        parse_mode="HTML",
                        reply_markup=get_chat_menu(
                            has_active_session=bool(
                                context.user_data
                                and context.user_data.get("active_chat_session")
                            )
                        ),
                    )
                    return

                lines = ["<b>💬 Ostatnie sesje czatu</b>\n"]
                for s in sessions:
                    title = _escape_html(s.title or "Bez tytułu")
                    if len(title) > 40:
                        title = title[:37] + "..."
                    status = "🟢" if s.is_active else "⚪"
                    date = s.created_at.strftime("%d.%m %H:%M") if s.created_at else ""
                    lines.append(f"{status} {title}  <i>{date}</i>")

                await query.edit_message_text(
                    "\n".join(lines),
                    parse_mode="HTML",
                    reply_markup=get_chat_menu(
                        has_active_session=bool(
                            context.user_data
                            and context.user_data.get("active_chat_session")
                        )
                    ),
                )
        except Exception as e:
            logger.error(f"Failed to list chat sessions: {e}")
            await query.edit_message_text(
                f"Błąd pobierania sesji: {e}",
                reply_markup=get_main_keyboard(),
            )
