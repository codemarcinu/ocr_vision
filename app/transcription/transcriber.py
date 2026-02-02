"""Faster-Whisper transcription service with GPU memory management."""

import asyncio
import gc
import logging
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

# Lazy import to avoid loading torch at module level
_whisper_model = None
_model_lock = asyncio.Lock()


def _clear_gpu_memory():
    """Clear GPU memory after transcription."""
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            logger.debug("GPU memory cleared")
    except ImportError:
        pass


async def _get_whisper_model():
    """Get or create Whisper model instance (singleton with lock)."""
    global _whisper_model

    async with _model_lock:
        if _whisper_model is not None:
            return _whisper_model

        # Import inside function to avoid loading at startup
        from faster_whisper import WhisperModel

        device = settings.WHISPER_DEVICE
        compute_type = settings.WHISPER_COMPUTE_TYPE
        model_size = settings.WHISPER_MODEL

        # Auto-detect device
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        logger.info(f"Loading Whisper model: {model_size} on {device} ({compute_type})")

        # Run model loading in thread pool (blocking operation)
        loop = asyncio.get_event_loop()
        _whisper_model = await loop.run_in_executor(
            None,
            lambda: WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                download_root=str(settings.TRANSCRIPTION_TEMP_DIR / "models"),
            )
        )

        logger.info(f"Whisper model loaded: {model_size}")
        return _whisper_model


async def _unload_whisper_model():
    """Unload Whisper model and free GPU memory."""
    global _whisper_model

    async with _model_lock:
        if _whisper_model is not None:
            del _whisper_model
            _whisper_model = None
            _clear_gpu_memory()
            logger.info("Whisper model unloaded, GPU memory freed")


