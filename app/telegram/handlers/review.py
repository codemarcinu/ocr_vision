"""Callback handlers for receipt review (human-in-the-loop)."""

import logging
import shutil
from pathlib import Path

from telegram import CallbackQuery, Update
from telegram.ext import ContextTypes

from app.config import settings
from app.feedback_logger import log_review_correction
from app.telegram.formatters import (
    escape_html,
    format_review_receipt,
    get_store_emoji,
)
from app.telegram.keyboards import (
    get_main_keyboard,
    get_review_keyboard,
    get_total_correction_keyboard,
)

logger = logging.getLogger(__name__)


async def handle_review_callback(
    query: CallbackQuery,
    action: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle review:* callbacks.

    Action format: "verb:receipt_id" (e.g., "approve:abc123").
    """
    parts = action.split(":", 1)
    if len(parts) < 2:
        return

    verb, receipt_id = parts

    pending_key = f"pending_review_{receipt_id}"
    review_data = context.user_data.get(pending_key) if context.user_data else None

    if not review_data and verb != "cancel":
        await query.edit_message_text(
            "Dane paragonu wygasły. Prześlij paragon ponownie."
        )
        return

    if verb == "approve":
        await _approve_receipt(query, context, review_data, receipt_id, pending_key)
    elif verb == "edit":
        await _show_total_correction(query, review_data, receipt_id)
    elif verb == "use_calculated":
        await _use_calculated_total(query, context, review_data, receipt_id, pending_key)
    elif verb == "manual":
        await _request_manual_total(query, context, receipt_id)
    elif verb == "reject":
        await _reject_receipt(query, context, pending_key)
    elif verb == "cancel":
        await _cancel_edit(query, review_data, receipt_id)


async def handle_manual_total_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle text input for manual receipt total entry."""
    receipt_id = context.user_data.get("awaiting_manual_total")
    if not receipt_id:
        return

    pending_key = f"pending_review_{receipt_id}"
    review_data = context.user_data.get(pending_key)

    if not review_data:
        del context.user_data["awaiting_manual_total"]
        await update.message.reply_text("Dane paragonu wygasły. Prześlij paragon ponownie.")
        return

    text = update.message.text.strip().replace(",", ".")
    try:
        manual_total = float(text)
        if manual_total <= 0 or manual_total > 10000:
            raise ValueError("Invalid amount")
    except ValueError:
        await update.message.reply_text(
            f"❌ <b>Nieprawidłowa kwota:</b> <code>{text}</code>\n\n"
            "Wpisz liczbę, np. <code>144.48</code> lub <code>144,48</code>",
            parse_mode="HTML",
        )
        return

    receipt = review_data["receipt"]
    original_total = receipt.suma
    receipt.suma = manual_total
    receipt.needs_review = False
    receipt.review_reasons = []

    log_review_correction(
        receipt_id=receipt_id,
        original_total=original_total,
        corrected_total=manual_total,
        correction_type="manual",
        store=receipt.sklep,
        product_count=len(receipt.products),
    )

    categorized = review_data["categorized"]
    filename = review_data["filename"]

    try:
        from app.services.receipt_saver import save_receipt_to_db, write_receipt_to_obsidian, index_receipt_in_rag

        db_receipt_id = await save_receipt_to_db(receipt, categorized, filename)
        if not db_receipt_id:
            raise Exception("Failed to save receipt to database")

        # Write Obsidian markdown + RAG indexing
        write_receipt_to_obsidian(receipt, categorized, filename)
        await index_receipt_in_rag(db_receipt_id)

        # Push notification
        try:
            from app.push.hooks import push_receipt_processed
            await push_receipt_processed(
                store_name=receipt.sklep,
                total=float(receipt.suma) if receipt.suma else None,
                item_count=len(categorized),
                receipt_id=str(db_receipt_id) if db_receipt_id else None,
            )
        except Exception:
            pass

        inbox_path = Path(review_data.get("inbox_path", settings.INBOX_DIR / filename))
        if inbox_path.exists():
            shutil.move(inbox_path, settings.PROCESSED_DIR / filename)

        del context.user_data[pending_key]
        del context.user_data["awaiting_manual_total"]

        store = receipt.sklep or "nieznany"
        emoji = get_store_emoji(store)

        await update.message.reply_text(
            f"✅ <b>Paragon zapisany z ręcznie wprowadzoną sumą!</b>\n\n"
            f"{emoji} <b>{store.upper()}</b>\n"
            f"💰 Suma: <b>{manual_total:.2f} zł</b>\n"
            f"📦 Produktów: {len(categorized)}",
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )
    except Exception as e:
        logger.error(f"Error saving receipt with manual total: {e}")
        await update.message.reply_text(f"❌ Błąd zapisu: {e}", parse_mode="HTML")


# ── Private helpers ──────────────────────────────────────────


async def _approve_receipt(query, context, review_data, receipt_id, pending_key):
    """Save approved receipt to database."""
    from app.services.receipt_saver import save_receipt_to_db, write_receipt_to_obsidian, index_receipt_in_rag

    receipt = review_data["receipt"]
    categorized = review_data["categorized"]
    filename = review_data["filename"]

    try:
        db_receipt_id = await save_receipt_to_db(receipt, categorized, filename)
        if not db_receipt_id:
            raise Exception("Failed to save receipt to database")

        # Write Obsidian markdown + RAG indexing
        write_receipt_to_obsidian(receipt, categorized, filename)
        await index_receipt_in_rag(db_receipt_id)

        # Push notification
        try:
            from app.push.hooks import push_receipt_processed
            await push_receipt_processed(
                store_name=receipt.sklep,
                total=float(receipt.suma) if receipt.suma else None,
                item_count=len(categorized),
                receipt_id=str(db_receipt_id) if db_receipt_id else None,
            )
        except Exception:
            pass

        log_review_correction(
            receipt_id=receipt_id,
            original_total=receipt.suma,
            corrected_total=receipt.suma or 0,
            correction_type="approved",
            store=receipt.sklep,
            product_count=len(categorized),
        )

        inbox_path = settings.INBOX_DIR / filename
        if inbox_path.exists():
            shutil.move(inbox_path, settings.PROCESSED_DIR / filename)

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
            reply_markup=get_main_keyboard(),
        )
    except Exception as e:
        logger.error(f"Error saving approved receipt: {e}")
        await query.edit_message_text(f"❌ Błąd zapisu: {e}", parse_mode="HTML")


