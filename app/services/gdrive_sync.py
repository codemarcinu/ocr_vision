"""Google Drive sync status monitor.

Reads the status file written by the host-side rclone script
(scripts/sync-gdrive.sh) to expose sync health via API.
Does NOT perform any sync operations — rclone runs on the host.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class GDriveSyncStatus:
    """Read-only monitor for host-side rclone sync."""

    def __init__(self):
        self.status_file = settings.GDRIVE_SYNC_STATUS_FILE

    def get_status(self) -> dict:
        """Read the status file written by sync-gdrive.sh.

        Returns dict with last_run, success, file counts, etc.
        Falls back to unknown status if file is missing or unreadable.
        """
        if not self.status_file.exists():
            return {
                "enabled": True,
                "status": "no_data",
                "message": "Plik statusu nie znaleziony — sync jeszcze nie uruchomiony",
            }

        try:
            data = json.loads(self.status_file.read_text(encoding="utf-8"))
            data["enabled"] = True
            data["status"] = "ok" if data.get("success") else "error"
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Cannot read gdrive sync status: {e}")
            return {
                "enabled": True,
                "status": "read_error",
                "message": f"Nie można odczytać statusu: {e}",
            }

    def is_healthy(self, max_age_minutes: Optional[int] = None) -> bool:
        """Check if sync ran recently and succeeded."""
        if max_age_minutes is None:
            max_age_minutes = settings.GDRIVE_SYNC_MAX_AGE_MINUTES

        status = self.get_status()
        if status.get("status") != "ok":
            return False

        last_run = status.get("last_run")
        if not last_run:
            return False

        try:
            last_dt = datetime.fromisoformat(last_run)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age_minutes = (now - last_dt).total_seconds() / 60
            return age_minutes <= max_age_minutes
        except (ValueError, TypeError):
            return False

    def get_inbox_pending_count(self) -> int:
        """Count files in INBOX_DIR waiting for folder watcher processing."""
        inbox = settings.INBOX_DIR
        if not inbox.exists():
            return 0

        count = 0
        for f in inbox.iterdir():
            if f.is_file() and f.suffix.lower() in settings.SUPPORTED_FORMATS:
                count += 1
        return count


# Singleton
gdrive_sync_status = GDriveSyncStatus()
