"""Telegram /chat and /endchat handlers for multi-turn conversations."""

import logging
from uuid import UUID

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.db.connection import get_session
from app.db.repositories.chat import ChatRepository
from app.chat import orchestrator
from app.telegram.middleware import authorized_only

logger = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _search_type_label(search_type: str) -> str:
    """Get label for search type."""
    return {
        "rag": "📚 Baza wiedzy",
        "web": "🌐 Internet",
        "both": "📚🌐 Baza + Internet",
        "direct": "💬 Bezpośrednio",
    }.get(search_type, "")


@authorized_only
async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /chat [question] command - start or continue a chat session."""
    if not update.message:
        return

    if not settings.CHAT_ENABLED:
        await update.message.reply_text("Chat jest wyłączony.")
        return

    chat_id = update.effective_chat.id

    # Check if there's already an active session
    active_session_id = context.user_data.get("active_chat_session") if context.user_data else None

    if context.args:
        # /chat <question> - send message (create session if needed)
        question = " ".join(context.args)

        status_msg = await update.message.reply_text("🤔 Myślę...")

        try:
            async for session in get_session():
                chat_repo = ChatRepository(session)

                # Get or create session
                if active_session_id:
                    chat_session = await chat_repo.get_by_id(UUID(active_session_id))
                    if not chat_session or not chat_session.is_active:
                        chat_session = None

                if not active_session_id or not chat_session:
                    chat_session = await chat_repo.create_session(
                        source="telegram", telegram_chat_id=chat_id,
                    )
                    await session.commit()
                    context.user_data["active_chat_session"] = str(chat_session.id)

                # Save user message
                await chat_repo.add_message(
                    session_id=chat_session.id, role="user", content=question,
                )
                await session.commit()

                # Process
                response = await orchestrator.process_message(
                    message=question,
                    session_id=chat_session.id,
                    db_session=session,
                )

                # Save assistant message
                await chat_repo.add_message(
                    session_id=chat_session.id,
                    role="assistant",
                    content=response.answer,
                    sources=response.sources,
                    search_type=response.search_type,
                    model_used=response.model_used,
                    processing_time_sec=response.processing_time_sec,
                )

                # Auto-generate title
                if not chat_session.title:
                    await chat_repo.generate_title(chat_session.id)

                await session.commit()

            # Format response
            parts = [_escape_html(response.answer)]

            if response.sources:
                parts.append("\n---")
                for s in response.sources[:3]:
                    emoji = "📚" if s.get("type") == "rag" else "🌐"
                    title = _escape_html(s.get("title", "")[:40])
                    parts.append(f"{emoji} {title}")

            parts.append(
                f"\n<i>{_search_type_label(response.search_type)} | "
                f"{response.processing_time_sec:.1f}s</i>"
            )

            try:
                await status_msg.edit_text("\n".join(parts), parse_mode="HTML")
            except Exception:
                plain = "\n".join(parts)
                plain = plain.replace("<i>", "").replace("</i>", "")
                await status_msg.edit_text(plain[:4096])

        except Exception as e:
            logger.error(f"Chat error: {e}", exc_info=True)
            await status_msg.edit_text(f"❌ Błąd: {e}")

    else:
        # /chat without args - start/show session info
        if active_session_id:
            await update.message.reply_text(
                "💬 <b>Tryb czatu aktywny</b>\n\n"
                "Pisz wiadomości - będę odpowiadać z dostępem do bazy wiedzy i internetu.\n"
                "Użyj /endchat aby zakończyć sesję.\n"
                "Użyj /chat &lt;pytanie&gt; aby wysłać wiadomość.",
                parse_mode="HTML",
            )
        else:
            # Create new session
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

                await update.message.reply_text(
                    "💬 <b>Rozpoczynam sesję czatu</b>\n\n"
                    "Pisz wiadomości - będę odpowiadać z dostępem do Twojej bazy wiedzy i internetu.\n"
                    "Użyj /endchat aby zakończyć sesję.",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"Failed to create chat session: {e}")
                await update.message.reply_text(f"❌ Błąd tworzenia sesji: {e}")


@authorized_only
async def endchat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /endchat command - end active chat session."""
    if not update.message:
        return

    session_id = context.user_data.pop("active_chat_session", None) if context.user_data else None

    if session_id:
        try:
            async for session in get_session():
                chat_repo = ChatRepository(session)
                await chat_repo.end_session(UUID(session_id))
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to end chat session: {e}")

        await update.message.reply_text("✅ Sesja czatu zakończona.")
    else:
        await update.message.reply_text("Brak aktywnej sesji czatu. Użyj /chat aby rozpocząć.")


async def handle_chat_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle a text message in active chat session (called from _handle_text_input)."""
    if not update.message or not update.message.text:
        return

    message = update.message.text.strip()
    session_id = context.user_data.get("active_chat_session")

    if not session_id:
        return

    status_msg = await update.message.reply_text("🤔 Myślę...")

    try:
        async for session in get_session():
            chat_repo = ChatRepository(session)

            # Verify session exists and is active
            chat_session = await chat_repo.get_by_id(UUID(session_id))
            if not chat_session or not chat_session.is_active:
                context.user_data.pop("active_chat_session", None)
                await status_msg.edit_text(
                    "Sesja czatu wygasła. Użyj /chat aby rozpocząć nową."
                )
                return

            # Save user message
            await chat_repo.add_message(
                session_id=chat_session.id, role="user", content=message,
            )
            await session.commit()

            # Process
            response = await orchestrator.process_message(
                message=message,
                session_id=chat_session.id,
                db_session=session,
            )

            # Save assistant message
            await chat_repo.add_message(
                session_id=chat_session.id,
                role="assistant",
                content=response.answer,
                sources=response.sources,
                search_type=response.search_type,
                model_used=response.model_used,
                processing_time_sec=response.processing_time_sec,
            )
            await session.commit()

        # Format response
        parts = [_escape_html(response.answer)]

        if response.sources:
            parts.append("\n---")
            for s in response.sources[:3]:
                emoji = "📚" if s.get("type") == "rag" else "🌐"
                title = _escape_html(s.get("title", "")[:40])
                parts.append(f"{emoji} {title}")

        parts.append(
            f"\n<i>{_search_type_label(response.search_type)} | "
            f"{response.processing_time_sec:.1f}s</i>"
        )

        try:
            await status_msg.edit_text("\n".join(parts), parse_mode="HTML")
        except Exception:
            plain = "\n".join(parts)
            plain = plain.replace("<i>", "").replace("</i>", "")
            await status_msg.edit_text(plain[:4096])

    except Exception as e:
        logger.error(f"Chat message error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Błąd: {e}")
