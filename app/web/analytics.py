"""Analytics web routes."""

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.dependencies import AnalyticsRepoDep
from app.web.helpers import templates

router = APIRouter()


@router.get("/app/analityka/", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    repo: AnalyticsRepoDep,
    tab: str = "spending",
):
    data = {}

    if tab == "spending":
        data["monthly"] = await repo.get_monthly_breakdown()
        data["by_category"] = await repo.get_spending_by_category()
    elif tab == "stores":
        data["by_store"] = await repo.get_spending_by_store()
    elif tab == "categories":
        data["by_category"] = await repo.get_spending_by_category()
    elif tab == "trends":
        data["top_products"] = await repo.get_top_products(limit=20, by="count")

    ctx = {
        "request": request, "tab": tab, "data": data,
        "data_json": json.dumps(data, default=str),
    }

    # Tabs use regular <a href> navigation, not HTMX — always return full page
    return templates.TemplateResponse("analytics/index.html", ctx)


@router.get("/app/analityka/trends/{product_id}", response_class=HTMLResponse)
async def analytics_trends(
    request: Request, product_id: int, repo: AnalyticsRepoDep,
    months: int = 6,
):
    trends = await repo.get_price_trends(product_id, months)
    return templates.TemplateResponse("analytics/partials/trends_chart.html", {
        "request": request, "product_id": product_id,
        "trends": trends,
    })
