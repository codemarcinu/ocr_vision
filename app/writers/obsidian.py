"""Obsidian markdown file generation."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from app.config import settings
from app.models import CategorizedProduct, Receipt
from app.dictionaries import normalize_product, normalize_store_name

logger = logging.getLogger(__name__)


def write_receipt_file(
    receipt: Receipt,
    categorized_products: list[CategorizedProduct],
    source_filename: str
) -> Path:
    """
    Write receipt history file with YAML frontmatter.

    Returns:
        Path to created file
    """
    settings.ensure_directories()

    timestamp = datetime.now()
    date_str = receipt.data or timestamp.strftime("%Y-%m-%d")
    filename = f"{date_str}_{source_filename.rsplit('.', 1)[0]}.md"
    output_path = settings.RECEIPTS_DIR / filename

    frontmatter = {
        "date": date_str,
        "store": receipt.sklep or "nieznany",
        "total": receipt.suma,
        "processed": timestamp.isoformat(),
        "source": source_filename
    }

    # Group products by category
    by_category: dict[str, list[CategorizedProduct]] = {}
    for product in categorized_products:
        category = product.kategoria or "Inne"
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(product)

    # Build markdown content
    lines = [
        "---",
        yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).strip(),
        "---",
        "",
        f"# Paragon: {receipt.sklep or 'Nieznany sklep'}",
        f"**Data:** {date_str}",
        f"**Suma:** {receipt.suma or 'N/A'} zł",
        ""
    ]

    for category in settings.CATEGORIES:
        if category in by_category:
            lines.append(f"## {category}")
            for product in by_category[category]:
                warning = f" {product.warning}" if product.warning else ""
                conf = f" (conf: {product.confidence:.0%})" if product.confidence < 0.8 else ""
                # Show discount if present
                discount_info = ""
                if product.rabat and product.cena_oryginalna:
                    discount_info = f" ~~{product.cena_oryginalna:.2f}~~ (-{product.rabat:.2f})"
                lines.append(f"- {product.nazwa} | {product.cena:.2f} zł{discount_info}{warning}{conf}")
            lines.append("")

    content = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Created receipt file: {output_path}")
    return output_path


def update_pantry_file(categorized_products: list[CategorizedProduct], receipt: Receipt) -> None:
    """
    Update spiżarnia.md with new products.
    Products are added as unchecked checkboxes, grouped by category.
    Deduplication: skips products that already exist (same normalized name, date, store).
    """
    settings.ensure_directories()

    pantry_path = settings.PANTRY_FILE
    date_str = receipt.data or datetime.now().strftime("%Y-%m-%d")
    # Normalize store name
    raw_store = receipt.sklep or "nieznany"
    store = normalize_store_name(raw_store) or raw_store

    # Load existing content or create new
    existing_content: dict[str, list[str]] = {}
    existing_keys: set[str] = set()  # For deduplication
    if pantry_path.exists():
        existing_content = _parse_pantry_file(pantry_path)
        # Build dedup keys from existing items
        existing_keys = _build_dedup_keys(existing_content)

    # Add new products (with deduplication)
    added_count = 0
    skipped_count = 0
    for product in categorized_products:
        # Normalize category name (capitalize first letter)
        raw_category = product.kategoria or "Inne"
        category = raw_category.capitalize()
        if category not in existing_content:
            existing_content[category] = []

        # Build dedup key: normalized_name|date|store
        norm_name = product.nazwa_znormalizowana or normalize_product(product.nazwa).normalized_name or product.nazwa.lower()
        dedup_key = f"{norm_name}|{date_str}|{store}".lower()

        if dedup_key in existing_keys:
            skipped_count += 1
            logger.debug(f"Skipping duplicate: {product.nazwa}")
            continue

        existing_keys.add(dedup_key)
        added_count += 1

        warning = f" {product.warning}" if product.warning else ""
        line = f"- [ ] {product.nazwa} | {date_str} | {store}{warning}"
        existing_content[category].append(line)

    # Write updated file
    _write_pantry_file(pantry_path, existing_content)
    logger.info(f"Updated pantry file: {pantry_path} (added: {added_count}, skipped duplicates: {skipped_count})")


def _parse_pantry_file(path: Path) -> dict[str, list[str]]:
    """Parse existing spiżarnia.md file."""
    content: dict[str, list[str]] = {}
    current_category: Optional[str] = None

    with open(path, "r", encoding="utf-8") as f:
        in_frontmatter = False
        for line in f:
            line = line.rstrip()

            # Skip frontmatter
            if line == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue

            # Detect category headers
            if line.startswith("## "):
                current_category = line[3:].strip()
                if current_category not in content:
                    content[current_category] = []
            # Collect items
            elif line.startswith("- [") and current_category:
                content[current_category].append(line)

    return content


def _build_dedup_keys(content: dict[str, list[str]]) -> set[str]:
    """
    Build deduplication keys from existing pantry content.
    Key format: normalized_name|date|store (lowercase)
    Supports both old format (with price) and new format (without price).
    """
    keys = set()
    for category, lines in content.items():
        for line in lines:
            try:
                # Parse: - [ ] nazwa | data | sklep (new format)
                # or:    - [ ] nazwa | cena zł | data | sklep (old format)
                item_content = line[6:].strip()  # Remove "- [ ] " or "- [x] "
                parts = [p.strip() for p in item_content.split("|")]

                if len(parts) >= 3:
                    name = parts[0]
                    # Check if second part looks like a price (contains "zł")
                    if "zł" in parts[1] and len(parts) >= 4:
                        # Old format with price
                        date = parts[2]
                        store = parts[3].split()[0]
                    else:
                        # New format without price
                        date = parts[1]
                        store = parts[2].split()[0]  # Remove any warnings

                    # Normalize the name for comparison
                    norm_result = normalize_product(name)
                    norm_name = norm_result.normalized_name or name.lower()

                    key = f"{norm_name}|{date}|{store}".lower()
                    keys.add(key)
            except Exception:
                continue
    return keys


def _write_pantry_file(path: Path, content: dict[str, list[str]]) -> None:
    """Write spiżarnia.md file."""
    lines = [
        "---",
        f"updated: {datetime.now().isoformat()}",
        "---",
        ""
    ]

    for category in settings.CATEGORIES:
        if category in content and content[category]:
            lines.append(f"## {category}")
            lines.extend(content[category])
            lines.append("")

    # Add any unknown categories
    for category, items in content.items():
        if category not in settings.CATEGORIES and items:
            lines.append(f"## {category}")
            lines.extend(items)
            lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_error_file(source_filename: str, error_message: str) -> Path:
    """
    Create ERROR.md file for failed processing.

    Returns:
        Path to created error file
    """
    settings.ensure_directories()

    timestamp = datetime.now()
    error_filename = f"ERROR_{timestamp.strftime('%Y%m%d_%H%M%S')}_{source_filename.rsplit('.', 1)[0]}.md"
    error_path = settings.RECEIPTS_DIR / error_filename

    content = f"""---
