"""Agent tool executors - connect agent tools to actual system functionality."""

import logging
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.router import AgentRouter, AgentResponse, create_agent_router
from app.agent.tools import (
    CreateNoteArgs,
    CreateBookmarkArgs,
    SummarizeUrlArgs,
    ListRecentArgs,
    SearchKnowledgeArgs,
    SearchWebArgs,
    GetSpendingArgs,
    GetInventoryArgs,
    GetWeatherArgs,
    AnswerDirectlyArgs,
)
from app.config import settings

logger = logging.getLogger(__name__)


# Tools that should be executed directly (actions)
ACTION_TOOLS = {"create_note", "create_bookmark", "summarize_url", "list_recent"}

# Tools that should fall through to orchestrator (searches/conversations)
ORCHESTRATOR_TOOLS = {
    "search_knowledge",
    "search_web",
    "get_spending",
    "get_inventory",
    "get_weather",
    "answer_directly",
}


@dataclass
class AgentExecutionResult:
    """Result of agent tool execution."""

    executed: bool  # True if tool was executed, False if should use orchestrator
    tool: Optional[str] = None
    result_text: Optional[str] = None
    error: Optional[str] = None


# =============================================================================
# Tool Executors
# =============================================================================


async def execute_create_note(
    tool_name: str,
    args: CreateNoteArgs,
    db_session: AsyncSession,
) -> str:
    """Execute create_note tool."""
    from app.db.repositories.notes import NoteRepository
    from app.notes_writer import write_note_file
    from app.rag.hooks import index_note_hook

    repo = NoteRepository(db_session)

    note = await repo.create(
        title=args.title,
        content=args.content,
        tags=args.tags,
    )

    # Write to Obsidian
    if settings.GENERATE_OBSIDIAN_FILES:
        try:
            write_note_file(note)
        except Exception as e:
            logger.warning(f"Failed to write note file: {e}")

    # RAG indexing
    if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
        try:
            await index_note_hook(note, db_session)
        except Exception as e:
            logger.warning(f"Failed to index note: {e}")

    await db_session.commit()

    return f"Utworzono notatkę: **{note.title}**"


async def execute_create_bookmark(
    tool_name: str,
    args: CreateBookmarkArgs,
    db_session: AsyncSession,
) -> str:
    """Execute create_bookmark tool."""
    from app.db.repositories.bookmarks import BookmarkRepository
    from app.bookmarks_writer import write_bookmarks_index
    from app.rag.hooks import index_bookmark_hook

    repo = BookmarkRepository(db_session)

    # Check for duplicate
    existing = await repo.get_by_url(args.url)
    if existing:
        return f"Zakładka już istnieje: **{existing.title or args.url}**"

    bookmark = await repo.create_from_url(
        url=args.url,
        source="agent",
        tags=args.tags,
    )

    # Update Obsidian index
    if settings.GENERATE_OBSIDIAN_FILES:
        try:
            all_bookmarks = await repo.get_all(limit=1000)
            write_bookmarks_index(all_bookmarks)
        except Exception as e:
            logger.warning(f"Failed to write bookmarks index: {e}")

    # RAG indexing
    if settings.RAG_ENABLED and settings.RAG_AUTO_INDEX:
        try:
            await index_bookmark_hook(bookmark, db_session)
        except Exception as e:
            logger.warning(f"Failed to index bookmark: {e}")

    await db_session.commit()

    title = bookmark.title or args.url[:50]
    return f"Zapisano zakładkę: **{title}**"


async def execute_summarize_url(
    tool_name: str,
    args: SummarizeUrlArgs,
    db_session: AsyncSession,
) -> str:
    """Execute summarize_url tool."""
    from app.summarizer import summarize_url

    result, error = await summarize_url(args.url)

    if error:
        return f"Błąd podsumowania: {error}"

    if not result:
        return "Nie udało się pobrać treści ze strony."

    # Format summary
    parts = [f"**Podsumowanie:**\n{result.summary_text}"]

    if result.tags:
        parts.append(f"\n**Tagi:** {', '.join(result.tags)}")

    if result.category:
        parts.append(f"**Kategoria:** {result.category}")

    return "\n".join(parts)


