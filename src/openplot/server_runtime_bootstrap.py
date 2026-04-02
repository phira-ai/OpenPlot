"""Runtime/bootstrap helpers extracted from openplot.server."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import ModuleType


def _runtime_is_shared(server_module: ModuleType, runtime) -> bool:
    return runtime is server_module.get_shared_runtime()


def _runtime_context(server_module: ModuleType, runtime):
    @contextmanager
    def _manager():
        token = server_module._current_runtime_var.set(runtime)
        try:
            yield
        finally:
            server_module._current_runtime_var.reset(token)

    return _manager()


def _current_runtime(server_module: ModuleType):
    return (
        server_module._current_runtime_var.get()
        or server_module._bound_runtime
        or server_module.get_shared_runtime()
    )


def _runtime_sessions_map(server_module: ModuleType):
    runtime = server_module._current_runtime()
    return (
        server_module._sessions
        if server_module._runtime_is_shared(runtime)
        else runtime.store.sessions
    )


def _runtime_fix_jobs_map(server_module: ModuleType):
    runtime = server_module._current_runtime()
    return (
        server_module._fix_jobs
        if server_module._runtime_is_shared(runtime)
        else runtime.store.fix_jobs
    )


def _runtime_fix_job_tasks_map(server_module: ModuleType):
    runtime = server_module._current_runtime()
    return (
        server_module._fix_job_tasks
        if server_module._runtime_is_shared(runtime)
        else runtime.infra.fix_job_tasks
    )


def _runtime_fix_job_processes_map(server_module: ModuleType):
    runtime = server_module._current_runtime()
    return (
        server_module._fix_job_processes
        if server_module._runtime_is_shared(runtime)
        else runtime.infra.fix_job_processes
    )


def _runtime_active_fix_jobs_map(server_module: ModuleType):
    runtime = server_module._current_runtime()
    return (
        server_module._active_fix_job_ids_by_session
        if server_module._runtime_is_shared(runtime)
        else runtime.store.active_fix_job_ids_by_session
    )


def _runtime_workspace_dir(server_module: ModuleType):
    runtime = server_module._current_runtime()
    return (
        server_module._workspace_dir
        if server_module._runtime_is_shared(runtime)
        else runtime.store.workspace_dir
    )


def _runtime_ws_clients(server_module: ModuleType):
    runtime = server_module._current_runtime()
    return (
        server_module._ws_clients
        if server_module._runtime_is_shared(runtime)
        else runtime.infra.ws_clients
    )


def _runtime_plot_mode_state_value(server_module: ModuleType):
    runtime = server_module._current_runtime()
    return (
        server_module._plot_mode
        if server_module._runtime_is_shared(runtime)
        else runtime.store.plot_mode
    )


def _runtime_active_session_value(server_module: ModuleType):
    runtime = server_module._current_runtime()
    return (
        server_module._session
        if server_module._runtime_is_shared(runtime)
        else runtime.store.active_session
    )


def _runtime_active_session_id_value(server_module: ModuleType):
    runtime = server_module._current_runtime()
    return (
        server_module._active_session_id
        if server_module._runtime_is_shared(runtime)
        else runtime.store.active_session_id
    )


def _path_from_override_env(server_module: ModuleType, env_name: str) -> Path | None:
    value = os.getenv(env_name, "").strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()


def _default_data_root(server_module: ModuleType) -> Path:
    del server_module
    xdg_data_home = os.getenv("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return Path(xdg_data_home).expanduser().resolve() / "openplot"
    return Path.home() / ".local" / "share" / "openplot"


def _default_state_root(server_module: ModuleType) -> Path:
    del server_module
    xdg_state_home = os.getenv("XDG_STATE_HOME", "").strip()
    if xdg_state_home:
        return Path(xdg_state_home).expanduser().resolve() / "openplot"
    return Path.home() / ".local" / "state" / "openplot"


def _state_root(server_module: ModuleType) -> Path:
    runtime = server_module._current_runtime_var.get()
    if runtime is not None and runtime.state_root is not None:
        return runtime.state_root
    if server_module._runtime_state_root_override is not None:
        return server_module._runtime_state_root_override
    return (
        server_module._path_from_override_env("OPENPLOT_STATE_DIR")
        or server_module._default_state_root()
    )


def _sync_runtime_from_globals(server_module: ModuleType, runtime) -> None:
    runtime.store.sessions = server_module._sessions
    runtime.store.session_order = server_module._session_order
    runtime.store.active_session_id = server_module._active_session_id
    runtime.store.active_workspace_id = server_module._active_workspace_id()
    runtime.store.active_session = server_module._session
    runtime.store.plot_mode = server_module._plot_mode
    runtime.store.workspace_dir = server_module._workspace_dir
    runtime.store.fix_jobs = server_module._fix_jobs
    runtime.store.active_fix_job_ids_by_session = (
        server_module._active_fix_job_ids_by_session
    )
    runtime.store.loaded_session_store_root = server_module._loaded_session_store_root

    runtime.infra.ws_clients = server_module._ws_clients
    runtime.infra.fix_job_tasks = server_module._fix_job_tasks
    runtime.infra.fix_job_processes = server_module._fix_job_processes
    runtime.infra.runner_install_jobs = server_module._runner_install_jobs
    runtime.infra.active_runner_install_job_id = (
        server_module._active_runner_install_job_id
    )
    runtime.infra.update_status_cache = server_module._update_status_cache
    runtime.infra.update_status_cache_expires_at = (
        server_module._update_status_cache_expires_at
    )
    runtime.infra.opencode_models_cache = server_module._opencode_models_cache
    runtime.infra.opencode_models_cache_expires_at = (
        server_module._opencode_models_cache_expires_at
    )
    runtime.infra.codex_models_cache = server_module._codex_models_cache
    runtime.infra.codex_models_cache_expires_at = (
        server_module._codex_models_cache_expires_at
    )
    runtime.infra.claude_models_cache = server_module._claude_models_cache
    runtime.infra.claude_models_cache_expires_at = (
        server_module._claude_models_cache_expires_at
    )
    if runtime.infra.port_file_path is None or server_module._runtime_is_shared(
        runtime
    ):
        runtime.infra.port_file_path = server_module._port_file


def _sync_globals_from_runtime(server_module: ModuleType, runtime) -> None:
    server_module._sessions = runtime.store.sessions
    server_module._session_order = runtime.store.session_order
    server_module._active_session_id = runtime.store.active_session_id
    server_module._session = runtime.store.active_session
    server_module._plot_mode = runtime.store.plot_mode
    server_module._workspace_dir = runtime.store.workspace_dir
    server_module._fix_jobs = runtime.store.fix_jobs
    server_module._fix_job_tasks = runtime.infra.fix_job_tasks
    server_module._fix_job_processes = runtime.infra.fix_job_processes
    server_module._active_fix_job_ids_by_session = (
        runtime.store.active_fix_job_ids_by_session
    )
    server_module._loaded_session_store_root = runtime.store.loaded_session_store_root
    server_module._ws_clients = runtime.infra.ws_clients
    server_module._runner_install_jobs = runtime.infra.runner_install_jobs
    server_module._active_runner_install_job_id = (
        runtime.infra.active_runner_install_job_id
    )
    server_module._opencode_models_cache = runtime.infra.opencode_models_cache
    server_module._opencode_models_cache_expires_at = (
        runtime.infra.opencode_models_cache_expires_at
    )
    server_module._codex_models_cache = runtime.infra.codex_models_cache
    server_module._codex_models_cache_expires_at = (
        runtime.infra.codex_models_cache_expires_at
    )
    server_module._claude_models_cache = runtime.infra.claude_models_cache
    server_module._claude_models_cache_expires_at = (
        runtime.infra.claude_models_cache_expires_at
    )
    server_module._update_status_cache = runtime.infra.update_status_cache
    server_module._update_status_cache_expires_at = (
        runtime.infra.update_status_cache_expires_at
    )
    if runtime.infra.port_file_path is not None:
        server_module._port_file = runtime.infra.port_file_path
    server_module._runtime_state_root_override = (
        runtime.state_root if not server_module._runtime_is_shared(runtime) else None
    )


def _runtime_snapshot(server_module: ModuleType) -> dict[str, object]:
    return {
        "bound_runtime": server_module._bound_runtime,
        "sessions": server_module._sessions,
        "session_order": server_module._session_order,
        "active_session_id": server_module._active_session_id,
        "session": server_module._session,
        "plot_mode": server_module._plot_mode,
        "workspace_dir": server_module._workspace_dir,
        "fix_jobs": server_module._fix_jobs,
        "fix_job_tasks": server_module._fix_job_tasks,
        "fix_job_processes": server_module._fix_job_processes,
        "active_fix_job_ids_by_session": server_module._active_fix_job_ids_by_session,
        "loaded_session_store_root": server_module._loaded_session_store_root,
        "ws_clients": server_module._ws_clients,
        "runner_install_jobs": server_module._runner_install_jobs,
        "active_runner_install_job_id": server_module._active_runner_install_job_id,
        "opencode_models_cache": server_module._opencode_models_cache,
        "opencode_models_cache_expires_at": server_module._opencode_models_cache_expires_at,
        "codex_models_cache": server_module._codex_models_cache,
        "codex_models_cache_expires_at": server_module._codex_models_cache_expires_at,
        "claude_models_cache": server_module._claude_models_cache,
        "claude_models_cache_expires_at": server_module._claude_models_cache_expires_at,
        "update_status_cache": server_module._update_status_cache,
        "update_status_cache_expires_at": server_module._update_status_cache_expires_at,
        "port_file": server_module._port_file,
        "runtime_state_root_override": server_module._runtime_state_root_override,
    }


def _restore_runtime_snapshot(
    server_module: ModuleType, snapshot: dict[str, object]
) -> None:
    server_module._bound_runtime = snapshot["bound_runtime"]
    server_module._sessions = snapshot["sessions"]
    server_module._session_order = snapshot["session_order"]
    server_module._active_session_id = snapshot["active_session_id"]
    server_module._session = snapshot["session"]
    server_module._plot_mode = snapshot["plot_mode"]
    server_module._workspace_dir = snapshot["workspace_dir"]
    server_module._fix_jobs = snapshot["fix_jobs"]
    server_module._fix_job_tasks = snapshot["fix_job_tasks"]
    server_module._fix_job_processes = snapshot["fix_job_processes"]
    server_module._active_fix_job_ids_by_session = snapshot[
        "active_fix_job_ids_by_session"
    ]
    server_module._loaded_session_store_root = snapshot["loaded_session_store_root"]
    server_module._ws_clients = snapshot["ws_clients"]
    server_module._runner_install_jobs = snapshot["runner_install_jobs"]
    server_module._active_runner_install_job_id = snapshot[
        "active_runner_install_job_id"
    ]
    server_module._opencode_models_cache = snapshot["opencode_models_cache"]
    server_module._opencode_models_cache_expires_at = snapshot[
        "opencode_models_cache_expires_at"
    ]
    server_module._codex_models_cache = snapshot["codex_models_cache"]
    server_module._codex_models_cache_expires_at = snapshot[
        "codex_models_cache_expires_at"
    ]
    server_module._claude_models_cache = snapshot["claude_models_cache"]
    server_module._claude_models_cache_expires_at = snapshot[
        "claude_models_cache_expires_at"
    ]
    server_module._update_status_cache = snapshot["update_status_cache"]
    server_module._update_status_cache_expires_at = snapshot[
        "update_status_cache_expires_at"
    ]
    server_module._port_file = snapshot["port_file"]
    server_module._runtime_state_root_override = snapshot["runtime_state_root_override"]


def _activate_runtime(server_module: ModuleType, runtime):
    @contextmanager
    def _manager():
        snapshot = server_module._runtime_snapshot()
        server_module._bound_runtime = runtime
        server_module._sync_globals_from_runtime(runtime)
        try:
            yield
        finally:
            runtime.store.active_workspace_id = server_module._active_workspace_id()
            runtime.store.active_fix_job_ids_by_session = dict(
                server_module._active_fix_job_ids_by_session
            )
            server_module._sync_runtime_from_globals(runtime)
            if server_module._runtime_is_shared(runtime):
                server_module._sync_globals_from_runtime(runtime)
            else:
                server_module._restore_runtime_snapshot(snapshot)

    return _manager()


def _with_runtime(server_module: ModuleType, runtime, callback):
    if server_module._runtime_is_shared(runtime):
        server_module._sync_runtime_from_globals(runtime)
    with server_module._activate_runtime(runtime):
        return callback()


async def _with_runtime_async(server_module: ModuleType, runtime, awaitable_factory):
    with server_module._runtime_context(runtime):
        return await awaitable_factory()


def _clear_shared_shutdown_runtime_state(server_module: ModuleType) -> None:
    server_module._reset_plot_mode_runtime_state()
    server_module._session = None
    server_module._active_session_id = None
    server_module._sessions.clear()
    server_module._session_order.clear()
    server_module._loaded_session_store_root = None


def _ensure_session_store_loaded_impl(
    server_module: ModuleType, *, force_reload: bool = False
) -> None:
    if (
        not force_reload
        and server_module._bound_runtime is not None
        and not server_module._runtime_is_shared(server_module._bound_runtime)
        and (
            server_module._sessions
            or server_module._plot_mode is not None
            or server_module._active_session_id is not None
            or server_module._loaded_session_store_root is not None
        )
    ):
        return

    sessions_root = server_module._sessions_root_dir().resolve()
    if (
        not force_reload
        and server_module._loaded_session_store_root is not None
        and server_module._loaded_session_store_root == sessions_root
    ):
        return

    loaded_sessions = {}
    for snapshot_path in sorted(
        sessions_root.glob(f"*/{server_module._session_snapshot_file_name}")
    ):
        session_id = snapshot_path.parent.name
        session = server_module._load_session_snapshot(session_id)
        if session is None:
            continue
        loaded_sessions[session.id] = session

    registry_path = server_module._sessions_registry_path()
    order_from_registry: list[str] = []
    active_session_id: str | None = None
    if registry_path.exists():
        try:
            raw_registry = server_module.json.loads(
                server_module._read_file_text(registry_path)
            )
        except (OSError, server_module.json.JSONDecodeError):
            raw_registry = {}
        if isinstance(raw_registry, dict):
            raw_order = raw_registry.get("order")
            if isinstance(raw_order, list):
                for item in raw_order:
                    if not isinstance(item, str):
                        continue
                    if item in loaded_sessions and item not in order_from_registry:
                        order_from_registry.append(item)
            raw_active = raw_registry.get("active_session_id")
            if isinstance(raw_active, str) and raw_active in loaded_sessions:
                active_session_id = raw_active

    remaining = [
        session_id
        for session_id in loaded_sessions
        if session_id not in order_from_registry
    ]
    remaining.sort(
        key=lambda sid: server_module._session_sort_key(loaded_sessions[sid]),
        reverse=True,
    )

    server_module._sessions = loaded_sessions
    server_module._session_order = [*order_from_registry, *remaining]
    server_module._active_session_id = active_session_id
    server_module._session = (
        server_module._sessions.get(server_module._active_session_id)
        if server_module._active_session_id
        else None
    )
    server_module._plot_mode = server_module._load_plot_mode_snapshot()

    if server_module._session is not None:
        server_module.set_workspace_dir(
            server_module._workspace_for_session(server_module._session)
        )
    elif server_module._plot_mode is not None:
        server_module.set_workspace_dir(
            server_module.Path(server_module._plot_mode.workspace_dir)
        )

    server_module._loaded_session_store_root = sessions_root


def get_session(server_module: ModuleType):
    runtime = server_module._current_runtime()
    if server_module._runtime_is_shared(runtime):
        server_module._ensure_session_store_loaded()
        if server_module._session is None and server_module._active_session_id:
            server_module._session = server_module._sessions.get(
                server_module._active_session_id
            )
        session = server_module._session
    else:
        server_module._ensure_session_store_loaded()
        session = runtime.store.active_session
        if session is None and runtime.store.active_session_id:
            session = runtime.store.sessions.get(runtime.store.active_session_id)
            runtime.store.active_session = session

    if session is None:
        raise server_module.HTTPException(status_code=404, detail="No active session")
    server_module._ensure_workspace_name(session)
    return session


def _get_session_by_id(server_module: ModuleType, session_id: str):
    server_module._ensure_session_store_loaded()

    normalized_session_id = session_id.strip()
    if not normalized_session_id:
        raise server_module.HTTPException(status_code=400, detail="Missing session_id")

    session = server_module._runtime_sessions_map().get(normalized_session_id)
    if session is None:
        raise server_module.HTTPException(
            status_code=404,
            detail=f"Session not found: {normalized_session_id}",
        )

    server_module._ensure_workspace_name(session)
    return session


def _resolve_request_session(server_module: ModuleType, session_id: str | None):
    if session_id is None:
        return server_module.get_session()

    normalized = session_id.strip()
    if not normalized:
        return server_module.get_session()
    return server_module._get_session_by_id(normalized)


def _resolve_python_executable(server_module: ModuleType, session=None) -> str:
    state = server_module._resolve_python_interpreter_state(session)
    resolved_path = state.get("resolved_path")
    if isinstance(resolved_path, str) and resolved_path:
        try:
            if (
                server_module.Path(resolved_path).resolve()
                == server_module.Path(server_module.sys.executable).resolve()
            ):
                return server_module.sys.executable
        except OSError:
            pass
        return resolved_path
    return server_module.sys.executable


def _resolve_static_dir(server_module: ModuleType):
    pkg_static = server_module.Path(server_module.__file__).parent / "static"
    if pkg_static.is_dir() and (pkg_static / "index.html").exists():
        return pkg_static
    dev_static = (
        server_module.Path(server_module.__file__).resolve().parent.parent.parent
        / "frontend"
        / "dist"
    )
    if dev_static.is_dir() and (dev_static / "index.html").exists():
        return dev_static
    return pkg_static


def _lifespan(server_module: ModuleType, app):
    @asynccontextmanager
    async def _manager():
        runtime = app.state.runtime
        owner_token = server_module.uuid.uuid4().hex

        startup_complete = False
        try:
            server_module.claim_runtime_lifecycle(runtime, owner_token)
            should_reload_from_disk = (
                server_module.session_services.should_restore_session_store(runtime)
            )
            if should_reload_from_disk:
                if server_module._runtime_is_shared(runtime):
                    with server_module._runtime_context(runtime):
                        server_module._ensure_session_store_loaded(force_reload=True)
                else:
                    server_module._with_runtime(
                        runtime,
                        lambda: server_module._ensure_session_store_loaded(
                            force_reload=False
                        ),
                    )
                server_module.session_services.restore_latest_workspace_into_runtime(
                    runtime
                )
            startup_complete = True
        except Exception:
            server_module.release_runtime_lifecycle(runtime, owner_token)
            raise

        try:
            yield
        finally:
            if startup_complete:
                await server_module.session_services.teardown_runtime(runtime)
            server_module.release_runtime_lifecycle(runtime, owner_token)

    return _manager()


def create_app(server_module: ModuleType, runtime=None):
    resolved_runtime = (
        runtime or server_module._bound_runtime or server_module.get_shared_runtime()
    )
    if server_module._runtime_is_shared(resolved_runtime):
        server_module._sync_runtime_from_globals(resolved_runtime)

    app = server_module.FastAPI(
        title="OpenPlot",
        version=server_module.__version__,
        lifespan=server_module._lifespan,
    )
    app.state.runtime = resolved_runtime

    app.add_middleware(
        server_module.CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def bind_runtime(request, call_next):
        with server_module._runtime_context(request.app.state.runtime):
            return await call_next(request)

    server_module._register_routes(app)

    static_dir = server_module._resolve_static_dir()
    if static_dir.is_dir() and (static_dir / "assets").is_dir():
        app.mount(
            "/assets",
            server_module.StaticFiles(directory=str(static_dir / "assets")),
            name="assets",
        )

    return app


def init_session_from_script(
    server_module: ModuleType,
    script_path,
    *,
    inherit_id: str | None = None,
    inherit_workspace_id: str | None = None,
    inherit_workspace_name: str | None = None,
    inherit_runner_session_ids: dict[str, str] | None = None,
    inherit_artifacts_root: str | None = None,
    runtime=None,
):
    resolved_runtime = runtime or server_module.get_shared_runtime()

    def _run():
        server_module._ensure_session_store_loaded()

        resolved_script_path = server_module.Path(script_path).resolve()
        script_content = server_module._read_file_text(resolved_script_path)
        server_module.set_runtime_workspace_dir(
            resolved_runtime, resolved_script_path.parent
        )
        server_module._workspace_dir = resolved_runtime.store.workspace_dir

        session_kwargs: dict[str, object] = {
            "source_script": script_content,
            "source_script_path": str(resolved_script_path),
        }
        if inherit_id:
            session_kwargs["id"] = inherit_id
        if inherit_workspace_id:
            session_kwargs["workspace_id"] = inherit_workspace_id
        if inherit_workspace_name:
            session_kwargs["workspace_name"] = inherit_workspace_name
        if inherit_runner_session_ids:
            session_kwargs["runner_session_ids"] = inherit_runner_session_ids
        if inherit_artifacts_root:
            session_kwargs["artifacts_root"] = inherit_artifacts_root

        session = server_module.PlotSession(**session_kwargs)
        server_module._session_workspace_id(session)
        server_module._ensure_workspace_name(session)

        run_output_dir = server_module._new_run_output_dir(session)
        result = server_module.execute_script(
            resolved_script_path,
            capture_dir=run_output_dir,
            python_executable=server_module._resolve_python_executable(session),
        )

        session.current_plot = result.plot_path or ""
        session.plot_type = result.plot_type or "svg"

        if result.success and result.plot_path:
            server_module._clear_plot_mode_state()
            server_module._session = session
            server_module._init_version_graph(
                session,
                script=script_content,
                plot_path=result.plot_path,
                plot_type=result.plot_type or "svg",
            )
            server_module._touch_session(session)
            server_module._persist_session(session, promote=True)
            server_module._set_active_session(session.id, clear_plot_mode=False)
        else:
            server_module._session = None

        return result

    if server_module._bound_runtime is resolved_runtime:
        result = _run()
        if not server_module._runtime_is_shared(resolved_runtime):
            server_module._sync_runtime_from_globals(resolved_runtime)
        return result
    return server_module._with_runtime(resolved_runtime, _run)
