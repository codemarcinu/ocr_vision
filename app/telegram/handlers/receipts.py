"""Receipt handling for Telegram bot."""

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from app.classifier import categorize_products
from app.config import settings
from app.models import CategorizedProduct, Receipt
from app.obsidian_writer import log_error, update_pantry_file, write_error_file, write_receipt_file
from app.ocr import extract_products_from_image as extract_vision, unload_model
from app.pdf_converter import convert_pdf_to_images
from app.telegram.formatters import format_pending_files, format_receipt_list, format_receipt_summary, format_review_receipt
from app.telegram.keyboards import get_review_keyboard
from app.telegram.middleware import authorized_only

# Import PaddleOCR if configured
if settings.OCR_BACKEND == "paddle":
    from app.paddle_ocr import extract_products_paddle, extract_total_from_text


async def extract_products_from_image(image_path):
    """Use configured OCR backend."""
    if settings.OCR_BACKEND == "paddle":
        return await extract_products_paddle(image_path)
    return await extract_vision(image_path)

logger = logging.getLogger(__name__)


@authorized_only
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming photo - process as receipt."""
    if not update.message or not update.message.photo:
        return

    # Send immediate confirmation
    status_msg = await update.message.reply_text(
        "Odebrano zdjęcie paragonu. Rozpoczynam przetwarzanie..."
    )

    try:
        # Get highest resolution photo
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"telegram_{timestamp}.jpg"
        inbox_path = settings.INBOX_DIR / filename

        settings.ensure_directories()

        # Download file
        await file.download_to_drive(inbox_path)
        logger.info(f"Downloaded photo to: {inbox_path}")

        # Process receipt with progress updates
        result = await _process_receipt_with_progress(
            inbox_path, filename, status_msg, context
        )

        if result["success"]:
            # Check if human review is needed
            if result.get("needs_review"):
                import uuid
                receipt_id = str(uuid.uuid4())[:8]
                pending_key = f"pending_review_{receipt_id}"

                if context.user_data is not None:
                    context.user_data[pending_key] = {
                        "receipt": result["receipt"],
                        "categorized": result["categorized"],
                        "filename": filename,
                        "inbox_path": str(inbox_path),
                    }

                review_msg = format_review_receipt(
                    result["receipt"],
                    result["categorized"],
                    filename
                )
                try:
                    await status_msg.edit_text(
                        review_msg,
                        parse_mode="Markdown",
                        reply_markup=get_review_keyboard(receipt_id)
                    )
                except Exception:
                    await status_msg.edit_text(
                        review_msg,
                        reply_markup=get_review_keyboard(receipt_id)
                    )
            else:
                summary = format_receipt_summary(
                    result["receipt"],
                    result["categorized"],
                    filename
                )
                try:
                    await status_msg.edit_text(summary, parse_mode="Markdown")
                except Exception:
                    await status_msg.edit_text(summary)
        else:
            await status_msg.edit_text(
                f"Błąd przetwarzania: {result['error']}\n\n"
                f"Użyj `/reprocess {filename}` aby spróbować ponownie.",
                parse_mode="Markdown"
            )

    except Exception as e:
        logger.exception(f"Error processing photo: {e}")
        await status_msg.edit_text(f"Wystąpił błąd: {e}")


@authorized_only
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming PDF document - process as receipt."""
    if not update.message or not update.message.document:
        return

    document = update.message.document

    # Check if it's a PDF
    if not document.file_name or not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text(
            "Obsługuję tylko pliki PDF. Wyślij zdjęcie lub plik PDF paragonu."
        )
        return

    # Send immediate confirmation
    status_msg = await update.message.reply_text(
        "Odebrano plik PDF. Rozpoczynam przetwarzanie..."
    )

    temp_images: list[Path] = []

    try:
        # Download PDF
        file = await context.bot.get_file(document.file_id)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_filename = f"telegram_{timestamp}.pdf"
        inbox_path = settings.INBOX_DIR / pdf_filename

        settings.ensure_directories()

        await file.download_to_drive(inbox_path)
        logger.info(f"Downloaded PDF to: {inbox_path}")

        # Convert PDF to images
        await status_msg.edit_text("Konwersja PDF na obrazy...")
        try:
            temp_images = convert_pdf_to_images(inbox_path)
        except Exception as e:
            error_msg = f"PDF conversion failed: {e}"
            logger.error(error_msg)
            await status_msg.edit_text(f"Błąd konwersji PDF: {e}")
            return

        # Process each page and combine results
        all_products = []
        all_raw_texts = []  # Collect raw text for multi-page total extraction
        combined_receipt: Receipt | None = None

        for i, image_path in enumerate(temp_images):
            page_info = f" (strona {i+1}/{len(temp_images)})" if len(temp_images) > 1 else ""
            await status_msg.edit_text(f"Krok 1/3: Rozpoznawanie tekstu (OCR){page_info}...")

            receipt, ocr_error = await extract_products_from_image(image_path)

            if ocr_error or not receipt:
                # For multi-page PDFs, skip pages without products (e.g. summary pages)
                if len(temp_images) > 1:
                    logger.warning(f"Page {i+1}/{len(temp_images)} has no products, skipping: {ocr_error or 'No data'}")
                    continue
                # For single-page documents, this is an error
                error_msg = ocr_error or "OCR returned no data"
                logger.error(f"OCR failed for {pdf_filename}{page_info}: {error_msg}")
                write_error_file(pdf_filename, error_msg)
                log_error(pdf_filename, error_msg)
                await status_msg.edit_text(
                    f"Błąd OCR{page_info}: {error_msg}\n\n"
                    f"Użyj `/reprocess {pdf_filename}` aby spróbować ponownie.",
                    parse_mode="Markdown"
                )
                return

            all_products.extend(receipt.products)

            # Collect raw text for combined total extraction
            if receipt.raw_text:
                all_raw_texts.append(receipt.raw_text)

            if combined_receipt is None:
                combined_receipt = receipt
            else:
                if not combined_receipt.sklep and receipt.sklep:
                    combined_receipt.sklep = receipt.sklep
                if not combined_receipt.data and receipt.data:
                    combined_receipt.data = receipt.data

        # Check if any products were found across all pages
        if not all_products:
            error_msg = "No products found in any page of the PDF"
            logger.error(f"OCR failed for {pdf_filename}: {error_msg}")
            write_error_file(pdf_filename, error_msg)
            log_error(pdf_filename, error_msg)
            await status_msg.edit_text(
                f"Błąd OCR: Nie znaleziono produktów na żadnej stronie.\n\n"
                f"Użyj `/reprocess {pdf_filename}` aby spróbować ponownie.",
                parse_mode="Markdown"
            )
            return

        # Combine all products and fix multi-page total extraction
        if combined_receipt:
            combined_receipt.products = all_products

            # Calculate sum of all products for validation
            calculated_total = round(sum(p.cena for p in all_products), 2)
            combined_receipt.calculated_total = calculated_total

            # For multi-page PDFs, re-extract total from combined raw text
            # Payment info (Karta płatnicza) is typically on the last page
            if len(temp_images) > 1 and all_raw_texts and settings.OCR_BACKEND == "paddle":
                combined_raw_text = "\n".join(all_raw_texts)
                combined_receipt.raw_text = combined_raw_text

                final_total = extract_total_from_text(combined_raw_text)
                if final_total:
                    logger.info(f"Multi-page PDF: extracted payment total {final_total} from combined text")
                    combined_receipt.suma = final_total
                else:
                    logger.warning(f"Multi-page PDF: no payment total found, using calculated sum {calculated_total}")
                    combined_receipt.suma = calculated_total

            # Fallback: if no total set, use calculated
            if not combined_receipt.suma:
                combined_receipt.suma = calculated_total

            # Validate total against sum of products
            if combined_receipt.suma and calculated_total:
                variance = abs(combined_receipt.suma - calculated_total)
                variance_pct = (variance / calculated_total * 100) if calculated_total > 0 else 0

                if variance > 5.0 or variance_pct > 10:
                    combined_receipt.needs_review = True
                    combined_receipt.review_reasons.append(
                        f"Suma {combined_receipt.suma:.2f} zł różni się od sumy produktów {calculated_total:.2f} zł"
                    )
                    logger.warning(
                        f"Total mismatch: extracted={combined_receipt.suma}, calculated={calculated_total}"
                    )

            # Flag multi-page PDFs for review

        await unload_model(settings.OCR_MODEL)

        # Categorize
        await status_msg.edit_text(
            f"Krok 2/3: Kategoryzacja {len(all_products)} produktów..."
        )
        categorized, cat_error = await categorize_products(all_products)

        if cat_error:
            logger.warning(f"Categorization warning: {cat_error}")

        await unload_model(settings.CLASSIFIER_MODEL)

        # Check if human review is needed
        if combined_receipt.needs_review:
            # Store pending data for review
            import uuid
            receipt_id = str(uuid.uuid4())[:8]
            pending_key = f"pending_review_{receipt_id}"

            if context.user_data is not None:
                context.user_data[pending_key] = {
                    "receipt": combined_receipt,
                    "categorized": categorized,
                    "filename": pdf_filename,
                    "inbox_path": str(inbox_path),
                }

            # Show review message
            review_msg = format_review_receipt(combined_receipt, categorized, pdf_filename)
            try:
                await status_msg.edit_text(
                    review_msg,
                    parse_mode="Markdown",
                    reply_markup=get_review_keyboard(receipt_id)
                )
            except Exception as md_error:
                logger.warning(f"Markdown formatting failed: {md_error}")
                await status_msg.edit_text(
                    review_msg,
                    reply_markup=get_review_keyboard(receipt_id)
                )
            return

        # Write files (no review needed)
        await status_msg.edit_text("Krok 3/3: Zapisywanie do Obsidian...")

        try:
            receipt_file = write_receipt_file(combined_receipt, categorized, pdf_filename)
            update_pantry_file(categorized, combined_receipt)
        except Exception as e:
            error_msg = f"Failed to write output files: {e}"
            logger.error(error_msg)
            write_error_file(pdf_filename, error_msg)
            log_error(pdf_filename, error_msg)
            await status_msg.edit_text(f"Błąd zapisu: {e}")
            return

        # Move PDF to processed
        try:
            processed_path = settings.PROCESSED_DIR / pdf_filename
            shutil.move(inbox_path, processed_path)
            logger.info(f"Moved to processed: {processed_path}")
        except Exception as e:
            logger.warning(f"Failed to move file to processed: {e}")

        # Try with Markdown, fallback to plain text if it fails
        summary = format_receipt_summary(combined_receipt, categorized, pdf_filename)
        try:
            await status_msg.edit_text(summary, parse_mode="Markdown")
        except Exception as md_error:
            logger.warning(f"Markdown formatting failed, sending plain text: {md_error}")
            await status_msg.edit_text(summary)

    except Exception as e:
        logger.exception(f"Error processing PDF: {e}")
        await status_msg.edit_text(f"Wystąpił błąd: {e}")

    finally:
        # Clean up temporary PNG files
        for temp_image in temp_images:
            try:
                if temp_image.exists():
                    temp_image.unlink()
                    logger.debug(f"Cleaned up temp file: {temp_image}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp file {temp_image}: {e}")


