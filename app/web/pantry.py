"""Pantry web routes."""

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.dependencies import PantryRepoDep
from app.web.helpers import _htmx_trigger, templates

router = APIRouter()


@router.get("/app/spizarnia/", response_class=HTMLResponse)
async def pantry_page(
    request: Request,
    repo: PantryRepoDep,
    q: Optional[str] = None,
    include_consumed: bool = False,
):
    stats = await repo.get_stats()

    if q:
        items = await repo.search(q, include_consumed=include_consumed)
        grouped = {}
        for item in items:
            cat = item.category.name if item.category else "Inne"
            grouped.setdefault(cat, []).append(item)
    else:
        grouped = await repo.get_grouped_by_category()

    ctx = {
        "request": request,
        "stats": stats,
        "grouped": grouped,
        "q": q or "",
        "include_consumed": include_consumed,
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("pantry/partials/items_grouped.html", ctx)
    return templates.TemplateResponse("pantry/index.html", ctx)


@router.post("/app/spizarnia/consume", response_class=HTMLResponse)
async def pantry_consume(request: Request, repo: PantryRepoDep, item_ids: str = Form("")):
    ids = [int(x) for x in item_ids.split(",") if x.strip().isdigit()]
    if ids:
        await repo.consume_items_batch(ids)

    grouped = await repo.get_grouped_by_category()
    stats = await repo.get_stats()
    response = templates.TemplateResponse("pantry/partials/items_grouped.html", {
        "request": request, "grouped": grouped, "stats": stats, "q": "",
    })
    response.headers.update(_htmx_trigger(f"Zużytych produktów: {len(ids)}"))
    return response


@router.post("/app/spizarnia/add", response_class=HTMLResponse)
async def pantry_add(
    request: Request,
    repo: PantryRepoDep,
    name: str = Form(...),
    category: Optional[str] = Form(None),
):
    from app.db.models import Category
    from sqlalchemy import select

    category_id = None
    if category:
        result = await repo.session.execute(select(Category).where(Category.name == category))
        cat = result.scalar_one_or_none()
        if cat:
            category_id = cat.id

    await repo.add_from_receipt(
        receipt_item_id=None, product_id=None,
        name=name, category_id=category_id,
        store_id=None, purchase_date=date.today(),
        quantity=Decimal("1"),
    )

    grouped = await repo.get_grouped_by_category()
    stats = await repo.get_stats()
    response = templates.TemplateResponse("pantry/partials/items_grouped.html", {
        "request": request, "grouped": grouped, "stats": stats, "q": "",
    })
    response.headers.update(_htmx_trigger(f"Dodano: {name}"))
    return response


@router.get("/app/spizarnia/partials/add-form", response_class=HTMLResponse)
async def pantry_add_form(request: Request):
    return templates.TemplateResponse("pantry/partials/add_form.html", {
        "request": request, "categories": settings.CATEGORIES,
    })


@router.post("/app/spizarnia/{item_id}/consume", response_class=HTMLResponse)
async def pantry_consume_single(request: Request, item_id: int, repo: PantryRepoDep):
    await repo.consume_item(item_id)

    grouped = await repo.get_grouped_by_category()
    stats = await repo.get_stats()
    response = templates.TemplateResponse("pantry/partials/items_grouped.html", {
        "request": request, "grouped": grouped, "stats": stats, "q": "",
    })
    response.headers.update(_htmx_trigger("Produkt zużytowany"))
    return response


@router.post("/app/spizarnia/{item_id}/restore", response_class=HTMLResponse)
async def pantry_restore(request: Request, item_id: int, repo: PantryRepoDep):
    await repo.restore_item(item_id)

    grouped = await repo.get_grouped_by_category()
    stats = await repo.get_stats()
    response = templates.TemplateResponse("pantry/partials/items_grouped.html", {
        "request": request, "grouped": grouped, "stats": stats, "q": "",
    })
    response.headers.update(_htmx_trigger("Produkt przywrocony"))
    return response


@router.post("/app/spizarnia/{item_id}/update", response_class=HTMLResponse)
async def pantry_update_item(
    request: Request,
    item_id: int,
    repo: PantryRepoDep,
    name: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
):
    kwargs = {}
    if name:
        kwargs["name"] = name
    if category:
        from app.db.models import Category
        from sqlalchemy import select
        result = await repo.session.execute(select(Category).where(Category.name == category))
        cat = result.scalar_one_or_none()
        if cat:
            kwargs["category_id"] = cat.id

    if kwargs:
        await repo.update(item_id, **kwargs)

    grouped = await repo.get_grouped_by_category()
    stats = await repo.get_stats()
    response = templates.TemplateResponse("pantry/partials/items_grouped.html", {
        "request": request, "grouped": grouped, "stats": stats, "q": "",
    })
    response.headers.update(_htmx_trigger("Produkt zaktualizowany"))
    return response


@router.post("/app/spizarnia/{item_id}/delete", response_class=HTMLResponse)
async def pantry_delete_item(request: Request, item_id: int, repo: PantryRepoDep):
    await repo.delete_item(item_id)

    grouped = await repo.get_grouped_by_category()
    stats = await repo.get_stats()
    response = templates.TemplateResponse("pantry/partials/items_grouped.html", {
        "request": request, "grouped": grouped, "stats": stats, "q": "",
    })
    response.headers.update(_htmx_trigger("Produkt usunięty"))
    return response


@router.get("/app/spizarnia/partials/edit-form/{item_id}", response_class=HTMLResponse)
async def pantry_edit_form(request: Request, item_id: int, repo: PantryRepoDep):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.db.models import PantryItem
    stmt = (
        select(PantryItem)
        .options(selectinload(PantryItem.category))
        .where(PantryItem.id == item_id)
    )
    result = await repo.session.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Produkt nie znaleziony")
    return templates.TemplateResponse("pantry/partials/edit_form.html", {
        "request": request, "item": item, "categories": settings.CATEGORIES,
    })
