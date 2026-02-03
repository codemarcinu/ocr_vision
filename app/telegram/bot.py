"""Main Telegram bot for Second Brain."""

import hashlib
import logging
import re

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import settings
from app.telegram.callback_router import CallbackRouter
from app.telegram.handlers import (
    ask_command,
    articles_command,
    categories_command,
    clearerrors_command,
    discounts_command,
    errors_command,
    feeds_command,
    handle_document,
    handle_photo,
    is_json_receipt,
    note_command,
    pantry_command,
    pending_command,
    process_json_import,
    recent_command,
    refresh_command,
    remove_command,
    reprocess_command,
    search_command,
    stats_command,
    stores_command,
    subscribe_command,
    summarize_command,
    transcribe_command,
    transcriptions_command,
    unsubscribe_command,
    use_command,
    find_command,
    settings_command,
    chat_command,
    endchat_command,
    handle_chat_message,
)
from app.telegram.handlers.menu_articles import handle_articles_callback
from app.telegram.handlers.menu_bookmarks import handle_bookmarks_callback
from app.telegram.handlers.menu_chat import handle_chat_callback
from app.telegram.handlers.menu_notes import handle_note_text_input, handle_notes_callback
from app.telegram.handlers.menu_receipts import handle_receipts_callback
from app.telegram.handlers.menu_stats import handle_stats_callback
from app.telegram.handlers.menu_transcriptions import handle_transcriptions_callback
from app.telegram.handlers.review import handle_manual_total_input, handle_review_callback
from app.telegram.handlers.settings import handle_settings_callback
from app.telegram.handlers.url_actions import handle_url_callback
from app.telegram.keyboards import get_main_keyboard, get_url_action_keyboard
from app.telegram.middleware import authorized_only
from app.telegram.notifications import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)

# URL detection pattern
_URL_PATTERN = re.compile(r"^https?://\S+$", re.IGNORECASE)


