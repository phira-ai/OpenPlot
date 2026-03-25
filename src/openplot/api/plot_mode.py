from __future__ import annotations

from fastapi import APIRouter, Request

from ..services import plot_mode as plot_mode_service
from .schemas import (
    PlotModeChatRequest,
    PlotModeFinalizeRequest,
    PlotModePathSuggestionsRequest,
    PlotModeQuestionAnswerRequest,
    PlotModeSelectPathsRequest,
    PlotModeSettingsRequest,
    PlotModeTabularHintRequest,
)

router = APIRouter()


@router.get("/api/plot-mode")
async def get_plot_mode_state(request: Request):
    return plot_mode_service.get_plot_mode_state(request.app.state.runtime)


@router.post("/api/plot-mode/files")
async def set_plot_mode_files():
    return await plot_mode_service.set_plot_mode_files()


@router.post("/api/plot-mode/path-suggestions")
async def suggest_plot_mode_paths(
    body: PlotModePathSuggestionsRequest,
    request: Request,
):
    return await plot_mode_service.suggest_plot_mode_paths(
        body, request.app.state.runtime
    )


@router.post("/api/plot-mode/select-paths")
async def select_plot_mode_paths(
    body: PlotModeSelectPathsRequest,
    request: Request,
):
    return await plot_mode_service.select_plot_mode_paths(
        body, request.app.state.runtime
    )


@router.patch("/api/plot-mode/settings")
async def update_plot_mode_settings(body: PlotModeSettingsRequest, request: Request):
    return await plot_mode_service.update_plot_mode_settings(
        body, request.app.state.runtime
    )


@router.post("/api/plot-mode/tabular-hint")
async def submit_plot_mode_tabular_hint(
    body: PlotModeTabularHintRequest, request: Request
):
    return await plot_mode_service.submit_plot_mode_tabular_hint(
        body, request.app.state.runtime
    )


@router.post("/api/plot-mode/answer")
async def answer_plot_mode_question(
    body: PlotModeQuestionAnswerRequest, request: Request
):
    return await plot_mode_service.answer_plot_mode_question(
        body, request.app.state.runtime
    )


@router.post("/api/plot-mode/chat")
async def run_plot_mode_chat(body: PlotModeChatRequest, request: Request):
    return await plot_mode_service.run_plot_mode_chat(body, request.app.state.runtime)


@router.post("/api/plot-mode/finalize")
async def finalize_plot_mode(body: PlotModeFinalizeRequest, request: Request):
    return await plot_mode_service.finalize_plot_mode(body, request.app.state.runtime)


@router.patch("/api/plot-mode/workspace")
async def rename_plot_mode_workspace(request: Request):
    body = await request.json()
    return await plot_mode_service.rename_plot_mode_workspace(
        request.app.state.runtime, body
    )


@router.delete("/api/plot-mode")
async def delete_plot_mode_workspace(request: Request):
    requested_id = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            requested_id = body.get("id")
    except Exception:
        pass
    return await plot_mode_service.delete_plot_mode_workspace(
        request.app.state.runtime,
        requested_id,
    )


@router.post("/api/plot-mode/activate")
async def activate_plot_mode(request: Request):
    requested_id = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            requested_id = body.get("id")
    except Exception:
        pass
    return await plot_mode_service.activate_plot_mode(
        request.app.state.runtime,
        requested_id,
    )
