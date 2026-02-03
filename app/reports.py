"""Reports generation for Second Brain."""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


@dataclass
class DiscountItem:
    """Single discounted product."""
    product_name: str
    original_price: float
    final_price: float
    discount_amount: float
    date: str
    store: str


@dataclass
class DiscountSummary:
    """Summary of all discounts."""
    total_discount: float = 0.0
    total_original: float = 0.0
    total_final: float = 0.0
    discount_count: int = 0
    items: list[DiscountItem] = field(default_factory=list)
    by_store: dict = field(default_factory=lambda: defaultdict(float))
    by_category: dict = field(default_factory=lambda: defaultdict(float))
    by_month: dict = field(default_factory=lambda: defaultdict(float))


@dataclass
class StoreStats:
    """Statistics per store."""
    store_name: str
    total_spent: float = 0.0
    total_discount: float = 0.0
    receipt_count: int = 0
    product_count: int = 0


@dataclass
class MonthlyStats:
    """Monthly spending statistics."""
    month: str
    total_spent: float = 0.0
    total_discount: float = 0.0
    receipt_count: int = 0
    top_categories: list = field(default_factory=list)


def parse_receipt_files() -> list[dict]:
    """Parse all receipt markdown files from vault."""
    receipts = []
    receipts_dir = settings.RECEIPTS_DIR

    if not receipts_dir.exists():
        return receipts

    for md_file in receipts_dir.glob("*.md"):
        if md_file.name.startswith("ERROR_"):
            continue

        try:
            receipt_data = parse_single_receipt(md_file)
            if receipt_data:
                receipts.append(receipt_data)
        except Exception as e:
            logger.warning(f"Failed to parse {md_file}: {e}")

    return receipts


