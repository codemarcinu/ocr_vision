"""FastAPI application for Smart Pantry Tracker."""

import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.classifier import categorize_products
from app.config import settings
from app.dictionary_api import router as dictionary_router
from app.models import HealthStatus, ProcessingResult, Receipt
from app.obsidian_writer import log_error, update_pantry_file, write_error_file, write_receipt_file
from app.ocr import extract_products_from_image, unload_model
from app.pdf_converter import convert_pdf_to_images
from app.reports import router as reports_router
from prometheus_fastapi_instrumentator import Instrumentator
from app.telegram.bot import bot

# Import PaddleOCR backend if configured
if settings.OCR_BACKEND == "paddle":
    from app.paddle_ocr import extract_products_paddle, extract_total_from_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Smart Pantry Tracker",
    description="OCR-based receipt processing for pantry management",
    version="1.0.0"
)

# Register API routers
app.include_router(dictionary_router)
app.include_router(reports_router)

# Prometheus metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.on_event("startup")
async def startup_event():
    """Initialize directories and start Telegram bot on startup."""
    settings.ensure_directories()
    logger.info("Smart Pantry Tracker started")
    logger.info(f"Inbox: {settings.INBOX_DIR}")
    logger.info(f"Vault: {settings.VAULT_DIR}")

    # Start Telegram bot
    await bot.start()


@app.on_event("shutdown")
async def shutdown_event():
    """Stop Telegram bot on shutdown."""
    await bot.stop()


@app.get("/health", response_model=HealthStatus)
async def health_check():
    """Check health of the service and Ollama models."""
    ollama_available = False
    ocr_loaded = False
    classifier_loaded = False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            if response.status_code == 200:
                ollama_available = True
                models = response.json().get("models", [])
                model_names = [m.get("name", "").split(":")[0] for m in models]
                ocr_loaded = settings.OCR_MODEL.split(":")[0] in model_names
                classifier_loaded = settings.CLASSIFIER_MODEL.split(":")[0] in model_names
    except Exception as e:
        logger.warning(f"Health check failed: {e}")

    status = "healthy" if ollama_available else "degraded"

    return HealthStatus(
        status=status,
        ollama_available=ollama_available,
        ocr_model_loaded=ocr_loaded,
        classifier_model_loaded=classifier_loaded,
        inbox_path=str(settings.INBOX_DIR),
        vault_path=str(settings.VAULT_DIR)
    )


