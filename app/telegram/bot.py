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
from app.feedback_logger import log_review_correction
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
from app.telegram.handlers.menu_chat import handle_chat_callback
from app.telegram.handlers.menu_bookmarks import handle_bookmarks_callback
from app.telegram.handlers.settings import handle_settings_callback
from app.telegram.handlers.menu_notes import handle_note_text_input, handle_notes_callback
from app.telegram.handlers.menu_receipts import handle_receipts_callback
from app.telegram.handlers.menu_stats import handle_stats_callback
from app.telegram.handlers.menu_transcriptions import handle_transcriptions_callback
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

        # Register handlers
        self._register_handlers()

        # Start polling
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True)

        # Start notification scheduler
        start_scheduler(self.application.bot)

        self._running = True
        logger.info("Telegram bot started successfully")

    async def stop(self) -> None:
        """Stop the bot."""
        if not self._running or not self.application:
            return

        logger.info("Stopping Telegram bot...")

        # Stop notification scheduler
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
            reply_markup=get_main_keyboard()
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

        # Simple search across modules - search pantry products
        from app.telegram.formatters import escape_html, format_search_results
        from app.obsidian_writer import get_pantry_contents

        results = []

        # Search pantry
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

        # Search articles if DB is available
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

                await update.message.reply_text(
                    f"✅ <b>Notatka zapisana!</b>\n\n"
                    f"📌 {escape_html(note_text)}\n"
                    f"<code>ID: {str(note.id)[:8]}</code>",
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.error(f"Error saving quick note: {e}")
            await update.message.reply_text(f"❌ Błąd zapisu notatki: {e}")

    @authorized_only
    async def _handle_audio_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle audio file uploads - route to transcription."""
        if not update.message:
            return

        if not settings.TRANSCRIPTION_ENABLED:
            await update.message.reply_text("❌ Transkrypcja jest wyłączona")
            return

        # Delegate to transcribe handler
        from app.telegram.handlers.transcription import _transcribe_file
        await _transcribe_file(update)

    @authorized_only
    async def _handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text input: JSON import, manual total, URL detection."""
        if not update.message or not update.message.text:
            return

        text = update.message.text.strip()

        # 1. Check for JSON receipt import
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

        # 2. Check if we're awaiting manual total input
        if context.user_data and "awaiting_manual_total" in context.user_data:
            await self._handle_manual_total(update, context)
            return

        # 2.5. Check for active chat session
        if context.user_data and context.user_data.get("active_chat_session"):
            await handle_chat_message(update, context)
            return

        # 3. Check for URL - show action picker
        if _URL_PATTERN.match(text):
            url = text
            url_key = hashlib.md5(url.encode()).hexdigest()[:8]

            # Store URL in user_data for later retrieval
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

        # 4. Check for note creation flow (title or content)
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

    async def _handle_manual_total(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle manual total entry for receipt review."""
        receipt_id = context.user_data.get("awaiting_manual_total")
        if not receipt_id:
            return

        pending_key = f"pending_review_{receipt_id}"
        review_data = context.user_data.get(pending_key)

        if not review_data:
            del context.user_data["awaiting_manual_total"]
            await update.message.reply_text("Dane paragonu wygasły. Prześlij paragon ponownie.")
            return

        # Parse the manual total
        text = update.message.text.strip().replace(",", ".")
        try:
            manual_total = float(text)
            if manual_total <= 0 or manual_total > 10000:
                raise ValueError("Invalid amount")
        except ValueError:
            await update.message.reply_text(
                f"❌ <b>Nieprawidłowa kwota:</b> <code>{text}</code>\n\n"
                "Wpisz liczbę, np. <code>144.48</code> lub <code>144,48</code>",
                parse_mode="HTML"
            )
            return

        # Update receipt with manual total
        receipt = review_data["receipt"]
        original_total = receipt.suma
        receipt.suma = manual_total
        receipt.needs_review = False
        receipt.review_reasons = []

        # Log the manual correction for learning
        log_review_correction(
            receipt_id=receipt_id,
            original_total=original_total,
            corrected_total=manual_total,
            correction_type="manual",
            store=receipt.sklep,
            product_count=len(receipt.products)
        )

        # Save the receipt to database
        from app.services.receipt_saver import save_receipt_to_db
        import shutil
        from pathlib import Path

        categorized = review_data["categorized"]
        filename = review_data["filename"]

        try:
            db_receipt_id = await save_receipt_to_db(receipt, categorized, filename)
            if not db_receipt_id:
                raise Exception("Failed to save receipt to database")

            # Move file to processed
            inbox_path = Path(review_data.get("inbox_path", settings.INBOX_DIR / filename))
            if inbox_path.exists():
                processed_path = settings.PROCESSED_DIR / filename
                shutil.move(inbox_path, processed_path)

            # Clear pending data
            del context.user_data[pending_key]
            del context.user_data["awaiting_manual_total"]

            from app.telegram.formatters import get_store_emoji
            store = receipt.sklep or "nieznany"
            emoji = get_store_emoji(store)

            await update.message.reply_text(
                f"✅ <b>Paragon zapisany z ręcznie wprowadzoną sumą!</b>\n\n"
                f"{emoji} <b>{store.upper()}</b>\n"
                f"💰 Suma: <b>{manual_total:.2f} zł</b>\n"
                f"📦 Produktów: {len(categorized)}",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
        except Exception as e:
            logger.error(f"Error saving receipt with manual total: {e}")
            await update.message.reply_text(f"❌ Błąd zapisu: {e}", parse_mode="HTML")

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
                reply_markup=get_main_keyboard()
            )
            return

        # URL action callbacks
        if data.startswith("url:"):
            await query.answer()
            await self._handle_url_action(query, data, context)
            return

        # Review flow callbacks (kept in bot.py due to state complexity)
        if data.startswith("review_"):
            await query.answer()
            await self._handle_review_callback(query, data, context)
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
                reply_markup=get_pantry_quick_actions()
            )
            return

        # Cancel
        if data == "cancel":
            await query.answer()
            await query.edit_message_text("Anulowano.")
            return

        # Try callback router (module handlers)
        handled = await self._callback_router.route(query, context)
        if not handled:
            await query.answer()
            logger.warning(f"Unhandled callback: {data}")

    async def _handle_url_action(
        self,
        query,
        data: str,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle url:action:key callbacks."""
        parts = data.split(":", 2)
        if len(parts) < 3:
            return

        action = parts[1]
        url_key = parts[2]

        # Retrieve stored URL
        url = context.user_data.get(f"url_{url_key}") if context.user_data else None
        if not url:
            await query.edit_message_text("Link wygasł. Wyślij ponownie.")
            return

        if action == "bookmark":
            from app.db.connection import get_session
            from app.db.repositories.bookmarks import BookmarkRepository
            from app.telegram.formatters import escape_html

            try:
                # Try to fetch title from URL
                title = None
                try:
                    from app.web_scraper import scrape_url
                    scraped, _ = await scrape_url(url)
                    if scraped:
                        title = scraped.title
                except Exception:
                    pass

                async for session in get_session():
                    repo = BookmarkRepository(session)

                    # Check duplicate
                    existing = await repo.get_by_url(url)
                    if existing:
                        await query.edit_message_text(
                            f"⚠️ <b>Zakładka już istnieje</b>\n\n"
                            f"📌 {escape_html(existing.title or url[:60])}\n"
                            f"Status: {existing.status}",
                            parse_mode="HTML",
                            reply_markup=get_main_keyboard(),
                        )
                        return

                    bookmark = await repo.create_from_url(
                        url=url,
                        title=title,
                        source="telegram",
                    )
                    await session.commit()

                    display_title = title or url[:60]
                    await query.edit_message_text(
                        f"🔖 <b>Zakładka zapisana!</b>\n\n"
                        f"📌 {escape_html(display_title)}\n"
                        f"<code>ID: {str(bookmark.id)[:8]}</code>",
                        parse_mode="HTML",
                        reply_markup=get_main_keyboard(),
                    )
            except Exception as e:
                logger.error(f"Error saving bookmark: {e}")
                await query.edit_message_text(f"❌ Błąd: {e}")

        elif action == "summarize":
            await query.edit_message_text("📖 Pobieram artykuł...")

            from app.web_scraper import scrape_url
            from app.summarizer import summarize_content
            from app.telegram.formatters import escape_html

            scraped, error = await scrape_url(url)
            if error or not scraped:
                await query.edit_message_text(f"❌ Błąd pobierania: {error}")
                return

            await query.edit_message_text("🤖 Generuję podsumowanie...")

            result, error = await summarize_content(scraped.content)
            if error or not result:
                await query.edit_message_text(f"❌ Błąd podsumowania: {error}")
                return

            summary = result.summary_text
            if len(summary) > 3000:
                summary = summary[:3000] + "..."

            meta_parts = []
            if result.category:
                meta_parts.append(f"📂 {result.category}")
            if result.tags:
                tags_str = " ".join(f"#{t}" for t in result.tags[:5])
                meta_parts.append(tags_str)
            meta_line = " | ".join(meta_parts) if meta_parts else ""

            response = (
                f"📰 <b>{escape_html(scraped.title)}</b>\n\n"
                f"{escape_html(summary)}\n\n"
            )
            if meta_line:
                response += f"{escape_html(meta_line)}\n\n"
            response += (
                f"---\n"
                f"🔗 <a href=\"{url}\">Źródło</a> | "
                f"⏱️ {result.processing_time_sec}s | "
                f"🤖 {result.model_used}"
            )

            try:
                await query.edit_message_text(
                    response, parse_mode="HTML", disable_web_page_preview=True
                )
            except Exception:
                await query.edit_message_text(
                    response.replace("<b>", "").replace("</b>", "")
                    .replace("<a href=\"", "").replace("\">", " ").replace("</a>", "")
                )

            # Save to DB and Obsidian
            if settings.USE_DB_RECEIPTS:
                from app.db.connection import get_session
                from app.db.repositories.rss import ArticleRepository
                from app.summary_writer import write_summary_file

                async for session in get_session():
                    article_repo = ArticleRepository(session)
                    article = await article_repo.create_with_summary(
                        title=scraped.title,
                        url=url,
                        content=scraped.content,
                        summary_text=result.summary_text,
                        model_used=result.model_used,
                        processing_time=result.processing_time_sec,
                        author=scraped.author,
                    )
                    await session.commit()

                    if settings.GENERATE_OBSIDIAN_FILES:
                        write_summary_file(
                            article,
                            result.summary_text,
                            result.model_used,
                            tags=result.tags,
                            category=result.category,
                            entities=result.entities,
                        )
            elif settings.GENERATE_OBSIDIAN_FILES:
                from app.summary_writer import write_summary_file_simple

                write_summary_file_simple(
                    title=scraped.title,
                    url=url,
                    summary_text=result.summary_text,
                    model_used=result.model_used,
                    author=scraped.author,
                    tags=result.tags,
                    category=result.category,
                    entities=result.entities,
                )

        elif action == "transcribe":
            if not settings.TRANSCRIPTION_ENABLED:
                await query.edit_message_text("❌ Transkrypcja jest wyłączona")
                return

            await query.edit_message_text("🎙️ Rozpoczynam transkrypcję...")

            from app.telegram.handlers.transcription import _transcribe_url

            # Create a fake update with a message to pass to _transcribe_url
            # We need to use the original message context
            class _FakeUpdate:
                def __init__(self, message):
                    self.message = message

            # Send a new message since we can't use edit for long processes
            msg = await query.message.reply_text("🔍 Analizuję URL...")
            fake_update = _FakeUpdate(query.message)
            fake_update.message = type("obj", (object,), {"reply_text": msg.edit_text})()

            # Simplified: just create the job directly
            from app.transcription.downloader import is_youtube_url
            from app.db.connection import get_session
            from app.db.repositories.transcription import TranscriptionJobRepository

            source_type = "youtube" if is_youtube_url(url) else "url"

            async for session in get_session():
                repo = TranscriptionJobRepository(session)
                existing = await repo.get_by_url(url)
                if existing and existing.status == "completed":
                    await msg.edit_text(
                        f"✅ <b>Transkrypcja już istnieje!</b>\n\n"
                        f"📄 {url[:60]}",
                        parse_mode="HTML",
                    )
                    return

                job = await repo.create_job(
                    source_type=source_type,
                    source_url=url,
                )
                await session.commit()

                await msg.edit_text(
                    f"✅ <b>Zadanie transkrypcji utworzone</b>\n\n"
                    f"ID: <code>{str(job.id)[:8]}</code>\n"
                    f"Zostanie przetworzone w tle.",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard(),
                )

    async def _handle_review_callback(
        self,
        query,
        data: str,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle receipt review callbacks (human-in-the-loop)."""
        from app.telegram.keyboards import get_total_correction_keyboard

        parts = data.split("_", 2)
        if len(parts) < 3:
            return

        action = parts[1]
        receipt_id = parts[2]

        # Get pending review data from context
        pending_key = f"pending_review_{receipt_id}"
        review_data = context.user_data.get(pending_key) if context.user_data else None

        if not review_data and action not in ["cancel"]:
            await query.edit_message_text(
                "Dane paragonu wygasły. Prześlij paragon ponownie."
            )
            return

        if action == "approve":
            # Save the receipt to database
            from app.services.receipt_saver import save_receipt_to_db
            from app.telegram.formatters import get_store_emoji

            receipt = review_data["receipt"]
            categorized = review_data["categorized"]
            filename = review_data["filename"]

            try:
                db_receipt_id = await save_receipt_to_db(receipt, categorized, filename)
                if not db_receipt_id:
                    raise Exception("Failed to save receipt to database")

                # Log the approval for learning
                log_review_correction(
                    receipt_id=receipt_id,
                    original_total=receipt.suma,
                    corrected_total=receipt.suma or 0,
                    correction_type="approved",
                    store=receipt.sklep,
                    product_count=len(categorized)
                )

                # Move file to processed
                import shutil
                inbox_path = settings.INBOX_DIR / filename
                if inbox_path.exists():
                    processed_path = settings.PROCESSED_DIR / filename
                    shutil.move(inbox_path, processed_path)

                # Clear pending data
                if context.user_data:
                    del context.user_data[pending_key]

                store = receipt.sklep or "nieznany"
                emoji = get_store_emoji(store)
                await query.edit_message_text(
                    f"✅ <b>Paragon zatwierdzony i zapisany!</b>\n\n"
                    f"{emoji} <b>{store.upper()}</b>\n"
                    f"💰 Suma: <b>{receipt.suma:.2f} zł</b>\n"
                    f"📦 Produktów: {len(categorized)}",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard()
                )
            except Exception as e:
                logger.error(f"Error saving approved receipt: {e}")
                await query.edit_message_text(f"❌ Błąd zapisu: {e}", parse_mode="HTML")

        elif action == "edit":
            # Show total correction options
            receipt = review_data["receipt"]
            calculated = receipt.calculated_total or sum(p.cena for p in receipt.products)

            await query.edit_message_text(
                f"<b>✏️ Popraw sumę paragonu</b>\n\n"
                f"💵 Suma OCR: <b>{receipt.suma:.2f} zł</b>\n"
                f"🧮 Suma produktów: <b>{calculated:.2f} zł</b>\n\n"
                f"<i>Wybierz opcję:</i>",
                parse_mode="HTML",
                reply_markup=get_total_correction_keyboard(receipt_id, calculated)
            )

        elif action == "use_calculated":
            # Use calculated total from products
            receipt = review_data["receipt"]
            original_total = receipt.suma
            calculated = receipt.calculated_total or sum(p.cena for p in receipt.products)
            receipt.suma = calculated
            receipt.needs_review = False
            receipt.review_reasons = []

            # Log the correction for learning
            log_review_correction(
                receipt_id=receipt_id,
                original_total=original_total,
                corrected_total=calculated,
                correction_type="calculated",
                store=receipt.sklep,
                product_count=len(receipt.products)
            )

            # Trigger approve flow
            review_data["receipt"] = receipt
            if context.user_data:
                context.user_data[pending_key] = review_data

            # Call approve logic
            await self._handle_review_callback(query, f"review_approve_{receipt_id}", context)

        elif action == "manual":
            # Ask user to type the total
            if context.user_data:
                context.user_data["awaiting_manual_total"] = receipt_id

            await query.edit_message_text(
                "✏️ <b>Wpisz poprawną sumę paragonu</b>\n\n"
                "Przykład: <code>144.48</code>\n\n"
                "<i>Wyślij kwotę jako wiadomość</i>",
                parse_mode="HTML"
            )

        elif action == "reject":
            # Discard the receipt, keep file in inbox
            if context.user_data and pending_key in context.user_data:
                del context.user_data[pending_key]

            await query.edit_message_text(
                "🗑️ <b>Paragon odrzucony.</b>\n\n"
                "Plik pozostaje w inbox.\n"
                "Użyj <code>/reprocess &lt;plik&gt;</code> aby spróbować ponownie.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )

        elif action == "cancel":
            # Cancel editing, go back to review
            from app.telegram.keyboards import get_review_keyboard
            from app.telegram.formatters import format_review_receipt

            if review_data:
                receipt = review_data["receipt"]
                categorized = review_data["categorized"]
                filename = review_data["filename"]

                try:
                    await query.edit_message_text(
                        format_review_receipt(receipt, categorized, filename),
                        parse_mode="HTML",
                        reply_markup=get_review_keyboard(receipt_id)
                    )
                except Exception:
                    await query.edit_message_text(
                        format_review_receipt(receipt, categorized, filename),
                        reply_markup=get_review_keyboard(receipt_id)
                    )
            else:
                await query.edit_message_text("Anulowano.", reply_markup=get_main_keyboard())

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
