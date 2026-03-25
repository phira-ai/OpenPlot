"""Fix job workflow service helpers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from ..api.schemas import StartFixJobRequest
    from .runtime import BackendRuntime


async def list_fix_jobs(
    runtime: "BackendRuntime",
    *,
    limit: int = 20,
    session_id: str | None = None,
) -> dict[str, object]:
    from .. import server

    await server._reconcile_active_fix_job_state()
    bounded_limit = max(1, min(limit, 100))
    fix_jobs = server._runtime_fix_jobs_map()

    normalized_session_id = (
        session_id.strip() if session_id is not None and session_id.strip() else None
    )
    filtered_jobs = (
        [job for job in fix_jobs.values() if job.session_id == normalized_session_id]
        if normalized_session_id
        else list(fix_jobs.values())
    )

    sorted_jobs = sorted(filtered_jobs, key=lambda job: job.created_at, reverse=True)

    effective_session_id = normalized_session_id
    if effective_session_id is None:
        effective_session_id = runtime.store.active_session_id
        if effective_session_id is None and runtime.store.active_session is not None:
            effective_session_id = runtime.store.active_session.id

    return {
        "active_job_id": server._active_fix_job_id_for_session(effective_session_id),
        "jobs": [job.model_dump(mode="json") for job in sorted_jobs[:bounded_limit]],
    }


async def get_current_fix_job(
    runtime: "BackendRuntime",
    *,
    session_id: str | None = None,
) -> dict[str, object]:
    from .. import server

    await server._reconcile_active_fix_job_state()
    fix_jobs = server._runtime_fix_jobs_map()
    active_fix_jobs = server._runtime_active_fix_jobs_map()

    normalized_session_id = (
        session_id.strip() if session_id is not None and session_id.strip() else None
    )
    if normalized_session_id is None:
        normalized_session_id = runtime.store.active_session_id
        if normalized_session_id is None and runtime.store.active_session is not None:
            normalized_session_id = runtime.store.active_session.id

    if normalized_session_id:
        active_job_id = server._active_fix_job_id_for_session(normalized_session_id)
        if active_job_id:
            active_job = fix_jobs.get(active_job_id)
            if active_job is not None:
                return {"job": active_job.model_dump(mode="json")}

        session_jobs = [
            job for job in fix_jobs.values() if job.session_id == normalized_session_id
        ]
        if not session_jobs:
            return {"job": None}

        latest_session_job = max(session_jobs, key=lambda job: job.created_at)
        return {"job": latest_session_job.model_dump(mode="json")}

    for key, active_job_id in list(active_fix_jobs.items()):
        active_job = fix_jobs.get(active_job_id)
        if active_job is not None:
            return {"job": active_job.model_dump(mode="json")}
        active_fix_jobs.pop(key, None)

    if not fix_jobs:
        return {"job": None}

    latest_job = max(fix_jobs.values(), key=lambda job: job.created_at)
    return {"job": latest_job.model_dump(mode="json")}


async def start_fix_job(
    body: "StartFixJobRequest",
    runtime: "BackendRuntime",
) -> dict[str, object]:
    from .. import server

    await server._reconcile_active_fix_job_state()

    session_id_raw = body.session_id
    requested_session_id = (
        str(session_id_raw).strip() if session_id_raw is not None else None
    )
    session = server._resolve_request_session(requested_session_id)

    active_job_id = server._active_fix_job_id_for_session(session.id)
    if active_job_id:
        existing = server._runtime_fix_jobs_map().get(active_job_id)
        if existing and not server._is_terminal_fix_job_status(existing.status):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "A fix job is already running in this workspace",
                    "job": existing.model_dump(mode="json"),
                },
            )
        server._clear_active_fix_job_for_session(
            session.id, expected_job_id=active_job_id
        )

    pending = server.pending_annotations_for_context(session)
    if not pending:
        raise HTTPException(
            status_code=409,
            detail="No pending annotations in the current branch/context",
        )

    preferred_runner, _preferred_model, _preferred_variant = (
        server._load_fix_preferences()
    )
    runner = server._normalize_fix_runner(body.runner, default=preferred_runner)
    server._ensure_runner_is_available(runner)

    model = body.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="Missing model")

    variant_raw = body.variant
    variant = str(variant_raw).strip() if variant_raw is not None else ""
    normalized_variant = variant or None

    try:
        models = await asyncio.to_thread(server._refresh_runner_models_cache, runner)
    except RuntimeError:
        models = []

    server._validate_runner_model_selection(
        runner=runner,
        model=model,
        variant=normalized_variant,
        models=models,
    )

    try:
        await asyncio.to_thread(
            server._save_fix_preferences,
            runner=runner,
            model=model,
            variant=normalized_variant,
        )
    except OSError:
        pass

    active_branch = server._active_branch(session)
    job = server.FixJob(
        runner=runner,
        model=model,
        variant=normalized_variant,
        session_id=session.id,
        workspace_dir="",
        branch_id=active_branch.id,
        branch_name=active_branch.name,
        total_annotations=len(pending),
    )
    job.workspace_dir = str(
        server._prepare_fix_runner_workspace(session, job_id=job.id)
    )

    server._runtime_fix_jobs_map()[job.id] = job
    server._set_active_fix_job_for_session(session.id, job.id)

    task = asyncio.create_task(server._run_fix_job_loop(job.id, runtime=runtime))
    server._runtime_fix_job_tasks_map()[job.id] = task

    await server._broadcast_fix_job(job)
    return {"status": "ok", "job": job.model_dump(mode="json")}


async def cancel_fix_job(job_id: str) -> dict[str, object]:
    from .. import server

    await server._reconcile_active_fix_job_state()
    job = server._runtime_fix_jobs_map().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Fix job not found")

    if server._is_terminal_fix_job_status(job.status):
        server._clear_active_fix_job_for_session(job.session_id, expected_job_id=job.id)
        return {"status": "ok", "job": job.model_dump(mode="json")}

    await server._cancel_fix_job_execution(job, reason="Cancelled by user")
    return {"status": "ok", "job": job.model_dump(mode="json")}