async def _show_total_correction(query, review_data, receipt_id):
    """Show total correction options."""
    receipt = review_data["receipt"]
    calculated = receipt.calculated_total or sum(p.cena for p in receipt.products)

    await query.edit_message_text(
        f"<b>✏️ Popraw sumę paragonu</b>\n\n"
        f"💵 Suma OCR: <b>{receipt.suma:.2f} zł</b>\n"
        f"🧮 Suma produktów: <b>{calculated:.2f} zł</b>\n\n"
        f"<i>Wybierz opcję:</i>",
        parse_mode="HTML",
        reply_markup=get_total_correction_keyboard(receipt_id, calculated),
    )


async def _use_calculated_total(query, context, review_data, receipt_id, pending_key):
    """Use calculated total from products, then approve."""
    receipt = review_data["receipt"]
    original_total = receipt.suma
    calculated = receipt.calculated_total or sum(p.cena for p in receipt.products)
    receipt.suma = calculated
    receipt.needs_review = False
    receipt.review_reasons = []

    log_review_correction(
        receipt_id=receipt_id,
        original_total=original_total,
        corrected_total=calculated,
        correction_type="calculated",
        store=receipt.sklep,
        product_count=len(receipt.products),
    )

    review_data["receipt"] = receipt
    if context.user_data:
        context.user_data[pending_key] = review_data

    # Delegate to approve
    await _approve_receipt(query, context, review_data, receipt_id, pending_key)


async def _request_manual_total(query, context, receipt_id):
    """Ask user to type the total."""
    if context.user_data:
        context.user_data["awaiting_manual_total"] = receipt_id

    await query.edit_message_text(
        "✏️ <b>Wpisz poprawną sumę paragonu</b>\n\n"
        "Przykład: <code>144.48</code>\n\n"
        "<i>Wyślij kwotę jako wiadomość</i>",
        parse_mode="HTML",
    )


async def _reject_receipt(query, context, pending_key):
    """Discard the receipt, keep file in inbox."""
    if context.user_data and pending_key in context.user_data:
        del context.user_data[pending_key]

    await query.edit_message_text(
        "🗑️ <b>Paragon odrzucony.</b>\n\n"
        "Plik pozostaje w inbox.\n"
        "Użyj <code>/reprocess &lt;plik&gt;</code> aby spróbować ponownie.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard(),
    )


async def _cancel_edit(query, review_data, receipt_id):
    """Cancel editing, go back to review."""
    if review_data:
        receipt = review_data["receipt"]
        categorized = review_data["categorized"]
        filename = review_data["filename"]

        try:
            await query.edit_message_text(
                format_review_receipt(receipt, categorized, filename),
                parse_mode="HTML",
                reply_markup=get_review_keyboard(receipt_id),
            )
        except Exception:
            await query.edit_message_text(
                format_review_receipt(receipt, categorized, filename),
                reply_markup=get_review_keyboard(receipt_id),
            )
    else:
        await query.edit_message_text("Anulowano.", reply_markup=get_main_keyboard())
