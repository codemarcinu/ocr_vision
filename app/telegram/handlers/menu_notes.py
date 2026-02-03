"""Callback handlers for personal notes module menu."""

import logging

from telegram import CallbackQuery
from telegram.ext import ContextTypes

from app.config import settings
from app.telegram.formatters import escape_html
from app.telegram.keyboards import get_main_keyboard, get_notes_menu

logger = logging.getLogger(__name__)


async def handle_notes_callback(
    query: CallbackQuery,
    action: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle notes:* callbacks."""
    if action == "menu":
        await query.edit_message_text(
            "<b>📝 Notatki</b>\n\n"
            "Użyj <code>/n &lt;tekst&gt;</code> aby szybko zapisać notatkę.\n"
            "Wybierz opcję poniżej:",
            parse_mode="HTML",
            reply_markup=get_notes_menu(),
        )

    elif action == "new":
        # Start note creation flow
        if context.user_data is None:
            context.user_data = {}
        context.user_data["awaiting_note_title"] = True

        await query.edit_message_text(
            "✏️ <b>Nowa notatka</b>\n\n"
            "Wyślij tytuł notatki jako wiadomość:",
            parse_mode="HTML",
        )

    elif action == "list":
        if not settings.NOTES_ENABLED:
            await query.edit_message_text(
                "❌ Moduł notatek jest wyłączony",
                reply_markup=get_main_keyboard(),
            )
            return

        from app.db.connection import get_session
        from app.db.repositories.notes import NoteRepository

        async for session in get_session():
            repo = NoteRepository(session)
            notes = await repo.get_recent(limit=10)

            if not notes:
                await query.edit_message_text(
                    "📭 <b>Brak notatek</b>\n\n"
                    "Użyj <code>/n &lt;tekst&gt;</code> aby dodać pierwszą notatkę.",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard(),
                )
                return

            lines = ["📝 <b>Ostatnie notatki:</b>\n"]

            for note in notes:
                date = note.created_at.strftime("%m-%d %H:%M")
                title_short = (
                    note.title[:50] + "..."
                    if len(note.title) > 50
                    else note.title
                )
                tags_str = ""
                if note.tags:
                    tags_str = " " + " ".join(f"#{t}" for t in note.tags[:3])

                lines.append(f"📌 <b>{escape_html(title_short)}</b>{tags_str}")
                lines.append(f"   {date} | <code>{str(note.id)[:8]}</code>")

            await query.edit_message_text(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=get_main_keyboard(),
            )


async def handle_note_text_input(
    text: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> str | None:
    """Handle text input during note creation flow.

    Returns response text if handled, None otherwise.
    """
    if not context.user_data:
        return None

    # Step 1: waiting for title
    if context.user_data.get("awaiting_note_title"):
        context.user_data["awaiting_note_title"] = False
        context.user_data["awaiting_note_content"] = True
        context.user_data["note_title"] = text
        return (
            f"📝 <b>Tytuł:</b> {escape_html(text)}\n\n"
            "Teraz wyślij treść notatki\n"
            "(lub wyślij <code>.</code> aby zapisać tylko z tytułem):"
        )

    # Step 2: waiting for content
    if context.user_data.get("awaiting_note_content"):
        title = context.user_data.pop("note_title", text)
        context.user_data.pop("awaiting_note_content", None)

        content = "" if text == "." else text

        # Save to database
        from app.db.connection import get_session
        from app.db.repositories.notes import NoteRepository

        async for session in get_session():
            repo = NoteRepository(session)
            note = await repo.create_quick(title=title, content=content or title)
            await session.commit()

            # Write to Obsidian
            if settings.GENERATE_OBSIDIAN_FILES:
                from app.notes_writer import write_note_file
                write_note_file(note)

            # RAG indexing
            if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
                try:
                    from app.rag.hooks import index_note_hook
                    await index_note_hook(note, session)
                    await session.commit()
                except Exception:
                    pass

            return (
                f"✅ <b>Notatka zapisana!</b>\n\n"
                f"📌 {escape_html(title)}\n"
                f"<code>ID: {str(note.id)[:8]}</code>"
            )

    return None
