"""Analytics web routes."""

import csv
import io
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

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

    # KPI cards - always load for the top summary
    kpi = {}
    try:
        weekly = await repo.get_weekly_comparison()
        kpi["weekly"] = weekly
    except Exception:
        kpi["weekly"] = {}
    try:
        discounts = await repo.get_discount_summary()
        kpi["discounts"] = discounts
    except Exception:
        kpi["discounts"] = {}
    try:
        stores = await repo.get_spending_by_store()
        kpi["top_store"] = stores[0] if stores else None
    except Exception:
        kpi["top_store"] = None

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
        "request": request, "tab": tab, "data": data, "kpi": kpi,
        "data_json": json.dumps(data, default=str),
    }

    # Tabs use regular <a href> navigation, not HTMX — always return full page
    return templates.TemplateResponse("analytics/index.html", ctx)


@router.get("/app/analityka/export")
async def analytics_export(
    repo: AnalyticsRepoDep,
    type: str = "monthly",
):
    """Export analytics data as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)

    if type == "stores":
        writer.writerow(["Sklep", "Wydatki (zł)", "Paragony", "Średni paragon (zł)"])
        rows = await repo.get_spending_by_store()
        for r in rows:
            writer.writerow([
                r.get("store", ""),
                f"{r.get('total_spent', 0):.2f}",
                r.get("receipt_count", 0),
                f"{r.get('avg_receipt', 0):.2f}",
            ])
    elif type == "categories":
        writer.writerow(["Kategoria", "Wydatki (zł)", "Produkty", "Średnia cena (zł)"])
        rows = await repo.get_spending_by_category()
        for r in rows:
            writer.writerow([
                r.get("category", ""),
                f"{r.get('total_spent', 0):.2f}",
                r.get("item_count", 0),
                f"{r.get('avg_price', 0):.2f}",
            ])
    else:  # monthly
        writer.writerow(["Miesiąc", "Sklep", "Kategoria", "Wydatki (zł)"])
        rows = await repo.get_monthly_breakdown()
        for r in rows:
            writer.writerow([
                r.get("month", ""),
                r.get("store", ""),
                r.get("category", ""),
                f"{r.get('total', 0):.2f}",
            ])

    output.seek(0)
    filename = f"analityka_{type}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


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
