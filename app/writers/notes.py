"""Obsidian markdown writer for personal notes."""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import settings


def _sanitize_filename(title: str) -> str:
    """Sanitize title for use as filename."""
    sanitized = re.sub(r'[<>:"/\\|?*]', "", title)
    sanitized = re.sub(r"\s+", "_", sanitized)
    return sanitized.strip("_")[:50]


def write_note_file(note, summary_backlink: Optional[str] = None) -> Path:
    """Write a personal note to Obsidian vault.

    Args:
        note: Note model instance (from DB).
        summary_backlink: Optional stem of a summary file to link back to.

    Returns:
        Path to the written file.
    """
    output_dir = settings.NOTES_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    date_str = note.created_at.strftime("%Y-%m-%d")
    title_slug = _sanitize_filename(note.title)
    filename = f"{date_str}_{title_slug}.md"
    file_path = output_dir / filename

    # Handle duplicates
    counter = 1
    while file_path.exists():
        filename = f"{date_str}_{title_slug}_{counter}.md"
        file_path = output_dir / filename
        counter += 1

    # Build YAML frontmatter
    frontmatter_lines = [
        "---",
        f"title: \"{note.title}\"",
        "type: note",
    ]

    if note.category:
        frontmatter_lines.append(f"category: {note.category}")

    # Build tags
    tags = ["note"]
    if note.category:
        tags.append(note.category.lower().replace(" ", "-"))
    if note.tags:
        tags.extend(note.tags)
    tags = list(dict.fromkeys(tags))  # Deduplicate preserving order
    frontmatter_lines.append(f"tags: [{', '.join(tags)}]")

    frontmatter_lines.append(f"created: \"{note.created_at.isoformat()}\"")
    frontmatter_lines.append(f"updated: \"{note.updated_at.isoformat()}\"")
    frontmatter_lines.append(f"id: \"{note.id}\"")
    frontmatter_lines.append("---")

    # Build content
    content_lines = [
        "\n".join(frontmatter_lines),
        "",
        f"# {note.title}",
        "",
        note.content,
    ]

    # Add summary backlink if present
    if summary_backlink:
        content_lines.extend(["", "## Źródło", ""])
        content_lines.append(f"Podsumowanie artykułu: [[{summary_backlink}]]")

    # Add source references if any
    if note.source_refs:
        content_lines.extend(["", "## Powiązane", ""])
        for ref in note.source_refs:
            ref_type = ref.get("type", "?")
            ref_id = ref.get("id", "?")
            content_lines.append(f"- {ref_type}: {ref_id}")

    file_path.write_text("\n".join(content_lines), encoding="utf-8")
    return file_path


def write_notes_index(notes: list) -> Path:
    """Write index file for notes.

    Args:
        notes: List of Note model instances.

    Returns:
        Path to the index file.
    """
    output_dir = settings.NOTES_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    file_path = output_dir / "index.md"

    lines = [
        "---",
        f"updated: \"{datetime.now().isoformat()}\"",
        "---",
        "",
        "# Notatki",
        "",
        "## Ostatnie notatki",
        "",
    ]

    for note in notes[:30]:
        date_str = note.created_at.strftime("%Y-%m-%d")
        title_slug = _sanitize_filename(note.title)
        lines.append(f"- [[{date_str}_{title_slug}]]")

    lines.extend(["", f"Łącznie: {len(notes)} notatek"])

    file_path.write_text("\n".join(lines), encoding="utf-8")
    return file_path