async def _process_pdf_with_progress(
    file_path: Path,
    filename: str,
    status_msg,
    context: ContextTypes.DEFAULT_TYPE
) -> dict:
    """Process PDF receipt with progress updates."""
    temp_images: list[Path] = []

    try:
        # Convert PDF to images
        await status_msg.edit_text("Konwersja PDF na obrazy...")
        try:
            temp_images = convert_pdf_to_images(file_path)
        except Exception as e:
            return {"success": False, "error": f"PDF conversion failed: {e}"}

        # Process each page
        all_products = []
        all_raw_texts = []
        combined_receipt: Receipt | None = None

        for i, image_path in enumerate(temp_images):
            page_info = f" (strona {i+1}/{len(temp_images)})" if len(temp_images) > 1 else ""
            await status_msg.edit_text(f"Krok 1/3: Rozpoznawanie tekstu (OCR){page_info}...")

            receipt, ocr_error = await extract_products_from_image(image_path)

            if ocr_error or not receipt:
                # For multi-page PDFs, skip pages without products
                if len(temp_images) > 1:
                    logger.warning(f"Page {i+1}/{len(temp_images)} has no products, skipping: {ocr_error or 'No data'}")
                    continue
                error_msg = ocr_error or "OCR returned no data"
                logger.error(f"OCR failed for {filename}{page_info}: {error_msg}")
                write_error_file(filename, error_msg)
                log_error(filename, error_msg)
                return {"success": False, "error": f"OCR{page_info}: {error_msg}"}

            all_products.extend(receipt.products)

            if receipt.raw_text:
                all_raw_texts.append(receipt.raw_text)

            if combined_receipt is None:
                combined_receipt = receipt
            else:
                if not combined_receipt.sklep and receipt.sklep:
                    combined_receipt.sklep = receipt.sklep
                if not combined_receipt.data and receipt.data:
                    combined_receipt.data = receipt.data

        # Check if any products found
        if not all_products:
            return {"success": False, "error": "No products found in any page"}

        # Combine products with proper total extraction
        if combined_receipt:
            combined_receipt.products = all_products
            calculated_total = round(sum(p.cena for p in all_products), 2)
            combined_receipt.calculated_total = calculated_total

            # For multi-page PDFs, re-extract total from combined raw text
            if len(temp_images) > 1 and all_raw_texts and settings.OCR_BACKEND == "paddle":
                combined_raw_text = "\n".join(all_raw_texts)
                combined_receipt.raw_text = combined_raw_text

                final_total = extract_total_from_text(combined_raw_text)
                if final_total:
                    logger.info(f"Multi-page PDF: extracted payment total {final_total}")
                    combined_receipt.suma = final_total
                else:
                    combined_receipt.suma = calculated_total

            if not combined_receipt.suma:
                combined_receipt.suma = calculated_total

            # Validate and flag for review if needed
            if combined_receipt.suma and calculated_total:
                variance = abs(combined_receipt.suma - calculated_total)
                variance_pct = (variance / calculated_total * 100) if calculated_total > 0 else 0

                if variance > 5.0 or variance_pct > 10:
                    combined_receipt.needs_review = True
                    combined_receipt.review_reasons.append(
                        f"Suma {combined_receipt.suma:.2f} zł różni się od sumy produktów {calculated_total:.2f} zł"
                    )


        await unload_model(settings.OCR_MODEL)

        # Categorize
        await status_msg.edit_text(f"Krok 2/3: Kategoryzacja {len(all_products)} produktów...")
        categorized, cat_error = await categorize_products(all_products)

        if cat_error:
            logger.warning(f"Categorization warning: {cat_error}")

        await unload_model(settings.CLASSIFIER_MODEL)

        # Check if human review is needed
        if combined_receipt.needs_review:
            return {
                "success": True,
                "needs_review": True,
                "receipt": combined_receipt,
                "categorized": categorized,
                "file_path": str(file_path),
            }

        # Write files
        await status_msg.edit_text("Krok 3/3: Zapisywanie do Obsidian...")

        try:
            receipt_file = write_receipt_file(combined_receipt, categorized, filename)
            update_pantry_file(categorized, combined_receipt)
        except Exception as e:
            error_msg = f"Failed to write output files: {e}"
            logger.error(error_msg)
            write_error_file(filename, error_msg)
            log_error(filename, error_msg)
            return {"success": False, "error": error_msg}

        # Move to processed
        try:
            processed_path = settings.PROCESSED_DIR / filename
            shutil.move(file_path, processed_path)
            logger.info(f"Moved to processed: {processed_path}")
        except Exception as e:
            logger.warning(f"Failed to move file: {e}")

        return {
            "success": True,
            "needs_review": False,
            "receipt": combined_receipt,
            "categorized": categorized,
            "output_file": str(receipt_file)
        }

    finally:
        # Clean up temp images
        for temp_image in temp_images:
            try:
                if temp_image.exists():
                    temp_image.unlink()
            except Exception:
                pass


