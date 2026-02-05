"""Telegram /profile handler for user personalization settings."""

import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.config import settings
from app.db.connection import get_session
from app.db.repositories.user_profile import UserProfileRepository
from app.telegram.middleware import authorized_only
from app.telegram.formatters import escape_html

logger = logging.getLogger(__name__)


# Common Polish cities
POLISH_CITIES = [
    "Kraków", "Warszawa", "Wrocław", "Poznań", "Gdańsk",
    "Łódź", "Katowice", "Lublin", "Szczecin", "Bydgoszcz",
]


def _format_profile(profile) -> str:
    """Format profile for display."""
    stores = ", ".join(profile.favorite_stores) if profile.favorite_stores else "nie ustawiono"
    return (
        f"<b>Twój profil:</b>\n\n"
        f"<b>Miasto:</b> {escape_html(profile.default_city)}\n"
        f"<b>Strefa czasowa:</b> {escape_html(profile.timezone)}\n"
        f"<b>Język:</b> {escape_html(profile.preferred_language)}\n"
        f"<b>Ulubione sklepy:</b> {escape_html(stores)}\n"
    )


def _get_profile_keyboard() -> InlineKeyboardMarkup:
    """Get inline keyboard for profile editing."""
    keyboard = [
        [InlineKeyboardButton("Zmień miasto", callback_data="profile:edit_city")],
        [InlineKeyboardButton("Zmień ulubione sklepy", callback_data="profile:edit_stores")],
        [InlineKeyboardButton("Zamknij", callback_data="profile:close")],
    ]
    return InlineKeyboardMarkup(keyboard)


def _get_city_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for city selection."""
    keyboard = []
    # Add cities in rows of 2
    for i in range(0, len(POLISH_CITIES), 2):
        row = [
            InlineKeyboardButton(POLISH_CITIES[i], callback_data=f"profile:city:{POLISH_CITIES[i]}")
        ]
        if i + 1 < len(POLISH_CITIES):
            row.append(
                InlineKeyboardButton(POLISH_CITIES[i+1], callback_data=f"profile:city:{POLISH_CITIES[i+1]}")
            )
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("Anuluj", callback_data="profile:cancel")])
    return InlineKeyboardMarkup(keyboard)


@authorized_only
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /profile command - show and edit user profile."""
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id

    try:
        async for session in get_session():
            repo = UserProfileRepository(session)

            # Get or create profile
            profile, created = await repo.get_or_create_by_telegram_id(user_id)
            await session.commit()

            if created:
                text = (
                    "<b>Profil utworzony!</b>\n\n"
                    "Ustawiono domyślne wartości. Możesz je zmienić poniżej.\n\n"
                    + _format_profile(profile)
                )
            else:
                text = _format_profile(profile)

            await update.message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=_get_profile_keyboard(),
            )

    except Exception as e:
        logger.error(f"Profile error: {e}", exc_info=True)
        await update.message.reply_text(f"Wystąpił błąd: {e}")


async def handle_profile_callback(
    query, action: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle profile-related callback queries.

    Args:
        query: CallbackQuery object
        action: Action part of callback_data (after "profile:")
        context: Bot context
    """
    user_id = query.from_user.id if query.from_user else None
    if not user_id:
        await query.answer("Błąd: brak informacji o użytkowniku")
        return

    try:
        if action == "close":
            await query.message.delete()
            await query.answer()
            return

        if action == "cancel":
            # Go back to main profile view
            async for session in get_session():
                repo = UserProfileRepository(session)
                profile = await repo.get_by_telegram_id(user_id)
                if profile:
                    await query.message.edit_text(
                        _format_profile(profile),
                        parse_mode="HTML",
                        reply_markup=_get_profile_keyboard(),
                    )
            await query.answer()
            return

        if action == "edit_city":
            await query.message.edit_text(
                "Wybierz miasto:",
                reply_markup=_get_city_keyboard(),
            )
            await query.answer()
            return

        if action.startswith("city:"):
            city = action.split(":", 1)[1]
            async for session in get_session():
                repo = UserProfileRepository(session)
                profile = await repo.get_by_telegram_id(user_id)
                if profile:
                    await repo.update_preferences(profile.id, default_city=city)
                    await session.commit()
                    profile = await repo.get_by_telegram_id(user_id)
                    await query.message.edit_text(
                        f"Miasto zmienione na: <b>{escape_html(city)}</b>\n\n"
                        + _format_profile(profile),
                        parse_mode="HTML",
                        reply_markup=_get_profile_keyboard(),
                    )
            await query.answer(f"Miasto: {city}")
            return

        if action == "edit_stores":
            await query.message.edit_text(
                "Aby ustawić ulubione sklepy, wyślij wiadomość z listą:\n\n"
                "<code>/setstores Biedronka, Lidl, Żabka</code>\n\n"
                "Sklepy oddzielone przecinkami.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Powrót", callback_data="profile:cancel")]
                ]),
            )
            await query.answer()
            return

        await query.answer("Nieznana akcja")

    except Exception as e:
        logger.error(f"Profile callback error: {e}", exc_info=True)
        await query.answer(f"Błąd: {e}")


@authorized_only
async def setstores_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setstores command - set favorite stores."""
    if not update.message or not update.effective_user:
        return

    if not context.args:
        await update.message.reply_text(
            "Użycie: <code>/setstores Biedronka, Lidl, Żabka</code>",
            parse_mode="HTML",
        )
        return

    user_id = update.effective_user.id
    stores_text = " ".join(context.args)
    stores = [s.strip() for s in stores_text.split(",") if s.strip()]

    if not stores:
        await update.message.reply_text("Podaj nazwy sklepów oddzielone przecinkami.")
        return

    try:
        async for session in get_session():
            repo = UserProfileRepository(session)
            profile, _ = await repo.get_or_create_by_telegram_id(user_id)
            await repo.update_preferences(profile.id, favorite_stores=stores)
            await session.commit()

            stores_str = ", ".join(stores)
            await update.message.reply_text(
                f"Ulubione sklepy ustawione:\n<b>{escape_html(stores_str)}</b>",
                parse_mode="HTML",
            )

    except Exception as e:
        logger.error(f"Setstores error: {e}", exc_info=True)
        await update.message.reply_text(f"Wystąpił błąd: {e}")


@authorized_only
async def setcity_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setcity command - set default city."""
    if not update.message or not update.effective_user:
        return

    if not context.args:
        await update.message.reply_text(
            "Użycie: <code>/setcity Kraków</code>",
            parse_mode="HTML",
        )
        return

    user_id = update.effective_user.id
    city = " ".join(context.args).strip()

    try:
        async for session in get_session():
            repo = UserProfileRepository(session)
            profile, _ = await repo.get_or_create_by_telegram_id(user_id)
            await repo.update_preferences(profile.id, default_city=city)
            await session.commit()

            await update.message.reply_text(
                f"Domyślne miasto ustawione:\n<b>{escape_html(city)}</b>",
                parse_mode="HTML",
            )

    except Exception as e:
        logger.error(f"Setcity error: {e}", exc_info=True)
        await update.message.reply_text(f"Wystąpił błąd: {e}")
