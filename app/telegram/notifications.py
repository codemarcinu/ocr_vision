"""Smart notifications for Telegram bot.

Daily digest with:
- Unmatched products that need mapping
- Summary statistics
- Low stock alerts (if using pantry tracking)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.telegram.formatters import escape_html, get_category_icon, get_store_emoji

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler: Optional[AsyncIOScheduler] = None


async def get_unmatched_summary() -> list[dict]:
    """Get products that failed to match in recent processing."""
    try:
        from app.feedback_logger import get_unmatched_above_threshold
        return get_unmatched_above_threshold(min_count=2)
    except Exception as e:
        logger.warning(f"Failed to get unmatched products: {e}")
        return []


async def get_inne_products_summary() -> list[dict]:
    """Get products categorized as 'Inne' in the last 7 days."""
    try:
        from app.feedback_logger import get_recent_inne_products
        return get_recent_inne_products(days=7)
    except Exception as e:
        logger.warning(f"Failed to get 'Inne' products: {e}")
        return []


async def get_weekly_stats() -> dict:
    """Get spending stats for the past week."""
    try:
        from app.telegram.handlers.stats import _calculate_stats
        return _calculate_stats("week")
    except Exception as e:
        logger.warning(f"Failed to get weekly stats: {e}")
        return {}


async def get_weekly_comparison() -> dict:
    """Get this week vs previous week spending comparison."""
    try:
        from app.db.connection import get_session
        from app.db.repositories.analytics import AnalyticsRepository

        async for session in get_session():
            repo = AnalyticsRepository(session)
            return await repo.get_weekly_comparison()
    except Exception as e:
        logger.warning(f"Failed to get weekly comparison: {e}")
        return {}


async def get_price_anomalies() -> list[dict]:
    """Get products with price anomalies (>20% above average)."""
    try:
        from app.db.connection import get_session
        from app.db.repositories.analytics import AnalyticsRepository

        async for session in get_session():
            repo = AnalyticsRepository(session)
            return await repo.get_price_anomalies(threshold_pct=20.0)
    except Exception as e:
        logger.warning(f"Failed to get price anomalies: {e}")
        return []


async def get_pending_files() -> list[str]:
    """Get files waiting in inbox."""
    inbox_dir = settings.INBOX_DIR
    if not inbox_dir.exists():
        return []

    return [
        f.name for f in inbox_dir.iterdir()
        if f.is_file() and f.suffix.lower() in settings.SUPPORTED_FORMATS
    ]


async def send_daily_digest(bot: Bot, chat_id: int, notification_settings: dict | None = None) -> None:
    """Send daily digest notification.

    Includes:
    - Pending files in inbox
    - Unmatched products that need mapping
    - Weekly spending summary
    - Weekly comparison (if enabled)
    - Price anomalies (if enabled)
    """
    ns = notification_settings or {
        "anomalies_enabled": True,
        "weekly_comparison_enabled": True,
    }
    sections = []

    # Check for pending files
    pending = await get_pending_files()
    if pending:
        sections.append({
            "icon": "📬",
            "title": "Pliki do przetworzenia",
            "items": [{"name": f, "detail": "w inbox"} for f in pending[:5]],
            "count": len(pending),
        })

    # Check for unmatched products
    unmatched = await get_unmatched_summary()
    if unmatched:
        sections.append({
            "icon": "🔍",
            "title": "Produkty do zmapowania",
            "items": [
                {"name": p.get("raw_name", "?"), "detail": f"{p.get('count', 1)}x"}
                for p in unmatched[:5]
            ],
            "count": len(unmatched),
        })

    # Check for products categorized as "Inne"
    inne = await get_inne_products_summary()
    if inne:
        # Sort by count descending, show most frequent first
        inne_sorted = sorted(inne, key=lambda x: x.get("count", 1), reverse=True)
        sections.append({
            "icon": "❓",
            "title": "Produkty w kategorii 'Inne' (ostatnie 7 dni)",
            "items": [
                {"name": p.get("raw_name", "?"), "detail": f"{p.get('count', 1)}x, {p.get('last_price', 0):.2f} zł"}
                for p in inne_sorted[:5]
            ],
            "count": len(inne_sorted),
        })

    # Weekly stats
    stats = await get_weekly_stats()
    if stats and stats.get("total", 0) > 0:
        sections.append({
            "icon": "📊",
            "title": "Podsumowanie tygodnia",
            "items": [
                {"name": "Wydatki", "detail": f"{stats.get('total', 0):.2f} zł"},
                {"name": "Paragony", "detail": str(stats.get("receipt_count", 0))},
                {"name": "Produkty", "detail": str(stats.get("product_count", 0))},
            ],
            "count": 0,
        })

    # Weekly comparison (this week vs previous)
    if not ns.get("weekly_comparison_enabled", True):
        comparison = {}
    else:
        comparison = await get_weekly_comparison()
    if comparison and comparison.get("prev_week", {}).get("total", 0) > 0:
        this_w = comparison["this_week"]
        prev_w = comparison["prev_week"]
        diff = comparison["diff"]
        diff_pct = comparison["diff_pct"]

        if diff > 0:
            trend = "📈"
            trend_text = f"+{diff:.2f} zł (+{diff_pct:.0f}%)"
        elif diff < 0:
            trend = "📉"
            trend_text = f"{diff:.2f} zł ({diff_pct:.0f}%)"
        else:
            trend = "➡️"
            trend_text = "bez zmian"

        comp_items = [
            {"name": f"{trend} Ten tydzień", "detail": f"{this_w['total']:.2f} zł"},
            {"name": "Poprzedni tydzień", "detail": f"{prev_w['total']:.2f} zł"},
            {"name": "Różnica", "detail": trend_text},
        ]

        # Add top categories
        for cat in comparison.get("top_categories", [])[:3]:
            comp_items.append({
                "name": f"  {cat['category']}",
                "detail": f"{cat['total']:.2f} zł",
            })

        sections.append({
            "icon": "📈",
            "title": "Porównanie tygodniowe",
            "items": comp_items,
            "count": 0,
        })

    # Price anomalies
    if not ns.get("anomalies_enabled", True):
        anomalies = []
    else:
        anomalies = await get_price_anomalies()
    if anomalies:
        sections.append({
            "icon": "⚠️",
            "title": "Anomalie cenowe",
            "items": [
                {
                    "name": a["product"],
                    "detail": f"{a['latest_price']:.2f} zł (śr. {a['avg_price']:.2f}, +{a['diff_pct']:.0f}%)",
                }
                for a in anomalies[:5]
            ],
            "count": len(anomalies),
        })

    # If nothing to report, skip
    if not sections:
        logger.info("Daily digest: nothing to report")
        return

    # Format message
    now = datetime.now()
    message = f"<b>🔔 Dzienne podsumowanie</b>\n"
    message += f"<i>{now.strftime('%Y-%m-%d %H:%M')}</i>\n\n"

    for section in sections:
        message += f"{section['icon']} <b>{section['title']}</b>\n"
        for item in section["items"]:
            message += f"  • {escape_html(item['name'])} - {item['detail']}\n"
        if section["count"] > 5:
            message += f"  <i>...i {section['count'] - 5} więcej</i>\n"
        message += "\n"

    # Add action buttons
    keyboard = []

    if pending:
        keyboard.append([
            InlineKeyboardButton("📬 Zobacz pliki", callback_data="pending_files"),
        ])

    if unmatched:
        keyboard.append([
            InlineKeyboardButton("🔍 Mapuj produkty", url=f"http://localhost:8000/web/dictionary"),
        ])

    keyboard.append([
        InlineKeyboardButton("📊 Statystyki", callback_data="stats"),
        InlineKeyboardButton("🏠 Spiżarnia", callback_data="pantry"),
    ])

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        )
        logger.info(f"Daily digest sent to chat {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send daily digest: {e}")


def start_scheduler(bot: Bot) -> None:
    """Start the notification scheduler.

    Sends daily digest at 9:00 AM.
    """
    global scheduler

    if not settings.BOT_ENABLED or not settings.TELEGRAM_CHAT_ID:
        logger.info("Notifications disabled (bot disabled or no chat ID)")
        return

    scheduler = AsyncIOScheduler()

    # Daily digest at 9:00 AM
    scheduler.add_job(
        send_daily_digest,
        'cron',
        hour=9,
        minute=0,
        args=[bot, settings.TELEGRAM_CHAT_ID],
        id='daily_digest',
        replace_existing=True,
    )

    # Also run once shortly after startup (5 minutes delay)
    scheduler.add_job(
        send_daily_digest,
        'date',
        run_date=datetime.now() + timedelta(minutes=5),
        args=[bot, settings.TELEGRAM_CHAT_ID],
        id='startup_digest',
    )

    # Register RSS scheduler
    from app.telegram.rss_scheduler import register_rss_scheduler
    register_rss_scheduler(scheduler, bot)

    # Register transcription scheduler
    from app.telegram.transcription_scheduler import register_transcription_scheduler
    register_transcription_scheduler(scheduler, bot)

    scheduler.start()
    logger.info("Notification scheduler started (daily at 9:00 AM)")


def stop_scheduler() -> None:
    """Stop the notification scheduler."""
    global scheduler

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Notification scheduler stopped")
    scheduler = None


async def send_test_notification(bot: Bot, chat_id: int) -> None:
    """Send a test notification (for debugging)."""
    await send_daily_digest(bot, chat_id)