async def _process_receipt_with_progress(
    file_path: Path,
    filename: str,
    status_msg,
    context: ContextTypes.DEFAULT_TYPE
) -> dict:
    """Process receipt with progress updates."""

    # Step 1: OCR
    await status_msg.edit_text("Krok 1/3: Rozpoznawanie tekstu (OCR)...")
    logger.info(f"Starting OCR for: {filename}")

    receipt, ocr_error = await extract_products_from_image(file_path)

    if ocr_error or not receipt:
        error_msg = ocr_error or "OCR returned no data"
        logger.error(f"OCR failed for {filename}: {error_msg}")

        write_error_file(filename, error_msg)
        log_error(filename, error_msg)

        return {"success": False, "error": error_msg}

    # Validate total against sum of products
    calculated_total = round(sum(p.cena for p in receipt.products), 2)
    receipt.calculated_total = calculated_total

    if not receipt.suma:
        receipt.suma = calculated_total

    if receipt.suma and calculated_total:
        variance = abs(receipt.suma - calculated_total)
        variance_pct = (variance / calculated_total * 100) if calculated_total > 0 else 0

        if variance > 5.0 or variance_pct > 10:
            receipt.needs_review = True
            receipt.review_reasons.append(
                f"Suma {receipt.suma:.2f} zł różni się od sumy produktów {calculated_total:.2f} zł"
            )
            logger.warning(
                f"Total mismatch for {filename}: extracted={receipt.suma}, calculated={calculated_total}"
            )

    # Unload OCR model
    await unload_model(settings.OCR_MODEL)

    # Step 2: Categorize
    await status_msg.edit_text(
        f"Krok 2/3: Kategoryzacja {len(receipt.products)} produktów..."
    )
    logger.info(f"Categorizing {len(receipt.products)} products")

    categorized, cat_error = await categorize_products(receipt.products)

    if cat_error:
        logger.warning(f"Categorization warning: {cat_error}")

    # Unload classifier model
    await unload_model(settings.CLASSIFIER_MODEL)

    # Check if human review is needed
    if receipt.needs_review:
        return {
            "success": True,
            "needs_review": True,
            "receipt": receipt,
            "categorized": categorized,
            "file_path": str(file_path),
        }

    # Step 3: Write files
    await status_msg.edit_text("Krok 3/3: Zapisywanie do Obsidian...")

    try:
        receipt_file = write_receipt_file(receipt, categorized, filename)
        update_pantry_file(categorized, receipt)
    except Exception as e:
        error_msg = f"Failed to write output files: {e}"
        logger.error(error_msg)

        write_error_file(filename, error_msg)
        log_error(filename, error_msg)

        return {"success": False, "error": error_msg}

    # Move to processed
    try:
        processed_path = settings.PROCESSED_DIR / filename
        shutil.move(file_path, processed_path)
        logger.info(f"Moved to processed: {processed_path}")
    except Exception as e:
        logger.warning(f"Failed to move file to processed: {e}")

    return {
        "success": True,
        "needs_review": False,
        "receipt": receipt,
        "categorized": categorized,
        "output_file": str(receipt_file)
    }


