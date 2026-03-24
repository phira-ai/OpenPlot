"""Runtime-owned session bootstrap, restore, and teardown helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from ..models import FixJob, PlotModeState, PlotSession
from .naming import normalize_workspace_name

if TYPE_CHECKING:
    from ..api.schemas import RenameSessionRequest
    from .runtime import BackendRuntime


def _run_with_runtime(runtime: "BackendRuntime", callback):
    from .. import server

    if server._bound_runtime is runtime:
        return callback()
    return server._with_runtime(runtime, callback)


def should_restore_session_store(runtime: "BackendRuntime") -> bool:
    from .. import server

    if server._runtime_is_shared(runtime):
        return True
    if runtime.state_root is None:
        return False
    return (
        runtime.store.loaded_session_store_root is None
        and not runtime.store.sessions
        and runtime.store.active_session is None
        and runtime.store.active_session_id is None
        and runtime.store.plot_mode is None
    )


def ensure_session_store_loaded(
    runtime: "BackendRuntime", *, force_reload: bool = False
) -> None:
    from .. import server

    if (
        not force_reload
        and not server._runtime_is_shared(runtime)
        and runtime.state_root is None
    ):
        return

    if (
        server._runtime_is_shared(runtime)
        and server._bound_runtime is None
        and server._current_runtime_var.get() is None
    ):
        server._ensure_session_store_loaded_impl(force_reload=force_reload)
        return

    _run_with_runtime(
        runtime,
        lambda: server._ensure_session_store_loaded_impl(force_reload=force_reload),
    )


def restore_latest_workspace(
    runtime: "BackendRuntime",
) -> tuple[Literal["annotation", "plot"], PlotSession | PlotModeState] | None:
    from .. import server

    def _restore() -> (
        tuple[Literal["annotation", "plot"], PlotSession | PlotModeState] | None
    ):
        ensure_session_store_loaded(runtime)
        sessions = server._runtime_sessions_map()
        latest_session = (
            max(sessions.values(), key=server._session_sort_key) if sessions else None
        )
        latest_plot_mode = server._runtime_plot_mode_state_value()
        if latest_plot_mode is None:
            persisted_plot_workspaces = server._load_all_plot_mode_workspaces()
            latest_plot_mode = (
                max(persisted_plot_workspaces, key=server._plot_mode_sort_key)
                if persisted_plot_workspaces
                else None
            )
        elif not server._plot_mode_is_workspace(latest_plot_mode):
            latest_plot_mode = None

        if latest_session is None and latest_plot_mode is None:
            return None
        if latest_session is None:
            return ("plot", cast(PlotModeState, latest_plot_mode))
        if latest_plot_mode is None:
            return ("annotation", latest_session)
        if server._session_sort_key(latest_session) >= server._plot_mode_sort_key(
            latest_plot_mode
        ):
            return ("annotation", latest_session)
        return ("plot", latest_plot_mode)

    return _run_with_runtime(runtime, _restore)


def restore_latest_workspace_into_runtime(runtime: "BackendRuntime") -> None:
    from .. import server

    if not server._runtime_is_shared(runtime) and runtime.state_root is None:
        return

    def _hydrate() -> None:
        ensure_session_store_loaded(runtime)

        latest_workspace = restore_latest_workspace(runtime)
        if latest_workspace is not None:
            workspace_mode, workspace = latest_workspace
            if workspace_mode == "annotation":
                session = cast(PlotSession, workspace)
                server._set_active_session(session.id, clear_plot_mode=False)
            else:
                server._set_active_session(None, clear_plot_mode=False)
                state = cast(PlotModeState, workspace)
                server._plot_mode = state
                runtime.store.plot_mode = state
                server.set_workspace_dir(Path(state.workspace_dir))
                server._save_plot_mode_snapshot(state)

        runtime.store.active_session_id = server._runtime_active_session_id_value()
        runtime.store.active_session = server._runtime_active_session_value()
        runtime.store.plot_mode = server._runtime_plot_mode_state_value()
        runtime.store.workspace_dir = server._runtime_workspace_dir()
        runtime.store.active_workspace_id = server._active_workspace_id()
        runtime.store.loaded_session_store_root = server._loaded_session_store_root

    _run_with_runtime(runtime, _hydrate)


def list_session_summaries(runtime: "BackendRuntime") -> list[dict[str, object]]:
    from .. import server

    def _list() -> list[dict[str, object]]:
        ensure_session_store_loaded(runtime)
        sessions = server._runtime_sessions_map()
        active_plot_mode = server._runtime_plot_mode_state_value()
        summaries = [server._session_summary(session) for session in sessions.values()]

        seen_ids: set[str] = {
            server._session_workspace_id(session) for session in sessions.values()
        }
        if active_plot_mode is not None and server._plot_mode_is_workspace(
            active_plot_mode
        ):
            if active_plot_mode.id not in seen_ids:
                summaries.append(server._plot_mode_summary(active_plot_mode))
                seen_ids.add(active_plot_mode.id)

        for plot_workspace in server._load_all_plot_mode_workspaces():
            if plot_workspace.id not in seen_ids:
                summaries.append(server._plot_mode_summary(plot_workspace))
                seen_ids.add(plot_workspace.id)

        summaries.sort(key=server._workspace_summary_sort_key, reverse=True)
        return summaries

    return _run_with_runtime(runtime, _list)


def _build_workspace_payload(runtime: "BackendRuntime") -> dict[str, object]:
    from .. import server

    def _build() -> dict[str, object]:
        ensure_session_store_loaded(runtime)

        if (
            server._runtime_active_session_value() is None
            and server._runtime_plot_mode_state_value() is None
        ):
            restore_latest_workspace_into_runtime(runtime)

        active_session = server._runtime_active_session_value()
        if active_session is not None:
            session = server.get_session()
            server._rebuild_revision_history(session)
            return server._bootstrap_payload(
                mode="annotation",
                session=session,
                plot_mode=None,
            )

        state = (
            server._runtime_plot_mode_state_value()
            or server.init_plot_mode_session(
                workspace_dir=server._runtime_workspace_dir()
            )
        )
        return server._bootstrap_payload(mode="plot", session=None, plot_mode=state)

    return _run_with_runtime(runtime, _build)


def build_bootstrap_payload(runtime: "BackendRuntime") -> dict[str, object]:
    return _build_workspace_payload(runtime)


def build_plot_mode_payload(runtime: "BackendRuntime") -> dict[str, object]:
    return _build_workspace_payload(runtime)


def build_sessions_payload(runtime: "BackendRuntime") -> dict[str, object]:
    from .. import server

    def _build() -> dict[str, object]:
        ensure_session_store_loaded(runtime)
        active_session = server._runtime_active_session_value()
        return {
            "sessions": list_session_summaries(runtime),
            "active_session_id": server._runtime_active_session_id_value(),
            "active_workspace_id": server._active_workspace_id(),
            "mode": "annotation" if active_session is not None else "plot",
        }

    return _run_with_runtime(runtime, _build)


def get_session_state(session_id: str | None = None) -> dict[str, object]:
    from .. import server

    session = server._resolve_request_session(session_id)
    server._rebuild_revision_history(session)
    return session.model_dump()


async def create_new_session(runtime: "BackendRuntime") -> dict[str, object]:
    from .. import server

    state = _run_with_runtime(
        runtime,
        lambda: server.init_plot_mode_session(
            workspace_dir=None,
            persist_workspace=True,
        ),
    )
    await server._broadcast(
        {
            "type": "plot_mode_updated",
            "plot_mode": state.model_dump(mode="json"),
        }
    )
    return _run_with_runtime(
        runtime,
        lambda: server._bootstrap_payload(mode="plot", session=None, plot_mode=state),
    )


async def activate_session(
    runtime: "BackendRuntime",
    session_id: str,
) -> dict[str, object]:
    from .. import server

    def _activate_session_request() -> tuple[PlotSession, dict[str, object]]:
        ensure_session_store_loaded(runtime)

        session = server._runtime_sessions_map().get(session_id)
        if session is None:
            raise server.HTTPException(
                status_code=404,
                detail=f"Session not found: {session_id}",
            )

        server._set_active_session(session_id, clear_plot_mode=False)
        active_session = server.get_session()
        server._rebuild_revision_history(active_session)
        server._touch_session(active_session)
        server._persist_session(active_session, promote=True)
        return active_session, server._bootstrap_payload(
            mode="annotation",
            session=active_session,
            plot_mode=None,
        )

    active_session, payload = _run_with_runtime(runtime, _activate_session_request)

    await server._broadcast(
        {
            "type": "plot_updated",
            "session_id": active_session.id,
            "version_id": active_session.checked_out_version_id,
            "plot_type": active_session.plot_type,
            "revision": len(active_session.revision_history),
            "active_branch_id": active_session.active_branch_id,
            "checked_out_version_id": active_session.checked_out_version_id,
            "reason": "session_switch",
        }
    )

    return payload


def rename_session(
    runtime: "BackendRuntime",
    session_id: str,
    body: "RenameSessionRequest",
) -> dict[str, object]:
    from .. import server

    def _rename_session_request() -> dict[str, object]:
        ensure_session_store_loaded(runtime)

        target = server._runtime_sessions_map().get(session_id)
        if target is None:
            raise server.HTTPException(
                status_code=404,
                detail=f"Session not found: {session_id}",
            )

        raw_name = body.workspace_name if body.workspace_name is not None else body.name
        next_name = normalize_workspace_name(raw_name)

        target.workspace_name = next_name
        server._touch_session(target)
        server._persist_session(target, promote=True)

        workspace_id = server._session_workspace_id(target)
        active_plot_mode = server._runtime_plot_mode_state_value()
        if active_plot_mode is not None and active_plot_mode.id == workspace_id:
            active_plot_mode.workspace_name = next_name
            server._touch_plot_mode(active_plot_mode)
        else:
            persisted_plot_mode = server._load_plot_mode_workspace_by_id(workspace_id)
            if persisted_plot_mode is not None:
                persisted_plot_mode.workspace_name = next_name
                server._touch_plot_mode(persisted_plot_mode)

        return {
            "status": "ok",
            "workspace": server._session_summary(target),
            "active_session_id": server._runtime_active_session_id_value(),
        }

    return _run_with_runtime(runtime, _rename_session_request)


async def delete_session(
    runtime: "BackendRuntime", session_id: str
) -> dict[str, object]:
    from .. import server

    def _load_delete_context() -> tuple[PlotSession, list[FixJob]]:
        ensure_session_store_loaded(runtime)
        target = server._runtime_sessions_map().get(session_id)
        if target is None:
            raise server.HTTPException(
                status_code=404,
                detail=f"Session not found: {session_id}",
            )
        jobs = [
            job
            for job in server._runtime_fix_jobs_map().values()
            if job.session_id == session_id
        ]
        return target, jobs

    target, jobs_to_cancel = cast(
        tuple[PlotSession, list[FixJob]],
        _run_with_runtime(runtime, _load_delete_context),
    )
    for job in jobs_to_cancel:
        await server._with_runtime_async(
            runtime,
            lambda job=job: server._cancel_fix_job_execution(
                job,
                reason="Workspace deleted",
            ),
        )

    def _delete_session_request() -> dict[str, object]:
        fix_jobs = server._runtime_fix_jobs_map()
        fix_job_tasks = server._runtime_fix_job_tasks_map()
        fix_job_processes = server._runtime_fix_job_processes_map()
        sessions = server._runtime_sessions_map()
        runtime_session_order = (
            server._session_order
            if server._runtime_is_shared(runtime)
            else runtime.store.session_order
        )
        workspace_id = server._session_workspace_id(target)
        active_plot_mode = server._runtime_plot_mode_state_value()
        active_session = server._runtime_active_session_value()

        for job in jobs_to_cancel:
            fix_jobs.pop(job.id, None)
            fix_job_tasks.pop(job.id, None)
            fix_job_processes.pop(job.id, None)

        server._clear_active_fix_job_for_session(session_id)

        session_dir = server._sessions_root_dir() / session_id
        artifacts_root = server._session_artifacts_root(target)
        server.shutil.rmtree(session_dir, ignore_errors=True)
        if artifacts_root != session_dir and server._is_managed_workspace_path(
            artifacts_root
        ):
            server.shutil.rmtree(artifacts_root, ignore_errors=True)
        if active_plot_mode is not None and active_plot_mode.id == workspace_id:
            server._reset_plot_mode_runtime_state()
        server._delete_plot_mode_snapshot(
            state=PlotModeState(
                id=workspace_id,
                workspace_dir=str(
                    server._plot_mode_artifacts_path_for_id(workspace_id)
                ),
            )
        )

        sessions.pop(session_id, None)
        runtime_session_order[:] = [
            sid for sid in runtime_session_order if sid != session_id
        ]

        deleted_active = server._runtime_active_session_id_value() == session_id or (
            active_session is not None and active_session.id == session_id
        )

        if deleted_active:
            if server._runtime_is_shared(runtime):
                server._active_session_id = None
                server._session = None
            else:
                runtime.store.active_session_id = None
                runtime.store.active_session = None

            next_session_id = next(
                (sid for sid in runtime_session_order if sid in sessions),
                None,
            )
            if next_session_id is not None:
                server._set_active_session(next_session_id, clear_plot_mode=True)
                next_active_session = server.get_session()
                server._rebuild_revision_history(next_active_session)
                server._touch_session(next_active_session)
                server._persist_session(next_active_session, promote=True)
                return server._bootstrap_payload(
                    mode="annotation",
                    session=next_active_session,
                    plot_mode=None,
                )

            server._save_session_registry()
            state = (
                server._runtime_plot_mode_state_value()
                or server.init_plot_mode_session(workspace_dir=None)
            )
            return server._bootstrap_payload(mode="plot", session=None, plot_mode=state)

        server._save_session_registry()
        remaining_active_session = server._runtime_active_session_value()
        if remaining_active_session is not None:
            active_session = server.get_session()
            server._rebuild_revision_history(active_session)
            return server._bootstrap_payload(
                mode="annotation",
                session=active_session,
                plot_mode=None,
            )

        state = (
            server._runtime_plot_mode_state_value()
            or server.init_plot_mode_session(workspace_dir=None)
        )
        return server._bootstrap_payload(mode="plot", session=None, plot_mode=state)

    return _run_with_runtime(runtime, _delete_session_request)


async def teardown_runtime(runtime: "BackendRuntime") -> None:
    from .. import server

    with server._runtime_context(runtime):
        fix_job_processes = server._runtime_fix_job_processes_map()
        fix_job_tasks = server._runtime_fix_job_tasks_map()
        fix_jobs = server._runtime_fix_jobs_map()
        active_fix_jobs = server._runtime_active_fix_jobs_map()
        port_file_path = runtime.infra.port_file_path

        if runtime.infra.owns_port_file and port_file_path is not None:
            port_file_path.unlink(missing_ok=True)

        for process in list(fix_job_processes.values()):
            await server._terminate_fix_process(process)
        for task in list(fix_job_tasks.values()):
            task.cancel()

        fix_job_processes.clear()
        fix_job_tasks.clear()
        fix_jobs.clear()
        active_fix_jobs.clear()
        runtime.infra.ws_clients.clear()

        if server._runtime_is_shared(runtime):
            server._clear_shared_shutdown_runtime_state()
        else:
            runtime.store.sessions.clear()
            runtime.store.session_order.clear()
            runtime.store.active_session_id = None
            runtime.store.active_workspace_id = None
            runtime.store.active_session = None
            runtime.store.plot_mode = None
            runtime.store.loaded_session_store_root = None

        runtime.infra.owns_port_file = False
