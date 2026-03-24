from __future__ import annotations

from pathlib import Path

import pytest

import openplot.server as server


@pytest.fixture(autouse=True)
def backend_runtime_reset():
    shared_runtime = server.get_shared_runtime()
    prev_session = server._session
    prev_sessions = dict(server._sessions)
    prev_session_order = list(server._session_order)
    prev_active_session_id = server._active_session_id
    prev_plot_mode = server._plot_mode
    prev_workspace = server._workspace_dir
    prev_loaded_store_root = server._loaded_session_store_root
    prev_fix_jobs = dict(server._fix_jobs)
    prev_fix_job_tasks = dict(server._fix_job_tasks)
    prev_fix_job_processes = dict(server._fix_job_processes)
    prev_active_fix_jobs_by_session = dict(server._active_fix_job_ids_by_session)
    prev_bound_runtime = server._bound_runtime
    prev_runtime_state_root_override = server._runtime_state_root_override
    prev_current_runtime = server._current_runtime_var.get()
    prev_shared_store = {
        "sessions": dict(shared_runtime.store.sessions),
        "session_order": list(shared_runtime.store.session_order),
        "active_session_id": shared_runtime.store.active_session_id,
        "active_workspace_id": shared_runtime.store.active_workspace_id,
        "active_session": shared_runtime.store.active_session,
        "plot_mode": shared_runtime.store.plot_mode,
        "workspace_dir": shared_runtime.store.workspace_dir,
        "fix_jobs": dict(shared_runtime.store.fix_jobs),
        "active_fix_job_ids_by_session": dict(
            shared_runtime.store.active_fix_job_ids_by_session
        ),
        "loaded_session_store_root": shared_runtime.store.loaded_session_store_root,
    }
    prev_shared_infra = {
        "ws_clients": set(shared_runtime.infra.ws_clients),
        "fix_job_tasks": dict(shared_runtime.infra.fix_job_tasks),
        "fix_job_processes": dict(shared_runtime.infra.fix_job_processes),
        "runner_install_jobs": dict(shared_runtime.infra.runner_install_jobs),
        "active_runner_install_job_id": shared_runtime.infra.active_runner_install_job_id,
        "update_status_cache": shared_runtime.infra.update_status_cache,
        "update_status_cache_expires_at": shared_runtime.infra.update_status_cache_expires_at,
        "opencode_models_cache": shared_runtime.infra.opencode_models_cache,
        "opencode_models_cache_expires_at": shared_runtime.infra.opencode_models_cache_expires_at,
        "codex_models_cache": shared_runtime.infra.codex_models_cache,
        "codex_models_cache_expires_at": shared_runtime.infra.codex_models_cache_expires_at,
        "claude_models_cache": shared_runtime.infra.claude_models_cache,
        "claude_models_cache_expires_at": shared_runtime.infra.claude_models_cache_expires_at,
        "port_file_path": shared_runtime.infra.port_file_path,
        "owns_port_file": shared_runtime.infra.owns_port_file,
        "lifecycle_owner_token": shared_runtime.infra.lifecycle_owner_token,
    }

    server._session = None
    server._sessions.clear()
    server._session_order.clear()
    server._active_session_id = None
    server._plot_mode = None
    server._workspace_dir = Path.cwd()
    server._loaded_session_store_root = None
    server._fix_jobs.clear()
    server._fix_job_tasks.clear()
    server._fix_job_processes.clear()
    server._active_fix_job_ids_by_session.clear()
    server._bound_runtime = None
    server._runtime_state_root_override = None
    server._current_runtime_var.set(None)
    shared_runtime.store.sessions.clear()
    shared_runtime.store.session_order.clear()
    shared_runtime.store.active_session_id = None
    shared_runtime.store.active_workspace_id = None
    shared_runtime.store.active_session = None
    shared_runtime.store.plot_mode = None
    shared_runtime.store.workspace_dir = Path.cwd()
    shared_runtime.store.fix_jobs.clear()
    shared_runtime.store.active_fix_job_ids_by_session.clear()
    shared_runtime.store.loaded_session_store_root = None
    shared_runtime.infra.ws_clients.clear()
    shared_runtime.infra.fix_job_tasks.clear()
    shared_runtime.infra.fix_job_processes.clear()
    shared_runtime.infra.runner_install_jobs.clear()
    shared_runtime.infra.active_runner_install_job_id = None
    shared_runtime.infra.update_status_cache = None
    shared_runtime.infra.update_status_cache_expires_at = 0.0
    shared_runtime.infra.opencode_models_cache = None
    shared_runtime.infra.opencode_models_cache_expires_at = 0.0
    shared_runtime.infra.codex_models_cache = None
    shared_runtime.infra.codex_models_cache_expires_at = 0.0
    shared_runtime.infra.claude_models_cache = None
    shared_runtime.infra.claude_models_cache_expires_at = 0.0
    shared_runtime.infra.port_file_path = None
    shared_runtime.infra.owns_port_file = False
    shared_runtime.infra.lifecycle_owner_token = None

    try:
        yield
    finally:
        server._session = prev_session
        server._sessions.clear()
        server._sessions.update(prev_sessions)
        server._session_order.clear()
        server._session_order.extend(prev_session_order)
        server._active_session_id = prev_active_session_id
        server._plot_mode = prev_plot_mode
        server._workspace_dir = prev_workspace
        server._loaded_session_store_root = prev_loaded_store_root
        server._fix_jobs.clear()
        server._fix_jobs.update(prev_fix_jobs)
        server._fix_job_tasks.clear()
        server._fix_job_tasks.update(prev_fix_job_tasks)
        server._fix_job_processes.clear()
        server._fix_job_processes.update(prev_fix_job_processes)
        server._active_fix_job_ids_by_session.clear()
        server._active_fix_job_ids_by_session.update(prev_active_fix_jobs_by_session)
        server._bound_runtime = prev_bound_runtime
        server._runtime_state_root_override = prev_runtime_state_root_override
        server._current_runtime_var.set(prev_current_runtime)
        shared_runtime.store.sessions.clear()
        shared_runtime.store.sessions.update(prev_shared_store["sessions"])
        shared_runtime.store.session_order.clear()
        shared_runtime.store.session_order.extend(prev_shared_store["session_order"])
        shared_runtime.store.active_session_id = prev_shared_store["active_session_id"]
        shared_runtime.store.active_workspace_id = prev_shared_store[
            "active_workspace_id"
        ]
        shared_runtime.store.active_session = prev_shared_store["active_session"]
        shared_runtime.store.plot_mode = prev_shared_store["plot_mode"]
        shared_runtime.store.workspace_dir = prev_shared_store["workspace_dir"]
        shared_runtime.store.fix_jobs.clear()
        shared_runtime.store.fix_jobs.update(prev_shared_store["fix_jobs"])
        shared_runtime.store.active_fix_job_ids_by_session.clear()
        shared_runtime.store.active_fix_job_ids_by_session.update(
            prev_shared_store["active_fix_job_ids_by_session"]
        )
        shared_runtime.store.loaded_session_store_root = prev_shared_store[
            "loaded_session_store_root"
        ]
        shared_runtime.infra.ws_clients.clear()
        shared_runtime.infra.ws_clients.update(prev_shared_infra["ws_clients"])
        shared_runtime.infra.fix_job_tasks.clear()
        shared_runtime.infra.fix_job_tasks.update(prev_shared_infra["fix_job_tasks"])
        shared_runtime.infra.fix_job_processes.clear()
        shared_runtime.infra.fix_job_processes.update(
            prev_shared_infra["fix_job_processes"]
        )
        shared_runtime.infra.runner_install_jobs.clear()
        shared_runtime.infra.runner_install_jobs.update(
            prev_shared_infra["runner_install_jobs"]
        )
        shared_runtime.infra.active_runner_install_job_id = prev_shared_infra[
            "active_runner_install_job_id"
        ]
        shared_runtime.infra.update_status_cache = prev_shared_infra[
            "update_status_cache"
        ]
        shared_runtime.infra.update_status_cache_expires_at = prev_shared_infra[
            "update_status_cache_expires_at"
        ]
        shared_runtime.infra.opencode_models_cache = prev_shared_infra[
            "opencode_models_cache"
        ]
        shared_runtime.infra.opencode_models_cache_expires_at = prev_shared_infra[
            "opencode_models_cache_expires_at"
        ]
        shared_runtime.infra.codex_models_cache = prev_shared_infra[
            "codex_models_cache"
        ]
        shared_runtime.infra.codex_models_cache_expires_at = prev_shared_infra[
            "codex_models_cache_expires_at"
        ]
        shared_runtime.infra.claude_models_cache = prev_shared_infra[
            "claude_models_cache"
        ]
        shared_runtime.infra.claude_models_cache_expires_at = prev_shared_infra[
            "claude_models_cache_expires_at"
        ]
        shared_runtime.infra.port_file_path = prev_shared_infra["port_file_path"]
        shared_runtime.infra.owns_port_file = prev_shared_infra["owns_port_file"]
        shared_runtime.infra.lifecycle_owner_token = prev_shared_infra[
            "lifecycle_owner_token"
        ]
