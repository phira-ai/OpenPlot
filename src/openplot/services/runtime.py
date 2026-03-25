"""Backend runtime containers and shared runtime helpers."""

from __future__ import annotations

import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..models import FixJob, OpencodeModelOption, PlotModeState, PlotSession

if TYPE_CHECKING:
    import asyncio

    from fastapi import WebSocket


@dataclass(slots=True)
class RuntimeStore:
    sessions: dict[str, PlotSession] = field(default_factory=dict)
    session_order: list[str] = field(default_factory=list)
    active_session_id: str | None = None
    active_workspace_id: str | None = None
    active_session: PlotSession | None = None
    plot_mode: PlotModeState | None = None
    workspace_dir: Path = field(default_factory=Path.cwd)
    fix_jobs: dict[str, FixJob] = field(default_factory=dict)
    active_fix_job_ids_by_session: dict[str, str] = field(default_factory=dict)
    loaded_session_store_root: Path | None = None


@dataclass(slots=True)
class RuntimeInfra:
    ws_clients: set[WebSocket] = field(default_factory=set)
    fix_job_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    fix_job_processes: dict[str, asyncio.subprocess.Process] = field(
        default_factory=dict
    )
    runner_install_jobs: dict[str, dict[str, object]] = field(default_factory=dict)
    runner_install_lock: threading.Lock = field(default_factory=threading.Lock)
    active_runner_install_job_id: str | None = None
    update_status_cache: dict[str, object] | None = None
    update_status_cache_expires_at: float = 0.0
    opencode_models_cache: list[OpencodeModelOption] | None = None
    opencode_models_cache_expires_at: float = 0.0
    codex_models_cache: list[OpencodeModelOption] | None = None
    codex_models_cache_expires_at: float = 0.0
    claude_models_cache: list[OpencodeModelOption] | None = None
    claude_models_cache_expires_at: float = 0.0
    port_file_path: Path | None = None
    owns_port_file: bool = False
    lifecycle_owner_token: str | None = None


@dataclass(slots=True)
class BackendRuntime:
    store: RuntimeStore = field(default_factory=RuntimeStore)
    infra: RuntimeInfra = field(default_factory=RuntimeInfra)
    state_root: Path | None = None


_SHARED_RUNTIME: BackendRuntime | None = None


def get_shared_runtime() -> BackendRuntime:
    global _SHARED_RUNTIME
    if _SHARED_RUNTIME is None:
        _SHARED_RUNTIME = BackendRuntime()
        _SHARED_RUNTIME.infra.port_file_path = Path.home() / ".openplot" / "port"
    return _SHARED_RUNTIME


def build_test_runtime(*, store_root: Path | None = None) -> BackendRuntime:
    state_root = store_root.resolve() if store_root is not None else None
    if state_root is None:
        state_root = Path(tempfile.mkdtemp(prefix="openplot-runtime-"))
    return BackendRuntime(
        state_root=state_root,
        infra=RuntimeInfra(port_file_path=None),
    )


def set_runtime_workspace_dir(runtime: BackendRuntime, path: Path) -> Path:
    runtime.store.workspace_dir = Path(path).resolve()
    return runtime.store.workspace_dir


def write_runtime_port_file(runtime: BackendRuntime, port: int) -> None:
    port_file_path = runtime.infra.port_file_path
    if port_file_path is None:
        return
    port_file_path.parent.mkdir(parents=True, exist_ok=True)
    port_file_path.write_text(str(port), encoding="utf-8")
    runtime.infra.owns_port_file = True


def build_update_status_payload(
    runtime: BackendRuntime,
    *,
    allow_network: bool,
    force_refresh: bool = False,
) -> dict[str, object]:
    from .. import server

    return server._with_runtime(
        runtime,
        lambda: server._build_update_status_payload_impl(
            force_refresh=force_refresh,
            allow_network=allow_network,
        ),
    )


def claim_runtime_lifecycle(runtime: BackendRuntime, owner_token: str) -> None:
    current_owner = runtime.infra.lifecycle_owner_token
    if current_owner is None:
        runtime.infra.lifecycle_owner_token = owner_token
        return
    if current_owner != owner_token:
        raise RuntimeError("Backend runtime is already active in another app lifecycle")


def release_runtime_lifecycle(runtime: BackendRuntime, owner_token: str) -> None:
    if runtime.infra.lifecycle_owner_token == owner_token:
        runtime.infra.lifecycle_owner_token = None
