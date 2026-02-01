"""PDF to image conversion for Smart Pantry Tracker."""

import logging
from pathlib import Path

from pdf2image import convert_from_path

logger = logging.getLogger(__name__)


def convert_pdf_to_images(pdf_path: Path, dpi: int = 200) -> list[Path]:
    """
    Convert a PDF file to a list of PNG images (one per page).

    Args:
        pdf_path: Path to the PDF file
        dpi: Resolution for conversion (default 200 - good balance of quality/size)

    Returns:
        List of paths to created PNG images (e.g., receipt_page1.png, receipt_page2.png)
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    logger.info(f"Converting PDF to images: {pdf_path}")

    # Convert PDF to list of PIL images
    images = convert_from_path(pdf_path, dpi=dpi)

    output_paths: list[Path] = []
    stem = pdf_path.stem
    parent = pdf_path.parent

    for i, image in enumerate(images, start=1):
        output_path = parent / f"{stem}_page{i}.png"
        image.save(output_path, "PNG")
        output_paths.append(output_path)
        logger.info(f"Created page {i}: {output_path}")

    logger.info(f"PDF converted to {len(output_paths)} image(s)")
    return output_paths
