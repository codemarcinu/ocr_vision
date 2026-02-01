"""Feedback logging for learning from OCR corrections and unmatched products."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Output files
LOGS_DIR = settings.VAULT_DIR / "logs"
UNMATCHED_FILE = LOGS_DIR / "unmatched.json"
CORRECTIONS_FILE = LOGS_DIR / "corrections.json"


def _ensure_logs_dir():
    """Ensure logs directory exists."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _load_json_file(file_path: Path) -> list:
    """Load JSON file or return empty list if doesn't exist."""
    if not file_path.exists():
        return []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading {file_path}: {e}")
        return []


def _save_json_file(file_path: Path, data: list):
    """Save data to JSON file."""
    _ensure_logs_dir()
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def log_unmatched_product(
    raw_name: str,
    price: float,
    store: Optional[str] = None,
    confidence: float = 0.0
):
    """
    Log a product that failed to match any dictionary entry.

    Increments count if already logged, otherwise adds new entry.
    """
    if not raw_name or len(raw_name) < 2:
        return

    raw_name_lower = raw_name.lower().strip()
    today = datetime.now().strftime("%Y-%m-%d")

    unmatched = _load_json_file(UNMATCHED_FILE)

    # Check if product already exists
    found = False
    for entry in unmatched:
        if entry.get("raw_name", "").lower() == raw_name_lower:
            entry["count"] = entry.get("count", 1) + 1
            entry["last_seen"] = today
            entry["last_price"] = price
            if store:
                entry["store"] = store
            found = True
            break

    if not found:
        unmatched.append({
            "raw_name": raw_name,
            "price": price,
            "store": store,
            "confidence": confidence,
            "count": 1,
            "first_seen": today,
            "last_seen": today,
            "last_price": price
        })

    _save_json_file(UNMATCHED_FILE, unmatched)
    logger.debug(f"Logged unmatched product: {raw_name}")


def log_review_correction(
    receipt_id: str,
    original_total: Optional[float],
    corrected_total: float,
    correction_type: str,
    store: Optional[str] = None,
    product_count: int = 0
):
    """
    Log a receipt review correction for learning purposes.

    Args:
        receipt_id: Unique identifier for the receipt
        original_total: Original OCR total (may be None)
        corrected_total: User-provided or calculated correct total
        correction_type: "calculated" (from products sum), "manual", or "approved"
        store: Store name
        product_count: Number of products in the receipt
    """
    corrections = _load_json_file(CORRECTIONS_FILE)

    corrections.append({
        "receipt_id": receipt_id,
        "original_total": original_total,
        "corrected_total": corrected_total,
        "correction_type": correction_type,
        "store": store,
        "product_count": product_count,
        "timestamp": datetime.now().isoformat(),
        "difference": round(corrected_total - (original_total or 0), 2) if original_total else None
    })

    _save_json_file(CORRECTIONS_FILE, corrections)
    logger.info(f"Logged review correction: {receipt_id} ({correction_type})")


def get_unmatched_products() -> list:
    """Get all unmatched products."""
    return _load_json_file(UNMATCHED_FILE)


def get_unmatched_above_threshold(min_count: int = 3) -> list:
    """
    Get unmatched products that appeared at least min_count times.
    These are good candidates for adding to the dictionary.
    """
    unmatched = _load_json_file(UNMATCHED_FILE)
    return [
        entry for entry in unmatched
        if entry.get("count", 1) >= min_count
    ]


def remove_from_unmatched(raw_name: str) -> bool:
    """
    Remove a product from the unmatched list (after learning).

    Returns True if product was found and removed.
    """
    raw_name_lower = raw_name.lower().strip()
    unmatched = _load_json_file(UNMATCHED_FILE)

    original_len = len(unmatched)
    unmatched = [
        entry for entry in unmatched
        if entry.get("raw_name", "").lower() != raw_name_lower
    ]

    if len(unmatched) < original_len:
        _save_json_file(UNMATCHED_FILE, unmatched)
        logger.info(f"Removed '{raw_name}' from unmatched list")
        return True
    return False


def get_correction_stats() -> dict:
    """Get statistics about corrections."""
    corrections = _load_json_file(CORRECTIONS_FILE)

    if not corrections:
        return {
            "total_corrections": 0,
            "by_type": {},
            "by_store": {},
            "avg_difference": 0
        }

    by_type = {}
    by_store = {}
    differences = []

    for c in corrections:
        ctype = c.get("correction_type", "unknown")
        by_type[ctype] = by_type.get(ctype, 0) + 1

        store = c.get("store", "unknown")
        by_store[store] = by_store.get(store, 0) + 1

        if c.get("difference") is not None:
            differences.append(abs(c["difference"]))

    return {
        "total_corrections": len(corrections),
        "by_type": by_type,
        "by_store": by_store,
        "avg_difference": round(sum(differences) / len(differences), 2) if differences else 0
    }
