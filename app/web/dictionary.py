"""Dictionary web routes."""

from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.dependencies import FeedbackRepoDep, ProductRepoDep
from app.web.helpers import _htmx_trigger, templates

router = APIRouter()


@router.get("/app/slownik/", response_class=HTMLResponse)
async def dictionary_page(
    request: Request,
    feedback_repo: FeedbackRepoDep,
    tab: str = "unmatched",
    search: Optional[str] = None,
    category: Optional[str] = None,
    store: Optional[str] = None,
):
    from app.dictionary_api import load_products, load_shortcuts

    ctx = {"request": request, "tab": tab}

    if tab == "unmatched":
        ctx["unmatched"] = await feedback_repo.get_unmatched(limit=50)
    elif tab == "dictionary":
        products, categories = _filter_products(load_products(), search, category)
        ctx["products"] = products
        ctx["categories"] = sorted(categories)
        ctx["search"] = search or ""
        ctx["category"] = category or ""
    elif tab == "shortcuts":
        shortcuts_data = load_shortcuts()
        shortcuts = []
        stores = []
        for store_key, store_shortcuts in shortcuts_data.items():
            if store_key == "metadata" or not isinstance(store_shortcuts, dict):
                continue
            stores.append(store_key)
            if store and store_key.lower() != store.lower():
                continue
            for shortcut, full_name in store_shortcuts.items():
                shortcuts.append({
                    "shortcut": shortcut,
                    "full_name": full_name,
                    "store": store_key,
                })
        ctx["shortcuts"] = shortcuts
        ctx["stores"] = sorted(stores)
        ctx["store"] = store or ""

    return templates.TemplateResponse("dictionary/index.html", ctx)


@router.get("/app/slownik/partials/unmatched", response_class=HTMLResponse)
async def dictionary_unmatched(request: Request, feedback_repo: FeedbackRepoDep):
    unmatched = await feedback_repo.get_unmatched(limit=50)
    return templates.TemplateResponse("dictionary/partials/unmatched_list.html", {
        "request": request, "unmatched": unmatched,
    })


@router.get("/app/slownik/partials/products", response_class=HTMLResponse)
async def dictionary_products_partial(
    request: Request,
    search: Optional[str] = None,
    category: Optional[str] = None,
):
    from app.dictionary_api import load_products

    products, categories = _filter_products(load_products(), search, category)
    return templates.TemplateResponse("dictionary/partials/products_list.html", {
        "request": request,
        "products": products,
        "categories": sorted(categories),
        "search": search or "",
        "category": category or "",
    })


@router.get("/app/slownik/partials/shortcuts", response_class=HTMLResponse)
async def dictionary_shortcuts_partial(
    request: Request,
    store: Optional[str] = None,
):
    from app.dictionary_api import load_shortcuts

    shortcuts_data = load_shortcuts()
    shortcuts = []
    stores = []
    for store_key, store_shortcuts in shortcuts_data.items():
        if store_key == "metadata" or not isinstance(store_shortcuts, dict):
            continue
        stores.append(store_key)
        if store and store_key.lower() != store.lower():
            continue
        for shortcut, full_name in store_shortcuts.items():
            shortcuts.append({
                "shortcut": shortcut,
                "full_name": full_name,
                "store": store_key,
            })
    return templates.TemplateResponse("dictionary/partials/shortcuts_list.html", {
        "request": request,
        "shortcuts": shortcuts,
        "stores": sorted(stores),
        "store": store or "",
    })


@router.post("/app/slownik/learn/{raw_name}", response_class=HTMLResponse)
async def dictionary_learn(
    request: Request,
    raw_name: str,
    feedback_repo: FeedbackRepoDep,
    product_repo: ProductRepoDep,
    normalized_name: str = Form(...),
    category: str = Form("Inne"),
):
    # Create or find the product, then mark unmatched as learned
    product = await product_repo.get_by_normalized_name(normalized_name)
    if not product:
        product = await product_repo.create_with_variant(
            normalized_name=normalized_name,
            raw_name=raw_name,
        )
    else:
        await product_repo.add_variant(product.id, raw_name)
    await feedback_repo.learn_product(raw_name, product.id)

    unmatched = await feedback_repo.get_unmatched(limit=50)
    response = templates.TemplateResponse("dictionary/partials/unmatched_list.html", {
        "request": request, "unmatched": unmatched,
    })
    response.headers.update(_htmx_trigger(f"Nauczone: {raw_name}"))
    return response


def _filter_products(
    products_data: dict,
    search: Optional[str],
    category: Optional[str],
) -> tuple[list[dict], list[str]]:
    """Filter products from dictionary data. Returns (products, categories)."""
    products = []
    categories = []
    for cat_key, cat_data in products_data.items():
        if cat_key == "metadata" or not isinstance(cat_data, dict):
            continue
        if "products" not in cat_data:
            continue
        categories.append(cat_key)
        if category and cat_key != category:
            continue
        for product in cat_data["products"]:
            normalized = product.get("normalized_name", "")
            raw_names = product.get("raw_names", [])
            if search:
                sl = search.lower()
                if not (sl in normalized.lower() or any(sl in rn.lower() for rn in raw_names)):
                    continue
            products.append({
                "normalized_name": normalized,
                "category": cat_key,
                "raw_names": raw_names,
                "typical_price": product.get("typical_price_pln"),
            })
    return products, categories
