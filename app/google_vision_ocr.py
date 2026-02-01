"""Google Cloud Vision OCR - ultimate fallback when local models fail.

This module provides OCR text extraction using Google Cloud Vision API.
It's designed as the last resort fallback when all local Ollama models fail.

Usage:
    from app.google_vision_ocr import ocr_with_google_vision

    text, error = await ocr_with_google_vision(image_path)
    if error:
        # Handle error
    else:
        # Use text with LLM structuring

Requirements:
    - GOOGLE_VISION_ENABLED=true in environment
    - GOOGLE_APPLICATION_CREDENTIALS pointing to service account JSON file
    - google-cloud-vision package installed

Cost: ~$1.50 per 1000 images (Document Text Detection)
"""

import logging
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


async def ocr_with_google_vision(image_path: Path) -> tuple[str, Optional[str]]:
    """
    Extract text from image using Google Cloud Vision API.

    This is the ultimate fallback - only called when all local models fail.
    Uses DOCUMENT_TEXT_DETECTION for better receipt/document handling.

    Args:
        image_path: Path to the image file (PNG, JPG, WEBP supported)

    Returns:
        Tuple (raw OCR text, error message or None)
    """
    if not settings.GOOGLE_VISION_ENABLED:
        return "", "Google Vision not enabled (set GOOGLE_VISION_ENABLED=true)"

    # Lazy import to avoid loading google-cloud-vision when not needed
    try:
        from google.cloud import vision
        from google.api_core import exceptions as google_exceptions
    except ImportError:
        logger.error("google-cloud-vision package not installed")
        return "", "google-cloud-vision not installed (pip install google-cloud-vision)"

    if not image_path.exists():
        return "", f"Image file not found: {image_path}"

    try:
        # Create client (uses GOOGLE_APPLICATION_CREDENTIALS automatically)
        client = vision.ImageAnnotatorClient()

        # Read image content
        with open(image_path, "rb") as f:
            content = f.read()

        image = vision.Image(content=content)

        logger.info(f"Google Vision: processing {image_path.name} ({len(content)} bytes)")

        # Use DOCUMENT_TEXT_DETECTION for better receipt handling
        # This provides better results for dense text and preserves layout
        response = client.document_text_detection(image=image)

        # Check for API errors
        if response.error.message:
            logger.error(f"Google Vision API error: {response.error.message}")
            return "", f"Google Vision API error: {response.error.message}"

        # Get full text annotation (preserves layout better than text_annotations)
        if not response.full_text_annotation:
            logger.warning("Google Vision returned no text annotation")
            return "", "Google Vision returned no text"

        text = response.full_text_annotation.text

        if not text or not text.strip():
            logger.warning("Google Vision returned empty text")
            return "", "Google Vision returned empty text"

        logger.info(f"Google Vision extracted {len(text)} chars from {image_path.name}")
        logger.debug(f"Google Vision text preview: {text[:500]}")

        return text, None

    except google_exceptions.PermissionDenied as e:
        logger.error(f"Google Vision permission denied: {e}")
        return "", f"Google Vision permission denied - check service account permissions: {e}"

    except google_exceptions.InvalidArgument as e:
        logger.error(f"Google Vision invalid argument: {e}")
        return "", f"Google Vision invalid argument (unsupported image format?): {e}"

    except google_exceptions.ResourceExhausted as e:
        logger.error(f"Google Vision quota exceeded: {e}")
        return "", f"Google Vision quota exceeded: {e}"

    except google_exceptions.GoogleAPICallError as e:
        logger.error(f"Google Vision API call error: {e}")
        return "", f"Google Vision API error: {e}"

    except FileNotFoundError:
        return "", f"Image file not found: {image_path}"

    except Exception as e:
        logger.error(f"Google Vision unexpected exception: {type(e).__name__}: {e}")
        return "", f"Google Vision exception: {type(e).__name__}: {e}"


async def ocr_pdf_with_google_vision(pdf_path: Path) -> tuple[str, Optional[str]]:
    """
    Extract text from PDF using Google Cloud Vision API.

    For multi-page PDFs, processes each page and combines text.
    Note: This requires pdf2image to convert PDF to images first.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Tuple (combined raw OCR text, error message or None)
    """
    if not settings.GOOGLE_VISION_ENABLED:
        return "", "Google Vision not enabled"

    if not pdf_path.exists():
        return "", f"PDF file not found: {pdf_path}"

    if pdf_path.suffix.lower() != ".pdf":
        return "", f"Not a PDF file: {pdf_path}"

    try:
        from pdf2image import convert_from_path
        import tempfile
        import os

        logger.info(f"Google Vision: converting PDF {pdf_path.name} to images")

        # Convert PDF to images
        images = convert_from_path(pdf_path, dpi=200)

        if not images:
            return "", "PDF conversion returned no images"

        logger.info(f"Google Vision: PDF has {len(images)} pages")

        # Process each page
        page_texts = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, image in enumerate(images):
                # Save page as PNG
                page_path = Path(tmpdir) / f"page_{i+1}.png"
                image.save(page_path, "PNG")

                # OCR the page
                text, error = await ocr_with_google_vision(page_path)

                if error:
                    logger.warning(f"Google Vision failed on page {i+1}: {error}")
                    page_texts.append(f"[PAGE {i+1} - OCR ERROR: {error}]")
                elif text.strip():
                    page_texts.append(f"--- PAGE {i+1}/{len(images)} ---\n{text}")
                else:
                    page_texts.append(f"[PAGE {i+1} - EMPTY]")

        # Combine all pages
        combined_text = "\n\n".join(page_texts)

        if not combined_text.strip():
            return "", "Google Vision returned no text from any page"

        logger.info(f"Google Vision PDF: {len(combined_text)} total chars from {len(images)} pages")
        return combined_text, None

    except ImportError:
        return "", "pdf2image not installed (required for PDF processing)"

    except Exception as e:
        logger.error(f"Google Vision PDF exception: {type(e).__name__}: {e}")
        return "", f"Google Vision PDF exception: {type(e).__name__}: {e}"