date: {timestamp.isoformat()}
status: error
source: {source_filename}
---

# Błąd przetwarzania paragonu

**Plik:** {source_filename}
**Data:** {timestamp.strftime('%Y-%m-%d %H:%M:%S')}

## Błąd
```
{error_message}
```

## Akcje
- [ ] Sprawdzić jakość zdjęcia
- [ ] Ponowić przetwarzanie: `POST /reprocess/{source_filename}`
"""

    with open(error_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Created error file: {error_path}")
    return error_path


def log_error(source_filename: str, error_message: str) -> None:
    """Append error entry to ocr-errors.md log."""
    settings.ensure_directories()

    timestamp = datetime.now()
    log_entry = f"\n## {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
    log_entry += f"**Plik:** {source_filename}\n"
    log_entry += f"**Błąd:** {error_message}\n"

    log_path = settings.ERROR_LOG_FILE

    # Create file with header if it doesn't exist
    if not log_path.exists():
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# OCR Error Log\n\n")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(log_entry)

    logger.info(f"Logged error to: {log_path}")


def get_pantry_contents() -> dict[str, list[dict]]:
    """
    Get pantry contents organized by category.

    Returns:
        Dictionary mapping category to list of product dicts with:
        - name: str
        - price: float
        - date: str
        - store: str
        - checked: bool
        - line_number: int (for updates)
    """
    pantry_path = settings.PANTRY_FILE

    if not pantry_path.exists():
        return {}

    contents: dict[str, list[dict]] = {}
    current_category: Optional[str] = None

    with open(pantry_path, "r", encoding="utf-8") as f:
        in_frontmatter = False
        line_number = 0

        for line in f:
            line_number += 1
            line = line.rstrip()

            # Skip frontmatter
            if line == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue

            # Detect category headers
            if line.startswith("## "):
                current_category = line[3:].strip()
                if current_category not in contents:
                    contents[current_category] = []
            # Parse items
            elif line.startswith("- [") and current_category:
                item = _parse_pantry_item(line, line_number)
                if item:
                    contents[current_category].append(item)

    return contents


def _parse_pantry_item(line: str, line_number: int) -> Optional[dict]:
    """Parse a pantry item line. Supports both old and new formats."""
    try:
        # New format: - [ ] nazwa | data | sklep
        # Old format: - [ ] nazwa | cena zł | data | sklep
        checked = line.startswith("- [x]") or line.startswith("- [X]")
        content = line[6:].strip()  # Remove "- [ ] " or "- [x] "

        parts = [p.strip() for p in content.split("|")]
        if len(parts) < 2:
            return None

        name = parts[0]

        # Check if second part looks like a price (contains "zł")
        if "zł" in parts[1] and len(parts) >= 4:
            # Old format with price
            price_str = parts[1].replace("zł", "").strip()
            try:
                price = float(price_str)
            except ValueError:
                price = 0.0
            date = parts[2]
            store = parts[3].split()[0] if len(parts) > 3 else ""
        else:
            # New format without price
            price = 0.0
            date = parts[1] if len(parts) > 1 else ""
            store = parts[2].split()[0] if len(parts) > 2 else ""  # Remove warnings

        return {
            "name": name,
            "price": price,
            "date": date,
            "store": store,
            "checked": checked,
            "line_number": line_number
        }
    except Exception as e:
        logger.warning(f"Failed to parse pantry item: {line} - {e}")
        return None


def mark_product_used(query: str) -> tuple[bool, str]:
    """
    Mark a product as used (checked) in the pantry.

    Args:
        query: Product name or partial match

    Returns:
        Tuple of (success, message)
    """
    pantry_path = settings.PANTRY_FILE

    if not pantry_path.exists():
        return False, "Plik spiżarni nie istnieje."

    with open(pantry_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    query_lower = query.lower()
    found = False
    matched_name = ""

    for i, line in enumerate(lines):
        if line.startswith("- [ ]"):
            content = line[6:].strip()
            name = content.split("|")[0].strip()

            if query_lower in name.lower():
                lines[i] = line.replace("- [ ]", "- [x]", 1)
                found = True
                matched_name = name
                break

    if not found:
        return False, f"Nie znaleziono niezużytego produktu: '{query}'"

    with open(pantry_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # Update timestamp in frontmatter
    _update_pantry_timestamp()

    return True, f"Oznaczono jako zużyte: {matched_name}"


def remove_product_from_pantry(query: str) -> tuple[bool, str]:
    """
    Remove a product from the pantry.

    Args:
        query: Product name or partial match

    Returns:
        Tuple of (success, message)
    """
    pantry_path = settings.PANTRY_FILE

    if not pantry_path.exists():
        return False, "Plik spiżarni nie istnieje."

    with open(pantry_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    query_lower = query.lower()
    found_index = -1
    matched_name = ""

    for i, line in enumerate(lines):
        if line.startswith("- ["):
            content = line[6:].strip()
            name = content.split("|")[0].strip()

            if query_lower in name.lower():
                found_index = i
                matched_name = name
                break

    if found_index == -1:
        return False, f"Nie znaleziono produktu: '{query}'"

    # Remove the line
    del lines[found_index]

    with open(pantry_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # Update timestamp
    _update_pantry_timestamp()

    return True, f"Usunięto: {matched_name}"


def search_pantry(query: str) -> list[dict]:
    """
    Search for products in pantry.

    Args:
        query: Search string

    Returns:
        List of matching products with category info
    """
    contents = get_pantry_contents()
    results = []
    query_lower = query.lower()

    for category, items in contents.items():
        for item in items:
            if query_lower in item["name"].lower():
                item["category"] = category
                results.append(item)

    return results


def _update_pantry_timestamp() -> None:
    """Update the timestamp in pantry file frontmatter."""
    pantry_path = settings.PANTRY_FILE

    if not pantry_path.exists():
        return

    with open(pantry_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Update the updated field in frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import re
            new_timestamp = datetime.now().isoformat()
            parts[1] = re.sub(
                r"updated:.*",
                f"updated: {new_timestamp}",
                parts[1]
            )
            content = "---".join(parts)

            with open(pantry_path, "w", encoding="utf-8") as f:
                f.write(content)


def clear_error_log() -> bool:
    """
    Clear the error log file.

    Returns:
        True if successful
    """
    log_path = settings.ERROR_LOG_FILE

    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# OCR Error Log\n\n")
            f.write(f"_Wyczyszczono: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n")
        logger.info("Cleared error log")
        return True
    except Exception as e:
        logger.error(f"Failed to clear error log: {e}")
        return False


def get_errors() -> list[dict]:
    """
    Get list of errors from error log.

    Returns:
        List of error dicts with date, filename, message
    """
    log_path = settings.ERROR_LOG_FILE

    if not log_path.exists():
        return []

    errors = []

    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Parse error entries (## date format)
    import re
    entries = re.split(r"\n## ", content)

    for entry in entries[1:]:  # Skip header
        lines = entry.strip().split("\n")
        if not lines:
            continue

        date = lines[0].strip()
        filename = ""
        message = ""

        for line in lines[1:]:
            if line.startswith("**Plik:**"):
                filename = line.replace("**Plik:**", "").strip()
            elif line.startswith("**Błąd:**"):
                message = line.replace("**Błąd:**", "").strip()

        if date:
            errors.append({
                "date": date,
                "filename": filename,
                "message": message
            })

    return errors
