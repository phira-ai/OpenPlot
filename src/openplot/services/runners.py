"""Runner, preferences, update, and interpreter service helpers."""

from __future__ import annotations

import asyncio
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, cast

from fastapi import HTTPException

from .. import server
from .. import server_python_runtime
from .. import server_runners
from .. import server_runtime_bootstrap

if TYPE_CHECKING:
    from ..api.schemas import (
        OpenExternalUrlRequest,
        PreferencesRequest,
        PythonInterpreterRequest,
        RunnerAuthLaunchRequest,
        RunnerInstallRequest,
    )
    from .runtime import BackendRuntime


async def _to_thread_with_runtime(
    runtime: "BackendRuntime",
    callback,
    /,
    *args,
    **kwargs,
):
    return await asyncio.to_thread(
        lambda: server_runtime_bootstrap._with_runtime(
            server, runtime, lambda: callback(*args, **kwargs)
        )
    )


async def get_preferences() -> dict[str, object]:
    fix_runner, fix_model, fix_variant = server._load_fix_preferences()
    return {
        "fix_runner": fix_runner,
        "fix_model": fix_model,
        "fix_variant": fix_variant,
    }


async def set_preferences(body: "PreferencesRequest") -> dict[str, object]:
    current_runner, current_model, current_variant = server._load_fix_preferences()

    runner = server._normalize_fix_runner(
        body.fix_runner,
        default=current_runner,
    )

    model: str | None
    if "fix_model" in body.model_fields_set:
        model_raw = body.fix_model
        model_candidate = str(model_raw).strip() if model_raw is not None else ""
        model = model_candidate or None
    else:
        model = current_model

    if model is None:
        variant = None
    elif "fix_variant" in body.model_fields_set:
        variant_raw = body.fix_variant
        variant_candidate = str(variant_raw).strip() if variant_raw is not None else ""
        variant = variant_candidate or None
    else:
        variant = current_variant

    try:
        models = await asyncio.to_thread(
            server_runners._refresh_runner_models_cache,
            server,
            runner,
        )
    except RuntimeError:
        models = []

    if model:
        server_runners._validate_runner_model_selection(
            server,
            runner=runner,
            model=model,
            variant=variant,
            models=models,
        )

    try:
        await asyncio.to_thread(
            server._save_fix_preferences,
            runner=runner,
            model=model,
            variant=variant,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save preferences: {exc}",
        ) from exc
    return {
        "status": "ok",
        "fix_runner": runner,
        "fix_model": model,
        "fix_variant": variant,
    }


async def get_runners() -> dict[str, object]:
    availability = await asyncio.to_thread(
        server_runners._detect_runner_availability, server
    )
    return {
        "available_runners": availability["available_runners"],
        "supported_runners": availability["supported_runners"],
        "claude_code_available": availability["claude_code_available"],
    }


async def get_runner_status() -> dict[str, object]:
    return await asyncio.to_thread(server_runners._build_runner_status_payload, server)


async def install_runner(
    body: "RunnerInstallRequest",
    runtime: "BackendRuntime",
) -> dict[str, object]:
    payload = await asyncio.to_thread(
        server_runners._build_runner_status_payload, server
    )
    runner_entries = cast(list[dict[str, object]], payload.get("runners") or [])
    entry = next(
        (item for item in runner_entries if item.get("runner") == body.runner), None
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown runner")
    if entry.get("primary_action") != "install":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Runner '{body.runner}' does not support click-install on this machine. "
                f"Use the guide instead: {entry.get('guide_url')}"
            ),
        )
    job = await asyncio.to_thread(
        server_runners._create_runner_install_job,
        server,
        body.runner,
        runtime=runtime,
    )
    return {"job": job}


async def launch_runner_auth(body: "RunnerAuthLaunchRequest") -> dict[str, object]:
    payload = await asyncio.to_thread(
        server_runners._build_runner_status_payload, server
    )
    runner_entries = cast(list[dict[str, object]], payload.get("runners") or [])
    entry = next(
        (item for item in runner_entries if item.get("runner") == body.runner), None
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown runner")
    if entry.get("primary_action") != "authenticate":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Runner '{body.runner}' is not waiting for Terminal authentication on this machine."
            ),
        )
    await asyncio.to_thread(
        server_runners._launch_runner_auth_terminal, server, body.runner
    )
    return {
        "status": "ok",
        "auth_command": entry.get("auth_command"),
        "auth_instructions": entry.get("auth_instructions"),
    }


async def open_external_url(body: "OpenExternalUrlRequest") -> dict[str, object]:
    url = body.url.strip()
    if not url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Only http(s) URLs are supported")
    await asyncio.to_thread(webbrowser.open, url)
    return {"status": "ok"}


