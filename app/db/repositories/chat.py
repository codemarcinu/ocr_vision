"""Chat repository for session and message management."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import ChatSession, ChatMessage
from app.db.repositories.base import BaseRepository


class ChatRepository(BaseRepository[ChatSession]):
    """Repository for chat sessions and messages."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ChatSession)

    async def create_session(
        self,
        source: str = "web",
        telegram_chat_id: Optional[int] = None,
    ) -> ChatSession:
        """Create a new chat session."""
        session = ChatSession(
            source=source,
            telegram_chat_id=telegram_chat_id,
        )
        self.session.add(session)
        await self.session.flush()
        await self.session.refresh(session)
        return session

    async def get_session_with_messages(
        self,
        session_id: UUID,
        limit: int = 50,
    ) -> Optional[ChatSession]:
        """Get session with eagerly loaded messages."""
        stmt = (
            select(ChatSession)
            .where(ChatSession.id == session_id)
            .options(selectinload(ChatSession.messages))
        )
        result = await self.session.execute(stmt)
        chat_session = result.scalar_one_or_none()

        if chat_session and limit and len(chat_session.messages) > limit:
            chat_session.messages = chat_session.messages[-limit:]

        return chat_session

    async def add_message(
        self,
        session_id: UUID,
        role: str,
        content: str,
        sources: Optional[list] = None,
        search_type: Optional[str] = None,
        search_query: Optional[str] = None,
        model_used: Optional[str] = None,
        processing_time_sec: Optional[float] = None,
    ) -> ChatMessage:
        """Add a message to a session."""
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            sources=sources or [],
            search_type=search_type,
            search_query=search_query,
            model_used=model_used,
            processing_time_sec=processing_time_sec,
        )
        self.session.add(msg)
        await self.session.flush()
        await self.session.refresh(msg)

        # Update session's updated_at
        session = await self.get_by_id(session_id)
        if session:
            session.updated_at = func.current_timestamp()
            await self.session.flush()

        return msg

    async def get_recent_messages(
        self,
        session_id: UUID,
        limit: int = 10,
    ) -> List[ChatMessage]:
        """Get recent messages for a session, ordered oldest first."""
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        messages = list(result.scalars().all())
        messages.reverse()  # Return in chronological order
        return messages

    async def get_user_sessions(
        self,
        source: Optional[str] = None,
        limit: int = 20,
    ) -> List[ChatSession]:
        """List recent chat sessions."""
        stmt = select(ChatSession).order_by(ChatSession.updated_at.desc())

        if source:
            stmt = stmt.where(ChatSession.source == source)

        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def end_session(self, session_id: UUID) -> None:
        """Mark a session as inactive."""
        session = await self.get_by_id(session_id)
        if session:
            session.is_active = False
            await self.session.flush()

    async def generate_title(self, session_id: UUID) -> Optional[str]:
        """Generate a title from the first user message."""
        stmt = (
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == "user",
            )
            .order_by(ChatMessage.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        first_msg = result.scalar_one_or_none()

        if first_msg:
            title = first_msg.content[:60]
            if len(first_msg.content) > 60:
                title += "..."
            session = await self.get_by_id(session_id)
            if session:
                session.title = title
                await self.session.flush()
            return title
        return None

    async def delete_all_sessions(self) -> int:
        """Delete all chat sessions (messages cascade)."""
        stmt = delete(ChatSession)
        result = await self.session.execute(stmt)
        return result.rowcount

    async def get_message_count(self, session_id: UUID) -> int:
        """Get the number of messages in a session."""
        stmt = (
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.session_id == session_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0
