from __future__ import annotations

from fastapi import APIRouter, Request

from ..services import sessions as session_services
from .schemas import RenameSessionRequest

router = APIRouter()


@router.get("/api/bootstrap")
async def get_bootstrap_state(request: Request):
    runtime = request.app.state.runtime
    return session_services.build_bootstrap_payload(runtime)


@router.get("/api/session")
async def get_session_state(session_id: str | None = None):
    return session_services.get_session_state(session_id=session_id)


@router.get("/api/sessions")
async def list_sessions(request: Request):
    runtime = request.app.state.runtime
    return session_services.build_sessions_payload(runtime)


@router.post("/api/sessions/new")
async def create_new_session(request: Request):
    runtime = request.app.state.runtime
    return await session_services.create_new_session(runtime)


@router.post("/api/sessions/{session_id}/activate")
async def activate_session(session_id: str, request: Request):
    runtime = request.app.state.runtime
    return await session_services.activate_session(runtime, session_id)


@router.patch("/api/sessions/{session_id}")
async def rename_session(
    session_id: str,
    body: RenameSessionRequest,
    request: Request,
):
    runtime = request.app.state.runtime
    return session_services.rename_session(runtime, session_id, body)


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    runtime = request.app.state.runtime
    return await session_services.delete_session(runtime, session_id)
