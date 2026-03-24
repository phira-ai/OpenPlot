from __future__ import annotations

from fastapi import APIRouter, Request

from ..services import artifacts as artifacts_service

router = APIRouter()


@router.get("/api/plot")
async def get_plot(
    request: Request,
    session_id: str | None = None,
    version_id: str | None = None,
    plot_mode: bool = False,
    workspace_id: str | None = None,
):
    return await artifacts_service.get_plot(
        request.app.state.runtime,
        session_id=session_id,
        version_id=version_id,
        plot_mode=plot_mode,
        workspace_id=workspace_id,
    )


@router.get("/api/plot-mode/export")
async def export_plot_mode_workspace(
    request: Request,
    workspace_id: str | None = None,
):
    return await artifacts_service.export_plot_mode_workspace(
        request.app.state.runtime,
        workspace_id=workspace_id,
    )


@router.get("/api/feedback")
async def get_feedback(session_id: str | None = None):
    return await artifacts_service.get_feedback(session_id=session_id)
