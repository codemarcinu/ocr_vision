"""REST API for pantry management."""

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dependencies import PantryRepoDep, StoreRepoDep

router = APIRouter(prefix="/pantry", tags=["pantry"])


class ConsumeRequest(BaseModel):
    item_ids: list[int]


class AddItemRequest(BaseModel):
    name: str
    category: Optional[str] = None
    store: Optional[str] = None
    purchase_date: Optional[str] = None  # YYYY-MM-DD
    quantity: float = 1.0


@router.get("/items")
async def get_pantry_items(
    repo: PantryRepoDep,
    q: Optional[str] = None,
    include_consumed: bool = False,
):
    """Get pantry items, optionally grouped by category."""
    if q:
        items = await repo.search(q, include_consumed=include_consumed)
    elif include_consumed:
        items = list(await repo.get_all(limit=500))
    else:
        items = await repo.get_all_active()

    result = []
    for item in items:
        result.append({
            "id": item.id,
            "name": item.name,
            "category": item.category.name if item.category else "Inne",
            "category_id": item.category_id,
            "store": item.store.name if item.store else None,
            "store_id": item.store_id,
            "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
            "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
            "quantity": float(item.quantity) if item.quantity else 1.0,
            "is_consumed": item.is_consumed,
            "consumed_at": item.consumed_at.isoformat() if item.consumed_at else None,
        })

    return result


@router.get("/grouped")
async def get_pantry_grouped(repo: PantryRepoDep):
    """Get pantry items grouped by category."""
    grouped = await repo.get_grouped_by_category()
    result = {}
    for category_name, items in grouped.items():
        result[category_name] = [
            {
                "id": item.id,
                "name": item.name,
                "store": item.store.name if item.store else None,
                "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                "expiry_date": item.expiry_date.isoformat() if item.expiry_date else None,
                "quantity": float(item.quantity) if item.quantity else 1.0,
                "is_consumed": item.is_consumed,
            }
            for item in items
        ]
    return result


@router.get("/stats")
async def get_pantry_stats(repo: PantryRepoDep):
    """Get pantry statistics."""
    return await repo.get_stats()


@router.post("/consume")
async def consume_items(request: ConsumeRequest, repo: PantryRepoDep):
    """Mark multiple items as consumed."""
    if not request.item_ids:
        raise HTTPException(status_code=400, detail="No item IDs provided")

    count = await repo.consume_items_batch(request.item_ids)
    return {"consumed": count, "requested": len(request.item_ids)}


@router.post("/restore/{item_id}")
async def restore_item(item_id: int, repo: PantryRepoDep):
    """Restore a consumed item."""
    item = await repo.restore_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"id": item.id, "name": item.name, "restored": True}


@router.post("/items")
async def add_manual_item(request: AddItemRequest, repo: PantryRepoDep):
    """Add an item to pantry manually."""
    from app.db.connection import get_session
    from app.db.repositories.products import ProductRepository
    from app.db.models import Category
    from sqlalchemy import select

    purchase = date.today()
    if request.purchase_date:
        try:
            purchase = date.fromisoformat(request.purchase_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Find category by name
    category_id = None
    if request.category:
        stmt = select(Category).where(Category.name == request.category)
        result = await repo.session.execute(stmt)
        cat = result.scalar_one_or_none()
        if cat:
            category_id = cat.id

    # Find store by name
    store_id = None
    if request.store:
        from app.db.models import Store
        stmt = select(Store).where(Store.name == request.store)
        result = await repo.session.execute(stmt)
        store = result.scalar_one_or_none()
        if store:
            store_id = store.id

    item = await repo.add_from_receipt(
        receipt_item_id=None,
        product_id=None,
        name=request.name,
        category_id=category_id,
        store_id=store_id,
        purchase_date=purchase,
        quantity=Decimal(str(request.quantity)),
    )

    return {
        "id": item.id,
        "name": item.name,
        "category_id": category_id,
        "store_id": store_id,
        "purchase_date": purchase.isoformat(),
    }


@router.get("/search")
async def search_pantry(q: str, repo: PantryRepoDep):
    """Search pantry items."""
    if not q or len(q) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters")

    items = await repo.search(q)
    return [
        {
            "id": item.id,
            "name": item.name,
            "category": item.category.name if item.category else "Inne",
            "store": item.store.name if item.store else None,
            "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
            "is_consumed": item.is_consumed,
        }
        for item in items
    ]
