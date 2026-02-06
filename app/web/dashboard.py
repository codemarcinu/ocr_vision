"""Dashboard web routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.dependencies import (
    AnalyticsRepoDep,
    ArticleRepoDep,
    FeedbackRepoDep,
    PantryRepoDep,
    ReceiptRepoDep,
)
from app.web.helpers import templates

router = APIRouter()


@router.get("/app/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    receipt_repo: ReceiptRepoDep,
    pantry_repo: PantryRepoDep,
    feedback_repo: FeedbackRepoDep,
    article_repo: ArticleRepoDep,
):
    receipt_stats = await receipt_repo.get_summary_stats()
    pantry_stats = await pantry_repo.get_stats()
    unmatched_stats = await feedback_repo.get_unmatched_stats()
    recent_receipts = await receipt_repo.get_recent(limit=5)
    recent_articles = await article_repo.get_recent(limit=5)
    unread_count = await article_repo.get_unread_count()

    is_new_user = (
        receipt_stats.get("total_receipts", 0) == 0
        and unread_count == 0
    )

    return templates.TemplateResponse("dashboard/index.html", {
        "request": request,
        "receipt_stats": receipt_stats,
        "pantry_stats": pantry_stats,
        "unmatched_count": unmatched_stats.get("total", 0) if isinstance(unmatched_stats, dict) else 0,
        "unread_articles": unread_count,
        "recent_receipts": recent_receipts,
        "recent_articles": recent_articles,
        "is_new_user": is_new_user,
    })
