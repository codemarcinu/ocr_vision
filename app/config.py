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
    # Uses qwen2.5vl:7b by default - qwen3-vl:8b has thinking mode issues
    OCR_FALLBACK_MODEL: str = os.getenv("OCR_FALLBACK_MODEL", "qwen2.5vl:7b")

    # Model keep-alive settings (how long to keep models loaded in memory)
    # Vision models use more VRAM, so shorter keep-alive
    VISION_MODEL_KEEP_ALIVE: str = os.getenv("VISION_MODEL_KEEP_ALIVE", "10m")
    TEXT_MODEL_KEEP_ALIVE: str = os.getenv("TEXT_MODEL_KEEP_ALIVE", "30m")

    # Whether to unload models after use (set to true for low VRAM systems)
    UNLOAD_MODELS_AFTER_USE: bool = os.getenv("UNLOAD_MODELS_AFTER_USE", "false").lower() == "true"

    # PDF parallel processing (number of pages to process concurrently)
    PDF_MAX_PARALLEL_PAGES: int = int(os.getenv("PDF_MAX_PARALLEL_PAGES", "2"))

    # Google Cloud Vision (ultimate fallback when all local models fail)
    # Requires: GOOGLE_APPLICATION_CREDENTIALS env var pointing to service account JSON
    GOOGLE_VISION_ENABLED: bool = os.getenv("GOOGLE_VISION_ENABLED", "false").lower() == "true"

    # Web Summarizer configuration
    SUMMARIZER_MODEL: str = os.getenv("SUMMARIZER_MODEL", "")  # Empty = use CLASSIFIER_MODEL (for EN)
    SUMMARIZER_MODEL_PL: str = os.getenv(
        "SUMMARIZER_MODEL_PL",
        "SpeakLeash/bielik-11b-v3.0-instruct:Q5_K_M"
    )  # Polish language model for article summarization
    SUMMARIZER_ENABLED: bool = os.getenv("SUMMARIZER_ENABLED", "true").lower() == "true"
    RSS_FETCH_INTERVAL_HOURS: int = int(os.getenv("RSS_FETCH_INTERVAL_HOURS", "4"))
    RSS_MAX_ARTICLES_PER_FEED: int = int(os.getenv("RSS_MAX_ARTICLES_PER_FEED", "10"))

    # Article categories for summarization
    ARTICLE_CATEGORIES: list = [
        "Technologia",
        "Biznes",
        "Nauka",
        "Polityka",
        "Kultura",
        "Sport",
        "Zdrowie",
        "Inne",
    ]

    # ==========================================================================
    # Transcription Agent Configuration
    # ==========================================================================
    TRANSCRIPTION_ENABLED: bool = os.getenv("TRANSCRIPTION_ENABLED", "true").lower() == "true"

    # Faster-Whisper settings
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "medium")  # tiny, base, small, medium, large-v3
    WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "cuda")  # cuda, cpu, auto
    WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", "float16")  # float16, int8, int8_float16
    WHISPER_LANGUAGE: str = os.getenv("WHISPER_LANGUAGE", "")  # empty = auto-detect
    WHISPER_UNLOAD_AFTER_USE: bool = os.getenv("WHISPER_UNLOAD_AFTER_USE", "true").lower() == "true"

    # LLM for knowledge extraction from transcriptions
    # Empty = use CLASSIFIER_MODEL
    TRANSCRIPTION_NOTE_MODEL: str = os.getenv("TRANSCRIPTION_NOTE_MODEL", "")

    # Auto-generate note after transcription completes
    TRANSCRIPTION_AUTO_GENERATE_NOTE: bool = os.getenv(
        "TRANSCRIPTION_AUTO_GENERATE_NOTE", "true"
    ).lower() == "true"

    # yt-dlp settings
    YTDLP_FORMAT: str = os.getenv("YTDLP_FORMAT", "bestaudio[ext=m4a]/bestaudio/best")
    YTDLP_MAX_FILESIZE_MB: int = int(os.getenv("YTDLP_MAX_FILESIZE_MB", "500"))

    # Processing limits
    TRANSCRIPTION_MAX_DURATION_HOURS: int = int(os.getenv("TRANSCRIPTION_MAX_DURATION_HOURS", "4"))
    TRANSCRIPTION_MAX_CONCURRENT_JOBS: int = int(os.getenv("TRANSCRIPTION_MAX_CONCURRENT_JOBS", "1"))
    TRANSCRIPTION_CLEANUP_HOURS: int = int(os.getenv("TRANSCRIPTION_CLEANUP_HOURS", "24"))

    # Transcription categories for note extraction
    TRANSCRIPTION_CATEGORIES: list = [
        "Edukacja",
        "Technologia",
        "Biznes",
        "Rozrywka",
        "Nauka",
        "Wywiad",
        "Podcast",
        "Tutorial",
        "Prezentacja",
        "Inne",
    ]

    # Paths
    BASE_DIR: Path = Path("/data")
    INBOX_DIR: Path = BASE_DIR / "paragony" / "inbox"
    PROCESSED_DIR: Path = BASE_DIR / "paragony" / "processed"
    VAULT_DIR: Path = BASE_DIR / "vault"
    RECEIPTS_DIR: Path = VAULT_DIR / "paragony"
    LOGS_DIR: Path = VAULT_DIR / "logs"
    # Summaries can be in a separate location (configurable via env or volume mount)
    SUMMARIES_DIR: Path = Path(os.getenv("SUMMARIES_DIR", str(BASE_DIR / "summaries")))
    PANTRY_FILE: Path = VAULT_DIR / "spiżarnia.md"
    ERROR_LOG_FILE: Path = LOGS_DIR / "ocr-errors.md"

    # Transcription paths
    TRANSCRIPTION_OUTPUT_DIR: Path = Path(os.getenv(
        "TRANSCRIPTION_OUTPUT_DIR", str(BASE_DIR / "transcriptions")
    ))
    TRANSCRIPTION_TEMP_DIR: Path = Path(os.getenv(
        "TRANSCRIPTION_TEMP_DIR", "/tmp/transcriptions"
    ))

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
            cls.LOGS_DIR,
            cls.SUMMARIES_DIR,
            cls.TRANSCRIPTION_OUTPUT_DIR,
            cls.TRANSCRIPTION_TEMP_DIR,
        ]:
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
