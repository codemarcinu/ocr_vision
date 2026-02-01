"""Main Telegram bot for Smart Pantry Tracker."""

import logging

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
from app.telegram.handlers import (
    categories_command,
    clearerrors_command,
    discounts_command,
    errors_command,
    handle_document,
    handle_photo,
    is_json_receipt,
    pantry_command,
    pending_command,
    process_json_import,
    recent_command,
    remove_command,
    reprocess_command,
    search_command,
    stats_command,
    stores_command,
    use_command,
)
from app.telegram.keyboards import get_main_keyboard
from app.telegram.middleware import authorized_only

logger = logging.getLogger(__name__)


class PantryBot:
    """Telegram bot for Smart Pantry Tracker."""

    def __init__(self):
        self.application: Application | None = None
        self._running = False

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

        self._running = True
        logger.info("Telegram bot started successfully")

    async def stop(self) -> None:
        """Stop the bot."""
        if not self._running or not self.application:
            return

        logger.info("Stopping Telegram bot...")

        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()

        self._running = False
        logger.info("Telegram bot stopped")

    def _register_handlers(self) -> None:
        """Register all command and message handlers."""
        if not self.application:
            return

        # Help commands
        self.application.add_handler(CommandHandler("start", self._start_command))
        self.application.add_handler(CommandHandler("help", self._help_command))

        # Receipt handlers
        self.application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        self.application.add_handler(MessageHandler(filters.Document.PDF, handle_document))

        # Manual total input handler (for review flow)
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text_input)
        )
        self.application.add_handler(CommandHandler("recent", recent_command))
        self.application.add_handler(CommandHandler("reprocess", reprocess_command))
        self.application.add_handler(CommandHandler("pending", pending_command))

        # Pantry handlers
        self.application.add_handler(CommandHandler("pantry", pantry_command))
        self.application.add_handler(CommandHandler("use", use_command))
        self.application.add_handler(CommandHandler("remove", remove_command))
        self.application.add_handler(CommandHandler("search", search_command))

        # Stats handlers
        self.application.add_handler(CommandHandler("stats", stats_command))
        self.application.add_handler(CommandHandler("stores", stores_command))
        self.application.add_handler(CommandHandler("categories", categories_command))
        self.application.add_handler(CommandHandler("rabaty", discounts_command))
        self.application.add_handler(CommandHandler("discounts", discounts_command))

        # Error handlers
        self.application.add_handler(CommandHandler("errors", errors_command))
        self.application.add_handler(CommandHandler("clearerrors", clearerrors_command))

        # Callback query handler for inline keyboards
        self.application.add_handler(CallbackQueryHandler(self._handle_callback))

        # Error handler
        self.application.add_error_handler(self._error_handler)

    @authorized_only
    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message:
            return

        await update.message.reply_text(
            "*Smart Pantry Tracker*\n\n"
            "Witaj! Wyślij mi zdjęcie paragonu, a przetworzę je automatycznie.\n\n"
            "Użyj /help aby zobaczyć dostępne komendy.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

    @authorized_only
    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not update.message:
            return

        help_text = """*Dostępne komendy:*

*Paragony:*
• Wyślij zdjęcie - przetwórz paragon
• Wklej JSON - import z Gemini/innego źródła
• `/recent [N]` - ostatnie N paragonów
• `/reprocess <plik>` - ponowne przetwarzanie
• `/pending` - pliki w kolejce

*Spiżarnia:*
• `/pantry [kategoria]` - zawartość spiżarni
• `/use <produkt>` - oznacz jako zużyty
• `/remove <produkt>` - usuń ze spiżarni
• `/search <fraza>` - szukaj produktu

*Statystyki:*
• `/stats [week/month]` - podsumowanie wydatków
• `/stores` - wydatki wg sklepów
• `/categories` - wydatki wg kategorii
• `/rabaty` - raport rabatów i oszczędności

*Błędy:*
• `/errors` - lista błędów OCR
• `/clearerrors` - wyczyść logi błędów"""

        await update.message.reply_text(help_text, parse_mode="Markdown")

    @authorized_only
    async def _handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text input for manual total entry or JSON import."""
        if not update.message or not update.message.text:
            return

        text = update.message.text

        # Check if this is a JSON receipt import
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

        # Check if we're awaiting manual total input
        if not context.user_data or "awaiting_manual_total" not in context.user_data:
            return  # Not in manual input mode, ignore

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
                f"Nieprawidłowa kwota: `{text}`\n\n"
                "Wpisz liczbę, np. `144.48` lub `144,48`",
                parse_mode="Markdown"
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

        # Save the receipt
        from app.obsidian_writer import update_pantry_file, write_receipt_file
        import shutil
        from app.config import settings
        from pathlib import Path

        categorized = review_data["categorized"]
        filename = review_data["filename"]

        try:
            receipt_file = write_receipt_file(receipt, categorized, filename)
            update_pantry_file(categorized, receipt)

            # Move file to processed
            inbox_path = Path(review_data.get("inbox_path", settings.INBOX_DIR / filename))
            if inbox_path.exists():
                processed_path = settings.PROCESSED_DIR / filename
                shutil.move(inbox_path, processed_path)

            # Clear pending data
            del context.user_data[pending_key]
            del context.user_data["awaiting_manual_total"]

            await update.message.reply_text(
                f"Paragon zapisany z ręcznie wprowadzoną sumą.\n\n"
                f"Sklep: {receipt.sklep or 'nieznany'}\n"
                f"Suma: {manual_total:.2f} zł\n"
                f"Produktów: {len(categorized)}"
            )
        except Exception as e:
            logger.error(f"Error saving receipt with manual total: {e}")
            await update.message.reply_text(f"Błąd zapisu: {e}")

    @authorized_only
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle callback queries from inline keyboards."""
        query = update.callback_query
        if not query:
            return

        await query.answer()

        data = query.data or ""

        if data == "pantry":
            from app.obsidian_writer import get_pantry_contents
            from app.telegram.formatters import format_pantry_contents
            contents = get_pantry_contents()
            await query.edit_message_text(
                format_pantry_contents(contents),
                parse_mode="Markdown"
            )

        elif data.startswith("pantry_"):
            category = data.replace("pantry_", "")
            from app.obsidian_writer import get_pantry_contents
            from app.telegram.formatters import format_pantry_contents
            contents = get_pantry_contents()
            cat = None if category == "all" else category
            await query.edit_message_text(
                format_pantry_contents(contents, cat),
                parse_mode="Markdown"
            )

        elif data == "stats":
            from app.telegram.keyboards import get_stats_keyboard
            await query.edit_message_text(
                "Wybierz okres:",
                reply_markup=get_stats_keyboard()
            )

        elif data == "stats_week":
            from app.telegram.handlers.stats import _calculate_stats
            from app.telegram.formatters import format_stats
            stats = _calculate_stats("week")
            await query.edit_message_text(
                format_stats(stats, "week"),
                parse_mode="Markdown"
            )

        elif data == "stats_month":
            from app.telegram.handlers.stats import _calculate_stats
            from app.telegram.formatters import format_stats
            stats = _calculate_stats("month")
            await query.edit_message_text(
                format_stats(stats, "month"),
                parse_mode="Markdown"
            )

        elif data == "stores":
            from app.telegram.handlers.stats import _calculate_stores_stats
            from app.telegram.formatters import format_stores_stats
            stores = _calculate_stores_stats()
            await query.edit_message_text(
                format_stores_stats(stores),
                parse_mode="Markdown"
            )

        elif data == "categories":
            from app.telegram.handlers.stats import _calculate_categories_stats
            from app.telegram.formatters import format_categories_stats
            categories = _calculate_categories_stats()
            await query.edit_message_text(
                format_categories_stats(categories),
                parse_mode="Markdown"
            )

        elif data == "recent":
            from app.telegram.handlers.receipts import _get_recent_receipts
            from app.telegram.formatters import format_receipt_list
            receipts = _get_recent_receipts(5)
            await query.edit_message_text(
                format_receipt_list(receipts),
                parse_mode="Markdown"
            )

        elif data == "errors":
            from app.obsidian_writer import get_errors
            from app.telegram.formatters import format_errors
            errors = get_errors()
            await query.edit_message_text(
                format_errors(errors),
                parse_mode="Markdown"
            )

        elif data == "cancel":
            await query.edit_message_text("Anulowano.")

        # Review flow callbacks
        elif data.startswith("review_"):
            await self._handle_review_callback(query, data, context)

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
            # Save the receipt as-is
            from app.obsidian_writer import update_pantry_file, write_receipt_file

            receipt = review_data["receipt"]
            categorized = review_data["categorized"]
            filename = review_data["filename"]

            try:
                receipt_file = write_receipt_file(receipt, categorized, filename)
                update_pantry_file(categorized, receipt)

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
                from app.config import settings
                inbox_path = settings.INBOX_DIR / filename
                if inbox_path.exists():
                    processed_path = settings.PROCESSED_DIR / filename
                    shutil.move(inbox_path, processed_path)

                # Clear pending data
                if context.user_data:
                    del context.user_data[pending_key]

                await query.edit_message_text(
                    f"Paragon zatwierdzony i zapisany.\n\n"
                    f"Sklep: {receipt.sklep or 'nieznany'}\n"
                    f"Suma: {receipt.suma:.2f} zł\n"
                    f"Produktów: {len(categorized)}"
                )
            except Exception as e:
                logger.error(f"Error saving approved receipt: {e}")
                await query.edit_message_text(f"Błąd zapisu: {e}")

        elif action == "edit":
            # Show total correction options
            receipt = review_data["receipt"]
            calculated = receipt.calculated_total or sum(p.cena for p in receipt.products)

            await query.edit_message_text(
                f"*Popraw sumę paragonu*\n\n"
                f"Suma OCR: {receipt.suma:.2f} zł\n"
                f"Suma produktów: {calculated:.2f} zł\n\n"
                f"Wybierz opcję:",
                parse_mode="Markdown",
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
                "Wpisz poprawną sumę paragonu (np. `144.48`):\n\n"
                "_Wyślij kwotę jako wiadomość_",
                parse_mode="Markdown"
            )

        elif action == "reject":
            # Discard the receipt, keep file in inbox
            if context.user_data and pending_key in context.user_data:
                del context.user_data[pending_key]

            await query.edit_message_text(
                "Paragon odrzucony. Plik pozostaje w inbox.\n"
                "Użyj `/reprocess <plik>` aby spróbować ponownie."
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
                        parse_mode="Markdown",
                        reply_markup=get_review_keyboard(receipt_id)
                    )
                except Exception:
                    await query.edit_message_text(
                        format_review_receipt(receipt, categorized, filename),
                        reply_markup=get_review_keyboard(receipt_id)
                    )
            else:
                await query.edit_message_text("Anulowano.")

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