class PantryBot:
    """Telegram bot for Second Brain."""

    def __init__(self):
        self.application: Application | None = None
        self._running = False
        self._callback_router = CallbackRouter()
        self._setup_callback_router()

    def _setup_callback_router(self) -> None:
        """Register module callback handlers."""
        self._callback_router.register("receipts:", handle_receipts_callback)
        self._callback_router.register("articles:", handle_articles_callback)
        self._callback_router.register("transcriptions:", handle_transcriptions_callback)
        self._callback_router.register("stats:", handle_stats_callback)
        self._callback_router.register("notes:", handle_notes_callback)
        self._callback_router.register("bookmarks:", handle_bookmarks_callback)
        self._callback_router.register("settings:", handle_settings_callback)
        self._callback_router.register("chat:", handle_chat_callback)
        self._callback_router.register("url:", handle_url_callback)
        self._callback_router.register("review:", handle_review_callback)

    async def start(self) -> None:
        """Start the bot in polling mode."""
        if not settings.BOT_ENABLED:
            logger.info("Telegram bot is disabled")
            return

        if not settings.TELEGRAM_BOT_TOKEN:
            logger.warning("TELEGRAM_BOT_TOKEN not configured, bot will not start")
            return

        logger.info("Starting Telegram bot...")

        self.application = (
            Application.builder()
            .token(settings.TELEGRAM_BOT_TOKEN)
            .build()
        )

        self._register_handlers()

        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True)

        start_scheduler(self.application.bot)

        self._running = True
        logger.info("Telegram bot started successfully")

    async def stop(self) -> None:
        """Stop the bot."""
        if not self._running or not self.application:
            return

        logger.info("Stopping Telegram bot...")

        stop_scheduler()

        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()

        self._running = False
        logger.info("Telegram bot stopped")

    def _register_handlers(self) -> None:
        """Register all command and message handlers."""
        if not self.application:
            return

        # Primary commands (shown in /help)
        self.application.add_handler(CommandHandler("start", self._start_command))
        self.application.add_handler(CommandHandler("help", self._help_command))
        self.application.add_handler(CommandHandler("ask", ask_command))
        self.application.add_handler(CommandHandler("find", find_command))
        self.application.add_handler(CommandHandler("settings", settings_command))
        self.application.add_handler(CommandHandler("chat", chat_command))
        self.application.add_handler(CommandHandler("endchat", endchat_command))
        self.application.add_handler(CommandHandler("q", self._quick_search_command))
        self.application.add_handler(CommandHandler("n", self._quick_note_command))

        # Media handlers
        self.application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        self.application.add_handler(MessageHandler(filters.Document.PDF, handle_document))
        self.application.add_handler(MessageHandler(
            filters.Document.MimeType("audio/mpeg")
            | filters.Document.MimeType("audio/mp4")
            | filters.Document.MimeType("audio/ogg")
            | filters.Document.MimeType("audio/wav")
            | filters.Document.MimeType("audio/webm")
            | filters.Document.MimeType("video/mp4")
            | filters.AUDIO
            | filters.VOICE,
            self._handle_audio_input,
        ))

        # Text input handler (JSON import, manual total, URL detection)
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text_input)
        )

        # Legacy commands (still work, not shown in /help)
        self.application.add_handler(CommandHandler("recent", recent_command))
        self.application.add_handler(CommandHandler("reprocess", reprocess_command))
        self.application.add_handler(CommandHandler("pending", pending_command))
        self.application.add_handler(CommandHandler("pantry", pantry_command))
        self.application.add_handler(CommandHandler("use", use_command))
        self.application.add_handler(CommandHandler("remove", remove_command))
        self.application.add_handler(CommandHandler("search", search_command))
        self.application.add_handler(CommandHandler("stats", stats_command))
        self.application.add_handler(CommandHandler("stores", stores_command))
        self.application.add_handler(CommandHandler("categories", categories_command))
        self.application.add_handler(CommandHandler("rabaty", discounts_command))
        self.application.add_handler(CommandHandler("discounts", discounts_command))
        self.application.add_handler(CommandHandler("errors", errors_command))
        self.application.add_handler(CommandHandler("clearerrors", clearerrors_command))
        self.application.add_handler(CommandHandler("feeds", feeds_command))
        self.application.add_handler(CommandHandler("subscribe", subscribe_command))
        self.application.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
        self.application.add_handler(CommandHandler("summarize", summarize_command))
        self.application.add_handler(CommandHandler("refresh", refresh_command))
        self.application.add_handler(CommandHandler("articles", articles_command))
        self.application.add_handler(CommandHandler("transcribe", transcribe_command))
        self.application.add_handler(CommandHandler("transcriptions", transcriptions_command))
        self.application.add_handler(CommandHandler("note", note_command))

        # Callback query handler (routes via CallbackRouter)
        self.application.add_handler(CallbackQueryHandler(self._handle_callback))

        # Error handler
        self.application.add_error_handler(self._error_handler)

    # ── Command handlers ─────────────────────────────────────

    @authorized_only
    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command - show main menu."""
        if not update.message:
            return

        await update.message.reply_text(
            "<b>🧠 Second Brain</b>\n\n"
            "Wybierz moduł lub wyślij:\n"
            "• 📸 zdjęcie paragonu\n"
            "• 🔗 link do artykułu/wideo\n"
            "• 🎵 plik audio\n",
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )

    @authorized_only
    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command - show available commands."""
        if not update.message:
            return

        help_text = (
            "<b>🧠 Second Brain</b>\n\n"
            "<b>Komendy:</b>\n"
            "• <code>/start</code> — menu główne\n"
            "• <code>/ask &lt;pytanie&gt;</code> — zapytaj bazę wiedzy (RAG)\n"
            "• <code>/n &lt;tekst&gt;</code> — szybka notatka\n"
            "• <code>/q &lt;fraza&gt;</code> — szukaj wszędzie\n"
            "• <code>/find &lt;fraza&gt;</code> — szukaj w bazie\n"
            "• <code>/settings</code> — ustawienia powiadomień\n"
            "• <code>/help</code> — ta pomoc\n\n"
            "<b>Wyślij wiadomość:</b>\n"
            "• 📸 Zdjęcie → przetwarzanie paragonu\n"
            "• 📄 PDF → przetwarzanie paragonu\n"
            "• 🎵 Audio → transkrypcja\n"
            "• 🔗 Link → wybór akcji (zapisz / podsumuj / transkrybuj)\n"
            "• 📋 JSON → import paragonu\n\n"
            "<b>Nawigacja:</b>\n"
            "Użyj przycisków w menu do nawigacji między modułami."
        )

        await update.message.reply_text(
            help_text,
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )

    @authorized_only
    async def _quick_search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /q command - quick cross-module search."""
        if not update.message:
            return

        if not context.args:
            await update.message.reply_text(
                "Użycie: <code>/q &lt;fraza&gt;</code>\n\n"
                "Przykład: <code>/q mleko</code>",
                parse_mode="HTML",
            )
            return

        query = " ".join(context.args)

        from app.telegram.formatters import escape_html, format_search_results
        from app.obsidian_writer import get_pantry_contents

        results = []

        contents = get_pantry_contents()
        for category, items in (contents or {}).items():
            for item in items:
                name = item.get("name", "")
                if query.lower() in name.lower():
                    results.append({
                        "name": name,
                        "price": item.get("price", "?"),
                        "category": category,
                        "date": item.get("date", ""),
                        "checked": item.get("checked", False),
                    })

        text = format_search_results(results, query)

        if settings.USE_DB_RECEIPTS:
            try:
                from app.db.connection import get_session
                from app.db.repositories.rss import ArticleRepository

                async for session in get_session():
                    repo = ArticleRepository(session)
                    articles = await repo.get_recent(limit=50)
                    matching = [
                        a for a in articles
                        if query.lower() in (a.title or "").lower()
                    ]
                    if matching:
                        text += f"\n\n📰 <b>Artykuły ({len(matching)}):</b>\n"
                        for a in matching[:5]:
                            title_short = a.title[:50] + "..." if len(a.title) > 50 else a.title
                            text += f"  • {escape_html(title_short)}\n"
            except Exception:
                pass

        await update.message.reply_text(text, parse_mode="HTML")

    @authorized_only
    async def _quick_note_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /n command - quick note capture."""
        if not update.message:
            return

        if not context.args:
            await update.message.reply_text(
                "Użycie: <code>/n &lt;tekst notatki&gt;</code>\n\n"
                "Przykład: <code>/n kupić mleko</code>",
                parse_mode="HTML",
            )
            return

        note_text = " ".join(context.args)

        from app.db.connection import get_session
        from app.db.repositories.notes import NoteRepository
        from app.telegram.formatters import escape_html

        try:
            async for session in get_session():
                repo = NoteRepository(session)
                note = await repo.create_quick(title=note_text)
                await session.commit()

                if settings.GENERATE_OBSIDIAN_FILES:
                    from app.notes_writer import write_note_file
                    write_note_file(note)

                if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
                    try:
                        from app.rag.hooks import index_note_hook
                        await index_note_hook(note, session)
                        await session.commit()
                    except Exception:
                        pass

                await update.message.reply_text(
                    f"✅ <b>Notatka zapisana!</b>\n\n"
                    f"📌 {escape_html(note_text)}\n"
                    f"<code>ID: {str(note.id)[:8]}</code>",
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.error(f"Error saving quick note: {e}")
            await update.message.reply_text(f"❌ Błąd zapisu notatki: {e}")

    # ── Message handlers ─────────────────────────────────────

    @authorized_only
    async def _handle_audio_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle audio file uploads - route to transcription."""
        if not update.message:
            return

        if not settings.TRANSCRIPTION_ENABLED:
            await update.message.reply_text("❌ Transkrypcja jest wyłączona")
            return

        from app.telegram.handlers.transcription import _transcribe_file
        await _transcribe_file(update)

    @authorized_only
    async def _handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text input: JSON import, manual total, chat, URL, notes."""
        if not update.message or not update.message.text:
            return

        text = update.message.text.strip()

        # 1. JSON receipt import
        if is_json_receipt(text):
            status_msg = await update.message.reply_text(
                "Wykryto JSON paragonu. Przetwarzam..."
            )
            success, message, filename = await process_json_import(text)
            if success:
                try:
                    await status_msg.edit_text(message, parse_mode="Markdown")
                except Exception:
                    await status_msg.edit_text(message)
            else:
                await status_msg.edit_text(f"Błąd importu: {message}")
            return

        # 2. Manual total input (receipt review flow)
        if context.user_data and "awaiting_manual_total" in context.user_data:
            await handle_manual_total_input(update, context)
            return

        # 3. Active chat session
        if context.user_data and context.user_data.get("active_chat_session"):
            await handle_chat_message(update, context)
            return

        # 4. URL - show action picker
        if _URL_PATTERN.match(text):
            url = text
            url_key = hashlib.md5(url.encode()).hexdigest()[:8]

            if context.user_data is None:
                context.user_data = {}
            context.user_data[f"url_{url_key}"] = url

            await update.message.reply_text(
                f"🔗 <b>Co zrobić z linkiem?</b>\n\n"
                f"<code>{url[:80]}{'...' if len(url) > 80 else ''}</code>",
                parse_mode="HTML",
                reply_markup=get_url_action_keyboard(url_key),
            )
            return

        # 5. Note creation flow (title or content)
        if context.user_data and (
            context.user_data.get("awaiting_note_title")
            or context.user_data.get("awaiting_note_content")
        ):
            response = await handle_note_text_input(text, context)
            if response:
                await update.message.reply_text(
                    response,
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard() if "zapisana" in response else None,
                )
                return

    # ── Callback query handler ───────────────────────────────

    @authorized_only
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle callback queries from inline keyboards."""
        query = update.callback_query
        if not query:
            return

        data = query.data or ""

        # Main menu
        if data == "main_menu":
            await query.answer()
            await query.edit_message_text(
                "<b>🧠 Second Brain</b>\n\n"
                "Wybierz moduł:",
                parse_mode="HTML",
                reply_markup=get_main_keyboard(),
            )
            return

        # Legacy pantry callbacks
        if data == "pantry" or data.startswith("pantry_"):
            await query.answer()
            from app.obsidian_writer import get_pantry_contents
            from app.telegram.formatters import format_pantry_contents
            from app.telegram.keyboards import get_pantry_quick_actions

            contents = get_pantry_contents()
            if data == "pantry":
                cat = None
            else:
                category = data.replace("pantry_", "")
                cat = None if category == "all" else category

            await query.edit_message_text(
                format_pantry_contents(contents, cat),
                parse_mode="HTML",
                reply_markup=get_pantry_quick_actions(),
            )
            return

        # Cancel
        if data == "cancel":
            await query.answer()
            await query.edit_message_text("Anulowano.")
            return

        # Try callback router (module handlers: receipts, articles, stats, etc.)
        handled = await self._callback_router.route(query, context)
        if not handled:
            await query.answer()
            logger.warning(f"Unhandled callback: {data}")

    # ── Error handler ────────────────────────────────────────

    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors in the bot."""
        logger.error(f"Bot error: {context.error}", exc_info=context.error)

        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "Wystąpił błąd podczas przetwarzania. Spróbuj ponownie."
                )
            except Exception:
                pass


# Global bot instance
bot = PantryBot()
