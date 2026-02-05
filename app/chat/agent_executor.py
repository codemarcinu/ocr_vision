"""Agent tool executors - connect agent tools to actual system functionality."""

import logging
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.router import AgentRouter, AgentResponse, AgentCallLog, create_agent_router
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
    AskClarificationArgs,
)
from app.config import settings

logger = logging.getLogger(__name__)


# Tools that should be executed directly (actions)
ACTION_TOOLS = {"create_note", "create_bookmark", "summarize_url", "list_recent", "ask_clarification"}

# Tools that should fall through to orchestrator (searches/conversations)
ORCHESTRATOR_TOOLS = {
    "search_knowledge",
    "search_web",
    "get_spending",
    "get_inventory",
    "get_weather",
    "answer_directly",
}


# Maximum tools in a chain (matches tools.py MAX_TOOLS_IN_CHAIN)
MAX_TOOLS_IN_CHAIN = 3


# Mapping from agent tool to orchestrator search strategy
TOOL_TO_STRATEGY = {
    "create_note": "direct",
    "create_bookmark": "direct",
    "summarize_url": "direct",
    "list_recent": "direct",
    "ask_clarification": "direct",
    "search_knowledge": "rag",
    "search_web": "web",
    "get_spending": "spending",
    "get_inventory": "inventory",
    "get_weather": "weather",
    "answer_directly": "direct",
}


@dataclass
class AgentExecutionResult:
    """Result of agent tool execution."""

    executed: bool  # True if tool was executed, False if should use orchestrator
    tool: Optional[str] = None
    result_text: Optional[str] = None
    error: Optional[str] = None
    # For conversation history - formatted tool result for agent context
    history_entry: Optional[dict] = None  # {"role": "assistant", "content": "[TOOL_RESULT: ...]"}
    # For orchestrator - skip IntentClassifier when these are set
    search_strategy: Optional[str] = None  # rag|web|spending|inventory|weather|direct
    search_query: Optional[str] = None  # Reformulated query from agent arguments
    # Multi-tool support
    is_multi: bool = False
    executed_tools: list[str] = None  # List of executed tools in order
    results: list[str] = None  # Results from each tool in order
    partial_success: bool = False  # True if some tools succeeded before failure

    def __post_init__(self):
        if self.executed_tools is None:
            self.executed_tools = []
        if self.results is None:
            self.results = []


@dataclass
class ToolChainContext:
    """Context passed between tools in a chain."""

    previous_results: dict[str, str]  # tool_name -> result_text
    last_result: Optional[str] = None  # Result of the most recent tool
    last_tool: Optional[str] = None  # Name of the most recent tool


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


def execute_ask_clarification(args: AskClarificationArgs) -> str:
    """Execute ask_clarification tool - format clarification request.

    This doesn't perform any action, just formats the question for display.
    """
    parts = []

    if args.context:
        parts.append(f"_{args.context}_")
        parts.append("")

    parts.append(f"❓ **{args.question}**")

    if args.options:
        parts.append("")
        for i, opt in enumerate(args.options, 1):
            parts.append(f"{i}. {opt}")

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
# Multi-Tool Chain Execution
# =============================================================================


