"""Redirects from old URLs for backwards compatibility."""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter()


@router.get("/web/dictionary")
async def redirect_dictionary():
    return RedirectResponse(url="/app/slownik/", status_code=301)


@router.get("/web/pantry")
async def redirect_pantry():
    return RedirectResponse(url="/app/spizarnia/", status_code=301)


@router.get("/web/receipts")
async def redirect_receipts():
    return RedirectResponse(url="/app/paragony/", status_code=301)


@router.get("/web/search")
async def redirect_search():
    return RedirectResponse(url="/app/szukaj/", status_code=301)
