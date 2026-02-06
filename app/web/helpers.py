"""Shared utilities for Web UI routes."""

import json
from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# Store emoji map
STORE_EMOJIS = {
    "biedronka": "🐞", "lidl": "🔵", "kaufland": "🔴",
    "zabka": "🐸", "auchan": "🟠", "carrefour": "🔷",
    "netto": "🟡", "dino": "🦕", "rossmann": "🩷",
    "lewiatan": "🟢", "stokrotka": "🌼",
}

# Category emoji map
CATEGORY_EMOJIS = {
    "Nabial": "🥛", "Nabiał": "🥛", "Pieczywo": "🍞", "Mieso": "🥩", "Mięso": "🥩",
    "Wedliny": "🥓", "Wędliny": "🥓", "Ryby": "🐟", "Warzywa": "🥬",
    "Owoce": "🍎", "Napoje": "🥤", "Alkohol": "🍺",
    "Napoje gorace": "☕", "Napoje gorące": "☕", "Slodycze": "🍫", "Słodycze": "🍫",
    "Przekaski": "🥨", "Przekąski": "🥨", "Produkty sypkie": "🌾",
    "Przyprawy": "🧂", "Konserwy": "🥫", "Mrozonki": "🧊", "Mrożonki": "🧊",
    "Dania gotowe": "🍲", "Chemia": "🧴", "Kosmetyki": "💄",
    "Dla dzieci": "👶", "Dla zwierzat": "🐾", "Dla zwierząt": "🐾",
    "Inne": "📦",
}


def _store_emoji(name: str) -> str:
    if not name:
        return "🏪"
    key = name.lower().split(",")[0].split(" ")[0].strip()
    return STORE_EMOJIS.get(key, "🏪")


def _category_emoji(name: str) -> str:
    return CATEGORY_EMOJIS.get(name, "📦")


def _htmx_trigger(message: str, msg_type: str = "success") -> dict:
    return {"HX-Trigger": json.dumps({"showToast": {"message": message, "type": msg_type}})}


# Register template globals
templates.env.globals.update({
    "store_emoji": _store_emoji,
    "category_emoji": _category_emoji,
})
