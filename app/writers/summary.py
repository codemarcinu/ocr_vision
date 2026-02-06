"""Obsidian markdown writer for article summaries with rich metadata."""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml

from app.config import settings
from app.db.models import Article

logger = logging.getLogger(__name__)


def write_summary_file(
    article: Article,
    summary_text: str,
    model_used: str,
    tags: Optional[List[str]] = None,
    category: Optional[str] = None,
    entities: Optional[List[str]] = None,
) -> Path:
    """
    Write article summary to Obsidian vault with rich metadata.

    File format:
    - YAML frontmatter with metadata (tags, category, entities)
    - Title
    - Summary bullet points
    - Related entities as Obsidian links
    - Source link

    Returns:
        Path to created file
    """
    settings.SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

    # Generate filename from date and title
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_title = _sanitize_filename(article.title)[:50]
    filename = f"{date_str}_{safe_title}.md"
    output_path = settings.SUMMARIES_DIR / filename

    # Handle duplicates
    counter = 1
    while output_path.exists():
        filename = f"{date_str}_{safe_title}_{counter}.md"
        output_path = settings.SUMMARIES_DIR / filename
        counter += 1

    # Build frontmatter
    frontmatter = {
        "title": article.title,
        "url": article.url,
        "source": article.feed.name if article.feed else "manual",
        "author": article.author,
        "published": article.published_date.isoformat() if article.published_date else None,
        "summarized": datetime.now().isoformat(),
        "model": model_used,
        "category": category,
        "tags": _build_tags(tags, category),
        "entities": entities or [],
    }

    # Remove None/empty values
    frontmatter = {k: v for k, v in frontmatter.items() if v}

    # Build content
    lines = [
        "---",
        yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).strip(),
        "---",
        "",
        f"# {article.title}",
        "",
    ]

    # Add category badge if present
    if category:
        lines.append(f"**Kategoria:** {category}")
        lines.append("")

    lines.extend([
        "## Podsumowanie",
        "",
        summary_text,
        "",
    ])

    # Add related entities section if present
    if entities:
        lines.extend([
            "## Powiązane",
            "",
        ])
        for entity in entities:
            # Create Obsidian wiki links
            lines.append(f"- [[{entity}]]")
        lines.append("")

    lines.extend([
        "---",
        f"Źródło: [{article.title}]({article.url})" if article.url else "",
    ])

    content = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Created summary file: {output_path}")
    return output_path


def write_summary_file_simple(
    title: str,
    url: str,
    summary_text: str,
    model_used: str,
    source_name: Optional[str] = None,
    author: Optional[str] = None,
    tags: Optional[List[str]] = None,
    category: Optional[str] = None,
    entities: Optional[List[str]] = None,
) -> Path:
    """
    Simplified version for on-demand summaries without database Article.

    Returns:
        Path to created file
    """
    settings.SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_title = _sanitize_filename(title)[:50]
    filename = f"{date_str}_{safe_title}.md"
    output_path = settings.SUMMARIES_DIR / filename

    counter = 1
    while output_path.exists():
        filename = f"{date_str}_{safe_title}_{counter}.md"
        output_path = settings.SUMMARIES_DIR / filename
        counter += 1

    frontmatter = {
        "title": title,
        "url": url,
        "source": source_name or "manual",
        "author": author,
        "summarized": datetime.now().isoformat(),
        "model": model_used,
        "category": category,
        "tags": _build_tags(tags, category),
        "entities": entities or [],
    }

    frontmatter = {k: v for k, v in frontmatter.items() if v}

    lines = [
        "---",
        yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).strip(),
        "---",
        "",
        f"# {title}",
        "",
    ]

    if category:
        lines.append(f"**Kategoria:** {category}")
        lines.append("")

    lines.extend([
        "## Podsumowanie",
        "",
        summary_text,
        "",
    ])

    if entities:
        lines.extend([
            "## Powiązane",
            "",
        ])
        for entity in entities:
            lines.append(f"- [[{entity}]]")
        lines.append("")

    lines.extend([
        "---",
        f"Źródło: [{title}]({url})" if url else "",
    ])

    content = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Created summary file: {output_path}")
    return output_path


def _build_tags(tags: Optional[List[str]], category: Optional[str]) -> List[str]:
    """Build tag list with standard prefixes."""
    result = ["summary", "article"]

    if category:
        # Add category as tag (lowercase, no spaces)
        cat_tag = category.lower().replace(" ", "-")
        result.append(cat_tag)

    if tags:
        result.extend(tags)

    return list(dict.fromkeys(result))  # Remove duplicates while preserving order


def _sanitize_filename(title: str) -> str:
    """Sanitize title for use in filename."""
    # Remove/replace problematic characters
    sanitized = re.sub(r'[<>:"/\\|?*]', "", title)
    sanitized = re.sub(r"\s+", "_", sanitized)
    return sanitized.strip("_")


def write_feed_index() -> Path:
    """
    Write index file listing all feeds and recent summaries.
    Similar to spiżarnia.md for pantry.

    Returns:
        Path to index file
    """
    settings.SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

    index_path = settings.SUMMARIES_DIR / "index.md"

    # Get recent summary files
    summary_files = sorted(
        settings.SUMMARIES_DIR.glob("*.md"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    # Build content
    lines = [
        "---",
        f"updated: {datetime.now().isoformat()}",
        "---",
        "",
        "# Podsumowania artykułów",
        "",
        "## Ostatnie podsumowania",
        "",
    ]

    for f in summary_files[:20]:
        if f.name == "index.md":
            continue
        lines.append(f"- [[{f.stem}]]")

    content = "\n".join(lines)

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)

    return index_path
