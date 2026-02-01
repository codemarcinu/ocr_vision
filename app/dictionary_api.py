"""API endpoints for managing product dictionary."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dictionary", tags=["dictionary"])

DICTIONARIES_PATH = Path(__file__).parent / "dictionaries"
PRODUCTS_FILE = DICTIONARIES_PATH / "products.json"
STORES_FILE = DICTIONARIES_PATH / "stores.json"
SHORTCUTS_FILE = DICTIONARIES_PATH / "product_shortcuts.json"


# ============================================================
# Pydantic models
# ============================================================

class AddProductRequest(BaseModel):
    """Request to add a new product variant to dictionary."""
    raw_name: str = Field(..., description="Raw product name from receipt", min_length=2)
    normalized_name: str = Field(..., description="Normalized product name", min_length=2)
    category: str = Field(..., description="Category key (e.g., 'nabiał', 'mięso')")


class AddStoreRequest(BaseModel):
    """Request to add a new store alias."""
    alias: str = Field(..., description="Store name variant", min_length=2)
    normalized_name: str = Field(..., description="Normalized store name", min_length=2)


class AddShortcutRequest(BaseModel):
    """Request to add a product shortcut."""
    shortcut: str = Field(..., description="Product shortcut/abbreviation", min_length=2)
    full_name: str = Field(..., description="Full product name", min_length=2)
    store: str = Field(..., description="Store name (lowercase)", min_length=2)


class ShortcutInfo(BaseModel):
    """Shortcut information."""
    shortcut: str
    full_name: str
    store: str


class ProductInfo(BaseModel):
    """Product information."""
    normalized_name: str
    category: str
    raw_names: list[str]
    typical_price: Optional[float] = None


class StoreInfo(BaseModel):
    """Store information."""
    normalized_name: str
    aliases: list[str]


class DictionaryStats(BaseModel):
    """Dictionary statistics."""
    total_products: int
    total_raw_names: int
    total_categories: int
    total_stores: int
    total_store_aliases: int
    categories: list[str]
    stores: list[str]


class UnmatchedProduct(BaseModel):
    """Unmatched product from OCR."""
    raw_name: str
    price: float
    date: str
    store: Optional[str]
    count: int = 1


# ============================================================
# Helper functions
# ============================================================

def load_products() -> dict:
    """Load products dictionary."""
    with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_products(data: dict) -> None:
    """Save products dictionary."""
    data["metadata"]["updated"] = datetime.now().isoformat()
    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Clear cache
    from app.dictionaries import _products_index
    import app.dictionaries
    app.dictionaries._products_index = None


def load_stores() -> dict:
    """Load stores dictionary."""
    with open(STORES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_stores(data: dict) -> None:
    """Save stores dictionary."""
    with open(STORES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Clear cache
    import app.dictionaries
    app.dictionaries._stores_dict = None


# ============================================================
# API Endpoints
# ============================================================

@router.get("/stats", response_model=DictionaryStats)
async def get_dictionary_stats():
    """Get dictionary statistics."""
    products_data = load_products()
    stores_data = load_stores()

    total_products = 0
    total_raw_names = 0
    categories = []

    for key, value in products_data.items():
        if key == "metadata" or not isinstance(value, dict):
            continue
        if "products" in value:
            categories.append(key)
            for product in value["products"]:
                total_products += 1
                total_raw_names += len(product.get("raw_names", []))

    stores = stores_data.get("stores", {})
    total_store_aliases = sum(len(aliases) for aliases in stores.values())

    return DictionaryStats(
        total_products=total_products,
        total_raw_names=total_raw_names,
        total_categories=len(categories),
        total_stores=len(stores),
        total_store_aliases=total_store_aliases,
        categories=categories,
        stores=list(stores.keys())
    )


@router.get("/products", response_model=list[ProductInfo])
async def list_products(category: Optional[str] = None, search: Optional[str] = None):
    """List products, optionally filtered by category or search term."""
    data = load_products()
    results = []

    for cat_key, cat_data in data.items():
        if cat_key == "metadata" or not isinstance(cat_data, dict):
            continue
        if "products" not in cat_data:
            continue
        if category and cat_key != category:
            continue

        for product in cat_data["products"]:
            normalized = product.get("normalized_name", "")
            raw_names = product.get("raw_names", [])

            # Search filter
            if search:
                search_lower = search.lower()
                if not (search_lower in normalized.lower() or
                        any(search_lower in rn.lower() for rn in raw_names)):
                    continue

            results.append(ProductInfo(
                normalized_name=normalized,
                category=cat_key,
                raw_names=raw_names,
                typical_price=product.get("typical_price_pln")
            ))

    return results


@router.post("/products/add")
async def add_product_variant(request: AddProductRequest):
    """
    Add a new raw_name variant to an existing product,
    or create a new product if normalized_name doesn't exist.
    """
    data = load_products()

    # Validate category exists
    if request.category not in data:
        raise HTTPException(
            status_code=400,
            detail=f"Category '{request.category}' not found. Available: {[k for k in data.keys() if k != 'metadata']}"
        )

    category_data = data[request.category]
    if "products" not in category_data:
        category_data["products"] = []

    # Check if normalized_name exists
    found = False
    for product in category_data["products"]:
        if product.get("normalized_name") == request.normalized_name:
            # Add raw_name if not already present
            raw_names = product.get("raw_names", [])
            raw_name_lower = request.raw_name.lower()
            if not any(rn.lower() == raw_name_lower for rn in raw_names):
                raw_names.append(request.raw_name)
                product["raw_names"] = raw_names
                found = True
                logger.info(f"Added variant '{request.raw_name}' to product '{request.normalized_name}'")
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Variant '{request.raw_name}' already exists for product '{request.normalized_name}'"
                )
            break

    if not found:
        # Create new product
        new_product = {
            "raw_names": [request.raw_name],
            "normalized_name": request.normalized_name,
            "default_unit": "g",
            "typical_price_pln": None
        }
        category_data["products"].append(new_product)
        logger.info(f"Created new product '{request.normalized_name}' in category '{request.category}'")

    save_products(data)

    return {
        "success": True,
        "message": f"Added '{request.raw_name}' → '{request.normalized_name}' in {request.category}"
    }


@router.delete("/products/{category}/{normalized_name}")
async def delete_product(category: str, normalized_name: str):
    """Delete a product from dictionary."""
    data = load_products()

    if category not in data:
        raise HTTPException(status_code=404, detail=f"Category '{category}' not found")

    products = data[category].get("products", [])
    original_len = len(products)

    data[category]["products"] = [
        p for p in products if p.get("normalized_name") != normalized_name
    ]

    if len(data[category]["products"]) == original_len:
        raise HTTPException(status_code=404, detail=f"Product '{normalized_name}' not found")

    save_products(data)
    return {"success": True, "message": f"Deleted product '{normalized_name}'"}


@router.get("/stores", response_model=list[StoreInfo])
async def list_stores():
    """List all stores with aliases."""
    data = load_stores()
    stores = data.get("stores", {})

    return [
        StoreInfo(normalized_name=name, aliases=aliases)
        for name, aliases in stores.items()
    ]


@router.post("/stores/add")
async def add_store_alias(request: AddStoreRequest):
    """Add a new store alias."""
    data = load_stores()
    stores = data.get("stores", {})

    if request.normalized_name not in stores:
        stores[request.normalized_name] = []

    alias_lower = request.alias.lower()
    if alias_lower not in [a.lower() for a in stores[request.normalized_name]]:
        stores[request.normalized_name].append(request.alias.lower())
        data["stores"] = stores
        save_stores(data)
        return {"success": True, "message": f"Added alias '{request.alias}' for store '{request.normalized_name}'"}
    else:
        raise HTTPException(status_code=400, detail=f"Alias '{request.alias}' already exists")


@router.get("/categories")
async def list_categories():
    """List all available categories."""
    data = load_products()
    categories = []

    for key, value in data.items():
        if key == "metadata" or not isinstance(value, dict):
            continue
        if "products" in value:
            categories.append({
                "key": key,
                "id": value.get("category_id", ""),
                "description": value.get("description", ""),
                "products_count": len(value.get("products", []))
            })

    return categories


@router.get("/unmatched")
async def get_unmatched_products():
    """
    Get list of products that failed to match in recent processing.
    Sorted by count (descending) to show most common first.
    """
    from app.feedback_logger import get_unmatched_products
    unmatched = get_unmatched_products()
    # Sort by count descending
    return sorted(unmatched, key=lambda x: x.get("count", 1), reverse=True)


@router.get("/unmatched/suggestions")
async def get_unmatched_suggestions(min_count: int = 3):
    """
    Get unmatched products that appeared at least min_count times.
    These are good candidates for adding to the dictionary.
    """
    from app.feedback_logger import get_unmatched_above_threshold
    return get_unmatched_above_threshold(min_count)


@router.get("/corrections/stats")
async def get_correction_stats():
    """Get statistics about receipt corrections."""
    from app.feedback_logger import get_correction_stats
    return get_correction_stats()


@router.post("/learn/{raw_name}")
async def learn_from_unmatched(
    raw_name: str,
    normalized_name: str,
    category: str
):
    """
    Learn a new product from unmatched list.
    Adds to dictionary and removes from unmatched.
    """
    from app.feedback_logger import remove_from_unmatched

    # Add to dictionary
    request = AddProductRequest(
        raw_name=raw_name,
        normalized_name=normalized_name,
        category=category
    )
    await add_product_variant(request)

    # Remove from unmatched using feedback_logger
    remove_from_unmatched(raw_name)

    return {"success": True, "message": f"Learned: '{raw_name}' → '{normalized_name}'"}


# ============================================================
# Shortcuts API
# ============================================================

def load_shortcuts() -> dict:
    """Load shortcuts dictionary."""
    if not SHORTCUTS_FILE.exists():
        return {"metadata": {"version": "1.0"}}
    with open(SHORTCUTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_shortcuts(data: dict) -> None:
    """Save shortcuts dictionary."""
    data["metadata"]["updated"] = datetime.now().isoformat()
    with open(SHORTCUTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Clear cache
    from app.dictionaries import clear_shortcuts_cache
    clear_shortcuts_cache()


@router.get("/shortcuts", response_model=list[ShortcutInfo])
async def list_shortcuts(store: Optional[str] = None):
    """List all shortcuts, optionally filtered by store."""
    data = load_shortcuts()
    results = []

    for store_key, shortcuts in data.items():
        if store_key == "metadata" or not isinstance(shortcuts, dict):
            continue
        if store and store_key.lower() != store.lower():
            continue

        for shortcut, full_name in shortcuts.items():
            results.append(ShortcutInfo(
                shortcut=shortcut,
                full_name=full_name,
                store=store_key
            ))

    return results


@router.post("/shortcuts/add")
async def add_shortcut(request: AddShortcutRequest):
    """Add a new product shortcut."""
    data = load_shortcuts()
    store_lower = request.store.lower()

    if store_lower not in data:
        data[store_lower] = {}

    shortcut_lower = request.shortcut.lower().replace(" ", "")

    if shortcut_lower in data[store_lower]:
        raise HTTPException(
            status_code=400,
            detail=f"Shortcut '{request.shortcut}' already exists for store '{request.store}'"
        )

    data[store_lower][shortcut_lower] = request.full_name.lower()
    save_shortcuts(data)

    logger.info(f"Added shortcut: {shortcut_lower} → {request.full_name} for {store_lower}")

    return {
        "success": True,
        "message": f"Added shortcut '{request.shortcut}' → '{request.full_name}' for {request.store}"
    }


@router.delete("/shortcuts/{store}/{shortcut}")
async def delete_shortcut(store: str, shortcut: str):
    """Delete a product shortcut."""
    data = load_shortcuts()
    store_lower = store.lower()
    shortcut_lower = shortcut.lower().replace(" ", "")

    if store_lower not in data:
        raise HTTPException(status_code=404, detail=f"Store '{store}' not found")

    if shortcut_lower not in data[store_lower]:
        raise HTTPException(status_code=404, detail=f"Shortcut '{shortcut}' not found for store '{store}'")

    del data[store_lower][shortcut_lower]
    save_shortcuts(data)

    return {"success": True, "message": f"Deleted shortcut '{shortcut}' from {store}"}
