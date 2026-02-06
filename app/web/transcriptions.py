"""Transcription web routes."""

from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.dependencies import DbSession
from app.web.helpers import _htmx_trigger, templates

router = APIRouter()


@router.get("/app/transkrypcje/", response_class=HTMLResponse)
async def transcriptions_page(request: Request, session: DbSession):
    from app.db.repositories.transcription import TranscriptionJobRepository
    repo = TranscriptionJobRepository(session)
    jobs = await repo.get_recent_jobs(limit=20)
    return templates.TemplateResponse("transcriptions/list.html", {
        "request": request, "jobs": jobs,
    })


@router.get("/app/transkrypcje/{job_id}", response_class=HTMLResponse)
async def transcription_detail(request: Request, job_id: UUID, session: DbSession):
    from app.db.repositories.transcription import TranscriptionJobRepository
    repo = TranscriptionJobRepository(session)
    job = await repo.get_with_transcription(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job nie znaleziony")
    return templates.TemplateResponse("transcriptions/detail.html", {
        "request": request, "job": job,
    })


@router.post("/app/transkrypcje/new", response_class=HTMLResponse)
async def transcription_new(request: Request, session: DbSession, url: str = Form(...)):
    from app.db.repositories.transcription import TranscriptionJobRepository
    repo = TranscriptionJobRepository(session)
    job = await repo.create_job(source_type="youtube", source_url=url, title=url)
    await session.commit()

    jobs = await repo.get_recent_jobs(limit=20)
    response = templates.TemplateResponse("transcriptions/partials/job_list.html", {
        "request": request, "jobs": jobs,
    })
    response.headers.update(_htmx_trigger("Transkrypcja dodana do kolejki"))
    return response
