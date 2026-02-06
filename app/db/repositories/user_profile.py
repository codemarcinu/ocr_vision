"""Repository for user profiles (personalization)."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile
from app.db.repositories.base import BaseRepository


class UserProfileRepository(BaseRepository[UserProfile]):
    """Repository for user profile CRUD and lookup."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, UserProfile)

    async def update_preferences(
        self,
        profile_id: UUID,
        *,
        default_city: Optional[str] = None,
        timezone: Optional[str] = None,
        preferred_language: Optional[str] = None,
        favorite_stores: Optional[list[str]] = None,
    ) -> Optional[UserProfile]:
        """Update user preferences."""
        updates = {}
        if default_city is not None:
            updates["default_city"] = default_city
        if timezone is not None:
            updates["timezone"] = timezone
        if preferred_language is not None:
            updates["preferred_language"] = preferred_language
        if favorite_stores is not None:
            updates["favorite_stores"] = favorite_stores

        if not updates:
            return await self.get_by_id(profile_id)

        return await self.update(profile_id, **updates)

    async def increment_tool_usage(
        self, profile_id: UUID, tool_name: str
    ) -> Optional[UserProfile]:
        """Increment usage counter for a tool."""
        profile = await self.get_by_id(profile_id)
        if not profile:
            return None

        most_used = profile.most_used_tools or {}
        most_used[tool_name] = most_used.get(tool_name, 0) + 1

        return await self.update(profile_id, most_used_tools=most_used)
