"""Receipt repository for storing and querying receipts."""

from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Category,
    PriceHistory,
    Receipt,
    ReceiptItem,
    Store,
)
from app.db.repositories.base import BaseRepository


class ReceiptRepository(BaseRepository[Receipt]):
    """Repository for receipt operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Receipt)

    async def get_by_source_file(self, source_file: str) -> Optional[Receipt]:
        """Get receipt by source file name."""
        stmt = select(Receipt).where(Receipt.source_file == source_file)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_items(self, receipt_id: UUID) -> Optional[Receipt]:
        """Get receipt with all items loaded."""
        stmt = (
            select(Receipt)
            .options(
                selectinload(Receipt.items).selectinload(ReceiptItem.category),
                selectinload(Receipt.items).selectinload(ReceiptItem.product),
                selectinload(Receipt.store),
            )
            .where(Receipt.id == receipt_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_recent(
        self, limit: int = 10, include_items: bool = False
    ) -> List[Receipt]:
        """Get most recent receipts."""
        if include_items:
            stmt = (
                select(Receipt)
                .options(
                    selectinload(Receipt.items),
                    selectinload(Receipt.store),
                )
                .order_by(Receipt.receipt_date.desc(), Receipt.processed_at.desc())
                .limit(limit)
            )
        else:
            stmt = (
                select(Receipt)
                .options(selectinload(Receipt.store))
                .order_by(Receipt.receipt_date.desc(), Receipt.processed_at.desc())
                .limit(limit)
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_review(self) -> List[Receipt]:
        """Get receipts pending human review."""
        stmt = (
            select(Receipt)
            .options(
                selectinload(Receipt.items),
                selectinload(Receipt.store),
            )
            .where(Receipt.needs_review == True)
            .order_by(Receipt.processed_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_date_range(
        self, start_date: date, end_date: date
    ) -> List[Receipt]:
        """Get receipts within date range."""
        stmt = (
            select(Receipt)
            .options(selectinload(Receipt.store))
            .where(
                Receipt.receipt_date >= start_date,
                Receipt.receipt_date <= end_date,
            )
            .order_by(Receipt.receipt_date.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_store(
        self, store_id: int, limit: int = 50
    ) -> List[Receipt]:
        """Get receipts from a specific store."""
        stmt = (
            select(Receipt)
            .options(selectinload(Receipt.items))
            .where(Receipt.store_id == store_id)
            .order_by(Receipt.receipt_date.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_receipt(
        self,
        source_file: str,
        receipt_date: date,
        store_id: Optional[int] = None,
        store_raw: Optional[str] = None,
        total_ocr: Optional[Decimal] = None,
        total_calculated: Optional[Decimal] = None,
        total_final: Optional[Decimal] = None,
        raw_text: Optional[str] = None,
        needs_review: bool = False,
        review_reasons: Optional[List[str]] = None,
    ) -> Receipt:
        """Create a new receipt."""
        receipt = Receipt(
            source_file=source_file,
            receipt_date=receipt_date,
            store_id=store_id,
            store_raw=store_raw,
            total_ocr=total_ocr,
            total_calculated=total_calculated,
            total_final=total_final,
            raw_text=raw_text,
            needs_review=needs_review,
            review_reasons=review_reasons or [],
        )
        self.session.add(receipt)
        await self.session.flush()
        await self.session.refresh(receipt)
        return receipt

    async def add_item(
        self,
        receipt_id: UUID,
        name_raw: str,
        price_final: Decimal,
        product_id: Optional[int] = None,
        name_normalized: Optional[str] = None,
        price_original: Optional[Decimal] = None,
        discount_amount: Optional[Decimal] = None,
        discount_details: Optional[list] = None,
        category_id: Optional[int] = None,
        confidence: Optional[Decimal] = None,
        warning: Optional[str] = None,
        match_method: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> ReceiptItem:
        """Add an item to a receipt."""
        item = ReceiptItem(
            receipt_id=receipt_id,
            product_id=product_id,
            name_raw=name_raw,
            name_normalized=name_normalized,
            price_final=price_final,
            price_original=price_original,
            discount_amount=discount_amount,
            discount_details=discount_details or [],
            category_id=category_id,
            confidence=confidence,
            warning=warning,
            match_method=match_method,
            metadata=metadata or {},
        )
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def add_items_batch(
        self, receipt_id: UUID, items: List[dict]
    ) -> List[ReceiptItem]:
        """Add multiple items to a receipt in batch."""
        receipt_items = []
        for item_data in items:
            item = ReceiptItem(
                receipt_id=receipt_id,
                product_id=item_data.get("product_id"),
                name_raw=item_data["name_raw"],
                name_normalized=item_data.get("name_normalized"),
                price_final=item_data["price_final"],
                price_original=item_data.get("price_original"),
                discount_amount=item_data.get("discount_amount"),
                discount_details=item_data.get("discount_details", []),
                category_id=item_data.get("category_id"),
                confidence=item_data.get("confidence"),
                warning=item_data.get("warning"),
                match_method=item_data.get("match_method"),
                metadata=item_data.get("metadata", {}),
            )
            self.session.add(item)
            receipt_items.append(item)

        await self.session.flush()
        for item in receipt_items:
            await self.session.refresh(item)
        return receipt_items

    async def update_review_status(
        self,
        receipt_id: UUID,
        needs_review: bool = False,
        total_final: Optional[Decimal] = None,
    ) -> Optional[Receipt]:
        """Update receipt review status."""
        receipt = await self.get_by_id(receipt_id)
        if not receipt:
            return None

        receipt.needs_review = needs_review
        if total_final is not None:
            receipt.total_final = total_final

        await self.session.flush()
        await self.session.refresh(receipt)
        return receipt

    async def record_price_history(
        self, receipt_id: UUID, store_id: Optional[int] = None
    ) -> int:
        """Record price history for all items in a receipt."""
        receipt = await self.get_with_items(receipt_id)
        if not receipt:
            return 0

        count = 0
        for item in receipt.items:
            if item.product_id:
                price_record = PriceHistory(
                    product_id=item.product_id,
                    store_id=store_id or receipt.store_id,
                    price=item.price_final,
                    receipt_id=receipt_id,
                    recorded_date=receipt.receipt_date,
                )
                self.session.add(price_record)
                count += 1

        await self.session.flush()
        return count

    async def get_summary_stats(self) -> dict:
        """Get overall receipt statistics."""
        stmt = text("""
            SELECT
                COUNT(*) as total_receipts,
                COALESCE(SUM(total_final), 0) as total_spent,
                COALESCE(AVG(total_final), 0) as avg_receipt,
                MIN(receipt_date) as first_receipt,
                MAX(receipt_date) as last_receipt
            FROM receipts
        """)
        result = await self.session.execute(stmt)
        row = result.fetchone()
        return {
            "total_receipts": row.total_receipts,
            "total_spent": float(row.total_spent) if row.total_spent else 0,
            "avg_receipt": float(row.avg_receipt) if row.avg_receipt else 0,
            "first_receipt": row.first_receipt.isoformat() if row.first_receipt else None,
            "last_receipt": row.last_receipt.isoformat() if row.last_receipt else None,
        }

    async def get_recent_paginated(
        self,
        limit: int = 20,
        offset: int = 0,
        store_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> tuple[List[Receipt], int]:
        """Get receipts with pagination and filters. Returns (items, total_count)."""
        # Count query
        count_stmt = select(func.count(Receipt.id))
        if store_id:
            count_stmt = count_stmt.where(Receipt.store_id == store_id)
        if date_from:
            count_stmt = count_stmt.where(Receipt.receipt_date >= date_from)
        if date_to:
            count_stmt = count_stmt.where(Receipt.receipt_date <= date_to)
        total = await self.session.execute(count_stmt)
        total_count = total.scalar() or 0

        # Data query
        stmt = (
            select(Receipt)
            .options(selectinload(Receipt.store))
            .order_by(Receipt.receipt_date.desc(), Receipt.processed_at.desc())
        )
        if store_id:
            stmt = stmt.where(Receipt.store_id == store_id)
        if date_from:
            stmt = stmt.where(Receipt.receipt_date >= date_from)
        if date_to:
            stmt = stmt.where(Receipt.receipt_date <= date_to)
        stmt = stmt.offset(offset).limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total_count

    async def update_item(
        self, item_id: int, **kwargs
    ) -> Optional[ReceiptItem]:
        """Update a receipt item."""
        stmt = select(ReceiptItem).where(ReceiptItem.id == item_id)
        result = await self.session.execute(stmt)
        item = result.scalar_one_or_none()
        if not item:
            return None

        for key, value in kwargs.items():
            if hasattr(item, key) and value is not None:
                setattr(item, key, value)

        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def get_monthly_spending(
        self, months: int = 12
    ) -> List[dict]:
        """Get monthly spending summary."""
        stmt = text("""
            SELECT
                DATE_TRUNC('month', receipt_date) as month,
                COUNT(*) as receipt_count,
                COALESCE(SUM(total_final), 0) as total_spent
            FROM receipts
            WHERE receipt_date >= NOW() - INTERVAL ':months months'
            GROUP BY DATE_TRUNC('month', receipt_date)
            ORDER BY month DESC
        """.replace(":months", str(months)))
        result = await self.session.execute(stmt)
        return [
            {
                "month": row.month.isoformat() if row.month else None,
                "receipt_count": row.receipt_count,
                "total_spent": float(row.total_spent) if row.total_spent else 0,
            }
            for row in result.fetchall()
        ]
