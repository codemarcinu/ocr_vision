"""Ask AI (RAG) web routes."""

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.web.helpers import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/app/zapytaj/", response_class=HTMLResponse)
async def ask_page(request: Request):
    return templates.TemplateResponse("ask/index.html", {"request": request})


@router.post("/app/zapytaj/", response_class=HTMLResponse)
async def ask_submit(request: Request, question: str = Form(...)):
    if not settings.RAG_ENABLED:
        return templates.TemplateResponse("ask/partials/answer.html", {
            "request": request, "error": "RAG jest wylaczony",
        })

    try:
        from app.db.connection import get_session
        from app.rag import answerer

        async for session in get_session():
            result = await answerer.ask(question=question, session=session)
            return templates.TemplateResponse("ask/partials/answer.html", {
                "request": request,
                "question": question,
                "answer": result.answer,
                "sources": result.sources,
                "model_used": result.model_used,
                "processing_time": result.processing_time_sec,
                "chunks_found": result.chunks_found,
            })
    except Exception as e:
        logger.error(f"Ask error: {e}")
        return templates.TemplateResponse("ask/partials/answer.html", {
            "request": request, "question": question, "error": "Wystąpił błąd podczas przetwarzania pytania",
        })
