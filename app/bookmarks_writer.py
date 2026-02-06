"""Obsidian markdown writer for bookmarks."""

from datetime import datetime
from pathlib import Path

from app.config import settings


def write_bookmarks_index(bookmarks: list) -> Path:
    """Write bookmark index to Obsidian vault.

    Args:
        bookmarks: List of Bookmark model instances.

    Returns:
        Path to the index file.
    """
    output_dir = settings.BOOKMARKS_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    file_path = output_dir / "index.md"

    lines = [
        "---",
        f"updated: \"{datetime.now().isoformat()}\"",
        "---",
        "",
        "# Zakładki",
        "",
    ]

    # Group by status
    by_status: dict[str, list] = {"pending": [], "read": [], "archived": []}
    for b in bookmarks:
        status = b.status if b.status in by_status else "pending"
        by_status[status].append(b)

    if by_status["pending"]:
        lines.append("## Do przeczytania")
        lines.append("")
        for b in by_status["pending"]:
            title = b.title or b.url[:60]
            date_str = b.created_at.strftime("%Y-%m-%d")
            lines.append(f"- [ ] [{title}]({b.url}) ({date_str})")
        lines.append("")

    if by_status["read"]:
        lines.append("## Przeczytane")
        lines.append("")
        for b in by_status["read"]:
            title = b.title or b.url[:60]
            date_str = b.created_at.strftime("%Y-%m-%d")
            lines.append(f"- [x] [{title}]({b.url}) ({date_str})")
        lines.append("")

    lines.append(f"Łącznie: {len(bookmarks)} zakładek")

    file_path.write_text("\n".join(lines), encoding="utf-8")
    return file_path
