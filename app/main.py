"""FastAPI application for Second Brain."""

import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from uuid import UUID

import httpx
import secrets

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.classifier import categorize_products
from app.config import settings
from app.db.connection import close_db, init_db
from app.dependencies import AnalyticsRepoDep, FeedbackRepoDep, PantryRepoDep, ReceiptRepoDep
from app.dictionary_api import router as dictionary_router
from app.models import HealthStatus, ProcessingResult, Receipt
from app.obsidian_writer import log_error, write_error_file
from app.services.receipt_saver import save_receipt_to_db, write_receipt_to_obsidian, index_receipt_in_rag
from app.rss_api import router as rss_router
from app.transcription_api import router as transcription_router
from app.notes_api import router as notes_router
from app.ask_api import router as ask_router
from app.chat_api import router as chat_router
from app.bookmarks_api import router as bookmarks_router
from app.pantry_api import router as pantry_router
from app.receipts_api import router as receipts_router
from app.search_api import router as search_router
from app.web_routes import router as web_router
from app.profile_api import router as profile_router
from app.mobile_routes import router as mobile_router
from app.push_api import router as push_router
from app.ocr import extract_products_from_image, extract_total_from_text
from app.pdf_converter import convert_pdf_to_images
from app.reports import router as reports_router
from app.services.obsidian_sync import obsidian_sync
from app import ollama_client
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.telegram.bot import bot
from app.auth import web_auth_middleware, create_session, destroy_session

# Import alternative OCR backends if configured
if settings.OCR_BACKEND == "paddle":
    from app.paddle_ocr import extract_products_paddle, extract_total_from_text
elif settings.OCR_BACKEND == "deepseek":
    from app.deepseek_ocr import extract_products_deepseek, extract_total_from_text, process_multipage_pdf
elif settings.OCR_BACKEND == "google":
    from app.google_ocr_backend import extract_products_google, process_multipage_pdf_google
elif settings.OCR_BACKEND == "openai":
    from app.openai_ocr_backend import extract_products_openai, process_multipage_pdf_openai, extract_total_from_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Second Brain",
    description="Personal knowledge management system",
    version="1.0.0"
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security headers middleware
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# Authentication middleware
app.middleware("http")(web_auth_middleware)

