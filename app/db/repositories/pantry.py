"""Pantry repository for managing pantry items."""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Category, PantryItem, Product, Store
from app.db.repositories.base import BaseRepository


class PantryRepository(BaseRepository[PantryItem]):
    """Repository for pantry operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, PantryItem)

    async def get_all_active(self) -> List[PantryItem]:
        """Get all non-consumed pantry items."""
        stmt = (
            select(PantryItem)
            .options(
                selectinload(PantryItem.category),
                selectinload(PantryItem.store),
                selectinload(PantryItem.product),
            )
            .where(PantryItem.is_consumed == False)
            .order_by(PantryItem.purchase_date.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_category(
        self, category_id: int, include_consumed: bool = False
    ) -> List[PantryItem]:
        """Get pantry items by category."""
        stmt = (
            select(PantryItem)
            .options(
                selectinload(PantryItem.store),
                selectinload(PantryItem.product),
            )
            .where(PantryItem.category_id == category_id)
        )
        if not include_consumed:
            stmt = stmt.where(PantryItem.is_consumed == False)
        stmt = stmt.order_by(PantryItem.purchase_date.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_grouped_by_category(self) -> dict:
        """Get all active pantry items grouped by category."""
        stmt = (
            select(PantryItem)
            .options(
                selectinload(PantryItem.category),
                selectinload(PantryItem.store),
            )
            .where(PantryItem.is_consumed == False)
            .order_by(PantryItem.category_id, PantryItem.name)
        )
        result = await self.session.execute(stmt)
        items = result.scalars().all()

        grouped = {}
        for item in items:
            category_name = item.category.name if item.category else "Inne"
            if category_name not in grouped:
                grouped[category_name] = []
            grouped[category_name].append(item)

        return grouped

    async def add_from_receipt(
        self,
        receipt_item_id: int,
        product_id: Optional[int],
        name: str,
        category_id: Optional[int],
        store_id: Optional[int],
        purchase_date: date,
        quantity: Decimal = Decimal("1.0"),
        expiry_date: Optional[date] = None,
    ) -> PantryItem:
        """Add an item to pantry from a receipt."""
        item = PantryItem(
            receipt_item_id=receipt_item_id,
            product_id=product_id,
            name=name,
            category_id=category_id,
            store_id=store_id,
            purchase_date=purchase_date,
            quantity=quantity,
            expiry_date=expiry_date,
        )
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def add_items_batch(self, items: List[dict]) -> List[PantryItem]:
        """Add multiple items to pantry in batch."""
        pantry_items = []
        for item_data in items:
            item = PantryItem(
                receipt_item_id=item_data.get("receipt_item_id"),
                product_id=item_data.get("product_id"),
                name=item_data["name"],
                category_id=item_data.get("category_id"),
                store_id=item_data.get("store_id"),
                purchase_date=item_data["purchase_date"],
                quantity=item_data.get("quantity", Decimal("1.0")),
                expiry_date=item_data.get("expiry_date"),
            )
            self.session.add(item)
            pantry_items.append(item)

        await self.session.flush()
        for item in pantry_items:
            await self.session.refresh(item)
        return pantry_items

    async def consume_item(self, item_id: int) -> Optional[PantryItem]:
        """Mark an item as consumed."""
        item = await self.get_by_id(item_id)
        if not item:
            return None

        item.is_consumed = True
        item.consumed_at = datetime.utcnow()
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def consume_items_batch(self, item_ids: List[int]) -> int:
        """Mark multiple items as consumed."""
        stmt = (
            update(PantryItem)
            .where(PantryItem.id.in_(item_ids))
            .values(is_consumed=True, consumed_at=datetime.utcnow())
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def restore_item(self, item_id: int) -> Optional[PantryItem]:
        """Restore a consumed item."""
        item = await self.get_by_id(item_id)
        if not item:
            return None

        item.is_consumed = False
        item.consumed_at = None
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def update_quantity(
        self, item_id: int, quantity: Decimal
    ) -> Optional[PantryItem]:
        """Update item quantity."""
        item = await self.get_by_id(item_id)
        if not item:
            return None

        item.quantity = quantity
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def search(
        self, query: str, include_consumed: bool = False, limit: int = 20
    ) -> List[PantryItem]:
        """Search pantry items by name."""
        stmt = text("""
            SELECT pi.id, similarity(:query, pi.name) as sim
            FROM pantry_items pi
            WHERE similarity(:query, pi.name) > 0.2
            ORDER BY sim DESC
            LIMIT :limit
        """)
        if not include_consumed:
            stmt = text("""
                SELECT pi.id, similarity(:query, pi.name) as sim
                FROM pantry_items pi
                WHERE similarity(:query, pi.name) > 0.2
                  AND pi.is_consumed = FALSE
                ORDER BY sim DESC
                LIMIT :limit
            """)
        result = await self.session.execute(
            stmt, {"query": query, "limit": limit}
        )
        ids = [row.id for row in result.fetchall()]

        if not ids:
            return []

        items_stmt = (
            select(PantryItem)
            .options(
                selectinload(PantryItem.category),
                selectinload(PantryItem.store),
            )
            .where(PantryItem.id.in_(ids))
        )
        items_result = await self.session.execute(items_stmt)
        return list(items_result.scalars().all())

    async def get_expiring_soon(self, days: int = 7) -> List[PantryItem]:
        """Get items expiring within specified days."""
        stmt = (
            select(PantryItem)
            .options(
                selectinload(PantryItem.category),
                selectinload(PantryItem.store),
            )
            .where(
                PantryItem.is_consumed == False,
                PantryItem.expiry_date != None,
                PantryItem.expiry_date <= func.current_date() + days,
            )
            .order_by(PantryItem.expiry_date)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_stats(self) -> dict:
        """Get pantry statistics."""
        stmt = text("""
            SELECT
                COUNT(*) FILTER (WHERE is_consumed = FALSE) as active_items,
                COUNT(*) FILTER (WHERE is_consumed = TRUE) as consumed_items,
                COUNT(DISTINCT category_id) FILTER (WHERE is_consumed = FALSE) as category_count,
                COUNT(*) FILTER (
                    WHERE is_consumed = FALSE
                    AND expiry_date IS NOT NULL
                    AND expiry_date <= CURRENT_DATE + 7
                ) as expiring_soon
            FROM pantry_items
        """)
        result = await self.session.execute(stmt)
        row = result.fetchone()
        return {
            "active_items": row.active_items or 0,
            "consumed_items": row.consumed_items or 0,
            "category_count": row.category_count or 0,
            "expiring_soon": row.expiring_soon or 0,
        }

    async def get_category_summary(self) -> List[dict]:
        """Get summary of items per category."""
        stmt = text("""
            SELECT
                c.name as category,
                COUNT(*) as item_count
            FROM pantry_items pi
            JOIN categories c ON pi.category_id = c.id
            WHERE pi.is_consumed = FALSE
            GROUP BY c.id, c.name
            ORDER BY item_count DESC
        """)
        result = await self.session.execute(stmt)
        return [
            {
                "category": row.category,
                "item_count": row.item_count,
            }
            for row in result.fetchall()
        ]
