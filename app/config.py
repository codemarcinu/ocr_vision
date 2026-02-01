"""Configuration settings for Smart Pantry Tracker."""

from pathlib import Path
from typing import Optional
import os


class Settings:
    """Application settings."""

    # Database configuration
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://pantry:pantry123@localhost:5432/pantry"
    )
    DATABASE_POOL_SIZE: int = int(os.getenv("DATABASE_POOL_SIZE", "5"))
    DATABASE_MAX_OVERFLOW: int = int(os.getenv("DATABASE_MAX_OVERFLOW", "10"))

    # Feature flags for gradual migration
    USE_DB_DICTIONARIES: bool = os.getenv("USE_DB_DICTIONARIES", "true").lower() == "true"
    USE_DB_RECEIPTS: bool = os.getenv("USE_DB_RECEIPTS", "true").lower() == "true"
    GENERATE_OBSIDIAN_FILES: bool = os.getenv("GENERATE_OBSIDIAN_FILES", "true").lower() == "true"

    # Ollama configuration
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
    OCR_MODEL: str = os.getenv("OCR_MODEL", "qwen2.5vl:7b")
    CLASSIFIER_MODEL: str = os.getenv("CLASSIFIER_MODEL", "qwen2.5:7b")

    # A/B Testing for classifier models
    # Set CLASSIFIER_MODEL_B to enable A/B testing (runs both models and logs comparison)
    CLASSIFIER_MODEL_B: str = os.getenv("CLASSIFIER_MODEL_B", "")  # e.g., "gpt-oss:20b"
    CLASSIFIER_AB_MODE: str = os.getenv("CLASSIFIER_AB_MODE", "primary")  # "primary", "secondary", "both"
    # "primary" - use CLASSIFIER_MODEL, log B results if set
    # "secondary" - use CLASSIFIER_MODEL_B as primary
    # "both" - run both, use primary, log comparison

    # OCR backend: "vision" (LLM vision model), "paddle" (PaddleOCR + LLM), or "deepseek" (DeepSeek-OCR + LLM)
    OCR_BACKEND: str = os.getenv("OCR_BACKEND", "vision")

    # Structuring model for deepseek backend (converts OCR text to JSON)
    # If not set, uses CLASSIFIER_MODEL
    STRUCTURING_MODEL: str = os.getenv("STRUCTURING_MODEL", "")

    # Fallback model for DeepSeek-OCR when it fails (repetition loops, etc.)
    # Uses qwen3-vl:8b by default - faster and more accurate than qwen2.5vl:7b
    OCR_FALLBACK_MODEL: str = os.getenv("OCR_FALLBACK_MODEL", "qwen3-vl:8b")

    # Model keep-alive settings (how long to keep models loaded in memory)
    # Vision models use more VRAM, so shorter keep-alive
    VISION_MODEL_KEEP_ALIVE: str = os.getenv("VISION_MODEL_KEEP_ALIVE", "10m")
    TEXT_MODEL_KEEP_ALIVE: str = os.getenv("TEXT_MODEL_KEEP_ALIVE", "30m")

    # Whether to unload models after use (set to true for low VRAM systems)
    UNLOAD_MODELS_AFTER_USE: bool = os.getenv("UNLOAD_MODELS_AFTER_USE", "false").lower() == "true"

    # PDF parallel processing (number of pages to process concurrently)
    PDF_MAX_PARALLEL_PAGES: int = int(os.getenv("PDF_MAX_PARALLEL_PAGES", "2"))

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
