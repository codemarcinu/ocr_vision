"""Product repository with fuzzy search using pg_trgm."""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Category, Product, ProductShortcut, ProductVariant, Store
from app.db.repositories.base import BaseRepository


@dataclass
class NormalizedProductResult:
    """Result of product normalization."""
    product_id: int
    normalized_name: str
    category: Optional[str]
    confidence: float
    match_method: str  # 'exact', 'shortcut', 'partial', 'fuzzy', 'keyword'


class ProductRepository(BaseRepository[Product]):
    """Repository for product dictionary operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Product)

    async def get_by_normalized_name(
        self, name: str, category_id: Optional[int] = None
    ) -> Optional[Product]:
        """Get product by normalized name."""
        stmt = select(Product).where(
            func.lower(Product.normalized_name) == name.lower()
        )
        if category_id:
            stmt = stmt.where(Product.category_id == category_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_with_variants(self) -> List[Product]:
        """Get all products with their variants loaded."""
        stmt = (
            select(Product)
            .options(selectinload(Product.variants), selectinload(Product.category))
            .order_by(Product.normalized_name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_variant(self, product_id: int, raw_name: str) -> Optional[ProductVariant]:
        """Add a new variant to a product."""
        # Check if variant already exists
        existing = await self.session.execute(
            select(ProductVariant).where(
                func.lower(ProductVariant.raw_name) == raw_name.lower()
            )
        )
        if existing.scalar_one_or_none():
            return None

        variant = ProductVariant(product_id=product_id, raw_name=raw_name)
        self.session.add(variant)
        await self.session.flush()
        await self.session.refresh(variant)
        return variant

    async def normalize_product(
        self, raw_name: str, store_name: Optional[str] = None
    ) -> Optional[NormalizedProductResult]:
        """
        Normalize product name using multiple matching strategies.

        Order of matching:
        1. Exact match in product_variants
        2. Shortcut match (store-specific)
        3. Partial match (word overlap)
        4. Fuzzy match using pg_trgm
        5. Keyword match
        """
        clean_name = self._clean_name(raw_name)
        if not clean_name or len(clean_name) < 3:
            return None

        # 1. Exact match
        result = await self._exact_match(clean_name)
        if result:
            return result

        # 2. Shortcut match (if store provided)
        if store_name:
            result = await self._shortcut_match(clean_name, store_name)
            if result:
                return result

        # 3. Partial match (word overlap)
        result = await self._partial_match(clean_name)
        if result:
            return result

        # 4. Fuzzy match with pg_trgm
        result = await self._fuzzy_match(clean_name)
        if result:
            return result

        # 5. Keyword match
        result = await self._keyword_match(clean_name)
        if result:
            return result

        return None

    def _clean_name(self, name: str) -> str:
        """Clean product name for matching."""
        # Remove common noise
        cleaned = name.lower().strip()
        # Remove quantities/weights
        cleaned = re.sub(r'\d+\s*(g|kg|ml|l|szt|x)\b', '', cleaned)
        # Remove special characters
        cleaned = re.sub(r'[^\w\sąćęłńóśźżĄĆĘŁŃÓŚŹŻ]', ' ', cleaned)
        # Normalize whitespace
        cleaned = ' '.join(cleaned.split())
        return cleaned

    async def _exact_match(self, clean_name: str) -> Optional[NormalizedProductResult]:
        """Exact match in product variants."""
        stmt = text("""
            SELECT p.id, p.normalized_name, c.key as category
            FROM product_variants pv
            JOIN products p ON pv.product_id = p.id
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE LOWER(pv.raw_name) = :query
            LIMIT 1
        """)
        result = await self.session.execute(stmt, {"query": clean_name})
        row = result.fetchone()
        if row:
            return NormalizedProductResult(
                product_id=row.id,
                normalized_name=row.normalized_name,
                category=row.category,
                confidence=0.99,
                match_method="exact"
            )
        return None

    async def _shortcut_match(
        self, clean_name: str, store_name: str
    ) -> Optional[NormalizedProductResult]:
        """Match against store-specific shortcuts."""
        stmt = text("""
            SELECT ps.full_name, s.name as store_name
            FROM product_shortcuts ps
            JOIN stores s ON ps.store_id = s.id
            WHERE LOWER(ps.shortcut) = :query
              AND LOWER(s.name) = :store
            LIMIT 1
        """)
        result = await self.session.execute(
            stmt, {"query": clean_name, "store": store_name.lower()}
        )
        row = result.fetchone()
        if row:
            # Now find the product for this full name
            return await self._exact_match(row.full_name.lower()) or \
                   await self._fuzzy_match(row.full_name.lower())
        return None

    async def _partial_match(self, clean_name: str) -> Optional[NormalizedProductResult]:
        """Partial match based on word overlap (70%+)."""
        words = set(clean_name.split())
        if len(words) < 2:
            return None

        # Use word_similarity for partial matching
        stmt = text("""
            SELECT p.id, p.normalized_name, c.key as category,
                   word_similarity(:query, pv.raw_name) as sim
            FROM product_variants pv
            JOIN products p ON pv.product_id = p.id
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE word_similarity(:query, pv.raw_name) > 0.5
            ORDER BY sim DESC
            LIMIT 1
        """)
        result = await self.session.execute(stmt, {"query": clean_name})
        row = result.fetchone()
        if row and row.sim >= 0.7:
            return NormalizedProductResult(
                product_id=row.id,
                normalized_name=row.normalized_name,
                category=row.category,
                confidence=float(row.sim) * 0.9,
                match_method="partial"
            )
        return None

    async def _fuzzy_match(self, clean_name: str) -> Optional[NormalizedProductResult]:
        """Fuzzy match using pg_trgm similarity."""
        stmt = text("""
            SELECT p.id, p.normalized_name, c.key as category,
                   similarity(:query, pv.raw_name) as sim
            FROM product_variants pv
            JOIN products p ON pv.product_id = p.id
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE similarity(:query, pv.raw_name) > 0.3
            ORDER BY sim DESC
            LIMIT 1
        """)
        result = await self.session.execute(stmt, {"query": clean_name})
        row = result.fetchone()
        if row:
            # Calculate confidence: 0.68-0.81 range for fuzzy
            confidence = 0.68 + (float(row.sim) - 0.3) * 0.26
            return NormalizedProductResult(
                product_id=row.id,
                normalized_name=row.normalized_name,
                category=row.category,
                confidence=min(confidence, 0.81),
                match_method="fuzzy"
            )
        return None

    async def _keyword_match(self, clean_name: str) -> Optional[NormalizedProductResult]:
        """Match based on category keywords."""
        keywords = {
            "mleko": "nabial",
            "ser": "nabial",
            "jogurt": "nabial",
            "masło": "nabial",
            "chleb": "pieczywo",
            "bułka": "pieczywo",
            "pieczywo": "pieczywo",
            "mięso": "mieso",
            "wędlina": "mieso",
            "szynka": "mieso",
            "kiełbasa": "mieso",
            "jabłko": "warzywa",
            "pomidor": "warzywa",
            "ogórek": "warzywa",
            "ziemniak": "warzywa",
            "woda": "napoje",
            "sok": "napoje",
            "cola": "napoje",
            "piwo": "napoje",
            "czekolada": "slodycze",
            "cukierki": "slodycze",
            "ciastka": "slodycze",
            "mąka": "suche",
            "ryż": "suche",
            "makaron": "suche",
            "mrożon": "mrozonki",
            "lody": "mrozonki",
            "proszek": "chemia",
            "płyn": "chemia",
            "środek": "chemia",
        }

        for keyword, category_key in keywords.items():
            if keyword in clean_name:
                # Find any product in this category
                stmt = text("""
                    SELECT p.id, p.normalized_name, c.key as category
                    FROM products p
                    JOIN categories c ON p.category_id = c.id
                    WHERE c.key = :category_key
                    AND word_similarity(:query, p.normalized_name) > 0.2
                    ORDER BY word_similarity(:query, p.normalized_name) DESC
                    LIMIT 1
                """)
                result = await self.session.execute(
                    stmt, {"category_key": category_key, "query": clean_name}
                )
                row = result.fetchone()
                if row:
                    return NormalizedProductResult(
                        product_id=row.id,
                        normalized_name=row.normalized_name,
                        category=row.category,
                        confidence=0.6,
                        match_method="keyword"
                    )
        return None

    async def search(
        self, query: str, category_id: Optional[int] = None, limit: int = 20
    ) -> List[Product]:
        """Search products by name with optional category filter."""
        stmt = text("""
            SELECT p.id, p.normalized_name, p.category_id, p.typical_price_pln,
                   similarity(:query, p.normalized_name) as sim
            FROM products p
            WHERE similarity(:query, p.normalized_name) > 0.2
            ORDER BY sim DESC
            LIMIT :limit
        """)
        if category_id:
            stmt = text("""
                SELECT p.id, p.normalized_name, p.category_id, p.typical_price_pln,
                       similarity(:query, p.normalized_name) as sim
                FROM products p
                WHERE similarity(:query, p.normalized_name) > 0.2
                  AND p.category_id = :category_id
                ORDER BY sim DESC
                LIMIT :limit
            """)
            result = await self.session.execute(
                stmt, {"query": query, "category_id": category_id, "limit": limit}
            )
        else:
            result = await self.session.execute(
                stmt, {"query": query, "limit": limit}
            )

        rows = result.fetchall()
        if not rows:
            return []

        # Load full products
        ids = [row.id for row in rows]
        products_stmt = (
            select(Product)
            .options(selectinload(Product.category))
            .where(Product.id.in_(ids))
        )
        products_result = await self.session.execute(products_stmt)
        return list(products_result.scalars().all())

    async def get_by_category(self, category_id: int) -> List[Product]:
        """Get all products in a category."""
        stmt = (
            select(Product)
            .options(selectinload(Product.variants))
            .where(Product.category_id == category_id)
            .order_by(Product.normalized_name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_with_variant(
        self,
        normalized_name: str,
        raw_name: str,
        category_id: Optional[int] = None,
        typical_price: Optional[Decimal] = None,
    ) -> Product:
        """Create a new product with its first variant."""
        product = Product(
            normalized_name=normalized_name,
            category_id=category_id,
            typical_price_pln=typical_price,
        )
        self.session.add(product)
        await self.session.flush()

        variant = ProductVariant(product_id=product.id, raw_name=raw_name)
        self.session.add(variant)
        await self.session.flush()

        await self.session.refresh(product)
        return product