# Templates for login page
_auth_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show login form."""
    return _auth_templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login_submit(request: Request, token: str = Form(...)):
    """Validate token and set session cookie."""
    if not secrets.compare_digest(token, settings.AUTH_TOKEN):
        return _auth_templates.TemplateResponse("login.html", {
            "request": request, "error": "Nieprawidłowy token",
        })
    session_token = create_session()
    response = RedirectResponse(url="/app/", status_code=303)
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 30,  # 30 days
    )
    return response


@app.get("/logout")
async def logout(request: Request):
    """Destroy session and redirect to login."""
    session_token = request.cookies.get("session_token", "")
    destroy_session(session_token)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_token")
    return response


# Register API routers
app.include_router(dictionary_router)
app.include_router(reports_router)
app.include_router(rss_router)
app.include_router(transcription_router)
app.include_router(notes_router)
app.include_router(bookmarks_router)
app.include_router(ask_router)
app.include_router(chat_router)
app.include_router(pantry_router)
app.include_router(receipts_router)
app.include_router(search_router)
app.include_router(profile_router)
app.include_router(mobile_router)
app.include_router(push_router)
app.include_router(web_router)

# Mount static files for web UI
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

# Prometheus metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.on_event("startup")
async def startup_event():
    """Initialize directories, database, and start Telegram bot on startup."""
    settings.ensure_directories()

    # Initialize database connection
    if settings.USE_DB_RECEIPTS or settings.USE_DB_DICTIONARIES:
        try:
            await init_db()
            logger.info("Database connection initialized")
        except Exception as e:
            logger.warning(f"Database initialization failed: {e}")
            logger.info("Continuing without database - using file-based storage")

    logger.info("Second Brain started")
    logger.info(f"Inbox: {settings.INBOX_DIR}")
    logger.info(f"Vault: {settings.VAULT_DIR}")
    logger.info(f"Database enabled: {settings.USE_DB_RECEIPTS}")

    # RAG: check if embeddings table is empty and trigger background reindex
    if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
        try:
            from app.db.connection import get_session
            from app.db.repositories.embeddings import EmbeddingRepository
            from app.rag.indexer import reindex_all
            async for session in get_session():
                repo = EmbeddingRepository(session)
                stats = await repo.get_stats()
                total = sum(stats.values()) if stats else 0
                if total == 0:
                    logger.info("RAG: embeddings table empty, starting background reindex")
                    asyncio.create_task(reindex_all(progress_callback=lambda msg: logger.info(f"RAG reindex: {msg}")))
                else:
                    logger.info(f"RAG: {total} embeddings found, skipping reindex")
        except Exception as e:
            logger.warning(f"RAG startup check failed: {e}")

    # Model preloading: warm up frequently used models to reduce first-request latency
    if settings.MODEL_PRELOAD_ON_STARTUP:
        models = [m.strip() for m in settings.MODEL_PRELOAD_ON_STARTUP.split(",") if m.strip()]
        if models:
            logger.info(f"Preloading models: {models}")
            for model in models:
                try:
                    # Send a minimal request to load the model into VRAM
                    _, error = await ollama_client.post_generate(
                        model=model,
                        prompt="warmup",
                        options={"num_predict": 1},
                        timeout=120.0,
                    )
                    if error:
                        logger.warning(f"Failed to preload model {model}: {error}")
                    else:
                        logger.info(f"Preloaded model: {model}")
                except Exception as e:
                    logger.warning(f"Failed to preload model {model}: {e}")

    # Start Telegram bot
    await bot.start()


@app.on_event("shutdown")
async def shutdown_event():
    """Stop Telegram bot, close database and HTTP clients on shutdown."""
    await bot.stop()

    # Close Ollama HTTP client
    await ollama_client.close_client()
    logger.info("Ollama client closed")

    # Close OpenAI client if used
    if settings.OCR_BACKEND == "openai":
        from app.openai_client import close_client as close_openai
        await close_openai()
        logger.info("OpenAI client closed")

    # Close database connection
    if settings.USE_DB_RECEIPTS or settings.USE_DB_DICTIONARIES:
        await close_db()
        logger.info("Database connection closed")


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


@app.get("/models/status")
async def model_coordinator_status():
    """Get current status of Ollama model coordinator.

    Shows which models are loaded, VRAM usage, and coordination metrics.
    Useful for monitoring model switching overhead and VRAM pressure.
    """
    from app.model_coordinator import get_coordinator

    coordinator = get_coordinator()
    status = coordinator.get_status()

    # Add Ollama's actual loaded models for comparison
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{settings.OLLAMA_BASE_URL}/api/ps")
            if response.status_code == 200:
                ollama_ps = response.json().get("models", [])
                status["ollama_loaded"] = [
                    {
                        "name": m.get("name"),
                        "size_vram": m.get("size_vram"),
                        "digest": m.get("digest", "")[:12],
                    }
                    for m in ollama_ps
                ]
    except Exception as e:
        status["ollama_loaded"] = f"Error fetching: {e}"

    status["coordination_enabled"] = settings.MODEL_COORDINATION_ENABLED

    return status


@app.post("/process-receipt", response_model=ProcessingResult)
@limiter.limit("10/minute")
async def process_receipt(request: Request, file: UploadFile = File(...)):
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

    # Save to inbox (sanitize filename to prevent path traversal)
    from pathlib import PurePosixPath
    safe_name = PurePosixPath(file.filename).name
    if not safe_name or safe_name.startswith('.'):
        raise HTTPException(status_code=400, detail="Nieprawidłowa nazwa pliku")
    inbox_path = settings.INBOX_DIR / safe_name
    try:
        with open(inbox_path, "wb") as f:
            content = await file.read()
            f.write(content)
        logger.info(f"Saved file to inbox: {inbox_path}")
    except Exception as e:
        logger.error(f"Failed to save file: {e}")
        raise HTTPException(status_code=500, detail="Nie udało się zapisać pliku")

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

        # For multi-page PDFs, skip per-page verification (done after combining)
        is_multi_page = total_pages > 1

        # Use configured OCR backend
        if settings.OCR_BACKEND == "paddle":
            receipt, ocr_error = await extract_products_paddle(image_path)
        elif settings.OCR_BACKEND == "deepseek":
            receipt, ocr_error = await extract_products_deepseek(image_path, is_multi_page=is_multi_page)
        elif settings.OCR_BACKEND == "google":
            receipt, ocr_error = await extract_products_google(image_path, is_multi_page=is_multi_page)
        elif settings.OCR_BACKEND == "openai":
            receipt, ocr_error = await extract_products_openai(image_path, is_multi_page=is_multi_page)
        else:
            receipt, ocr_error = await extract_products_from_image(image_path, is_multi_page=is_multi_page)

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

    # For multi-page PDFs, skip per-page verification (done after combining)
    is_multi_page = total_pages > 1

    for i, image_path in enumerate(image_paths):
        page_info = f" (page {i+1}/{total_pages})" if total_pages > 1 else ""
        logger.info(f"Starting OCR ({settings.OCR_BACKEND}) for: {filename}{page_info}")

        # Use configured OCR backend
        if settings.OCR_BACKEND == "paddle":
            receipt, ocr_error = await extract_products_paddle(image_path)
        elif settings.OCR_BACKEND == "deepseek":
            receipt, ocr_error = await extract_products_deepseek(image_path, is_multi_page=is_multi_page)
        elif settings.OCR_BACKEND == "google":
            receipt, ocr_error = await extract_products_google(image_path, is_multi_page=is_multi_page)
        elif settings.OCR_BACKEND == "openai":
            receipt, ocr_error = await extract_products_openai(image_path, is_multi_page=is_multi_page)
        else:
            receipt, ocr_error = await extract_products_from_image(image_path, is_multi_page=is_multi_page)

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

        # Step 1: OCR (process all pages)
        all_products = []
        all_raw_texts = []  # Collect raw text from all pages for total extraction
        combined_receipt: Receipt | None = None

        # NEW: For multi-page PDFs with deepseek/google backend, use unified processing
        # (OCR all pages first, then single LLM call on combined text)
        if len(image_paths) > 1 and settings.OCR_BACKEND == "deepseek":
            logger.info(f"Multipage PDF ({len(image_paths)} pages): using unified OCR→LLM pipeline")
            combined_receipt, ocr_error = await process_multipage_pdf(image_paths, filename)

            if ocr_error or not combined_receipt:
                error_msg = ocr_error or "Multipage OCR returned no data"
                logger.error(f"Multipage OCR failed for {filename}: {error_msg}")
                error_file = write_error_file(filename, error_msg)
                log_error(filename, error_msg)
                return ProcessingResult(
                    success=False,
                    source_file=filename,
                    output_file=str(error_file),
                    error=error_msg,
                    processed_at=processed_at
                )

            # Skip the per-page processing loop - go directly to categorization
            all_products = combined_receipt.products
            page_results = []  # Empty - not used in unified mode

        elif len(image_paths) > 1 and settings.OCR_BACKEND == "google":
            logger.info(f"Multipage PDF ({len(image_paths)} pages): using Google Vision pipeline")
            combined_receipt, ocr_error = await process_multipage_pdf_google(image_paths, filename)

            if ocr_error or not combined_receipt:
                error_msg = ocr_error or "Google Vision OCR returned no data"
                logger.error(f"Google Vision OCR failed for {filename}: {error_msg}")
                error_file = write_error_file(filename, error_msg)
                log_error(filename, error_msg)
                return ProcessingResult(
                    success=False,
                    source_file=filename,
                    output_file=str(error_file),
                    error=error_msg,
                    processed_at=processed_at
                )

            # Skip the per-page processing loop - go directly to categorization
            all_products = combined_receipt.products
            page_results = []  # Empty - not used in unified mode

        elif len(image_paths) > 1 and settings.OCR_BACKEND == "openai":
            logger.info(f"Multipage PDF ({len(image_paths)} pages): using OpenAI pipeline")
            combined_receipt, ocr_error = await process_multipage_pdf_openai(image_paths, filename)

            if ocr_error or not combined_receipt:
                error_msg = ocr_error or "OpenAI OCR returned no data"
                logger.error(f"OpenAI OCR failed for {filename}: {error_msg}")
                error_file = write_error_file(filename, error_msg)
                log_error(filename, error_msg)
                return ProcessingResult(
                    success=False,
                    source_file=filename,
                    output_file=str(error_file),
                    error=error_msg,
                    processed_at=processed_at
                )

            # Skip the per-page processing loop - go directly to categorization
            all_products = combined_receipt.products
            page_results = []  # Empty - not used in unified mode

        # LEGACY: Per-page processing (for single pages or non-deepseek/google backends)
        elif len(image_paths) > 1 and settings.PDF_MAX_PARALLEL_PAGES > 1:
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

            # For multi-page PDFs with LEGACY per-page processing, re-extract total
            # Skip this for unified mode (deepseek multipage) - already handled
            is_unified_mode = len(image_paths) > 1 and settings.OCR_BACKEND in ("deepseek", "google", "openai")

            if len(image_paths) > 1 and all_raw_texts and not is_unified_mode:
                combined_raw_text = "\n".join(all_raw_texts)
                combined_receipt.raw_text = combined_raw_text

                # Try to extract final payment total from combined text
                # extract_total_from_text works for both vision and paddle backends
                final_total = extract_total_from_text(combined_raw_text)
                if final_total:
                    logger.info(f"Multi-page PDF: extracted payment total {final_total} from combined text")
                    combined_receipt.suma = final_total
                else:
                    # For vision backend, raw_text is JSON not receipt text
                    # Fall back to suma from last page that has it
                    last_page_suma = None
                    for page_num in reversed(range(len(page_results))):
                        page_receipt, _ = page_results[page_num]
                        if page_receipt and page_receipt.suma:
                            last_page_suma = page_receipt.suma
                            break

                    if last_page_suma and abs(last_page_suma - calculated_total) < abs(calculated_total * 0.15):
                        # Use last page suma if it's reasonably close to calculated
                        logger.info(f"Multi-page PDF: using last page suma {last_page_suma} (calculated: {calculated_total})")
                        combined_receipt.suma = last_page_suma
                    else:
                        logger.warning(f"Multi-page PDF: no reliable total found, using calculated sum {calculated_total}")
                        combined_receipt.suma = calculated_total

            # Fallback: if no total set, use calculated
            if not combined_receipt.suma:
                combined_receipt.suma = calculated_total

            # Validate total against sum of products
            # Skip for unified mode - already validated by confidence_scoring
            if combined_receipt.suma and calculated_total and not is_unified_mode:
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

        # Models are unloaded after categorization (in parallel) if UNLOAD_MODELS_AFTER_USE=true

        # Step 2: Categorize
        logger.info(f"Categorizing {len(receipt.products)} products")
        categorized, cat_error = await categorize_products(receipt.products)

        if cat_error:
            logger.warning(f"Categorization warning: {cat_error}")

        # Optionally unload ALL models in parallel (saves ~1-2s vs sequential)
        # Skip for OpenAI backend - no local models to unload
        if settings.UNLOAD_MODELS_AFTER_USE and settings.OCR_BACKEND != "openai":
            models_to_unload = [settings.OCR_MODEL, settings.CLASSIFIER_MODEL]
            # Remove duplicates (e.g., if both use same model)
            models_to_unload = list(set(models_to_unload))
            await asyncio.gather(*[
                ollama_client.unload_model(model) for model in models_to_unload
            ])
            logger.debug(f"Unloaded models in parallel: {models_to_unload}")

        # Step 3: Save to database
        receipt_file = None
        db_receipt_id = None
        if settings.USE_DB_RECEIPTS:
            db_receipt_id = await save_receipt_to_db(receipt, categorized, filename)
            if not db_receipt_id:
                error_msg = "Failed to save receipt to database"
                logger.error(error_msg)
                log_error(filename, error_msg)
                return ProcessingResult(
                    success=False,
                    receipt=receipt,
                    source_file=filename,
                    error=error_msg,
                    processed_at=processed_at
                )

        # Step 3b: Write Obsidian markdown
        receipt_path = write_receipt_to_obsidian(receipt, categorized, filename)
        if receipt_path:
            receipt_file = str(receipt_path)

        # Step 3c: RAG indexing
        if db_receipt_id:
            await index_receipt_in_rag(db_receipt_id)

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
    """Root endpoint - redirect to web UI."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/app/")