async def execute_list_recent(
    tool_name: str,
    args: ListRecentArgs,
    db_session: AsyncSession,
) -> str:
    """Execute list_recent tool."""
    content_type = args.content_type
    limit = args.limit or 5

    if content_type == "notes":
        from app.db.repositories.notes import NoteRepository

        repo = NoteRepository(db_session)
        items = await repo.get_recent(limit=limit)

        if not items:
            return "Brak notatek."

        lines = ["**Ostatnie notatki:**"]
        for note in items:
            date_str = note.created_at.strftime("%d.%m") if note.created_at else ""
            lines.append(f"- {note.title} ({date_str})")
        return "\n".join(lines)

    elif content_type == "bookmarks":
        from app.db.repositories.bookmarks import BookmarkRepository

        repo = BookmarkRepository(db_session)
        items = await repo.get_recent(limit=limit)

        if not items:
            return "Brak zakładek."

        lines = ["**Ostatnie zakładki:**"]
        for b in items:
            title = b.title or b.url[:40]
            lines.append(f"- [{title}]({b.url})")
        return "\n".join(lines)

    elif content_type == "articles":
        from app.db.repositories.rss import ArticleRepository

        repo = ArticleRepository(db_session)
        items = await repo.get_recent(limit=limit)

        if not items:
            return "Brak artykułów."

        lines = ["**Ostatnie artykuły:**"]
        for a in items:
            date_str = a.fetched_date.strftime("%d.%m") if a.fetched_date else ""
            lines.append(f"- {a.title[:60]} ({date_str})")
        return "\n".join(lines)

    elif content_type == "receipts":
        from app.db.repositories.receipts import ReceiptRepository

        repo = ReceiptRepository(db_session)
        items = await repo.get_recent(limit=limit, include_items=False)

        if not items:
            return "Brak paragonów."

        lines = ["**Ostatnie paragony:**"]
        for r in items:
            store = r.store.name if r.store else "?"
            date_str = r.receipt_date.strftime("%d.%m") if r.receipt_date else ""
            lines.append(f"- {store} - {r.total:.2f} PLN ({date_str})")
        return "\n".join(lines)

    elif content_type == "transcriptions":
        from app.db.repositories.transcription import TranscriptionJobRepository

        repo = TranscriptionJobRepository(db_session)
        items = await repo.get_recent_jobs(limit=limit, status="completed")

        if not items:
            return "Brak transkrypcji."

        lines = ["**Ostatnie transkrypcje:**"]
        for job in items:
            title = job.title or job.original_filename or "Bez tytułu"
            lines.append(f"- {title[:50]}")
        return "\n".join(lines)

    else:
        return f"Nieznany typ: {content_type}. Dostępne: notes, bookmarks, articles, receipts, transcriptions"


# =============================================================================
# Main Processor
# =============================================================================


class ChatAgentProcessor:
    """Processes chat messages through agent for action detection."""

    def __init__(self):
        self._router: Optional[AgentRouter] = None

    def _get_router(self) -> AgentRouter:
        """Lazy initialization of agent router."""
        if self._router is None:
            self._router = create_agent_router(
                model=settings.CLASSIFIER_MODEL,
                register_default_executors=False,
            )
        return self._router

    async def process(
        self,
        message: str,
        db_session: AsyncSession,
    ) -> AgentExecutionResult:
        """Process message through agent.

        Args:
            message: User message
            db_session: Database session for tool execution

        Returns:
            AgentExecutionResult indicating if tool was executed or should fallback
        """
        router = self._get_router()

        # Get agent's tool selection
        response = await router.process(message)

        if not response.success:
            logger.warning(f"Agent routing failed: {response.error}")
            return AgentExecutionResult(
                executed=False,
                error=response.error,
            )

        tool = response.tool
        args = response.arguments

        logger.info(f"Agent selected tool: {tool}")

        # Check if this is an action tool
        if tool not in ACTION_TOOLS:
            # Fall through to orchestrator
            return AgentExecutionResult(
                executed=False,
                tool=tool,
            )

        # Execute action tool
        try:
            if tool == "create_note" and response.log and response.log.parsed_arguments:
                validated_args = CreateNoteArgs.model_validate(args)
                result = await execute_create_note(tool, validated_args, db_session)

            elif tool == "create_bookmark" and args:
                validated_args = CreateBookmarkArgs.model_validate(args)
                result = await execute_create_bookmark(tool, validated_args, db_session)

            elif tool == "summarize_url" and args:
                validated_args = SummarizeUrlArgs.model_validate(args)
                result = await execute_summarize_url(tool, validated_args, db_session)

            elif tool == "list_recent" and args:
                validated_args = ListRecentArgs.model_validate(args)
                result = await execute_list_recent(tool, validated_args, db_session)

            else:
                return AgentExecutionResult(
                    executed=False,
                    tool=tool,
                    error="Missing arguments",
                )

            return AgentExecutionResult(
                executed=True,
                tool=tool,
                result_text=result,
            )

        except Exception as e:
            logger.exception(f"Tool execution failed: {tool}")
            return AgentExecutionResult(
                executed=False,
                tool=tool,
                error=str(e),
            )


# Singleton instance
_processor: Optional[ChatAgentProcessor] = None


def get_agent_processor() -> ChatAgentProcessor:
    """Get or create the singleton agent processor."""
    global _processor
    if _processor is None:
        _processor = ChatAgentProcessor()
    return _processor


async def process_with_agent(
    message: str,
    db_session: AsyncSession,
) -> AgentExecutionResult:
    """Convenience function to process message with agent.

    Args:
        message: User message
        db_session: Database session

    Returns:
        AgentExecutionResult
    """
    processor = get_agent_processor()
    return await processor.process(message, db_session)
