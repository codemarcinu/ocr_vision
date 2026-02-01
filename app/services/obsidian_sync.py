"""
Obsidian Sync Service - Generate markdown files from database.

This service regenerates Obsidian vault files from the PostgreSQL database,
ensuring consistency between the database (source of truth) and markdown files.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import UUID

import yaml

from app.config import settings
from app.db.connection import get_session_context
from app.db.repositories.pantry import PantryRepository
from app.db.repositories.receipts import ReceiptRepository

logger = logging.getLogger(__name__)


class ObsidianSyncService:
    """Service for syncing database content to Obsidian markdown files."""

    def __init__(self):
        self.receipts_dir = settings.RECEIPTS_DIR
        self.pantry_file = settings.PANTRY_FILE
        self.categories = settings.CATEGORIES

    async def regenerate_receipt(self, receipt_id: UUID) -> Optional[Path]:
        """
        Regenerate markdown file for a single receipt.

        Args:
            receipt_id: UUID of the receipt to regenerate

        Returns:
            Path to the generated file, or None if receipt not found
        """
        async with get_session_context() as session:
            repo = ReceiptRepository(session)
            receipt = await repo.get_with_items(receipt_id)

            if not receipt:
                logger.warning(f"Receipt not found: {receipt_id}")
                return None

            return self._write_receipt_file(receipt)

    async def regenerate_all_receipts(self) -> dict:
        """
        Regenerate all receipt markdown files from database.

        Returns:
            Dict with count of processed/errors
        """
        settings.ensure_directories()
        processed = 0
        errors = 0

        async with get_session_context() as session:
            repo = ReceiptRepository(session)
            # Get all receipts in batches
            offset = 0
            batch_size = 100

            while True:
                receipts = await repo.get_all(limit=batch_size, offset=offset)
                if not receipts:
                    break

                for receipt in receipts:
                    try:
                        # Load items for this receipt
                        full_receipt = await repo.get_with_items(receipt.id)
                        if full_receipt:
                            self._write_receipt_file(full_receipt)
                            processed += 1
                    except Exception as e:
                        logger.error(f"Error regenerating receipt {receipt.id}: {e}")
                        errors += 1

                offset += batch_size

        logger.info(f"Regenerated {processed} receipts, {errors} errors")
        return {"processed": processed, "errors": errors}

    async def regenerate_pantry(self) -> Path:
        """
        Regenerate spiżarnia.md from database.

        Returns:
            Path to the generated pantry file
        """
        settings.ensure_directories()

        async with get_session_context() as session:
            repo = PantryRepository(session)
            grouped = await repo.get_grouped_by_category()

            return self._write_pantry_file(grouped)

    async def full_regenerate(self) -> dict:
        """
        Full regeneration of all Obsidian vault files.

        Returns:
            Dict with summary of regenerated files
        """
        logger.info("Starting full Obsidian vault regeneration")

        # Regenerate all receipts
        receipts_result = await self.regenerate_all_receipts()

        # Regenerate pantry
        pantry_path = await self.regenerate_pantry()

        return {
            "receipts": receipts_result,
            "pantry": str(pantry_path),
            "timestamp": datetime.now().isoformat(),
        }

    def _write_receipt_file(self, receipt) -> Path:
        """
        Write a receipt to markdown file.

        Args:
            receipt: Receipt model with items loaded

        Returns:
            Path to the created file
        """
        date_str = receipt.receipt_date.isoformat() if receipt.receipt_date else datetime.now().strftime("%Y-%m-%d")
        source_name = receipt.source_file.rsplit(".", 1)[0] if receipt.source_file else str(receipt.id)[:8]
        filename = f"{date_str}_{source_name}.md"
        output_path = self.receipts_dir / filename

        store_name = receipt.store.name if receipt.store else (receipt.store_raw or "nieznany")
        total = float(receipt.total_final) if receipt.total_final else None

        frontmatter = {
            "date": date_str,
            "store": store_name,
            "total": total,
            "processed": receipt.processed_at.isoformat() if receipt.processed_at else None,
            "source": receipt.source_file,
            "id": str(receipt.id),
        }

        # Group items by category
        by_category: dict[str, list] = {}
        for item in receipt.items:
            category = item.category.name if item.category else "Inne"
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(item)

        # Build markdown content
        lines = [
            "---",
            yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).strip(),
            "---",
            "",
            f"# Paragon: {store_name}",
            f"**Data:** {date_str}",
            f"**Suma:** {total or 'N/A'} zł",
            "",
        ]

        for category in self.categories:
            if category in by_category:
                lines.append(f"## {category}")
                for item in by_category[category]:
                    warning = f" {item.warning}" if item.warning else ""
                    conf = f" (conf: {float(item.confidence):.0%})" if item.confidence and float(item.confidence) < 0.8 else ""

                    # Show discount if present
                    discount_info = ""
                    if item.discount_amount and item.price_original:
                        discount_info = f" ~~{float(item.price_original):.2f}~~ (-{float(item.discount_amount):.2f})"

                    name = item.name_normalized or item.name_raw
                    price = float(item.price_final)
                    lines.append(f"- {name} | {price:.2f} zł{discount_info}{warning}{conf}")
                lines.append("")

        # Add any categories not in the standard list
        for category, items in by_category.items():
            if category not in self.categories:
                lines.append(f"## {category}")
                for item in items:
                    name = item.name_normalized or item.name_raw
                    price = float(item.price_final)
                    lines.append(f"- {name} | {price:.2f} zł")
                lines.append("")

        content = "\n".join(lines)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.debug(f"Wrote receipt file: {output_path}")
        return output_path

    def _write_pantry_file(self, grouped_items: dict) -> Path:
        """
        Write pantry file from grouped items.

        Args:
            grouped_items: Dict mapping category names to lists of PantryItem

        Returns:
            Path to the created file
        """
        lines = [
            "---",
            f"updated: {datetime.now().isoformat()}",
            "---",
            "",
        ]

        for category in self.categories:
            if category in grouped_items and grouped_items[category]:
                lines.append(f"## {category}")
                for item in grouped_items[category]:
                    checkbox = "[x]" if item.is_consumed else "[ ]"
                    date_str = item.purchase_date.isoformat() if item.purchase_date else ""
                    store_name = item.store.name if item.store else ""

                    line = f"- {checkbox} {item.name} | {date_str} | {store_name}"
                    lines.append(line)
                lines.append("")

        # Add any categories not in the standard list
        for category, items in grouped_items.items():
            if category not in self.categories and items:
                lines.append(f"## {category}")
                for item in items:
                    checkbox = "[x]" if item.is_consumed else "[ ]"
                    date_str = item.purchase_date.isoformat() if item.purchase_date else ""
                    store_name = item.store.name if item.store else ""
                    line = f"- {checkbox} {item.name} | {date_str} | {store_name}"
                    lines.append(line)
                lines.append("")

        content = "\n".join(lines)

        with open(self.pantry_file, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Wrote pantry file: {self.pantry_file}")
        return self.pantry_file


# Singleton instance
obsidian_sync = ObsidianSyncService()