# --- PWA Endpoints ---

@app.get("/sw.js")
async def service_worker():
    """Serve Service Worker with correct scope header."""
    from fastapi.responses import FileResponse
    return FileResponse(
        Path(__file__).parent / "static" / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"}
    )


@app.get("/offline.html")
async def offline_page(request: Request):
    """Offline fallback page for PWA."""
    return _auth_templates.TemplateResponse("offline.html", {"request": request})


# --- Obsidian Sync Endpoints ---

@app.post("/obsidian/sync/receipt/{receipt_id}")
async def sync_receipt(receipt_id: UUID):
    """Regenerate markdown file for a specific receipt."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    path = await obsidian_sync.regenerate_receipt(receipt_id)
    if not path:
        raise HTTPException(status_code=404, detail="Receipt not found")

    return {"success": True, "file": str(path)}


@app.post("/obsidian/sync/pantry")
async def sync_pantry():
    """Regenerate spiżarnia.md from database."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    path = await obsidian_sync.regenerate_pantry()
    return {"success": True, "file": str(path)}


@app.post("/obsidian/sync/all")
async def sync_all():
    """Full regeneration of all Obsidian vault files."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    result = await obsidian_sync.full_regenerate()
    return {"success": True, **result}


# --- Analytics Endpoints ---

@app.get("/analytics/price-trends/{product_id}")
async def get_price_trends(
    product_id: int,
    months: int = 6,
    repo: AnalyticsRepoDep = None
):
    """Get price history for a product."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    trends = await repo.get_price_trends(product_id, months)
    return {"product_id": product_id, "months": months, "trends": trends}


