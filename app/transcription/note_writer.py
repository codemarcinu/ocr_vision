"""Obsidian markdown writer for transcription notes with rich metadata."""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml

from app.config import settings
from app.transcription.extractor import ExtractionResult

logger = logging.getLogger(__name__)


def _sanitize_filename(title: str) -> str:
    """Sanitize title for use in filename."""
    sanitized = re.sub(r'[<>:"/\\|?*]', "", title)
    sanitized = re.sub(r"\s+", "_", sanitized)
    return sanitized.strip("_.")[:100] or "transcription"


def _format_duration(seconds: Optional[int]) -> str:
    """Format duration in human-readable format."""
    if not seconds:
        return ""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _build_tags(
    tags: Optional[List[str]],
    category: Optional[str],
    source_type: str,
) -> List[str]:
    """Build tag list with standard prefixes."""
    result = ["transcription", source_type]

    if category:
        cat_tag = category.lower().replace(" ", "-")
        result.append(cat_tag)

    if tags:
        result.extend(tags)

    # Remove duplicates while preserving order
    return list(dict.fromkeys(result))


class TranscriptionNoteWriter:
    """Service for generating Obsidian markdown notes from transcriptions."""

    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize note writer.

        Args:
            output_dir: Directory for output files (default: TRANSCRIPTION_OUTPUT_DIR)
        """
        self.output_dir = output_dir or settings.TRANSCRIPTION_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_note(
        self,
        title: str,
        extraction: ExtractionResult,
        source_type: str = "youtube",
        source_url: Optional[str] = None,
        channel_name: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        transcription_text: Optional[str] = None,
        include_transcription: bool = False,
    ) -> Path:
        """
        Write transcription note to Obsidian vault.

        Args:
            title: Video/audio title
            extraction: ExtractionResult from knowledge extractor
            source_type: 'youtube', 'url', or 'file'
            source_url: Original source URL
            channel_name: YouTube channel or author name
            duration_seconds: Duration in seconds
            transcription_text: Full transcription (optional, for appendix)
            include_transcription: Whether to include full transcription in note

        Returns:
            Path to created file
        """
        # Generate filename
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_title = _sanitize_filename(title)
        filename = f"{date_str}_{safe_title}.md"
        output_path = self.output_dir / filename

        # Handle duplicates
        counter = 1
        while output_path.exists():
            filename = f"{date_str}_{safe_title}_{counter}.md"
            output_path = self.output_dir / filename
            counter += 1

        # Build YAML frontmatter
        frontmatter = {
            "title": title,
            "type": "transcription",
            "source_type": source_type,
            "source_url": source_url,
            "channel": channel_name,
            "duration": _format_duration(duration_seconds),
            "duration_seconds": duration_seconds,
            "category": extraction.category,
            "tags": _build_tags(extraction.tags, extraction.category, source_type),
            "entities": extraction.entities,
            "topics": extraction.topics,
            "created": datetime.now().isoformat(),
            "model": extraction.model_used,
            "language": extraction.language,
        }

        # Remove None/empty values
        frontmatter = {k: v for k, v in frontmatter.items() if v}

        # Build markdown content
        lines = [
            "---",
            yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).strip(),
            "---",
            "",
            f"# {title}",
            "",
        ]

        # Metadata section
        if channel_name or duration_seconds:
            if channel_name:
                lines.append(f"**Kanał:** {channel_name}")
            if duration_seconds:
                lines.append(f"**Czas trwania:** {_format_duration(duration_seconds)}")
            if extraction.category:
                lines.append(f"**Kategoria:** {extraction.category}")
            lines.append("")

        # Summary section
        lines.extend([
            "## Podsumowanie",
            "",
            extraction.summary_text,
            "",
        ])

        # Topics section
        if extraction.topics:
            lines.extend([
                "## Główne tematy",
                "",
            ])
            for topic in extraction.topics:
                lines.append(f"- {topic}")
            lines.append("")

        # Key points section
        if extraction.key_points:
            lines.extend([
                "## Kluczowe punkty",
                "",
            ])
            for point in extraction.key_points:
                # Ensure bullet format
                if not point.startswith("-"):
                    point = f"- {point}"
                lines.append(point)
            lines.append("")

        # Action items section
        if extraction.action_items:
            lines.extend([
                "## Zadania do wykonania",
                "",
            ])
            for item in extraction.action_items:
                lines.append(f"- [ ] {item}")
            lines.append("")

        # Entities section (as Obsidian wiki links)
        if extraction.entities:
            lines.extend([
                "## Powiązane",
                "",
            ])
            for entity in extraction.entities:
                lines.append(f"- [[{entity}]]")
            lines.append("")

        # Full transcription (optional appendix)
        if include_transcription and transcription_text:
            lines.extend([
                "---",
                "",
                "## Pełna transkrypcja",
                "",
                "<details>",
                "<summary>Rozwiń transkrypcję</summary>",
                "",
                transcription_text,
                "",
                "</details>",
                "",
            ])

        # Source link footer
        lines.extend([
            "---",
        ])
        if source_url:
            lines.append(f"Źródło: [{title}]({source_url})")

        content = "\n".join(lines)

        # Write file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Created transcription note: {output_path}")
        return output_path

    def write_index(self) -> Path:
        """
        Write/update index file listing all transcription notes.

        Returns:
            Path to index file
        """
        index_path = self.output_dir / "index.md"

        # Get all transcription notes (sorted by modification time, newest first)
        note_files = sorted(
            [f for f in self.output_dir.glob("*.md") if f.name != "index.md"],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        # Build index content
        lines = [
            "---",
            f"updated: {datetime.now().isoformat()}",
            "---",
            "",
            "# Transkrypcje",
            "",
            "## Ostatnie notatki",
            "",
        ]

        for f in note_files[:30]:  # Show last 30
            lines.append(f"- [[{f.stem}]]")

        lines.append("")
        lines.append(f"Łącznie: {len(note_files)} notatek")

        content = "\n".join(lines)

        with open(index_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Updated transcription index: {index_path}")
        return index_path


def write_transcription_note(
    title: str,
    extraction: ExtractionResult,
    source_type: str = "youtube",
    source_url: Optional[str] = None,
    channel_name: Optional[str] = None,
    duration_seconds: Optional[int] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    Convenience function to write a transcription note.

    Returns:
        Path to created file
    """
    writer = TranscriptionNoteWriter(output_dir=output_dir)
    return writer.write_note(
        title=title,
        extraction=extraction,
        source_type=source_type,
        source_url=source_url,
        channel_name=channel_name,
        duration_seconds=duration_seconds,
    )