async def execute_tool_chain(
    tools: list[str],
    args_list: list[dict],
    validated_args_list: list,
    db_session: AsyncSession,
) -> AgentExecutionResult:
    """Execute multiple tools sequentially, passing results between them.

    Args:
        tools: List of tool names to execute in order
        args_list: List of arguments dicts for each tool
        validated_args_list: List of validated Pydantic models for each tool
        db_session: Database session

    Returns:
        AgentExecutionResult with combined results
    """
    if not tools:
        return AgentExecutionResult(
            executed=False,
            error="Brak narzędzi do wykonania",
        )

    if len(tools) > MAX_TOOLS_IN_CHAIN:
        return AgentExecutionResult(
            executed=False,
            error=f"Za dużo narzędzi ({len(tools)}), max {MAX_TOOLS_IN_CHAIN}",
        )

    context = ToolChainContext(previous_results={})
    executed_tools: list[str] = []
    results: list[str] = []
    history_entries: list[str] = []

    for i, (tool, args, validated_args) in enumerate(zip(tools, args_list, validated_args_list)):
        logger.info(f"Executing tool {i+1}/{len(tools)}: {tool}")

        # Check if this is an orchestrator tool (not supported in chains)
        if tool in ORCHESTRATOR_TOOLS:
            logger.warning(f"Tool '{tool}' is an orchestrator tool, skipping in chain")
            # Return partial results and indicate orchestrator needed
            return AgentExecutionResult(
                executed=len(executed_tools) > 0,
                tool=tool,
                result_text="\n\n".join(results) if results else None,
                is_multi=True,
                executed_tools=executed_tools,
                results=results,
                partial_success=len(executed_tools) > 0,
                search_strategy=TOOL_TO_STRATEGY.get(tool, "direct"),
                search_query=args.get("query") if args else None,
                history_entry={
                    "role": "assistant",
                    "content": "\n\n".join(history_entries),
                } if history_entries else None,
            )

        # Inject context from previous tools if needed
        validated_args = _inject_chain_context(tool, validated_args, context)

        try:
            result = await _execute_single_tool(tool, validated_args, db_session)

            if result is None:
                error_msg = f"Narzędzie '{tool}' zwróciło pusty wynik"
                logger.warning(error_msg)
                # Continue with warning, don't abort chain
                result = f"(brak wyniku z {tool})"

            executed_tools.append(tool)
            results.append(result)

            # Update context for next tool
            context.previous_results[tool] = result
            context.last_result = result
            context.last_tool = tool

            # Build history entry
            history_entries.append(f"[TOOL_RESULT: {tool}]\n{result}")

        except Exception as e:
            logger.exception(f"Tool '{tool}' failed in chain")
            # Return partial results on failure
            return AgentExecutionResult(
                executed=len(executed_tools) > 0,
                tool=tool,
                result_text="\n\n".join(results) if results else None,
                error=f"Błąd w {tool}: {str(e)}",
                is_multi=True,
                executed_tools=executed_tools,
                results=results,
                partial_success=len(executed_tools) > 0,
                history_entry={
                    "role": "assistant",
                    "content": "\n\n".join(history_entries),
                } if history_entries else None,
            )

    # All tools executed successfully
    combined_result = "\n\n---\n\n".join(results)

    return AgentExecutionResult(
        executed=True,
        tool=",".join(executed_tools),
        result_text=combined_result,
        is_multi=True,
        executed_tools=executed_tools,
        results=results,
        history_entry={
            "role": "assistant",
            "content": "\n\n".join(history_entries),
        },
    )


def _inject_chain_context(
    tool: str,
    validated_args: BaseModel,
    context: ToolChainContext,
) -> BaseModel:
    """Inject context from previous tools into current tool arguments.

    Handles automatic mapping between common tool combinations:
    - summarize_url -> create_note: summary becomes note content
    - summarize_url -> create_bookmark: URL preserved

    Args:
        tool: Current tool name
        validated_args: Validated arguments for current tool
        context: Chain context with previous results

    Returns:
        Modified validated_args with injected context
    """
    if not context.last_result or not context.last_tool:
        return validated_args

    # summarize_url -> create_note: inject summary as content
    if tool == "create_note" and context.last_tool == "summarize_url":
        if hasattr(validated_args, "content"):
            # Check if content is a placeholder or very short
            current_content = getattr(validated_args, "content", "")
            if not current_content or len(current_content) < 20 or "{previous}" in current_content.lower():
                # Inject the summary
                validated_args.content = context.last_result
                logger.info("Injected summarize_url result into create_note content")

    # summarize_url -> create_bookmark: both use same URL, no injection needed
    # The URL should already be in both tool arguments

    return validated_args


