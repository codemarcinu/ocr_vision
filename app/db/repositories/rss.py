"""Repository for RSS feeds and articles."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Article, ArticleSummary, RssFeed
from app.db.repositories.base import BaseRepository


class RssFeedRepository(BaseRepository[RssFeed]):
    """Repository for RSS feed operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, RssFeed)

    async def get_by_url(self, url: str) -> Optional[RssFeed]:
        """Get feed by URL."""
        stmt = select(RssFeed).where(RssFeed.feed_url == url)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_feeds(self) -> List[RssFeed]:
        """Get all active feeds."""
        stmt = (
            select(RssFeed)
            .where(RssFeed.is_active == True)
            .order_by(RssFeed.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_feeds_due_for_fetch(self) -> List[RssFeed]:
        """
        Get feeds that need to be fetched (past their interval).

        Returns feeds where:
        - is_active = True
        - last_fetched is NULL OR (now - last_fetched) > fetch_interval_hours
        """
        now = datetime.now()
        stmt = select(RssFeed).where(RssFeed.is_active == True)
        result = await self.session.execute(stmt)
        feeds = list(result.scalars().all())

        # Filter in Python to avoid complex SQL interval math
        due_feeds = []
        for feed in feeds:
            if feed.last_fetched is None:
                due_feeds.append(feed)
            else:
                hours_since_fetch = (now - feed.last_fetched).total_seconds() / 3600
                if hours_since_fetch >= feed.fetch_interval_hours:
                    due_feeds.append(feed)

        return due_feeds

    async def update_last_fetched(
        self, feed_id: int, error: Optional[str] = None
    ) -> Optional[RssFeed]:
        """Update feed's last_fetched timestamp and error."""
        feed = await self.get_by_id(feed_id)
        if feed:
            feed.last_fetched = datetime.now()
            feed.last_error = error
            await self.session.flush()
            await self.session.refresh(feed)
        return feed

    async def get_with_articles(
        self, feed_id: int, limit: int = 20
    ) -> Optional[RssFeed]:
        """Get feed with its recent articles loaded."""
        stmt = (
            select(RssFeed)
            .options(
                selectinload(RssFeed.articles).selectinload(Article.summary)
            )
            .where(RssFeed.id == feed_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class ArticleRepository(BaseRepository[Article]):
    """Repository for article operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Article)

    async def get_by_url(self, url: str) -> Optional[Article]:
        """Get article by URL."""
        stmt = select(Article).where(Article.url == url)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_external_id(
        self, feed_id: int, external_id: str
    ) -> Optional[Article]:
        """Get article by feed and external ID (guid)."""
        stmt = select(Article).where(
            and_(Article.feed_id == feed_id, Article.external_id == external_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_unsummarized(self, limit: int = 10) -> List[Article]:
        """Get articles that haven't been summarized yet."""
        stmt = (
            select(Article)
            .where(Article.is_summarized == False)
            .order_by(Article.fetched_date.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_recent(
        self, feed_id: Optional[int] = None, limit: int = 20
    ) -> List[Article]:
        """Get recent articles with their summaries."""
        stmt = (
            select(Article)
            .options(selectinload(Article.summary), selectinload(Article.feed))
            .order_by(Article.fetched_date.desc())
            .limit(limit)
        )
        if feed_id:
            stmt = stmt.where(Article.feed_id == feed_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_article(
        self,
        title: str,
        url: Optional[str] = None,
        content: Optional[str] = None,
        feed_id: Optional[int] = None,
        external_id: Optional[str] = None,
        author: Optional[str] = None,
        published_date: Optional[datetime] = None,
    ) -> Article:
        """Create a new article."""
        article = Article(
            feed_id=feed_id,
            external_id=external_id,
            title=title,
            url=url,
            content=content,
            author=author,
            published_date=published_date,
            is_summarized=False,
        )
        self.session.add(article)
        await self.session.flush()
        await self.session.refresh(article)
        return article

    async def create_with_summary(
        self,
        title: str,
        url: Optional[str],
        content: Optional[str],
        summary_text: str,
        model_used: str,
        processing_time: float,
        feed_id: Optional[int] = None,
        external_id: Optional[str] = None,
        author: Optional[str] = None,
        published_date: Optional[datetime] = None,
    ) -> Article:
        """Create article with its summary in one transaction."""
        article = Article(
            feed_id=feed_id,
            external_id=external_id,
            title=title,
            url=url,
            content=content,
            author=author,
            published_date=published_date,
            is_summarized=True,
        )
        self.session.add(article)
        await self.session.flush()

        summary = ArticleSummary(
            article_id=article.id,
            summary_text=summary_text,
            model_used=model_used,
            processing_time_sec=Decimal(str(processing_time)),
        )
        self.session.add(summary)
        await self.session.flush()

        await self.session.refresh(article)
        return article

    async def add_summary(
        self,
        article_id: int,
        summary_text: str,
        model_used: str,
        processing_time: float,
    ) -> Optional[ArticleSummary]:
        """Add summary to an existing article."""
        article = await self.get_by_id(article_id)
        if not article:
            return None

        summary = ArticleSummary(
            article_id=article_id,
            summary_text=summary_text,
            model_used=model_used,
            processing_time_sec=Decimal(str(processing_time)),
        )
        self.session.add(summary)

        article.is_summarized = True
        await self.session.flush()
        await self.session.refresh(summary)
        return summary

    async def mark_as_read(self, article_id: int) -> Optional[Article]:
        """Mark article as read."""
        article = await self.get_by_id(article_id)
        if article:
            article.is_read = True
            await self.session.flush()
            await self.session.refresh(article)
        return article

    async def get_unread_count(self, feed_id: Optional[int] = None) -> int:
        """Get count of unread articles."""
        from sqlalchemy import func
        stmt = select(func.count()).select_from(Article).where(Article.is_read == False)
        if feed_id:
            stmt = stmt.where(Article.feed_id == feed_id)
        result = await self.session.execute(stmt)
        return result.scalar() or 0
