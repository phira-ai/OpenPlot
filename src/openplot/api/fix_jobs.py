from __future__ import annotations

from fastapi import APIRouter, Request

from ..services import fix_jobs as fix_jobs_service
from .schemas import StartFixJobRequest

router = APIRouter()


@router.get("/api/fix-jobs")
async def list_fix_jobs(
    request: Request,
    limit: int = 20,
    session_id: str | None = None,
):
    return await fix_jobs_service.list_fix_jobs(
        request.app.state.runtime,
        limit=limit,
        session_id=session_id,
    )


@router.get("/api/fix-jobs/current")
async def get_current_fix_job(request: Request, session_id: str | None = None):
    return await fix_jobs_service.get_current_fix_job(
        request.app.state.runtime,
        session_id=session_id,
    )


@router.post("/api/fix-jobs")
async def start_fix_job(body: StartFixJobRequest, request: Request):
    return await fix_jobs_service.start_fix_job(body, request.app.state.runtime)


@router.post("/api/fix-jobs/{job_id}/cancel")
async def cancel_fix_job(job_id: str, request: Request):
    _ = request
    return await fix_jobs_service.cancel_fix_job(job_id)
