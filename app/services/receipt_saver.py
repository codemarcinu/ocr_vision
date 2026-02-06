"""Save processed receipt data to the database."""

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connection import get_session_context
from app.db.models import Category
from app.db.repositories.pantry import PantryRepository
from app.db.repositories.receipts import ReceiptRepository
from app.db.repositories.stores import StoreRepository
from app.models import CategorizedProduct, Receipt

logger = logging.getLogger(__name__)


async def _resolve_category_id(
    session: AsyncSession, category_name: str
) -> Optional[int]:
    """Resolve category name to category_id."""
    if not category_name:
        return None
    stmt = select(Category).where(Category.name == category_name)
    result = await session.execute(stmt)
    cat = result.scalar_one_or_none()
    if cat:
        return cat.id
    # Try matching by key (lowercase, no diacritics)
    stmt = select(Category).where(Category.key == category_name.lower())
    result = await session.execute(stmt)
    cat = result.scalar_one_or_none()
    if cat:
        return cat.id
    return None


async def save_receipt_to_db(
    receipt: Receipt,
    categorized: List[CategorizedProduct],
    filename: str,
) -> Optional[UUID]:
    """
    Save a processed receipt and its items to the database.

    Args:
        receipt: Processing model with OCR results
        categorized: List of categorized products
        filename: Source file name

    Returns:
        UUID of the created receipt, or None on failure
    """
    try:
        async with get_session_context() as session:
            receipt_repo = ReceiptRepository(session)
            store_repo = StoreRepository(session)

            # Resolve store
            store_id = None
            if receipt.sklep:
                store = await store_repo.normalize_store(receipt.sklep)
                if not store:
                    store = await store_repo.get_or_create(receipt.sklep)
                store_id = store.id

            # Parse receipt date
            receipt_date = None
            if receipt.data:
                try:
                    receipt_date = date.fromisoformat(receipt.data)
                except ValueError:
                    logger.warning(f"Invalid date format: {receipt.data}")
            if not receipt_date:
                receipt_date = date.today()

            # Determine totals
            total_ocr = Decimal(str(receipt.suma)) if receipt.suma else None
            calculated_total = receipt.calculated_total or sum(
                p.cena for p in categorized
            )
            total_calculated = Decimal(str(calculated_total)) if calculated_total else None
            total_final = total_ocr or total_calculated

            # Create receipt record
            db_receipt = await receipt_repo.create_receipt(
                source_file=filename,
                receipt_date=receipt_date,
                store_id=store_id,
                store_raw=receipt.sklep,
                total_ocr=total_ocr,
                total_calculated=total_calculated,
                total_final=total_final,
                raw_text=receipt.raw_text,
                needs_review=receipt.needs_review,
                review_reasons=receipt.review_reasons,
            )

            # Build items for batch insert
            items_data = []
            for product in categorized:
                category_id = await _resolve_category_id(
                    session, product.kategoria
                )
                discount_details = None
                if product.rabaty_szczegoly:
                    discount_details = [
                        d.model_dump() if hasattr(d, "model_dump") else d
                        for d in product.rabaty_szczegoly
                    ]

                items_data.append({
                    "name_raw": product.nazwa_oryginalna or product.nazwa,
                    "name_normalized": product.nazwa_znormalizowana or product.nazwa,
                    "price_final": Decimal(str(product.cena)),
                    "price_original": (
                        Decimal(str(product.cena_oryginalna))
                        if product.cena_oryginalna
                        else None
                    ),
                    "discount_amount": (
                        Decimal(str(product.rabat))
                        if product.rabat
                        else None
                    ),
                    "discount_details": discount_details or [],
                    "category_id": category_id,
                    "confidence": (
                        Decimal(str(product.confidence))
                        if product.confidence is not None
                        else None
                    ),
                    "warning": product.warning if hasattr(product, "warning") else None,
                })

            if items_data:
                receipt_items = await receipt_repo.add_items_batch(db_receipt.id, items_data)

                # Add items to pantry
                pantry_repo = PantryRepository(session)
                pantry_items_data = []
                for ri in receipt_items:
                    pantry_items_data.append({
                        "receipt_item_id": ri.id,
                        "product_id": ri.product_id,
                        "name": ri.name_normalized or ri.name_raw,
                        "category_id": ri.category_id,
                        "store_id": store_id,
                        "purchase_date": receipt_date or date.today(),
                    })
                if pantry_items_data:
                    await pantry_repo.add_items_batch(pantry_items_data)
                    logger.info(f"Added {len(pantry_items_data)} items to pantry")

            logger.info(
                f"Saved receipt {db_receipt.id} to DB: "
                f"{len(items_data)} items, store={receipt.sklep}, "
                f"total={total_final}"
            )
            return db_receipt.id

    except Exception as e:
        logger.error(f"Failed to save receipt to DB: {e}", exc_info=True)
        return None


def write_receipt_to_obsidian(
    receipt: Receipt,
    categorized: List[CategorizedProduct],
    filename: str,
) -> Optional[Path]:
    """Write receipt markdown and update pantry file in Obsidian vault.

    Returns:
        Path to the created receipt file, or None if disabled/failed.
    """
    from app.config import settings

    if not settings.GENERATE_OBSIDIAN_FILES:
        return None

    try:
        from app.writers.obsidian import write_receipt_file, update_pantry_file

        receipt_path = write_receipt_file(receipt, categorized, filename)
        update_pantry_file(categorized, receipt)
        return receipt_path
    except Exception as e:
        logger.error(f"Failed to write Obsidian files for {filename}: {e}", exc_info=True)
        return None


async def index_receipt_in_rag(
    db_receipt_id: UUID,
) -> None:
    """Index a receipt in RAG for /ask searchability."""
    from app.config import settings

    if not settings.RAG_ENABLED or not settings.RAG_AUTO_INDEX:
        return

    try:
        from app.rag.hooks import index_receipt_hook
        from app.db.repositories.receipts import ReceiptRepository

        async with get_session_context() as session:
            repo = ReceiptRepository(session)
            db_receipt = await repo.get_with_items(db_receipt_id)
            if db_receipt:
                await index_receipt_hook(db_receipt, db_receipt.items, session)
                await session.commit()
    except Exception as e:
        logger.warning(f"RAG indexing failed for receipt {db_receipt_id}: {e}")