async def _execute_single_tool(
    tool: str,
    validated_args: BaseModel,
    db_session: AsyncSession,
) -> Optional[str]:
    """Execute a single ACTION_TOOL and return result text.

    Args:
        tool: Tool name
        validated_args: Validated Pydantic model with arguments
        db_session: Database session

    Returns:
        Result text or None on failure
    """
    if tool == "create_note":
        return await execute_create_note(tool, validated_args, db_session)

    elif tool == "create_bookmark":
        return await execute_create_bookmark(tool, validated_args, db_session)

    elif tool == "summarize_url":
        return await execute_summarize_url(tool, validated_args, db_session)

    elif tool == "list_recent":
        return await execute_list_recent(tool, validated_args, db_session)

    elif tool == "ask_clarification":
        return execute_ask_clarification(validated_args)

    else:
        logger.warning(f"Unknown action tool: {tool}")
        return None


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

    async def _save_log(
        self,
        response: AgentResponse,
        db_session: AsyncSession,
        execution_success: bool = False,
        execution_error: Optional[str] = None,
    ) -> None:
        """Persist agent call log to database."""
        if not response.log:
            return

        try:
            from app.db.repositories.agent import AgentCallLogRepository

            repo = AgentCallLogRepository(db_session)
            await repo.create(
                user_input=response.log.user_input,
                model_used=response.log.model_used,
                sanitized_input=response.log.sanitized_input,
                raw_response=response.log.raw_response,
                parsed_tool=response.log.parsed_tool,
                parsed_arguments=response.log.parsed_arguments,
                validation_success=response.log.validation_success,
                validation_error=response.log.validation_error,
                execution_success=execution_success or response.log.execution_success,
                execution_error=execution_error or response.log.execution_error,
                confidence=response.log.confidence,
                retry_count=response.log.retry_count,
                total_time_ms=response.log.total_time_ms,
                injection_risk=response.log.injection_risk,
                source="telegram",
            )
        except Exception as e:
            logger.warning(f"Failed to save agent call log: {e}")

    async def process(
        self,
        message: str,
        db_session: AsyncSession,
        conversation_history: Optional[list[dict]] = None,
        user_profile: Optional[dict] = None,
    ) -> AgentExecutionResult:
        """Process message through agent.

        Supports both single-tool and multi-tool requests.

        Args:
            message: User message
            db_session: Database session for tool execution
            conversation_history: Recent messages for context [{role, content}, ...]
            user_profile: Optional user profile for personalization:
                - default_city: str
                - timezone: str
                - favorite_stores: list[str]

        Returns:
            AgentExecutionResult indicating if tool was executed or should fallback
        """
        router = self._get_router()

        # Get agent's tool selection with conversation context and profile
        response = await router.process(message, conversation_history, user_profile)

        if not response.success:
            logger.warning(f"Agent routing failed: {response.error}")
            await self._save_log(response, db_session, execution_success=False)
            return AgentExecutionResult(
                executed=False,
                error=response.error,
            )

        # Handle multi-tool request
        if response.is_multi:
            logger.info(f"Multi-tool request: {response.tools}")

            # Check if any tool is an orchestrator tool (not supported in chains)
            has_orchestrator = any(t in ORCHESTRATOR_TOOLS for t in response.tools)
            has_action = any(t in ACTION_TOOLS for t in response.tools)

            if has_orchestrator and not has_action:
                # All orchestrator tools - can't chain them
                await self._save_log(response, db_session, execution_success=True)
                return AgentExecutionResult(
                    executed=False,
                    tool=response.tools[0] if response.tools else None,
                    search_strategy=TOOL_TO_STRATEGY.get(response.tools[0], "direct") if response.tools else None,
                    search_query=response.arguments.get("query") if response.arguments else None,
                )

            # Execute tool chain
            chain_result = await execute_tool_chain(
                tools=response.tools,
                args_list=response.arguments_list,
                validated_args_list=response.validated_args_list,
                db_session=db_session,
            )

            await self._save_log(
                response,
                db_session,
                execution_success=chain_result.executed,
                execution_error=chain_result.error,
            )

            return chain_result

        # Single tool handling (original logic)
        tool = response.tool
        args = response.arguments

        logger.info(f"Agent selected tool: {tool} with args: {args}")

        # Check if this is an action tool
        if tool not in ACTION_TOOLS:
            # Fall through to orchestrator with search strategy (skip IntentClassifier)
            await self._save_log(response, db_session, execution_success=True)

            # Extract search_query from arguments based on tool type
            search_query = None
            if args:
                # Different tools have different query fields
                search_query = args.get("query") or args.get("question") or args.get("city")

            return AgentExecutionResult(
                executed=False,
                tool=tool,
                search_strategy=TOOL_TO_STRATEGY.get(tool, "direct"),
                search_query=search_query,
            )

        # Execute action tool
        try:
            if tool == "create_note" and args:
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

            elif tool == "ask_clarification" and args:
                validated_args = AskClarificationArgs.model_validate(args)
                result = execute_ask_clarification(validated_args)

            else:
                await self._save_log(response, db_session, execution_error="Missing arguments")
                return AgentExecutionResult(
                    executed=False,
                    tool=tool,
                    error="Missing arguments",
                )

            # Success - save log with execution_success=True
            await self._save_log(response, db_session, execution_success=True)

            # Create history entry for agent context in future messages
            # Format: [TOOL_RESULT: tool_name]\n<result>
            # This allows agent to use the result in follow-up requests
            history_entry = {
                "role": "assistant",
                "content": f"[TOOL_RESULT: {tool}]\n{result}",
            }

            return AgentExecutionResult(
                executed=True,
                tool=tool,
                result_text=result,
                history_entry=history_entry,
            )

        except Exception as e:
            logger.exception(f"Tool execution failed: {tool}")
            await self._save_log(response, db_session, execution_error=str(e))
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
    conversation_history: Optional[list[dict]] = None,
    user_profile: Optional[dict] = None,
) -> AgentExecutionResult:
    """Convenience function to process message with agent.

    Args:
        message: User message
        db_session: Database session
        conversation_history: Recent messages for context
        user_profile: Optional user profile for personalization

    Returns:
        AgentExecutionResult
    """
    processor = get_agent_processor()
    return await processor.process(message, db_session, conversation_history, user_profile)
