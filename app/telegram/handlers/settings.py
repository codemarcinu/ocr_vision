"""Telegram /settings handler for notification preferences."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.telegram.middleware import authorized_only

logger = logging.getLogger(__name__)

# Default settings
DEFAULT_SETTINGS = {
    "digest_hour": 9,
    "anomalies_enabled": True,
    "weekly_comparison_enabled": True,
}

HOUR_OPTIONS = [6, 8, 9, 12, 18]


def _get_settings(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Get current notification settings from bot_data."""
    if context.bot_data is None:
        context.bot_data = {}
    if "notification_settings" not in context.bot_data:
        context.bot_data["notification_settings"] = DEFAULT_SETTINGS.copy()
    return context.bot_data["notification_settings"]


def _build_settings_keyboard(s: dict) -> InlineKeyboardMarkup:
    """Build inline keyboard for settings display."""
    anomalies_icon = "✅" if s.get("anomalies_enabled", True) else "❌"
    weekly_icon = "✅" if s.get("weekly_comparison_enabled", True) else "❌"

    keyboard = [
        [InlineKeyboardButton(
            f"🕐 Godzina: {s.get('digest_hour', 9)}:00",
            callback_data="settings:hour",
        )],
        [InlineKeyboardButton(
            f"{anomalies_icon} Anomalie cenowe",
            callback_data="settings:toggle_anomalies",
        )],
        [InlineKeyboardButton(
            f"{weekly_icon} Porównanie tygodniowe",
            callback_data="settings:toggle_weekly",
        )],
        [InlineKeyboardButton("◀️ Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def _build_hour_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for hour selection."""
    rows = []
    row = []
    for h in HOUR_OPTIONS:
        row.append(InlineKeyboardButton(f"{h}:00", callback_data=f"settings:set_hour:{h}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("◀️ Wróć", callback_data="settings:back")])
    return InlineKeyboardMarkup(rows)


def _format_settings_text(s: dict) -> str:
    """Format settings display text."""
    anomalies = "włączone" if s.get("anomalies_enabled", True) else "wyłączone"
    weekly = "włączone" if s.get("weekly_comparison_enabled", True) else "wyłączone"

    return (
        "<b>⚙️ Ustawienia powiadomień</b>\n\n"
        f"🕐 Godzina digestu: <b>{s.get('digest_hour', 9)}:00</b>\n"
        f"⚠️ Anomalie cenowe: <b>{anomalies}</b>\n"
        f"📈 Porównanie tygodniowe: <b>{weekly}</b>\n\n"
        "<i>Kliknij przycisk aby zmienić ustawienie.</i>"
    )


@authorized_only
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings command - show notification settings."""
    if not update.message:
        return

    s = _get_settings(context)
    await update.message.reply_text(
        _format_settings_text(s),
        parse_mode="HTML",
        reply_markup=_build_settings_keyboard(s),
    )


async def handle_settings_callback(
    query: CallbackQuery, data: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle settings: callback queries."""
    s = _get_settings(context)
    action = data.replace("settings:", "")

    if action == "hour":
        await query.edit_message_text(
            "<b>🕐 Wybierz godzinę digestu</b>",
            parse_mode="HTML",
            reply_markup=_build_hour_keyboard(),
        )
        return

    if action.startswith("set_hour:"):
        hour = int(action.split(":")[1])
        s["digest_hour"] = hour
        context.bot_data["notification_settings"] = s

        # Reschedule the digest
        _reschedule_digest(hour)

        await query.edit_message_text(
            _format_settings_text(s),
            parse_mode="HTML",
            reply_markup=_build_settings_keyboard(s),
        )
        return

    if action == "toggle_anomalies":
        s["anomalies_enabled"] = not s.get("anomalies_enabled", True)
        context.bot_data["notification_settings"] = s
        await query.edit_message_text(
            _format_settings_text(s),
            parse_mode="HTML",
            reply_markup=_build_settings_keyboard(s),
        )
        return

    if action == "toggle_weekly":
        s["weekly_comparison_enabled"] = not s.get("weekly_comparison_enabled", True)
        context.bot_data["notification_settings"] = s
        await query.edit_message_text(
            _format_settings_text(s),
            parse_mode="HTML",
            reply_markup=_build_settings_keyboard(s),
        )
        return

    if action == "back":
        await query.edit_message_text(
            _format_settings_text(s),
            parse_mode="HTML",
            reply_markup=_build_settings_keyboard(s),
        )
        return


def _reschedule_digest(hour: int) -> None:
    """Reschedule daily digest to new hour."""
    try:
        from app.telegram.notifications import scheduler
        if scheduler and scheduler.running:
            job = scheduler.get_job("daily_digest")
            if job:
                job.reschedule(trigger="cron", hour=hour, minute=0)
                logger.info(f"Daily digest rescheduled to {hour}:00")
    except Exception as e:
        logger.warning(f"Failed to reschedule digest: {e}")