class TranscriberService:
    """Service for transcribing audio/video files using Faster-Whisper."""

    def __init__(
        self,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ):
        """
        Initialize transcriber service.

        Args:
            progress_callback: Optional callback(percent, status) for progress updates
        """
        self.progress_callback = progress_callback or (lambda p, s: None)

    async def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> Tuple[str, List[dict], dict]:
        """
        Transcribe audio file using Faster-Whisper.

        Args:
            audio_path: Path to audio file
            language: Optional language code (None for auto-detect)

        Returns:
            Tuple of (full_text, segments, info_dict)
            - full_text: Complete transcription text
            - segments: List of segment dicts with start, end, text
            - info_dict: Metadata (language, confidence, duration, word_count)
        """
        start_time = time.time()
        audio_path = Path(audio_path)

        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        logger.info(f"Starting transcription: {audio_path.name}")
        self.progress_callback(0, "loading_model")

        # Get or load model
        model = await _get_whisper_model()

        # Use configured language or None for auto-detect
        transcribe_language = language or settings.WHISPER_LANGUAGE or None

        self.progress_callback(5, "transcribing")
        logger.info(f"Transcribing with language: {transcribe_language or 'auto-detect'}")

        # Run transcription in thread pool (blocking operation)
        loop = asyncio.get_event_loop()

        def _run_transcription():
            return model.transcribe(
                str(audio_path),
                language=transcribe_language,
                beam_size=5,
                vad_filter=True,
            )

        segments_generator, info = await loop.run_in_executor(None, _run_transcription)

        # Process segments (generator consumption must be in thread pool too)
        def _process_segments():
            segments_list = []
            full_text_parts = []
            duration = getattr(info, 'duration', 0) or 0

            for segment in segments_generator:
                seg_data = {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip(),
                }
                segments_list.append(seg_data)
                full_text_parts.append(segment.text.strip())

                # Update progress based on segment end time
                if duration > 0:
                    percent = min(95, int((segment.end / duration) * 90) + 5)
                    # Note: can't call async callback from thread, we'll update after

            return segments_list, " ".join(full_text_parts)

        segments_list, full_text = await loop.run_in_executor(None, _process_segments)

        self.progress_callback(95, "finalizing")

        # Calculate metadata
        processing_time = time.time() - start_time
        word_count = len(full_text.split())
        detected_language = getattr(info, 'language', transcribe_language or 'unknown')
        language_probability = getattr(info, 'language_probability', 0.0)
        duration = getattr(info, 'duration', 0) or 0

        info_dict = {
            "detected_language": detected_language,
            "language_probability": language_probability,
            "confidence": language_probability,
            "duration_seconds": int(duration),
            "word_count": word_count,
            "processing_time_sec": round(processing_time, 2),
            "segment_count": len(segments_list),
        }

        logger.info(
            f"Transcription complete: {word_count} words, "
            f"{len(segments_list)} segments, {processing_time:.1f}s"
        )

        # Unload model if configured
        if settings.WHISPER_UNLOAD_AFTER_USE:
            await _unload_whisper_model()

        self.progress_callback(100, "completed")
        return full_text, segments_list, info_dict

    async def transcribe_with_subtitles(
        self,
        audio_path: str,
        subtitle_path: str,
    ) -> Tuple[str, List[dict], dict]:
        """
        Use existing subtitles instead of transcribing.

        Parses VTT/SRT subtitle files downloaded from YouTube.

        Args:
            audio_path: Path to audio file (for duration metadata)
            subtitle_path: Path to VTT or SRT subtitle file

        Returns:
            Same format as transcribe()
        """
        subtitle_path = Path(subtitle_path)
        audio_path = Path(audio_path)

        if not subtitle_path.exists():
            raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")

        logger.info(f"Using existing subtitles: {subtitle_path.name}")
        self.progress_callback(10, "parsing_subtitles")

        # Parse subtitles
        segments_list = await self._parse_subtitles(subtitle_path)
        full_text = " ".join(seg["text"] for seg in segments_list)

        # Try to get duration from audio file
        duration = 0
        if audio_path.exists():
            try:
                from mutagen import File as MutagenFile
                audio = MutagenFile(str(audio_path))
                if audio and audio.info:
                    duration = int(audio.info.length)
            except Exception:
                pass

        # Fallback to last segment end time
        if duration == 0 and segments_list:
            duration = int(segments_list[-1]["end"])

        word_count = len(full_text.split())

        info_dict = {
            "detected_language": self._detect_subtitle_language(subtitle_path),
            "language_probability": 1.0,
            "confidence": 1.0,
            "duration_seconds": duration,
            "word_count": word_count,
            "processing_time_sec": 0.0,
            "segment_count": len(segments_list),
            "source": "subtitles",
        }

        logger.info(f"Subtitles parsed: {word_count} words, {len(segments_list)} segments")
        self.progress_callback(100, "completed")

        return full_text, segments_list, info_dict

    async def _parse_subtitles(self, subtitle_path: Path) -> List[dict]:
        """Parse VTT or SRT subtitle file into segments."""
        import re

        content = subtitle_path.read_text(encoding="utf-8")
        segments = []

        # Detect format by extension or content
        is_vtt = subtitle_path.suffix.lower() == ".vtt" or content.startswith("WEBVTT")

        if is_vtt:
            # VTT format: 00:00:00.000 --> 00:00:05.000
            pattern = r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})\s*\n(.+?)(?=\n\n|\n\d{2}:\d{2}|\Z)"
        else:
            # SRT format: 00:00:00,000 --> 00:00:05,000
            pattern = r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n(.+?)(?=\n\n|\n\d+\n|\Z)"

        matches = re.findall(pattern, content, re.DOTALL)

        for start_str, end_str, text in matches:
            # Convert timestamp to seconds
            start = self._timestamp_to_seconds(start_str)
            end = self._timestamp_to_seconds(end_str)

            # Clean text (remove HTML tags, extra whitespace)
            text = re.sub(r"<[^>]+>", "", text)
            text = " ".join(text.split())

            if text:
                segments.append({
                    "start": start,
                    "end": end,
                    "text": text,
                })

        return segments

    def _timestamp_to_seconds(self, timestamp: str) -> float:
        """Convert VTT/SRT timestamp to seconds."""
        # Handle both . and , as decimal separator
        timestamp = timestamp.replace(",", ".")
        parts = timestamp.split(":")

        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        elif len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
        else:
            return float(timestamp)

    def _detect_subtitle_language(self, subtitle_path: Path) -> str:
        """Detect language from subtitle filename (e.g., video.pl.vtt)."""
        name = subtitle_path.stem.lower()
        if ".pl" in name or name.endswith(".pl"):
            return "pl"
        elif ".en" in name or name.endswith(".en"):
            return "en"
        return "unknown"


# Convenience function for direct use
async def transcribe_audio(
    audio_path: str,
    language: Optional[str] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Tuple[str, List[dict], dict]:
    """
    Transcribe audio file.

    Args:
        audio_path: Path to audio file
        language: Optional language code
        progress_callback: Optional progress callback

    Returns:
        Tuple of (full_text, segments, info_dict)
    """
    service = TranscriberService(progress_callback=progress_callback)
    return await service.transcribe(audio_path, language)
