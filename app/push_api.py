"""Web Push notification API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.dependencies import DbSession
from app.db.repositories.push import PushSubscriptionRepository
from app.services.push_service import push_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/push", tags=["push"])


class SubscriptionRequest(BaseModel):
    """Web Push subscription data from browser."""
    endpoint: str
    keys: dict  # Contains 'auth' and 'p256dh'


class UnsubscribeRequest(BaseModel):
    """Unsubscribe request."""
    endpoint: str


class TestNotificationRequest(BaseModel):
    """Test notification request."""
    title: Optional[str] = "Test notification"
    body: Optional[str] = "This is a test push notification from Second Brain"


@router.get("/vapid-key")
async def get_vapid_public_key():
    """Get VAPID public key for subscription.

    This key is needed by the browser to subscribe to push notifications.
    """
    if not settings.PUSH_ENABLED:
        raise HTTPException(status_code=503, detail="Push notifications disabled")

    if not settings.PUSH_VAPID_PUBLIC_KEY:
        raise HTTPException(
            status_code=503,
            detail="Push notifications not configured (missing VAPID keys)"
        )

    return {"publicKey": settings.PUSH_VAPID_PUBLIC_KEY}


@router.post("/subscribe")
async def subscribe(
    data: SubscriptionRequest,
    session: DbSession,
):
    """Subscribe to push notifications.

    Saves the browser's push subscription to the database.
    """
    if not settings.PUSH_ENABLED:
        raise HTTPException(status_code=503, detail="Push notifications disabled")

    if "auth" not in data.keys or "p256dh" not in data.keys:
        raise HTTPException(status_code=400, detail="Missing keys (auth, p256dh)")

    repo = PushSubscriptionRepository(session)
    subscription = await repo.create_or_update(
        endpoint=data.endpoint,
        auth_key=data.keys["auth"],
        p256dh_key=data.keys["p256dh"],
    )
    await session.commit()

    logger.info(f"Push subscription created/updated: {subscription.id}")
    return {"status": "subscribed", "id": str(subscription.id)}


@router.post("/unsubscribe")
async def unsubscribe(
    data: UnsubscribeRequest,
    session: DbSession,
):
    """Unsubscribe from push notifications.

    Removes the browser's push subscription from the database.
    """
    repo = PushSubscriptionRepository(session)
    deleted = await repo.delete_by_endpoint(data.endpoint)
    await session.commit()

    if deleted:
        logger.info(f"Push subscription deleted: {data.endpoint[:50]}...")
        return {"status": "unsubscribed"}
    else:
        return {"status": "not_found"}


@router.post("/test")
async def send_test_notification(
    data: TestNotificationRequest,
    session: DbSession,
):
    """Send a test notification to all active subscriptions.

    Useful for verifying push notifications are working.
    """
    if not settings.PUSH_ENABLED:
        raise HTTPException(status_code=503, detail="Push notifications disabled")

    if not push_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Push notifications not configured (missing VAPID keys)"
        )

    repo = PushSubscriptionRepository(session)
    subscriptions = await repo.list_active()

    if not subscriptions:
        return {"status": "no_subscriptions", "sent": 0, "failed": 0}

    success, failed = await push_service.broadcast(
        subscriptions=subscriptions,
        title=data.title,
        body=data.body,
        url="/m/",
        tag="test",
    )

    # Deactivate failed subscriptions (likely expired)
    # We do this in a separate loop to avoid modifying during iteration
    if failed > 0:
        for sub in subscriptions:
            result = await push_service.send_to_subscription(
                sub, "ping", "test", tag="ping"
            )
            if not result:
                await repo.deactivate(sub.endpoint)
        await session.commit()

    return {"status": "sent", "sent": success, "failed": failed}


@router.get("/status")
async def get_push_status(session: DbSession):
    """Get push notification system status."""
    repo = PushSubscriptionRepository(session)
    active_count = len(await repo.list_active())

    return {
        "enabled": settings.PUSH_ENABLED,
        "configured": push_service.is_configured(),
        "active_subscriptions": active_count,
    }
