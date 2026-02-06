"""Repository for Web Push subscriptions."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PushSubscription
from app.db.repositories.base import BaseRepository


class PushSubscriptionRepository(BaseRepository[PushSubscription]):
    """Repository for Web Push subscription CRUD operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, PushSubscription)

    async def get_by_endpoint(self, endpoint: str) -> Optional[PushSubscription]:
        """Get subscription by endpoint URL."""
        stmt = select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> List[PushSubscription]:
        """Get all active subscriptions."""
        stmt = select(PushSubscription).where(PushSubscription.is_active == True)  # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_or_update(
        self,
        endpoint: str,
        auth_key: str,
        p256dh_key: str,
        user_agent: Optional[str] = None,
    ) -> PushSubscription:
        """Create new subscription or update existing one."""
        existing = await self.get_by_endpoint(endpoint)
        if existing:
            existing.auth_key = auth_key
            existing.p256dh_key = p256dh_key
            existing.is_active = True
            if user_agent:
                existing.user_agent = user_agent
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        return await self.create(
            endpoint=endpoint,
            auth_key=auth_key,
            p256dh_key=p256dh_key,
            user_agent=user_agent,
        )

    async def deactivate(self, endpoint: str) -> bool:
        """Deactivate subscription by endpoint."""
        stmt = (
            update(PushSubscription)
            .where(PushSubscription.endpoint == endpoint)
            .values(is_active=False)
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def mark_used(self, subscription_id: UUID) -> None:
        """Update last_used_at timestamp."""
        stmt = (
            update(PushSubscription)
            .where(PushSubscription.id == subscription_id)
            .values(last_used_at=datetime.utcnow())
        )
        await self.session.execute(stmt)

    async def delete_by_endpoint(self, endpoint: str) -> bool:
        """Delete subscription by endpoint."""
        subscription = await self.get_by_endpoint(endpoint)
        if subscription:
            return await self.delete(subscription.id)
        return False
