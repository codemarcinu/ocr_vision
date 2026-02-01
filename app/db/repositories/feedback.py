"""Feedback repository for unmatched products and review corrections."""

from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Product, ReviewCorrection, Store, UnmatchedProduct
from app.db.repositories.base import BaseRepository


class FeedbackRepository(BaseRepository[UnmatchedProduct]):
    """Repository for feedback operations (unmatched products, corrections)."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, UnmatchedProduct)

    # --- Unmatched Products ---

    async def log_unmatched(
        self,
        raw_name: str,
        price: Optional[Decimal] = None,
        store_id: Optional[int] = None,
    ) -> UnmatchedProduct:
        """Log an unmatched product (increment count if exists)."""
        # Normalize name for deduplication
        normalized = raw_name.lower().strip()

        # Check if already exists
        stmt = select(UnmatchedProduct).where(
            UnmatchedProduct.raw_name_normalized == normalized
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        today = date.today()

        if existing:
            existing.occurrence_count += 1
            existing.last_seen = today
            if price and (not existing.price or price != existing.price):
                existing.price = price
            await self.session.flush()
            await self.session.refresh(existing)
            return existing

        # Create new entry
        unmatched = UnmatchedProduct(
            raw_name=raw_name,
            raw_name_normalized=normalized,
            price=price,
            store_id=store_id,
            first_seen=today,
            last_seen=today,
            occurrence_count=1,
        )
        self.session.add(unmatched)
        await self.session.flush()
        await self.session.refresh(unmatched)
        return unmatched

    async def get_unmatched(
        self,
        include_learned: bool = False,
        limit: int = 100,
    ) -> List[UnmatchedProduct]:
        """Get unmatched products sorted by occurrence count."""
        stmt = (
            select(UnmatchedProduct)
            .options(selectinload(UnmatchedProduct.store))
        )
        if not include_learned:
            stmt = stmt.where(UnmatchedProduct.is_learned == False)
        stmt = stmt.order_by(
            UnmatchedProduct.occurrence_count.desc(),
            UnmatchedProduct.last_seen.desc(),
        ).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_suggestions(self, min_count: int = 3) -> List[UnmatchedProduct]:
        """Get high-frequency unmatched products (suggestions for learning)."""
        stmt = (
            select(UnmatchedProduct)
            .options(selectinload(UnmatchedProduct.store))
            .where(
                UnmatchedProduct.is_learned == False,
                UnmatchedProduct.occurrence_count >= min_count,
            )
            .order_by(
                UnmatchedProduct.occurrence_count.desc(),
                UnmatchedProduct.last_seen.desc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_as_learned(
        self, unmatched_id: int, product_id: int
    ) -> Optional[UnmatchedProduct]:
        """Mark an unmatched product as learned."""
        unmatched = await self.get_by_id(unmatched_id)
        if not unmatched:
            return None

        unmatched.is_learned = True
        unmatched.learned_product_id = product_id
        await self.session.flush()
        await self.session.refresh(unmatched)
        return unmatched

    async def learn_product(
        self,
        raw_name: str,
        product_id: int,
    ) -> Optional[UnmatchedProduct]:
        """Learn from unmatched by raw name."""
        normalized = raw_name.lower().strip()
        stmt = select(UnmatchedProduct).where(
            UnmatchedProduct.raw_name_normalized == normalized
        )
        result = await self.session.execute(stmt)
        unmatched = result.scalar_one_or_none()

        if unmatched:
            unmatched.is_learned = True
            unmatched.learned_product_id = product_id
            await self.session.flush()
            await self.session.refresh(unmatched)
            return unmatched
        return None

    async def get_unmatched_stats(self) -> dict:
        """Get statistics about unmatched products."""
        stmt = text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE is_learned = TRUE) as learned,
                COUNT(*) FILTER (WHERE is_learned = FALSE) as unlearned,
                COUNT(*) FILTER (
                    WHERE is_learned = FALSE AND occurrence_count >= 3
                ) as suggestions,
                SUM(occurrence_count) FILTER (WHERE is_learned = FALSE) as total_occurrences
            FROM unmatched_products
        """)
        result = await self.session.execute(stmt)
        row = result.fetchone()
        return {
            "total": row.total or 0,
            "learned": row.learned or 0,
            "unlearned": row.unlearned or 0,
            "suggestions": row.suggestions or 0,
            "total_occurrences": row.total_occurrences or 0,
        }

    # --- Review Corrections ---

    async def log_correction(
        self,
        receipt_id: Optional[UUID],
        original_total: Optional[Decimal],
        corrected_total: Decimal,
        correction_type: str,
        store_id: Optional[int] = None,
        product_count: Optional[int] = None,
    ) -> ReviewCorrection:
        """Log a review correction."""
        correction = ReviewCorrection(
            receipt_id=receipt_id,
            original_total=original_total,
            corrected_total=corrected_total,
            correction_type=correction_type,
            store_id=store_id,
            product_count=product_count,
        )
        self.session.add(correction)
        await self.session.flush()
        await self.session.refresh(correction)
        return correction

    async def get_corrections(
        self, limit: int = 100
    ) -> List[ReviewCorrection]:
        """Get recent corrections."""
        stmt = (
            select(ReviewCorrection)
            .options(
                selectinload(ReviewCorrection.store),
                selectinload(ReviewCorrection.receipt),
            )
            .order_by(ReviewCorrection.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_correction_stats(self) -> dict:
        """Get correction statistics."""
        stmt = text("""
            SELECT
                correction_type,
                COUNT(*) as count,
                AVG(ABS(corrected_total - original_total)) as avg_difference
            FROM review_corrections
            WHERE original_total IS NOT NULL
            GROUP BY correction_type
        """)
        result = await self.session.execute(stmt)
        stats_by_type = {}
        for row in result.fetchall():
            stats_by_type[row.correction_type] = {
                "count": row.count,
                "avg_difference": float(row.avg_difference) if row.avg_difference else 0,
            }

        # Overall stats
        overall_stmt = text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE correction_type = 'approved') as approved,
                COUNT(*) FILTER (WHERE correction_type = 'calculated') as calculated,
                COUNT(*) FILTER (WHERE correction_type = 'manual') as manual,
                COUNT(*) FILTER (WHERE correction_type = 'rejected') as rejected,
                AVG(ABS(corrected_total - original_total))
                    FILTER (WHERE original_total IS NOT NULL) as avg_difference
            FROM review_corrections
        """)
        overall_result = await self.session.execute(overall_stmt)
        overall = overall_result.fetchone()

        return {
            "total": overall.total or 0,
            "by_type": stats_by_type,
            "approved": overall.approved or 0,
            "calculated": overall.calculated or 0,
            "manual": overall.manual or 0,
            "rejected": overall.rejected or 0,
            "avg_difference": float(overall.avg_difference) if overall.avg_difference else 0,
        }

    async def get_store_correction_stats(self) -> List[dict]:
        """Get correction statistics per store."""
        stmt = text("""
            SELECT
                s.name as store,
                COUNT(*) as total_corrections,
                COUNT(*) FILTER (WHERE correction_type = 'approved') as approved,
                COUNT(*) FILTER (WHERE correction_type != 'approved') as modified,
                AVG(ABS(corrected_total - original_total))
                    FILTER (WHERE original_total IS NOT NULL) as avg_difference
            FROM review_corrections rc
            JOIN stores s ON rc.store_id = s.id
            GROUP BY s.id, s.name
            ORDER BY total_corrections DESC
        """)
        result = await self.session.execute(stmt)
        return [
            {
                "store": row.store,
                "total_corrections": row.total_corrections,
                "approved": row.approved,
                "modified": row.modified,
                "avg_difference": float(row.avg_difference) if row.avg_difference else 0,
            }
            for row in result.fetchall()
        ]
