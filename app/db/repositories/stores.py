"""Store repository with alias support."""

from typing import List, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import ProductShortcut, Store, StoreAlias
from app.db.repositories.base import BaseRepository


class StoreRepository(BaseRepository[Store]):
    """Repository for store operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Store)

    async def get_by_name(self, name: str) -> Optional[Store]:
        """Get store by exact name."""
        stmt = select(Store).where(func.lower(Store.name) == name.lower())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_with_aliases(self) -> List[Store]:
        """Get all stores with their aliases."""
        stmt = (
            select(Store)
            .options(selectinload(Store.aliases))
            .order_by(Store.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def normalize_store(self, raw_name: str) -> Optional[Store]:
        """
        Normalize store name using aliases and fuzzy matching.

        Order of matching:
        1. Exact match on store name
        2. Exact match on alias
        3. Fuzzy match on alias using pg_trgm
        """
        clean_name = raw_name.lower().strip()
        if not clean_name:
            return None

        # 1. Exact match on store name
        store = await self.get_by_name(clean_name)
        if store:
            return store

        # 2. Exact match on alias
        stmt = (
            select(Store)
            .join(StoreAlias)
            .where(func.lower(StoreAlias.alias) == clean_name)
        )
        result = await self.session.execute(stmt)
        store = result.scalar_one_or_none()
        if store:
            return store

        # 3. Fuzzy match on alias
        stmt = text("""
            SELECT s.id, s.name, similarity(:query, sa.alias) as sim
            FROM stores s
            JOIN store_aliases sa ON s.id = sa.store_id
            WHERE similarity(:query, sa.alias) > 0.4
            ORDER BY sim DESC
            LIMIT 1
        """)
        result = await self.session.execute(stmt, {"query": clean_name})
        row = result.fetchone()
        if row:
            return await self.get_by_id(row.id)

        return None

    async def add_alias(self, store_id: int, alias: str) -> Optional[StoreAlias]:
        """Add an alias to a store."""
        # Check if alias already exists
        existing = await self.session.execute(
            select(StoreAlias).where(func.lower(StoreAlias.alias) == alias.lower())
        )
        if existing.scalar_one_or_none():
            return None

        store_alias = StoreAlias(store_id=store_id, alias=alias)
        self.session.add(store_alias)
        await self.session.flush()
        await self.session.refresh(store_alias)
        return store_alias

    async def get_or_create(self, name: str) -> Store:
        """Get existing store or create new one."""
        store = await self.get_by_name(name)
        if store:
            return store

        store = Store(name=name)
        self.session.add(store)
        await self.session.flush()
        await self.session.refresh(store)

        # Also add the name as an alias for fuzzy matching
        alias = StoreAlias(store_id=store.id, alias=name)
        self.session.add(alias)
        await self.session.flush()

        return store

    async def get_shortcuts(
        self, store_id: Optional[int] = None
    ) -> List[ProductShortcut]:
        """Get product shortcuts, optionally filtered by store."""
        stmt = select(ProductShortcut)
        if store_id:
            stmt = stmt.where(ProductShortcut.store_id == store_id)
        stmt = stmt.order_by(ProductShortcut.shortcut)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_shortcut(
        self, store_id: int, shortcut: str, full_name: str
    ) -> Optional[ProductShortcut]:
        """Add a product shortcut for a store."""
        # Check if shortcut already exists for this store
        existing = await self.session.execute(
            select(ProductShortcut).where(
                ProductShortcut.store_id == store_id,
                func.lower(ProductShortcut.shortcut) == shortcut.lower(),
            )
        )
        if existing.scalar_one_or_none():
            return None

        product_shortcut = ProductShortcut(
            store_id=store_id, shortcut=shortcut, full_name=full_name
        )
        self.session.add(product_shortcut)
        await self.session.flush()
        await self.session.refresh(product_shortcut)
        return product_shortcut

    async def delete_shortcut(self, store_id: int, shortcut: str) -> bool:
        """Delete a product shortcut."""
        stmt = select(ProductShortcut).where(
            ProductShortcut.store_id == store_id,
            func.lower(ProductShortcut.shortcut) == shortcut.lower(),
        )
        result = await self.session.execute(stmt)
        product_shortcut = result.scalar_one_or_none()
        if not product_shortcut:
            return False

        await self.session.delete(product_shortcut)
        await self.session.flush()
        return True

    async def get_store_stats(self) -> List[dict]:
        """Get statistics for all stores."""
        stmt = text("""
            SELECT
                s.id,
                s.name,
                COUNT(DISTINCT r.id) as receipt_count,
                COALESCE(SUM(r.total_final), 0) as total_spent,
                MAX(r.receipt_date) as last_visit
            FROM stores s
            LEFT JOIN receipts r ON s.id = r.store_id
            GROUP BY s.id, s.name
            ORDER BY total_spent DESC
        """)
        result = await self.session.execute(stmt)
        return [
            {
                "id": row.id,
                "name": row.name,
                "receipt_count": row.receipt_count,
                "total_spent": float(row.total_spent) if row.total_spent else 0,
                "last_visit": row.last_visit.isoformat() if row.last_visit else None,
            }
            for row in result.fetchall()
        ]