def parse_single_receipt(file_path: Path) -> Optional[dict]:
    """Parse a single receipt markdown file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract YAML frontmatter
    if not content.startswith("---"):
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None

    # Parse products from markdown
    products = []
    current_category = None

    for line in parts[2].split("\n"):
        line = line.strip()

        if line.startswith("## "):
            current_category = line[3:].strip()
        elif line.startswith("- ") and current_category:
            product = parse_product_line(line, current_category)
            if product:
                products.append(product)

    return {
        "file": file_path.name,
        "date": frontmatter.get("date", ""),
        "store": frontmatter.get("store", "nieznany"),
        "total": frontmatter.get("total", 0),
        "products": products
    }


def parse_product_line(line: str, category: str) -> Optional[dict]:
    """Parse a product line from receipt markdown."""
    # Format: - Product Name | 12.99 zł ~~15.99~~ (-3.00)
    # or:     - Product Name | 12.99 zł

    try:
        # Remove "- " prefix
        content = line[2:].strip()

        # Split by |
        parts = content.split("|")
        if len(parts) < 2:
            return None

        name = parts[0].strip()
        price_part = parts[1].strip()

        # Extract prices
        final_price = None
        original_price = None
        discount = None

        # Check for strikethrough (original price)
        strike_match = re.search(r'~~([\d.]+)~~', price_part)
        if strike_match:
            original_price = float(strike_match.group(1))

        # Check for discount amount
        discount_match = re.search(r'\(-([\d.]+)\)', price_part)
        if discount_match:
            discount = float(discount_match.group(1))

        # Extract final price
        price_match = re.search(r'([\d.]+)\s*zł', price_part)
        if price_match:
            final_price = float(price_match.group(1))

        if final_price is None:
            return None

        return {
            "name": name,
            "category": category,
            "price": final_price,
            "original_price": original_price,
            "discount": discount
        }

    except Exception:
        return None


def calculate_discount_summary(receipts: list[dict]) -> DiscountSummary:
    """Calculate discount summary from receipts."""
    summary = DiscountSummary()

    for receipt in receipts:
        date = receipt.get("date", "")
        store = receipt.get("store", "nieznany")
        month = date[:7] if len(date) >= 7 else "unknown"

        for product in receipt.get("products", []):
            if product.get("discount") and product.get("original_price"):
                item = DiscountItem(
                    product_name=product["name"],
                    original_price=product["original_price"],
                    final_price=product["price"],
                    discount_amount=product["discount"],
                    date=date,
                    store=store
                )
                summary.items.append(item)
                summary.total_discount += product["discount"]
                summary.total_original += product["original_price"]
                summary.total_final += product["price"]
                summary.discount_count += 1
                summary.by_store[store] += product["discount"]
                summary.by_category[product.get("category", "Inne")] += product["discount"]
                summary.by_month[month] += product["discount"]

    return summary


def calculate_store_stats(receipts: list[dict]) -> list[StoreStats]:
    """Calculate statistics per store."""
    stats_by_store = defaultdict(lambda: StoreStats(store_name=""))

    for receipt in receipts:
        store = receipt.get("store", "nieznany")
        total = receipt.get("total", 0) or 0

        stats = stats_by_store[store]
        stats.store_name = store
        stats.total_spent += total
        stats.receipt_count += 1
        stats.product_count += len(receipt.get("products", []))

        for product in receipt.get("products", []):
            if product.get("discount"):
                stats.total_discount += product["discount"]

    return sorted(stats_by_store.values(), key=lambda x: x.total_spent, reverse=True)


def calculate_monthly_stats(receipts: list[dict]) -> list[MonthlyStats]:
    """Calculate monthly spending statistics."""
    monthly = defaultdict(lambda: {
        "total": 0,
        "discount": 0,
        "receipts": 0,
        "categories": defaultdict(float)
    })

    for receipt in receipts:
        date = receipt.get("date", "")
        month = date[:7] if len(date) >= 7 else "unknown"
        total = receipt.get("total", 0) or 0

        monthly[month]["total"] += total
        monthly[month]["receipts"] += 1

        for product in receipt.get("products", []):
            category = product.get("category", "Inne")
            monthly[month]["categories"][category] += product.get("price", 0)
            if product.get("discount"):
                monthly[month]["discount"] += product["discount"]

    results = []
    for month, data in sorted(monthly.items(), reverse=True):
        # Get top 3 categories
        top_cats = sorted(
            data["categories"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:3]

        results.append(MonthlyStats(
            month=month,
            total_spent=round(data["total"], 2),
            total_discount=round(data["discount"], 2),
            receipt_count=data["receipts"],
            top_categories=[{"category": c, "amount": round(a, 2)} for c, a in top_cats]
        ))

    return results


# ============================================================
# API Endpoints
# ============================================================

@router.get("/discounts")
async def get_discount_report():
    """
    Get comprehensive discount report.

    Returns summary of all discounts from processed receipts including:
    - Total savings
    - Discounts by store
    - Discounts by category
    - Monthly discount trends
    - List of all discounted items
    """
    receipts = parse_receipt_files()
    summary = calculate_discount_summary(receipts)

    return {
        "summary": {
            "total_discount": round(summary.total_discount, 2),
            "total_original_value": round(summary.total_original, 2),
            "total_paid": round(summary.total_final, 2),
            "discount_count": summary.discount_count,
            "savings_percentage": round(
                (summary.total_discount / summary.total_original * 100)
                if summary.total_original > 0 else 0, 1
            )
        },
        "by_store": {k: round(v, 2) for k, v in sorted(
            summary.by_store.items(), key=lambda x: x[1], reverse=True
        )},
        "by_category": {k: round(v, 2) for k, v in sorted(
            summary.by_category.items(), key=lambda x: x[1], reverse=True
        )},
        "by_month": {k: round(v, 2) for k, v in sorted(
            summary.by_month.items(), reverse=True
        )},
        "recent_items": [
            {
                "product": item.product_name,
                "original_price": item.original_price,
                "final_price": item.final_price,
                "discount": item.discount_amount,
                "date": item.date,
                "store": item.store
            }
            for item in summary.items[-20:]  # Last 20 items
        ]
    }


@router.get("/stores")
async def get_store_report():
    """
    Get spending statistics per store.

    Returns:
    - Total spent per store
    - Number of receipts
    - Total discounts received
    """
    receipts = parse_receipt_files()
    stats = calculate_store_stats(receipts)

    return {
        "stores": [
            {
                "name": s.store_name,
                "total_spent": round(s.total_spent, 2),
                "total_discount": round(s.total_discount, 2),
                "receipt_count": s.receipt_count,
                "product_count": s.product_count,
                "avg_receipt": round(s.total_spent / s.receipt_count, 2) if s.receipt_count > 0 else 0
            }
            for s in stats
        ],
        "total_receipts": sum(s.receipt_count for s in stats),
        "total_spent": round(sum(s.total_spent for s in stats), 2)
    }


@router.get("/monthly")
async def get_monthly_report():
    """
    Get monthly spending report.

    Returns:
    - Total spent per month
    - Discounts per month
    - Top categories per month
    """
    receipts = parse_receipt_files()
    monthly = calculate_monthly_stats(receipts)

    return {
        "months": [
            {
                "month": m.month,
                "total_spent": m.total_spent,
                "total_discount": m.total_discount,
                "receipt_count": m.receipt_count,
                "top_categories": m.top_categories
            }
            for m in monthly
        ]
    }


@router.get("/categories")
async def get_category_report():
    """
    Get spending by category.
    """
    receipts = parse_receipt_files()

    category_totals = defaultdict(lambda: {"spent": 0, "count": 0, "discount": 0})

    for receipt in receipts:
        for product in receipt.get("products", []):
            category = product.get("category", "Inne")
            category_totals[category]["spent"] += product.get("price", 0)
            category_totals[category]["count"] += 1
            if product.get("discount"):
                category_totals[category]["discount"] += product["discount"]

    return {
        "categories": [
            {
                "category": cat,
                "total_spent": round(data["spent"], 2),
                "product_count": data["count"],
                "total_discount": round(data["discount"], 2)
            }
            for cat, data in sorted(
                category_totals.items(),
                key=lambda x: x[1]["spent"],
                reverse=True
            )
        ]
    }


@router.get("/summary")
async def get_full_summary():
    """
    Get comprehensive summary of all receipts and spending.
    """
    receipts = parse_receipt_files()

    total_spent = sum(r.get("total", 0) or 0 for r in receipts)
    total_products = sum(len(r.get("products", [])) for r in receipts)
    total_discount = sum(
        p.get("discount", 0) or 0
        for r in receipts
        for p in r.get("products", [])
    )

    # Date range
    dates = [r.get("date", "") for r in receipts if r.get("date")]
    date_range = {"from": min(dates) if dates else None, "to": max(dates) if dates else None}

    return {
        "overview": {
            "total_receipts": len(receipts),
            "total_products": total_products,
            "total_spent": round(total_spent, 2),
            "total_discount": round(total_discount, 2),
            "net_spent": round(total_spent, 2),  # After discounts
            "date_range": date_range
        },
        "averages": {
            "avg_receipt_value": round(total_spent / len(receipts), 2) if receipts else 0,
            "avg_products_per_receipt": round(total_products / len(receipts), 1) if receipts else 0,
            "avg_discount_per_receipt": round(total_discount / len(receipts), 2) if receipts else 0
        }
    }


@router.get("/classifier-ab")
async def get_classifier_ab_report():
    """
    Get A/B test results for classifier models.

    Returns comparison data between CLASSIFIER_MODEL and CLASSIFIER_MODEL_B
    including agreement rates, timing differences, and error rates.
    """
    import json

    ab_log_path = settings.LOGS_DIR / "classifier_ab_test.jsonl"

    if not ab_log_path.exists():
        return {
            "status": "no_data",
            "message": "No A/B test data yet. Set CLASSIFIER_MODEL_B to enable testing.",
            "config": {
                "model_a": settings.CLASSIFIER_MODEL,
                "model_b": settings.CLASSIFIER_MODEL_B or "(not configured)",
                "mode": settings.CLASSIFIER_AB_MODE,
            }
        }

    # Parse JSONL log
    results = []
    try:
        with open(ab_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    results.append(json.loads(line))
    except Exception as e:
        return {"status": "error", "message": f"Failed to read log: {e}"}

    if not results:
        return {"status": "no_data", "message": "Log file is empty"}

    # Calculate aggregated stats
    total_tests = len(results)
    total_products = sum(r.get("products_count", 0) for r in results)

    # Agreement stats
    agreements = [r.get("agreement", 0) for r in results]
    avg_agreement = sum(agreements) / len(agreements) if agreements else 0

    # Timing stats
    times_a = [r.get("time_a_sec", 0) for r in results]
    times_b = [r.get("time_b_sec", 0) for r in results if r.get("time_b_sec")]
    avg_time_a = sum(times_a) / len(times_a) if times_a else 0
    avg_time_b = sum(times_b) / len(times_b) if times_b else 0

    # Error rates
    errors_a = sum(1 for r in results if r.get("error_a"))
    errors_b = sum(1 for r in results if r.get("error_b"))

    # Get unique model pairs
    model_pairs = set()
    for r in results:
        model_pairs.add((r.get("model_a", ""), r.get("model_b", "")))

    return {
        "status": "ok",
        "config": {
            "model_a": settings.CLASSIFIER_MODEL,
            "model_b": settings.CLASSIFIER_MODEL_B or "(not configured)",
            "mode": settings.CLASSIFIER_AB_MODE,
        },
        "summary": {
            "total_tests": total_tests,
            "total_products_categorized": total_products,
            "avg_agreement": round(avg_agreement * 100, 1),  # percentage
            "agreement_interpretation": (
                "excellent" if avg_agreement >= 0.9 else
                "good" if avg_agreement >= 0.75 else
                "moderate" if avg_agreement >= 0.5 else
                "poor"
            ),
        },
        "timing": {
            "avg_time_model_a_sec": round(avg_time_a, 2),
            "avg_time_model_b_sec": round(avg_time_b, 2),
            "speedup": round(avg_time_a / avg_time_b, 2) if avg_time_b > 0 else None,
        },
        "reliability": {
            "errors_model_a": errors_a,
            "errors_model_b": errors_b,
            "error_rate_a": round(errors_a / total_tests * 100, 1) if total_tests > 0 else 0,
            "error_rate_b": round(errors_b / total_tests * 100, 1) if total_tests > 0 else 0,
        },
        "model_pairs_tested": [{"model_a": a, "model_b": b} for a, b in model_pairs],
        "recent_tests": results[-10:][::-1],  # Last 10, newest first
    }