@authorized_only
async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /recent command - list recent receipts."""
    if not update.message:
        return

    # Get count from args (default 5)
    count = 5
    if context.args:
        try:
            count = min(int(context.args[0]), 20)
        except ValueError:
            pass

    receipts = _get_recent_receipts(count)
    await update.message.reply_text(
        format_receipt_list(receipts),
        parse_mode="Markdown"
    )


def _get_recent_receipts(count: int) -> list[dict]:
    """Get list of recent receipt files with metadata."""
    receipts = []
    receipts_dir = settings.RECEIPTS_DIR

    if not receipts_dir.exists():
        return []

    # Get all receipt files (not ERROR files)
    files = [
        f for f in receipts_dir.glob("*.md")
        if not f.name.startswith("ERROR_")
    ]

    # Sort by modification time
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    for file_path in files[:count]:
        receipt_info = _parse_receipt_frontmatter(file_path)
        if receipt_info:
            receipt_info["filename"] = file_path.name
            receipts.append(receipt_info)

    return receipts


def _parse_receipt_frontmatter(file_path: Path) -> Optional[dict]:
    """Parse YAML frontmatter from receipt file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.startswith("---"):
            return None

        # Extract frontmatter
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        import yaml
        frontmatter = yaml.safe_load(parts[1])
        return {
            "date": frontmatter.get("date", "?"),
            "store": frontmatter.get("store", "nieznany"),
            "total": frontmatter.get("total", "?")
        }
    except Exception as e:
        logger.warning(f"Failed to parse receipt {file_path}: {e}")
        return None


