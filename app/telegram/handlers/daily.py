"""Daily note command - collect today's notes and generate a summary."""

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.telegram.formatters import escape_html
from app.telegram.middleware import authorized_only

logger = logging.getLogger(__name__)

DAILY_PROMPT_TEMPLATE = """Stwórz podsumowanie dnia na podstawie poniższych notatek.

INSTRUKCJE:
1. Napisz krótkie podsumowanie dnia (2-3 zdania)
2. Wypisz najważniejsze tematy i aktywności jako bullet points
3. Jeśli są zadania do zrobienia, wylistuj je osobno jako checklist

Data: {date}
Liczba notatek: {count}

NOTATKI:
{notes_text}

PODSUMOWANIE DNIA:"""


@authorized_only
async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /daily command - generate daily note from today's notes."""
    if not update.message:
        return

    if not settings.NOTES_ENABLED:
        await update.message.reply_text("❌ Notatki są wyłączone")
        return

    from app.db.connection import get_session
    from app.db.repositories.notes import NoteRepository

    async for session in get_session():
        repo = NoteRepository(session)
        notes = await repo.get_today()

    if not notes:
        await update.message.reply_text(
            "📭 <b>Brak notatek z dzisiaj</b>\n\n"
            "Wyślij głosówkę lub użyj <code>/n tekst</code> aby dodać notatkę.",
            parse_mode="HTML",
        )
        return

    status_msg = await update.message.reply_text("🧠 Generuję podsumowanie dnia...")

    today_str = datetime.now().strftime("%Y-%m-%d")

    # Build notes text for LLM
    notes_text = ""
    for i, note in enumerate(notes, 1):
        time_str = note.created_at.strftime("%H:%M")
        tags_str = ", ".join(note.tags) if note.tags else ""
        notes_text += f"\n--- Notatka {i} ({time_str}) ---\n"
        if tags_str:
            notes_text += f"Tagi: {tags_str}\n"
        notes_text += f"{note.content}\n"

    # LLM summary
    summary_text = ""
    try:
        from app import ollama_client

        model = settings.SUMMARIZER_MODEL_PL or settings.CLASSIFIER_MODEL
        prompt = DAILY_PROMPT_TEMPLATE.format(
            date=today_str,
            count=len(notes),
            notes_text=notes_text,
        )

        response, error = await ollama_client.post_generate(
            model=model,
            prompt=prompt,
            options={"temperature": 0.3, "num_predict": 1024},
            timeout=120.0,
            keep_alive=settings.TEXT_MODEL_KEEP_ALIVE,
        )

        if not error and response:
            summary_text = response.strip()
        else:
            logger.warning(f"Daily summary LLM error: {error}")
            summary_text = "*(Nie udało się wygenerować podsumowania)*"

    except Exception as e:
        logger.warning(f"Daily summary LLM failed: {e}")
        summary_text = "*(Nie udało się wygenerować podsumowania)*"

    # Time range
    first_time = notes[-1].created_at.strftime("%H:%M")  # oldest (list is desc)
    last_time = notes[0].created_at.strftime("%H:%M")  # newest

    # Collect all tags
    all_tags = {"daily"}
    for n in notes:
        if n.tags:
            all_tags.update(n.tags)
    tags_str = ", ".join(sorted(all_tags))

    # Write daily markdown
    try:
        output_dir = settings.DAILY_OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"{today_str}.md"

        lines = [
            "---",
            f'title: "Dziennik {today_str}"',
            "type: daily",
            f"date: {today_str}",
            f"notes_count: {len(notes)}",
            f'time_range: "{first_time} - {last_time}"',
            f"tags: [{tags_str}]",
            f'created: "{datetime.now().isoformat()}"',
            "---",
            "",
            f"# Dziennik {today_str}",
            "",
            "## Podsumowanie",
            "",
            summary_text,
            "",
            f"## Notatki ({len(notes)})",
            "",
        ]

        for note in notes:
            time_str = note.created_at.strftime("%H:%M")
            tag_badges = ""
            if note.tags:
                tag_badges = " " + " ".join(f"#{t}" for t in note.tags)

            lines.append(f"### {time_str} - {note.title}")
            if tag_badges:
                lines.append(tag_badges)
            lines.append("")
            lines.append(note.content)
            lines.append("")

        file_path.write_text("\n".join(lines), encoding="utf-8")

    except Exception as e:
        logger.error(f"Failed to write daily file: {e}")

    # Send confirmation
    summary_preview = summary_text[:300] + "..." if len(summary_text) > 300 else summary_text

    await status_msg.edit_text(
        f"✅ <b>Dziennik {today_str}</b>\n\n"
        f"📝 {len(notes)} notatek ({first_time} - {last_time})\n\n"
        f"<b>Podsumowanie:</b>\n"
        f"{escape_html(summary_preview)}\n\n"
        f"📄 Zapisano do Obsidian",
        parse_mode="HTML",
    )