@app.post("/process-receipt", response_model=ProcessingResult)
async def process_receipt(file: UploadFile = File(...)):
    """
    Process a receipt image.

    1. Save uploaded file to inbox
    2. Run OCR to extract products
    3. Categorize products
    4. Write receipt markdown file
    5. Update pantry file
    6. Move file to processed folder
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in settings.SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format. Allowed: {settings.SUPPORTED_FORMATS}"
        )

    settings.ensure_directories()

    # Save to inbox
    inbox_path = settings.INBOX_DIR / file.filename
    try:
        with open(inbox_path, "wb") as f:
            content = await file.read()
            f.write(content)
        logger.info(f"Saved file to inbox: {inbox_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    return await _process_file(inbox_path)


@app.post("/reprocess/{filename}", response_model=ProcessingResult)
async def reprocess_receipt(filename: str):
    """Reprocess a file from inbox or processed folder."""
    # Check inbox first, then processed
    inbox_path = settings.INBOX_DIR / filename
    processed_path = settings.PROCESSED_DIR / filename

    if inbox_path.exists():
        file_path = inbox_path
    elif processed_path.exists():
        # Move back to inbox for reprocessing
        shutil.move(processed_path, inbox_path)
        file_path = inbox_path
    else:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    return await _process_file(file_path)


async def _process_single_page(
    image_path: Path,
    page_num: int,
    total_pages: int,
    filename: str,
    semaphore: asyncio.Semaphore
) -> tuple[int, tuple[Optional[Receipt], Optional[str]]]:
    """Process a single page with semaphore for concurrency control."""
    async with semaphore:
        page_info = f" (page {page_num+1}/{total_pages})" if total_pages > 1 else ""
        logger.info(f"Starting OCR ({settings.OCR_BACKEND}) for: {filename}{page_info}")

        # Use configured OCR backend
        if settings.OCR_BACKEND == "paddle":
            receipt, ocr_error = await extract_products_paddle(image_path)
        else:
            receipt, ocr_error = await extract_products_from_image(image_path)

        return page_num, (receipt, ocr_error)


async def _process_pages_parallel(
    image_paths: list[Path],
    filename: str
) -> list[tuple[Optional[Receipt], Optional[str]]]:
    """Process multiple pages in parallel using semaphore for concurrency control."""
    semaphore = asyncio.Semaphore(settings.PDF_MAX_PARALLEL_PAGES)
    total_pages = len(image_paths)

    # Create tasks for all pages
    tasks = [
        _process_single_page(image_path, i, total_pages, filename, semaphore)
        for i, image_path in enumerate(image_paths)
    ]

    # Run all tasks concurrently (semaphore limits actual parallelism)
    results = await asyncio.gather(*tasks)

    # Sort by page number and extract just the receipt/error tuples
    results.sort(key=lambda x: x[0])
    return [result[1] for result in results]


async def _process_pages_sequential(
    image_paths: list[Path],
    filename: str
) -> list[tuple[Optional[Receipt], Optional[str]]]:
    """Process pages sequentially (for single-page or when parallel is disabled)."""
    results = []
    total_pages = len(image_paths)

    for i, image_path in enumerate(image_paths):
        page_info = f" (page {i+1}/{total_pages})" if total_pages > 1 else ""
        logger.info(f"Starting OCR ({settings.OCR_BACKEND}) for: {filename}{page_info}")

        # Use configured OCR backend
        if settings.OCR_BACKEND == "paddle":
            receipt, ocr_error = await extract_products_paddle(image_path)
        else:
            receipt, ocr_error = await extract_products_from_image(image_path)

        results.append((receipt, ocr_error))

    return results


async def _process_file(file_path: Path) -> ProcessingResult:
    """Internal processing logic."""
    filename = file_path.name
    processed_at = datetime.now()
    temp_images: list[Path] = []

    try:
        # Check if PDF - convert to images first
        if file_path.suffix.lower() == ".pdf":
            logger.info(f"Converting PDF to images: {filename}")
            try:
                temp_images = convert_pdf_to_images(file_path)
            except Exception as e:
                error_msg = f"PDF conversion failed: {e}"
                logger.error(error_msg)
                error_file = write_error_file(filename, error_msg)
                log_error(filename, error_msg)
                return ProcessingResult(
                    success=False,
                    source_file=filename,
                    output_file=str(error_file),
                    error=error_msg,
                    processed_at=processed_at
                )
            image_paths = temp_images
        else:
            image_paths = [file_path]

        # Step 1: OCR (process all pages - parallel for multi-page PDFs)
        all_products = []
        all_raw_texts = []  # Collect raw text from all pages for total extraction
        combined_receipt: Receipt | None = None

        # Process pages - use parallel processing for multi-page PDFs
        if len(image_paths) > 1 and settings.PDF_MAX_PARALLEL_PAGES > 1:
            # Parallel processing for multi-page PDFs
            logger.info(f"Processing {len(image_paths)} pages in parallel (max {settings.PDF_MAX_PARALLEL_PAGES} concurrent)")
            page_results = await _process_pages_parallel(image_paths, filename)
        else:
            # Sequential processing for single pages or when parallel is disabled
            page_results = await _process_pages_sequential(image_paths, filename)

        # Combine results from all pages
        for page_num, (page_receipt, page_error) in enumerate(page_results):
            page_info = f" (page {page_num+1}/{len(image_paths)})" if len(image_paths) > 1 else ""

            if page_error or not page_receipt:
                # For multi-page PDFs, skip pages without products (e.g. summary pages)
                if len(image_paths) > 1:
                    logger.warning(f"Page {page_num+1}/{len(image_paths)} has no products, skipping: {page_error or 'No data'}")
                    continue
                # For single-page documents, this is an error
                error_msg = page_error or "OCR returned no data"
                logger.error(f"OCR failed for {filename}{page_info}: {error_msg}")

                error_file = write_error_file(filename, error_msg)
                log_error(filename, error_msg)

                return ProcessingResult(
                    success=False,
                    source_file=filename,
                    output_file=str(error_file),
                    error=error_msg,
                    processed_at=processed_at
                )

            # Combine results from all pages
            all_products.extend(page_receipt.products)

            # Collect raw text for combined total extraction
            if page_receipt.raw_text:
                all_raw_texts.append(page_receipt.raw_text)

            # Use metadata from first page (or update if later page has better data)
            if combined_receipt is None:
                combined_receipt = page_receipt
            else:
                # Keep first page's metadata but combine products
                combined_receipt.products = all_products
                # If first page didn't have store/date, use from this page
                if not combined_receipt.sklep and page_receipt.sklep:
                    combined_receipt.sklep = page_receipt.sklep
                if not combined_receipt.data and page_receipt.data:
                    combined_receipt.data = page_receipt.data

        # Check if any products were found across all pages
        if not all_products:
            error_msg = "No products found in any page of the PDF"
            logger.error(f"OCR failed for {filename}: {error_msg}")
            error_file = write_error_file(filename, error_msg)
            log_error(filename, error_msg)
            return ProcessingResult(
                success=False,
                source_file=filename,
                output_file=str(error_file),
                error=error_msg,
                processed_at=processed_at
            )

        # Combine products for multi-page receipts
        if combined_receipt:
            combined_receipt.products = all_products

            # Calculate sum of all products for validation
            calculated_total = round(sum(p.cena for p in all_products), 2)
            combined_receipt.calculated_total = calculated_total

            # For multi-page PDFs, re-extract total from combined raw text
            # Payment info (Karta płatnicza) is typically on the last page
            if len(image_paths) > 1 and all_raw_texts and settings.OCR_BACKEND == "paddle":
                combined_raw_text = "\n".join(all_raw_texts)
                combined_receipt.raw_text = combined_raw_text

                # Try to extract final payment total from combined text
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

                # Flag for review if significant mismatch (>5 PLN or >10%)
                if variance > 5.0 or variance_pct > 10:
                    combined_receipt.needs_review = True
                    combined_receipt.review_reasons.append(
                        f"Suma {combined_receipt.suma:.2f} zł różni się od sumy produktów {calculated_total:.2f} zł "
                        f"(różnica: {variance:.2f} zł / {variance_pct:.1f}%)"
                    )
                    logger.warning(
                        f"Total mismatch for {filename}: extracted={combined_receipt.suma}, "
                        f"calculated={calculated_total}, variance={variance:.2f} ({variance_pct:.1f}%)"
                    )


            receipt = combined_receipt

        # Optionally unload OCR model to free memory (controlled by UNLOAD_MODELS_AFTER_USE)
        if settings.UNLOAD_MODELS_AFTER_USE:
            await unload_model(settings.OCR_MODEL)
            logger.debug("Unloaded OCR model (UNLOAD_MODELS_AFTER_USE=true)")

        # Step 2: Categorize
        logger.info(f"Categorizing {len(receipt.products)} products")
        categorized, cat_error = await categorize_products(receipt.products)

        if cat_error:
            logger.warning(f"Categorization warning: {cat_error}")

        # Optionally unload classifier model
        if settings.UNLOAD_MODELS_AFTER_USE:
            await unload_model(settings.CLASSIFIER_MODEL)
            logger.debug("Unloaded classifier model (UNLOAD_MODELS_AFTER_USE=true)")

        # Step 3: Write files
        try:
            receipt_file = write_receipt_file(receipt, categorized, filename)
            update_pantry_file(categorized, receipt)
        except Exception as e:
            error_msg = f"Failed to write output files: {e}"
            logger.error(error_msg)

            error_file = write_error_file(filename, error_msg)
            log_error(filename, error_msg)

            return ProcessingResult(
                success=False,
                receipt=receipt,
                source_file=filename,
                output_file=str(error_file),
                error=error_msg,
                processed_at=processed_at
            )

        # Step 4: Move to processed
        try:
            processed_path = settings.PROCESSED_DIR / filename
            shutil.move(file_path, processed_path)
            logger.info(f"Moved to processed: {processed_path}")
        except Exception as e:
            logger.warning(f"Failed to move file to processed: {e}")

        return ProcessingResult(
            success=True,
            receipt=receipt,
            source_file=filename,
            output_file=str(receipt_file),
            processed_at=processed_at,
            needs_review=receipt.needs_review if receipt else False
        )

    finally:
        # Clean up temporary PNG files created from PDF
        for temp_image in temp_images:
            try:
                if temp_image.exists():
                    temp_image.unlink()
                    logger.debug(f"Cleaned up temp file: {temp_image}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp file {temp_image}: {e}")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Smart Pantry Tracker",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "process": "/process-receipt",
            "reprocess": "/reprocess/{filename}"
        }
    }
