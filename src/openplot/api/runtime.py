from __future__ import annotations

from fastapi import APIRouter, Request

from ..services import runners as runner_services
from .schemas import OpenExternalUrlRequest, PythonInterpreterRequest

router = APIRouter()


@router.post("/api/open-external-url")
async def open_external_url(body: OpenExternalUrlRequest):
    return await runner_services.open_external_url(body)


@router.post("/api/update-status/refresh")
async def refresh_update_status(request: Request):
    runtime = request.app.state.runtime
    return await runner_services.refresh_update_status(runtime)


@router.get("/api/python/interpreter")
async def get_python_interpreter(request: Request, session_id: str | None = None):
    runtime = request.app.state.runtime
    return await runner_services.get_python_interpreter(runtime, session_id=session_id)


@router.post("/api/python/interpreter")
async def set_python_interpreter(body: PythonInterpreterRequest, request: Request):
    runtime = request.app.state.runtime
    return await runner_services.set_python_interpreter(body, runtime)
