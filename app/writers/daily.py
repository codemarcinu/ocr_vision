"""Obsidian markdown writer for daily notes (voice memo aggregation)."""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from app.config import settings

logger = logging.getLogger(__name__)

_DAY_NAMES_PL = [
    "Poniedziałek", "Wtorek", "Środa", "Czwartek",
    "Piątek", "Sobota", "Niedziela",
]


class DailyNoteWriter:
    """Aggregates voice memos into daily note files (one file per day)."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or settings.DAILY_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_daily_path(self, date: datetime) -> Path:
        return self.output_dir / f"{date.strftime('%Y-%m-%d')}.md"

    def append_voice_memo(
        self,
        title: str,
        content: str,
        timestamp: Optional[datetime] = None,
    ) -> Path:
        """Append a voice memo entry to the daily note.

        If the daily note doesn't exist, creates it with frontmatter.
        If it exists, appends a new timestamped section.

        Args:
            title: Memo title (e.g., "Notatka głosowa")
            content: Transcribed text
            timestamp: When the memo was recorded (defaults to now)

        Returns:
            Path to the daily note file
        """
        timestamp = timestamp or datetime.now()
        daily_path = self._get_daily_path(timestamp)

        if not daily_path.exists():
            self._create_daily_file(daily_path, timestamp)

        # Build the memo section
        time_str = timestamp.strftime("%H:%M")
        section = f"\n## {time_str} - {title}\n\n{content}\n"

        with open(daily_path, "a", encoding="utf-8") as f:
            f.write(section)

        # Update frontmatter timestamp
        self._update_frontmatter(daily_path, timestamp)

        logger.info(f"Appended voice memo to daily note: {daily_path}")
        return daily_path

    def _create_daily_file(self, path: Path, date: datetime) -> None:
        """Create a new daily note with frontmatter."""
        date_str = date.strftime("%Y-%m-%d")
        day_name = _DAY_NAMES_PL[date.weekday()]

        frontmatter = {
            "date": date_str,
            "type": "daily",
            "tags": ["daily", "voice-memo"],
            "created": date.isoformat(),
            "updated": date.isoformat(),
        }

        lines = [
            "---",
            yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).strip(),
            "---",
            "",
            f"# {day_name}, {date_str}",
            "",
        ]

        path.write_text("\n".join(lines), encoding="utf-8")

    def _update_frontmatter(self, path: Path, timestamp: datetime) -> None:
        """Update the 'updated' timestamp in frontmatter."""
        content = path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return

        parts = content.split("---", 2)
        if len(parts) < 3:
            return

        new_timestamp = timestamp.isoformat()
        parts[1] = re.sub(
            r"updated:.*",
            f"updated: '{new_timestamp}'",
            parts[1],
        )
        path.write_text("---".join(parts), encoding="utf-8")
