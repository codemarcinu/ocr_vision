"""Analytics repository for reports and data analysis."""

from datetime import date
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.base import BaseRepository
from app.db.models import PriceHistory


class AnalyticsRepository(BaseRepository[PriceHistory]):
    """Repository for analytics and reporting."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, PriceHistory)

    async def get_price_trends(
        self, product_id: int, months: int = 6
    ) -> List[dict]:
        """Get price history for a product."""
        stmt = text("""
            SELECT
                ph.recorded_date,
                ph.price,
                s.name as store
            FROM price_history ph
            LEFT JOIN stores s ON ph.store_id = s.id
            WHERE ph.product_id = :product_id
              AND ph.recorded_date > CURRENT_DATE - :months * INTERVAL '1 month'
            ORDER BY ph.recorded_date
        """)
        result = await self.session.execute(stmt, {"product_id": product_id, "months": months})
        return [
            {
                "date": row.recorded_date.isoformat(),
                "price": float(row.price),
                "store": row.store,
            }
            for row in result.fetchall()
        ]

    async def get_store_comparison(
        self, product_ids: List[int]
    ) -> List[dict]:
        """Compare prices across stores for given products."""
        if not product_ids:
            return []

        stmt = text("""
            SELECT
                p.normalized_name as product,
                s.name as store,
                AVG(ri.price_final) as avg_price,
                MIN(ri.price_final) as min_price,
                MAX(ri.price_final) as max_price,
                COUNT(*) as purchase_count
            FROM receipt_items ri
            JOIN receipts r ON ri.receipt_id = r.id
            JOIN products p ON ri.product_id = p.id
            JOIN stores s ON r.store_id = s.id
            WHERE ri.product_id = ANY(:product_ids)
            GROUP BY p.id, p.normalized_name, s.id, s.name
            ORDER BY p.normalized_name, avg_price
        """)
        result = await self.session.execute(stmt, {"product_ids": product_ids})
        return [
            {
                "product": row.product,
                "store": row.store,
                "avg_price": float(row.avg_price),
                "min_price": float(row.min_price),
                "max_price": float(row.max_price),
                "purchase_count": row.purchase_count,
            }
            for row in result.fetchall()
        ]

    async def get_spending_by_category(
        self, start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> List[dict]:
        """Get spending breakdown by category."""
        if start_date and end_date:
            stmt = text("""
                SELECT
                    c.name as category,
                    SUM(ri.price_final) as total_spent,
                    COUNT(*) as item_count,
                    AVG(ri.price_final) as avg_price
                FROM receipt_items ri
                JOIN receipts r ON ri.receipt_id = r.id
                LEFT JOIN categories c ON ri.category_id = c.id
                WHERE r.receipt_date BETWEEN :start_date AND :end_date
                GROUP BY c.id, c.name
                ORDER BY total_spent DESC
            """)
            result = await self.session.execute(
                stmt, {"start_date": start_date, "end_date": end_date}
            )
        else:
            stmt = text("""
                SELECT
                    c.name as category,
                    SUM(ri.price_final) as total_spent,
                    COUNT(*) as item_count,
                    AVG(ri.price_final) as avg_price
                FROM receipt_items ri
                JOIN receipts r ON ri.receipt_id = r.id
                LEFT JOIN categories c ON ri.category_id = c.id
                GROUP BY c.id, c.name
                ORDER BY total_spent DESC
            """)
            result = await self.session.execute(stmt)

        return [
            {
                "category": row.category or "Inne",
                "total_spent": float(row.total_spent) if row.total_spent else 0,
                "item_count": row.item_count,
                "avg_price": float(row.avg_price) if row.avg_price else 0,
            }
            for row in result.fetchall()
        ]

    async def get_spending_by_store(
        self, start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> List[dict]:
        """Get spending breakdown by store."""
        if start_date and end_date:
            stmt = text("""
                SELECT
                    s.name as store,
                    SUM(r.total_final) as total_spent,
                    COUNT(r.id) as receipt_count,
                    AVG(r.total_final) as avg_receipt
                FROM receipts r
                JOIN stores s ON r.store_id = s.id
                WHERE r.receipt_date BETWEEN :start_date AND :end_date
                GROUP BY s.id, s.name
                ORDER BY total_spent DESC
            """)
            result = await self.session.execute(
                stmt, {"start_date": start_date, "end_date": end_date}
            )
        else:
            stmt = text("""
                SELECT
                    s.name as store,
                    SUM(r.total_final) as total_spent,
                    COUNT(r.id) as receipt_count,
                    AVG(r.total_final) as avg_receipt
                FROM receipts r
                JOIN stores s ON r.store_id = s.id
                GROUP BY s.id, s.name
                ORDER BY total_spent DESC
            """)
            result = await self.session.execute(stmt)

        return [
            {
                "store": row.store,
                "total_spent": float(row.total_spent) if row.total_spent else 0,
                "receipt_count": row.receipt_count,
                "avg_receipt": float(row.avg_receipt) if row.avg_receipt else 0,
            }
            for row in result.fetchall()
        ]

    async def get_monthly_breakdown(
        self, months: int = 12
    ) -> List[dict]:
        """Get monthly spending breakdown."""
        stmt = text("""
            SELECT
                DATE_TRUNC('month', r.receipt_date) as month,
                s.name as store,
                c.name as category,
                SUM(ri.price_final) as total
            FROM receipt_items ri
            JOIN receipts r ON ri.receipt_id = r.id
            LEFT JOIN stores s ON r.store_id = s.id
            LEFT JOIN categories c ON ri.category_id = c.id
            WHERE r.receipt_date > CURRENT_DATE - :months * INTERVAL '1 month'
            GROUP BY DATE_TRUNC('month', r.receipt_date), s.name, c.name
            ORDER BY month DESC, total DESC
        """)
        result = await self.session.execute(stmt, {"months": months})
        return [
            {
                "month": row.month.isoformat() if row.month else None,
                "store": row.store,
                "category": row.category or "Inne",
                "total": float(row.total) if row.total else 0,
            }
            for row in result.fetchall()
        ]

    async def get_discount_summary(
        self, start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> dict:
        """Get discount summary."""
        if start_date and end_date:
            stmt = text("""
                SELECT
                    COUNT(*) FILTER (WHERE ri.discount_amount > 0) as discounted_items,
                    COUNT(*) as total_items,
                    SUM(ri.discount_amount) FILTER (WHERE ri.discount_amount > 0) as total_savings,
                    AVG(ri.discount_amount) FILTER (WHERE ri.discount_amount > 0) as avg_discount
                FROM receipt_items ri
                JOIN receipts r ON ri.receipt_id = r.id
                WHERE r.receipt_date BETWEEN :start_date AND :end_date
            """)
            result = await self.session.execute(
                stmt, {"start_date": start_date, "end_date": end_date}
            )
        else:
            stmt = text("""
                SELECT
                    COUNT(*) FILTER (WHERE ri.discount_amount > 0) as discounted_items,
                    COUNT(*) as total_items,
                    SUM(ri.discount_amount) FILTER (WHERE ri.discount_amount > 0) as total_savings,
                    AVG(ri.discount_amount) FILTER (WHERE ri.discount_amount > 0) as avg_discount
                FROM receipt_items ri
            """)
            result = await self.session.execute(stmt)

        row = result.fetchone()
        return {
            "discounted_items": row.discounted_items or 0,
            "total_items": row.total_items or 0,
            "total_savings": float(row.total_savings) if row.total_savings else 0,
            "avg_discount": float(row.avg_discount) if row.avg_discount else 0,
            "discount_percentage": (
                (row.discounted_items / row.total_items * 100)
                if row.total_items
                else 0
            ),
        }

    async def get_top_products(
        self, limit: int = 20, by: str = "count"
    ) -> List[dict]:
        """Get top products by count or spending."""
        order_by = "purchase_count DESC" if by == "count" else "total_spent DESC"
        stmt = text(f"""
            SELECT
                p.normalized_name as product,
                c.name as category,
                COUNT(*) as purchase_count,
                SUM(ri.price_final) as total_spent,
                AVG(ri.price_final) as avg_price
            FROM receipt_items ri
            JOIN products p ON ri.product_id = p.id
            LEFT JOIN categories c ON p.category_id = c.id
            GROUP BY p.id, p.normalized_name, c.name
            ORDER BY {order_by}
            LIMIT :limit
        """)
        result = await self.session.execute(stmt, {"limit": limit})
        return [
            {
                "product": row.product,
                "category": row.category or "Inne",
                "purchase_count": row.purchase_count,
                "total_spent": float(row.total_spent) if row.total_spent else 0,
                "avg_price": float(row.avg_price) if row.avg_price else 0,
            }
            for row in result.fetchall()
        ]

    async def get_basket_analysis(self, min_support: float = 0.1) -> List[dict]:
        """Get frequently bought together products (basket analysis)."""
        # Simple co-occurrence analysis
        stmt = text("""
            WITH product_pairs AS (
                SELECT
                    LEAST(ri1.product_id, ri2.product_id) as product_a,
                    GREATEST(ri1.product_id, ri2.product_id) as product_b,
                    COUNT(DISTINCT ri1.receipt_id) as co_occurrences
                FROM receipt_items ri1
                JOIN receipt_items ri2 ON ri1.receipt_id = ri2.receipt_id
                    AND ri1.product_id < ri2.product_id
                WHERE ri1.product_id IS NOT NULL
                  AND ri2.product_id IS NOT NULL
                GROUP BY product_a, product_b
                HAVING COUNT(DISTINCT ri1.receipt_id) >= 3
            )
            SELECT
                p1.normalized_name as product_a,
                p2.normalized_name as product_b,
                pp.co_occurrences,
                pp.co_occurrences::float / (
                    SELECT COUNT(DISTINCT id) FROM receipts
                ) as support
            FROM product_pairs pp
            JOIN products p1 ON pp.product_a = p1.id
            JOIN products p2 ON pp.product_b = p2.id
            WHERE pp.co_occurrences::float / (
                SELECT COUNT(DISTINCT id) FROM receipts
            ) >= :min_support
            ORDER BY pp.co_occurrences DESC
            LIMIT 50
        """)
        result = await self.session.execute(stmt, {"min_support": min_support})
        return [
            {
                "product_a": row.product_a,
                "product_b": row.product_b,
                "co_occurrences": row.co_occurrences,
                "support": float(row.support),
            }
            for row in result.fetchall()
        ]

    async def get_weekly_comparison(self) -> dict:
        """Compare spending: this week vs previous week."""
        stmt = text("""
            WITH this_week AS (
                SELECT
                    COALESCE(SUM(r.total_final), 0) as total,
                    COUNT(r.id) as receipt_count,
                    COUNT(ri.id) as product_count
                FROM receipts r
                LEFT JOIN receipt_items ri ON ri.receipt_id = r.id
                WHERE r.receipt_date >= date_trunc('week', CURRENT_DATE)
            ),
            prev_week AS (
                SELECT
                    COALESCE(SUM(r.total_final), 0) as total,
                    COUNT(r.id) as receipt_count,
                    COUNT(ri.id) as product_count
                FROM receipts r
                LEFT JOIN receipt_items ri ON ri.receipt_id = r.id
                WHERE r.receipt_date >= date_trunc('week', CURRENT_DATE) - INTERVAL '7 days'
                  AND r.receipt_date < date_trunc('week', CURRENT_DATE)
            ),
            top_categories AS (
                SELECT
                    c.name as category,
                    SUM(ri.price_final) as total
                FROM receipt_items ri
                JOIN receipts r ON ri.receipt_id = r.id
                LEFT JOIN categories c ON ri.category_id = c.id
                WHERE r.receipt_date >= date_trunc('week', CURRENT_DATE)
                GROUP BY c.name
                ORDER BY total DESC
                LIMIT 3
            )
            SELECT
                tw.total as this_total,
                tw.receipt_count as this_receipts,
                tw.product_count as this_products,
                pw.total as prev_total,
                pw.receipt_count as prev_receipts,
                pw.product_count as prev_products
            FROM this_week tw, prev_week pw
        """)
        result = await self.session.execute(stmt)
        row = result.fetchone()

        if not row:
            return {}

        this_total = float(row.this_total)
        prev_total = float(row.prev_total)
        diff = this_total - prev_total
        diff_pct = (diff / prev_total * 100) if prev_total > 0 else 0

        # Get top categories for this week
        cat_stmt = text("""
            SELECT
                c.name as category,
                SUM(ri.price_final) as total
            FROM receipt_items ri
            JOIN receipts r ON ri.receipt_id = r.id
            LEFT JOIN categories c ON ri.category_id = c.id
            WHERE r.receipt_date >= date_trunc('week', CURRENT_DATE)
            GROUP BY c.name
            ORDER BY total DESC
            LIMIT 3
        """)
        cat_result = await self.session.execute(cat_stmt)
        top_cats = [
            {"category": r.category or "Inne", "total": float(r.total)}
            for r in cat_result.fetchall()
        ]

        return {
            "this_week": {
                "total": this_total,
                "receipts": row.this_receipts,
                "products": row.this_products,
            },
            "prev_week": {
                "total": prev_total,
                "receipts": row.prev_receipts,
                "products": row.prev_products,
            },
            "diff": diff,
            "diff_pct": diff_pct,
            "top_categories": top_cats,
        }

    async def get_price_anomalies(self, threshold_pct: float = 20.0) -> List[dict]:
        """Detect price anomalies: products costing >threshold% more than avg."""
        stmt = text("""
            WITH product_stats AS (
                SELECT
                    p.id as product_id,
                    p.normalized_name as product_name,
                    AVG(ph.price) as avg_price,
                    STDDEV(ph.price) as stddev_price,
                    COUNT(ph.id) as history_count
                FROM products p
                JOIN price_history ph ON ph.product_id = p.id
                GROUP BY p.id, p.normalized_name
                HAVING COUNT(ph.id) >= 3
            ),
            recent_purchases AS (
                SELECT DISTINCT ON (ri.product_id)
                    ri.product_id,
                    ri.price_final as latest_price,
                    r.receipt_date,
                    s.name as store
                FROM receipt_items ri
                JOIN receipts r ON ri.receipt_id = r.id
                LEFT JOIN stores s ON r.store_id = s.id
                WHERE r.receipt_date >= CURRENT_DATE - INTERVAL '14 days'
                ORDER BY ri.product_id, r.receipt_date DESC
            )
            SELECT
                ps.product_name,
                ps.avg_price,
                rp.latest_price,
                rp.receipt_date,
                rp.store,
                ((rp.latest_price - ps.avg_price) / ps.avg_price * 100) as diff_pct
            FROM product_stats ps
            JOIN recent_purchases rp ON rp.product_id = ps.product_id
            WHERE rp.latest_price > ps.avg_price * (1 + :threshold / 100.0)
              AND ps.avg_price > 0
            ORDER BY diff_pct DESC
            LIMIT 10
        """)
        result = await self.session.execute(stmt, {"threshold": threshold_pct})
        return [
            {
                "product": row.product_name,
                "avg_price": float(row.avg_price),
                "latest_price": float(row.latest_price),
                "date": row.receipt_date.isoformat() if row.receipt_date else None,
                "store": row.store,
                "diff_pct": float(row.diff_pct),
            }
            for row in result.fetchall()
        ]

    async def get_yearly_comparison(self) -> List[dict]:
        """Get year-over-year comparison."""
        stmt = text("""
            SELECT
                EXTRACT(YEAR FROM receipt_date) as year,
                EXTRACT(MONTH FROM receipt_date) as month,
                SUM(total_final) as total_spent,
                COUNT(*) as receipt_count
            FROM receipts
            GROUP BY EXTRACT(YEAR FROM receipt_date), EXTRACT(MONTH FROM receipt_date)
            ORDER BY year DESC, month
        """)
        result = await self.session.execute(stmt)
        return [
            {
                "year": int(row.year),
                "month": int(row.month),
                "total_spent": float(row.total_spent) if row.total_spent else 0,
                "receipt_count": row.receipt_count,
            }
            for row in result.fetchall()
        ]
