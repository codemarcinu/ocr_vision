"""Telegram /chat and /endchat handlers for multi-turn conversations."""

import logging
from typing import Optional
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


async def _try_agent_action(
    message: str,
    db_session,
    session_id: Optional[UUID] = None,
    telegram_user_id: Optional[int] = None,
):
    """Try to execute message as agent action.

    Args:
        message: User message
        db_session: Database session
        session_id: Chat session ID for conversation context
        telegram_user_id: Telegram user ID for profile personalization

    Returns:
        AgentExecutionResult or None if agent not applicable
    """
    from app.chat.agent_executor import AgentExecutionResult

    if not settings.CHAT_AGENT_ENABLED:
        return None

    # Heuristic pre-filter: skip agent if message doesn't look like an action
    # This avoids model switching for regular questions
    if not _looks_like_action(message):
        return None

    try:
        from app.chat.agent_executor import process_with_agent
        from app.db.repositories.chat import ChatRepository
        from app.db.repositories.user_profile import UserProfileRepository

        # Get conversation history for context
        conversation_history = None
        if session_id:
            chat_repo = ChatRepository(db_session)
            recent_msgs = await chat_repo.get_recent_messages(session_id, limit=6)
            if recent_msgs:
                conversation_history = [
                    {"role": msg.role, "content": msg.content}
                    for msg in recent_msgs
                ]

        # Get user profile for personalization
        user_profile = None
        if telegram_user_id:
            profile_repo = UserProfileRepository(db_session)
            profile = await profile_repo.get_by_telegram_id(telegram_user_id)
            if profile:
                user_profile = {
                    "default_city": profile.default_city,
                    "timezone": profile.timezone,
                    "favorite_stores": profile.favorite_stores,
                }

        result = await process_with_agent(message, db_session, conversation_history, user_profile)

        if result.executed:
            return result
        elif result.error:
            logger.warning(f"Agent error (falling back to chat): {result.error}")

        return None
    except Exception as e:
        logger.warning(f"Agent processing failed: {e}")
        return None


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
                user_id = update.effective_user.id if update.effective_user else None
                agent_result = await _try_agent_action(
                    question, session, session_id=chat_session.id, telegram_user_id=user_id
                )

                if agent_result and agent_result.executed and agent_result.result_text:
                    # Save user message
                    await chat_repo.add_message(
                        session_id=chat_session.id, role="user", content=question,
                    )
                    # Save agent response with TOOL_RESULT format for context
                    # This allows agent to use result in follow-up messages
                    history_content = (
                        agent_result.history_entry["content"]
                        if agent_result.history_entry
                        else agent_result.result_text
                    )
                    await chat_repo.add_message(
                        session_id=chat_session.id,
                        role="assistant",
                        content=history_content,
                        search_type="agent",
                    )

                    # Auto-generate title
                    if not chat_session.title:
                        await chat_repo.generate_title(chat_session.id)

                    await session.commit()

                    # Format and send response (show clean result to user)
                    parts = [escape_html(agent_result.result_text)]
                    parts.append("\n<i>🤖 Agent</i>")

                    try:
                        await status_msg.edit_text("\n".join(parts), parse_mode="HTML")
                    except Exception:
                        await status_msg.edit_text(agent_result.result_text[:4096])
                    return

                # Fall through to orchestrator (with agent hint if available)
                # Save user message
                await chat_repo.add_message(
                    session_id=chat_session.id, role="user", content=question,
                )
                await session.commit()

                # Process with orchestrator - pass agent hint to skip IntentClassifier
                response = await orchestrator.process_message(
                    message=question,
                    session_id=chat_session.id,
                    db_session=session,
                    agent_search_strategy=agent_result.search_strategy if agent_result else None,
                    agent_search_query=agent_result.search_query if agent_result else None,
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
            user_id = update.effective_user.id if update.effective_user else None
            agent_result = await _try_agent_action(
                message, session, session_id=chat_session.id, telegram_user_id=user_id
            )

            if agent_result and agent_result.executed and agent_result.result_text:
                # Save user message
                await chat_repo.add_message(
                    session_id=chat_session.id, role="user", content=message,
                )
                # Save agent response with TOOL_RESULT format for context
                # This allows agent to use result in follow-up messages
                history_content = (
                    agent_result.history_entry["content"]
                    if agent_result.history_entry
                    else agent_result.result_text
                )
                await chat_repo.add_message(
                    session_id=chat_session.id,
                    role="assistant",
                    content=history_content,
                    search_type="agent",
                )
                await session.commit()

                # Format and send response (show clean result to user)
                parts = [escape_html(agent_result.result_text)]
                parts.append("\n<i>🤖 Agent</i>")

                try:
                    await status_msg.edit_text("\n".join(parts), parse_mode="HTML")
                except Exception:
                    await status_msg.edit_text(agent_result.result_text[:4096])
                return

            # Fall through to orchestrator for search/conversation (with agent hint)
            # Save user message
            await chat_repo.add_message(
                session_id=chat_session.id, role="user", content=message,
            )
            await session.commit()

            # Process with orchestrator - pass agent hint to skip IntentClassifier
            response = await orchestrator.process_message(
                message=message,
                session_id=chat_session.id,
                db_session=session,
                agent_search_strategy=agent_result.search_strategy if agent_result else None,
                agent_search_query=agent_result.search_query if agent_result else None,
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
