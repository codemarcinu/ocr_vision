"""OpenWeatherMap API client for weather queries."""

import logging
from datetime import datetime
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE_PARAMS = {
    "appid": "",  # filled at call time
    "units": "",
    "lang": "pl",
}


def _common_params(city: str) -> dict:
    return {
        "q": city,
        "appid": settings.OPENWEATHER_API_KEY,
        "units": settings.WEATHER_UNITS,
        "lang": "pl",
    }


def _handle_http_error(e: httpx.HTTPStatusError, city: str) -> str:
    if e.response.status_code == 401:
        logger.error("OpenWeatherMap: nieprawidłowy klucz API")
        return "Nieprawidłowy klucz API OpenWeatherMap"
    if e.response.status_code == 404:
        logger.warning(f"OpenWeatherMap: nie znaleziono miasta '{city}'")
        return f"Nie znaleziono miasta: {city}"
    logger.error(f"OpenWeatherMap HTTP error: {e}")
    return f"Błąd HTTP: {e.response.status_code}"


async def get_weather(city: Optional[str] = None) -> tuple[Optional[dict], Optional[str]]:
    """Fetch current weather from OpenWeatherMap.

    Returns:
        Tuple of (weather_data dict, error message or None).
    """
    if not settings.OPENWEATHER_API_KEY:
        return None, "OPENWEATHER_API_KEY nie jest ustawiony"

    city = city or settings.WEATHER_CITY

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params=_common_params(city),
            )
            response.raise_for_status()
            data = response.json()

        main = data.get("main", {})
        wind = data.get("wind", {})
        weather_desc = data.get("weather", [{}])[0].get("description", "")

        return {
            "city_name": data.get("name", city),
            "temp": main.get("temp"),
            "feels_like": main.get("feels_like"),
            "humidity": main.get("humidity"),
            "pressure": main.get("pressure"),
            "description": weather_desc,
            "wind_speed": wind.get("speed"),
            "clouds": data.get("clouds", {}).get("all"),
        }, None

    except httpx.TimeoutException:
        logger.warning(f"OpenWeatherMap timeout for city: {city}")
        return None, "Timeout połączenia z OpenWeatherMap"
    except httpx.HTTPStatusError as e:
        return None, _handle_http_error(e, city)
    except Exception as e:
        logger.error(f"OpenWeatherMap error: {e}")
        return None, f"Błąd pogody: {e}"


async def get_forecast(city: Optional[str] = None) -> tuple[Optional[list[dict]], Optional[str]]:
    """Fetch 5-day / 3-hour forecast from OpenWeatherMap.

    Returns:
        Tuple of (list of forecast entries, error message or None).
        Each entry: {datetime, temp, feels_like, humidity, description, wind_speed, rain_mm}.
    """
    if not settings.OPENWEATHER_API_KEY:
        return None, "OPENWEATHER_API_KEY nie jest ustawiony"

    city = city or settings.WEATHER_CITY

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params=_common_params(city),
            )
            response.raise_for_status()
            data = response.json()

        entries = []
        for item in data.get("list", []):
            main = item.get("main", {})
            wind = item.get("wind", {})
            weather_desc = item.get("weather", [{}])[0].get("description", "")
            rain_3h = item.get("rain", {}).get("3h", 0)

            entries.append({
                "datetime": item.get("dt_txt", ""),
                "temp": main.get("temp"),
                "feels_like": main.get("feels_like"),
                "humidity": main.get("humidity"),
                "description": weather_desc,
                "wind_speed": wind.get("speed"),
                "rain_mm": rain_3h,
            })

        city_name = data.get("city", {}).get("name", city)
        # Tag entries with city for formatting
        for e in entries:
            e["city_name"] = city_name

        return entries, None

    except httpx.TimeoutException:
        logger.warning(f"OpenWeatherMap forecast timeout for city: {city}")
        return None, "Timeout połączenia z OpenWeatherMap"
    except httpx.HTTPStatusError as e:
        return None, _handle_http_error(e, city)
    except Exception as e:
        logger.error(f"OpenWeatherMap forecast error: {e}")
        return None, f"Błąd prognozy: {e}"