@app.get("/analytics/store-comparison")
async def get_store_comparison(
    product_ids: str,
    repo: AnalyticsRepoDep = None
):
    """Compare prices across stores for given products."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    ids = [int(x.strip()) for x in product_ids.split(",") if x.strip().isdigit()]
    if not ids:
        raise HTTPException(status_code=400, detail="No valid product IDs provided")

    comparison = await repo.get_store_comparison(ids)
    return {"product_ids": ids, "comparison": comparison}


@app.get("/analytics/spending/by-category")
async def get_spending_by_category(
    start: Optional[date] = None,
    end: Optional[date] = None,
    repo: AnalyticsRepoDep = None
):
    """Get spending breakdown by category."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    spending = await repo.get_spending_by_category(start, end)
    return {"start": start, "end": end, "spending": spending}


@app.get("/analytics/spending/by-store")
async def get_spending_by_store(
    start: Optional[date] = None,
    end: Optional[date] = None,
    repo: AnalyticsRepoDep = None
):
    """Get spending breakdown by store."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    spending = await repo.get_spending_by_store(start, end)
    return {"start": start, "end": end, "spending": spending}


@app.get("/analytics/basket-analysis")
async def get_basket_analysis(
    min_support: float = 0.1,
    repo: AnalyticsRepoDep = None
):
    """Get frequently bought together products."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    analysis = await repo.get_basket_analysis(min_support)
    return {"min_support": min_support, "pairs": analysis}


