#!/usr/bin/env python3
"""
Migration script: JSON/Markdown files → PostgreSQL database.

Usage:
    python scripts/migrate_data.py

This script migrates data from:
- app/dictionaries/products.json → products, product_variants, categories
- app/dictionaries/stores.json → stores, store_aliases
- app/dictionaries/product_shortcuts.json → product_shortcuts
- vault/paragony/*.md → receipts, receipt_items
- vault/logs/unmatched.json → unmatched_products
- vault/logs/corrections.json → review_corrections

Run with --dry-run to preview without making changes.
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.connection import async_session_factory, engine, init_db
from app.db.models import (
    Category,
    Product,
    ProductShortcut,
    ProductVariant,
    Receipt,
    ReceiptItem,
    ReviewCorrection,
    Store,
    StoreAlias,
    UnmatchedProduct,
)


# Paths
DICTIONARIES_DIR = Path(__file__).parent.parent / "app" / "dictionaries"
VAULT_DIR = settings.VAULT_DIR if settings.VAULT_DIR.exists() else Path(__file__).parent.parent / "vault"
PARAGONY_DIR = VAULT_DIR / "paragony"
LOGS_DIR = VAULT_DIR / "logs"


async def migrate_categories(session: AsyncSession, products_data: dict) -> Dict[str, int]:
    """Migrate categories from products.json metadata."""
    print("Migrating categories...")

    # Map from category name to normalized key
    category_name_map = {
        "nabiał": ("nabial", "Nabiał"),
        "mięso": ("mieso", "Mięso i wędliny"),
        "wędliny": ("mieso", "Mięso i wędliny"),
        "ryby": ("ryby", "Ryby"),
        "warzywa": ("warzywa", "Warzywa i owoce"),
        "owoce": ("warzywa", "Warzywa i owoce"),
        "napoje": ("napoje", "Napoje"),
        "alkohol": ("alkohol", "Alkohol"),
        "piekarnia": ("pieczywo", "Pieczywo"),
        "pieczywo": ("pieczywo", "Pieczywo"),
        "słodycze": ("slodycze", "Słodycze"),
        "przekąski": ("przekaski", "Przekąski"),
        "konserwy": ("konserwy", "Konserwy"),
        "makarony": ("suche", "Produkty suche"),
        "przyprawy": ("przyprawy", "Przyprawy"),
        "mrożonki": ("mrozonki", "Mrożonki"),
        "dania_gotowe": ("gotowe", "Dania gotowe"),
        "chemia": ("chemia", "Chemia"),
        "kosmetyki": ("kosmetyki", "Kosmetyki"),
        "dla_dzieci": ("dzieci", "Dla dzieci"),
        "dla_zwierząt": ("zwierzeta", "Dla zwierząt"),
        "inne": ("inne", "Inne"),
    }

    category_ids = {}

    # Get existing categories
    result = await session.execute(select(Category))
    existing = {c.key: c.id for c in result.scalars().all()}

    for cat_name in products_data.get("metadata", {}).get("categories", []):
        key, display_name = category_name_map.get(cat_name, (cat_name.lower(), cat_name.title()))

        if key in existing:
            category_ids[cat_name] = existing[key]
            continue

        category = Category(key=key, name=display_name)
        session.add(category)
        await session.flush()
        category_ids[cat_name] = category.id
        existing[key] = category.id
        print(f"  Created category: {display_name} ({key})")

    await session.commit()
    print(f"  Total categories: {len(category_ids)}")
    return category_ids


async def migrate_stores(session: AsyncSession, stores_data: dict) -> Dict[str, int]:
    """Migrate stores and aliases from stores.json."""
    print("Migrating stores...")

    store_ids = {}
    stores = stores_data.get("stores", {})

    for store_name, aliases in stores.items():
        # Check if store exists
        result = await session.execute(
            select(Store).where(Store.name == store_name)
        )
        store = result.scalar_one_or_none()

        if not store:
            store = Store(name=store_name)
            session.add(store)
            await session.flush()
            print(f"  Created store: {store_name}")

        store_ids[store_name] = store.id
        store_ids[store_name.lower()] = store.id

        # Add aliases
        for alias in aliases:
            # Check if alias exists
            result = await session.execute(
                select(StoreAlias).where(StoreAlias.alias == alias)
            )
            if not result.scalar_one_or_none():
                store_alias = StoreAlias(store_id=store.id, alias=alias)
                session.add(store_alias)

    await session.commit()
    print(f"  Total stores: {len(stores)}")
    return store_ids


async def migrate_products(
    session: AsyncSession,
    products_data: dict,
    category_ids: Dict[str, int]
) -> Dict[str, int]:
    """Migrate products and variants from products.json."""
    print("Migrating products...")

    product_ids = {}
    product_count = 0
    variant_count = 0

    # Skip metadata
    for category_name, category_data in products_data.items():
        if category_name == "metadata":
            continue

        category_id = category_ids.get(category_name)
        products_list = category_data.get("products", [])

        for product_info in products_list:
            normalized_name = product_info.get("normalized_name", "").lower()
            if not normalized_name:
                continue

            typical_price = product_info.get("typical_price_pln")

            # Check if product exists
            result = await session.execute(
                select(Product).where(
                    Product.normalized_name == normalized_name,
                    Product.category_id == category_id,
                )
            )
            product = result.scalar_one_or_none()

            if not product:
                product = Product(
                    normalized_name=normalized_name,
                    category_id=category_id,
                    typical_price_pln=Decimal(str(typical_price)) if typical_price else None,
                )
                session.add(product)
                await session.flush()
                product_count += 1

            product_ids[normalized_name] = product.id

            # Add variants (raw_names)
            for raw_name in product_info.get("raw_names", []):
                raw_name_lower = raw_name.lower()
                # Check if variant exists
                result = await session.execute(
                    select(ProductVariant).where(ProductVariant.raw_name == raw_name_lower)
                )
                if not result.scalar_one_or_none():
                    variant = ProductVariant(product_id=product.id, raw_name=raw_name_lower)
                    session.add(variant)
                    variant_count += 1

    await session.commit()
    print(f"  Products: {product_count}, Variants: {variant_count}")
    return product_ids


async def migrate_shortcuts(
    session: AsyncSession,
    shortcuts_data: dict,
    store_ids: Dict[str, int]
) -> int:
    """Migrate product shortcuts from product_shortcuts.json."""
    print("Migrating product shortcuts...")

    count = 0

    for store_name, shortcuts in shortcuts_data.items():
        if store_name == "metadata":
            continue

        store_id = store_ids.get(store_name.lower())
        if not store_id:
            print(f"  Warning: Store '{store_name}' not found, skipping shortcuts")
            continue

        for shortcut, full_name in shortcuts.items():
            # Check if exists
            result = await session.execute(
                select(ProductShortcut).where(
                    ProductShortcut.store_id == store_id,
                    ProductShortcut.shortcut == shortcut.lower(),
                )
            )
            if not result.scalar_one_or_none():
                ps = ProductShortcut(
                    store_id=store_id,
                    shortcut=shortcut.lower(),
                    full_name=full_name,
                )
                session.add(ps)
                count += 1

    await session.commit()
    print(f"  Shortcuts: {count}")
    return count


async def migrate_receipts(
    session: AsyncSession,
    store_ids: Dict[str, int],
    category_ids: Dict[str, int]
) -> int:
    """Migrate receipts from vault/paragony/*.md files."""
    print("Migrating receipts...")

    if not PARAGONY_DIR.exists():
        print(f"  Directory not found: {PARAGONY_DIR}")
        return 0

    count = 0
    md_files = list(PARAGONY_DIR.glob("*.md"))
    print(f"  Found {len(md_files)} receipt files")

    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
            receipt_data = parse_receipt_markdown(content)
            if not receipt_data:
                continue

            # Check if receipt already exists
            result = await session.execute(
                select(Receipt).where(Receipt.source_file == md_file.name)
            )
            if result.scalar_one_or_none():
                continue

            # Get store ID
            store_id = None
            if receipt_data.get("store"):
                store_id = store_ids.get(receipt_data["store"].lower())

            # Create receipt
            receipt = Receipt(
                id=uuid4(),
                source_file=md_file.name,
                receipt_date=receipt_data.get("date", date.today()),
                store_id=store_id,
                store_raw=receipt_data.get("store"),
                total_final=receipt_data.get("total"),
                total_ocr=receipt_data.get("total"),
            )
            session.add(receipt)
            await session.flush()

            # Add items
            for item in receipt_data.get("products", []):
                category_id = None
                if item.get("category"):
                    cat_key = item["category"].lower()
                    category_id = category_ids.get(cat_key)

                receipt_item = ReceiptItem(
                    receipt_id=receipt.id,
                    name_raw=item.get("name", "Unknown"),
                    name_normalized=item.get("normalized_name"),
                    price_final=Decimal(str(item.get("price", 0))),
                    category_id=category_id,
                    discount_amount=Decimal(str(item["discount"])) if item.get("discount") else None,
                )
                session.add(receipt_item)

            count += 1

        except Exception as e:
            print(f"  Error processing {md_file.name}: {e}")

    await session.commit()
    print(f"  Receipts migrated: {count}")
    return count


def parse_receipt_markdown(content: str) -> Optional[dict]:
    """Parse receipt data from markdown file."""
    # Extract YAML frontmatter
    frontmatter_match = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not frontmatter_match:
        return None

    frontmatter = frontmatter_match.group(1)
    data = {}

    # Parse frontmatter fields
    for line in frontmatter.split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip("'\"")

            if key == "date":
                try:
                    data["date"] = datetime.strptime(value, "%Y-%m-%d").date()
                except ValueError:
                    pass
            elif key == "store":
                data["store"] = value
            elif key == "total":
                try:
                    data["total"] = Decimal(value.replace(",", ".").replace(" PLN", ""))
                except (ValueError, TypeError):
                    pass

    # Parse products from list format: "- Product | Price zł" or "- Product | Price zł (conf: X%)"
    products = []
    current_category = None

    for line in content.split("\n"):
        # Check for category header (## Category)
        if line.startswith("## "):
            current_category = line[3:].strip()
            continue

        # Check for product line (- Product | Price zł)
        if line.startswith("- ") and "|" in line:
            # Parse: "- ProductName | 12.99 zł" or "- ProductName | 12.99 zł (conf: 50%)"
            parts = line[2:].split("|")
            if len(parts) >= 2:
                name = parts[0].strip()
                price_part = parts[1].strip()

                # Extract price (remove " zł", "(conf: X%)", etc.)
                price_match = re.match(r"([\d,\.]+)\s*zł", price_part)
                price = 0.0
                if price_match:
                    try:
                        price = float(price_match.group(1).replace(",", "."))
                    except ValueError:
                        pass

                product = {
                    "name": name,
                    "price": price,
                }
                if current_category:
                    product["category"] = current_category

                products.append(product)

    data["products"] = products
    return data


async def migrate_unmatched(session: AsyncSession, store_ids: Dict[str, int]) -> int:
    """Migrate unmatched products from logs/unmatched.json."""
    print("Migrating unmatched products...")

    unmatched_file = LOGS_DIR / "unmatched.json"
    if not unmatched_file.exists():
        print(f"  File not found: {unmatched_file}")
        return 0

    try:
        with open(unmatched_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  Error reading file: {e}")
        return 0

    count = 0
    # Handle both list format (new) and dict format (legacy)
    items = data if isinstance(data, list) else [{"raw_name": k, **v} for k, v in data.items()]

    for info in items:
        raw_name = info.get("raw_name", "")
        if not raw_name:
            continue

        # Check if exists
        result = await session.execute(
            select(UnmatchedProduct).where(
                UnmatchedProduct.raw_name_normalized == raw_name.lower()
            )
        )
        if result.scalar_one_or_none():
            continue

        store_id = None
        if info.get("store"):
            store_id = store_ids.get(info["store"].lower())

        first_seen = date.today()
        last_seen = date.today()
        if info.get("first_seen"):
            try:
                first_seen = datetime.fromisoformat(info["first_seen"]).date()
            except ValueError:
                pass
        if info.get("last_seen"):
            try:
                last_seen = datetime.fromisoformat(info["last_seen"]).date()
            except ValueError:
                pass

        unmatched = UnmatchedProduct(
            raw_name=raw_name,
            raw_name_normalized=raw_name.lower(),
            price=Decimal(str(info["price"])) if info.get("price") else None,
            store_id=store_id,
            first_seen=first_seen,
            last_seen=last_seen,
            occurrence_count=info.get("count", 1),
        )
        session.add(unmatched)
        count += 1

    await session.commit()
    print(f"  Unmatched products: {count}")
    return count


async def migrate_corrections(session: AsyncSession, store_ids: Dict[str, int]) -> int:
    """Migrate review corrections from logs/corrections.json."""
    print("Migrating review corrections...")

    corrections_file = LOGS_DIR / "corrections.json"
    if not corrections_file.exists():
        print(f"  File not found: {corrections_file}")
        return 0

    try:
        with open(corrections_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  Error reading file: {e}")
        return 0

    count = 0
    for entry in data:
        store_id = None
        if entry.get("store"):
            store_id = store_ids.get(entry["store"].lower())

        correction = ReviewCorrection(
            original_total=Decimal(str(entry["original_total"])) if entry.get("original_total") else None,
            corrected_total=Decimal(str(entry["corrected_total"])) if entry.get("corrected_total") else Decimal("0"),
            correction_type=entry.get("correction_type", entry.get("action", "unknown")),
            store_id=store_id,
            product_count=entry.get("product_count"),
        )
        session.add(correction)
        count += 1

    await session.commit()
    print(f"  Corrections: {count}")
    return count


async def run_migration(dry_run: bool = False):
    """Run full migration."""
    print("=" * 60)
    print("Starting migration: JSON/Markdown → PostgreSQL")
    print("=" * 60)

    if dry_run:
        print("DRY RUN MODE - no changes will be made\n")

    # Initialize database connection
    await init_db()

    # Load source data
    print("\nLoading source data...")

    products_file = DICTIONARIES_DIR / "products.json"
    stores_file = DICTIONARIES_DIR / "stores.json"
    shortcuts_file = DICTIONARIES_DIR / "product_shortcuts.json"

    with open(products_file, encoding="utf-8") as f:
        products_data = json.load(f)
    print(f"  Loaded products.json")

    with open(stores_file, encoding="utf-8") as f:
        stores_data = json.load(f)
    print(f"  Loaded stores.json")

    with open(shortcuts_file, encoding="utf-8") as f:
        shortcuts_data = json.load(f)
    print(f"  Loaded product_shortcuts.json")

    # Run migrations
    print("\n")

    async with async_session_factory() as session:
        try:
            # 1. Categories
            category_ids = await migrate_categories(session, products_data)

            # 2. Stores
            store_ids = await migrate_stores(session, stores_data)

            # 3. Products
            product_ids = await migrate_products(session, products_data, category_ids)

            # 4. Shortcuts
            await migrate_shortcuts(session, shortcuts_data, store_ids)

            # 5. Receipts
            await migrate_receipts(session, store_ids, category_ids)

            # 6. Unmatched
            await migrate_unmatched(session, store_ids)

            # 7. Corrections
            await migrate_corrections(session, store_ids)

            if dry_run:
                print("\nDRY RUN - Rolling back all changes...")
                await session.rollback()
            else:
                await session.commit()

        except Exception as e:
            print(f"\nError during migration: {e}")
            await session.rollback()
            raise

    print("\n" + "=" * 60)
    print("Migration completed!")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Migrate data to PostgreSQL")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without making them",
    )
    args = parser.parse_args()

    asyncio.run(run_migration(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
