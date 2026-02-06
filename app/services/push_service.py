"""Web Push notification service."""

import json
import logging
from typing import Optional

from pywebpush import webpush, WebPushException

from app.config import settings
from app.db.models import PushSubscription

logger = logging.getLogger(__name__)


class PushService:
    """Service for sending Web Push notifications."""

    def __init__(self):
        self.vapid_private_key = settings.PUSH_VAPID_PRIVATE_KEY
        self.vapid_public_key = settings.PUSH_VAPID_PUBLIC_KEY
        self.vapid_subject = settings.PUSH_VAPID_SUBJECT

    def is_configured(self) -> bool:
        """Check if VAPID keys are configured."""
        return bool(self.vapid_private_key and self.vapid_public_key)

    async def send_to_subscription(
        self,
        subscription: PushSubscription,
        title: str,
        body: str,
        url: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> bool:
        """Send push notification to a single subscription.

        Returns True if successful, False if failed.
        """
        if not self.is_configured():
            logger.warning("Push notifications not configured (missing VAPID keys)")
            return False

        payload = {
            "title": title,
            "body": body,
            "url": url or "/m/",
            "tag": tag or "default",
        }

        subscription_info = {
            "endpoint": subscription.endpoint,
            "keys": {
                "auth": subscription.auth_key,
                "p256dh": subscription.p256dh_key,
            },
        }

        try:
            webpush(
                subscription_info=subscription_info,
                data=json.dumps(payload),
                vapid_private_key=self.vapid_private_key,
                vapid_claims={"sub": self.vapid_subject},
            )
            logger.info(f"Push sent to endpoint: {subscription.endpoint[:50]}...")
            return "ok"
        except WebPushException as e:
            # 410 Gone or 404 Not Found = subscription expired/invalid
            if e.response and e.response.status_code in (410, 404):
                logger.info(f"Subscription expired ({e.response.status_code}): {subscription.endpoint[:50]}...")
                return "expired"
            logger.error(f"Push failed: {e}")
            return "error"
        except Exception as e:
            logger.exception(f"Unexpected error sending push: {e}")
            return "error"

    async def broadcast(
        self,
        subscriptions: list[PushSubscription],
        title: str,
        body: str,
        url: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> tuple[int, int, list[str]]:
        """Send push notification to multiple subscriptions.

        Returns (success_count, failure_count, expired_endpoints).
        """
        success = 0
        failed = 0
        expired_endpoints: list[str] = []

        for sub in subscriptions:
            result = await self.send_to_subscription(sub, title, body, url, tag)
            if result == "ok":
                success += 1
            elif result == "expired":
                failed += 1
                expired_endpoints.append(sub.endpoint)
            else:
                failed += 1

        logger.info(f"Broadcast complete: {success} sent, {failed} failed")
        return success, failed, expired_endpoints


# Singleton instance
push_service = PushService()
