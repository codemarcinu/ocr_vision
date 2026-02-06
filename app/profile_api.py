"""REST API for user profiles (personalization)."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import UserProfileRepoDep

router = APIRouter(prefix="/profile", tags=["Profile"])


class ProfilePreferences(BaseModel):
    """User preference update request."""

    default_city: Optional[str] = Field(None, max_length=100)
    timezone: Optional[str] = Field(None, max_length=50)
    preferred_language: Optional[str] = Field(None, max_length=10)
    favorite_stores: Optional[list[str]] = None


class ProfileResponse(BaseModel):
    """User profile response."""

    id: UUID
    default_city: str
    timezone: str
    preferred_language: str
    favorite_stores: Optional[list[str]]
    most_used_tools: Optional[dict]
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


@router.get("/{profile_id}")
async def get_profile(
    profile_id: UUID,
    repo: UserProfileRepoDep,
):
    """Get user profile by ID."""
    profile = await repo.get_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profil nie znaleziony")

    return {
        "id": str(profile.id),
        "default_city": profile.default_city,
        "timezone": profile.timezone,
        "preferred_language": profile.preferred_language,
        "favorite_stores": profile.favorite_stores,
        "most_used_tools": profile.most_used_tools,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


@router.patch("/{profile_id}")
async def update_profile(
    profile_id: UUID,
    prefs: ProfilePreferences,
    repo: UserProfileRepoDep,
):
    """Update user profile preferences."""
    profile = await repo.update_preferences(
        profile_id,
        default_city=prefs.default_city,
        timezone=prefs.timezone,
        preferred_language=prefs.preferred_language,
        favorite_stores=prefs.favorite_stores,
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Profil nie znaleziony")

    return {
        "id": str(profile.id),
        "default_city": profile.default_city,
        "timezone": profile.timezone,
        "preferred_language": profile.preferred_language,
        "favorite_stores": profile.favorite_stores,
        "updated_at": profile.updated_at.isoformat(),
        "message": "Profil zaktualizowany",
    }
