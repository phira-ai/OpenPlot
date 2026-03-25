from __future__ import annotations

from fastapi import APIRouter, Request

from ..services import runners as runner_services
from .schemas import RunnerAuthLaunchRequest, RunnerInstallRequest

router = APIRouter()


@router.get("/api/runners")
async def get_runners():
    return await runner_services.get_runners()


@router.get("/api/runners/status")
async def get_runner_status():
    return await runner_services.get_runner_status()


@router.post("/api/runners/install")
async def install_runner(body: RunnerInstallRequest, request: Request):
    runtime = request.app.state.runtime
    return await runner_services.install_runner(body, runtime=runtime)


@router.post("/api/runners/auth/launch")
async def launch_runner_auth(body: RunnerAuthLaunchRequest):
    return await runner_services.launch_runner_auth(body)


@router.get("/api/runners/models")
async def get_runner_models(runner: str = "opencode", force_refresh: bool = False):
    return await runner_services.get_runner_models(
        runner=runner,
        force_refresh=force_refresh,
    )


@router.get("/api/opencode/models")
async def get_opencode_models(force_refresh: bool = False):
    return await runner_services.get_opencode_models(force_refresh=force_refresh)
