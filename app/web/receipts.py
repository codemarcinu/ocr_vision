"""Receipt web routes."""

from datetime import date
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.dependencies import ReceiptRepoDep, StoreRepoDep
from app.web.helpers import _htmx_trigger, templates

router = APIRouter()


@router.get("/app/paragony/", response_class=HTMLResponse)
async def receipt_list(
    request: Request,
    repo: ReceiptRepoDep,
    store_repo: StoreRepoDep,
    store_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    offset: int = 0,
    limit: int = 20,
):
    sid = int(store_id) if store_id and store_id.strip() else None
    d_from = date.fromisoformat(date_from) if date_from and date_from.strip() else None
    d_to = date.fromisoformat(date_to) if date_to and date_to.strip() else None

    receipts, total = await repo.get_recent_paginated(
        limit=limit, offset=offset, store_id=sid,
        date_from=d_from, date_to=d_to,
    )
    stores = await store_repo.get_all_with_aliases()

    ctx = {
        "request": request,
        "receipts": receipts,
        "total": total,
        "stores": stores,
        "filters": {"store_id": sid or "", "date_from": date_from or "", "date_to": date_to or ""},
        "offset": offset,
        "limit": limit,
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("receipts/partials/table_rows.html", ctx)
    return templates.TemplateResponse("receipts/list.html", ctx)


@router.get("/app/paragony/upload", response_class=HTMLResponse)
async def receipt_upload_page(request: Request):
    return templates.TemplateResponse("receipts/upload.html", {"request": request})


@router.post("/app/paragony/upload", response_class=HTMLResponse)
async def receipt_upload(request: Request, file: UploadFile = File(...)):
    if not file.filename:
        return templates.TemplateResponse("receipts/partials/upload_result.html", {
            "request": request, "success": False, "error": "Brak nazwy pliku",
        })

    suffix = Path(file.filename).suffix.lower()
    if suffix not in settings.SUPPORTED_FORMATS:
        return templates.TemplateResponse("receipts/partials/upload_result.html", {
            "request": request, "success": False,
            "error": f"Nieobsługiwany format. Dozwolone: {', '.join(settings.SUPPORTED_FORMATS)}",
        })

    settings.ensure_directories()
    safe_name = PurePosixPath(file.filename).name
    if not safe_name or safe_name.startswith('.'):
        return templates.TemplateResponse("receipts/partials/upload_result.html", {
            "request": request, "success": False, "error": "Nieprawidłowa nazwa pliku",
        })
    inbox_path = settings.INBOX_DIR / safe_name
    with open(inbox_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Process using the existing pipeline
    from app.main import _process_file
    result = await _process_file(inbox_path)

    return templates.TemplateResponse("receipts/partials/upload_result.html", {
        "request": request,
        "success": result.success,
        "result": result,
        "error": result.error,
    })


@router.get("/app/paragony/{receipt_id}", response_class=HTMLResponse)
async def receipt_detail(request: Request, receipt_id: UUID, repo: ReceiptRepoDep):
    receipt = await repo.get_with_items(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Paragon nie znaleziony")
    return templates.TemplateResponse("receipts/detail.html", {
        "request": request, "receipt": receipt,
    })


@router.post("/app/paragony/{receipt_id}/update", response_class=HTMLResponse)
async def receipt_update(
    request: Request,
    receipt_id: UUID,
    repo: ReceiptRepoDep,
    store_raw: Optional[str] = Form(None),
    receipt_date: Optional[str] = Form(None),
    total_final: Optional[str] = Form(None),
):
    kwargs = {}
    if store_raw:
        kwargs["store_raw"] = store_raw
    if receipt_date:
        kwargs["receipt_date"] = date.fromisoformat(receipt_date)
    if total_final:
        kwargs["total_final"] = Decimal(total_final)

    if kwargs:
        await repo.update(receipt_id, **kwargs)

    receipt = await repo.get_with_items(receipt_id)
    response = templates.TemplateResponse("receipts/detail.html", {
        "request": request, "receipt": receipt,
    })
    response.headers.update(_htmx_trigger("Paragon zaktualizowany"))
    return response


@router.post("/app/paragony/{receipt_id}/items/{item_id}/update", response_class=HTMLResponse)
async def receipt_item_update(
    request: Request,
    receipt_id: UUID,
    item_id: int,
    repo: ReceiptRepoDep,
    name_normalized: Optional[str] = Form(None),
    price_final: Optional[str] = Form(None),
):
    kwargs = {}
    if name_normalized:
        kwargs["name_normalized"] = name_normalized
    if price_final:
        kwargs["price_final"] = Decimal(price_final)

    if kwargs:
        await repo.update_item(item_id, **kwargs)

    receipt = await repo.get_with_items(receipt_id)
    response = templates.TemplateResponse("receipts/partials/items_table.html", {
        "request": request, "receipt": receipt,
    })
    response.headers.update(_htmx_trigger("Produkt zaktualizowany"))
    return response


@router.post("/app/paragony/{receipt_id}/delete")
async def receipt_delete(receipt_id: UUID, repo: ReceiptRepoDep):
    await repo.delete(receipt_id)
    return RedirectResponse(url="/app/paragony/", status_code=303)
