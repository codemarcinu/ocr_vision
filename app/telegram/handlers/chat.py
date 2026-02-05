"""Telegram /chat and /endchat handlers for multi-turn conversations."""

import logging
from uuid import UUID

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.db.connection import get_session
from app.db.repositories.chat import ChatRepository
from app.chat import orchestrator
from app.telegram.formatters import escape_html
from app.telegram.middleware import authorized_only

logger = logging.getLogger(__name__)


# Keywords that suggest user wants an ACTION (not just a search/conversation)
# Agent will only be invoked if message contains one of these patterns
_ACTION_KEYWORDS = [
    # Note creation
    "zanotuj", "zapisz notatkę", "notatka:", "dodaj notatkę", "note:",
    "zapamiętaj", "przypomnij mi",
    # Bookmarks
    "zapisz link", "dodaj zakładkę", "bookmark", "zachowaj link",
    # Summarization (with URL)
    "streść", "podsumuj", "streszczenie",
    # List recent
    "pokaż ostatnie", "ostatnie notatki", "ostatnie zakładki",
    "ostatnie paragony", "ostatnie artykuły", "lista notatek",
    "wyświetl ostatnie", "co ostatnio",
]


def _looks_like_action(message: str) -> bool:
    """Check if message looks like an action command (heuristic pre-filter).

    This avoids invoking the agent (and model switch) for regular questions.
    """
    msg_lower = message.lower()

    # Check for action keywords
    for keyword in _ACTION_KEYWORDS:
        if keyword in msg_lower:
            return True

    # Check for URL + action verb (suggests summarize or bookmark)
    has_url = "http://" in msg_lower or "https://" in msg_lower or "www." in msg_lower
    if has_url:
        action_verbs = ["zapisz", "dodaj", "streść", "podsumuj", "zachowaj"]
        if any(verb in msg_lower for verb in action_verbs):
            return True

    return False


async def _try_agent_action(message: str, db_session) -> tuple[bool, str | None]:
    """Try to execute message as agent action.

    Returns:
        (executed, result_text) - executed=True if action was performed
    """
    if not settings.CHAT_AGENT_ENABLED:
        return False, None

    # Heuristic pre-filter: skip agent if message doesn't look like an action
    # This avoids model switching for regular questions
    if not _looks_like_action(message):
        return False, None

    try:
        from app.chat.agent_executor import process_with_agent

        result = await process_with_agent(message, db_session)

        if result.executed:
            return True, result.result_text
        elif result.error:
            logger.warning(f"Agent error (falling back to chat): {result.error}")

        return False, None
    except Exception as e:
        logger.warning(f"Agent processing failed: {e}")
        return False, None


def _search_type_label(search_type: str) -> str:
    """Get label for search type."""
    return {
        "rag": "📚 Baza wiedzy",
        "rag→web": "📚→🌐 Baza → Internet",
        "web": "🌐 Internet",
        "web→rag": "🌐→📚 Internet → Baza",
        "both": "📚🌐 Baza + Internet",
        "spending": "💰 Wydatki",
        "inventory": "🥫 Spiżarnia",
        "weather": "⛅ Pogoda",
        "direct": "💬 Bezpośrednio",
        "agent": "🤖 Agent",
    }.get(search_type, search_type)


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

                # Try agent action first (create_note, bookmark, summarize, list)
                agent_executed, agent_result = await _try_agent_action(question, session)

                if agent_executed and agent_result:
                    # Save user message
                    await chat_repo.add_message(
                        session_id=chat_session.id, role="user", content=question,
                    )
                    # Save agent response
                    await chat_repo.add_message(
                        session_id=chat_session.id,
                        role="assistant",
                        content=agent_result,
                        search_type="agent",
                    )

                    # Auto-generate title
                    if not chat_session.title:
                        await chat_repo.generate_title(chat_session.id)

                    await session.commit()

                    # Format and send response
                    parts = [escape_html(agent_result)]
                    parts.append("\n<i>🤖 Agent</i>")

                    try:
                        await status_msg.edit_text("\n".join(parts), parse_mode="HTML")
                    except Exception:
                        await status_msg.edit_text(agent_result[:4096])
                    return

                # Fall through to orchestrator
                # Save user message
                await chat_repo.add_message(
                    session_id=chat_session.id, role="user", content=question,
                )
                await session.commit()

                # Process with orchestrator
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
            parts = [escape_html(response.answer)]

            if response.sources:
                parts.append("\n---")
                for s in response.sources[:3]:
                    emoji = "📚" if s.get("type") == "rag" else "🌐"
                    title = escape_html(s.get("title", "")[:40])
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
        # /chat without args - inform that chat works automatically
        await update.message.reply_text(
            "💬 <b>Chat działa automatycznie!</b>\n\n"
            "Po prostu pisz wiadomości - odpowiem z dostępem do bazy wiedzy i internetu.\n\n"
            "Możesz też użyć <code>/ask pytanie</code> dla szybkiego wyszukiwania RAG.",
            parse_mode="HTML",
        )


@authorized_only
async def endchat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /endchat command - end current session, start fresh."""
    if not update.message:
        return

    chat_id = update.effective_chat.id
    old_session_id = context.user_data.pop("active_chat_session", None) if context.user_data else None

    try:
        async for session in get_session():
            chat_repo = ChatRepository(session)

            # End old session if exists
            if old_session_id:
                await chat_repo.end_session(UUID(old_session_id))

            # Create new session
            chat_session = await chat_repo.create_session(
                source="telegram", telegram_chat_id=chat_id,
            )
            await session.commit()

            if context.user_data is None:
                context.user_data = {}
            context.user_data["active_chat_session"] = str(chat_session.id)

        await update.message.reply_text(
            "✅ <b>Nowa rozmowa rozpoczęta!</b>\n\n"
            "Poprzednia sesja zapisana w historii.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to reset chat session: {e}")
        await update.message.reply_text(f"❌ Błąd: {e}")


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

            # Try agent action first (create_note, bookmark, summarize, list)
            agent_executed, agent_result = await _try_agent_action(message, session)

            if agent_executed and agent_result:
                # Save user message
                await chat_repo.add_message(
                    session_id=chat_session.id, role="user", content=message,
                )
                # Save agent response
                await chat_repo.add_message(
                    session_id=chat_session.id,
                    role="assistant",
                    content=agent_result,
                    search_type="agent",
                )
                await session.commit()

                # Format and send response
                parts = [escape_html(agent_result)]
                parts.append("\n<i>🤖 Agent</i>")

                try:
                    await status_msg.edit_text("\n".join(parts), parse_mode="HTML")
                except Exception:
                    await status_msg.edit_text(agent_result[:4096])
                return

            # Fall through to orchestrator for search/conversation
            # Save user message
            await chat_repo.add_message(
                session_id=chat_session.id, role="user", content=message,
            )
            await session.commit()

            # Process with orchestrator
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
        parts = [escape_html(response.answer)]

        if response.sources:
            parts.append("\n---")
            for s in response.sources[:3]:
                emoji = "📚" if s.get("type") == "rag" else "🌐"
                title = escape_html(s.get("title", "")[:40])
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
