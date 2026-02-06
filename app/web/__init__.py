"""Web UI routes - split by feature module."""

from fastapi import APIRouter

from app.web.analytics import router as analytics_router
from app.web.articles import router as articles_router
from app.web.ask import router as ask_router
from app.web.bookmarks import router as bookmarks_router
from app.web.chat import router as chat_router
from app.web.dashboard import router as dashboard_router
from app.web.dictionary import router as dictionary_router
from app.web.notes import router as notes_router
from app.web.pantry import router as pantry_router
from app.web.receipts import router as receipts_router
from app.web.redirects import router as redirects_router
from app.web.search import router as search_router
from app.web.transcriptions import router as transcriptions_router

router = APIRouter(tags=["Web UI"])

router.include_router(dashboard_router)
router.include_router(receipts_router)
router.include_router(pantry_router)
router.include_router(analytics_router)
router.include_router(articles_router)
router.include_router(transcriptions_router)
router.include_router(notes_router)
router.include_router(bookmarks_router)
router.include_router(dictionary_router)
router.include_router(search_router)
router.include_router(ask_router)
router.include_router(chat_router)
router.include_router(redirects_router)