@app.get("/analytics/top-products")
async def get_top_products(
    limit: int = 20,
    by: str = "count",
    repo: AnalyticsRepoDep = None
):
    """Get top products by purchase count or spending."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    if by not in ("count", "spending"):
        raise HTTPException(status_code=400, detail="by must be 'count' or 'spending'")

    products = await repo.get_top_products(limit, by)
    return {"limit": limit, "by": by, "products": products}


@app.get("/analytics/discounts")
async def get_discount_summary(
    start: Optional[date] = None,
    end: Optional[date] = None,
    repo: AnalyticsRepoDep = None
):
    """Get discount statistics."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    summary = await repo.get_discount_summary(start, end)
    return {"start": start, "end": end, "summary": summary}


@app.get("/analytics/yearly-comparison")
async def get_yearly_comparison(repo: AnalyticsRepoDep = None):
    """Get year-over-year spending comparison."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    comparison = await repo.get_yearly_comparison()
    return {"comparison": comparison}


# --- Database Statistics Endpoints ---

@app.get("/db/receipts/stats")
async def get_receipt_stats(repo: ReceiptRepoDep = None):
    """Get receipt statistics from database."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    stats = await repo.get_summary_stats()
    return stats


@app.get("/db/receipts/pending")
async def get_pending_receipts(repo: ReceiptRepoDep = None):
    """Get receipts pending review."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    receipts = await repo.get_pending_review()
    return {
        "count": len(receipts),
        "receipts": [
            {
                "id": str(r.id),
                "source_file": r.source_file,
                "date": r.receipt_date.isoformat() if r.receipt_date else None,
                "store": r.store.name if r.store else r.store_raw,
                "total": float(r.total_final) if r.total_final else None,
                "review_reasons": r.review_reasons,
            }
            for r in receipts
        ]
    }


@app.get("/db/pantry/stats")
async def get_pantry_stats(repo: PantryRepoDep = None):
    """Get pantry statistics from database."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    stats = await repo.get_stats()
    return stats


@app.get("/db/feedback/stats")
async def get_feedback_stats(repo: FeedbackRepoDep = None):
    """Get feedback statistics (unmatched products, corrections)."""
    if not settings.USE_DB_RECEIPTS:
        raise HTTPException(status_code=400, detail="Database not enabled")

    unmatched = await repo.get_unmatched_stats()
    corrections = await repo.get_correction_stats()
    return {"unmatched": unmatched, "corrections": corrections}
