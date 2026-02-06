"""YouTube/URL downloader service using yt-dlp."""

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Result of a download operation."""
    audio_path: str
    subtitle_path: Optional[str] = None
    source_url: str = ""
    title: str = ""
    description: Optional[str] = None
    duration_seconds: Optional[int] = None
    channel_name: Optional[str] = None
    thumbnail_url: Optional[str] = None
    has_subtitles: bool = False


class DownloaderService:
    """Service for downloading audio from YouTube and other sources."""

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ):
        """
        Initialize downloader service.

        Args:
            output_dir: Directory for downloaded files (default: TRANSCRIPTION_TEMP_DIR)
            progress_callback: Optional callback(percent, status) for progress updates
        """
        self.output_dir = output_dir or settings.TRANSCRIPTION_TEMP_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.progress_callback = progress_callback or (lambda p, s: None)

    async def download(self, url: str) -> DownloadResult:
        """
        Download audio from URL (YouTube, etc.).

        Attempts to download subtitles first. If Polish or English subtitles
        are available, they will be used instead of transcription.

        Args:
            url: URL to download from

        Returns:
            DownloadResult with paths and metadata
        """
        from app.url_validator import validate_url
        try:
            validate_url(url)
        except ValueError as e:
            raise ValueError(f"Nieprawidłowy URL: {e}")

        import yt_dlp

        logger.info(f"Downloading from: {url}")
        self.progress_callback(0, "analyzing")

        # First, extract info without downloading
        info = await self._extract_info(url)

        title = info.get("title", "Unknown")
        duration = info.get("duration", 0) or 0

        # Check duration limit
        max_duration_hours = settings.TRANSCRIPTION_MAX_DURATION_HOURS
        if duration > max_duration_hours * 3600:
            raise ValueError(
                f"Video too long: {duration // 3600}h > {max_duration_hours}h limit"
            )

        logger.info(f"Video info: {title} ({duration // 60}:{duration % 60:02d})")
        self.progress_callback(5, "downloading")

        # Prepare output template
        safe_title = self._sanitize_filename(title)[:100]
        output_template = str(self.output_dir / f"{safe_title}.%(ext)s")

        # Configure yt-dlp options
        ydl_opts = {
            "format": settings.YTDLP_FORMAT,
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            # Subtitle options - try to get Polish or English
            "writesubtitles": True,
            "writeautomaticsubtitles": True,
            "subtitleslangs": ["pl", "en", "en-US", "en-GB"],
            "subtitlesformat": "vtt/srt/best",
            # Progress hook
            "progress_hooks": [self._create_progress_hook()],
        }

        # Download audio + subtitles
        loop = asyncio.get_event_loop()
        result_info = await loop.run_in_executor(
            None,
            lambda: self._download_with_ytdlp(url, ydl_opts)
        )

        # Find the downloaded audio file
        audio_path = await self._find_downloaded_file(safe_title)
        if not audio_path:
            raise RuntimeError(f"Download failed: audio file not found for {title}")

        # Find subtitle file if available
        subtitle_path = await self._find_subtitle_file(safe_title)

        self.progress_callback(100, "completed")

        return DownloadResult(
            audio_path=str(audio_path),
            subtitle_path=str(subtitle_path) if subtitle_path else None,
            source_url=url,
            title=result_info.get("title", title),
            description=result_info.get("description"),
            duration_seconds=result_info.get("duration", duration),
            channel_name=result_info.get("channel") or result_info.get("uploader"),
            thumbnail_url=result_info.get("thumbnail"),
            has_subtitles=subtitle_path is not None,
        )

    async def _extract_info(self, url: str) -> dict:
        """Extract video info without downloading."""
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "noplaylist": True,
        }

        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        return await loop.run_in_executor(None, _extract)

    def _download_with_ytdlp(self, url: str, ydl_opts: dict) -> dict:
        """Download using yt-dlp (blocking, run in executor)."""
        import yt_dlp

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return info
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if "Sign in to confirm" in error_msg or "HTTP Error 403" in error_msg:
                raise RuntimeError(
                    "YouTube download blocked. Try updating yt-dlp: pip install -U yt-dlp"
                ) from e
            raise

    def _create_progress_hook(self) -> Callable:
        """Create yt-dlp progress hook."""
        def hook(d):
            if d["status"] == "downloading":
                try:
                    percent_str = d.get("_percent_str", "0%").replace("%", "").strip()
                    percent = float(percent_str)
                    # Scale to 5-90% range (0-5 is analyzing, 90-100 is finalizing)
                    scaled = int(5 + (percent * 0.85))
                    self.progress_callback(scaled, "downloading")
                except (ValueError, TypeError):
                    pass
            elif d["status"] == "finished":
                self.progress_callback(90, "processing")

        return hook

    async def _find_downloaded_file(self, safe_title: str) -> Optional[Path]:
        """Find the downloaded audio file."""
        # Common audio extensions
        extensions = [".m4a", ".mp3", ".webm", ".opus", ".ogg", ".wav", ".mp4"]

        for ext in extensions:
            path = self.output_dir / f"{safe_title}{ext}"
            if path.exists():
                logger.info(f"Found audio: {path.name}")
                return path

        # Fallback: search by partial name
        for path in self.output_dir.iterdir():
            if path.stem.startswith(safe_title[:50]) and path.suffix in extensions:
                logger.info(f"Found audio (partial match): {path.name}")
                return path

        return None

    async def _find_subtitle_file(self, safe_title: str) -> Optional[Path]:
        """Find downloaded subtitle file (prefer Polish, then English)."""
        # Priority order for subtitle files
        search_patterns = [
            f"{safe_title}.pl.vtt",
            f"{safe_title}.pl.srt",
            f"{safe_title}.en.vtt",
            f"{safe_title}.en.srt",
            f"{safe_title}.en-US.vtt",
            f"{safe_title}.en-GB.vtt",
        ]

        for pattern in search_patterns:
            path = self.output_dir / pattern
            if path.exists():
                logger.info(f"Found subtitles: {path.name}")
                return path

        # Fallback: any VTT/SRT file with matching prefix
        for path in self.output_dir.iterdir():
            if path.stem.startswith(safe_title[:50]):
                if path.suffix.lower() in [".vtt", ".srt"]:
                    logger.info(f"Found subtitles (fallback): {path.name}")
                    return path

        return None

    def _sanitize_filename(self, title: str) -> str:
        """Sanitize title for use as filename."""
        # Remove/replace problematic characters
        sanitized = re.sub(r'[<>:"/\\|?*]', "", title)
        sanitized = re.sub(r"\s+", "_", sanitized)
        sanitized = sanitized.strip("_.")
        return sanitized or "download"

    async def cleanup_files(self, *paths: str) -> None:
        """Clean up downloaded files."""
        for path_str in paths:
            if path_str:
                path = Path(path_str)
                if path.exists():
                    try:
                        path.unlink()
                        logger.debug(f"Cleaned up: {path.name}")
                    except OSError as e:
                        logger.warning(f"Failed to delete {path}: {e}")


def is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube URL."""
    youtube_patterns = [
        r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=",
        r"(?:https?://)?(?:www\.)?youtube\.com/shorts/",
        r"(?:https?://)?(?:www\.)?youtu\.be/",
        r"(?:https?://)?(?:www\.)?youtube\.com/live/",
    ]
    return any(re.match(pattern, url) for pattern in youtube_patterns)


def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from URL."""
    patterns = [
        r"(?:v=|/)([a-zA-Z0-9_-]{11})(?:[?&]|$)",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"shorts/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


# Convenience function for direct use
async def download_audio(
    url: str,
    output_dir: Optional[Path] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> DownloadResult:
    """
    Download audio from URL.

    Args:
        url: URL to download from
        output_dir: Optional output directory
        progress_callback: Optional progress callback

    Returns:
        DownloadResult with paths and metadata
    """
    service = DownloaderService(
        output_dir=output_dir,
        progress_callback=progress_callback,
    )
    return await service.download(url)
