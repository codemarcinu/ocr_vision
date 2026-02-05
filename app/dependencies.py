"""FastAPI dependencies for database repositories."""

from typing import Annotated, AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connection import get_session
from app.db.repositories.analytics import AnalyticsRepository
from app.db.repositories.feedback import FeedbackRepository
from app.db.repositories.pantry import PantryRepository
from app.db.repositories.products import ProductRepository
from app.db.repositories.receipts import ReceiptRepository
from app.db.repositories.rss import ArticleRepository, RssFeedRepository
from app.db.repositories.bookmarks import BookmarkRepository
from app.db.repositories.notes import NoteRepository
from app.db.repositories.chat import ChatRepository
from app.db.repositories.embeddings import EmbeddingRepository
from app.db.repositories.stores import StoreRepository
from app.db.repositories.user_profile import UserProfileRepository


# Session dependency
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session dependency."""
    async for session in get_session():
        yield session


# Type alias for session dependency
DbSession = Annotated[AsyncSession, Depends(get_db)]


# Repository dependencies
async def get_product_repo(session: DbSession) -> ProductRepository:
    """Get product repository."""
    return ProductRepository(session)


async def get_store_repo(session: DbSession) -> StoreRepository:
    """Get store repository."""
    return StoreRepository(session)


async def get_receipt_repo(session: DbSession) -> ReceiptRepository:
    """Get receipt repository."""
    return ReceiptRepository(session)


async def get_pantry_repo(session: DbSession) -> PantryRepository:
    """Get pantry repository."""
    return PantryRepository(session)


async def get_feedback_repo(session: DbSession) -> FeedbackRepository:
    """Get feedback repository."""
    return FeedbackRepository(session)


async def get_analytics_repo(session: DbSession) -> AnalyticsRepository:
    """Get analytics repository."""
    return AnalyticsRepository(session)


async def get_feed_repo(session: DbSession) -> RssFeedRepository:
    """Get RSS feed repository."""
    return RssFeedRepository(session)


async def get_article_repo(session: DbSession) -> ArticleRepository:
    """Get article repository."""
    return ArticleRepository(session)


async def get_note_repo(session: DbSession) -> NoteRepository:
    """Get note repository."""
    return NoteRepository(session)


async def get_bookmark_repo(session: DbSession) -> BookmarkRepository:
    """Get bookmark repository."""
    return BookmarkRepository(session)


async def get_embedding_repo(session: DbSession) -> EmbeddingRepository:
    """Get embedding repository."""
    return EmbeddingRepository(session)


async def get_chat_repo(session: DbSession) -> ChatRepository:
    """Get chat repository."""
    return ChatRepository(session)


async def get_user_profile_repo(session: DbSession) -> UserProfileRepository:
    """Get user profile repository."""
    return UserProfileRepository(session)


# Type aliases for repository dependencies
ProductRepoDep = Annotated[ProductRepository, Depends(get_product_repo)]
StoreRepoDep = Annotated[StoreRepository, Depends(get_store_repo)]
ReceiptRepoDep = Annotated[ReceiptRepository, Depends(get_receipt_repo)]
PantryRepoDep = Annotated[PantryRepository, Depends(get_pantry_repo)]
FeedbackRepoDep = Annotated[FeedbackRepository, Depends(get_feedback_repo)]
AnalyticsRepoDep = Annotated[AnalyticsRepository, Depends(get_analytics_repo)]
FeedRepoDep = Annotated[RssFeedRepository, Depends(get_feed_repo)]
ArticleRepoDep = Annotated[ArticleRepository, Depends(get_article_repo)]
NoteRepoDep = Annotated[NoteRepository, Depends(get_note_repo)]
BookmarkRepoDep = Annotated[BookmarkRepository, Depends(get_bookmark_repo)]
EmbeddingRepoDep = Annotated[EmbeddingRepository, Depends(get_embedding_repo)]
ChatRepoDep = Annotated[ChatRepository, Depends(get_chat_repo)]
UserProfileRepoDep = Annotated[UserProfileRepository, Depends(get_user_profile_repo)]
