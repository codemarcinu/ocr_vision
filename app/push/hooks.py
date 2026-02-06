"""Fire-and-forget push notification hooks for content creation flows.

Mirrors the pattern from app/rag/hooks.py: each hook is guarded by
PUSH_ENABLED, uses lazy imports, catches all exceptions, and never
propagates errors to the caller.
"""

import logging

from app.config import settings

logger = logging.getLogger(__name__)


async def _broadcast_push(
    title: str,
    body: str,
    url: str = "/m/",
    tag: str = "default",
) -> None:
    """Fetch active subscriptions and broadcast a push notification.

    Uses its own DB session to avoid coupling with the caller's transaction.
    """
    if not settings.PUSH_ENABLED:
        return

    try:
        from app.services.push_service import push_service

        if not push_service.is_configured():
            return

        from app.db.connection import get_session_context
        from app.db.repositories.push import PushSubscriptionRepository

        async with get_session_context() as session:
            repo = PushSubscriptionRepository(session)
            subscriptions = await repo.list_active()
            if not subscriptions:
                return

            success, failed = await push_service.broadcast(
                subscriptions=subscriptions,
                title=title,
                body=body,
                url=url,
                tag=tag,
            )
            logger.info(f"Push broadcast ({tag}): {success} sent, {failed} failed")
    except Exception as e:
        logger.warning(f"Push notification failed ({tag}): {e}")


async def push_receipt_processed(
    store_name: str | None,
    total: float | None,
    item_count: int,
    receipt_id: str | None = None,
) -> None:
    """Push after receipt OCR completes."""
    store = store_name or "Nieznany sklep"
    total_str = f"{total:.2f} PLN" if total else "?"

    await _broadcast_push(
        title=f"Paragon: {store}",
        body=f"Suma: {total_str}, produktów: {item_count}",
        url=f"/m/paragony/{receipt_id}" if receipt_id else "/m/paragony",
        tag="receipt",
    )


async def push_note_created(
    title: str,
    note_id: str | None = None,
) -> None:
    """Push when a note is created."""
    await _broadcast_push(
        title="Nowa notatka",
        body=title[:100],
        url=f"/m/notatki/{note_id}" if note_id else "/m/notatki",
        tag="note",
    )


async def push_articles_fetched(new_count: int) -> None:
    """Push when RSS articles are fetched."""
    if new_count <= 0:
        return

    await _broadcast_push(
        title="Nowe artykuły",
        body=f"Pobrano {new_count} nowych artykułów",
        url="/m/wiedza",
        tag="rss",
    )


async def push_bookmark_created(
    title: str,
    bookmark_id: str | None = None,
) -> None:
    """Push when a bookmark is created."""
    await _broadcast_push(
        title="Nowa zakładka",
        body=title[:100] if title else "Nowa zakładka",
        url="/m/wiedza",
        tag="bookmark",
    )