@authorized_only
async def reprocess_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reprocess command - reprocess a file."""
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Użycie: `/reprocess <nazwa_pliku>`\n\n"
            "Przykład: `/reprocess telegram_20240115_120000.jpg`",
            parse_mode="Markdown"
        )
        return

    filename = context.args[0]

    # Check inbox first, then processed
    inbox_path = settings.INBOX_DIR / filename
    processed_path = settings.PROCESSED_DIR / filename

    if inbox_path.exists():
        file_path = inbox_path
    elif processed_path.exists():
        # Move back to inbox
        shutil.move(processed_path, inbox_path)
        file_path = inbox_path
    else:
        await update.message.reply_text(f"Nie znaleziono pliku: `{filename}`", parse_mode="Markdown")
        return

    status_msg = await update.message.reply_text(
        f"Ponowne przetwarzanie: `{filename}`...",
        parse_mode="Markdown"
    )

    # Check if it's a PDF - needs special handling
    if filename.lower().endswith('.pdf'):
        result = await _process_pdf_with_progress(file_path, filename, status_msg, context)
    else:
        result = await _process_receipt_with_progress(file_path, filename, status_msg, context)

    if result["success"]:
        # Check if human review is needed
        if result.get("needs_review"):
            import uuid
            receipt_id = str(uuid.uuid4())[:8]
            pending_key = f"pending_review_{receipt_id}"

            if context.user_data is not None:
                context.user_data[pending_key] = {
                    "receipt": result["receipt"],
                    "categorized": result["categorized"],
                    "filename": filename,
                    "inbox_path": str(file_path),
                }

            review_msg = format_review_receipt(
                result["receipt"],
                result["categorized"],
                filename
            )
            try:
                await status_msg.edit_text(
                    review_msg,
                    parse_mode="Markdown",
                    reply_markup=get_review_keyboard(receipt_id)
                )
            except Exception:
                await status_msg.edit_text(
                    review_msg,
                    reply_markup=get_review_keyboard(receipt_id)
                )
        else:
            summary = format_receipt_summary(
                result["receipt"],
                result["categorized"],
                filename
            )
            try:
                await status_msg.edit_text(summary, parse_mode="Markdown")
            except Exception:
                await status_msg.edit_text(summary)
    else:
        await status_msg.edit_text(f"Błąd przetwarzania: {result['error']}")


@authorized_only
async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pending command - list files in inbox."""
    if not update.message:
        return

    inbox_dir = settings.INBOX_DIR

    if not inbox_dir.exists():
        await update.message.reply_text("Folder inbox nie istnieje.")
        return

    files = [
        f.name for f in inbox_dir.iterdir()
        if f.is_file() and f.suffix.lower() in settings.SUPPORTED_FORMATS
    ]

    await update.message.reply_text(
        format_pending_files(files),
        parse_mode="Markdown"
    )