async def refresh_update_status(runtime: "BackendRuntime") -> dict[str, object]:
    return await asyncio.to_thread(
        server.build_update_status_payload,
        runtime,
        allow_network=True,
        force_refresh=True,
    )


async def get_python_interpreter(
    runtime: "BackendRuntime",
    *,
    session_id: str | None = None,
) -> dict[str, object]:
    def _resolve_session_for_python():
        server._ensure_session_store_loaded()
        return (
            server._resolve_request_session(session_id)
            if session_id is not None
            else server._runtime_active_session_value()
        )

    session = server_runtime_bootstrap._with_runtime(
        server, runtime, _resolve_session_for_python
    )
    return await _to_thread_with_runtime(
        runtime,
        server_python_runtime._resolve_python_interpreter_state,
        server,
        session,
    )


async def set_python_interpreter(
    body: "PythonInterpreterRequest",
    runtime: "BackendRuntime",
) -> dict[str, object]:
    server_runtime_bootstrap._with_runtime(
        server, runtime, lambda: server._ensure_session_store_loaded()
    )
    mode = body.mode
    if mode not in {"builtin", "manual", "auto"}:
        raise HTTPException(
            status_code=400,
            detail="Mode must be 'builtin', 'manual', or 'auto'",
        )

    if mode in {"builtin", "auto"}:
        try:
            await _to_thread_with_runtime(
                runtime,
                server_python_runtime._save_python_interpreter_preference,
                server,
                None,
            )
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save interpreter preference: {exc}",
            ) from exc
        session = server_runtime_bootstrap._with_runtime(
            server, runtime, lambda: server._runtime_active_session_value()
        )
        return await _to_thread_with_runtime(
            runtime,
            server_python_runtime._resolve_python_interpreter_state,
            server,
            session,
        )

    path_raw = body.path
    path = str(path_raw).strip() if path_raw is not None else ""
    if not path:
        raise HTTPException(
            status_code=400,
            detail="Missing interpreter path for manual mode",
        )

    candidate, validation_error = await _to_thread_with_runtime(
        runtime,
        server_python_runtime._validated_python_candidate,
        server,
        Path(path),
        source="manual",
    )
    if candidate is None:
        raise HTTPException(
            status_code=400,
            detail=validation_error or "Invalid interpreter path",
        )

    try:
        await _to_thread_with_runtime(
            runtime,
            server_python_runtime._save_python_interpreter_preference,
            server,
            candidate["path"],
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save interpreter preference: {exc}",
        ) from exc

    session = server_runtime_bootstrap._with_runtime(
        server, runtime, lambda: server._runtime_active_session_value()
    )
    return await _to_thread_with_runtime(
        runtime,
        server_python_runtime._resolve_python_interpreter_state,
        server,
        session,
    )


async def get_runner_models(
    *,
    runner: str = "opencode",
    force_refresh: bool = False,
) -> dict[str, object]:
    normalized_runner = server._normalize_fix_runner(
        runner, default=server._default_fix_runner
    )
    server._ensure_runner_is_available(normalized_runner)
    fallback_to_empty_models = False
    try:
        models = await asyncio.to_thread(
            server_runners._refresh_runner_models_cache,
            server,
            normalized_runner,
            force_refresh=force_refresh,
        )
    except RuntimeError as exc:
        if normalized_runner == "codex" and "model cache not found" in str(exc).lower():
            models = []
            fallback_to_empty_models = True
        else:
            raise HTTPException(
                status_code=503,
                detail=f"Failed to load models from {normalized_runner}: {exc}",
            ) from exc

    preferred_runner, preferred_model, preferred_variant = await asyncio.to_thread(
        server._load_fix_preferences
    )
    if fallback_to_empty_models and preferred_runner != normalized_runner:
        preferred_model = server._runner_default_model_id(normalized_runner)
        preferred_variant = None
    default_model, default_variant = server._resolve_runner_default_model_and_variant(
        runner=normalized_runner,
        models=models,
        preferred_runner=preferred_runner,
        preferred_model=preferred_model,
        preferred_variant=preferred_variant,
    )

    return {
        "runner": normalized_runner,
        "models": [model.model_dump() for model in models],
        "default_model": default_model,
        "default_variant": default_variant,
    }


async def get_opencode_models(*, force_refresh: bool = False) -> dict[str, object]:
    payload = await get_runner_models(runner="opencode", force_refresh=force_refresh)
    return {
        "models": payload["models"],
        "default_model": payload["default_model"],
        "default_variant": payload["default_variant"],
    }
