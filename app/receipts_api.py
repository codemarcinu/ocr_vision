"""REST API for receipt browsing and editing."""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dependencies import ReceiptRepoDep, StoreRepoDep, DbSession

router = APIRouter(prefix="/receipts", tags=["receipts"])


class UpdateReceiptRequest(BaseModel):
    store_raw: Optional[str] = None
    receipt_date: Optional[str] = None  # YYYY-MM-DD
    total_final: Optional[float] = None


class UpdateItemRequest(BaseModel):
    name_raw: Optional[str] = None
    name_normalized: Optional[str] = None
    price_final: Optional[float] = None
    category_id: Optional[int] = None


@router.get("")
async def list_receipts(
    repo: ReceiptRepoDep,
    limit: int = 20,
    offset: int = 0,
    store_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """List receipts with pagination and filters."""
    d_from = None
    d_to = None
    if date_from:
        try:
            d_from = date.fromisoformat(date_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format")
    if date_to:
        try:
            d_to = date.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format")

    receipts, total = await repo.get_recent_paginated(
        limit=min(limit, 100),
        offset=offset,
        store_id=store_id,
        date_from=d_from,
        date_to=d_to,
    )

    return {
        "items": [
            {
                "id": str(r.id),
                "source_file": r.source_file,
                "receipt_date": r.receipt_date.isoformat() if r.receipt_date else None,
                "store": r.store.name if r.store else r.store_raw,
                "store_id": r.store_id,
                "total_ocr": float(r.total_ocr) if r.total_ocr else None,
                "total_final": float(r.total_final) if r.total_final else None,
                "needs_review": r.needs_review,
                "item_count": len(r.items) if hasattr(r, 'items') and r.items else None,
                "processed_at": r.processed_at.isoformat() if r.processed_at else None,
            }
            for r in receipts
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{receipt_id}")
async def get_receipt_detail(receipt_id: UUID, repo: ReceiptRepoDep):
    """Get receipt with all items."""
    receipt = await repo.get_with_items(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    return {
        "id": str(receipt.id),
        "source_file": receipt.source_file,
        "receipt_date": receipt.receipt_date.isoformat() if receipt.receipt_date else None,
        "store": receipt.store.name if receipt.store else receipt.store_raw,
        "store_id": receipt.store_id,
        "store_raw": receipt.store_raw,
        "total_ocr": float(receipt.total_ocr) if receipt.total_ocr else None,
        "total_calculated": float(receipt.total_calculated) if receipt.total_calculated else None,
        "total_final": float(receipt.total_final) if receipt.total_final else None,
        "needs_review": receipt.needs_review,
        "review_reasons": receipt.review_reasons,
        "processed_at": receipt.processed_at.isoformat() if receipt.processed_at else None,
        "items": [
            {
                "id": item.id,
                "name_raw": item.name_raw,
                "name_normalized": item.name_normalized,
                "price_final": float(item.price_final) if item.price_final else 0,
                "price_original": float(item.price_original) if item.price_original else None,
                "discount_amount": float(item.discount_amount) if item.discount_amount else None,
                "category": item.category.name if item.category else None,
                "category_id": item.category_id,
                "confidence": float(item.confidence) if item.confidence else None,
                "warning": item.warning,
                "match_method": item.match_method,
            }
            for item in (receipt.items or [])
        ],
    }


@router.put("/{receipt_id}")
async def update_receipt(
    receipt_id: UUID,
    request: UpdateReceiptRequest,
    repo: ReceiptRepoDep,
):
    """Update receipt metadata."""
    kwargs = {}
    if request.store_raw is not None:
        kwargs["store_raw"] = request.store_raw
    if request.receipt_date is not None:
        try:
            kwargs["receipt_date"] = date.fromisoformat(request.receipt_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
    if request.total_final is not None:
        kwargs["total_final"] = Decimal(str(request.total_final))

    if not kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")

    receipt = await repo.update(receipt_id, **kwargs)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    return {"id": str(receipt.id), "updated": list(kwargs.keys())}


@router.put("/{receipt_id}/items/{item_id}")
async def update_receipt_item(
    receipt_id: UUID,
    item_id: int,
    request: UpdateItemRequest,
    repo: ReceiptRepoDep,
):
    """Update a receipt item."""
    kwargs = {}
    if request.name_raw is not None:
        kwargs["name_raw"] = request.name_raw
    if request.name_normalized is not None:
        kwargs["name_normalized"] = request.name_normalized
    if request.price_final is not None:
        kwargs["price_final"] = Decimal(str(request.price_final))
    if request.category_id is not None:
        kwargs["category_id"] = request.category_id

    if not kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")

    item = await repo.update_item(item_id, **kwargs)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    return {"id": item.id, "receipt_id": str(receipt_id), "updated": list(kwargs.keys())}


@router.delete("/{receipt_id}")
async def delete_receipt(receipt_id: UUID, repo: ReceiptRepoDep):
    """Delete a receipt."""
    deleted = await repo.delete(receipt_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return {"deleted": True, "id": str(receipt_id)}
