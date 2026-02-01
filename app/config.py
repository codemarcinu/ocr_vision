"""Configuration settings for Smart Pantry Tracker."""

from pathlib import Path
from typing import Optional
import os


class Settings:
    """Application settings."""

    # Ollama configuration
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
    OCR_MODEL: str = os.getenv("OCR_MODEL", "qwen2.5vl:7b")
    CLASSIFIER_MODEL: str = os.getenv("CLASSIFIER_MODEL", "qwen2.5:7b")

    # OCR backend: "vision" (LLM vision model) or "paddle" (PaddleOCR + LLM)
    OCR_BACKEND: str = os.getenv("OCR_BACKEND", "vision")

    # Paths
    BASE_DIR: Path = Path("/data")
    INBOX_DIR: Path = BASE_DIR / "paragony" / "inbox"
    PROCESSED_DIR: Path = BASE_DIR / "paragony" / "processed"
    VAULT_DIR: Path = BASE_DIR / "vault"
    RECEIPTS_DIR: Path = VAULT_DIR / "paragony"
    LOGS_DIR: Path = VAULT_DIR / "logs"
    PANTRY_FILE: Path = VAULT_DIR / "spiżarnia.md"
    ERROR_LOG_FILE: Path = LOGS_DIR / "ocr-errors.md"

    # Validation
    PRICE_WARNING_THRESHOLD: float = 100.0  # Flag prices above this

    # Supported image formats (including PDF)
    SUPPORTED_FORMATS: tuple = (".png", ".jpg", ".jpeg", ".webp", ".pdf")

    # Telegram Bot configuration
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: int = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
    BOT_ENABLED: bool = os.getenv("BOT_ENABLED", "true").lower() == "true"

    # Categories for products
    CATEGORIES: list = [
        "Nabiał",
        "Pieczywo",
        "Mięso i wędliny",
        "Warzywa i owoce",
        "Napoje",
        "Słodycze",
        "Produkty suche",
        "Mrożonki",
        "Chemia",
        "Inne"
    ]

    @classmethod
    def ensure_directories(cls) -> None:
        """Create all required directories if they don't exist."""
        for directory in [
            cls.INBOX_DIR,
            cls.PROCESSED_DIR,
            cls.RECEIPTS_DIR,
            cls.LOGS_DIR
        ]:
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
