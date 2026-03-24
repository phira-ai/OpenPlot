"""FastAPI backend — REST endpoints, WebSocket, and static file serving."""

from __future__ import annotations

import ast
import asyncio
import json
import locale
import os
import platform
import pkgutil
import re
import signal
import shlex
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from contextvars import ContextVar, Token
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Mapping, cast
from urllib import error as urllib_error
from urllib import request as urllib_request

import pandas as pd
from openpyxl import load_workbook
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.schemas import (
    AnnotationUpdateRequest,
    CheckoutVersionRequest,
    OpenExternalUrlRequest,
    PlotModeChatRequest,
    PlotModeFinalizeRequest,
    PlotModeQuestionAnswerRequest,
    PlotModePathSuggestionsRequest,
    PlotModeSelectPathsRequest,
    PlotModeSettingsRequest,
    PlotModeTabularHintRequest,
    PreferencesRequest,
    PythonInterpreterRequest,
    RenameBranchRequest,
    RenameSessionRequest,
    RunnerAuthLaunchRequest,
    RunnerInstallRequest,
    StartFixJobRequest,
    SubmitScriptRequest,
)
from .domain.annotations import pending_annotations_for_context
from .executor import ExecutionResult, execute_script
from .models import (
    Annotation,
    AnnotationStatus,
    Branch,
    FixJob,
    FixRunner,
    FixJobStatus,
    FixJobStep,
    FixStepStatus,
    OpencodeModelOption,
    PlotModeChatMessage,
    PlotModeDataRegion,
    PlotModeDataProfile,
    PlotModeExecutionMode,
    PlotModeFile,
    PlotModeInputBundle,
    PlotModeMessageKind,
    PlotModeMessageMetadata,
    PlotModePhase,
    PlotModeQuestionItem,
    PlotModeQuestionOption,
    PlotModeQuestionSet,
    PlotModeResolvedDataSource,
    PlotModeSheetBounds,
    PlotModeSheetCandidate,
    PlotModeSheetPreview,
    PlotModeState,
    PlotModeTabularSelectionRegion,
    PlotModeTabularSelector,
    PlotSession,
    Revision,
    VersionNode,
)
from .services.runtime import (
    BackendRuntime,
    build_update_status_payload,
    claim_runtime_lifecycle,
    get_shared_runtime,
    release_runtime_lifecycle,
    set_runtime_workspace_dir,
    write_runtime_port_file,
)
from .services import runners as runner_services
from .services import sessions as session_services
from .services import annotations as annotation_services
from .services import artifacts as artifact_services
from .services import fix_jobs as fix_job_services
from .services import plot_mode as plot_mode_services
from .services import versioning as versioning_services

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ---------------------------------------------------------------------------
# Encoding helper — always write UTF-8, but tolerate legacy system-encoded
# files (cp1252, GBK, etc.) that may exist from before this fix.
# ---------------------------------------------------------------------------


def _read_file_text(path: Path) -> str:
    """Read a text file with robust encoding detection.

    Tries UTF-8 first (strict). If that fails, falls back to the system
    default encoding (e.g. GBK on Chinese Windows, cp1252 on Western Windows).
    If both fail, reads as UTF-8 with replacement characters so we never crash.
    """
    raw = path.read_bytes()
    # UTF-8 BOM is a strong signal
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # Bytes are not valid UTF-8 — use the system default encoding (GBK, cp1252, etc.)
    fallback = locale.getpreferredencoding(False)
    if fallback and fallback.lower().replace("-", "") != "utf8":
        try:
            return raw.decode(fallback)
        except (UnicodeDecodeError, LookupError):
            pass
    # Last resort — decode as UTF-8 with replacement so we never crash
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Global session state
# ---------------------------------------------------------------------------

_sessions: dict[str, PlotSession] = {}
_session_order: list[str] = []
_active_session_id: str | None = None
_session: PlotSession | None = None
_plot_mode: PlotModeState | None = None
_ws_clients: set[WebSocket] = set()
_port_file: Path = Path.home() / ".openplot" / "port"
_workspace_dir: Path = Path.cwd()
_fix_jobs: dict[str, FixJob] = {}
_fix_job_tasks: dict[str, asyncio.Task[None]] = {}
_fix_job_processes: dict[str, asyncio.subprocess.Process] = {}
_active_fix_job_ids_by_session: dict[str, str] = {}
_opencode_models_cache: list[OpencodeModelOption] | None = None
_opencode_models_cache_expires_at: float = 0.0
_opencode_models_cache_ttl_s: float = 30.0
_codex_models_cache: list[OpencodeModelOption] | None = None
_codex_models_cache_expires_at: float = 0.0
_codex_models_cache_ttl_s: float = 30.0
_claude_models_cache: list[OpencodeModelOption] | None = None
_claude_models_cache_expires_at: float = 0.0
_claude_models_cache_ttl_s: float = 30.0
_update_status_cache: dict[str, object] | None = None
_update_status_cache_expires_at: float = 0.0
_update_status_cache_ttl_s: float = 900.0
_latest_release_api_url = (
    "https://api.github.com/repos/phira-ai/OpenPlot/releases/latest"
)
_latest_release_page_url = "https://github.com/phira-ai/OpenPlot/releases/latest"
_preferences_file_name = "preferences.json"
_python_interpreter_preference_key = "python_interpreter"
_plot_mode_generated_script_name = "openplot_generated.py"
_plot_mode_prompt_files_limit = 24
_plot_mode_autonomous_watchdog_s = 240.0
_plot_mode_autonomous_stall_limit = 2
_plot_mode_execution_retry_limit = 4
_plot_mode_autonomous_focus_directions = (
    "tighten label spacing and padding",
    "improve axis clarity and tick balance",
    "clean up legend placement and redundancy",
    "align colors and visual consistency",
    "balance title hierarchy and typography",
    "smooth margins and overall whitespace",
)
_fix_job_retry_limit = 3
_session_registry_file_name = "registry.json"
_session_snapshot_file_name = "session.json"
_plot_mode_snapshot_file_name = "active.json"
_plot_mode_workspace_snapshot_file_name = "workspace.json"
_loaded_session_store_root: Path | None = None
_runner_install_jobs: dict[str, dict[str, object]] = {}
_runner_install_jobs_lock = threading.Lock()
_active_runner_install_job_id: str | None = None
_default_fix_runner: FixRunner = "opencode"
_default_opencode_model = "openai/gpt-5.3-codex"
_default_codex_model = "gpt-5.2-codex"
_default_claude_model = "claude-sonnet-4-6"
_extra_command_search_paths = (
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
    "/usr/local/sbin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)
_auto_python_relative_paths = (
    ".venv/bin/python",
    ".venv/bin/python3",
    "venv/bin/python",
    "venv/bin/python3",
)
_python_project_markers = (
    ".git",
    "pyproject.toml",
    "requirements.txt",
    "Pipfile",
    "setup.py",
    "uv.lock",
)
_bound_runtime: BackendRuntime | None = None
_runtime_state_root_override: Path | None = None
_current_runtime_var: ContextVar[BackendRuntime | None] = ContextVar(
    "openplot_current_runtime",
    default=None,
)


def _runtime_is_shared(runtime: BackendRuntime) -> bool:
    return runtime is get_shared_runtime()


@contextmanager
def _runtime_context(runtime: BackendRuntime):
    token: Token[BackendRuntime | None] = _current_runtime_var.set(runtime)
    try:
        yield
    finally:
        _current_runtime_var.reset(token)


def _current_runtime() -> BackendRuntime:
    return _current_runtime_var.get() or _bound_runtime or get_shared_runtime()


def _runtime_sessions_map() -> dict[str, PlotSession]:
    runtime = _current_runtime()
    return _sessions if _runtime_is_shared(runtime) else runtime.store.sessions


def _runtime_fix_jobs_map() -> dict[str, FixJob]:
    runtime = _current_runtime()
    return _fix_jobs if _runtime_is_shared(runtime) else runtime.store.fix_jobs


def _runtime_fix_job_tasks_map() -> dict[str, asyncio.Task[None]]:
    runtime = _current_runtime()
    return (
        _fix_job_tasks if _runtime_is_shared(runtime) else runtime.infra.fix_job_tasks
    )


def _runtime_fix_job_processes_map() -> dict[str, asyncio.subprocess.Process]:
    runtime = _current_runtime()
    return (
        _fix_job_processes
        if _runtime_is_shared(runtime)
        else runtime.infra.fix_job_processes
    )


def _runtime_active_fix_jobs_map() -> dict[str, str]:
    runtime = _current_runtime()
    return (
        _active_fix_job_ids_by_session
        if _runtime_is_shared(runtime)
        else runtime.store.active_fix_job_ids_by_session
    )


def _runtime_workspace_dir() -> Path:
    runtime = _current_runtime()
    return (
        _workspace_dir if _runtime_is_shared(runtime) else runtime.store.workspace_dir
    )


def _runtime_ws_clients() -> set[WebSocket]:
    runtime = _current_runtime()
    return _ws_clients if _runtime_is_shared(runtime) else runtime.infra.ws_clients


def _runtime_plot_mode_state_value() -> PlotModeState | None:
    runtime = _current_runtime()
    return _plot_mode if _runtime_is_shared(runtime) else runtime.store.plot_mode


def _runtime_active_session_value() -> PlotSession | None:
    runtime = _current_runtime()
    return _session if _runtime_is_shared(runtime) else runtime.store.active_session


def _runtime_active_session_id_value() -> str | None:
    runtime = _current_runtime()
    return (
        _active_session_id
        if _runtime_is_shared(runtime)
        else runtime.store.active_session_id
    )


def _sync_runtime_from_globals(runtime: BackendRuntime) -> None:
    runtime.store.sessions = _sessions
    runtime.store.session_order = _session_order
    runtime.store.active_session_id = _active_session_id
    runtime.store.active_workspace_id = _active_workspace_id()
    runtime.store.active_session = _session
    runtime.store.plot_mode = _plot_mode
    runtime.store.workspace_dir = _workspace_dir
    runtime.store.fix_jobs = _fix_jobs
    runtime.store.active_fix_job_ids_by_session = _active_fix_job_ids_by_session
    runtime.store.loaded_session_store_root = _loaded_session_store_root

    runtime.infra.ws_clients = _ws_clients
    runtime.infra.fix_job_tasks = _fix_job_tasks
    runtime.infra.fix_job_processes = _fix_job_processes
    runtime.infra.runner_install_jobs = _runner_install_jobs
    runtime.infra.active_runner_install_job_id = _active_runner_install_job_id
    runtime.infra.update_status_cache = _update_status_cache
    runtime.infra.update_status_cache_expires_at = _update_status_cache_expires_at
    runtime.infra.opencode_models_cache = _opencode_models_cache
    runtime.infra.opencode_models_cache_expires_at = _opencode_models_cache_expires_at
    runtime.infra.codex_models_cache = _codex_models_cache
    runtime.infra.codex_models_cache_expires_at = _codex_models_cache_expires_at
    runtime.infra.claude_models_cache = _claude_models_cache
    runtime.infra.claude_models_cache_expires_at = _claude_models_cache_expires_at
    if runtime.infra.port_file_path is None or _runtime_is_shared(runtime):
        runtime.infra.port_file_path = _port_file


def _sync_globals_from_runtime(runtime: BackendRuntime) -> None:
    global _active_fix_job_ids_by_session
    global _active_runner_install_job_id
    global _active_session_id
    global _claude_models_cache
    global _claude_models_cache_expires_at
    global _codex_models_cache
    global _codex_models_cache_expires_at
    global _fix_job_processes
    global _fix_job_tasks
    global _fix_jobs
    global _loaded_session_store_root
    global _opencode_models_cache
    global _opencode_models_cache_expires_at
    global _plot_mode
    global _port_file
    global _runner_install_jobs
    global _runtime_state_root_override
    global _session
    global _session_order
    global _sessions
    global _update_status_cache
    global _update_status_cache_expires_at
    global _workspace_dir
    global _ws_clients

    _sessions = runtime.store.sessions
    _session_order = runtime.store.session_order
    _active_session_id = runtime.store.active_session_id
    _session = runtime.store.active_session
    _plot_mode = runtime.store.plot_mode
    _workspace_dir = runtime.store.workspace_dir
    _fix_jobs = runtime.store.fix_jobs
    _fix_job_tasks = runtime.infra.fix_job_tasks
    _fix_job_processes = runtime.infra.fix_job_processes
    _active_fix_job_ids_by_session = runtime.store.active_fix_job_ids_by_session
    _loaded_session_store_root = runtime.store.loaded_session_store_root
    _ws_clients = runtime.infra.ws_clients
    _runner_install_jobs = runtime.infra.runner_install_jobs
    _active_runner_install_job_id = runtime.infra.active_runner_install_job_id
    _opencode_models_cache = runtime.infra.opencode_models_cache
    _opencode_models_cache_expires_at = runtime.infra.opencode_models_cache_expires_at
    _codex_models_cache = runtime.infra.codex_models_cache
    _codex_models_cache_expires_at = runtime.infra.codex_models_cache_expires_at
    _claude_models_cache = runtime.infra.claude_models_cache
    _claude_models_cache_expires_at = runtime.infra.claude_models_cache_expires_at
    _update_status_cache = runtime.infra.update_status_cache
    _update_status_cache_expires_at = runtime.infra.update_status_cache_expires_at
    if runtime.infra.port_file_path is not None:
        _port_file = runtime.infra.port_file_path
    _runtime_state_root_override = (
        runtime.state_root if not _runtime_is_shared(runtime) else None
    )


def _runtime_snapshot() -> dict[str, object]:
    return {
        "bound_runtime": _bound_runtime,
        "sessions": _sessions,
        "session_order": _session_order,
        "active_session_id": _active_session_id,
        "session": _session,
        "plot_mode": _plot_mode,
        "workspace_dir": _workspace_dir,
        "fix_jobs": _fix_jobs,
        "fix_job_tasks": _fix_job_tasks,
        "fix_job_processes": _fix_job_processes,
        "active_fix_job_ids_by_session": _active_fix_job_ids_by_session,
        "loaded_session_store_root": _loaded_session_store_root,
        "ws_clients": _ws_clients,
        "runner_install_jobs": _runner_install_jobs,
        "active_runner_install_job_id": _active_runner_install_job_id,
        "opencode_models_cache": _opencode_models_cache,
        "opencode_models_cache_expires_at": _opencode_models_cache_expires_at,
        "codex_models_cache": _codex_models_cache,
        "codex_models_cache_expires_at": _codex_models_cache_expires_at,
        "claude_models_cache": _claude_models_cache,
        "claude_models_cache_expires_at": _claude_models_cache_expires_at,
        "update_status_cache": _update_status_cache,
        "update_status_cache_expires_at": _update_status_cache_expires_at,
        "port_file": _port_file,
        "runtime_state_root_override": _runtime_state_root_override,
    }


def _restore_runtime_snapshot(snapshot: dict[str, object]) -> None:
    global _active_fix_job_ids_by_session
    global _bound_runtime
    global _active_runner_install_job_id
    global _active_session_id
    global _claude_models_cache
    global _claude_models_cache_expires_at
    global _codex_models_cache
    global _codex_models_cache_expires_at
    global _fix_job_processes
    global _fix_job_tasks
    global _fix_jobs
    global _loaded_session_store_root
    global _opencode_models_cache
    global _opencode_models_cache_expires_at
    global _plot_mode
    global _port_file
    global _runner_install_jobs
    global _runtime_state_root_override
    global _session
    global _session_order
    global _sessions
    global _update_status_cache
    global _update_status_cache_expires_at
    global _workspace_dir
    global _ws_clients

    _bound_runtime = cast(BackendRuntime | None, snapshot["bound_runtime"])
    _sessions = cast(dict[str, PlotSession], snapshot["sessions"])
    _session_order = cast(list[str], snapshot["session_order"])
    _active_session_id = cast(str | None, snapshot["active_session_id"])
    _session = cast(PlotSession | None, snapshot["session"])
    _plot_mode = cast(PlotModeState | None, snapshot["plot_mode"])
    _workspace_dir = cast(Path, snapshot["workspace_dir"])
    _fix_jobs = cast(dict[str, FixJob], snapshot["fix_jobs"])
    _fix_job_tasks = cast(dict[str, asyncio.Task[None]], snapshot["fix_job_tasks"])
    _fix_job_processes = cast(
        dict[str, asyncio.subprocess.Process], snapshot["fix_job_processes"]
    )
    _active_fix_job_ids_by_session = cast(
        dict[str, str], snapshot["active_fix_job_ids_by_session"]
    )
    _loaded_session_store_root = cast(
        Path | None, snapshot["loaded_session_store_root"]
    )
    _ws_clients = cast(set[WebSocket], snapshot["ws_clients"])
    _runner_install_jobs = cast(
        dict[str, dict[str, object]], snapshot["runner_install_jobs"]
    )
    _active_runner_install_job_id = cast(
        str | None, snapshot["active_runner_install_job_id"]
    )
    _opencode_models_cache = cast(
        list[OpencodeModelOption] | None, snapshot["opencode_models_cache"]
    )
    _opencode_models_cache_expires_at = cast(
        float, snapshot["opencode_models_cache_expires_at"]
    )
    _codex_models_cache = cast(
        list[OpencodeModelOption] | None, snapshot["codex_models_cache"]
    )
    _codex_models_cache_expires_at = cast(
        float, snapshot["codex_models_cache_expires_at"]
    )
    _claude_models_cache = cast(
        list[OpencodeModelOption] | None, snapshot["claude_models_cache"]
    )
    _claude_models_cache_expires_at = cast(
        float, snapshot["claude_models_cache_expires_at"]
    )
    _update_status_cache = cast(
        dict[str, object] | None, snapshot["update_status_cache"]
    )
    _update_status_cache_expires_at = cast(
        float, snapshot["update_status_cache_expires_at"]
    )
    _port_file = cast(Path, snapshot["port_file"])
    _runtime_state_root_override = cast(
        Path | None, snapshot["runtime_state_root_override"]
    )


@contextmanager
def _activate_runtime(runtime: BackendRuntime):
    global _bound_runtime
    snapshot = _runtime_snapshot()
    _bound_runtime = runtime
    _sync_globals_from_runtime(runtime)
    try:
        yield
    finally:
        runtime.store.active_workspace_id = _active_workspace_id()
        runtime.store.active_fix_job_ids_by_session = dict(
            _active_fix_job_ids_by_session
        )
        _sync_runtime_from_globals(runtime)
        if _runtime_is_shared(runtime):
            _sync_globals_from_runtime(runtime)
        else:
            _restore_runtime_snapshot(snapshot)


def _with_runtime(runtime: BackendRuntime, callback):
    if _runtime_is_shared(runtime):
        _sync_runtime_from_globals(runtime)
    with _activate_runtime(runtime):
        return callback()


async def _with_runtime_async(runtime: BackendRuntime, awaitable_factory):
    with _runtime_context(runtime):
        return await awaitable_factory()


def _clear_shared_shutdown_runtime_state() -> None:
    global _active_session_id
    global _loaded_session_store_root
    global _session

    _reset_plot_mode_runtime_state()
    _session = None
    _active_session_id = None
    _sessions.clear()
    _session_order.clear()
    _loaded_session_store_root = None


@dataclass(slots=True)
class PlotModeGenerationResult:
    assistant_text: str = ""
    script: str | None = None
    execution_result: ExecutionResult | None = None
    done_hint: bool | None = None
    error_message: str | None = None


@dataclass(slots=True)
class PlotModePlanResult:
    assistant_text: str = ""
    summary: str = ""
    plot_type: str = ""
    plan_outline: list[str] | None = None
    data_actions: list[str] | None = None
    questions: list[PlotModeQuestionItem] | None = None
    question_purpose: str | None = None
    clarification_question: str | None = None
    ready_to_plot: bool = False
    error_message: str | None = None


@dataclass(slots=True)
class PlotModeTabularProposalResult:
    profile: PlotModeDataProfile
    rationale: str = ""
    used_agent: bool = False


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _normalize_fix_runner(value: object | None, *, default: FixRunner) -> FixRunner:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"opencode", "codex", "claude"}:
            return cast(FixRunner, normalized)
    return default


def _sync_plot_mode_runner_selection(
    state: "PlotModeState",
    *,
    runner: object | None,
    model: object | None,
    variant: object | None,
) -> None:
    """Update *state* runner/model/variant from an incoming request payload.

    Called before any automatic phase transition so that the runner chosen in
    the toolbar is honoured even when no chat message has been sent yet.
    If the resolved runner is not available, falls back to the first available
    runner so that stale preferences never cause a 503.
    """
    if runner:
        state.selected_runner = _normalize_fix_runner(
            runner, default=_default_fix_runner
        )
    state.selected_runner = _resolve_available_runner(state.selected_runner)
    if model:
        state.selected_model = str(model).strip()
    if variant is not None:
        state.selected_variant = str(variant).strip()


def _runner_default_model_id(runner: FixRunner) -> str:
    if runner == "codex":
        return _default_codex_model
    if runner == "claude":
        return _default_claude_model
    return _default_opencode_model


def _normalize_runner_session_id(value: object) -> str | None:
    candidate = _as_string(value)
    if candidate is None:
        return None
    if len(candidate) > 256:
        return None
    return candidate


def _runner_session_id_for_session(
    session: PlotSession, runner: FixRunner
) -> str | None:
    return _normalize_runner_session_id(session.runner_session_ids.get(runner))


def _set_runner_session_id_for_session(
    session: PlotSession,
    *,
    runner: FixRunner,
    session_id: str,
) -> None:
    normalized_session_id = _normalize_runner_session_id(session_id)
    if normalized_session_id is None:
        return
    if session.runner_session_ids.get(runner) == normalized_session_id:
        return
    session.runner_session_ids[runner] = normalized_session_id
    _touch_session(session)
    with suppress(OSError):
        _save_session_snapshot(session)


def _clear_runner_session_id_for_session(
    session: PlotSession, runner: FixRunner
) -> None:
    if runner not in session.runner_session_ids:
        return
    session.runner_session_ids.pop(runner, None)
    _touch_session(session)
    with suppress(OSError):
        _save_session_snapshot(session)


def _runner_session_id_for_plot_mode(
    state: PlotModeState,
    runner: FixRunner,
) -> str | None:
    return _normalize_runner_session_id(state.runner_session_ids.get(runner))


def _set_runner_session_id_for_plot_mode(
    state: PlotModeState,
    *,
    runner: FixRunner,
    session_id: str,
) -> None:
    normalized_session_id = _normalize_runner_session_id(session_id)
    if normalized_session_id is None:
        return
    if state.runner_session_ids.get(runner) == normalized_session_id:
        return
    state.runner_session_ids[runner] = normalized_session_id
    _touch_plot_mode(state)


def _clear_runner_session_id_for_plot_mode(
    state: PlotModeState,
    runner: FixRunner,
) -> None:
    if runner not in state.runner_session_ids:
        return
    state.runner_session_ids.pop(runner, None)
    _touch_plot_mode(state)


def _command_search_path() -> str:
    raw_path = os.getenv("PATH") or ""
    entries = [entry for entry in raw_path.split(os.pathsep) if entry]

    home_bin_paths = (
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".opencode" / "bin"),
        str(Path.home() / ".cargo" / "bin"),
    )
    for candidate in (*home_bin_paths, *_extra_command_search_paths):
        if candidate not in entries:
            entries.append(candidate)

    return os.pathsep.join(entries)


def _runner_tools_root() -> Path:
    path = _state_root() / "tools"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _managed_command_path(command: str) -> str | None:
    if command != "codex":
        return None
    candidate = _runner_tools_root() / "codex" / "current" / "codex"
    if not candidate.exists():
        return None
    return str(candidate)


def _resolve_command_path(command: str) -> str | None:
    managed = _managed_command_path(command)
    if managed:
        return managed
    return shutil.which(command, path=_command_search_path())


def _subprocess_env(*, overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = _command_search_path()
    if overrides:
        env.update(overrides)
    return env


def _no_window_kwargs() -> dict[str, object]:
    """Return kwargs that suppress console windows on Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _hidden_window_kwargs() -> dict[str, object]:
    """Return kwargs that hide the console window but still allocate a console.

    Unlike CREATE_NO_WINDOW, this gives the child process a real console so
    Node.js-based CLIs (claude, codex, opencode) can perform TTY detection and
    signal handling without hanging.
    """
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return {"startupinfo": si}
    return {}


def _shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def _resolve_openplot_mcp_launch_command() -> list[str]:
    executable = Path(sys.executable).expanduser()
    if _is_openplot_app_launcher_path(executable):
        return [str(executable), "--internal-run-mcp"]

    virtual_env = os.getenv("VIRTUAL_ENV")
    if virtual_env:
        venv_root = Path(virtual_env).expanduser()
        venv_candidates = [
            venv_root / "bin" / "python",
            venv_root / "bin" / "python3",
            venv_root / "Scripts" / "python.exe",
            venv_root / "Scripts" / "python",
        ]
        for venv_python in venv_candidates:
            if venv_python.is_file() and os.access(venv_python, os.X_OK):
                return [str(venv_python), "-m", "openplot.cli", "mcp"]

    return [str(executable), "-m", "openplot.cli", "mcp"]


def _backend_url_from_port_file() -> str | None:
    try:
        raw_port = _read_file_text(_port_file).strip()
    except OSError:
        return None

    if not raw_port:
        return None

    try:
        port = int(raw_port)
    except ValueError:
        return None

    if port <= 0:
        return None

    return f"http://127.0.0.1:{port}"


def _write_fix_runner_shims(runtime_dir: Path) -> Path:
    shim_bin = runtime_dir / "bin"
    shim_bin.mkdir(parents=True, exist_ok=True)

    mcp_command = _resolve_openplot_mcp_launch_command()

    if sys.platform == "win32":
        _write_fix_runner_shims_windows(shim_bin, mcp_command)
    else:
        _write_fix_runner_shims_unix(shim_bin, mcp_command)

    return shim_bin


def _write_fix_runner_shims_unix(shim_bin: Path, mcp_command: list[str]) -> None:
    openplot_script = "\n".join(
        [
            "#!/bin/sh",
            "set -e",
            'if [ "$#" -ge 1 ] && [ "$1" = "mcp" ]; then',
            "  shift",
            f'  exec {_shell_join(mcp_command)} "$@"',
            "fi",
            'echo "openplot shim supports only the mcp subcommand" >&2',
            "exit 2",
            "",
        ]
    )
    openplot_path = shim_bin / "openplot"
    openplot_path.write_text(openplot_script, encoding="utf-8")
    openplot_path.chmod(0o755)

    real_uv = _resolve_command_path("uv")
    uv_script_lines = [
        "#!/bin/sh",
        "set -e",
        'if [ "$#" -ge 1 ] && [ "$1" = "run" ]; then',
        "  shift",
        '  if [ "$#" -eq 0 ]; then',
        "    echo 'uv shim: missing command after \"run\"' >&2",
        "    exit 2",
        "  fi",
        '  exec "$@"',
        "fi",
    ]

    if real_uv:
        uv_script_lines.extend(
            [
                f'exec {shlex.quote(real_uv)} "$@"',
                "",
            ]
        )
    else:
        uv_script_lines.extend(
            [
                "echo 'uv shim supports only the \"run\" command when uv is unavailable' >&2",
                "exit 2",
                "",
            ]
        )

    uv_path = shim_bin / "uv"
    uv_path.write_text("\n".join(uv_script_lines), encoding="utf-8")
    uv_path.chmod(0o755)


def _write_fix_runner_shims_windows(shim_bin: Path, mcp_command: list[str]) -> None:
    mcp_cmd_line = subprocess.list2cmdline(mcp_command)
    openplot_script = "\r\n".join(
        [
            "@echo off",
            'if /i "%~1"=="mcp" (',
            f"    {mcp_cmd_line}",
            "    exit /b %errorlevel%",
            ")",
            "echo openplot shim supports only the mcp subcommand 1>&2",
            "exit /b 2",
            "",
        ]
    )
    openplot_path = shim_bin / "openplot.cmd"
    openplot_path.write_text(openplot_script, encoding="utf-8")

    real_uv = _resolve_command_path("uv")
    if real_uv:
        uv_script = "\r\n".join(
            [
                "@echo off",
                'if /i "%~1"=="run" (',
                "    shift",
                "    %1 %2 %3 %4 %5 %6 %7 %8 %9",
                "    exit /b %errorlevel%",
                ")",
                f"{subprocess.list2cmdline([real_uv])} %*",
                "exit /b %errorlevel%",
                "",
            ]
        )
    else:
        uv_script = "\r\n".join(
            [
                "@echo off",
                'if /i "%~1"=="run" (',
                "    shift",
                "    %1 %2 %3 %4 %5 %6 %7 %8 %9",
                "    exit /b %errorlevel%",
                ")",
                "echo uv shim supports only the run command when uv is unavailable 1>&2",
                "exit /b 2",
                "",
            ]
        )
    uv_path = shim_bin / "uv.cmd"
    uv_path.write_text(uv_script, encoding="utf-8")


def _resolve_claude_cli_command() -> str | None:
    for command in ("claude", "claude-code"):
        resolved = _resolve_command_path(command)
        if resolved:
            return resolved
    return None


def _is_command_available(command: str) -> bool:
    return _resolve_command_path(command) is not None


def _runner_launch_probe(runner: FixRunner) -> bool:
    command = (
        _resolve_claude_cli_command()
        if runner == "claude"
        else _resolve_command_path(runner)
    )
    if not command:
        return False
    try:
        result = _run_install_subprocess([command, "--version"])
    except Exception:
        return False
    return result.returncode == 0


def _opencode_auth_file_path() -> Path:
    return Path.home() / ".local" / "share" / "opencode" / "auth.json"


def _opencode_auth_file_has_credentials() -> bool:
    path = _opencode_auth_file_path()
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if isinstance(payload, dict):
        return any(bool(value) for value in payload.values())
    if isinstance(payload, list):
        return len(payload) > 0
    return bool(payload)


def _opencode_auth_list_has_credentials(output: str) -> bool:
    normalized = output.strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    return not any(
        token in lowered
        for token in (
            "no authenticated providers",
            "no providers configured",
            "no credentials found",
        )
    )


def _runner_auth_command(runner: FixRunner) -> str:
    if runner == "claude":
        return "claude"
    if runner == "codex":
        return "codex"
    return "opencode auth login"


def _runner_auth_launch_parts(runner: FixRunner) -> list[str]:
    executable = (
        _resolve_claude_cli_command()
        if runner == "claude"
        else _resolve_command_path(runner)
    ) or ("claude" if runner == "claude" else runner)
    if runner == "claude":
        return [executable]
    if runner == "codex":
        return [executable]
    return [executable, "auth", "login"]


def _runner_auth_launch_command(runner: FixRunner) -> str:
    return _shell_join(_runner_auth_launch_parts(runner))


def _powershell_quote(text: str) -> str:
    escaped = text.replace("`", "``").replace('"', '`"')
    return f'"{escaped}"'


def _runner_auth_windows_command(runner: FixRunner) -> str:
    parts = _runner_auth_launch_parts(runner)
    executable, *args = parts
    if any(token in executable for token in ("/", "\\", " ")):
        rendered_executable = f"& {_powershell_quote(executable)}"
    else:
        rendered_executable = executable
    rendered_args = [
        _powershell_quote(arg)
        if any(token in arg for token in (" ", '"', "&"))
        else arg
        for arg in args
    ]
    return " ".join([rendered_executable, *rendered_args])


def _runner_auth_guide_url(runner: FixRunner) -> str:
    if runner == "claude":
        return "https://code.claude.com/docs/en/authentication"
    if runner == "codex":
        return "https://developers.openai.com/codex/auth"
    return "https://opencode.ai/docs/providers"


def _runner_auth_instructions(
    runner: FixRunner, *, terminal_launch_supported: bool
) -> str:
    command = _runner_auth_command(runner)
    if not terminal_launch_supported:
        return (
            f'Open a terminal and run "{command}". '
            "Finish the sign-in steps there, then come back to OpenPlot and click Refresh."
        )
    return (
        f'OpenPlot will open Terminal and run "{command}" for you. '
        "Finish the sign-in steps there, close Terminal, then come back here and click Refresh."
    )


def _runner_auth_probe(runner: FixRunner) -> bool:
    if runner == "claude":
        command = _resolve_claude_cli_command()
        if not command:
            return False
        try:
            result = _run_install_subprocess([command, "auth", "status", "--text"])
        except Exception:
            return False
        return result.returncode == 0

    command = _resolve_command_path(runner)
    if not command:
        return False

    if runner == "codex":
        try:
            result = _run_install_subprocess([command, "login", "status"])
        except Exception:
            return False
        return result.returncode == 0

    if _opencode_auth_file_has_credentials():
        return True
    try:
        result = _run_install_subprocess([command, "auth", "list"])
    except Exception:
        return False
    return result.returncode == 0 and _opencode_auth_list_has_credentials(result.stdout)


def _runner_auth_launch_supported(host_platform: str) -> bool:
    return host_platform in {"darwin", "win32"}


def _apple_script_quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _launch_runner_auth_terminal(runner: FixRunner) -> None:
    if sys.platform == "win32":
        command = _runner_auth_windows_command(runner)
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoExit", "-Command", command],
                env=_subprocess_env(),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise RuntimeError(
                "Failed to launch PowerShell for runner authentication"
            ) from exc
        return

    command = _runner_auth_launch_command(runner)
    if sys.platform != "darwin":
        raise RuntimeError(
            "Launching authentication in Terminal is only supported on macOS and Windows"
        )

    result = subprocess.run(
        [
            "osascript",
            "-e",
            'tell application "Terminal" to activate',
            "-e",
            f'tell application "Terminal" to do script {_apple_script_quote(command)}',
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        raise RuntimeError(
            stderr or stdout or "Failed to launch Terminal for runner authentication"
        )


def _detect_runner_availability() -> dict[str, object]:
    opencode_available = _runner_launch_probe("opencode") and _runner_auth_probe(
        "opencode"
    )
    codex_available = _runner_launch_probe("codex") and _runner_auth_probe("codex")
    claude_code_available = _runner_launch_probe("claude") and _runner_auth_probe(
        "claude"
    )

    available_runners: list[FixRunner] = []
    if opencode_available:
        available_runners.append("opencode")
    if codex_available:
        available_runners.append("codex")
    if claude_code_available:
        available_runners.append("claude")

    return {
        "available_runners": available_runners,
        "supported_runners": ["opencode", "codex", "claude"],
        "claude_code_available": claude_code_available,
    }


def _runner_host_platform() -> tuple[str, str]:
    machine = platform.machine().strip().lower() or "unknown"
    if sys.platform == "darwin":
        return "darwin", machine
    if os.name == "nt":
        return "win32", machine
    if sys.platform.startswith("linux"):
        return "linux", machine
    return sys.platform, machine


def _winget_available() -> bool:
    if os.name != "nt":
        return False
    return _is_command_available("winget")


def _runner_guide_url(runner: FixRunner) -> str:
    if runner == "claude":
        return (
            "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview"
        )
    if runner == "codex":
        return "https://developers.openai.com/codex"
    return "https://opencode.ai/docs"


def _runner_install_supported(
    *, runner: FixRunner, host_platform: str, host_arch: str
) -> bool:
    normalized_arch = host_arch.lower()
    if host_platform == "darwin" and normalized_arch in {"arm64", "aarch64"}:
        return True
    return False


def _runner_default_status(
    *, runner: FixRunner, host_platform: str, host_arch: str
) -> tuple[str, str, str, str]:
    if host_platform == "darwin" and host_arch.lower() in {"arm64", "aarch64"}:
        return "available_to_install", "Available to install", "install", "Install"
    if host_platform == "win32":
        return "unsupported", "Guide available", "guide", "See guide"
    return "manual", "Guide available", "guide", "See guide"


def _runner_install_job_snapshot(job_id: str | None) -> dict[str, object] | None:
    if not job_id:
        return None
    with _runner_install_jobs_lock:
        job = _runner_install_jobs.get(job_id)
        if job is None:
            return None
        return dict(job)


def _latest_runner_install_job_snapshot(runner: FixRunner) -> dict[str, object] | None:
    with _runner_install_jobs_lock:
        matching_jobs = [
            dict(job)
            for job in _runner_install_jobs.values()
            if job.get("runner") == runner
        ]
    if not matching_jobs:
        return None
    matching_jobs.sort(key=lambda job: str(job.get("created_at") or ""))
    return matching_jobs[-1]


def _build_runner_status_payload() -> dict[str, object]:
    availability = _detect_runner_availability()
    available_runners = cast(
        list[FixRunner],
        availability.get("available_runners") or [],
    )
    supported_runners = cast(
        list[FixRunner],
        availability.get("supported_runners") or ["opencode", "codex", "claude"],
    )
    host_platform, host_arch = _runner_host_platform()
    active_job = _runner_install_job_snapshot(_active_runner_install_job_id)

    runners: list[dict[str, object]] = []
    for runner in supported_runners:
        latest_job = _latest_runner_install_job_snapshot(runner)
        latest_job_state = str(latest_job.get("state")) if latest_job else None
        resolved_path = (
            _resolve_claude_cli_command()
            if runner == "claude"
            else _resolve_command_path(runner)
        )
        auth_command: str | None = None
        auth_instructions: str | None = None
        install_supported = _runner_install_supported(
            runner=runner,
            host_platform=host_platform,
            host_arch=host_arch,
        )
        can_launch_auth = _runner_auth_launch_supported(host_platform)
        is_installed = runner in available_runners
        status, status_label, primary_action, primary_action_label = (
            _runner_default_status(
                runner=runner,
                host_platform=host_platform,
                host_arch=host_arch,
            )
        )
        if is_installed:
            status = "installed"
            status_label = "Installed"
            primary_action = "none"
            primary_action_label = "Installed"
        elif latest_job_state in {"queued", "running"}:
            status = "installing"
            status_label = "Installing"
            primary_action = "none"
            primary_action_label = "Installing"
        elif resolved_path:
            if _runner_launch_probe(runner):
                status = "installed_needs_auth"
                status_label = "Sign-in required"
                primary_action = "authenticate" if can_launch_auth else "guide"
                primary_action_label = (
                    "Authenticate" if can_launch_auth else "See guide"
                )
                auth_command = _runner_auth_command(runner)
                auth_instructions = _runner_auth_instructions(
                    runner,
                    terminal_launch_supported=can_launch_auth,
                )
            else:
                status = "needs_attention"
                status_label = "Needs attention"
                primary_action = "guide"
                primary_action_label = "See guide"
        elif latest_job_state == "failed":
            primary_action = "install" if install_supported else "guide"
            primary_action_label = "Retry" if install_supported else "See guide"
            status = "needs_attention"
            status_label = "Needs attention"

        runners.append(
            {
                "runner": runner,
                "status": status,
                "status_label": status_label,
                "primary_action": primary_action,
                "primary_action_label": primary_action_label,
                "guide_url": (
                    _runner_auth_guide_url(runner)
                    if status == "installed_needs_auth"
                    else _runner_guide_url(runner)
                ),
                "installed": is_installed or resolved_path is not None,
                "executable_path": resolved_path,
                "install_job": latest_job,
                "auth_command": auth_command,
                "auth_instructions": auth_instructions,
            }
        )

    return {
        "available_runners": available_runners,
        "supported_runners": supported_runners,
        "claude_code_available": availability.get("claude_code_available", False),
        "host_platform": host_platform,
        "host_arch": host_arch,
        "active_install_job_id": active_job.get("id") if active_job else None,
        "runners": runners,
    }


def _create_runner_install_job(
    runner: FixRunner,
    *,
    runtime: BackendRuntime | None = None,
) -> dict[str, object]:
    global _active_runner_install_job_id
    resolved_runtime = runtime or _bound_runtime or get_shared_runtime()

    with _runner_install_jobs_lock:
        active_job = _runner_install_jobs.get(_active_runner_install_job_id or "")
        if active_job is not None and active_job.get("state") in {"queued", "running"}:
            raise HTTPException(
                status_code=409,
                detail="Another runner install is already in progress.",
            )

        job = {
            "id": uuid.uuid4().hex,
            "runner": runner,
            "state": "queued",
            "logs": [f"Queued install for {runner}."],
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "finished_at": None,
        }
        _runner_install_jobs[str(job["id"])] = job
        _active_runner_install_job_id = str(job["id"])
        threading.Thread(
            target=_run_runner_install_job,
            args=(str(job["id"]), resolved_runtime),
            name=f"runner-install-{runner}",
            daemon=True,
        ).start()
        return dict(job)


def _update_runner_install_job(
    job_id: str, **updates: object
) -> dict[str, object] | None:
    global _active_runner_install_job_id

    with _runner_install_jobs_lock:
        job = _runner_install_jobs.get(job_id)
        if job is None:
            return None
        job.update(updates)
        if (
            job.get("state") in {"succeeded", "failed"}
            and _active_runner_install_job_id == job_id
        ):
            _active_runner_install_job_id = None
        return dict(job)


def _append_runner_install_log(job_id: str, message: str) -> None:
    with _runner_install_jobs_lock:
        job = _runner_install_jobs.get(job_id)
        if job is None:
            return
        logs = cast(list[str], job.setdefault("logs", []))
        logs.append(message)
        if len(logs) > 200:
            del logs[:-200]


def _run_install_subprocess(
    command: list[str], *, shell: bool = False
) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, object] = {
        "capture_output": True,
        "text": True,
        "timeout": 900,
        "env": _subprocess_env(),
    }
    kwargs.update(_no_window_kwargs())
    if shell:
        return subprocess.run(command[0], shell=True, check=False, **kwargs)
    return subprocess.run(command, check=False, **kwargs)


def _resolve_runner_executable_path(runner: FixRunner) -> str | None:
    if runner == "claude":
        return _resolve_claude_cli_command()
    return _resolve_command_path(runner)


def _install_runner_via_script(
    *, runner: FixRunner, script_url: str, job_id: str
) -> dict[str, object]:
    _append_runner_install_log(job_id, f"Running official installer from {script_url}")
    if os.name == "nt":
        raise RuntimeError(
            f"{runner} script installer is not supported on this platform"
        )
    result = _run_install_subprocess(
        [f"curl -fsSL {shlex.quote(script_url)} | bash"], shell=True
    )
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if stdout:
        _append_runner_install_log(job_id, stdout[-1000:])
    if stderr:
        _append_runner_install_log(job_id, stderr[-1000:])
    if result.returncode != 0:
        raise RuntimeError(
            stderr or stdout or f"Installer exited with code {result.returncode}"
        )
    executable_path = _resolve_runner_executable_path(runner)
    if not executable_path:
        raise RuntimeError(
            "Installer completed, but OpenPlot still could not find the runner executable"
        )
    return {"executable_path": executable_path}


def _download_url_to_file(url: str, target: Path) -> None:
    target.write_bytes(_read_url_bytes(url))


def _run_download_subprocess(
    url: str, *, headers: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[bytes]:
    command = ["curl", "-fsSL"]
    if headers:
        for key, value in headers.items():
            command.extend(["-H", f"{key}: {value}"])
    command.append(url)
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(
        command,
        capture_output=True,
        text=False,
        timeout=900,
        env=_subprocess_env(),
        check=False,
        creationflags=creationflags,
    )


def _read_url_bytes(url: str, *, headers: Mapping[str, str] | None = None) -> bytes:
    request_headers = {"User-Agent": "OpenPlot"}
    if headers:
        request_headers.update(headers)
    request = urllib_request.Request(url, headers=request_headers)
    try:
        with urllib_request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib_error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if not isinstance(reason, ssl.SSLCertVerificationError):
            raise
        fallback = _run_download_subprocess(url, headers=headers)
        if fallback.returncode != 0:
            stderr = fallback.stderr.decode("utf-8", errors="replace").strip()
            stdout = fallback.stdout.decode("utf-8", errors="replace").strip()
            raise RuntimeError(stderr or stdout or f"Failed to download {url}") from exc
        return fallback.stdout


def _parse_semver_parts(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value.strip())
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def _normalize_release_version(value: object) -> str | None:
    parts = _parse_semver_parts(value)
    if parts is None:
        return None
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def _fetch_latest_release_payload() -> dict[str, object]:
    payload = json.loads(
        _read_url_bytes(
            _latest_release_api_url,
            headers={"Accept": "application/vnd.github+json"},
        ).decode("utf-8")
    )
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub release payload was not an object")
    return payload


def _default_update_status_payload() -> dict[str, object]:
    return {
        "current_version": __version__,
        "latest_version": None,
        "latest_release_url": _latest_release_page_url,
        "update_available": False,
        "checked_at": None,
        "error": None,
    }


def _update_status_cache_path() -> Path:
    root = _state_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "update-status.json"


def _load_update_status_disk_cache(*, require_fresh: bool) -> dict[str, object] | None:
    path = _update_status_cache_path()
    if not path.exists():
        return None
    if (
        require_fresh
        and time.time() - path.stat().st_mtime >= _update_status_cache_ttl_s
    ):
        return None
    try:
        payload = json.loads(_read_file_text(path))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _store_update_status_cache(payload: Mapping[str, object]) -> None:
    global _update_status_cache, _update_status_cache_expires_at

    cached = dict(payload)
    _update_status_cache = cached
    _update_status_cache_expires_at = time.monotonic() + _update_status_cache_ttl_s
    try:
        _update_status_cache_path().write_text(json.dumps(cached), encoding="utf-8")
    except OSError:
        pass


def _build_update_status_payload_impl(
    *, force_refresh: bool = False, allow_network: bool = True
) -> dict[str, object]:
    global _update_status_cache, _update_status_cache_expires_at

    now = time.monotonic()
    if (
        not force_refresh
        and _update_status_cache is not None
        and now < _update_status_cache_expires_at
    ):
        return dict(_update_status_cache)

    if not force_refresh:
        disk_cached = _load_update_status_disk_cache(require_fresh=True)
        if disk_cached is not None:
            _update_status_cache = dict(disk_cached)
            _update_status_cache_expires_at = now + _update_status_cache_ttl_s
            return dict(disk_cached)

    stale_cached = (
        None if force_refresh else _load_update_status_disk_cache(require_fresh=False)
    )
    if not allow_network:
        if stale_cached is not None:
            return dict(stale_cached)
        return _default_update_status_payload()

    checked_at = _now_iso()
    payload: dict[str, object] = _default_update_status_payload()
    payload["checked_at"] = checked_at

    try:
        release = _fetch_latest_release_payload()
        if release.get("draft") is True or release.get("prerelease") is True:
            raise RuntimeError("No stable GitHub release is currently published")

        latest_version = _normalize_release_version(release.get("tag_name"))
        if latest_version is None:
            latest_version = _normalize_release_version(release.get("name"))
        if latest_version is None:
            raise RuntimeError(
                "Latest GitHub release did not expose a semantic version"
            )

        release_url = release.get("html_url")
        if isinstance(release_url, str) and release_url.startswith(
            ("https://", "http://")
        ):
            payload["latest_release_url"] = release_url

        current_parts = _parse_semver_parts(__version__)
        latest_parts = _parse_semver_parts(latest_version)
        if current_parts is None or latest_parts is None:
            raise RuntimeError("Could not compare semantic versions")

        payload["latest_version"] = latest_version
        payload["update_available"] = latest_parts > current_parts
    except Exception as exc:
        payload["error"] = str(exc) or "Failed to check for updates"

    _store_update_status_cache(payload)
    return dict(payload)


def _build_update_status_payload(
    *, force_refresh: bool = False, allow_network: bool = True
) -> dict[str, object]:
    return build_update_status_payload(
        _bound_runtime or get_shared_runtime(),
        allow_network=allow_network,
        force_refresh=force_refresh,
    )


def _install_codex_release(job_id: str) -> dict[str, object]:
    host_platform, host_arch = _runner_host_platform()
    if host_platform != "darwin" or host_arch.lower() not in {"arm64", "aarch64"}:
        raise RuntimeError(
            "Codex click-install is only supported on macOS Apple Silicon"
        )

    _append_runner_install_log(job_id, "Fetching latest Codex release metadata")
    payload = json.loads(
        _read_url_bytes(
            "https://api.github.com/repos/openai/codex/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
        ).decode("utf-8")
    )

    assets = payload.get("assets") or []
    asset_name = "codex-aarch64-apple-darwin.tar.gz"
    asset = next((item for item in assets if item.get("name") == asset_name), None)
    if asset is None:
        raise RuntimeError(f"Could not find {asset_name} in the latest Codex release")

    with tempfile.TemporaryDirectory(prefix="openplot-codex-") as temp_dir:
        temp_root = Path(temp_dir)
        archive_path = temp_root / asset_name
        _append_runner_install_log(job_id, f"Downloading {asset_name}")
        _download_url_to_file(str(asset["browser_download_url"]), archive_path)

        extract_dir = temp_root / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(extract_dir)

        binary_candidates = [path for path in extract_dir.rglob("*") if path.is_file()]
        binary_path = next(
            (path for path in binary_candidates if path.name.startswith("codex-")), None
        )
        if binary_path is None:
            raise RuntimeError("Codex archive did not contain an executable")

        target_path = _runner_tools_root() / "codex" / "current" / "codex"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary_path, target_path)
        target_path.chmod(0o755)
        _append_runner_install_log(job_id, f"Installed Codex to {target_path}")

    executable_path = _resolve_runner_executable_path("codex")
    if not executable_path:
        raise RuntimeError(
            "Codex install finished, but OpenPlot still could not find the executable"
        )
    return {"executable_path": executable_path}


def _perform_runner_install(
    runner: FixRunner, job: dict[str, object]
) -> dict[str, object]:
    job_id = str(job["id"])
    host_platform, host_arch = _runner_host_platform()
    if runner == "opencode":
        if host_platform == "darwin" and host_arch.lower() in {"arm64", "aarch64"}:
            return _install_runner_via_script(
                runner=runner,
                script_url="https://opencode.ai/install",
                job_id=job_id,
            )
        raise RuntimeError("OpenCode click-install is not supported on this machine")
    if runner == "claude":
        if host_platform == "darwin" and host_arch.lower() in {"arm64", "aarch64"}:
            return _install_runner_via_script(
                runner=runner,
                script_url="https://claude.ai/install.sh",
                job_id=job_id,
            )
        raise RuntimeError(
            "Claude click-install is only supported on macOS Apple Silicon"
        )
    if runner == "codex":
        return _install_codex_release(job_id)
    raise RuntimeError(f"Unknown runner: {runner}")


def _run_runner_install_job(
    job_id: str,
    runtime: BackendRuntime | None = None,
) -> None:
    resolved_runtime = runtime or _bound_runtime or get_shared_runtime()

    def _run() -> None:
        job = _update_runner_install_job(
            job_id,
            state="running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        if job is None:
            return

        runner = cast(FixRunner, job["runner"])
        try:
            result = _perform_runner_install(runner, job)
            resolved_path = result.get(
                "executable_path"
            ) or _resolve_runner_executable_path(runner)
            if not _runner_launch_probe(runner):
                raise RuntimeError(
                    "Install completed, but the runner still does not pass a launch probe"
                )
            _update_runner_install_job(
                job_id,
                state="succeeded",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error=None,
                resolved_path=resolved_path,
            )
        except Exception as exc:
            _append_runner_install_log(job_id, str(exc))
            _update_runner_install_job(
                job_id,
                state="failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error=str(exc),
            )

    _with_runtime(resolved_runtime, _run)


def _runner_is_available(runner: FixRunner) -> bool:
    availability = _detect_runner_availability()
    available_runners = availability.get("available_runners")
    if not isinstance(available_runners, list):
        return False
    return runner in available_runners


def _resolve_available_runner(preferred: FixRunner) -> FixRunner:
    """Return *preferred* if it is installed, otherwise the first available runner."""
    availability = _detect_runner_availability()
    available_runners = availability.get("available_runners")
    if not isinstance(available_runners, list) or not available_runners:
        return preferred
    if preferred in available_runners:
        return preferred
    return available_runners[0]


def _ensure_runner_is_available(runner: FixRunner) -> None:
    if _runner_is_available(runner):
        return
    raise HTTPException(
        status_code=503,
        detail=(
            f"Runner '{runner}' is not available on this machine. "
            "Install the matching CLI first."
        ),
    )


def set_workspace_dir(path: str | Path) -> Path:
    """Set the workspace directory used by agent subprocesses."""
    runtime = _current_runtime()
    resolved = set_runtime_workspace_dir(runtime, Path(path))
    global _workspace_dir
    if _runtime_is_shared(runtime):
        _workspace_dir = resolved
    return resolved


def _path_from_override_env(var_name: str) -> Path | None:
    raw_value = os.getenv(var_name)
    if raw_value is None:
        return None
    normalized = raw_value.strip()
    if not normalized:
        return None
    return Path(normalized).expanduser().resolve()


def _default_data_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenPlot" / "data"

    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if local_app_data:
            return Path(local_app_data) / "OpenPlot" / "data"
        return Path.home() / "AppData" / "Local" / "OpenPlot" / "data"

    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "openplot"
    return Path.home() / ".local" / "share" / "openplot"


def _default_state_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenPlot" / "state"

    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if local_app_data:
            return Path(local_app_data) / "OpenPlot" / "state"
        return Path.home() / "AppData" / "Local" / "OpenPlot" / "state"

    xdg_state_home = os.getenv("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home) / "openplot"
    return Path.home() / ".local" / "state" / "openplot"


def _data_root() -> Path:
    return _path_from_override_env("OPENPLOT_DATA_DIR") or _default_data_root()


def _plot_mode_root_dir() -> Path:
    root = _state_root() / "plot-mode"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _plot_mode_artifacts_dir(state: PlotModeState) -> Path:
    path = _plot_mode_root_dir() / state.id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _plot_mode_captures_dir(state: PlotModeState) -> Path:
    path = _plot_mode_artifacts_dir(state) / "captures"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _plot_mode_generated_script_path(state: PlotModeState) -> Path:
    return _plot_mode_artifacts_dir(state) / _plot_mode_generated_script_name


def _plot_mode_snapshot_path() -> Path:
    return _plot_mode_root_dir() / _plot_mode_snapshot_file_name


def _plot_mode_artifacts_path_for_id(plot_mode_id: str) -> Path:
    return _plot_mode_root_dir() / plot_mode_id


def _plot_mode_workspace_snapshot_path_for_id(plot_mode_id: str) -> Path:
    return (
        _plot_mode_artifacts_path_for_id(plot_mode_id)
        / _plot_mode_workspace_snapshot_file_name
    )


def _plot_mode_workspace_snapshot_path(state: PlotModeState) -> Path:
    return _plot_mode_workspace_snapshot_path_for_id(state.id)


def _iso_from_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _plot_mode_has_user_content(state: PlotModeState) -> bool:
    if state.files:
        return True
    if state.messages:
        return True
    if state.data_profiles:
        return True
    if state.tabular_selector is not None:
        return True
    if state.pending_question_set is not None:
        return True
    if (state.current_script or "").strip():
        return True
    if (state.current_script_path or "").strip():
        return True
    if (state.current_plot or "").strip():
        return True
    if state.latest_plan_outline or state.latest_plan_actions:
        return True
    if state.latest_plan_summary.strip() or state.latest_plan_plot_type.strip():
        return True
    if state.latest_user_goal.strip():
        return True
    if state.last_error:
        return True
    return False


def _plot_mode_is_workspace(state: PlotModeState) -> bool:
    return state.is_workspace or _plot_mode_has_user_content(state)


def _promote_plot_mode_workspace(state: PlotModeState) -> None:
    if state.is_workspace:
        return
    state.is_workspace = True


def _ensure_plot_mode_workspace_name(state: PlotModeState) -> None:
    existing = state.workspace_name.strip()
    if existing:
        state.workspace_name = existing
        return
    state.workspace_name = _default_workspace_name(state.created_at)


def _is_active_plot_mode_state(state: PlotModeState) -> bool:
    active_plot_mode = _runtime_plot_mode_state_value()
    return active_plot_mode is not None and active_plot_mode.id == state.id


def _save_plot_mode_snapshot(state: PlotModeState) -> None:
    if not _plot_mode_is_workspace(state):
        return
    _promote_plot_mode_workspace(state)
    _ensure_plot_mode_workspace_name(state)
    payload = cast(dict[str, object], state.model_dump(mode="json"))

    workspace_snapshot_path = _plot_mode_workspace_snapshot_path(state)
    if workspace_snapshot_path != _plot_mode_snapshot_path():
        _write_json_atomic(workspace_snapshot_path, payload)

    if _is_active_plot_mode_state(state):
        _write_json_atomic(_plot_mode_snapshot_path(), payload)


def _load_plot_mode_state_from_payload(raw: object) -> PlotModeState | None:
    if not isinstance(raw, dict):
        return None

    try:
        state = PlotModeState.model_validate(raw)
    except Exception:
        return None

    raw_is_workspace = raw.get("is_workspace")
    if isinstance(raw_is_workspace, bool):
        state.is_workspace = raw_is_workspace
    else:
        state.is_workspace = _plot_mode_has_user_content(state)
    if _plot_mode_has_user_content(state):
        state.is_workspace = True

    _ensure_plot_mode_workspace_name(state)
    if not state.updated_at:
        state.updated_at = state.created_at or _now_iso()
    if not _plot_mode_is_workspace(state):
        return None
    return state


def _load_plot_mode_state_from_path(snapshot_path: Path) -> PlotModeState | None:
    if not snapshot_path.exists():
        return None

    try:
        raw = json.loads(_read_file_text(snapshot_path))
    except (OSError, json.JSONDecodeError):
        return None
    return _load_plot_mode_state_from_payload(raw)


def _infer_plot_mode_state_from_artifacts_dir(
    plot_mode_dir: Path,
) -> PlotModeState | None:
    if not plot_mode_dir.is_dir():
        return None

    script_path = plot_mode_dir / _plot_mode_generated_script_name
    current_script = _read_file_text(script_path) if script_path.exists() else None

    latest_plot: Path | None = None
    captures_dir = plot_mode_dir / "captures"
    if captures_dir.is_dir():
        plot_candidates = [
            candidate
            for candidate in captures_dir.rglob("*")
            if candidate.is_file()
            and candidate.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg", ".pdf"}
        ]
        if plot_candidates:
            latest_plot = max(plot_candidates, key=lambda item: item.stat().st_mtime)

    if current_script is None and latest_plot is None:
        return None

    mtimes: list[float] = [plot_mode_dir.stat().st_mtime]
    if script_path.exists():
        mtimes.append(script_path.stat().st_mtime)
    if latest_plot is not None:
        mtimes.append(latest_plot.stat().st_mtime)
    created_at = _iso_from_timestamp(min(mtimes))
    updated_at = _iso_from_timestamp(max(mtimes))
    plot_type: Literal["svg", "raster"] | None = None
    if latest_plot is not None:
        plot_type = "svg" if latest_plot.suffix.lower() == ".svg" else "raster"

    state = PlotModeState(
        id=plot_mode_dir.name,
        is_workspace=True,
        phase=PlotModePhase.ready
        if latest_plot is not None
        else PlotModePhase.awaiting_prompt,
        workspace_dir=str(plot_mode_dir.resolve()),
        current_script=current_script,
        current_script_path=str(script_path) if script_path.exists() else None,
        current_plot=str(latest_plot) if latest_plot is not None else None,
        plot_type=plot_type,
        created_at=created_at,
        updated_at=updated_at,
    )
    _ensure_plot_mode_workspace_name(state)
    return state


def _load_plot_mode_snapshot() -> PlotModeState | None:
    active_state = _load_plot_mode_state_from_path(_plot_mode_snapshot_path())
    if active_state is not None:
        return active_state

    candidates: list[PlotModeState] = []
    for child in _plot_mode_root_dir().iterdir():
        if not child.is_dir():
            continue
        state = _load_plot_mode_state_from_path(
            child / _plot_mode_workspace_snapshot_file_name
        )
        if state is None:
            state = _infer_plot_mode_state_from_artifacts_dir(child)
        if state is not None and _plot_mode_is_workspace(state):
            candidates.append(state)

    if not candidates:
        return None

    latest_state = max(candidates, key=_plot_mode_sort_key)
    _save_plot_mode_snapshot(latest_state)
    return latest_state


def _load_all_plot_mode_workspaces() -> list[PlotModeState]:
    """Load all persisted plot-mode workspaces from disk (not just the active one)."""
    workspaces: list[PlotModeState] = []
    for child in _plot_mode_root_dir().iterdir():
        if not child.is_dir():
            continue
        state = _load_plot_mode_state_from_path(
            child / _plot_mode_workspace_snapshot_file_name
        )
        if state is None:
            state = _infer_plot_mode_state_from_artifacts_dir(child)
        if state is not None and _plot_mode_is_workspace(state):
            workspaces.append(state)
    return workspaces


def _load_plot_mode_workspace_by_id(
    plot_mode_id: str,
) -> PlotModeState | None:
    """Load a specific plot-mode workspace by ID from disk."""
    snapshot_path = _plot_mode_workspace_snapshot_path_for_id(plot_mode_id)
    state = _load_plot_mode_state_from_path(snapshot_path)
    if state is not None:
        return state
    artifacts_dir = _plot_mode_artifacts_path_for_id(plot_mode_id)
    return _infer_plot_mode_state_from_artifacts_dir(artifacts_dir)


def _resolve_plot_mode_workspace(
    workspace_id: str | None,
    *,
    create_if_missing: bool = False,
) -> PlotModeState:
    normalized_workspace_id = (workspace_id or "").strip()
    active_plot_mode = _runtime_plot_mode_state_value()
    if normalized_workspace_id:
        if (
            active_plot_mode is not None
            and active_plot_mode.id == normalized_workspace_id
        ):
            return active_plot_mode
        state = _load_plot_mode_workspace_by_id(normalized_workspace_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail=f"Plot-mode workspace not found: {normalized_workspace_id}",
            )
        return state

    if create_if_missing:
        return active_plot_mode or init_plot_mode_session(
            workspace_dir=_runtime_workspace_dir()
        )

    return _get_plot_mode_state()


def _is_internal_plot_mode_workspace_dir(path: Path) -> bool:
    resolved_path = path.resolve()
    plot_mode_root = _plot_mode_root_dir().resolve()
    try:
        resolved_path.relative_to(plot_mode_root)
        return True
    except ValueError:
        return False


def _common_parent_dir(paths: list[Path]) -> Path | None:
    resolved_dirs: list[Path] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        resolved_dirs.append(resolved if resolved.is_dir() else resolved.parent)

    if not resolved_dirs:
        return None

    try:
        return Path(os.path.commonpath([str(path) for path in resolved_dirs])).resolve()
    except ValueError:
        return resolved_dirs[0]


def _plot_mode_picker_base_dir(state: PlotModeState) -> Path:
    candidate_paths: list[Path] = []

    current_script_path = (state.current_script_path or "").strip()
    if current_script_path:
        candidate_paths.append(Path(current_script_path))

    for file in state.files:
        stored_path = file.stored_path.strip()
        if stored_path:
            candidate_paths.append(Path(stored_path))

    preferred_dir = _common_parent_dir(candidate_paths)
    if preferred_dir is not None:
        return preferred_dir

    workspace_dir = Path(state.workspace_dir).resolve()
    if _is_internal_plot_mode_workspace_dir(workspace_dir):
        return Path.home().resolve()

    return workspace_dir


def _plot_mode_workspace_base_dir(workspace_id: str | None) -> Path:
    normalized_workspace_id = (workspace_id or "").strip()
    if normalized_workspace_id:
        return _plot_mode_picker_base_dir(
            _resolve_plot_mode_workspace(normalized_workspace_id)
        )
    if _plot_mode is not None:
        return _plot_mode_picker_base_dir(_plot_mode)
    fallback_dir = _workspace_dir.resolve()
    if _is_internal_plot_mode_workspace_dir(fallback_dir):
        return Path.home().resolve()
    return fallback_dir


def _delete_plot_mode_snapshot(
    *,
    state: PlotModeState | None = None,
    clear_active_snapshot: bool = True,
) -> None:
    if clear_active_snapshot:
        _plot_mode_snapshot_path().unlink(missing_ok=True)
    if state is None:
        return
    _plot_mode_workspace_snapshot_path(state).unlink(missing_ok=True)
    shutil.rmtree(_plot_mode_artifacts_path_for_id(state.id), ignore_errors=True)


def _touch_plot_mode(state: PlotModeState) -> None:
    if _plot_mode_has_user_content(state):
        _promote_plot_mode_workspace(state)
    _ensure_plot_mode_workspace_name(state)
    state.updated_at = _now_iso()
    if _plot_mode_is_workspace(state):
        _save_plot_mode_snapshot(state)


def _new_plot_mode_state(
    *, workspace_dir: Path | None = None, is_workspace: bool = False
) -> PlotModeState:
    if workspace_dir is None:
        workspace_dir = _plot_mode_root_dir() / _new_id()
    workspace = workspace_dir.resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    preferred_runner, preferred_model, preferred_variant = _load_fix_preferences()
    preferred_runner = _resolve_available_runner(preferred_runner)
    state = PlotModeState(
        is_workspace=is_workspace,
        workspace_dir=str(workspace),
        selected_runner=preferred_runner,
        selected_model=preferred_model or _runner_default_model_id(preferred_runner),
        selected_variant=preferred_variant or "",
    )
    _ensure_plot_mode_workspace_name(state)
    _plot_mode_captures_dir(state)
    return state


def init_plot_mode_session(
    *, workspace_dir: str | Path | None = None, persist_workspace: bool = False
) -> PlotModeState:
    """Initialise plot mode state (no script/image selected yet)."""
    global _plot_mode

    _ensure_session_store_loaded()

    resolved_workspace: Path | None = None
    if workspace_dir is not None:
        resolved_workspace = Path(workspace_dir).resolve()

    if _plot_mode is not None:
        _clear_plot_mode_state()

    _plot_mode = _new_plot_mode_state(
        workspace_dir=resolved_workspace,
        is_workspace=persist_workspace,
    )
    if persist_workspace:
        _save_plot_mode_snapshot(_plot_mode)
    set_workspace_dir(Path(_plot_mode.workspace_dir))
    _set_active_session(None, clear_plot_mode=False)
    return _plot_mode


def _get_plot_mode_state() -> PlotModeState:
    active_plot_mode = _runtime_plot_mode_state_value()
    if active_plot_mode is None:
        raise HTTPException(status_code=404, detail="Plot mode is not active")
    return active_plot_mode


def _clear_plot_mode_state() -> None:
    global _plot_mode
    existing = _plot_mode
    _plot_mode = None

    if existing is not None and _plot_mode_is_workspace(existing):
        # Preserve non-empty workspaces: keep workspace.json and artifacts,
        # only remove the active.json pointer.
        _plot_mode_snapshot_path().unlink(missing_ok=True)
    else:
        _delete_plot_mode_snapshot(state=existing)


def _reset_plot_mode_runtime_state() -> None:
    global _plot_mode
    _plot_mode = None


def _resolve_local_picker_path(raw_path: str, *, base_dir: Path | None = None) -> Path:
    resolved_base_dir = (base_dir or _workspace_dir).resolve()
    text = raw_path.strip()
    if not text:
        return resolved_base_dir

    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (resolved_base_dir / candidate).resolve()


def _picker_parent_and_fragment(
    raw_query: str,
    *,
    base_dir: Path | None = None,
) -> tuple[Path, str]:
    resolved_base_dir = (base_dir or _workspace_dir).resolve()
    query = raw_query.strip()
    if not query:
        return resolved_base_dir, ""

    normalized = query.replace("\\", "/")
    resolved = _resolve_local_picker_path(query, base_dir=resolved_base_dir)
    if normalized.endswith("/"):
        return resolved, ""
    return resolved.parent, resolved.name


def _display_picker_path(path: Path, *, as_dir: bool) -> str:
    resolved = path.expanduser().resolve()
    home = Path.home().resolve()

    try:
        relative_to_home = resolved.relative_to(home)
        if str(relative_to_home) == ".":
            display = "~"
        else:
            display = f"~/{relative_to_home.as_posix()}"
    except ValueError:
        display = resolved.as_posix()

    if as_dir and not display.endswith("/"):
        return f"{display}/"
    return display


def _is_fuzzy_subsequence(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    index = 0
    for char in haystack:
        if char == needle[index]:
            index += 1
            if index == len(needle):
                return True
    return False


def _path_suggestion_score(name: str, fragment: str) -> int | None:
    if not fragment:
        return 0

    lower_name = name.lower()
    lower_fragment = fragment.lower()

    if lower_name.startswith(lower_fragment):
        return 0

    contains_index = lower_name.find(lower_fragment)
    if contains_index != -1:
        return 10 + contains_index

    if _is_fuzzy_subsequence(lower_fragment, lower_name):
        return 100 + len(lower_name)

    return None


def _list_path_suggestions(
    *,
    query: str,
    selection_type: str,
    base_dir: Path | None = None,
    limit: int = 120,
) -> tuple[Path, list[dict[str, object]]]:
    parent_dir, fragment = _picker_parent_and_fragment(query, base_dir=base_dir)
    if not parent_dir.is_dir():
        return parent_dir, []

    show_hidden = fragment.startswith(".")
    ranked: list[tuple[int, int, str, dict[str, object]]] = []
    try:
        entries = list(parent_dir.iterdir())
    except OSError:
        return parent_dir, []

    for entry in entries:
        name = entry.name
        if not show_hidden and name.startswith("."):
            continue

        try:
            is_dir = entry.is_dir()
            is_file = entry.is_file()
        except OSError:
            continue

        if not is_dir and not is_file:
            continue

        if is_file:
            suffix = entry.suffix.lower()
            if selection_type == "script" and suffix != ".py":
                continue
            if selection_type == "data" and suffix == ".py":
                continue

        score = _path_suggestion_score(name, fragment)
        if score is None:
            continue

        resolved_entry = entry.resolve()
        ranked.append(
            (
                score,
                0 if is_dir else 1,
                name.lower(),
                {
                    "path": str(resolved_entry),
                    "display_path": _display_picker_path(resolved_entry, as_dir=is_dir),
                    "is_dir": is_dir,
                    "is_file": is_file,
                },
            )
        )

    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    suggestions = [item[3] for item in ranked[:limit]]
    return parent_dir, suggestions


def _resolve_selected_file_path(
    *,
    raw_path: str,
    selection_type: str,
    base_dir: Path | None = None,
) -> Path:
    normalized = raw_path.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="File path cannot be empty")

    resolved = _resolve_local_picker_path(normalized, base_dir=base_dir)
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=422, detail=f"File not found: {resolved}")

    suffix = resolved.suffix.lower()
    if selection_type == "script" and suffix != ".py":
        raise HTTPException(
            status_code=422,
            detail=f"Script selection requires a .py file: {resolved}",
        )
    if selection_type == "data" and suffix == ".py":
        raise HTTPException(
            status_code=422,
            detail=(
                "Data-file selection does not accept .py scripts. "
                "Use selection_type='script' for Python files."
            ),
        )

    return resolved.resolve()


def _append_plot_mode_message(
    state: PlotModeState,
    *,
    role: Literal["user", "assistant", "error"],
    content: str,
    metadata: PlotModeMessageMetadata | None = None,
) -> None:
    text = content.strip()
    if not text and metadata is None:
        return
    state.messages.append(
        PlotModeChatMessage(role=role, content=text, metadata=metadata)
    )
    _touch_plot_mode(state)


def _create_plot_mode_message(
    state: PlotModeState,
    *,
    role: Literal["user", "assistant", "error"],
    content: str = "",
    metadata: PlotModeMessageMetadata | None = None,
) -> PlotModeChatMessage:
    message = PlotModeChatMessage(role=role, content=content, metadata=metadata)
    state.messages.append(message)
    _touch_plot_mode(state)
    return message


def _remove_plot_mode_message(state: PlotModeState, message_id: str) -> None:
    original_len = len(state.messages)
    state.messages = [message for message in state.messages if message.id != message_id]
    if len(state.messages) != original_len:
        _touch_plot_mode(state)


def _set_plot_mode_message_content(
    state: PlotModeState,
    message: PlotModeChatMessage,
    content: str,
    *,
    final: bool = False,
) -> bool:
    normalized = content.strip() if final else content.lstrip("\n")
    if message.content == normalized:
        return False
    message.content = normalized
    _touch_plot_mode(state)
    return True


def _set_plot_mode_message_metadata(
    state: PlotModeState,
    message: PlotModeChatMessage,
    metadata: PlotModeMessageMetadata | None,
) -> bool:
    if message.metadata == metadata:
        return False
    message.metadata = metadata
    _touch_plot_mode(state)
    return True


def _plot_mode_sandbox_dir(state: PlotModeState) -> Path:
    sandbox_dir = Path(state.workspace_dir) / ".openplot-plot-mode" / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    return sandbox_dir


def _append_plot_mode_activity(
    state: PlotModeState,
    *,
    title: str,
    items: list[str],
) -> None:
    metadata = PlotModeMessageMetadata(
        kind=PlotModeMessageKind.activity,
        title=title,
        items=items,
    )
    _append_plot_mode_message(state, role="assistant", content=title, metadata=metadata)


def _plot_mode_autonomous_focus_direction(pass_index: int) -> str:
    offset = max(pass_index - 2, 0)
    return _plot_mode_autonomous_focus_directions[
        offset % len(_plot_mode_autonomous_focus_directions)
    ]


def _plot_mode_refining_metadata(focus_direction: str) -> PlotModeMessageMetadata:
    return PlotModeMessageMetadata(
        kind=PlotModeMessageKind.status,
        title="Refining plot",
        items=[f"Target: {focus_direction}."],
    )


def _append_plot_mode_table_preview(
    state: PlotModeState,
    *,
    source_label: str,
    caption: str,
    columns: list[str],
    rows: list[list[str]],
) -> None:
    metadata = PlotModeMessageMetadata(
        kind=PlotModeMessageKind.table_preview,
        title=source_label,
        table_columns=columns,
        table_rows=rows,
        table_caption=caption,
        table_source_label=source_label,
    )
    _append_plot_mode_message(
        state, role="assistant", content=caption, metadata=metadata
    )


def _append_plot_mode_question_set(
    state: PlotModeState,
    *,
    question_set: PlotModeQuestionSet,
    lead_content: str,
) -> None:
    state.pending_question_set = question_set
    metadata = PlotModeMessageMetadata(
        kind=PlotModeMessageKind.question,
        title=question_set.title,
        question_set_id=question_set.id,
        question_set_title=question_set.title,
        questions=question_set.questions,
    )
    _append_plot_mode_message(
        state, role="assistant", content=lead_content, metadata=metadata
    )


def _mark_question_set_answered(
    state: PlotModeState,
    question_set_id: str,
    *,
    answered_questions: list[PlotModeQuestionItem],
) -> None:
    for message in reversed(state.messages):
        metadata = message.metadata
        if metadata is None or metadata.kind != PlotModeMessageKind.question:
            continue
        if metadata.question_set_id != question_set_id:
            continue
        metadata.questions = answered_questions
        break
    _touch_plot_mode(state)


def _answer_map_for_question_set(
    body: PlotModeQuestionAnswerRequest,
) -> dict[str, tuple[list[str], str | None]]:
    answers: dict[str, tuple[list[str], str | None]] = {}
    for item in body.answers:
        answers[item.question_id] = (
            [option_id.strip() for option_id in item.option_ids if option_id.strip()],
            (item.text or "").strip() or None,
        )
    return answers


def _apply_answers_to_question_set(
    question_set: PlotModeQuestionSet,
    answer_map: Mapping[str, tuple[list[str], str | None]],
) -> list[PlotModeQuestionItem]:
    answered_questions: list[PlotModeQuestionItem] = []
    for question in question_set.questions:
        option_ids, answer_text = answer_map.get(question.id, ([], None))
        answered_questions.append(
            question.model_copy(
                update={
                    "answered": bool(option_ids or answer_text),
                    "selected_option_ids": option_ids,
                    "answer_text": answer_text,
                }
            )
        )
    return answered_questions


def _first_answer_for_question_set(
    answered_questions: list[PlotModeQuestionItem],
) -> tuple[list[str], str | None]:
    if not answered_questions:
        return [], None
    question = answered_questions[0]
    return question.selected_option_ids, question.answer_text


def _question_set_answer_summary(
    answered_questions: list[PlotModeQuestionItem],
) -> str:
    lines: list[str] = []
    for question in answered_questions:
        if not question.answered:
            continue
        answers: list[str] = []
        if question.selected_option_ids:
            label_by_id = {option.id: option.label for option in question.options}
            answers.extend(
                label_by_id.get(option_id, option_id)
                for option_id in question.selected_option_ids
            )
        if question.answer_text:
            answers.append(question.answer_text)
        if not answers:
            continue
        lines.append(f"- {question.prompt}: {'; '.join(answers)}")
    return "\n".join(lines)


def _stringify_preview_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value)
    if len(text) > 120:
        return text[:117] + "..."
    return text


def _sample_integrity_notes(frame: pd.DataFrame) -> list[str]:
    notes: list[str] = []
    if frame.empty:
        notes.append(
            "The sampled rows are empty, so I need confirmation before drafting a plot."
        )
        return notes

    empty_columns: list[str] = []
    for column in frame.columns:
        series = cast(pd.Series, frame[column])
        if bool(series.isna().all()):
            empty_columns.append(str(column))
    if empty_columns:
        notes.append(
            "The sample includes all-empty columns: " + ", ".join(empty_columns[:5])
        )

    blank_row_count = int(frame.isna().all(axis=1).sum())
    if blank_row_count:
        notes.append(f"The sample includes {blank_row_count} fully empty row(s).")

    duplicate_columns = frame.columns[frame.columns.duplicated()].tolist()
    if duplicate_columns:
        notes.append(
            "Duplicate column labels detected: "
            + ", ".join(str(value) for value in duplicate_columns[:5])
        )

    missing_columns: list[str] = []
    for column in frame.columns:
        series = cast(pd.Series, frame[column])
        if len(series.index) == 0:
            continue
        missing_ratio = float(cast(float, series.isna().mean()))
        if missing_ratio >= 0.5:
            missing_columns.append(f"{column} ({missing_ratio:.0%} missing in sample)")
    if missing_columns:
        notes.append(
            "High missingness in sampled columns: " + ", ".join(missing_columns[:5])
        )

    return notes


def _column_label(index: int) -> str:
    label = ""
    value = index + 1
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        label = chr(65 + remainder) + label
    return label or "A"


def _format_sheet_bounds(bounds: tuple[int, int, int, int]) -> str:
    row_start, row_end, col_start, col_end = bounds
    return (
        f"{_column_label(col_start)}{row_start + 1}:"
        f"{_column_label(col_end)}{row_end + 1}"
    )


def _format_sheet_region_label(
    sheet_name: str | None, bounds: tuple[int, int, int, int] | None
) -> str:
    if bounds is None:
        return sheet_name or "<unknown region>"
    bounds_label = _format_sheet_bounds(bounds)
    if sheet_name:
        return f"{sheet_name}!{bounds_label}"
    return bounds_label


def _normalize_preview_grid(rows: list[list[str]]) -> list[list[str]]:
    width = max((len(row) for row in rows), default=0)
    if width <= 0:
        return []
    return [row + [""] * (width - len(row)) for row in rows]


def _non_empty_cell_count(row: list[str]) -> int:
    return sum(1 for value in row if value.strip())


def _detect_non_empty_blocks(rows: list[list[str]]) -> list[tuple[int, int, int, int]]:
    grid = _normalize_preview_grid(rows)
    if not grid:
        return []

    height = len(grid)
    width = len(grid[0])
    visited = [[False for _ in range(width)] for _ in range(height)]
    bounds_list: list[tuple[int, int, int, int]] = []

    for row_index in range(height):
        for col_index in range(width):
            if visited[row_index][col_index] or not grid[row_index][col_index].strip():
                continue

            queue = [(row_index, col_index)]
            visited[row_index][col_index] = True
            cells: list[tuple[int, int]] = []

            while queue:
                current_row, current_col = queue.pop()
                cells.append((current_row, current_col))
                for next_row, next_col in (
                    (current_row - 1, current_col),
                    (current_row + 1, current_col),
                    (current_row, current_col - 1),
                    (current_row, current_col + 1),
                ):
                    if not (0 <= next_row < height and 0 <= next_col < width):
                        continue
                    if visited[next_row][next_col]:
                        continue
                    if not grid[next_row][next_col].strip():
                        continue
                    visited[next_row][next_col] = True
                    queue.append((next_row, next_col))

            if not cells:
                continue
            min_row = min(row for row, _ in cells)
            max_row = max(row for row, _ in cells)
            min_col = min(col for _, col in cells)
            max_col = max(col for _, col in cells)
            if len(cells) >= 2:
                bounds_list.append((min_row, max_row, min_col, max_col))

    if bounds_list:
        return sorted(bounds_list)

    non_empty_rows = [
        index for index, row in enumerate(grid) if _non_empty_cell_count(row)
    ]
    non_empty_cols = [
        index
        for index in range(width)
        if any(grid[row_index][index].strip() for row_index in range(height))
    ]
    if not non_empty_rows or not non_empty_cols:
        return []
    return [
        (
            non_empty_rows[0],
            non_empty_rows[-1],
            non_empty_cols[0],
            non_empty_cols[-1],
        )
    ]


def _rows_for_bounds(
    rows: list[list[str]], bounds: tuple[int, int, int, int]
) -> list[list[str]]:
    row_start, row_end, col_start, col_end = bounds
    normalized = _normalize_preview_grid(rows)
    sliced = [
        row[col_start : col_end + 1] for row in normalized[row_start : row_end + 1]
    ]
    while sliced and not any(cell.strip() for cell in sliced[-1]):
        sliced.pop()
    while sliced and _non_empty_cell_count(sliced[0]) <= 1 and len(sliced) > 1:
        sliced = sliced[1:]
    return sliced


def _looks_like_numeric_text(value: str) -> bool:
    stripped = value.strip().replace(",", "")
    if not stripped:
        return False
    if stripped.endswith("%"):
        stripped = stripped[:-1]
    try:
        float(stripped)
    except ValueError:
        return False
    return True


def _dataframe_from_block_rows(rows: list[list[str]]) -> pd.DataFrame:
    normalized = _normalize_preview_grid(rows)
    if not normalized:
        return pd.DataFrame()

    first_row = normalized[0]
    non_empty_first_row = [value for value in first_row if value.strip()]
    use_header = bool(non_empty_first_row) and (
        any(any(char.isalpha() for char in value) for value in non_empty_first_row)
        or not all(_looks_like_numeric_text(value) for value in non_empty_first_row)
    )
    if use_header:
        headers: list[str] = []
        seen_headers: set[str] = set()
        for index, value in enumerate(first_row):
            candidate = value.strip() or f"column_{index + 1}"
            deduped = candidate
            suffix = 2
            while deduped in seen_headers:
                deduped = f"{candidate}_{suffix}"
                suffix += 1
            headers.append(deduped)
            seen_headers.add(deduped)
        data_rows = normalized[1:]
        return pd.DataFrame(data_rows, columns=headers)

    headers = [f"column_{index + 1}" for index in range(len(first_row))]
    return pd.DataFrame(normalized, columns=headers)


def _build_data_profile(
    *,
    file_path: Path,
    file_id: str | None,
    source_kind: str,
    source_label: str,
    table_name: str | None,
    frame: pd.DataFrame,
    inferred_bounds: tuple[int, int, int, int] | None = None,
) -> PlotModeDataProfile:
    normalized_frame = frame.head(8).copy()
    normalized_frame = normalized_frame.replace({pd.NA: None})
    preview_rows = [
        [_stringify_preview_value(value) for value in row]
        for row in normalized_frame.to_numpy().tolist()
    ]
    columns = [str(column) for column in normalized_frame.columns.tolist()]
    integrity_notes = _sample_integrity_notes(normalized_frame)
    summary = f"{source_kind.title()} preview with {len(columns)} sampled column(s)" + (
        f" from {table_name}" if table_name else ""
    )
    return PlotModeDataProfile(
        file_path=str(file_path),
        file_name=file_path.name,
        source_label=source_label,
        source_kind=source_kind,
        table_name=table_name,
        summary=summary,
        columns=columns,
        preview_rows=preview_rows,
        integrity_notes=integrity_notes,
        needs_confirmation=source_kind == "excel" or table_name is not None,
        source_file_id=file_id,
        inferred_sheet_name=table_name,
        inferred_bounds=inferred_bounds,
    )


def _build_tabular_region_from_frame(
    *,
    file_path: Path,
    source_kind: str,
    sheet_name: str | None,
    bounds: tuple[int, int, int, int],
    frame: pd.DataFrame,
) -> PlotModeDataRegion:
    normalized_frame = frame.head(8).copy()
    normalized_frame = normalized_frame.replace({pd.NA: None})
    preview_rows = [
        [_stringify_preview_value(value) for value in row]
        for row in normalized_frame.to_numpy().tolist()
    ]
    columns = [str(column) for column in normalized_frame.columns.tolist()]
    bounds_label = _format_sheet_bounds(bounds)
    source_label = file_path.name
    if sheet_name:
        source_label = f"{file_path.name} - {sheet_name} ({bounds_label})"
    else:
        source_label = f"{file_path.name} ({bounds_label})"
    summary = f"Sampled {source_kind} table from {bounds_label}" + (
        f" on {sheet_name}" if sheet_name else ""
    )
    return PlotModeDataRegion(
        sheet_name=sheet_name,
        source_label=source_label,
        summary=summary,
        bounds=_sheet_bounds_from_tuple(bounds),
        columns=columns,
        preview_rows=preview_rows,
    )


def _build_data_profile_from_grid(
    *,
    file_path: Path,
    file_id: str,
    source_kind: str,
    sheet_name: str | None,
    bounds: tuple[int, int, int, int],
    rows: list[list[str]],
) -> PlotModeDataProfile:
    frame = _dataframe_from_block_rows(_rows_for_bounds(rows, bounds))
    tabular_region = _build_tabular_region_from_frame(
        file_path=file_path,
        source_kind=source_kind,
        sheet_name=sheet_name,
        bounds=bounds,
        frame=frame,
    )
    profile = _build_data_profile(
        file_path=file_path,
        file_id=file_id,
        source_kind=source_kind,
        source_label=tabular_region.source_label,
        table_name=sheet_name,
        frame=frame,
        inferred_bounds=bounds,
    )
    profile.summary = tabular_region.summary
    profile.needs_confirmation = True
    profile.tabular_regions = [tabular_region]
    return profile


def _build_grouped_data_profile_from_regions(
    *,
    file_path: Path,
    file_id: str,
    source_kind: str,
    region_profiles: list[PlotModeDataProfile],
) -> PlotModeDataProfile:
    if not region_profiles:
        raise ValueError("At least one region profile is required.")
    if len(region_profiles) == 1:
        return region_profiles[0]

    tabular_regions = [
        region
        for profile in region_profiles
        for region in (profile.tabular_regions or [])
    ]
    if not tabular_regions:
        return region_profiles[0]

    sheet_names = sorted(
        {
            region.sheet_name.strip()
            for region in tabular_regions
            if region.sheet_name and region.sheet_name.strip()
        }
    )
    integrity_notes: list[str] = []
    for profile in region_profiles:
        for note in profile.integrity_notes:
            if note not in integrity_notes:
                integrity_notes.append(note)

    region_count = len(tabular_regions)
    sheet_count = len(sheet_names)
    source_label = f"{file_path.name} - {region_count} selected regions"
    summary = f"Sampled {region_count} {source_kind} regions"
    if sheet_count == 1 and sheet_names:
        summary += f" on {sheet_names[0]}"
    elif sheet_count > 1:
        summary += f" across {sheet_count} sheets"

    return PlotModeDataProfile(
        file_path=str(file_path),
        file_name=file_path.name,
        source_label=source_label,
        source_kind=source_kind,
        summary=summary,
        integrity_notes=integrity_notes,
        needs_confirmation=True,
        source_file_id=file_id,
        tabular_regions=tabular_regions,
    )


def _build_sheet_preview(
    *,
    sheet_name: str,
    rows: list[list[str]],
    total_rows: int,
    total_cols: int,
) -> PlotModeSheetPreview:
    bounds_list = _detect_non_empty_blocks(rows)
    candidates = [
        PlotModeSheetCandidate(
            label=f"Candidate {index + 1} ({_format_sheet_bounds(bounds)})",
            bounds=PlotModeSheetBounds(
                row_start=bounds[0],
                row_end=bounds[1],
                col_start=bounds[2],
                col_end=bounds[3],
            ),
            summary=f"Detected non-empty table block in {sheet_name}",
        )
        for index, bounds in enumerate(bounds_list)
    ]
    return PlotModeSheetPreview(
        name=sheet_name,
        total_rows=total_rows,
        total_cols=total_cols,
        preview_rows=_normalize_preview_grid(rows),
        candidate_tables=candidates,
    )


def _read_delimited_grid(
    path: Path, *, delimiter: str
) -> tuple[list[list[str]], int, int]:
    frame = pd.read_csv(
        path,
        sep=delimiter,
        header=None,
        dtype=str,
        keep_default_na=False,
        engine="python",
        on_bad_lines="skip",
    )
    rows = [
        [_stringify_preview_value(value) for value in row]
        for row in frame.to_numpy().tolist()
    ]
    return rows, int(frame.shape[0]), int(frame.shape[1])


def _build_tabular_selector(
    *,
    file: PlotModeFile,
    path: Path,
    source_kind: str,
    sheets: list[PlotModeSheetPreview],
) -> PlotModeTabularSelector:
    return PlotModeTabularSelector(
        file_id=file.id,
        file_path=str(path),
        file_name=path.name,
        source_kind=source_kind,
        sheets=sheets,
        selected_sheet_id=sheets[0].id if sheets else None,
        status_text=(
            f"I found multiple possible tables in {path.name}. Mark one or more regions that belong to the source you want."
        ),
        requires_user_hint=True,
    )


def _overlap_area(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> int:
    row_start = max(first[0], second[0])
    row_end = min(first[1], second[1])
    col_start = max(first[2], second[2])
    col_end = min(first[3], second[3])
    if row_start > row_end or col_start > col_end:
        return 0
    return (row_end - row_start + 1) * (col_end - col_start + 1)


def _bounds_from_sheet_bounds(bounds: PlotModeSheetBounds) -> tuple[int, int, int, int]:
    return bounds.row_start, bounds.row_end, bounds.col_start, bounds.col_end


def _sheet_bounds_from_tuple(bounds: tuple[int, int, int, int]) -> PlotModeSheetBounds:
    return PlotModeSheetBounds(
        row_start=bounds[0],
        row_end=bounds[1],
        col_start=bounds[2],
        col_end=bounds[3],
    )


def _selection_region_key(
    region: PlotModeTabularSelectionRegion,
) -> tuple[str, int, int, int, int]:
    bounds = _bounds_from_sheet_bounds(region.bounds)
    return (region.sheet_id, bounds[0], bounds[1], bounds[2], bounds[3])


def _dedupe_selection_regions(
    regions: list[PlotModeTabularSelectionRegion],
) -> list[PlotModeTabularSelectionRegion]:
    deduped: list[PlotModeTabularSelectionRegion] = []
    seen: set[tuple[str, int, int, int, int]] = set()
    for region in regions:
        key = _selection_region_key(region)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(region)
    return deduped


def _tabular_regions_for_profile(
    profile: PlotModeDataProfile,
) -> list[PlotModeDataRegion]:
    if profile.tabular_regions:
        return profile.tabular_regions
    if profile.inferred_bounds is None:
        return []
    return [
        PlotModeDataRegion(
            sheet_name=profile.inferred_sheet_name,
            source_label=profile.source_label,
            summary=profile.summary,
            bounds=_sheet_bounds_from_tuple(profile.inferred_bounds),
            columns=profile.columns,
            preview_rows=profile.preview_rows,
        )
    ]


def _clip_bounds_to_sheet(
    bounds: tuple[int, int, int, int], *, max_row_index: int, max_col_index: int
) -> tuple[int, int, int, int]:
    row_start = max(0, min(bounds[0], max_row_index))
    row_end = max(0, min(bounds[1], max_row_index))
    col_start = max(0, min(bounds[2], max_col_index))
    col_end = max(0, min(bounds[3], max_col_index))
    if row_end < row_start:
        row_start, row_end = row_end, row_start
    if col_end < col_start:
        col_start, col_end = col_end, col_start
    return row_start, row_end, col_start, col_end


def _expand_bounds(
    bounds: tuple[int, int, int, int],
    *,
    max_row_index: int,
    max_col_index: int,
    row_padding: int = 2,
    col_padding: int = 2,
) -> tuple[int, int, int, int]:
    return _clip_bounds_to_sheet(
        (
            bounds[0] - row_padding,
            bounds[1] + row_padding,
            bounds[2] - col_padding,
            bounds[3] + col_padding,
        ),
        max_row_index=max_row_index,
        max_col_index=max_col_index,
    )


def _compact_cell_text(value: str, *, max_chars: int = 32) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if not compact:
        return ""
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _sheet_excerpt_for_prompt(
    rows: list[list[str]],
    bounds: tuple[int, int, int, int],
    *,
    max_rows: int = 16,
    max_cols: int = 10,
) -> str:
    grid = _normalize_preview_grid(rows)
    if not grid:
        return "<empty sheet>"

    row_indices = list(range(bounds[0], bounds[1] + 1))
    col_indices = list(range(bounds[2], bounds[3] + 1))
    if not row_indices or not col_indices:
        return "<empty selection>"

    if len(row_indices) > max_rows:
        keep = max_rows // 2
        row_indices = row_indices[:keep] + row_indices[-keep:]
    if len(col_indices) > max_cols:
        keep = max_cols // 2
        col_indices = col_indices[:keep] + col_indices[-keep:]

    header = ["#", *(_column_label(index) for index in col_indices)]
    lines = ["\t".join(header)]
    displayed_rows = set(row_indices)
    previous_row: int | None = None

    for row_index in row_indices:
        if previous_row is not None and row_index - previous_row > 1:
            lines.append("...")
        cells = [str(row_index + 1)]
        for col_index in col_indices:
            cells.append(_compact_cell_text(grid[row_index][col_index]) or "-")
        lines.append("\t".join(cells))
        previous_row = row_index

    full_col_indices = list(range(bounds[2], bounds[3] + 1))
    if len(full_col_indices) > len(col_indices):
        hidden = len(full_col_indices) - len(col_indices)
        lines.append(f"... ({hidden} additional column(s) omitted)")
    hidden_rows = (bounds[1] - bounds[0] + 1) - len(displayed_rows)
    if hidden_rows > 0:
        lines.append(f"... ({hidden_rows} additional row(s) omitted)")
    return "\n".join(lines)


def _candidate_summaries_for_prompt(
    sheet: PlotModeSheetPreview, hint_tuple: tuple[int, int, int, int]
) -> list[str]:
    summaries: list[str] = []
    for candidate in sheet.candidate_tables[:8]:
        candidate_bounds = _bounds_from_sheet_bounds(candidate.bounds)
        overlap = _overlap_area(candidate_bounds, hint_tuple)
        summaries.append(
            f"- {candidate.label}: overlap_with_hint={overlap}, summary={candidate.summary or 'detected non-empty region'}"
        )
    return summaries or ["- No candidate table regions were detected."]


def _build_tabular_range_inference_prompt(
    *,
    file_name: str,
    sheet: PlotModeSheetPreview,
    hint_bounds: PlotModeSheetBounds,
    instruction: str | None,
) -> str:
    hint_tuple = _bounds_from_sheet_bounds(hint_bounds)
    max_row_index = len(sheet.preview_rows) - 1
    max_col_index = max((len(row) for row in sheet.preview_rows), default=0) - 1
    surrounding_bounds = _expand_bounds(
        hint_tuple,
        max_row_index=max_row_index,
        max_col_index=max_col_index,
        row_padding=3,
        col_padding=3,
    )
    lines = [
        "You infer the intended spreadsheet table range for OpenPlot.",
        "Return exactly one JSON object between OPENPLOT_TABULAR_RANGE_BEGIN and OPENPLOT_TABULAR_RANGE_END.",
        "Required JSON keys: row_start, row_end, col_start, col_end, rationale, confidence.",
        "Use zero-based inclusive indexes for rows and columns.",
        "Rules:",
        "- Prefer explicit user instructions over structural heuristics.",
        "- Treat the drag selection as a rough hint, but do not widen to unrelated nearby columns just because they are non-empty.",
        "- Stay on the selected sheet and return one contiguous rectangle.",
        "- The proposed rectangle must overlap the user hint.",
        "- If unsure, stay conservative and close to the hint.",
        "",
        f"File: {file_name}",
        f"Sheet: {sheet.name}",
        f"Sheet preview size: {len(sheet.preview_rows)} row(s) x {max_col_index + 1 if max_col_index >= 0 else 0} column(s)",
        f"User hint range: {_format_sheet_bounds(hint_tuple)}",
        f"User instruction: {(instruction or 'None').strip() or 'None'}",
        "",
        "Detected candidate regions:",
        *_candidate_summaries_for_prompt(sheet, hint_tuple),
        "",
        f"Exact hint excerpt ({_format_sheet_bounds(hint_tuple)}):",
        _sheet_excerpt_for_prompt(
            sheet.preview_rows, hint_tuple, max_rows=12, max_cols=8
        ),
        "",
        f"Surrounding context ({_format_sheet_bounds(surrounding_bounds)}):",
        _sheet_excerpt_for_prompt(
            sheet.preview_rows,
            surrounding_bounds,
            max_rows=18,
            max_cols=12,
        ),
        "",
        "Respond with JSON only inside the markers.",
    ]
    return "\n".join(lines)


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        with suppress(ValueError):
            return int(float(stripped))
    return None


def _extract_plot_mode_tabular_range_result(
    text: str,
    *,
    max_row_index: int,
    max_col_index: int,
) -> tuple[tuple[int, int, int, int], str] | None:
    candidate_dicts: list[dict[str, object]] = []
    strict_match = re.search(
        r"OPENPLOT_TABULAR_RANGE_BEGIN\s*(\{.*?\})\s*OPENPLOT_TABULAR_RANGE_END",
        text,
        flags=re.DOTALL,
    )
    if strict_match:
        with suppress(json.JSONDecodeError):
            payload = json.loads(strict_match.group(1))
            if isinstance(payload, dict):
                candidate_dicts.append(cast(dict[str, object], payload))

    with suppress(json.JSONDecodeError):
        payload = json.loads(text.strip())
        if isinstance(payload, dict):
            candidate_dicts.append(cast(dict[str, object], payload))

    candidate_dicts.extend(_json_object_candidates(text))

    for payload in candidate_dicts:
        bounds_payload = _as_record(payload.get("bounds")) or payload
        row_start = _coerce_int(bounds_payload.get("row_start"))
        row_end = _coerce_int(bounds_payload.get("row_end"))
        col_start = _coerce_int(bounds_payload.get("col_start"))
        col_end = _coerce_int(bounds_payload.get("col_end"))
        if None in {row_start, row_end, col_start, col_end}:
            continue
        clipped_bounds = _clip_bounds_to_sheet(
            cast(tuple[int, int, int, int], (row_start, row_end, col_start, col_end)),
            max_row_index=max_row_index,
            max_col_index=max_col_index,
        )
        rationale_parts: list[str] = []
        rationale = _as_string(payload.get("rationale"))
        confidence = _as_string(payload.get("confidence"))
        if rationale:
            rationale_parts.append(rationale)
        if confidence:
            rationale_parts.append(f"Confidence: {confidence}.")
        return clipped_bounds, " ".join(rationale_parts).strip()
    return None


async def _propose_profile_from_selector_hint(
    *,
    state: PlotModeState,
    selector: PlotModeTabularSelector,
    sheet_id: str,
    hint_bounds: PlotModeSheetBounds,
    instruction: str | None,
) -> PlotModeTabularProposalResult:
    sheet = next((sheet for sheet in selector.sheets if sheet.id == sheet_id), None)
    if sheet is None:
        raise HTTPException(status_code=400, detail="Selected sheet is unavailable.")

    hint_tuple = _bounds_from_sheet_bounds(hint_bounds)
    chosen_bounds = hint_tuple
    rationale = "Used your selected hint directly as a conservative range proposal."
    used_agent = False
    max_row_index = len(sheet.preview_rows) - 1
    max_col_index = max((len(row) for row in sheet.preview_rows), default=0) - 1

    if max_row_index >= 0 and max_col_index >= 0:
        runner = _normalize_fix_runner(
            state.selected_runner, default=_default_fix_runner
        )
        try:
            _ensure_runner_is_available(runner)
        except HTTPException:
            runner = ""

        if runner:
            model = str(state.selected_model or "").strip() or _runner_default_model_id(
                cast(FixRunner, runner)
            )
            normalized_variant = (
                str(state.selected_variant).strip() if state.selected_variant else ""
            )
            prompt = _build_tabular_range_inference_prompt(
                file_name=selector.file_name,
                sheet=sheet,
                hint_bounds=hint_bounds,
                instruction=instruction,
            )
            assistant_text, runner_error = await _run_plot_mode_runner_prompt(
                state=state,
                runner=cast(FixRunner, runner),
                prompt=prompt,
                model=model,
                variant=normalized_variant or None,
            )
            if runner_error is None:
                parsed = _extract_plot_mode_tabular_range_result(
                    assistant_text,
                    max_row_index=max_row_index,
                    max_col_index=max_col_index,
                )
                if parsed is not None:
                    proposed_bounds, proposed_rationale = parsed
                    if _overlap_area(proposed_bounds, hint_tuple) > 0:
                        chosen_bounds = proposed_bounds
                        rationale = (
                            proposed_rationale
                            or "Proposed a range from the hint and surrounding sheet context."
                        )
                        used_agent = True

    profile = _build_data_profile_from_grid(
        file_path=Path(selector.file_path),
        file_id=selector.file_id,
        source_kind=selector.source_kind,
        sheet_name=sheet.name,
        bounds=chosen_bounds,
        rows=sheet.preview_rows,
    )
    return PlotModeTabularProposalResult(
        profile=profile,
        rationale=rationale,
        used_agent=used_agent,
    )


def _queue_tabular_range_confirmation(
    state: PlotModeState,
    profile: PlotModeDataProfile,
    *,
    rationale: str,
) -> None:
    tabular_regions = _tabular_regions_for_profile(profile)
    region_labels = [
        _format_sheet_region_label(
            region.sheet_name,
            _bounds_from_sheet_bounds(region.bounds)
            if region.bounds is not None
            else None,
        )
        for region in tabular_regions
    ]
    question_set = PlotModeQuestionSet(
        purpose="confirm_tabular_range",
        title="Confirm inferred regions",
        source_ids=[profile.id],
    )
    if len(region_labels) > 1:
        prompt = "I think the relevant table regions are " + ", ".join(
            f"`{label}`" for label in region_labels
        )
        prompt += "."
    else:
        bounds_label = region_labels[0] if region_labels else profile.source_label
        prompt = f"I think the relevant table range is `{bounds_label}`."
    if rationale.strip():
        prompt = f"{prompt} {rationale.strip()}"
    prompt += " Use this proposal, mark new regions, or type a note to refine it."
    question_set.questions = [
        PlotModeQuestionItem(
            title="Confirm inferred regions",
            prompt=prompt,
            options=[
                PlotModeQuestionOption(
                    id="use_proposed_range",
                    label="Use proposed regions",
                    description="Continue with these inferred spreadsheet regions.",
                    recommended=True,
                ),
                PlotModeQuestionOption(
                    id="adjust_selection",
                    label="Mark new regions",
                    description="Reopen the sheet grid and revise the marked regions.",
                ),
            ],
            allow_custom_answer=True,
        )
    ]
    _append_plot_mode_question_set(
        state, question_set=question_set, lead_content=prompt
    )


def _profile_delimited_file(
    file: PlotModeFile,
    path: Path,
    *,
    delimiter: str,
    source_kind: str,
) -> tuple[list[PlotModeDataProfile], PlotModeTabularSelector | None, list[str]]:
    rows, total_rows, total_cols = _read_delimited_grid(path, delimiter=delimiter)
    sheet_preview = _build_sheet_preview(
        sheet_name=path.name,
        rows=rows,
        total_rows=total_rows,
        total_cols=total_cols,
    )
    if len(sheet_preview.candidate_tables) <= 1:
        if not sheet_preview.candidate_tables:
            return (
                [],
                None,
                [f"Read {path.name}, but did not detect a clear table region."],
            )
        profile = _build_data_profile_from_grid(
            file_path=path,
            file_id=file.id,
            source_kind=source_kind,
            sheet_name=None,
            bounds=_bounds_from_sheet_bounds(sheet_preview.candidate_tables[0].bounds),
            rows=sheet_preview.preview_rows,
        )
        return [profile], None, [f"Read {path.name} and found one likely table."]

    selector = _build_tabular_selector(
        file=file,
        path=path,
        source_kind=source_kind,
        sheets=[sheet_preview],
    )
    return (
        [],
        selector,
        [
            f"Read {path.name} and found {len(sheet_preview.candidate_tables)} candidate tables."
        ],
    )


def _profile_json_file(path: Path) -> list[PlotModeDataProfile]:
    frame = pd.read_json(path, lines=path.suffix.lower() == ".jsonl").head(8)
    return [
        _build_data_profile(
            file_path=path,
            file_id=None,
            source_kind="json",
            source_label=path.name,
            table_name=None,
            frame=frame,
        )
    ]


def _profile_excel_file(
    file: PlotModeFile, path: Path
) -> tuple[list[PlotModeDataProfile], PlotModeTabularSelector | None, list[str]]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    sheets: list[PlotModeSheetPreview] = []
    total_candidates = 0
    non_empty_sheet_count = 0
    try:
        for worksheet in workbook.worksheets[:8]:
            max_row = int(worksheet.max_row or 0)
            max_col = int(worksheet.max_column or 0)
            rows: list[list[str]] = []
            if max_row > 0 and max_col > 0:
                for row in worksheet.iter_rows(
                    min_row=1,
                    max_row=max_row,
                    min_col=1,
                    max_col=max_col,
                    values_only=True,
                ):
                    rows.append([_stringify_preview_value(value) for value in row])
            sheet_preview = _build_sheet_preview(
                sheet_name=worksheet.title,
                rows=rows,
                total_rows=int(worksheet.max_row or len(rows)),
                total_cols=int(worksheet.max_column or (len(rows[0]) if rows else 0)),
            )
            if sheet_preview.candidate_tables:
                non_empty_sheet_count += 1
                total_candidates += len(sheet_preview.candidate_tables)
            sheets.append(sheet_preview)
    finally:
        workbook.close()

    if total_candidates == 1:
        for sheet in sheets:
            if not sheet.candidate_tables:
                continue
            profile = _build_data_profile_from_grid(
                file_path=path,
                file_id=file.id,
                source_kind="excel",
                sheet_name=sheet.name,
                bounds=_bounds_from_sheet_bounds(sheet.candidate_tables[0].bounds),
                rows=sheet.preview_rows,
            )
            return (
                [profile],
                None,
                [f"Read {path.name} and found one likely table on {sheet.name}."],
            )

    visible_sheets = [
        sheet for sheet in sheets if sheet.candidate_tables or sheet.preview_rows
    ]
    if not visible_sheets:
        return (
            [],
            None,
            [f"Read {path.name}, but did not detect a usable worksheet preview."],
        )

    selector = _build_tabular_selector(
        file=file,
        path=path,
        source_kind="excel",
        sheets=visible_sheets,
    )
    return (
        [],
        selector,
        [
            f"Read {path.name} and found {max(total_candidates, non_empty_sheet_count)} possible source tables across workbook sheets."
        ],
    )


def _profile_selected_data_files(
    files: list[PlotModeFile],
) -> tuple[list[PlotModeDataProfile], list[str], PlotModeTabularSelector | None]:
    profiles: list[PlotModeDataProfile] = []
    activity_items: list[str] = []
    selector: PlotModeTabularSelector | None = None
    for file in files:
        path = Path(file.stored_path).resolve()
        suffix = path.suffix.lower()
        try:
            if suffix == ".csv":
                file_profiles, file_selector, file_activity = _profile_delimited_file(
                    file,
                    path,
                    delimiter=",",
                    source_kind="csv",
                )
            elif suffix == ".tsv":
                file_profiles, file_selector, file_activity = _profile_delimited_file(
                    file,
                    path,
                    delimiter="\t",
                    source_kind="tsv",
                )
            elif suffix in {".json", ".jsonl"}:
                file_profiles = _profile_json_file(path)
                file_selector = None
                file_activity = [
                    f"Read {path.name} and sampled {sum(len(profile.preview_rows) for profile in file_profiles)} row(s)."
                ]
            elif suffix in {".xls", ".xlsx"}:
                file_profiles, file_selector, file_activity = _profile_excel_file(
                    file, path
                )
            else:
                file_profiles = []
                file_selector = None
                file_activity = []
        except Exception as exc:
            activity_items.append(
                f"Tried to inspect {path.name}, but preview loading failed: {exc}"
            )
            continue

        activity_items.extend(file_activity)

        if selector is None and file_selector is not None:
            selector = file_selector
        elif file_selector is not None:
            activity_items.append(
                f"{path.name} also needs range selection; resolve one source at a time."
            )

        if file_profiles:
            profiles.extend(file_profiles)
            continue

        if file_selector is not None:
            continue

        activity_items.append(
            f"Registered {path.name}, but automatic preview is unavailable for {suffix or 'this file type'}."
        )
        profiles.append(
            PlotModeDataProfile(
                file_path=str(path),
                file_name=path.name,
                source_label=path.name,
                source_kind="file",
                summary="Unsupported preview type; use the absolute path directly in the plot script.",
                needs_confirmation=True,
                source_file_id=file.id,
            )
        )

    return profiles, activity_items, selector


def _plot_mode_file_kind(file: PlotModeFile) -> str:
    suffix = Path(file.stored_path).suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".tsv":
        return "tsv"
    if suffix in {".xls", ".xlsx"}:
        return "excel"
    if suffix in {".json", ".jsonl"}:
        return "json"
    if suffix == ".txt":
        return "txt"
    return suffix.lstrip(".") or "file"


def _build_plot_mode_input_bundle(
    files: list[PlotModeFile],
) -> PlotModeInputBundle | None:
    if not files:
        return None

    file_kinds: list[str] = []
    for file in files:
        kind = _plot_mode_file_kind(file)
        if kind not in file_kinds:
            file_kinds.append(kind)

    file_count = len(files)
    kind_label = "/".join(file_kinds[:3]) if file_kinds else "file"
    label = f"{file_count} selected file{'s' if file_count != 1 else ''}"
    summary = f"{file_count} {kind_label} file{'s' if file_count != 1 else ''} selected for this workspace."
    return PlotModeInputBundle(
        label=label,
        summary=summary,
        file_ids=[file.id for file in files],
        file_paths=[str(Path(file.stored_path).resolve()) for file in files],
        file_count=file_count,
        file_kinds=file_kinds,
    )


def _resolved_source_kind_for_profile(profile: PlotModeDataProfile) -> str:
    if profile.source_kind == "file":
        return "unstructured_file"
    if len(_tabular_regions_for_profile(profile)) > 1:
        return "multi_region_excel_source"
    if profile.source_kind == "excel" or profile.table_name is not None:
        return "excel_region"
    return "single_file"


def _build_resolved_source_for_profile(
    profile: PlotModeDataProfile,
) -> PlotModeResolvedDataSource:
    return PlotModeResolvedDataSource(
        kind=cast(
            Literal[
                "single_file",
                "multi_file_collection",
                "excel_region",
                "multi_region_excel_source",
                "unstructured_file",
                "mixed_bundle",
            ],
            _resolved_source_kind_for_profile(profile),
        ),
        label=profile.source_label,
        summary=profile.summary,
        file_ids=[profile.source_file_id] if profile.source_file_id else [],
        file_paths=[profile.file_path],
        file_count=1,
        profile_ids=[profile.id],
        columns=profile.columns,
        integrity_notes=profile.integrity_notes,
    )


def _profile_column_signature(profile: PlotModeDataProfile) -> tuple[str, ...]:
    return tuple(
        sorted({column.strip().lower() for column in profile.columns if column.strip()})
    )


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _build_multi_file_collection_source(
    files: list[PlotModeFile],
    profiles: list[PlotModeDataProfile],
) -> PlotModeResolvedDataSource:
    columns = profiles[0].columns[:] if profiles else []
    integrity_notes = _dedupe_preserving_order(
        [note for profile in profiles for note in profile.integrity_notes]
    )
    label = f"{len(files)} CSV files"
    summary = f"Treat these {len(files)} CSV files as one multi-file dataset."
    if columns:
        summary += " Shared columns: " + ", ".join(columns[:6]) + "."
    return PlotModeResolvedDataSource(
        kind="multi_file_collection",
        label=label,
        summary=summary,
        file_ids=[file.id for file in files],
        file_paths=[str(Path(file.stored_path).resolve()) for file in files],
        file_count=len(files),
        profile_ids=[profile.id for profile in profiles],
        columns=columns,
        integrity_notes=integrity_notes,
    )


def _build_mixed_bundle_source(
    files: list[PlotModeFile],
    profiles: list[PlotModeDataProfile],
) -> PlotModeResolvedDataSource:
    kinds = _dedupe_preserving_order([_plot_mode_file_kind(file) for file in files])
    label = f"{len(files)} selected files"
    summary = f"Treat these {len(files)} files as one input bundle until the plotting relationship is clarified."
    if kinds:
        summary += " Source kinds: " + ", ".join(kinds[:6]) + "."
    return PlotModeResolvedDataSource(
        kind="mixed_bundle",
        label=label,
        summary=summary,
        file_ids=[file.id for file in files],
        file_paths=[str(Path(file.stored_path).resolve()) for file in files],
        file_count=len(files),
        profile_ids=[profile.id for profile in profiles],
        columns=_dedupe_preserving_order(
            [column for profile in profiles for column in profile.columns]
        )[:16],
        integrity_notes=_dedupe_preserving_order(
            [note for profile in profiles for note in profile.integrity_notes]
        ),
    )


def _build_plot_mode_resolved_sources(
    files: list[PlotModeFile],
    profiles: list[PlotModeDataProfile],
    selector: PlotModeTabularSelector | None,
) -> tuple[list[PlotModeResolvedDataSource], list[str]]:
    if len(files) > 1 and selector is None:
        signatures = {_profile_column_signature(profile) for profile in profiles}
        if (
            len(profiles) == len(files)
            and profiles
            and all(profile.source_kind == "csv" for profile in profiles)
            and len(signatures) == 1
            and all(signature for signature in signatures)
        ):
            source = _build_multi_file_collection_source(files, profiles)
            return [source], [source.id]

        source = _build_mixed_bundle_source(files, profiles)
        return [source], [source.id]

    return [_build_resolved_source_for_profile(profile) for profile in profiles], []


def _active_resolved_sources(state: PlotModeState) -> list[PlotModeResolvedDataSource]:
    if not state.active_resolved_source_ids:
        return []
    active_ids = set(state.active_resolved_source_ids)
    return [source for source in state.resolved_sources if source.id in active_ids]


def _set_active_resolved_source_for_profile(
    state: PlotModeState,
    profile: PlotModeDataProfile | None,
) -> None:
    if profile is None:
        state.active_resolved_source_ids = []
        return
    for source in state.resolved_sources:
        if profile.id in source.profile_ids:
            state.active_resolved_source_ids = [source.id]
            return
    state.active_resolved_source_ids = []


def _clear_selected_plot_mode_source_context(state: PlotModeState) -> None:
    state.selected_data_profile_id = None
    state.active_resolved_source_ids = []


def _append_active_resolved_source_context(
    lines: list[str],
    state: PlotModeState,
    *,
    heading: str,
) -> None:
    sources = _active_resolved_sources(state)
    if not sources:
        return

    lines.extend(["", heading])
    for source in sources[:4]:
        lines.append(f"- Label: {source.label}")
        lines.append(f"- Kind: {source.kind}")
        if source.summary:
            lines.append(f"- Summary: {source.summary}")
        if source.columns:
            lines.append("- Columns: " + ", ".join(source.columns[:16]))
        if source.file_paths:
            lines.append("- Files:")
            for path in source.file_paths[:_plot_mode_prompt_files_limit]:
                lines.append(f"  - {path}")
            if len(source.file_paths) > _plot_mode_prompt_files_limit:
                remaining = len(source.file_paths) - _plot_mode_prompt_files_limit
                lines.append(f"  - ... and {remaining} more files")
        if source.integrity_notes:
            lines.append("- Integrity notes:")
            for note in source.integrity_notes[:8]:
                lines.append(f"  - {note}")


def _selected_data_profile(state: PlotModeState) -> PlotModeDataProfile | None:
    if state.selected_data_profile_id:
        for profile in state.data_profiles:
            if profile.id == state.selected_data_profile_id:
                return profile
    return None


def _reset_plot_mode_draft(state: PlotModeState) -> None:
    state.current_script = None
    state.current_script_path = None
    state.current_plot = None
    state.plot_type = None
    state.last_error = None


def _append_profile_preview_card(
    state: PlotModeState, profile: PlotModeDataProfile
) -> None:
    tabular_regions = _tabular_regions_for_profile(profile)
    if tabular_regions:
        for index, region in enumerate(tabular_regions[:4]):
            if not region.columns or not region.preview_rows:
                continue
            caption = region.summary
            if index == 0 and profile.integrity_notes:
                caption += " Integrity notes: " + " ".join(profile.integrity_notes[:2])
            _append_plot_mode_table_preview(
                state,
                source_label=region.source_label,
                caption=caption,
                columns=region.columns,
                rows=region.preview_rows,
            )
        return
    if not profile.columns or not profile.preview_rows:
        return
    caption = profile.summary
    if profile.integrity_notes:
        caption += " Integrity notes: " + " ".join(profile.integrity_notes[:2])
    _append_plot_mode_table_preview(
        state,
        source_label=profile.source_label,
        caption=caption,
        columns=profile.columns,
        rows=profile.preview_rows,
    )


def _profile_supports_preview_confirmation(profile: PlotModeDataProfile) -> bool:
    if profile.source_kind == "file":
        return False

    tabular_regions = _tabular_regions_for_profile(profile)
    if tabular_regions:
        return any(region.columns or region.preview_rows for region in tabular_regions)

    return bool(profile.columns or profile.preview_rows)


def _queue_data_preview_confirmation(
    state: PlotModeState, profile: PlotModeDataProfile
) -> None:
    question_set = PlotModeQuestionSet(
        purpose="confirm_data_preview",
        title="Data confirmation",
        source_ids=[profile.id],
    )
    options = [
        PlotModeQuestionOption(
            id="use_preview",
            label="Use this preview",
            description="Continue with this inferred source.",
        )
    ]
    if (
        state.tabular_selector is not None
        and profile.source_file_id == state.tabular_selector.file_id
    ):
        options.append(
            PlotModeQuestionOption(
                id="adjust_selection",
                label="Adjust selection",
                description="Reopen the sheet grid and revise the marked regions.",
            )
        )
    elif len(state.data_profiles) > 1:
        options.append(
            PlotModeQuestionOption(
                id="choose_other_source",
                label="Choose another source",
                description="Go back to the available source previews.",
            )
        )

    if len(_tabular_regions_for_profile(profile)) > 1:
        prompt = f"I sampled `{profile.source_label}` from multiple spreadsheet regions. Does this combined source look right for plotting?"
    else:
        prompt = f"I sampled `{profile.source_label}`. Does this preview look like the source you want to plot?"
    question_set.questions = [
        PlotModeQuestionItem(
            title="Confirm preview",
            prompt=prompt,
            options=options,
            allow_custom_answer=True,
        )
    ]
    _append_plot_mode_question_set(
        state,
        question_set=question_set,
        lead_content=prompt,
    )


def _append_profile_integrity_activity(
    state: PlotModeState, profile: PlotModeDataProfile
) -> None:
    if not profile.integrity_notes:
        return
    _append_plot_mode_activity(
        state,
        title="Integrity check",
        items=[
            *profile.integrity_notes,
            "Source files stay immutable; conservative fixes happen only inside the generated script.",
        ],
    )


def _present_profile_for_confirmation(
    state: PlotModeState, profile: PlotModeDataProfile
) -> None:
    if not _profile_supports_preview_confirmation(profile):
        state.pending_question_set = None
        state.selected_data_profile_id = profile.id
        _set_active_resolved_source_for_profile(state, profile)
        state.phase = PlotModePhase.awaiting_prompt
        _append_plot_mode_message(
            state,
            role="assistant",
            content=(
                f"I registered `{profile.source_label}`, but this file type does not support preview. "
                "I will use its path directly while planning the plot."
            ),
        )
        return

    _append_profile_preview_card(state, profile)
    _append_profile_integrity_activity(state, profile)
    _queue_data_preview_confirmation(state, profile)


def _present_tabular_range_proposal(
    state: PlotModeState,
    profile: PlotModeDataProfile,
    *,
    rationale: str,
) -> None:
    _append_profile_preview_card(state, profile)
    _append_profile_integrity_activity(state, profile)
    _queue_tabular_range_confirmation(state, profile, rationale=rationale)


async def _propose_grouped_profile_from_selector_regions(
    *,
    state: PlotModeState,
    selector: PlotModeTabularSelector,
    selected_regions: list[PlotModeTabularSelectionRegion],
    instruction: str | None,
) -> PlotModeTabularProposalResult:
    normalized_regions = _dedupe_selection_regions(selected_regions)
    if not normalized_regions:
        raise HTTPException(status_code=400, detail="No tabular regions were provided.")

    region_profiles: list[PlotModeDataProfile] = []
    rationale_parts: list[str] = []
    used_agent = False
    for region in normalized_regions:
        proposal = await _propose_profile_from_selector_hint(
            state=state,
            selector=selector,
            sheet_id=region.sheet_id,
            hint_bounds=region.bounds,
            instruction=instruction,
        )
        region_profiles.append(proposal.profile)
        used_agent = used_agent or proposal.used_agent
        if proposal.rationale.strip():
            rationale_parts.append(
                f"{_format_sheet_region_label(region.sheet_name, _bounds_from_sheet_bounds(region.bounds))}: {proposal.rationale.strip()}"
            )

    profile = _build_grouped_data_profile_from_regions(
        file_path=Path(selector.file_path),
        file_id=selector.file_id,
        source_kind=selector.source_kind,
        region_profiles=region_profiles,
    )
    return PlotModeTabularProposalResult(
        profile=profile,
        rationale=" ".join(rationale_parts).strip(),
        used_agent=used_agent,
    )


async def _apply_tabular_range_proposal(
    state: PlotModeState,
    selector: PlotModeTabularSelector,
    *,
    selected_regions: list[PlotModeTabularSelectionRegion],
    instruction: str | None,
    activity_title: str,
) -> None:
    normalized_regions = _dedupe_selection_regions(selected_regions)
    proposal = await _propose_grouped_profile_from_selector_regions(
        state=state,
        selector=selector,
        selected_regions=normalized_regions,
        instruction=instruction,
    )
    profile = proposal.profile
    selector.selected_sheet_id = (
        normalized_regions[-1].sheet_id if normalized_regions else None
    )
    selector.selected_regions = normalized_regions
    selector.inferred_profile_id = profile.id
    selector.requires_user_hint = False

    state.pending_question_set = None
    state.selected_data_profile_id = None
    state.data_profiles = [
        existing
        for existing in state.data_profiles
        if existing.source_file_id != profile.source_file_id
    ]
    state.data_profiles.append(profile)
    state.phase = PlotModePhase.awaiting_data_choice

    tabular_regions = _tabular_regions_for_profile(profile)
    region_labels = [
        _format_sheet_region_label(
            region.sheet_name,
            _bounds_from_sheet_bounds(region.bounds)
            if region.bounds is not None
            else None,
        )
        for region in tabular_regions
    ]
    if len(region_labels) > 1:
        activity_items = [
            "Proposed grouped datasource from: " + ", ".join(region_labels) + ".",
        ]
    else:
        proposal_label = region_labels[0] if region_labels else profile.source_label
        activity_items = [f"Proposed {proposal_label} from your selected hint."]
    if instruction and instruction.strip():
        activity_items.append(f"Used note: {instruction.strip()}")
    if proposal.rationale.strip():
        activity_items.append(proposal.rationale.strip())
    _append_plot_mode_activity(state, title=activity_title, items=activity_items)
    _present_tabular_range_proposal(state, profile, rationale=proposal.rationale)


def _populate_plot_mode_data_messages(state: PlotModeState) -> None:
    profiles, activity_items, selector = _profile_selected_data_files(state.files)
    state.messages = []
    state.input_bundle = _build_plot_mode_input_bundle(state.files)
    state.data_profiles = profiles
    (
        state.resolved_sources,
        state.active_resolved_source_ids,
    ) = _build_plot_mode_resolved_sources(state.files, profiles, selector)
    state.selected_data_profile_id = None
    state.tabular_selector = selector
    state.pending_question_set = None
    state.latest_user_goal = ""
    state.latest_plan_summary = ""
    state.latest_plan_outline = []
    state.latest_plan_plot_type = ""
    state.latest_plan_actions = []
    _reset_plot_mode_draft(state)

    if activity_items:
        _append_plot_mode_activity(state, title="Data inspection", items=activity_items)

    if selector is not None and selector.requires_user_hint:
        state.phase = PlotModePhase.awaiting_data_choice
        _append_plot_mode_message(state, role="assistant", content=selector.status_text)
        return

    if not profiles:
        if state.resolved_sources:
            state.phase = PlotModePhase.awaiting_data_choice
            for source in state.resolved_sources:
                _append_plot_mode_activity(
                    state,
                    title="Source bundle ready",
                    items=[source.summary],
                )
            _queue_plot_mode_bundle_kickoff_question(state)
            return
        state.phase = PlotModePhase.awaiting_prompt
        return

    if len(state.files) > 1 and state.active_resolved_source_ids:
        for profile in profiles:
            _append_profile_preview_card(state, profile)
        for source in _active_resolved_sources(state):
            activity_items = [source.summary]
            if source.columns:
                activity_items.append(
                    "Shared columns: " + ", ".join(source.columns[:8])
                )
            _append_plot_mode_activity(
                state,
                title="Source bundle ready",
                items=activity_items,
            )
        state.phase = PlotModePhase.awaiting_data_choice
        _queue_plot_mode_bundle_kickoff_question(state)
        return

    if len(profiles) == 1:
        state.phase = PlotModePhase.awaiting_data_choice
        _present_profile_for_confirmation(state, profiles[0])
        return

    for profile in profiles[: min(2, len(profiles))]:
        _append_profile_preview_card(state, profile)

    state.selected_data_profile_id = None
    state.phase = PlotModePhase.awaiting_data_choice
    question_set = PlotModeQuestionSet(
        purpose="select_data_source",
        title="Choose a source",
        source_ids=[profile.id for profile in profiles],
    )
    options = [
        PlotModeQuestionOption(
            id=profile.id,
            label=profile.source_label,
            description=(
                ", ".join(profile.columns[:4]) if profile.columns else profile.summary
            ),
        )
        for profile in profiles[:8]
    ]
    question_set.questions = [
        PlotModeQuestionItem(
            title="Available sources",
            prompt="I found several plausible source tables. Which one should I preview?",
            options=options,
            allow_custom_answer=True,
        )
    ]
    _append_plot_mode_question_set(
        state,
        question_set=question_set,
        lead_content="I found several plausible source tables. Which one should I preview?",
    )


def _build_plot_mode_review_prompt(
    state: PlotModeState,
    *,
    iteration_index: int,
    focus_direction: str,
) -> str:
    profile = _selected_data_profile(state)
    lines = [
        "Review and improve the current OpenPlot draft for publication quality.",
        "Preferred response format is OPENPLOT_RESULT_BEGIN/END JSON with summary, script, and optional done boolean.",
        "If the plot is already strong, you may keep the same script and set done=true.",
        "Write the user-facing summary in plain language and avoid internal implementation jargon.",
        f"Autonomous review pass: {iteration_index}",
        f"Current review focus: {focus_direction}.",
    ]
    if profile is not None:
        lines.extend(
            [
                f"Confirmed source: {profile.source_label}",
                f"Source path: {profile.file_path}",
            ]
        )
        for region in _tabular_regions_for_profile(profile)[:8]:
            bounds = _bounds_from_sheet_bounds(region.bounds) if region.bounds else None
            lines.append(
                f"Confirmed region: {_format_sheet_region_label(region.sheet_name, bounds)}"
            )
    else:
        _append_active_resolved_source_context(
            lines,
            state,
            heading="Confirmed datasource(s):",
        )
    if state.current_plot:
        lines.append(f"Latest rendered preview path: {state.current_plot}")
        lines.append(
            "If your runner can inspect local files, use that preview as grounding for typography, spacing, legend placement, and visual polish."
        )
    lines.append(
        "Focus on typography, label clarity, margins, legend placement, and overall visual polish for grant applications or top-conference papers."
    )
    return "\n".join(lines)


async def _broadcast_plot_mode_state(state: PlotModeState) -> None:
    _ensure_plot_mode_workspace_name(state)
    _save_plot_mode_snapshot(state)
    await _broadcast(
        {
            "type": "plot_mode_updated",
            "plot_mode": state.model_dump(mode="json"),
        }
    )


async def _broadcast_plot_mode_message_update(
    state: PlotModeState,
    message: PlotModeChatMessage,
) -> None:
    await _broadcast(
        {
            "type": "plot_mode_message_updated",
            "plot_mode_id": state.id,
            "updated_at": state.updated_at,
            "message": message.model_dump(mode="json"),
        }
    )


def _join_streaming_text(previous: str, incoming: str, *, append: bool = False) -> str:
    if not incoming:
        return previous
    if not previous:
        return incoming
    if append:
        return f"{previous}{incoming}"
    if previous.endswith(incoming):
        return previous
    if incoming.startswith(previous):
        return incoming
    return f"{previous}\n{incoming}"


def _append_profile_region_details(
    lines: list[str], profile: PlotModeDataProfile
) -> None:
    tabular_regions = _tabular_regions_for_profile(profile)
    if not tabular_regions:
        return
    lines.append("- Selected regions:")
    for region in tabular_regions[:8]:
        bounds = (
            _bounds_from_sheet_bounds(region.bounds)
            if region.bounds is not None
            else None
        )
        lines.append(f"  - {_format_sheet_region_label(region.sheet_name, bounds)}")
        if region.columns:
            lines.append("    Columns: " + ", ".join(region.columns[:12]))


def _build_plot_mode_prompt(state: PlotModeState, user_message: str) -> str:
    python_state = _resolve_python_interpreter_state(None)
    resolved_path = str(python_state.get("resolved_path") or "").strip()
    resolved_version = str(python_state.get("resolved_version") or "").strip()
    available_packages_raw = python_state.get("available_packages")
    available_packages = (
        [str(item) for item in available_packages_raw]
        if isinstance(available_packages_raw, list)
        else []
    )

    lines: list[str] = [
        "You are helping OpenPlot generate a complete Python plotting script for publication-quality figures.",
        "",
        "Preferred return format:",
        "- Prefer one JSON object between OPENPLOT_RESULT_BEGIN and OPENPLOT_RESULT_END.",
        '- Preferred keys: {"summary": string, "script": string, "done": boolean}.',
        "- If JSON formatting fails, return exactly one fenced Python block containing the full script.",
        "- The summary should be a short user-facing explanation of what you drafted or improved.",
        "- Write in plain language and avoid implementation jargon.",
        "- If you describe actions or changes, use bullet points or numbered items.",
        "",
        "Script rules:",
        "- Use only local files listed below (absolute paths).",
        "- Do not invent file paths that are not listed.",
        "- Treat the listed source data files as immutable. Never modify them.",
        "- Any data cleaning must happen in-memory inside the generated script.",
        "- Use conservative data-integrity fixes only: drop fully empty rows/columns, normalize headers, parse dates safely, and coerce obvious numeric/date types.",
        "- Do not impute, interpolate, aggregate, or deduplicate unless the user explicitly requested it.",
        "- Produce one figure and save it to 'plot.png'.",
        "- Include imports and executable top-level code.",
        "- Do not request interactive input.",
        "- Never use built-in question tools such as AskUserQuestion or question.",
        "- If user input is absolutely required, return it only in the structured OpenPlot response format requested above so OpenPlot can render a question card.",
        "- Aim for a polished grant-application / top-conference-paper visual standard.",
        "",
        "Python runtime constraints (strict, must follow):",
        f"- Runtime path: {resolved_path or '<unknown>'}",
        f"- Python version: {resolved_version or '<unknown>'}",
        "- Use Python standard library plus third-party packages listed below.",
        "- Treat this list as a strict allowlist for third-party imports.",
        "- Any non-stdlib import not listed is forbidden.",
        "- If a package is unavailable, rewrite using stdlib or listed packages only.",
        "- Do not ask to install packages or change environments.",
        (
            "- Available third-party packages: "
            + (", ".join(available_packages) if available_packages else "<none>")
        ),
    ]

    if state.files:
        lines.append("")
        lines.append("Available data files:")
        for entry in state.files[:_plot_mode_prompt_files_limit]:
            lines.append(f"- {Path(entry.stored_path).resolve()}")
        if len(state.files) > _plot_mode_prompt_files_limit:
            remaining = len(state.files) - _plot_mode_prompt_files_limit
            lines.append(f"- ... and {remaining} more files")

    selected_profile = next(
        (
            profile
            for profile in state.data_profiles
            if profile.id == state.selected_data_profile_id
        ),
        None,
    )
    if selected_profile is not None:
        lines.extend(
            [
                "",
                "Confirmed data source:",
                f"- Label: {selected_profile.source_label}",
                f"- Path: {selected_profile.file_path}",
                f"- Kind: {selected_profile.source_kind}",
            ]
        )
        if selected_profile.table_name:
            lines.append(f"- Table/sheet: {selected_profile.table_name}")
        if selected_profile.columns:
            lines.append(
                "- Sampled columns: " + ", ".join(selected_profile.columns[:16])
            )
        _append_profile_region_details(lines, selected_profile)
        if len(_tabular_regions_for_profile(selected_profile)) > 1:
            lines.append(
                "- Treat the listed regions as one logical datasource assembled from multiple sheet/range fragments."
            )
        if selected_profile.integrity_notes:
            lines.append("- Integrity notes:")
            for note in selected_profile.integrity_notes[:8]:
                lines.append(f"  - {note}")
    else:
        _append_active_resolved_source_context(
            lines,
            state,
            heading="Confirmed datasource(s):",
        )

    if state.current_script:
        lines.extend(
            [
                "",
                "Current script to refine:",
                state.current_script.rstrip(),
            ]
        )

    lines.extend(
        [
            "",
            f"Execution mode: {state.execution_mode.value}",
            f"Latest approved plotting goal: {state.latest_user_goal or user_message.strip()}",
        ]
    )
    lines.extend(["", "User request:", user_message.strip()])
    return "\n".join(lines).strip()


def _build_plot_mode_planning_prompt(state: PlotModeState, user_message: str) -> str:
    profile = _selected_data_profile(state)
    lines: list[str] = [
        "You are planning a publication-quality OpenPlot figure before script generation.",
        "",
        "Planning workflow requirements:",
        "- Inspect selected local data files directly before proposing a plot plan.",
        "- For Excel and complex structures, reason about candidate sheets/tables/ranges.",
        "- Infer the most suitable chart type(s), layout, style direction, and color strategy.",
        "- Include conservative in-script data integrity handling plans when needed.",
        "- Do not generate or return Python code in this phase.",
        "",
        "Preferred response format:",
        "- Return one JSON object between OPENPLOT_PLAN_BEGIN and OPENPLOT_PLAN_END.",
        "- Suggested keys: summary, plot_type, data_actions, plan_outline, questions, question_purpose, clarification_question, ready_to_plot.",
        "- If formatting fails, return plain text; OpenPlot will attempt recovery.",
        "- Use plain language for the summary and questions; avoid implementation jargon.",
        "- Write any action list as bullet points or numbered items.",
        "- If you need user input or approval, return one or more questions. Each question should have prompt, options, allow_custom_answer, and multiple.",
        "- Keep the JSON keys literal: use prompt and options, not question or choices.",
        "- Each options entry should be either a string label or an object with label plus optional id, description, and recommended.",
        "- Never use built-in question tools such as AskUserQuestion or question.",
        "- Do not ask the user for missing inputs in free-form prose alone. Put every user-facing choice into the questions array so OpenPlot can render an interactive question card.",
        "- When asking a question, propose 2-5 discrete options first whenever possible, then allow a custom answer only as a fallback.",
        "- Use question_purpose='continue_plot_planning' when you need more user input before drafting.",
        "- Use question_purpose='approve_plot_plan' when the plan is ready and you want permission to start drafting.",
    ]

    if state.files:
        lines.append("")
        lines.append("Available data files:")
        for entry in state.files[:_plot_mode_prompt_files_limit]:
            lines.append(f"- {Path(entry.stored_path).resolve()}")
        if len(state.files) > _plot_mode_prompt_files_limit:
            remaining = len(state.files) - _plot_mode_prompt_files_limit
            lines.append(f"- ... and {remaining} more files")

    if profile is not None:
        lines.extend(
            [
                "",
                "Current selected source:",
                f"- {profile.source_label}",
                f"- Path: {profile.file_path}",
            ]
        )
        if profile.table_name:
            lines.append(f"- Sheet/table hint: {profile.table_name}")
        if profile.columns:
            lines.append("- Previewed columns: " + ", ".join(profile.columns[:16]))
        _append_profile_region_details(lines, profile)
        if len(_tabular_regions_for_profile(profile)) > 1:
            lines.append(
                "- Treat the listed regions as one logical datasource assembled from multiple sheet/range fragments."
            )
        if profile.integrity_notes:
            lines.append("- Preview integrity notes:")
            for note in profile.integrity_notes[:8]:
                lines.append(f"  - {note}")
    else:
        _append_active_resolved_source_context(
            lines,
            state,
            heading="Confirmed datasource(s):",
        )

    if state.latest_plan_summary:
        lines.extend(
            [
                "",
                "Latest plan summary:",
                state.latest_plan_summary,
            ]
        )
        if state.latest_plan_outline:
            lines.append("Latest plan outline:")
            for item in state.latest_plan_outline[:8]:
                lines.append(f"- {item}")

    lines.extend(["", "User message:", user_message.strip()])
    return "\n".join(lines).strip()


def _json_object_candidates(text: str) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            candidates.append(cast(dict[str, object], payload))
    return candidates


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "ready", "done"}:
            return True
        if normalized in {"false", "no", "n", "not_ready", "pending"}:
            return False
    return None


def _plot_mode_plan_result_has_selectable_options(
    result: PlotModePlanResult | None,
) -> bool:
    if result is None or not result.questions:
        return False
    return any(question.options for question in result.questions)


def _suggest_plot_mode_question_options(prompt: str) -> list[PlotModeQuestionOption]:
    normalized = re.sub(r"\s+", " ", prompt).strip().lower()
    if not normalized:
        return []

    def _option(
        option_id: str,
        label: str,
        description: str = "",
        *,
        recommended: bool = False,
    ) -> PlotModeQuestionOption:
        return PlotModeQuestionOption(
            id=option_id,
            label=label,
            description=description,
            recommended=recommended,
        )

    if any(token in normalized for token in ("figure type", "chart type", "plot type")):
        return [
            _option(
                "line_chart",
                "Line chart",
                "Best for ordered or time-based trends.",
                recommended=True,
            ),
            _option(
                "scatter_plot",
                "Scatter plot",
                "Best for relationships between two variables.",
            ),
            _option("bar_chart", "Bar chart", "Best for category comparisons."),
            _option("heatmap", "Heatmap", "Best for dense matrix-style comparisons."),
            _option("multi_panel", "Multi-panel", "Split related views across panels."),
        ]

    if "data source" in normalized or (
        "source" in normalized
        and any(
            token in normalized
            for token in ("file", "path", "table", "schema", "column")
        )
    ):
        return [
            _option(
                "use_selected_source",
                "Use selected source",
                "Proceed with the dataset already previewed.",
                recommended=True,
            ),
            _option(
                "choose_another_source",
                "Choose another source",
                "Switch to a different file, sheet, or range.",
            ),
            _option(
                "describe_schema",
                "Describe schema",
                "I will type the columns and units manually.",
            ),
        ]

    if any(
        token in normalized
        for token in ("layout", "single panel", "multi-panel", "shared axes")
    ):
        return [
            _option(
                "single_panel", "Single panel", "One main chart only.", recommended=True
            ),
            _option("two_panel", "1x2 panels", "Two related panels side by side."),
            _option(
                "small_multiples",
                "2x2 small multiples",
                "Compare several facets at once.",
            ),
            _option(
                "custom_layout",
                "Custom layout",
                "I will describe the panel arrangement.",
            ),
        ]

    if any(
        token in normalized
        for token in ("axes", "x/y", "scales", "ranges", "transforms")
    ):
        return [
            _option(
                "use_default_axes",
                "Use obvious x/y mapping",
                "Infer the clearest x and y variables from the data.",
                recommended=True,
            ),
            _option(
                "linear_scales",
                "Keep linear scales",
                "Avoid log transforms unless clearly needed.",
            ),
            _option(
                "allow_log_scale",
                "Allow log scaling",
                "Use log scaling if it improves readability.",
            ),
            _option(
                "custom_axes",
                "I need custom axes",
                "I will specify variables, ranges, or transforms manually.",
            ),
        ]

    if any(
        token in normalized
        for token in (
            "styling",
            "journal",
            "venue style",
            "font",
            "palette",
            "line widths",
            "marker styles",
        )
    ):
        return [
            _option(
                "publication_neutral",
                "Publication-neutral",
                "Clean, restrained defaults for papers.",
                recommended=True,
            ),
            _option(
                "presentation_bold",
                "Presentation-forward",
                "Higher contrast and larger labels for slides.",
            ),
            _option(
                "print_safe",
                "Print-safe monochrome",
                "Works well in grayscale or print.",
            ),
            _option(
                "match_reference_style",
                "Match a reference style",
                "I will point to an example to follow.",
            ),
        ]

    if any(
        token in normalized
        for token in (
            "annotations",
            "legend",
            "error bars",
            "statistical markers",
            "reference lines",
        )
    ):
        return [
            _option(
                "minimal_annotations",
                "Minimal annotations",
                "Only essential labels and a simple legend.",
                recommended=True,
            ),
            _option(
                "full_annotations",
                "Legend and labels",
                "Include fuller explanatory labelling.",
            ),
            _option(
                "uncertainty_annotations",
                "Include uncertainty markers",
                "Add error bars or statistical markers if relevant.",
            ),
            _option(
                "custom_annotations",
                "Custom annotations",
                "I will specify exact callouts or reference lines.",
            ),
        ]

    if any(
        token in normalized
        for token in ("output", "dpi", "file format", "transparent", "background")
    ):
        return [
            _option(
                "vector_output",
                "PDF/SVG vector output",
                "Best for publication workflows.",
                recommended=True,
            ),
            _option("png_output", "High-res PNG", "Best for quick sharing and slides."),
            _option(
                "both_outputs",
                "Both vector and PNG",
                "Export both publication and preview formats.",
            ),
            _option(
                "transparent_bg",
                "Transparent background",
                "Useful for compositing in other layouts.",
            ),
        ]

    if any(
        token in normalized
        for token in (
            "constraint",
            "examples to match",
            "example to match",
            "strict constraints",
        )
    ):
        return [
            _option(
                "no_strict_constraints",
                "No strict constraints",
                "Use best judgment from the dataset and goal.",
                recommended=True,
            ),
            _option(
                "match_example",
                "Match an example",
                "I have a reference figure or house style.",
            ),
            _option(
                "journal_constraints",
                "Journal or brand constraints",
                "Follow explicit formatting requirements.",
            ),
            _option(
                "custom_constraints",
                "Custom constraints",
                "I will describe the limits manually.",
            ),
        ]

    if "audience" in normalized:
        return [
            _option(
                "academic_audience",
                "Academic readers",
                "Optimize for publication-style clarity.",
                recommended=True,
            ),
            _option(
                "executive_audience",
                "Executive audience",
                "Optimize for quick takeaway and contrast.",
            ),
            _option(
                "technical_internal",
                "Technical internal audience",
                "Balance detail and readability.",
            ),
        ]

    if "tone" in normalized:
        return [
            _option(
                "academic_tone", "Academic", "Formal and restrained.", recommended=True
            ),
            _option("executive_tone", "Executive", "Direct and presentation-oriented."),
            _option(
                "exploratory_tone", "Exploratory", "More flexible and analysis-forward."
            ),
        ]

    if any(
        token in normalized
        for token in ("metric matters most", "which metric", "key metric")
    ):
        return [
            _option(
                "trend_focus",
                "Trend over time",
                "Emphasize directional change.",
                recommended=True,
            ),
            _option(
                "comparison_focus",
                "Group comparison",
                "Emphasize differences between categories.",
            ),
            _option(
                "distribution_focus",
                "Distribution or uncertainty",
                "Emphasize spread, range, or variability.",
            ),
            _option(
                "custom_metric_focus",
                "Custom metric",
                "I will specify the main metric.",
            ),
        ]

    if "print or slides" in normalized or (
        "print" in normalized and "slides" in normalized
    ):
        return [
            _option(
                "print_first",
                "Print-first",
                "Optimize for papers or PDFs.",
                recommended=True,
            ),
            _option(
                "slides_first",
                "Slides-first",
                "Optimize for projection and speaking contexts.",
            ),
            _option(
                "balanced_output", "Balanced for both", "Try to work in both settings."
            ),
        ]

    return []


def _extract_structured_plot_mode_result(
    text: str,
) -> tuple[str, str, bool | None] | None:
    candidate_dicts: list[dict[str, object]] = []
    strict_match = re.search(
        r"OPENPLOT_RESULT_BEGIN\s*(\{.*?\})\s*OPENPLOT_RESULT_END",
        text,
        flags=re.DOTALL,
    )
    if strict_match:
        with suppress(json.JSONDecodeError):
            payload = json.loads(strict_match.group(1))
            if isinstance(payload, dict):
                candidate_dicts.append(cast(dict[str, object], payload))

    with suppress(json.JSONDecodeError):
        payload = json.loads(text.strip())
        if isinstance(payload, dict):
            candidate_dicts.append(cast(dict[str, object], payload))

    candidate_dicts.extend(_json_object_candidates(text))

    for payload in candidate_dicts:
        script = payload.get("script")
        if not isinstance(script, str) or not script.strip():
            continue
        summary_value = payload.get("summary")
        summary = (
            summary_value.strip()
            if isinstance(summary_value, str) and summary_value.strip()
            else "Generated plotting script."
        )
        done_hint = _coerce_bool(payload.get("done"))
        if done_hint is None:
            done_hint = _coerce_bool(payload.get("ready"))
        if done_hint is None:
            done_hint = _coerce_bool(payload.get("satisfied"))
        return summary, script.strip(), done_hint

    return None


def _extract_python_script_from_text(text: str) -> str | None:
    fenced_python = re.search(
        r"```python\s*(.*?)```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced_python:
        candidate = fenced_python.group(1).strip()
        if candidate:
            return candidate

    fenced_generic = re.search(r"```\s*(.*?)```", text, flags=re.DOTALL)
    if fenced_generic:
        candidate = fenced_generic.group(1).strip()
        if candidate:
            return candidate

    stripped = text.strip()
    if "\n" in stripped and (
        "import " in stripped
        or "plt." in stripped
        or "fig," in stripped
        or "plot.png" in stripped
    ):
        return stripped
    return None


def _extract_plot_mode_script_result(
    text: str,
) -> tuple[str, str, bool | None] | None:
    structured = _extract_structured_plot_mode_result(text)
    if structured is not None:
        return structured

    script = _extract_python_script_from_text(text)
    if script is None:
        return None

    summary = "Generated plotting script from fallback parsing."
    first_non_code_line = next(
        (
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("```")
        ),
        "",
    )
    if first_non_code_line and "import " not in first_non_code_line:
        summary = first_non_code_line[:240]
    return summary, script, None


def _extract_plot_mode_plan_result(text: str) -> PlotModePlanResult | None:
    def _first_non_empty_string(*values: object) -> str | None:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _strip_option_marker(value: str) -> str:
        return re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+|[A-Za-z][.)]\s+)", "", value).strip()

    def _build_question_option(
        label: str,
        *,
        option_id: object = None,
        description: object = None,
        recommended: object = None,
    ) -> PlotModeQuestionOption:
        normalized_label = _strip_option_marker(label).rstrip(":").strip()
        normalized_id = (
            option_id.strip()
            if isinstance(option_id, str) and option_id.strip()
            else re.sub(r"[^a-z0-9]+", "_", normalized_label.lower()).strip("_")
            or _new_id()
        )
        return PlotModeQuestionOption(
            id=normalized_id,
            label=normalized_label,
            description=description.strip() if isinstance(description, str) else "",
            recommended=bool(recommended is True),
        )

    def _parse_question_options(value: object) -> list[PlotModeQuestionOption]:
        if isinstance(value, str):
            parts: list[str] = []
            if "\n" in value:
                parts = [line.strip() for line in value.splitlines() if line.strip()]
            elif "|" in value:
                parts = [part.strip() for part in value.split("|") if part.strip()]
            elif ";" in value:
                parts = [part.strip() for part in value.split(";") if part.strip()]
            else:
                comma_parts = [
                    part.strip() for part in value.split(",") if part.strip()
                ]
                if len(comma_parts) >= 2:
                    parts = comma_parts
            normalized_parts = [
                _strip_option_marker(part).rstrip(":").strip()
                for part in parts
                if _strip_option_marker(part).rstrip(":").strip()
            ]
            if len(normalized_parts) >= 2:
                return [_build_question_option(part) for part in normalized_parts]
            return []

        if not isinstance(value, list):
            return []

        options: list[PlotModeQuestionOption] = []
        for option_entry in value:
            if isinstance(option_entry, str) and option_entry.strip():
                options.append(_build_question_option(option_entry))
                continue
            if not isinstance(option_entry, dict):
                continue
            label_value = _first_non_empty_string(
                option_entry.get("label"),
                option_entry.get("text"),
                option_entry.get("title"),
                option_entry.get("name"),
                option_entry.get("option"),
                option_entry.get("value"),
            )
            if label_value is None:
                continue
            options.append(
                _build_question_option(
                    label_value,
                    option_id=(
                        option_entry.get("id")
                        if option_entry.get("id") is not None
                        else option_entry.get("value")
                    ),
                    description=_first_non_empty_string(
                        option_entry.get("description"),
                        option_entry.get("details"),
                        option_entry.get("reason"),
                        option_entry.get("summary"),
                    ),
                    recommended=(
                        option_entry.get("recommended")
                        if option_entry.get("recommended") is not None
                        else option_entry.get("default")
                    ),
                )
            )
        return options

    def _extract_inline_question_options(
        prompt: str,
    ) -> tuple[str, list[PlotModeQuestionOption]]:
        match = re.match(
            r"^(.*?)(?:\s+|\s*[-:]\s*)(?:options?|choices?|answers?)\s*:\s*(.+)$",
            prompt.strip(),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return prompt.strip(), []

        prompt_text = match.group(1).strip().rstrip(":")
        option_text = match.group(2).strip()
        if "?" not in prompt_text and not re.search(
            r"\b(which|what|would you like|should i|do you want|choose|select|pick|confirm)\b",
            prompt_text,
            flags=re.IGNORECASE,
        ):
            return prompt.strip(), []
        return prompt_text or prompt.strip(), _parse_question_options(option_text)

    candidate_dicts: list[dict[str, object]] = []
    strict_match = re.search(
        r"OPENPLOT_PLAN_BEGIN\s*(\{.*?\})\s*OPENPLOT_PLAN_END",
        text,
        flags=re.DOTALL,
    )
    if strict_match:
        with suppress(json.JSONDecodeError):
            payload = json.loads(strict_match.group(1))
            if isinstance(payload, dict):
                candidate_dicts.append(cast(dict[str, object], payload))

    with suppress(json.JSONDecodeError):
        payload = json.loads(text.strip())
        if isinstance(payload, dict):
            candidate_dicts.append(cast(dict[str, object], payload))

    candidate_dicts.extend(_json_object_candidates(text))

    for payload in candidate_dicts:
        summary_value = payload.get("summary")
        if not isinstance(summary_value, str) or not summary_value.strip():
            continue
        plot_type_value = payload.get("plot_type")
        plot_type = ""
        if isinstance(plot_type_value, str) and plot_type_value.strip():
            plot_type = plot_type_value.strip()
        elif isinstance(plot_type_value, dict):
            primary = plot_type_value.get("primary")
            if isinstance(primary, str) and primary.strip():
                plot_type = primary.strip()

        def _string_list(value: object) -> list[str]:
            if not isinstance(value, list):
                return []
            return [
                str(item).strip()
                for item in value
                if isinstance(item, str) and str(item).strip()
            ]

        plan_outline = _string_list(payload.get("plan_outline"))
        if not plan_outline:
            plan_outline = _string_list(payload.get("plan_steps"))

        data_actions = _string_list(payload.get("data_actions"))
        if not data_actions:
            data_actions = _string_list(payload.get("inspected_sources"))

        questions_raw = payload.get("questions")
        parsed_questions: list[PlotModeQuestionItem] = []
        if isinstance(questions_raw, list):
            for entry in questions_raw:
                if not isinstance(entry, dict):
                    continue
                prompt_value = _first_non_empty_string(
                    entry.get("prompt"),
                    entry.get("question"),
                    entry.get("clarification_question"),
                    entry.get("text"),
                )
                if prompt_value is None:
                    continue
                options_raw = next(
                    (
                        entry.get(key)
                        for key in (
                            "options",
                            "choices",
                            "answers",
                            "suggested_answers",
                            "suggested_options",
                            "selections",
                        )
                        if entry.get(key) is not None
                    ),
                    None,
                )
                options = _parse_question_options(options_raw)
                prompt_text = prompt_value.strip()
                if not options:
                    prompt_text, options = _extract_inline_question_options(prompt_text)
                if not options:
                    options = _suggest_plot_mode_question_options(prompt_text)
                parsed_questions.append(
                    PlotModeQuestionItem(
                        title=(
                            _first_non_empty_string(
                                entry.get("title"),
                                entry.get("label"),
                            )
                        ),
                        prompt=prompt_text,
                        options=options,
                        allow_custom_answer=bool(
                            entry.get(
                                "allow_custom_answer",
                                entry.get("allow_custom", entry.get("freeform", True)),
                            )
                        ),
                        multiple=bool(
                            entry.get("multiple", entry.get("multi_select", False))
                        ),
                    )
                )

        question_purpose_value = payload.get("question_purpose")
        question_purpose = (
            question_purpose_value.strip()
            if isinstance(question_purpose_value, str)
            and question_purpose_value.strip()
            else None
        )

        clarification_question_value = payload.get("clarification_question")
        clarification_question = (
            clarification_question_value.strip()
            if isinstance(clarification_question_value, str)
            and clarification_question_value.strip()
            else None
        )

        ready_to_plot = _coerce_bool(payload.get("ready_to_plot"))
        if ready_to_plot is None:
            ready_to_plot = _coerce_bool(payload.get("approved_to_draft"))
        if ready_to_plot is None:
            ready_to_plot = clarification_question is None

        return PlotModePlanResult(
            assistant_text=text,
            summary=summary_value.strip(),
            plot_type=plot_type,
            plan_outline=plan_outline,
            data_actions=data_actions,
            questions=parsed_questions or None,
            question_purpose=question_purpose,
            clarification_question=clarification_question,
            ready_to_plot=bool(ready_to_plot),
        )

    stripped = text.strip()
    if not stripped:
        return None
    lines = [
        line.strip()
        for line in stripped.splitlines()
        if line.strip()
        and line.strip() not in {"OPENPLOT_PLAN_BEGIN", "OPENPLOT_PLAN_END"}
    ]
    if not lines:
        return None

    def _extract_inline_numbered_items(
        value: str,
    ) -> tuple[str | None, list[str]]:
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized:
            return None, []

        matches = list(
            re.finditer(
                r"(?:(?<=^)|(?<=\s))(\d+[.)])\s+(.+?)(?=(?:\s+\d+[.)]\s+)|$)",
                normalized,
            )
        )
        if len(matches) < 2:
            return None, []

        summary = normalized[: matches[0].start()].strip()
        items = [match.group(2).strip().rstrip(":") for match in matches]
        return summary or None, [item for item in items if item]

    def _extract_option_label(line: str) -> str | None:
        match = re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$", line)
        if not match:
            return None
        label = match.group(1).strip().rstrip(":")
        return label or None

    def _looks_like_prompt(line: str) -> bool:
        normalized = line.strip().lower()
        if not normalized:
            return False
        if "?" in normalized:
            return True
        prompt_markers = (
            "please provide",
            "which ",
            "what ",
            "would you like",
            "should i",
            "do you want",
            "choose ",
            "select ",
            "pick ",
            "let me know",
            "confirm ",
        )
        return any(marker in normalized for marker in prompt_markers)

    inline_summary, inline_numbered_items = _extract_inline_numbered_items(stripped)
    if len(inline_numbered_items) >= 2:
        question_like_items = sum(
            1
            for item in inline_numbered_items
            if "?" in item or ":" in item or _looks_like_prompt(item)
        )
        intro_text = (inline_summary or "").lower()
        intro_requests_answers = any(
            marker in intro_text
            for marker in (
                "please answer",
                "answer these",
                "i need",
                "more input",
                "questions",
                "before script generation",
                "before drafting",
            )
        )
        if intro_requests_answers or question_like_items >= max(
            2, len(inline_numbered_items) - 1
        ):
            return PlotModePlanResult(
                assistant_text=stripped,
                summary=inline_summary or "I need a few details before drafting.",
                plan_outline=[],
                data_actions=[],
                questions=[
                    PlotModeQuestionItem(
                        prompt=item,
                        options=_suggest_plot_mode_question_options(item),
                        allow_custom_answer=True,
                    )
                    for item in inline_numbered_items
                ],
                question_purpose="continue_plot_planning",
                clarification_question=inline_summary,
                ready_to_plot=False,
            )

    option_start_index: int | None = None
    option_labels: list[str] = []
    for index, line in enumerate(lines):
        option_label = _extract_option_label(line)
        if option_label is None:
            if option_start_index is not None:
                break
            continue
        if option_start_index is None:
            option_start_index = index
        option_labels.append(option_label)

    if option_start_index is not None and len(option_labels) >= 2:
        if all(_looks_like_prompt(label) for label in option_labels):
            summary = (
                " ".join(lines[:option_start_index]).strip()
                or "I need a few details before drafting."
            )
            return PlotModePlanResult(
                assistant_text=stripped,
                summary=summary,
                plan_outline=[],
                data_actions=[],
                questions=[
                    PlotModeQuestionItem(
                        prompt=label,
                        options=_suggest_plot_mode_question_options(label),
                        allow_custom_answer=True,
                    )
                    for label in option_labels
                ],
                question_purpose="continue_plot_planning",
                clarification_question=(
                    summary
                    if summary != "I need a few details before drafting."
                    else None
                ),
                ready_to_plot=False,
            )

        prompt_index: int | None = None
        for index in range(option_start_index - 1, -1, -1):
            if _looks_like_prompt(lines[index]):
                prompt_index = index
                break

        if prompt_index is not None:
            prompt = lines[prompt_index].rstrip(" :")
            summary = " ".join(lines[:prompt_index]).strip() or prompt
            return PlotModePlanResult(
                assistant_text=stripped,
                summary=summary,
                plan_outline=[],
                data_actions=[],
                questions=[
                    PlotModeQuestionItem(
                        prompt=prompt,
                        options=[
                            PlotModeQuestionOption(
                                id=(
                                    re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
                                    or _new_id()
                                ),
                                label=label,
                            )
                            for label in option_labels
                        ],
                        allow_custom_answer=True,
                    )
                ],
                question_purpose="continue_plot_planning",
                clarification_question=prompt,
                ready_to_plot=False,
            )

    for index in range(len(lines) - 1, -1, -1):
        if not _looks_like_prompt(lines[index]):
            continue
        prompt = lines[index].rstrip(" :")
        summary = " ".join(lines[:index]).strip() or prompt
        return PlotModePlanResult(
            assistant_text=stripped,
            summary=summary,
            plan_outline=[],
            data_actions=[],
            question_purpose="continue_plot_planning",
            clarification_question=prompt,
            ready_to_plot=False,
        )

    summary = lines[0]
    plan_outline = [
        line.lstrip("- ").strip() for line in lines[1:] if line.startswith("-")
    ]
    return PlotModePlanResult(
        assistant_text=stripped,
        summary=summary,
        plan_outline=plan_outline,
        data_actions=[],
        clarification_question=None,
        ready_to_plot=False,
    )


def _as_record(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return None


def _as_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _as_non_empty_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _read_path(record: dict[str, object], path: str) -> object | None:
    cursor: object = record
    for key in path.split("."):
        current = _as_record(cursor)
        if current is None or key not in current:
            return None
        cursor = current[key]
    return cursor


def _collect_text(value: object, depth: int = 0) -> list[str]:
    if value is None or depth > 4:
        return []

    if isinstance(value, str):
        return [value] if value.strip() else []

    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            lines.extend(_collect_text(item, depth + 1))
        return lines

    if isinstance(value, dict):
        record = cast(dict[str, object], value)
        priority_keys = [
            "text",
            "content",
            "message",
            "output_text",
            "delta",
            "summary",
            "result",
            "error",
        ]
        for key in priority_keys:
            if key in record:
                found = _collect_text(record[key], depth + 1)
                if found:
                    return found

        ignored = {
            "type",
            "id",
            "sessionID",
            "sessionId",
            "messageID",
            "messageId",
            "timestamp",
            "time",
            "tokens",
            "cost",
            "snapshot",
            "reason",
        }
        fallback: list[str] = []
        for key, child in record.items():
            if key in ignored:
                continue
            fallback.extend(_collect_text(child, depth + 1))
        return fallback

    return []


def _join_collected_text(value: object) -> str | None:
    lines = _collect_text(value)
    if not lines:
        return None
    joined = "".join(lines).strip()
    return joined or None


def _extract_runner_session_id_from_event(
    runner: FixRunner,
    parsed: dict[str, object],
) -> str | None:
    candidate_paths: list[str]
    if runner == "codex":
        candidate_paths = [
            "thread_id",
            "threadId",
            "session_id",
            "sessionId",
            "session.id",
        ]
    elif runner == "claude":
        candidate_paths = [
            "session_id",
            "sessionId",
            "session.id",
        ]
    else:
        candidate_paths = [
            "sessionID",
            "sessionId",
            "session_id",
            "session.id",
        ]

    for path in candidate_paths:
        value = _read_path(parsed, path)
        candidate = _normalize_runner_session_id(value)
        if candidate is not None:
            return candidate
    return None


def _extract_runner_session_id_from_output(
    runner: FixRunner,
    output_text: str,
) -> str | None:
    for line in output_text.splitlines():
        parsed = _parse_json_event_line(line)
        if parsed is None:
            continue
        session_id = _extract_runner_session_id_from_event(runner, parsed)
        if session_id is not None:
            return session_id
    return None


def _extract_runner_reported_error(
    runner: FixRunner,
    *,
    stdout_text: str,
    stderr_text: str,
) -> str | None:
    if runner != "claude":
        return None

    for line in stdout_text.splitlines():
        parsed = _parse_json_event_line(line)
        if parsed is None:
            continue

        root_type = (_as_string(parsed.get("type")) or "").lower().replace("_", "-")
        if root_type != "result" or parsed.get("is_error") is not True:
            continue

        for candidate in (parsed.get("result"), parsed.get("error")):
            message = _as_string(candidate)
            if message:
                return message
            if candidate is not None:
                try:
                    return json.dumps(candidate)
                except TypeError:
                    continue

        stderr_message = _as_string(stderr_text)
        if stderr_message:
            return stderr_message
        return "Claude reported an error result"

    return None


def _is_resume_session_error(
    runner: FixRunner,
    *,
    stdout_text: str,
    stderr_text: str,
) -> bool:
    combined = f"{stderr_text}\n{stdout_text}".lower()
    if not combined:
        return False

    runner_keywords: tuple[str, ...]
    if runner == "codex":
        runner_keywords = ("thread", "session", "resume")
    elif runner == "claude":
        runner_keywords = ("session", "conversation", "resume")
    else:
        runner_keywords = ("session", "conversation", "resume")

    if not any(keyword in combined for keyword in runner_keywords):
        return False

    error_markers = (
        "not found",
        "does not exist",
        "doesn't exist",
        "unknown",
        "invalid",
        "expired",
        "failed to resume",
        "unable to resume",
        "cannot resume",
        "context length exceeded",
        "maximum context length",
        "context window",
        "too many tokens",
        "prompt is too long",
        "conversation is too long",
    )
    return any(marker in combined for marker in error_markers)


def _is_rate_limit_error(
    runner: FixRunner,
    *,
    stdout_text: str,
    stderr_text: str,
) -> bool:
    combined = f"{stderr_text}\n{stdout_text}".lower()
    if not combined:
        return False

    rate_limit_markers = (
        "rate_limit",
        "rate limit",
        "ratelimit",
        "too many requests",
        "you've hit your limit",
        "you\u2019ve hit your limit",
        "usage limit",
        "quota exceeded",
        "quota_exceeded",
        "overloaded",
    )

    if any(marker in combined for marker in rate_limit_markers):
        return True

    if runner == "claude":
        if '"status":"rejected"' in f"{stderr_text}\n{stdout_text}":
            return True

    return False


def _format_rate_limit_error(runner: FixRunner) -> str:
    return f"Backend rate limit reached ({runner}). Please wait a few minutes and try again."


def _tool_name_is_builtin_question_tool(name: str | None) -> bool:
    normalized = (name or "").strip().lower().replace("_", "").replace("-", "")
    if not normalized:
        return False
    return normalized in {"askuserquestion", "question"}


def _candidate_tool_names_from_parsed_event(parsed: dict[str, object]) -> list[str]:
    part = _as_record(parsed.get("part")) or parsed
    item = _as_record(parsed.get("item"))
    candidates: list[str] = []
    for candidate in (
        _read_path(parsed, "part.tool_name"),
        _read_path(parsed, "part.toolName"),
        _read_path(parsed, "part.tool"),
        _read_path(parsed, "part.tool.name"),
        _read_path(parsed, "tool_name"),
        _read_path(parsed, "toolName"),
        _read_path(parsed, "tool"),
        _read_path(parsed, "tool.name"),
        _read_path(parsed, "name"),
        _read_path(part, "name"),
        _read_path(item, "tool") if item is not None else None,
        _read_path(item, "name") if item is not None else None,
        _read_path(item, "function.name") if item is not None else None,
    ):
        text = _as_string(candidate)
        if text:
            candidates.append(text)
    return candidates


def _parsed_runner_uses_builtin_question_tool(
    runner: FixRunner, parsed: dict[str, object]
) -> bool:
    if runner == "claude":
        root_type = (_as_string(parsed.get("type")) or "").lower().replace("_", "-")
        if root_type == "stream-event":
            event = _as_record(parsed.get("event"))
            if event is None:
                return False
            event_type = (_as_string(event.get("type")) or "").lower().replace("_", "-")
            if event_type != "content-block-start":
                return False
            content_block = _as_record(event.get("content_block"))
            if content_block is None:
                return False
            block_type = (
                (_as_string(content_block.get("type")) or "").lower().replace("_", "-")
            )
            return block_type == "tool-use" and _tool_name_is_builtin_question_tool(
                _as_string(content_block.get("name"))
            )

        message = _as_record(parsed.get("message"))
        if message is not None and isinstance(message.get("content"), list):
            for block_value in cast(list[object], message.get("content")):
                block = _as_record(block_value)
                if block is None:
                    continue
                block_type = (
                    (_as_string(block.get("type")) or "").lower().replace("_", "-")
                )
                if block_type not in {"tool-use", "tool_use"}:
                    continue
                if _tool_name_is_builtin_question_tool(_as_string(block.get("name"))):
                    return True
        return False

    part = _as_record(parsed.get("part")) or parsed
    event_type = (
        (_as_string(parsed.get("type")) or _as_string(parsed.get("event")) or "")
        .lower()
        .replace("_", "-")
    )
    part_type = (_as_string(part.get("type")) or "").lower().replace("_", "-")
    item = _as_record(parsed.get("item"))
    item_type = (
        ((_as_string(item.get("type")) or "") if item is not None else "")
        .lower()
        .replace("_", "-")
    )
    if "tool" not in event_type and "tool" not in part_type and "tool" not in item_type:
        return False

    return any(
        _tool_name_is_builtin_question_tool(candidate)
        for candidate in _candidate_tool_names_from_parsed_event(parsed)
    )


def _runner_output_used_builtin_question_tool(runner: FixRunner, text: str) -> bool:
    for line in text.splitlines():
        parsed = _parse_json_event_line(line)
        if parsed is None:
            continue
        if _parsed_runner_uses_builtin_question_tool(runner, parsed):
            return True
    return False


def _append_retry_instruction(prompt: str, instruction: str) -> str:
    normalized_instruction = instruction.strip()
    if not normalized_instruction:
        return prompt
    if normalized_instruction in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\nAdditional instruction: {normalized_instruction}"


def _plot_mode_question_tool_retry_instruction() -> str:
    return (
        "The previous attempt tried to use a built-in interactive question tool. "
        "OpenPlot cannot answer built-in runner questions in CLI mode. "
        "Do not use AskUserQuestion or question tools. "
        "If user input is required, return it only in the structured OpenPlot response format requested above so OpenPlot can render a question card."
    )


def _fix_mode_question_tool_retry_instruction() -> str:
    return (
        "The previous attempt tried to use a built-in interactive question tool. "
        "OpenPlot cannot answer built-in runner questions during fix mode. "
        "Do not use AskUserQuestion or question tools. "
        "Do not ask the user for interactive input. "
        "Infer the most conservative interpretation from the current annotation, current script, and existing accepted fixes, then continue."
    )


def _extract_plot_mode_assistant_text(
    parsed: dict[str, object], part: dict[str, object]
) -> str | None:
    candidates = [
        _read_path(part, "text"),
        _read_path(part, "content"),
        _read_path(part, "delta"),
        _read_path(part, "message"),
        _read_path(parsed, "text"),
        _read_path(parsed, "content"),
        _read_path(parsed, "message"),
        _read_path(parsed, "output_text"),
    ]

    for candidate in candidates:
        lines = _collect_text(candidate)
        if lines:
            return "".join(lines).strip()
    return None


def _extract_codex_plot_mode_stream_fragment(
    parsed: dict[str, object],
) -> tuple[str, bool] | None:
    event_type = (
        (_as_string(parsed.get("type")) or _as_string(parsed.get("event")) or "")
        .lower()
        .strip()
    )
    if not event_type.startswith("item."):
        return None

    item = _as_record(parsed.get("item"))
    if item is None:
        return None

    item_type = (_as_string(item.get("type")) or "").lower().strip()
    if item_type != "agent_message":
        return None

    assistant_text = (
        _as_string(item.get("text"))
        or _as_string(_read_path(item, "message"))
        or _as_string(_read_path(item, "output_text"))
        or _join_collected_text(item.get("content"))
        or _join_collected_text(item.get("result"))
    )
    if not assistant_text:
        return None
    return assistant_text, False


def _extract_opencode_plot_mode_stream_fragment(
    parsed: dict[str, object],
) -> tuple[str, bool] | None:
    part = _as_record(parsed.get("part")) or parsed
    event_type_raw = (
        _as_string(parsed.get("type"))
        or _as_string(parsed.get("event"))
        or _as_string(part.get("type"))
        or "event"
    )
    event_type = event_type_raw.lower().replace("_", "-")
    if "error" in event_type or "fail" in event_type or "tool" in event_type:
        return None

    assistant_text = _extract_plot_mode_assistant_text(parsed, part)
    if not assistant_text:
        return None
    return assistant_text, False


def _extract_claude_plot_mode_stream_fragment(
    parsed: dict[str, object],
) -> tuple[str, bool] | None:
    root_type = (_as_string(parsed.get("type")) or "").lower().replace("_", "-")

    if root_type == "stream-event":
        event = _as_record(parsed.get("event"))
        if event is None:
            return None

        event_type = (
            (_as_string(event.get("type")) or "event").lower().replace("_", "-")
        )
        if event_type == "content-block-delta":
            delta = _as_record(event.get("delta"))
            delta_type = (
                (_as_string(delta.get("type")) or "").lower().replace("_", "-")
                if delta
                else ""
            )
            if delta_type == "text-delta":
                text = _as_non_empty_string(delta.get("text")) if delta else None
                if text:
                    return text, True
            return None

        return None

    if root_type == "assistant":
        message = _as_record(parsed.get("message"))
        if message is None:
            return None

        content = message.get("content")
        if not isinstance(content, list):
            return None

        text_parts: list[str] = []
        for block_value in content:
            block = _as_record(block_value)
            if block is None:
                continue
            block_type = (_as_string(block.get("type")) or "").lower().replace("_", "-")
            if block_type != "text":
                continue
            text = _as_non_empty_string(block.get("text")) or _join_collected_text(
                block
            )
            if text:
                text_parts.append(text)

        if text_parts:
            return "".join(text_parts), False
        return None

    message = _as_record(parsed.get("message"))
    content_block = _as_record(parsed.get("content_block"))
    part = _as_record(parsed.get("part")) or content_block or message or parsed
    event_type = (
        (
            _as_string(parsed.get("type"))
            or _as_string(parsed.get("event"))
            or _as_string(part.get("type"))
            or "event"
        )
        .lower()
        .replace("_", "-")
    )
    part_type = (_as_string(part.get("type")) or "").lower().replace("_", "-")
    if "tool" in event_type or "tool" in part_type:
        return None

    assistant_text = (
        _as_string(_read_path(parsed, "delta.text"))
        or _as_string(_read_path(parsed, "content_block.text"))
        or _as_string(_read_path(parsed, "text"))
        or _join_collected_text(_read_path(parsed, "message.content"))
        or _extract_plot_mode_assistant_text(parsed, part)
    )
    if not assistant_text:
        return None
    return assistant_text, False


def _extract_plot_mode_stream_fragment(
    runner: FixRunner,
    parsed: dict[str, object],
) -> tuple[str, bool] | None:
    if runner == "codex":
        return _extract_codex_plot_mode_stream_fragment(parsed)
    if runner == "claude":
        return _extract_claude_plot_mode_stream_fragment(parsed)
    return _extract_opencode_plot_mode_stream_fragment(parsed)


async def _consume_plot_mode_text_stream(
    stream: asyncio.StreamReader | None,
    sink: list[str],
    *,
    runner: FixRunner | None = None,
    process: asyncio.subprocess.Process | None = None,
) -> None:
    if stream is None:
        return

    buffered = ""
    question_tool_seen = False

    while True:
        chunk_bytes = await stream.read(8192)
        if not chunk_bytes:
            break

        chunk = chunk_bytes.decode("utf-8", errors="replace")
        sink.append(chunk)

        if runner is None or process is None or question_tool_seen:
            continue

        buffered += chunk
        while True:
            newline_index = buffered.find("\n")
            if newline_index < 0:
                break
            line = buffered[: newline_index + 1]
            buffered = buffered[newline_index + 1 :]
            parsed = _parse_json_event_line(line)
            if parsed is None:
                continue
            if _parsed_runner_uses_builtin_question_tool(runner, parsed):
                question_tool_seen = True
                await _terminate_fix_process(process)
                break

    if runner is None or process is None or question_tool_seen or not buffered:
        return
    parsed = _parse_json_event_line(buffered)
    if parsed is not None and _parsed_runner_uses_builtin_question_tool(runner, parsed):
        await _terminate_fix_process(process)


def _resolve_plot_mode_final_assistant_text(
    *,
    runner: FixRunner,
    stdout_text: str,
    output_path: Path | None,
) -> str:
    if runner == "codex" and output_path is not None:
        try:
            file_text = _read_file_text(output_path).strip()
        except OSError:
            file_text = ""
        if file_text:
            return file_text

    collected_text = ""
    for line in stdout_text.splitlines():
        parsed = _parse_json_event_line(line)
        if parsed is None:
            continue
        fragment = _extract_plot_mode_stream_fragment(
            runner, cast(dict[str, object], parsed)
        )
        if fragment is None:
            continue
        text, append = fragment
        collected_text = _join_streaming_text(collected_text, text, append=append)
    if collected_text.strip():
        return collected_text.strip()

    raw_stdout = stdout_text.strip()
    if not raw_stdout:
        return ""

    if not any(line.lstrip().startswith("{") for line in raw_stdout.splitlines()):
        return raw_stdout

    return ""


async def _run_plot_mode_runner_prompt(
    *,
    state: PlotModeState,
    runner: FixRunner,
    prompt: str,
    model: str,
    variant: str | None,
) -> tuple[str, str | None]:
    current_resume_session_id = _runner_session_id_for_plot_mode(state, runner)
    current_prompt = prompt
    question_tool_retry_count = 0
    return_code: int | None = None
    stdout_text = ""
    stderr_text = ""
    assistant_text = ""

    while True:
        output_path: Path | None = None
        normalized_resume_session_id = _normalize_runner_session_id(
            current_resume_session_id
        )

        if runner == "codex":
            codex_command = _resolve_command_path("codex")
            if codex_command is None:
                return "", "Failed to launch codex: command not found"
            if normalized_resume_session_id:
                command = [
                    codex_command,
                    "exec",
                    "resume",
                    "--skip-git-repo-check",
                    "--json",
                    "-c",
                    'approval_policy="never"',
                    "--model",
                    model,
                    normalized_resume_session_id,
                ]
            else:
                output_file = tempfile.NamedTemporaryFile(delete=False)
                output_file.close()
                output_path = Path(output_file.name)
                command = [
                    codex_command,
                    "exec",
                    "--cd",
                    str(state.workspace_dir),
                    "--skip-git-repo-check",
                    "--json",
                    "--sandbox",
                    "workspace-write",
                    "-c",
                    'approval_policy="never"',
                    "--model",
                    model,
                    "--output-last-message",
                    str(output_path),
                ]
            normalized_variant = (variant or "").strip()
            if normalized_variant:
                command.extend(
                    [
                        "-c",
                        f"model_reasoning_effort={json.dumps(normalized_variant)}",
                    ]
                )
                command.append(current_prompt)
        elif runner == "claude":
            claude_command = _resolve_claude_cli_command()
            if claude_command is None:
                return "", "Failed to launch claude: command not found"

            command = [
                claude_command,
                "-p",
                current_prompt,
                "--output-format",
                "stream-json",
                "--verbose",
                "--include-partial-messages",
                "--permission-mode",
                "bypassPermissions",
                "--disallowedTools",
                "AskUserQuestion",
                "--model",
                model,
            ]
            if normalized_resume_session_id:
                command.extend(["--resume", normalized_resume_session_id])

            normalized_variant = (variant or "").strip()
            if normalized_variant:
                command.extend(["--effort", normalized_variant])
        else:
            opencode_command = _resolve_command_path("opencode")
            if opencode_command is None:
                return "", "Failed to launch opencode: command not found"
            command = [
                opencode_command,
                "run",
                "--dir",
                str(state.workspace_dir),
                "--format",
                "json",
                "--model",
                model,
            ]
            if normalized_resume_session_id:
                command.extend(["--session", normalized_resume_session_id])
            if variant:
                command.extend(["--variant", variant])
            command.append(current_prompt)

        env_overrides = (
            {
                "OPENCODE_CONFIG_CONTENT": _opencode_question_tool_disabled_config_content()
            }
            if runner == "opencode"
            else None
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(state.workspace_dir),
                env=_subprocess_env(overrides=env_overrides),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **_hidden_window_kwargs(),
                **({"start_new_session": True} if sys.platform != "win32" else {}),
            )
        except OSError as exc:
            if output_path is not None:
                output_path.unlink(missing_ok=True)
            return "", f"Failed to launch {runner}: {exc}"

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        stdout_task = asyncio.create_task(
            _consume_plot_mode_text_stream(
                process.stdout, stdout_chunks, runner=runner, process=process
            )
        )
        stderr_task = asyncio.create_task(
            _consume_plot_mode_text_stream(process.stderr, stderr_chunks)
        )

        try:
            await process.wait()
            results = await asyncio.gather(
                stdout_task,
                stderr_task,
                return_exceptions=True,
            )
            for label, result in (("stdout", results[0]), ("stderr", results[1])):
                if isinstance(result, Exception):
                    stderr_chunks.append(
                        f"[openplot warning] failed to read {label} stream: {result}\n"
                    )
        finally:
            if output_path is not None and runner != "codex":
                output_path.unlink(missing_ok=True)

        return_code = process.returncode
        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)

        discovered_session_id = _extract_runner_session_id_from_output(
            runner, stdout_text
        )
        if discovered_session_id is not None:
            _set_runner_session_id_for_plot_mode(
                state,
                runner=runner,
                session_id=discovered_session_id,
            )

        assistant_text = _resolve_plot_mode_final_assistant_text(
            runner=runner,
            stdout_text=stdout_text,
            output_path=output_path,
        )

        if output_path is not None:
            output_path.unlink(missing_ok=True)

        if _runner_output_used_builtin_question_tool(runner, stdout_text):
            _clear_runner_session_id_for_plot_mode(state, runner)
            if question_tool_retry_count >= 1:
                return assistant_text, (
                    "Runner attempted an unsupported built-in question tool. "
                    "Please try again after clarifying the request in plain language."
                )
            current_resume_session_id = None
            current_prompt = _append_retry_instruction(
                current_prompt, _plot_mode_question_tool_retry_instruction()
            )
            question_tool_retry_count += 1
            continue

        if (
            return_code != 0
            and normalized_resume_session_id
            and _is_resume_session_error(
                runner,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
            )
        ):
            _clear_runner_session_id_for_plot_mode(state, runner)
            current_resume_session_id = None
            continue

        break

    if return_code != 0:
        if _is_rate_limit_error(
            runner, stdout_text=stdout_text, stderr_text=stderr_text
        ):
            return assistant_text, _format_rate_limit_error(runner)
        details = (
            stderr_text.strip()
            or stdout_text.strip()
            or f"{runner} exited with {return_code}"
        )
        return assistant_text, f"Runner request failed: {details}"

    return assistant_text, None


async def _run_plot_mode_generation(
    *,
    state: PlotModeState,
    runner: FixRunner,
    message: str,
    model: str,
    variant: str | None,
    assistant_message: PlotModeChatMessage,
) -> PlotModeGenerationResult:
    _ = assistant_message
    prompt = _build_plot_mode_prompt(state, message)

    for attempt_index in range(1, _plot_mode_execution_retry_limit + 1):
        assistant_text, runner_error = await _run_plot_mode_runner_prompt(
            state=state,
            runner=runner,
            prompt=prompt,
            model=model,
            variant=variant,
        )
        if runner_error is not None:
            return PlotModeGenerationResult(
                assistant_text=assistant_text,
                error_message=runner_error,
            )

        script_result = _extract_plot_mode_script_result(assistant_text)
        if script_result is None:
            prompt = (
                f"{prompt}\n\n"
                "Your previous reply was not usable. Resend either OPENPLOT_RESULT JSON with "
                "summary and script, or one complete fenced python block containing the full script."
            )
            continue

        summary_text, script, done_hint = script_result

        try:
            ast.parse(script)
        except SyntaxError as exc:
            prompt = (
                f"{prompt}\n\n"
                "The previous script had a Python syntax error."
                f"\nError: {exc}\n"
                "Fix the script and resend the full corrected version."
            )
            continue

        script_path = _plot_mode_generated_script_path(state)
        script_path.write_text(script, encoding="utf-8")

        capture_dir = _plot_mode_captures_dir(state) / _new_id()
        capture_dir.mkdir(parents=True, exist_ok=True)
        set_workspace_dir(Path(state.workspace_dir))
        protected_paths = [
            str(Path(file.stored_path).resolve()) for file in state.files
        ]
        execution_result = await asyncio.to_thread(
            execute_script,
            script_path,
            work_dir=_plot_mode_sandbox_dir(state),
            capture_dir=capture_dir,
            python_executable=_resolve_python_executable(None),
            protected_paths=protected_paths,
        )

        if execution_result.success and execution_result.plot_path:
            return PlotModeGenerationResult(
                assistant_text=summary_text,
                script=script,
                execution_result=execution_result,
                done_hint=done_hint,
            )

        failure_parts = [execution_result.error or "Script execution failed"]
        if execution_result.stderr.strip():
            failure_parts.append(execution_result.stderr.strip())
        prompt = (
            f"{prompt}\n\n"
            "The previous script did not run successfully. "
            "Revise the script using this execution feedback and resend the full corrected script.\n"
            + "\n".join(failure_parts)
        )

    return PlotModeGenerationResult(
        assistant_text="",
        error_message="I couldn't produce a runnable plotting script after several tries.",
    )


async def _run_plot_mode_planning(
    *,
    state: PlotModeState,
    runner: FixRunner,
    user_message: str,
    model: str,
    variant: str | None,
) -> PlotModePlanResult:
    prompt = _build_plot_mode_planning_prompt(state, user_message)
    assistant_text, runner_error = await _run_plot_mode_runner_prompt(
        state=state,
        runner=runner,
        prompt=prompt,
        model=model,
        variant=variant,
    )
    if runner_error is not None:
        return PlotModePlanResult(
            assistant_text=assistant_text,
            error_message=runner_error,
        )

    parsed = _extract_plot_mode_plan_result(assistant_text)
    needs_option_recovery = (
        parsed is not None
        and parsed.questions is not None
        and not _plot_mode_plan_result_has_selectable_options(parsed)
    )
    if parsed is None or needs_option_recovery:
        recovery_prompt = (
            f"{prompt}\n\n"
            "FORMAT RECOVERY: Resend the planning response as JSON with keys "
            "summary, plot_type, data_actions, plan_outline, questions, question_purpose, clarification_question, and ready_to_plot. "
            "If you need user input, do not ask only in prose; include the prompt and choices in questions. "
            "Every question should include 2-5 selectable options in the options array whenever a discrete choice is possible."
        )
        recovered_text, recovery_error = await _run_plot_mode_runner_prompt(
            state=state,
            runner=runner,
            prompt=recovery_prompt,
            model=model,
            variant=variant,
        )
        if recovery_error is not None:
            return PlotModePlanResult(
                assistant_text=assistant_text,
                error_message=recovery_error,
            )
        recovered_parsed = _extract_plot_mode_plan_result(recovered_text)
        if recovered_parsed is not None and (
            parsed is None
            or _plot_mode_plan_result_has_selectable_options(recovered_parsed)
        ):
            parsed = recovered_parsed
            assistant_text = recovered_text

    if parsed is None:
        fallback_summary = (
            assistant_text.strip() or "I need more context before drafting."
        )
        return PlotModePlanResult(
            assistant_text=assistant_text,
            summary=fallback_summary[:480],
            plan_outline=[],
            data_actions=[],
            ready_to_plot=False,
        )

    parsed.assistant_text = assistant_text
    return parsed


def _store_plot_mode_plan(state: PlotModeState, result: PlotModePlanResult) -> None:
    state.latest_plan_summary = result.summary.strip()
    state.latest_plan_plot_type = result.plot_type.strip()
    state.latest_plan_outline = [
        item for item in (result.plan_outline or []) if item.strip()
    ]
    state.latest_plan_actions = [
        item for item in (result.data_actions or []) if item.strip()
    ]


def _queue_plot_mode_plan_approval_question(state: PlotModeState) -> None:
    question_set = PlotModeQuestionSet(
        purpose="approve_plot_plan",
        title="Ready to draft",
        questions=[
            PlotModeQuestionItem(
                title="Next step",
                prompt="Plan is ready. Should I start drafting the plot now?",
                options=[
                    PlotModeQuestionOption(
                        id="start_draft",
                        label="Start drafting",
                        description="Generate and execute the first approved plot draft.",
                        recommended=True,
                    ),
                    PlotModeQuestionOption(
                        id="revise_plan",
                        label="Revise the plan",
                        description="Adjust chart type, scope, style, or layout before drafting.",
                    ),
                ],
                allow_custom_answer=True,
            )
        ],
    )
    _append_plot_mode_question_set(
        state,
        question_set=question_set,
        lead_content="Plan is ready. Should I start drafting the plot now?",
    )


def _queue_plot_mode_continue_planning_question(
    state: PlotModeState,
    prompt: str,
) -> None:
    question_set = PlotModeQuestionSet(
        purpose="continue_plot_planning",
        title="More input needed",
        questions=[
            PlotModeQuestionItem(
                title="Continue planning",
                prompt=prompt,
                options=[
                    PlotModeQuestionOption(
                        id="continue_planning",
                        label="Continue",
                        description="Inspect the source more closely and refine the plan.",
                        recommended=True,
                    ),
                    PlotModeQuestionOption(
                        id="revise_goal",
                        label="Revise the plan",
                        description="Adjust the goal or constraints before continuing.",
                    ),
                ],
                allow_custom_answer=True,
            )
        ],
    )
    _append_plot_mode_question_set(
        state,
        question_set=question_set,
        lead_content=prompt,
    )


def _queue_plot_mode_bundle_kickoff_question(state: PlotModeState) -> None:
    prompt = (
        "Your source bundle is ready. Proceed to plot planning, "
        "or tell me anything else to consider first."
    )
    question_set = PlotModeQuestionSet(
        purpose="kickoff_plot_planning",
        title="Ready to plan",
        questions=[
            PlotModeQuestionItem(
                title="Next step",
                prompt=prompt,
                options=[
                    PlotModeQuestionOption(
                        id="proceed_to_planning",
                        label="Proceed",
                        description="Start planning the plot from this source bundle now.",
                        recommended=True,
                    )
                ],
                allow_custom_answer=True,
            )
        ],
    )
    _append_plot_mode_question_set(
        state,
        question_set=question_set,
        lead_content=prompt,
    )


def _present_plot_mode_plan_result(
    state: PlotModeState,
    result: PlotModePlanResult,
) -> None:
    _store_plot_mode_plan(state, result)

    if result.summary.strip():
        _append_plot_mode_message(
            state,
            role="assistant",
            content=_truncate_output(result.summary.strip()),
        )

    if state.latest_plan_plot_type:
        _append_plot_mode_activity(
            state,
            title="Recommended chart",
            items=[state.latest_plan_plot_type],
        )
    if state.latest_plan_actions:
        _append_plot_mode_activity(
            state,
            title="What I'll check in the data",
            items=state.latest_plan_actions[:8],
        )
    if state.latest_plan_outline:
        _append_plot_mode_activity(
            state,
            title="Proposed plot plan",
            items=state.latest_plan_outline[:8],
        )

    if result.questions:
        question_set = PlotModeQuestionSet(
            purpose=(
                cast(
                    Literal[
                        "select_data_source",
                        "confirm_tabular_range",
                        "confirm_data_preview",
                        "continue_plot_planning",
                        "approve_plot_plan",
                    ],
                    result.question_purpose,
                )
                if result.question_purpose
                in {
                    "select_data_source",
                    "confirm_tabular_range",
                    "confirm_data_preview",
                    "continue_plot_planning",
                    "approve_plot_plan",
                }
                else (
                    "approve_plot_plan"
                    if result.ready_to_plot
                    else "continue_plot_planning"
                )
            ),
            title="Questions",
            questions=result.questions,
        )
        state.phase = PlotModePhase.awaiting_data_choice
        _append_plot_mode_question_set(
            state,
            question_set=question_set,
            lead_content=result.clarification_question
            or "I have a few questions before moving on.",
        )
        return

    if result.ready_to_plot:
        state.phase = PlotModePhase.awaiting_plan_approval
        _queue_plot_mode_plan_approval_question(state)
        return

    state.phase = PlotModePhase.awaiting_prompt
    if result.clarification_question:
        state.phase = PlotModePhase.awaiting_data_choice
        _queue_plot_mode_continue_planning_question(
            state,
            prompt=result.clarification_question,
        )


async def _execute_plot_mode_draft(
    *,
    state: PlotModeState,
    runner: FixRunner,
    model: str,
    variant: str | None,
    draft_message: str,
) -> tuple[bool, str | None]:
    state.phase = PlotModePhase.drafting
    state.last_error = None
    await _broadcast_plot_mode_state(state)

    result = await _run_plot_mode_generation(
        state=state,
        runner=runner,
        message=draft_message,
        model=model,
        variant=variant,
        assistant_message=PlotModeChatMessage(role="assistant", content=""),
    )

    ok, error_message = _apply_plot_mode_result(state, result=result)
    if not ok:
        state.phase = PlotModePhase.awaiting_prompt
        details = error_message or "Plot generation failed"
        stderr_text = (
            result.execution_result.stderr.strip() if result.execution_result else ""
        )
        error_body = _truncate_output(
            "\n".join(part for part in [details, stderr_text] if part)
        )
        _append_plot_mode_message(state, role="error", content=error_body)
        await _broadcast_plot_mode_state(state)
        return False, details

    summary_message: PlotModeChatMessage | None = None
    summary_text = _truncate_output(result.assistant_text.strip())
    if summary_text:
        summary_message = _create_plot_mode_message(
            state,
            role="assistant",
            content=summary_text,
        )
    await _broadcast_plot_mode_preview(state)

    if state.execution_mode == PlotModeExecutionMode.autonomous:
        await _run_plot_mode_autonomous_reviews(
            state=state,
            runner=runner,
            model=model,
            variant=variant,
            summary_message=summary_message,
        )

    state.phase = PlotModePhase.ready
    await _broadcast_plot_mode_state(state)
    return True, None


async def _continue_plot_mode_planning(
    *,
    state: PlotModeState,
    runner: FixRunner,
    model: str,
    variant: str | None,
    planning_message: str,
) -> tuple[bool, str | None]:
    state.phase = PlotModePhase.planning
    state.last_error = None
    await _broadcast_plot_mode_state(state)

    result = await _run_plot_mode_planning(
        state=state,
        runner=runner,
        user_message=planning_message,
        model=model,
        variant=variant,
    )
    if result.error_message is not None:
        state.phase = PlotModePhase.awaiting_prompt
        _append_plot_mode_message(
            state,
            role="error",
            content=_truncate_output(result.error_message),
        )
        await _broadcast_plot_mode_state(state)
        return False, result.error_message

    _present_plot_mode_plan_result(state, result)
    _touch_plot_mode(state)
    await _broadcast_plot_mode_state(state)
    return True, None


def _default_plot_mode_planning_message(*, bundle: bool) -> str:
    if bundle:
        return (
            "Inspect the confirmed source bundle, suggest the strongest figure, "
            "and ask before drafting."
        )
    return "Inspect the confirmed source, suggest the strongest figure, and ask before drafting."


async def _continue_plot_mode_planning_with_selected_runner(
    *,
    state: PlotModeState,
    planning_message: str,
) -> tuple[bool, str | None]:
    runner = _resolve_available_runner(
        _normalize_fix_runner(state.selected_runner, default=_default_fix_runner)
    )
    state.selected_runner = runner
    _ensure_runner_is_available(runner)
    model = str(state.selected_model or "").strip() or _runner_default_model_id(runner)
    normalized_variant = (
        str(state.selected_variant).strip() if state.selected_variant else ""
    )
    return await _continue_plot_mode_planning(
        state=state,
        runner=runner,
        model=model,
        variant=normalized_variant or None,
        planning_message=planning_message,
    )


async def _start_plot_mode_planning_for_profile(
    state: PlotModeState,
    profile: PlotModeDataProfile,
) -> tuple[bool, str | None]:
    state.selected_data_profile_id = profile.id
    _set_active_resolved_source_for_profile(state, profile)
    planning_message = (
        state.latest_user_goal.strip()
        or _default_plot_mode_planning_message(bundle=False)
    )
    return await _continue_plot_mode_planning_with_selected_runner(
        state=state,
        planning_message=planning_message,
    )


async def _broadcast_plot_mode_preview(state: PlotModeState) -> None:
    await _broadcast_plot_mode_state(state)
    await _broadcast(
        {
            "type": "plot_updated",
            "plot_type": state.plot_type,
            "revision": 0,
            "reason": "plot_mode_preview",
        }
    )


def _apply_plot_mode_result(
    state: PlotModeState,
    *,
    result: PlotModeGenerationResult,
) -> tuple[bool, str | None]:
    if result.script is not None:
        state.current_script = result.script
        state.current_script_path = str(_plot_mode_generated_script_path(state))

    if result.execution_result is None:
        error_message = result.error_message or "Plot generation failed"
        state.last_error = error_message
        _promote_plot_mode_workspace(state)
        return False, error_message

    if not result.execution_result.success or not result.execution_result.plot_path:
        error_message = result.execution_result.error or "Script execution failed"
        state.last_error = error_message
        _promote_plot_mode_workspace(state)
        return False, error_message

    state.current_plot = result.execution_result.plot_path
    state.plot_type = result.execution_result.plot_type
    state.last_error = None
    _promote_plot_mode_workspace(state)
    return True, None


async def _run_plot_mode_autonomous_reviews(
    *,
    state: PlotModeState,
    runner: FixRunner,
    model: str,
    variant: str | None,
    summary_message: PlotModeChatMessage | None,
) -> None:
    pass_index = 2
    stalled_passes = 0
    started_at = time.monotonic()
    latest_summary = (
        summary_message.content if summary_message is not None else ""
    ).strip()
    initial_focus = _plot_mode_autonomous_focus_direction(pass_index)
    status_message = _create_plot_mode_message(
        state,
        role="assistant",
        content=f"Refining plot: {initial_focus}.",
        metadata=_plot_mode_refining_metadata(initial_focus),
    )

    async def _finalize_refining_status() -> None:
        nonlocal summary_message
        final_summary = _truncate_output(latest_summary)
        if final_summary:
            if summary_message is None:
                _append_plot_mode_message(
                    state,
                    role="assistant",
                    content=final_summary,
                )
            else:
                _set_plot_mode_message_content(
                    state,
                    summary_message,
                    final_summary,
                    final=True,
                )
        _remove_plot_mode_message(state, status_message.id)
        await _broadcast_plot_mode_state(state)

    while True:
        elapsed = time.monotonic() - started_at
        if elapsed >= _plot_mode_autonomous_watchdog_s:
            await _finalize_refining_status()
            return

        focus_direction = _plot_mode_autonomous_focus_direction(pass_index)
        previous_script = (state.current_script or "").strip()
        state.phase = PlotModePhase.self_review
        _set_plot_mode_message_content(
            state,
            status_message,
            f"Refining plot: {focus_direction}.",
            final=True,
        )
        _set_plot_mode_message_metadata(
            state,
            status_message,
            _plot_mode_refining_metadata(focus_direction),
        )
        await _broadcast_plot_mode_state(state)

        result = await _run_plot_mode_generation(
            state=state,
            runner=runner,
            message=_build_plot_mode_review_prompt(
                state,
                iteration_index=pass_index,
                focus_direction=focus_direction,
            ),
            model=model,
            variant=variant,
            assistant_message=PlotModeChatMessage(role="assistant", content=""),
        )
        ok, error_message = _apply_plot_mode_result(state, result=result)
        if not ok:
            if latest_summary and summary_message is not None:
                _set_plot_mode_message_content(
                    state,
                    summary_message,
                    _truncate_output(latest_summary),
                    final=True,
                )
            _remove_plot_mode_message(state, status_message.id)
            _append_plot_mode_message(
                state, role="error", content=error_message or "Autonomous review failed"
            )
            await _broadcast_plot_mode_state(state)
            return

        if result.assistant_text.strip():
            latest_summary = result.assistant_text.strip()
        await _broadcast_plot_mode_preview(state)

        current_script = (state.current_script or "").strip()
        if current_script == previous_script:
            stalled_passes += 1
        else:
            stalled_passes = 0

        if result.done_hint is True and stalled_passes >= 1:
            await _finalize_refining_status()
            return

        if stalled_passes >= _plot_mode_autonomous_stall_limit:
            await _finalize_refining_status()
            return

        pass_index += 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_terminal_fix_job_status(status: FixJobStatus) -> bool:
    return status in {
        FixJobStatus.completed,
        FixJobStatus.failed,
        FixJobStatus.cancelled,
    }


def _truncate_output(text: str, *, max_chars: int = 12_000) -> str:
    if len(text) <= max_chars:
        return text
    keep_tail = int(max_chars * 0.75)
    omitted = len(text) - keep_tail
    return f"[truncated {omitted} chars]\n{text[-keep_tail:]}"


def _parse_opencode_verbose_models(raw: str) -> list[OpencodeModelOption]:
    options_by_id: dict[str, OpencodeModelOption] = {}
    lines = raw.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if "/" not in line or line.startswith("{") or line.startswith("}"):
            index += 1
            continue

        model_id = line
        index += 1

        while index < len(lines) and not lines[index].strip():
            index += 1

        model_meta: dict = {}
        if index < len(lines) and lines[index].lstrip().startswith("{"):
            brace_depth = 0
            block: list[str] = []
            while index < len(lines):
                current = lines[index]
                brace_depth += current.count("{")
                brace_depth -= current.count("}")
                block.append(current)
                index += 1
                if brace_depth <= 0:
                    break
            try:
                model_meta = json.loads("\n".join(block))
            except json.JSONDecodeError:
                model_meta = {}

        variants_raw = model_meta.get("variants")
        variants = (
            sorted(str(key) for key in variants_raw.keys())
            if isinstance(variants_raw, dict)
            else []
        )
        provider = str(model_meta.get("providerID") or model_id.split("/", 1)[0])
        name = str(model_meta.get("name") or model_id)
        options_by_id[model_id] = OpencodeModelOption(
            id=model_id,
            provider=provider,
            name=name,
            variants=variants,
        )

    if options_by_id:
        return sorted(options_by_id.values(), key=lambda option: option.id)

    for line in lines:
        candidate = line.strip()
        if not candidate or "/" not in candidate or candidate.startswith("opencode "):
            continue
        options_by_id[candidate] = OpencodeModelOption(
            id=candidate,
            provider=candidate.split("/", 1)[0],
            name=candidate,
            variants=[],
        )

    return sorted(options_by_id.values(), key=lambda option: option.id)


def _refresh_opencode_models_cache(
    *, force_refresh: bool = False
) -> list[OpencodeModelOption]:
    global _opencode_models_cache, _opencode_models_cache_expires_at

    now = time.monotonic()
    if (
        not force_refresh
        and _opencode_models_cache is not None
        and now < _opencode_models_cache_expires_at
    ):
        return _opencode_models_cache

    opencode_command = _resolve_command_path("opencode")
    if opencode_command is None:
        raise RuntimeError("opencode command not found")

    attempts = [
        [opencode_command, "models", "--verbose"],
        [opencode_command, "models"],
    ]
    last_error: str | None = None

    for command in attempts:
        try:
            result = subprocess.run(
                command,
                cwd=str(_workspace_dir),
                env=_subprocess_env(),
                capture_output=True,
                text=True,
                check=False,
                **_hidden_window_kwargs(),
            )
        except OSError as exc:
            last_error = str(exc)
            continue

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if stderr:
                last_error = stderr
            continue

        parsed = _parse_opencode_verbose_models(result.stdout)
        if parsed:
            _opencode_models_cache = parsed
            _opencode_models_cache_expires_at = now + _opencode_models_cache_ttl_s
            return parsed

        if result.stdout.strip():
            last_error = "No parseable model entries returned by opencode"

    raise RuntimeError(last_error or "Failed to load models from opencode")


def _parse_codex_models_cache(raw: object) -> list[OpencodeModelOption]:
    if not isinstance(raw, dict):
        return []

    models_raw = raw.get("models")
    if not isinstance(models_raw, list):
        return []

    options: dict[str, OpencodeModelOption] = {}
    for entry in models_raw:
        if not isinstance(entry, dict):
            continue

        model_id = str(entry.get("slug") or "").strip()
        if not model_id:
            continue

        visibility = str(entry.get("visibility") or "").strip().lower()
        if visibility and visibility != "list":
            continue

        levels_raw = entry.get("supported_reasoning_levels")
        variants: list[str] = []
        if isinstance(levels_raw, list):
            for level in levels_raw:
                if not isinstance(level, dict):
                    continue
                effort = str(level.get("effort") or "").strip()
                if effort and effort not in variants:
                    variants.append(effort)

        options[model_id] = OpencodeModelOption(
            id=model_id,
            provider="openai",
            name=str(entry.get("display_name") or model_id),
            variants=variants,
        )

    return sorted(options.values(), key=lambda option: option.id)


def _refresh_codex_models_cache(
    *, force_refresh: bool = False
) -> list[OpencodeModelOption]:
    global _codex_models_cache, _codex_models_cache_expires_at

    now = time.monotonic()
    if (
        not force_refresh
        and _codex_models_cache is not None
        and now < _codex_models_cache_expires_at
    ):
        return _codex_models_cache

    cache_path = Path.home() / ".codex" / "models_cache.json"
    if not cache_path.exists():
        raise RuntimeError(
            "Codex model cache not found. Run `codex` once to initialise it."
        )

    try:
        parsed_json = json.loads(_read_file_text(cache_path))
    except OSError as exc:
        raise RuntimeError(f"Failed to read Codex model cache: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse Codex model cache: {exc}") from exc

    parsed = _parse_codex_models_cache(parsed_json)
    if not parsed:
        raise RuntimeError("No parseable model entries returned by Codex")

    _codex_models_cache = parsed
    _codex_models_cache_expires_at = now + _codex_models_cache_ttl_s
    return parsed


def _refresh_claude_models_cache(
    *, force_refresh: bool = False
) -> list[OpencodeModelOption]:
    global _claude_models_cache, _claude_models_cache_expires_at

    now = time.monotonic()
    if (
        not force_refresh
        and _claude_models_cache is not None
        and now < _claude_models_cache_expires_at
    ):
        return _claude_models_cache

    variants = ["low", "medium", "high"]
    parsed = [
        OpencodeModelOption(
            id="claude-sonnet-4-6",
            provider="anthropic",
            name="Claude Sonnet 4.6",
            variants=variants,
        ),
        OpencodeModelOption(
            id="claude-opus-4-6",
            provider="anthropic",
            name="Claude Opus 4.6",
            variants=variants,
        ),
        OpencodeModelOption(
            id="claude-haiku-4-5",
            provider="anthropic",
            name="Claude Haiku 4.5",
            variants=[],
        ),
    ]

    _claude_models_cache = parsed
    _claude_models_cache_expires_at = now + _claude_models_cache_ttl_s
    return parsed


def _refresh_runner_models_cache(
    runner: FixRunner, *, force_refresh: bool = False
) -> list[OpencodeModelOption]:
    if runner == "codex":
        return _refresh_codex_models_cache(force_refresh=force_refresh)
    if runner == "claude":
        return _refresh_claude_models_cache(force_refresh=force_refresh)
    return _refresh_opencode_models_cache(force_refresh=force_refresh)


def _resolve_runner_default_model_and_variant(
    *,
    runner: FixRunner,
    models: list[OpencodeModelOption],
    preferred_runner: FixRunner,
    preferred_model: str | None,
    preferred_variant: str | None,
) -> tuple[str, str]:
    model_ids = {model.id for model in models}
    runner_default_model = _runner_default_model_id(runner)

    if not models:
        if preferred_runner == runner and preferred_model:
            return preferred_model, preferred_variant or ""
        return runner_default_model, ""

    if preferred_runner == runner and preferred_model in model_ids:
        default_model = preferred_model
    elif runner_default_model in model_ids:
        default_model = runner_default_model
    else:
        default_model = models[0].id if models else ""

    default_variant = ""
    if default_model and preferred_runner == runner and preferred_variant:
        selected_default_model = next(
            (model for model in models if model.id == default_model),
            None,
        )
        if selected_default_model is not None and selected_default_model.variants:
            if preferred_variant in selected_default_model.variants:
                default_variant = preferred_variant
        elif default_model in model_ids:
            default_variant = preferred_variant

    return default_model, default_variant


def _validate_runner_model_selection(
    *,
    runner: FixRunner,
    model: str,
    variant: str | None,
    models: list[OpencodeModelOption],
) -> None:
    selected_model = next((entry for entry in models if entry.id == model), None)
    if models and selected_model is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model for {runner}: {model}",
        )

    if (
        selected_model is not None
        and variant is not None
        and selected_model.variants
        and variant not in selected_model.variants
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Variant '{variant}' is not available for model '{model}' "
                f"on runner '{runner}'"
            ),
        )


def _build_opencode_plot_fix_command(
    *,
    model: str,
    variant: str | None,
    workspace_dir: str | Path | None = None,
    resume_session_id: str | None = None,
    extra_prompt: str | None = None,
) -> list[str]:
    resolved_workspace_dir = (
        Path(workspace_dir).resolve() if workspace_dir else _workspace_dir
    )
    opencode_command = _resolve_command_path("opencode") or "opencode"
    command = [
        opencode_command,
        "run",
        "--dir",
        str(resolved_workspace_dir),
        "--format",
        "json",
        "--model",
        model,
    ]
    normalized_resume_session_id = _normalize_runner_session_id(resume_session_id)
    if normalized_resume_session_id:
        command.extend(["--session", normalized_resume_session_id])
    normalized_variant = (variant or "").strip()
    if normalized_variant:
        command.extend(["--variant", normalized_variant])
    command.append(_build_codex_plot_fix_prompt(extra_prompt=extra_prompt))
    return command


def _opencode_fix_config_content() -> str:
    mcp_launch = _resolve_openplot_mcp_launch_command()
    config = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "openplot": {
                "type": "local",
                "enabled": True,
                "command": mcp_launch,
                "timeout": 20000,
            }
        },
        "permission": {"question": "deny"},
        "tools": {"openplot_*": True},
    }
    return json.dumps(config)


def _opencode_question_tool_disabled_config_content() -> str:
    return json.dumps(
        {
            "$schema": "https://opencode.ai/config.json",
            "permission": {"question": "deny"},
        }
    )


def _build_codex_plot_fix_prompt(*, extra_prompt: str | None = None) -> str:
    prompt = (
        "Call MCP tools in this order: "
        "(1) get_pending_feedback_with_images, "
        "(2) get_pending_feedback, "
        "(3) get_plot_context. "
        "If step (1) fails, continue with step (2). "
        "Use target_annotation_id from get_pending_feedback as the FIFO "
        "annotation to address. "
        "Read python_interpreter from get_plot_context and treat "
        "python_interpreter.available_packages as a strict allowlist for "
        "third-party imports. Use Python standard library freely, but never "
        "import a third-party package unless it appears in "
        "python_interpreter.available_packages. "
        "Treat the current branch-head script and all previously addressed annotations as the source of truth. "
        "Preserve every earlier accepted fix unless changing it is strictly necessary to satisfy the current annotation. "
        "Make the smallest targeted change needed for the FIFO pending annotation. "
        "Then update the plotting script to address exactly that one pending "
        "annotation and call submit_updated_script with the complete "
        "updated script and annotation_id=target_annotation_id. "
        "For raster-region feedback, use the crop image as primary grounding and "
        "apply ambiguous references (for example, 'this', 'these', 'each line') "
        "only to elements visible in that selected region unless the feedback "
        "explicitly requests global edits. "
        "Never use built-in interactive question tools such as AskUserQuestion or question. "
        "Do not ask the user for interactive input during fix mode. "
        "If the annotation is ambiguous, infer the most conservative interpretation from the current script, pending annotation, and existing accepted fixes, then continue. "
        "Never execute shell commands named openplot_*; these are MCP tools."
    )
    if extra_prompt:
        prompt += f" Retry context: {extra_prompt.strip()}"
    return prompt


def _build_codex_plot_fix_command(
    *,
    model: str,
    variant: str | None,
    workspace_dir: str | Path | None = None,
    resume_session_id: str | None = None,
    extra_prompt: str | None = None,
) -> list[str]:
    resolved_workspace_dir = (
        Path(workspace_dir).resolve() if workspace_dir else _workspace_dir
    )
    codex_command = _resolve_command_path("codex") or "codex"
    normalized_resume_session_id = _normalize_runner_session_id(resume_session_id)
    mcp_launch = _resolve_openplot_mcp_launch_command()
    mcp_cmd = json.dumps(mcp_launch[0])
    mcp_args = json.dumps(mcp_launch[1:])
    command = [codex_command, "exec"]
    if normalized_resume_session_id:
        command.extend(
            [
                "resume",
                "--skip-git-repo-check",
                "--json",
                "-c",
                'approval_policy="never"',
                "-c",
                f"mcp_servers.openplot.command={mcp_cmd}",
                "-c",
                f"mcp_servers.openplot.args={mcp_args}",
                "-c",
                "mcp_servers.openplot.enabled=true",
                "-c",
                "mcp_servers.openplot.startup_timeout_sec=20",
                "--model",
                model,
                normalized_resume_session_id,
            ]
        )
    else:
        command.extend(
            [
                "--cd",
                str(resolved_workspace_dir),
                "--skip-git-repo-check",
                "--json",
                "--sandbox",
                "workspace-write",
                "-c",
                'approval_policy="never"',
                "-c",
                f"mcp_servers.openplot.command={mcp_cmd}",
                "-c",
                f"mcp_servers.openplot.args={mcp_args}",
                "-c",
                "mcp_servers.openplot.enabled=true",
                "-c",
                "mcp_servers.openplot.startup_timeout_sec=20",
                "--model",
                model,
            ]
        )
    normalized_variant = (variant or "").strip()
    if normalized_variant:
        command.extend(
            [
                "-c",
                f"model_reasoning_effort={json.dumps(normalized_variant)}",
            ]
        )
    command.append(_build_codex_plot_fix_prompt(extra_prompt=extra_prompt))
    return command


def _build_claude_plot_fix_command(
    *,
    model: str,
    variant: str | None,
    workspace_dir: str | Path | None = None,
    resume_session_id: str | None = None,
    extra_prompt: str | None = None,
) -> list[str]:
    claude_command = _resolve_claude_cli_command() or "claude"
    prompt = _build_codex_plot_fix_prompt(extra_prompt=extra_prompt)
    mcp_launch = _resolve_openplot_mcp_launch_command()
    mcp_config_data = {
        "mcpServers": {
            "openplot": {
                "type": "stdio",
                "command": mcp_launch[0],
                "args": mcp_launch[1:],
            }
        }
    }

    resolved_workspace = (
        Path(workspace_dir).resolve() if workspace_dir else _workspace_dir
    )
    mcp_config_path = resolved_workspace / ".openplot_mcp_config.json"
    mcp_config_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_config_path.write_text(json.dumps(mcp_config_data), encoding="utf-8")

    command = [
        claude_command,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--permission-mode",
        "bypassPermissions",
        "--disallowedTools",
        "AskUserQuestion",
        "--strict-mcp-config",
        "--add-dir",
        str(resolved_workspace),
        "--mcp-config",
        str(mcp_config_path),
        "--model",
        model,
    ]

    normalized_resume_session_id = _normalize_runner_session_id(resume_session_id)
    if normalized_resume_session_id:
        command.extend(["--resume", normalized_resume_session_id])

    normalized_variant = (variant or "").strip()
    if normalized_variant:
        command.extend(["--effort", normalized_variant])

    return command


async def _broadcast_fix_job(job: FixJob) -> None:
    await _broadcast({"type": "fix_job_updated", "job": job.model_dump()})


async def _cancel_fix_job_execution(job: FixJob, *, reason: str) -> None:
    if _is_terminal_fix_job_status(job.status):
        _clear_active_fix_job_for_session(job.session_id, expected_job_id=job.id)
        return

    job.status = FixJobStatus.cancelled
    job.last_error = reason
    if not job.finished_at:
        job.finished_at = _now_iso()

    if job.steps and job.steps[-1].status == FixStepStatus.running:
        job.steps[-1].status = FixStepStatus.cancelled
        job.steps[-1].finished_at = _now_iso()
        if not job.steps[-1].error:
            job.steps[-1].error = reason

    process = _runtime_fix_job_processes_map().get(job.id)
    if process is not None:
        await _terminate_fix_process(process)

    _clear_active_fix_job_for_session(job.session_id, expected_job_id=job.id)
    await _broadcast_fix_job(job)


async def _reconcile_active_fix_job_state() -> None:
    """Recover from stale active-job locks after worker/process drift."""
    active_fix_jobs = _runtime_active_fix_jobs_map()
    fix_jobs = _runtime_fix_jobs_map()
    fix_job_tasks = _runtime_fix_job_tasks_map()
    fix_job_processes = _runtime_fix_job_processes_map()

    if not active_fix_jobs:
        return

    for session_key, job_id in list(active_fix_jobs.items()):
        job = fix_jobs.get(job_id)
        if job is None:
            active_fix_jobs.pop(session_key, None)
            continue

        if _is_terminal_fix_job_status(job.status):
            active_fix_jobs.pop(session_key, None)
            fix_job_tasks.pop(job.id, None)
            fix_job_processes.pop(job.id, None)
            continue

        task = fix_job_tasks.get(job.id)
        process = fix_job_processes.get(job.id)

        task_running = task is not None and not task.done()
        process_running = process is not None and process.returncode is None
        if task_running or process_running:
            continue

        message = "Fix job worker state was lost; marking as failed."
        if job.steps and job.steps[-1].status == FixStepStatus.running:
            job.steps[-1].status = FixStepStatus.failed
            job.steps[-1].finished_at = _now_iso()
            if not job.steps[-1].error:
                job.steps[-1].error = message

        job.status = FixJobStatus.failed
        if not job.last_error:
            job.last_error = message
        if not job.finished_at:
            job.finished_at = _now_iso()

        active_fix_jobs.pop(session_key, None)
        fix_job_tasks.pop(job.id, None)
        fix_job_processes.pop(job.id, None)
        await _broadcast_fix_job(job)


def _parse_json_event_line(line: str) -> dict | None:
    stripped = line.strip()
    if not stripped or not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _parse_opencode_json_event_line(line: str) -> dict | None:
    return _parse_json_event_line(line)


async def _broadcast_fix_job_log(
    *,
    job_id: str,
    step_index: int,
    annotation_id: str,
    stream: Literal["stdout", "stderr"],
    chunk: str,
    parsed: dict | None,
) -> None:
    await _broadcast(
        {
            "type": "fix_job_log",
            "job_id": job_id,
            "step_index": step_index,
            "annotation_id": annotation_id,
            "stream": stream,
            "chunk": chunk,
            "timestamp": _now_iso(),
            "parsed": parsed,
        }
    )


def get_session() -> PlotSession:
    global _session

    runtime = _current_runtime()
    if _runtime_is_shared(runtime):
        _ensure_session_store_loaded()
        if _session is None and _active_session_id:
            _session = _sessions.get(_active_session_id)
        session = _session
    else:
        _ensure_session_store_loaded()
        session = runtime.store.active_session
        if session is None and runtime.store.active_session_id:
            session = runtime.store.sessions.get(runtime.store.active_session_id)
            runtime.store.active_session = session

    if session is None:
        raise HTTPException(status_code=404, detail="No active session")
    _ensure_workspace_name(session)
    return session


def _get_session_by_id(session_id: str) -> PlotSession:
    _ensure_session_store_loaded()

    normalized_session_id = session_id.strip()
    if not normalized_session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")

    session = _runtime_sessions_map().get(normalized_session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {normalized_session_id}",
        )

    _ensure_workspace_name(session)
    return session


def _resolve_request_session(session_id: str | None) -> PlotSession:
    if session_id is None:
        return get_session()

    normalized = session_id.strip()
    if not normalized:
        return get_session()
    return _get_session_by_id(normalized)


def _session_for_fix_job(job: FixJob) -> PlotSession:
    if job.session_id:
        return _get_session_by_id(job.session_id)
    return get_session()


def _workspace_dir_for_fix_job(job: FixJob, session: PlotSession) -> Path:
    context_workspace = _workspace_for_session(session).resolve()
    try:
        context_workspace.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    else:
        if context_workspace.exists() and context_workspace.is_dir():
            return context_workspace

    if job.workspace_dir:
        workspace_dir = Path(job.workspace_dir).resolve()
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return workspace_dir

    fallback_workspace = _runtime_workspace_dir().resolve()
    try:
        fallback_workspace.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return fallback_workspace


def _runtime_dir_for_fix_job(job: FixJob, session: PlotSession) -> Path:
    if job.workspace_dir:
        runtime_dir = Path(job.workspace_dir).resolve()
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return runtime_dir
    return _prepare_fix_runner_workspace(session, job_id=job.id)


def _fix_runner_env_overrides(job: FixJob, session: PlotSession) -> dict[str, str]:
    runtime_dir = _runtime_dir_for_fix_job(job, session)
    shim_bin = _write_fix_runner_shims(runtime_dir)

    path_entries = [str(shim_bin), _command_search_path()]
    overrides: dict[str, str] = {
        "OPENPLOT_SESSION_ID": session.id,
        "PATH": os.pathsep.join(path_entries),
    }

    runtime_executable = Path(sys.executable).expanduser().resolve()
    if not _is_openplot_app_launcher_path(runtime_executable):
        package_src_root = Path(__file__).resolve().parent.parent
        current_pythonpath = os.getenv("PYTHONPATH") or ""
        if current_pythonpath:
            overrides["PYTHONPATH"] = (
                f"{package_src_root}{os.pathsep}{current_pythonpath}"
            )
        else:
            overrides["PYTHONPATH"] = str(package_src_root)

    backend_url = _backend_url_from_port_file()
    if backend_url:
        overrides["OPENPLOT_SERVER_URL"] = backend_url

    overrides["OPENCODE_CONFIG_CONTENT"] = _opencode_fix_config_content()

    return overrides


def _fix_job_session_key(session_id: str | None) -> str:
    normalized = (session_id or "").strip()
    return normalized or "__legacy__"


def _active_fix_job_id_for_session(session_id: str | None) -> str | None:
    return _runtime_active_fix_jobs_map().get(_fix_job_session_key(session_id))


def _set_active_fix_job_for_session(session_id: str | None, job_id: str) -> None:
    _runtime_active_fix_jobs_map()[_fix_job_session_key(session_id)] = job_id


def _clear_active_fix_job_for_session(
    session_id: str | None,
    *,
    expected_job_id: str | None = None,
) -> None:
    key = _fix_job_session_key(session_id)
    active_fix_jobs = _runtime_active_fix_jobs_map()
    current_job_id = active_fix_jobs.get(key)
    if current_job_id is None:
        return
    if expected_job_id is not None and current_job_id != expected_job_id:
        return
    active_fix_jobs.pop(key, None)


async def _broadcast(event: dict) -> None:
    """Send a JSON event to all connected WebSocket clients."""
    payload = json.dumps(event)
    dead: list[WebSocket] = []
    ws_clients = _runtime_ws_clients()
    for ws in ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


def _resolve_plot_response(
    *,
    session_id: str | None,
    version_id: str | None,
    plot_mode: bool,
    workspace_id: str | None = None,
) -> tuple[Path, str]:
    if plot_mode:
        state = _resolve_plot_mode_workspace(workspace_id)
        if not state.current_plot:
            raise HTTPException(status_code=404, detail="No plot available")
        plot_path = Path(state.current_plot)
        plot_type = state.plot_type or "raster"
        return plot_path, plot_type

    session: PlotSession | None
    normalized_session_id = session_id.strip() if session_id is not None else ""
    if normalized_session_id:
        session = _get_session_by_id(normalized_session_id)
    else:
        session = _session

    if session is None:
        if _plot_mode is not None and _plot_mode.current_plot:
            return Path(_plot_mode.current_plot), _plot_mode.plot_type or "raster"
        raise HTTPException(status_code=404, detail="No plot available")

    normalized_version_id = version_id.strip() if version_id is not None else ""
    if normalized_version_id:
        version = _get_version(session, normalized_version_id)
        return Path(version.plot_artifact_path), version.plot_type

    if not session.current_plot:
        raise HTTPException(status_code=404, detail="No plot available")
    return Path(session.current_plot), session.plot_type


def _state_root() -> Path:
    """Runtime state root (artifacts, sessions, preferences)."""
    runtime = _current_runtime_var.get()
    if runtime is not None and runtime.state_root is not None:
        return runtime.state_root
    if _runtime_state_root_override is not None:
        return _runtime_state_root_override
    return _path_from_override_env("OPENPLOT_STATE_DIR") or _default_state_root()


def _touch_session(session: PlotSession) -> None:
    session.updated_at = _now_iso()


def _default_workspace_name(
    created_at: str, *, display_tz: tzinfo | None = None
) -> str:
    normalized = created_at.strip()
    if not normalized:
        normalized = _now_iso()

    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return normalized

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    if display_tz is not None:
        localized = parsed.astimezone(display_tz)
    else:
        localized = parsed.astimezone()

    timezone_label = localized.tzname() or localized.strftime("%z")
    if not timezone_label:
        timezone_label = "local"
    return f"{localized.strftime('%Y-%m-%d %H:%M')} {timezone_label}"


def _ensure_workspace_name(session: PlotSession) -> None:
    existing = session.workspace_name.strip()
    if existing:
        session.workspace_name = existing
        return
    session.workspace_name = _default_workspace_name(session.created_at)


def _session_workspace_id(session: PlotSession) -> str:
    candidate = session.workspace_id.strip()
    if candidate:
        return candidate
    session.workspace_id = session.id
    return session.workspace_id


def _sessions_root_dir() -> Path:
    root = _state_root() / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sessions_registry_path() -> Path:
    return _sessions_root_dir() / _session_registry_file_name


def _session_snapshot_path(session_id: str) -> Path:
    return _sessions_root_dir() / session_id / _session_snapshot_file_name


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _resolve_session_file_path(session: PlotSession, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    workspace_candidate = (_workspace_dir / candidate).resolve()
    if workspace_candidate.exists():
        return workspace_candidate

    if session.artifacts_root:
        artifacts_candidate = (Path(session.artifacts_root) / candidate).resolve()
        if artifacts_candidate.exists():
            return artifacts_candidate

    return workspace_candidate


def _workspace_for_session(session: PlotSession) -> Path:
    if session.source_script_path:
        script_path = _resolve_session_file_path(session, session.source_script_path)
        if script_path.parent.exists():
            return script_path.parent

    if session.current_plot:
        plot_path = _resolve_session_file_path(session, session.current_plot)
        if plot_path.parent.exists():
            return plot_path.parent

    return _workspace_dir


def _prepare_fix_runner_workspace(session: PlotSession, *, job_id: str) -> Path:
    """Create a per-job runtime directory for external fix runners."""
    workspace_root = _session_artifacts_root(session) / "fix_runner" / job_id
    workspace_root.mkdir(parents=True, exist_ok=True)

    context_dir = _workspace_for_session(session)
    context_note = workspace_root / "OPENPLOT_CONTEXT_DIR.txt"
    try:
        context_note.write_text(str(context_dir), encoding="utf-8")
    except OSError:
        pass

    context_link = workspace_root / "project"
    try:
        if context_link.is_symlink():
            try:
                if context_link.resolve() != context_dir.resolve():
                    context_link.unlink()
            except OSError:
                context_link.unlink(missing_ok=True)
        elif context_link.exists() and not context_link.is_dir():
            context_link.unlink(missing_ok=True)

        if not context_link.exists() and context_dir.exists():
            context_link.symlink_to(context_dir, target_is_directory=True)
    except OSError:
        # Symlink creation can fail on some platforms/permissions; keep going.
        pass

    return workspace_root.resolve()


def _session_sort_key(session: PlotSession) -> tuple[str, str, str]:
    return (session.updated_at or session.created_at, session.created_at, session.id)


def _load_session_snapshot(session_id: str) -> PlotSession | None:
    snapshot_path = _session_snapshot_path(session_id)
    if not snapshot_path.exists():
        return None

    try:
        raw = json.loads(_read_file_text(snapshot_path))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None

    try:
        session = PlotSession.model_validate(raw)
    except Exception:
        return None

    if not session.id:
        session.id = session_id
    if not session.workspace_id:
        session.workspace_id = session.id
    if not session.artifacts_root:
        session.artifacts_root = str(snapshot_path.parent.resolve())
    if not session.updated_at:
        session.updated_at = session.created_at or _now_iso()
    _ensure_workspace_name(session)
    return session


def _save_session_registry() -> None:
    global _active_session_id, _session_order

    filtered_order: list[str] = []
    seen: set[str] = set()
    for session_id in _session_order:
        if session_id in seen or session_id not in _sessions:
            continue
        seen.add(session_id)
        filtered_order.append(session_id)
    for session_id in sorted(
        (sid for sid in _sessions if sid not in seen),
        key=lambda sid: _session_sort_key(_sessions[sid]),
        reverse=True,
    ):
        filtered_order.append(session_id)

    _session_order = filtered_order

    if _active_session_id and _active_session_id not in _sessions:
        _active_session_id = None

    payload: dict[str, object] = {
        "order": _session_order,
        "active_session_id": _active_session_id,
    }
    _write_json_atomic(_sessions_registry_path(), payload)


def _save_session_snapshot(session: PlotSession) -> None:
    snapshot_path = _session_snapshot_path(session.id)
    if not session.artifacts_root:
        session.artifacts_root = str(snapshot_path.parent.resolve())
    _session_workspace_id(session)
    payload = cast(dict[str, object], session.model_dump(mode="json"))
    _write_json_atomic(snapshot_path, payload)


def _persist_session(session: PlotSession, *, promote: bool) -> None:
    _sessions[session.id] = session

    if session.id in _session_order:
        _session_order.remove(session.id)
    if promote:
        _session_order.insert(0, session.id)
    else:
        _session_order.append(session.id)

    _save_session_snapshot(session)
    _save_session_registry()


def _ensure_session_store_loaded_impl(*, force_reload: bool = False) -> None:
    global _active_session_id
    global _loaded_session_store_root
    global _plot_mode
    global _session
    global _session_order
    global _sessions

    if (
        not force_reload
        and _bound_runtime is not None
        and not _runtime_is_shared(_bound_runtime)
        and (
            _sessions
            or _plot_mode is not None
            or _active_session_id is not None
            or _loaded_session_store_root is not None
        )
    ):
        return

    sessions_root = _sessions_root_dir().resolve()
    if (
        not force_reload
        and _loaded_session_store_root is not None
        and _loaded_session_store_root == sessions_root
    ):
        return

    loaded_sessions: dict[str, PlotSession] = {}
    for snapshot_path in sorted(sessions_root.glob(f"*/{_session_snapshot_file_name}")):
        session_id = snapshot_path.parent.name
        session = _load_session_snapshot(session_id)
        if session is None:
            continue
        loaded_sessions[session.id] = session

    registry_path = _sessions_registry_path()
    order_from_registry: list[str] = []
    active_session_id: str | None = None
    if registry_path.exists():
        try:
            raw_registry = json.loads(_read_file_text(registry_path))
        except (OSError, json.JSONDecodeError):
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
        key=lambda sid: _session_sort_key(loaded_sessions[sid]), reverse=True
    )

    _sessions = loaded_sessions
    _session_order = [*order_from_registry, *remaining]
    _active_session_id = active_session_id
    _session = _sessions.get(_active_session_id) if _active_session_id else None
    _plot_mode = _load_plot_mode_snapshot()

    if _session is not None:
        set_workspace_dir(_workspace_for_session(_session))
    elif _plot_mode is not None:
        set_workspace_dir(Path(_plot_mode.workspace_dir))

    _loaded_session_store_root = sessions_root


def _ensure_session_store_loaded(*, force_reload: bool = False) -> None:
    session_services.ensure_session_store_loaded(
        _current_runtime(), force_reload=force_reload
    )


def _set_active_session(session_id: str | None, *, clear_plot_mode: bool) -> None:
    global _active_session_id
    global _session

    if session_id is None:
        _active_session_id = None
        _session = None
    else:
        target = _sessions.get(session_id)
        if target is None:
            raise HTTPException(
                status_code=404, detail=f"Session not found: {session_id}"
            )
        _active_session_id = session_id
        _session = target
        set_workspace_dir(_workspace_for_session(target))

    if clear_plot_mode:
        _clear_plot_mode_state()

    _save_session_registry()


def _session_title(session: PlotSession) -> str:
    _ensure_workspace_name(session)
    return session.workspace_name


def _safe_export_stem(name: str, *, default: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()).strip("._-")
    return sanitized or default


def _session_summary(session: PlotSession) -> dict[str, object]:
    _ensure_workspace_name(session)
    workspace_id = _session_workspace_id(session)
    pending_count = sum(
        1
        for annotation in session.annotations
        if annotation.status == AnnotationStatus.pending
    )
    title = _session_title(session)
    return {
        "id": workspace_id,
        "session_id": session.id,
        "workspace_mode": "annotation",
        "workspace_name": title,
        "title": title,
        "source_script_path": session.source_script_path,
        "plot_type": session.plot_type,
        "annotation_count": len(session.annotations),
        "pending_annotation_count": pending_count,
        "checked_out_version_id": session.checked_out_version_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _plot_mode_summary(state: PlotModeState) -> dict[str, object]:
    _ensure_plot_mode_workspace_name(state)
    plot_type = state.plot_type or "svg"
    return {
        "id": state.id,
        "workspace_mode": "plot",
        "plot_phase": state.phase.value,
        "workspace_name": state.workspace_name,
        "title": state.workspace_name,
        "source_script_path": state.current_script_path,
        "plot_type": plot_type,
        "annotation_count": 0,
        "pending_annotation_count": 0,
        "checked_out_version_id": "",
        "created_at": state.created_at,
        "updated_at": state.updated_at,
    }


def _workspace_summary_sort_key(summary: Mapping[str, object]) -> tuple[str, str, str]:
    updated_at = str(summary.get("updated_at") or summary.get("created_at") or "")
    created_at = str(summary.get("created_at") or "")
    workspace_id = str(summary.get("id") or "")
    return (updated_at, created_at, workspace_id)


def _list_session_summaries() -> list[dict[str, object]]:
    return session_services.list_session_summaries(_current_runtime())


def _last_modified_session() -> PlotSession | None:
    _ensure_session_store_loaded()
    sessions = _runtime_sessions_map()
    if not sessions:
        return None
    return max(sessions.values(), key=_session_sort_key)


def _plot_mode_sort_key(state: PlotModeState) -> tuple[str, str, str]:
    return (state.updated_at or state.created_at, state.created_at, state.id)


def _last_modified_plot_mode() -> PlotModeState | None:
    _ensure_session_store_loaded()
    active_plot_mode = _runtime_plot_mode_state_value()
    if active_plot_mode is None or not _plot_mode_is_workspace(active_plot_mode):
        return None
    return active_plot_mode


def _active_workspace_id() -> str | None:
    active_session = _runtime_active_session_value()
    active_plot_mode = _runtime_plot_mode_state_value()
    if active_session is not None:
        return _session_workspace_id(active_session)
    if active_plot_mode is not None and _plot_mode_is_workspace(active_plot_mode):
        return active_plot_mode.id
    return None


def _restore_latest_workspace() -> (
    tuple[Literal["annotation", "plot"], PlotSession | PlotModeState] | None
):
    return session_services.restore_latest_workspace(_current_runtime())


def _bootstrap_payload(
    *,
    mode: Literal["annotation", "plot"],
    session: PlotSession | None,
    plot_mode: PlotModeState | None,
) -> dict[str, object]:
    active_session_id = session.id if session is not None else None
    active_workspace_id = (
        _session_workspace_id(session)
        if session is not None
        else plot_mode.id
        if plot_mode is not None
        else _active_workspace_id()
    )
    return {
        "mode": mode,
        "session": session.model_dump(mode="json") if session is not None else None,
        "plot_mode": (
            plot_mode.model_dump(mode="json") if plot_mode is not None else None
        ),
        "sessions": _list_session_summaries(),
        "active_session_id": active_session_id,
        "active_workspace_id": active_workspace_id,
        "update_status": _build_update_status_payload(allow_network=False),
    }


def _preferences_path() -> Path:
    root = _state_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / _preferences_file_name


def _normalize_preference_value(value: object | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _load_preferences_data() -> dict[str, object]:
    preferences_path = _preferences_path()
    if not preferences_path.exists():
        return {}

    try:
        raw = json.loads(_read_file_text(preferences_path))
    except (OSError, json.JSONDecodeError):
        return {}

    return raw if isinstance(raw, dict) else {}


def _load_fix_preferences() -> tuple[FixRunner, str | None, str | None]:
    preferences = _load_preferences_data()
    runner = _normalize_fix_runner(
        preferences.get("fix_runner"),
        default=_default_fix_runner,
    )
    model = _normalize_preference_value(preferences.get("fix_model"))
    variant = _normalize_preference_value(preferences.get("fix_variant"))
    if model is None:
        return runner, None, None
    return runner, model, variant


def _save_fix_preferences(
    *, runner: FixRunner, model: str | None, variant: str | None
) -> None:
    preferences = _load_preferences_data()
    preferences["fix_runner"] = runner
    if model is None:
        preferences.pop("fix_model", None)
        preferences.pop("fix_variant", None)
    else:
        preferences["fix_model"] = model
        if variant is None:
            preferences.pop("fix_variant", None)
        else:
            preferences["fix_variant"] = variant

    preferences_path = _preferences_path()
    tmp_path = preferences_path.with_name(f".{preferences_path.name}.tmp")
    tmp_path.write_text(
        json.dumps(preferences, indent=2, sort_keys=True), encoding="utf-8"
    )
    tmp_path.replace(preferences_path)


def _load_python_interpreter_preference() -> str | None:
    preferences = _load_preferences_data()
    return _normalize_preference_value(
        preferences.get(_python_interpreter_preference_key)
    )


def _save_python_interpreter_preference(path: str | None) -> None:
    preferences = _load_preferences_data()
    if path is None:
        preferences.pop(_python_interpreter_preference_key, None)
    else:
        preferences[_python_interpreter_preference_key] = path

    preferences_path = _preferences_path()
    tmp_path = preferences_path.with_name(f".{preferences_path.name}.tmp")
    tmp_path.write_text(
        json.dumps(preferences, indent=2, sort_keys=True), encoding="utf-8"
    )
    tmp_path.replace(preferences_path)


def _python_context_dir(session: PlotSession | None = None) -> Path:
    if session is not None and session.source_script_path:
        script_path = _resolve_session_file_path(session, session.source_script_path)
        return script_path.parent.resolve()
    if session is not None:
        return _workspace_for_session(session)
    return _workspace_dir


def _is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _is_openplot_app_launcher_path(path: Path) -> bool:
    if getattr(sys, "frozen", False):
        try:
            return path.resolve() == Path(sys.executable).resolve()
        except OSError:
            return False
    normalized = str(path).lower()
    return path.name.lower() == "openplot" and ".app/contents/macos/" in normalized


def _should_probe_with_current_runtime(interpreter_path: Path) -> bool:
    if not _is_openplot_app_launcher_path(interpreter_path):
        return False

    try:
        return interpreter_path.resolve() == Path(sys.executable).resolve()
    except OSError:
        return False


def _probe_current_runtime_packages() -> list[str]:
    modules: set[str] = set()
    for module in pkgutil.iter_modules():
        modules.add(module.name)

    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    packages: list[str] = []
    for name in modules:
        if not isinstance(name, str):
            continue
        if not name or name in stdlib or name.startswith("_"):
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        packages.append(name)

    return sorted(set(packages))


def _probe_python_interpreter(
    interpreter_path: Path,
    *,
    timeout_s: float = 4.0,
) -> tuple[str | None, str | None]:
    if not _is_executable_file(interpreter_path):
        return None, f"Interpreter is not executable: {interpreter_path}"

    if _should_probe_with_current_runtime(interpreter_path):
        return sys.version.split()[0], None

    probe_code = (
        "import json,sys; print(json.dumps({'version': sys.version.split()[0], "
        "'executable': sys.executable}))"
    )

    try:
        result = subprocess.run(
            [str(interpreter_path), "-c", probe_code],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            **_no_window_kwargs(),
        )
    except OSError as exc:
        return None, str(exc)
    except subprocess.TimeoutExpired:
        return None, f"Timed out validating interpreter: {interpreter_path}"

    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip() or (
            f"Interpreter exited with code {result.returncode}"
        )
        return None, details

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return None, f"Interpreter probe returned no output: {interpreter_path}"

    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return None, f"Failed to parse interpreter probe output: {exc}"

    version = payload.get("version") if isinstance(payload, dict) else None
    if not isinstance(version, str) or not version.strip():
        return None, "Interpreter probe did not report a valid Python version"

    return version.strip(), None


def _validated_python_candidate(
    candidate_path: Path,
    *,
    source: str,
) -> tuple[dict[str, str] | None, str | None]:
    expanded = candidate_path.expanduser()
    if not expanded.exists():
        return None, f"Interpreter not found: {expanded}"

    absolute_path = expanded if expanded.is_absolute() else (_workspace_dir / expanded)
    absolute_path = absolute_path.absolute()
    version, error = _probe_python_interpreter(absolute_path)
    if version is None:
        return None, error

    return {
        "path": str(absolute_path),
        "source": source,
        "version": version,
    }, None


def _auto_python_search_dirs(context_dir: Path) -> list[Path]:
    ancestry = [context_dir, *context_dir.parents]
    marker_index = next(
        (
            index
            for index, directory in enumerate(ancestry)
            if any((directory / marker).exists() for marker in _python_project_markers)
        ),
        None,
    )

    if marker_index is None:
        return [context_dir]

    return ancestry[: marker_index + 1]


def _discover_python_interpreter_candidates(context_dir: Path) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    def append_candidate(path: Path, *, source: str) -> None:
        candidate, _error = _validated_python_candidate(path, source=source)
        if candidate is None:
            return
        key = candidate["path"]
        if key in seen_paths:
            return
        seen_paths.add(key)
        candidates.append(candidate)

    for directory in _auto_python_search_dirs(context_dir):
        for relative in _auto_python_relative_paths:
            append_candidate(directory / relative, source="nearest-venv")

    append_candidate(Path(sys.executable), source="app-runtime")

    virtual_env = os.getenv("VIRTUAL_ENV")
    if virtual_env:
        append_candidate(
            Path(virtual_env) / "bin" / "python", source="active-virtualenv"
        )

    python3_from_path = shutil.which("python3")
    if python3_from_path:
        append_candidate(Path(python3_from_path), source="path-python3")

    python_from_path = shutil.which("python")
    if python_from_path:
        append_candidate(Path(python_from_path), source="path-python")

    return candidates


def _built_in_python_candidate() -> tuple[dict[str, str] | None, str | None]:
    built_in_override = _normalize_preference_value(
        os.getenv("OPENPLOT_BUILTIN_PYTHON")
    )
    built_in_path = (
        Path(built_in_override) if built_in_override else Path(sys.executable)
    )
    return _validated_python_candidate(built_in_path, source="built-in")


def _probe_python_packages(
    interpreter_path: Path,
    *,
    timeout_s: float = 8.0,
) -> tuple[list[str], str | None]:
    if not _is_executable_file(interpreter_path):
        return [], (f"Interpreter is not executable: {interpreter_path}")

    if _should_probe_with_current_runtime(interpreter_path):
        try:
            return _probe_current_runtime_packages(), None
        except Exception as exc:
            return [], str(exc)

    probe_code = (
        "import json, pkgutil, site, sys\n"
        "paths = []\n"
        "seen = set()\n"
        "def add_path(raw):\n"
        "    if not isinstance(raw, str):\n"
        "        return\n"
        "    value = raw.strip()\n"
        "    if not value or value in seen:\n"
        "        return\n"
        "    seen.add(value)\n"
        "    paths.append(value)\n"
        "for item in (getattr(site, 'getsitepackages', lambda: [])() or []):\n"
        "    add_path(item)\n"
        "user_site = getattr(site, 'getusersitepackages', lambda: '')()\n"
        "if isinstance(user_site, str):\n"
        "    add_path(user_site)\n"
        "for item in sys.path:\n"
        "    if isinstance(item, str) and ('site-packages' in item or 'dist-packages' in item):\n"
        "        add_path(item)\n"
        "modules = set()\n"
        "for path in paths:\n"
        "    try:\n"
        "        for mod in pkgutil.iter_modules([path]):\n"
        "            modules.add(mod.name)\n"
        "    except Exception:\n"
        "        continue\n"
        "stdlib = set(getattr(sys, 'stdlib_module_names', ()))\n"
        "available = sorted(\n"
        "    name\n"
        "    for name in modules\n"
        "    if isinstance(name, str) and name and name not in stdlib\n"
        ")\n"
        "print(json.dumps(available))\n"
    )

    try:
        result = subprocess.run(
            [str(interpreter_path), "-c", probe_code],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            **_no_window_kwargs(),
        )
    except OSError as exc:
        return [], str(exc)
    except subprocess.TimeoutExpired:
        return [], (
            f"Timed out validating packages for interpreter: {interpreter_path}"
        )

    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip() or (
            f"Interpreter exited with code {result.returncode}"
        )
        return [], details

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return [], (f"Interpreter package probe returned no output: {interpreter_path}")

    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return [], (f"Failed to parse package probe output: {exc}")

    if not isinstance(payload, list):
        return [], "Package probe did not return a list"

    packages: list[str] = []
    for item in payload:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        packages.append(name)

    return sorted(set(packages)), None


def _resolve_python_interpreter_state(
    session: PlotSession | None = None,
) -> dict[str, object]:
    context_dir = _python_context_dir(session)
    candidates = _discover_python_interpreter_candidates(context_dir)
    configured_path = _load_python_interpreter_preference()
    mode: Literal["builtin", "manual"] = "manual" if configured_path else "builtin"
    configured_error: str | None = None

    built_in_candidate, _built_in_error = _built_in_python_candidate()
    if built_in_candidate is not None:
        default_runtime = built_in_candidate
        if all(
            candidate.get("path") != built_in_candidate["path"]
            for candidate in candidates
        ):
            candidates = [built_in_candidate, *candidates]
    else:
        default_runtime = {
            "path": str(Path(sys.executable).expanduser().resolve()),
            "source": "built-in",
            "version": "",
        }
        candidates = [default_runtime, *candidates]

    resolved = default_runtime

    if configured_path:
        manual_candidate, manual_error = _validated_python_candidate(
            Path(configured_path),
            source="manual",
        )
        if manual_candidate is None:
            configured_error = manual_error or (
                f"Configured interpreter is unavailable: {configured_path}"
            )
        else:
            resolved = manual_candidate
            if all(
                candidate.get("path") != manual_candidate["path"]
                for candidate in candidates
            ):
                candidates = [*candidates, manual_candidate]

    if resolved is None:
        resolved = {
            "path": str(Path(sys.executable).expanduser().resolve()),
            "source": "built-in",
            "version": "",
        }

    default_path = str(default_runtime.get("path", "")).strip()
    default_available_packages: list[str]
    default_package_probe_error: str | None
    if default_path:
        default_available_packages, default_package_probe_error = (
            _probe_python_packages(
                Path(default_path),
            )
        )
    else:
        default_available_packages = []
        default_package_probe_error = "Default runtime path is empty"

    resolved_path = str(resolved.get("path", "")).strip()
    available_packages: list[str]
    package_probe_error: str | None
    if resolved_path == default_path:
        available_packages = list(default_available_packages)
        package_probe_error = default_package_probe_error
    elif resolved_path:
        available_packages, package_probe_error = _probe_python_packages(
            Path(resolved_path),
        )
    else:
        available_packages = []
        package_probe_error = "Resolved interpreter path is empty"

    return {
        "mode": mode,
        "configured_path": configured_path,
        "configured_error": configured_error,
        "resolved_path": resolved_path,
        "resolved_source": str(resolved.get("source", "")),
        "resolved_version": str(resolved.get("version", "")),
        "default_path": default_path,
        "default_version": str(default_runtime.get("version", "")),
        "default_available_packages": default_available_packages,
        "default_available_package_count": len(default_available_packages),
        "default_package_probe_error": default_package_probe_error,
        "available_packages": available_packages,
        "available_package_count": len(available_packages),
        "package_probe_error": package_probe_error,
        "data_root": str(_data_root()),
        "state_root": str(_state_root()),
        "context_dir": str(context_dir),
        "candidates": candidates,
    }


def _resolve_python_executable(session: PlotSession | None = None) -> str:
    state = _resolve_python_interpreter_state(session)
    resolved_path = state.get("resolved_path")
    if isinstance(resolved_path, str) and resolved_path:
        return resolved_path
    return sys.executable


def _session_artifacts_root(session: PlotSession) -> Path:
    if session.artifacts_root:
        root = Path(session.artifacts_root)
    else:
        root = _state_root() / "sessions" / session.id
        session.artifacts_root = str(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _is_managed_workspace_path(path: Path) -> bool:
    resolved = path.resolve()
    for root in (_sessions_root_dir().resolve(), _plot_mode_root_dir().resolve()):
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _version_artifact_dir(session: PlotSession, version_id: str) -> Path:
    version_dir = _session_artifacts_root(session) / "versions" / version_id
    version_dir.mkdir(parents=True, exist_ok=True)
    return version_dir


def _new_run_output_dir(session: PlotSession) -> Path:
    run_dir = _session_artifacts_root(session) / "runs" / _new_id()
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_version_artifacts(
    session: PlotSession,
    version_id: str,
    *,
    script: str | None,
    plot_path: str,
) -> tuple[str | None, str]:
    """Persist immutable script/plot artifacts for one version."""
    plot_src = Path(plot_path).resolve()
    if not plot_src.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Plot artifact not found on disk: {plot_src}",
        )

    version_dir = _version_artifact_dir(session, version_id)

    script_artifact_path: str | None = None
    if script is not None:
        script_file = version_dir / "script.py"
        script_file.write_text(script, encoding="utf-8")
        script_artifact_path = str(script_file)

    ext = plot_src.suffix.lower() or ".png"
    plot_file = version_dir / f"plot{ext}"
    shutil.copy2(plot_src, plot_file)

    return script_artifact_path, str(plot_file)


def _delete_version_artifacts(session: PlotSession, version_id: str) -> None:
    version_dir = _session_artifacts_root(session) / "versions" / version_id
    shutil.rmtree(version_dir, ignore_errors=True)


def _find_branch(session: PlotSession, branch_id: str) -> Branch | None:
    return next((b for b in session.branches if b.id == branch_id), None)


def _get_branch(session: PlotSession, branch_id: str) -> Branch:
    branch = _find_branch(session, branch_id)
    if branch is None:
        raise HTTPException(status_code=404, detail=f"Branch not found: {branch_id}")
    return branch


def _active_branch(session: PlotSession) -> Branch:
    if not session.active_branch_id:
        raise HTTPException(status_code=409, detail="Session has no active branch")
    return _get_branch(session, session.active_branch_id)


def _find_version(session: PlotSession, version_id: str) -> VersionNode | None:
    return next((v for v in session.versions if v.id == version_id), None)


def _get_version(session: PlotSession, version_id: str) -> VersionNode:
    version = _find_version(session, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_id}")
    return version


def _safe_read_text(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return _read_file_text(p)


def _media_type_for_plot_path(plot_path: Path) -> str:
    media_types = {
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".pdf": "application/pdf",
    }
    return media_types.get(plot_path.suffix.lower(), "application/octet-stream")


def _branch_chain(session: PlotSession, head_version_id: str) -> list[VersionNode]:
    """Return root->head chain for a branch head pointer."""
    by_id = {v.id: v for v in session.versions}
    chain: list[VersionNode] = []
    cursor = head_version_id
    seen: set[str] = set()
    while cursor:
        if cursor in seen:
            break
        seen.add(cursor)
        node = by_id.get(cursor)
        if node is None:
            break
        chain.append(node)
        cursor = node.parent_version_id or ""
    chain.reverse()
    return chain


def _rebuild_revision_history(session: PlotSession) -> None:
    """Keep legacy linear revision list aligned with active branch."""
    if not session.active_branch_id:
        session.revision_history = []
        return
    branch = _get_branch(session, session.active_branch_id)
    chain = _branch_chain(session, branch.head_version_id)
    revisions: list[Revision] = []
    for node in chain:
        revisions.append(
            Revision(
                script=_safe_read_text(node.script_artifact_path) or "",
                plot_path=node.plot_artifact_path,
                plot_type=node.plot_type,
                timestamp=node.timestamp,
            )
        )
    session.revision_history = revisions


def _checkout_version(
    session: PlotSession,
    version_id: str,
    *,
    branch_id: str | None = None,
) -> VersionNode:
    """Set session view pointers to one version."""
    if branch_id is not None:
        _get_branch(session, branch_id)
        session.active_branch_id = branch_id
    version = _get_version(session, version_id)
    session.checked_out_version_id = version.id
    session.current_plot = version.plot_artifact_path
    session.plot_type = version.plot_type
    session.source_script = _safe_read_text(version.script_artifact_path)
    _rebuild_revision_history(session)
    return version


def _next_branch_name(session: PlotSession) -> str:
    taken = {b.name for b in session.branches}
    index = 1
    while True:
        name = f"branch-{index}"
        if name not in taken:
            return name
        index += 1


def _create_branch(session: PlotSession, *, base_version_id: str) -> Branch:
    branch = Branch(
        id=_new_id(),
        name=_next_branch_name(session),
        base_version_id=base_version_id,
        head_version_id=base_version_id,
    )
    session.branches.append(branch)
    return branch


def _resolve_target_annotation(
    session: PlotSession,
    annotation_id: str | None,
) -> Annotation:
    if annotation_id:
        ann = next((a for a in session.annotations if a.id == annotation_id), None)
        if ann is None:
            raise HTTPException(status_code=404, detail="Annotation not found")
        if ann.status != AnnotationStatus.pending:
            raise HTTPException(
                status_code=409,
                detail="Target annotation is already addressed",
            )
        return ann

    pending = pending_annotations_for_context(session)
    if not pending:
        raise HTTPException(
            status_code=409,
            detail="No pending annotations in the current branch/context",
        )
    return pending[0]


async def _consume_fix_stream(
    *,
    job: FixJob,
    step: FixJobStep,
    runner: FixRunner,
    process: asyncio.subprocess.Process,
    stream_name: Literal["stdout", "stderr"],
    stream: asyncio.StreamReader | None,
    sink: list[str],
) -> None:
    if stream is None:
        return

    buffered = ""
    question_tool_seen = False

    while True:
        chunk_bytes = await stream.read(8192)
        if not chunk_bytes:
            break

        chunk = chunk_bytes.decode("utf-8", errors="replace")
        sink.append(chunk)

        buffered += chunk
        while True:
            newline_index = buffered.find("\n")
            if newline_index < 0:
                break
            line = buffered[: newline_index + 1]
            buffered = buffered[newline_index + 1 :]

            parsed = _parse_json_event_line(line) if stream_name == "stdout" else None
            if (
                parsed is not None
                and not question_tool_seen
                and _parsed_runner_uses_builtin_question_tool(runner, parsed)
            ):
                question_tool_seen = True
                await _terminate_fix_process(process)
            await _broadcast_fix_job_log(
                job_id=job.id,
                step_index=step.index,
                annotation_id=step.annotation_id,
                stream=stream_name,
                chunk=line,
                parsed=parsed,
            )

    if buffered:
        parsed = _parse_json_event_line(buffered) if stream_name == "stdout" else None
        if (
            parsed is not None
            and not question_tool_seen
            and _parsed_runner_uses_builtin_question_tool(runner, parsed)
        ):
            await _terminate_fix_process(process)
        await _broadcast_fix_job_log(
            job_id=job.id,
            step_index=step.index,
            annotation_id=step.annotation_id,
            stream=stream_name,
            chunk=buffered,
            parsed=parsed,
        )


async def _run_fix_iteration_command(
    *,
    job: FixJob,
    step: FixJobStep,
    command: list[str],
    display_command: list[str] | None = None,
    cwd: Path | None = None,
    env_overrides: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    step.command = display_command or command

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    resolved_cwd = (cwd or _workspace_dir).resolve()
    process_env = _subprocess_env(overrides=env_overrides)

    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(resolved_cwd),
        env=process_env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **_hidden_window_kwargs(),
        **({"start_new_session": True} if sys.platform != "win32" else {}),
    )
    _runtime_fix_job_processes_map()[job.id] = process

    stdout_task = asyncio.create_task(
        _consume_fix_stream(
            job=job,
            step=step,
            runner=job.runner,
            process=process,
            stream_name="stdout",
            stream=process.stdout,
            sink=stdout_chunks,
        )
    )
    stderr_task = asyncio.create_task(
        _consume_fix_stream(
            job=job,
            step=step,
            runner=job.runner,
            process=process,
            stream_name="stderr",
            stream=process.stderr,
            sink=stderr_chunks,
        )
    )

    try:
        await process.wait()
    finally:
        for stream_label, task in (("stdout", stdout_task), ("stderr", stderr_task)):
            if task.done():
                with suppress(asyncio.CancelledError):
                    try:
                        _ = task.result()
                    except Exception as exc:
                        stderr_chunks.append(
                            (
                                "[openplot warning] "
                                f"failed to read {stream_label} stream: {exc}\n"
                            )
                        )
                continue
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        _runtime_fix_job_processes_map().pop(job.id, None)

    step.exit_code = process.returncode
    raw_stdout = "".join(stdout_chunks)
    raw_stderr = "".join(stderr_chunks)
    step.stdout = _truncate_output(raw_stdout)
    step.stderr = _truncate_output(raw_stderr)
    return raw_stdout, raw_stderr


async def _run_opencode_fix_iteration(
    job: FixJob, step: FixJobStep, *, extra_prompt: str | None = None
) -> None:
    session = _session_for_fix_job(job)
    workspace_dir = _workspace_dir_for_fix_job(job, session)
    env_overrides = _fix_runner_env_overrides(job, session)
    resume_session_id = _runner_session_id_for_session(session, "opencode")
    command = _build_opencode_plot_fix_command(
        model=job.model,
        variant=job.variant,
        workspace_dir=workspace_dir,
        resume_session_id=resume_session_id,
        extra_prompt=extra_prompt,
    )
    display_command = [*command[:-1], "<plot-fix prompt>"]
    raw_stdout, raw_stderr = await _run_fix_iteration_command(
        job=job,
        step=step,
        command=command,
        display_command=display_command,
        cwd=workspace_dir,
        env_overrides=env_overrides,
    )

    if _runner_output_used_builtin_question_tool("opencode", raw_stdout):
        _clear_runner_session_id_for_session(session, "opencode")
        command = _build_opencode_plot_fix_command(
            model=job.model,
            variant=job.variant,
            workspace_dir=workspace_dir,
            resume_session_id=None,
            extra_prompt=_append_retry_instruction(
                extra_prompt or "", _fix_mode_question_tool_retry_instruction()
            ),
        )
        display_command = [*command[:-1], "<plot-fix prompt>"]
        raw_stdout, raw_stderr = await _run_fix_iteration_command(
            job=job,
            step=step,
            command=command,
            display_command=display_command,
            cwd=workspace_dir,
            env_overrides=env_overrides,
        )

    if (
        step.exit_code != 0
        and resume_session_id
        and _is_resume_session_error(
            "opencode", stdout_text=raw_stdout, stderr_text=raw_stderr
        )
    ):
        _clear_runner_session_id_for_session(session, "opencode")
        command = _build_opencode_plot_fix_command(
            model=job.model,
            variant=job.variant,
            workspace_dir=workspace_dir,
            resume_session_id=None,
            extra_prompt=extra_prompt,
        )
        display_command = [*command[:-1], "<plot-fix prompt>"]
        raw_stdout, raw_stderr = await _run_fix_iteration_command(
            job=job,
            step=step,
            command=command,
            display_command=display_command,
            cwd=workspace_dir,
            env_overrides=env_overrides,
        )

    if _runner_output_used_builtin_question_tool("opencode", raw_stdout):
        step.exit_code = 1
        step.stderr = _truncate_output(
            "Runner attempted an unsupported built-in question tool during fix mode."
        )

    discovered_session_id = _extract_runner_session_id_from_output(
        "opencode", raw_stdout
    )
    if discovered_session_id is not None:
        _set_runner_session_id_for_session(
            session,
            runner="opencode",
            session_id=discovered_session_id,
        )


async def _run_codex_fix_iteration(
    job: FixJob, step: FixJobStep, *, extra_prompt: str | None = None
) -> None:
    session = _session_for_fix_job(job)
    workspace_dir = _workspace_dir_for_fix_job(job, session)
    env_overrides = _fix_runner_env_overrides(job, session)
    resume_session_id = _runner_session_id_for_session(session, "codex")
    command = _build_codex_plot_fix_command(
        model=job.model,
        variant=job.variant,
        workspace_dir=workspace_dir,
        resume_session_id=resume_session_id,
        extra_prompt=extra_prompt,
    )
    display_command = [*command[:-1], "<plot-fix prompt>"]
    raw_stdout, raw_stderr = await _run_fix_iteration_command(
        job=job,
        step=step,
        command=command,
        display_command=display_command,
        cwd=workspace_dir,
        env_overrides=env_overrides,
    )

    if _runner_output_used_builtin_question_tool("codex", raw_stdout):
        _clear_runner_session_id_for_session(session, "codex")
        command = _build_codex_plot_fix_command(
            model=job.model,
            variant=job.variant,
            workspace_dir=workspace_dir,
            resume_session_id=None,
            extra_prompt=_append_retry_instruction(
                extra_prompt or "", _fix_mode_question_tool_retry_instruction()
            ),
        )
        display_command = [*command[:-1], "<plot-fix prompt>"]
        raw_stdout, raw_stderr = await _run_fix_iteration_command(
            job=job,
            step=step,
            command=command,
            display_command=display_command,
            cwd=workspace_dir,
            env_overrides=env_overrides,
        )

    if (
        step.exit_code != 0
        and resume_session_id
        and _is_resume_session_error(
            "codex", stdout_text=raw_stdout, stderr_text=raw_stderr
        )
    ):
        _clear_runner_session_id_for_session(session, "codex")
        command = _build_codex_plot_fix_command(
            model=job.model,
            variant=job.variant,
            workspace_dir=workspace_dir,
            resume_session_id=None,
            extra_prompt=extra_prompt,
        )
        display_command = [*command[:-1], "<plot-fix prompt>"]
        raw_stdout, raw_stderr = await _run_fix_iteration_command(
            job=job,
            step=step,
            command=command,
            display_command=display_command,
            cwd=workspace_dir,
            env_overrides=env_overrides,
        )

    if _runner_output_used_builtin_question_tool("codex", raw_stdout):
        step.exit_code = 1
        step.stderr = _truncate_output(
            "Runner attempted an unsupported built-in question tool during fix mode."
        )

    discovered_session_id = _extract_runner_session_id_from_output("codex", raw_stdout)
    if discovered_session_id is not None:
        _set_runner_session_id_for_session(
            session,
            runner="codex",
            session_id=discovered_session_id,
        )


async def _run_claude_fix_iteration(
    job: FixJob, step: FixJobStep, *, extra_prompt: str | None = None
) -> None:
    session = _session_for_fix_job(job)
    workspace_dir = _workspace_dir_for_fix_job(job, session)
    env_overrides = _fix_runner_env_overrides(job, session)
    resume_session_id = _runner_session_id_for_session(session, "claude")
    command = _build_claude_plot_fix_command(
        model=job.model,
        variant=job.variant,
        workspace_dir=workspace_dir,
        resume_session_id=resume_session_id,
        extra_prompt=extra_prompt,
    )
    display_command = [*command]
    if len(display_command) >= 3:
        display_command[2] = "<plot-fix prompt>"
    raw_stdout, raw_stderr = await _run_fix_iteration_command(
        job=job,
        step=step,
        command=command,
        display_command=display_command,
        cwd=workspace_dir,
        env_overrides=env_overrides,
    )
    reported_error = _extract_runner_reported_error(
        "claude",
        stdout_text=raw_stdout,
        stderr_text=raw_stderr,
    )

    if _runner_output_used_builtin_question_tool("claude", raw_stdout):
        _clear_runner_session_id_for_session(session, "claude")
        command = _build_claude_plot_fix_command(
            model=job.model,
            variant=job.variant,
            workspace_dir=workspace_dir,
            resume_session_id=None,
            extra_prompt=_append_retry_instruction(
                extra_prompt or "", _fix_mode_question_tool_retry_instruction()
            ),
        )
        display_command = [*command]
        if len(display_command) >= 3:
            display_command[2] = "<plot-fix prompt>"
        raw_stdout, raw_stderr = await _run_fix_iteration_command(
            job=job,
            step=step,
            command=command,
            display_command=display_command,
            cwd=workspace_dir,
            env_overrides=env_overrides,
        )
        reported_error = _extract_runner_reported_error(
            "claude",
            stdout_text=raw_stdout,
            stderr_text=raw_stderr,
        )

    if resume_session_id and (
        (
            step.exit_code != 0
            and _is_resume_session_error(
                "claude",
                stdout_text=raw_stdout,
                stderr_text=raw_stderr,
            )
        )
        or reported_error is not None
    ):
        _clear_runner_session_id_for_session(session, "claude")
        command = _build_claude_plot_fix_command(
            model=job.model,
            variant=job.variant,
            workspace_dir=workspace_dir,
            resume_session_id=None,
            extra_prompt=extra_prompt,
        )
        display_command = [*command]
        if len(display_command) >= 3:
            display_command[2] = "<plot-fix prompt>"
        raw_stdout, raw_stderr = await _run_fix_iteration_command(
            job=job,
            step=step,
            command=command,
            display_command=display_command,
            cwd=workspace_dir,
            env_overrides=env_overrides,
        )
        reported_error = _extract_runner_reported_error(
            "claude",
            stdout_text=raw_stdout,
            stderr_text=raw_stderr,
        )

    if _runner_output_used_builtin_question_tool("claude", raw_stdout):
        step.exit_code = 1
        step.stderr = _truncate_output(
            "Runner attempted an unsupported built-in question tool during fix mode."
        )

    if reported_error is not None and step.exit_code == 0:
        step.exit_code = 1
        existing_stderr = step.stderr.strip()
        if not existing_stderr:
            step.stderr = reported_error
        elif reported_error not in existing_stderr:
            step.stderr = f"{existing_stderr}\n{reported_error}"

    discovered_session_id = _extract_runner_session_id_from_output("claude", raw_stdout)
    if discovered_session_id is not None:
        _set_runner_session_id_for_session(
            session,
            runner="claude",
            session_id=discovered_session_id,
        )


async def _terminate_fix_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return

    used_process_group = False
    if sys.platform != "win32" and process.pid > 0:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            used_process_group = True
        except ProcessLookupError:
            return
        except OSError:
            used_process_group = False

    if not used_process_group:
        process.terminate()

    try:
        await asyncio.wait_for(process.wait(), timeout=5.0)
        return
    except asyncio.TimeoutError:
        pass

    if process.returncode is not None:
        return

    if used_process_group and process.pid > 0:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError:
            process.kill()
    else:
        process.kill()

    with suppress(Exception):
        await process.wait()


def _fix_retry_context(step: FixJobStep, *, annotation_id: str) -> str:
    details: list[str] = [
        f"The previous attempt for annotation {annotation_id} did not finish successfully.",
    ]
    if step.error:
        details.append(step.error)
    stderr_text = step.stderr.strip()
    if stderr_text:
        details.append(stderr_text[-3000:])
    stdout_text = step.stdout.strip()
    if stdout_text and "error" in stdout_text.lower():
        details.append(stdout_text[-3000:])
    details.append(
        "Use the error details above to correct the script and submit a runnable update for the same annotation."
    )
    return " ".join(part.strip() for part in details if part.strip())


async def _run_fix_job_loop(
    job_id: str,
    *,
    runtime: BackendRuntime | None = None,
) -> None:
    resolved_runtime = runtime or _bound_runtime or get_shared_runtime()

    async def _run() -> None:
        fix_jobs = _runtime_fix_jobs_map()
        fix_job_processes = _runtime_fix_job_processes_map()
        fix_job_tasks = _runtime_fix_job_tasks_map()
        job = fix_jobs.get(job_id)
        if job is None:
            return

        job.status = FixJobStatus.running
        job.started_at = _now_iso()
        await _broadcast_fix_job(job)

        try:
            while True:
                if job.status == FixJobStatus.cancelled:
                    if not job.finished_at:
                        job.finished_at = _now_iso()
                    await _broadcast_fix_job(job)
                    return

                session = _session_for_fix_job(job)
                target_branch = _get_branch(session, job.branch_id)
                if (
                    session.active_branch_id != job.branch_id
                    or session.checked_out_version_id != target_branch.head_version_id
                ):
                    _checkout_version(
                        session, target_branch.head_version_id, branch_id=job.branch_id
                    )
                    await _broadcast(
                        {
                            "type": "plot_updated",
                            "session_id": session.id,
                            "version_id": session.checked_out_version_id,
                            "plot_type": session.plot_type,
                            "revision": len(session.revision_history),
                            "active_branch_id": session.active_branch_id,
                            "checked_out_version_id": session.checked_out_version_id,
                            "reason": "fix_job_branch_restore",
                        }
                    )

                pending = pending_annotations_for_context(session)
                job.total_annotations = max(
                    job.total_annotations,
                    job.completed_annotations + len(pending),
                )
                if not pending:
                    job.status = FixJobStatus.completed
                    job.finished_at = _now_iso()
                    await _broadcast_fix_job(job)
                    return

                target_annotation = pending[0]
                step = FixJobStep(
                    index=len(job.steps) + 1,
                    annotation_id=target_annotation.id,
                    status=FixStepStatus.running,
                    started_at=_now_iso(),
                )
                job.steps.append(step)
                await _broadcast_fix_job(job)

                retry_context: str | None = None
                for attempt_index in range(1, _fix_job_retry_limit + 1):
                    if job.runner == "codex":
                        await _run_codex_fix_iteration(
                            job, step, extra_prompt=retry_context
                        )
                    elif job.runner == "claude":
                        await _run_claude_fix_iteration(
                            job, step, extra_prompt=retry_context
                        )
                    else:
                        await _run_opencode_fix_iteration(
                            job, step, extra_prompt=retry_context
                        )

                    refreshed_session = _session_for_fix_job(job)
                    refreshed_annotation = next(
                        (
                            annotation
                            for annotation in refreshed_session.annotations
                            if annotation.id == target_annotation.id
                        ),
                        None,
                    )
                    addressed = (
                        refreshed_annotation is not None
                        and refreshed_annotation.status == AnnotationStatus.addressed
                    )
                    if step.exit_code == 0 and addressed:
                        break
                    if attempt_index >= _fix_job_retry_limit:
                        break
                    retry_context = _fix_retry_context(
                        step, annotation_id=target_annotation.id
                    )

                step.finished_at = _now_iso()
                if job.status == FixJobStatus.cancelled:
                    step.status = FixStepStatus.cancelled
                    if not job.finished_at:
                        job.finished_at = _now_iso()
                    await _broadcast_fix_job(job)
                    return

                if step.exit_code != 0:
                    step.status = FixStepStatus.failed
                    if _is_rate_limit_error(
                        job.runner,
                        stdout_text=step.stdout,
                        stderr_text=step.stderr,
                    ):
                        step.error = _format_rate_limit_error(job.runner)
                        job.last_error = step.error
                    else:
                        step.error = f"{job.runner} exited with status {step.exit_code}"
                        stderr_summary = step.stderr.strip().splitlines()
                        if stderr_summary:
                            job.last_error = stderr_summary[-1]
                        else:
                            job.last_error = step.error
                    job.status = FixJobStatus.failed
                    job.finished_at = _now_iso()
                    await _broadcast_fix_job(job)
                    return

                refreshed_session = _session_for_fix_job(job)
                refreshed_annotation = next(
                    (
                        annotation
                        for annotation in refreshed_session.annotations
                        if annotation.id == target_annotation.id
                    ),
                    None,
                )
                if (
                    refreshed_annotation is None
                    or refreshed_annotation.status != AnnotationStatus.addressed
                ):
                    step.status = FixStepStatus.failed
                    step.error = "Fix command completed but the target annotation was not addressed."
                    job.last_error = step.error
                    job.status = FixJobStatus.failed
                    job.finished_at = _now_iso()
                    await _broadcast_fix_job(job)
                    return

                step.status = FixStepStatus.completed
                step.error = None
                job.completed_annotations += 1
                remaining = len(pending_annotations_for_context(refreshed_session))
                job.total_annotations = max(
                    job.total_annotations,
                    job.completed_annotations + remaining,
                )
                await _broadcast_fix_job(job)
        except Exception as exc:
            if not _is_terminal_fix_job_status(job.status):
                if job.steps and job.steps[-1].status == FixStepStatus.running:
                    job.steps[-1].status = FixStepStatus.failed
                    job.steps[-1].finished_at = _now_iso()
                    job.steps[-1].error = str(exc)
                job.status = FixJobStatus.failed
                job.last_error = str(exc)
                job.finished_at = _now_iso()
                await _broadcast_fix_job(job)
        finally:
            fix_job_processes.pop(job.id, None)
            fix_job_tasks.pop(job.id, None)
            _clear_active_fix_job_for_session(job.session_id, expected_job_id=job.id)

    await _with_runtime_async(resolved_runtime, _run)


def _init_version_graph(
    session: PlotSession,
    *,
    script: str | None,
    plot_path: str,
    plot_type: Literal["svg", "raster"],
) -> None:
    main_branch_id = _new_id()
    root_version_id = _new_id()
    script_artifact, plot_artifact = _write_version_artifacts(
        session,
        root_version_id,
        script=script,
        plot_path=plot_path,
    )
    normalized_plot_type: Literal["svg", "raster"] = (
        "raster" if plot_type == "raster" else "svg"
    )

    root_node = VersionNode(
        id=root_version_id,
        parent_version_id=None,
        branch_id=main_branch_id,
        annotation_id=None,
        script_artifact_path=script_artifact,
        plot_artifact_path=plot_artifact,
        plot_type=normalized_plot_type,
    )
    main_branch = Branch(
        id=main_branch_id,
        name="main",
        base_version_id=root_version_id,
        head_version_id=root_version_id,
    )
    session.versions = [root_node]
    session.branches = [main_branch]
    session.root_version_id = root_version_id
    session.active_branch_id = main_branch_id
    session.checked_out_version_id = root_version_id
    _checkout_version(session, root_version_id, branch_id=main_branch_id)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _resolve_static_dir() -> Path:
    """Find the built frontend static directory."""
    pkg_static = Path(__file__).parent / "static"
    if pkg_static.is_dir() and (pkg_static / "index.html").exists():
        return pkg_static
    dev_static = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dev_static.is_dir() and (dev_static / "index.html").exists():
        return dev_static
    return pkg_static


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Write port file on startup, clean up on shutdown."""
    runtime = cast(BackendRuntime, app.state.runtime)
    owner_token = uuid.uuid4().hex

    startup_complete = False
    try:
        claim_runtime_lifecycle(runtime, owner_token)
        should_reload_from_disk = session_services.should_restore_session_store(runtime)
        if should_reload_from_disk:
            if _runtime_is_shared(runtime):
                with _runtime_context(runtime):
                    _ensure_session_store_loaded(force_reload=True)
            else:
                _with_runtime(
                    runtime,
                    lambda: _ensure_session_store_loaded(force_reload=False),
                )
            session_services.restore_latest_workspace_into_runtime(runtime)
        startup_complete = True
    except Exception:
        release_runtime_lifecycle(runtime, owner_token)
        raise

    try:
        yield
    finally:
        if startup_complete:
            await session_services.teardown_runtime(runtime)
        release_runtime_lifecycle(runtime, owner_token)


def create_app(runtime: BackendRuntime | None = None) -> FastAPI:
    resolved_runtime = runtime or _bound_runtime or get_shared_runtime()
    if _runtime_is_shared(resolved_runtime):
        _sync_runtime_from_globals(resolved_runtime)

    app = FastAPI(title="OpenPlot", version=__version__, lifespan=_lifespan)
    app.state.runtime = resolved_runtime

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def bind_runtime(request: Request, call_next):
        with _runtime_context(cast(BackendRuntime, request.app.state.runtime)):
            return await call_next(request)

    _register_routes(app)

    static_dir = _resolve_static_dir()
    if static_dir.is_dir() and (static_dir / "assets").is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(static_dir / "assets")),
            name="assets",
        )

    return app


# ---------------------------------------------------------------------------
# Session initialisation helpers (called from CLI)
# ---------------------------------------------------------------------------


def init_session_from_script(
    script_path: str | Path,
    *,
    inherit_id: str | None = None,
    inherit_workspace_id: str | None = None,
    inherit_workspace_name: str | None = None,
    inherit_runner_session_ids: dict[str, str] | None = None,
    inherit_artifacts_root: str | None = None,
    runtime: BackendRuntime | None = None,
) -> ExecutionResult:
    """Execute a script, create a session from the result."""
    resolved_runtime = runtime or get_shared_runtime()

    def _run() -> ExecutionResult:
        global _session

        _ensure_session_store_loaded()

        resolved_script_path = Path(script_path).resolve()
        script_content = _read_file_text(resolved_script_path)
        set_runtime_workspace_dir(resolved_runtime, resolved_script_path.parent)
        global _workspace_dir
        _workspace_dir = resolved_runtime.store.workspace_dir

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

        session = PlotSession(**session_kwargs)  # type: ignore[arg-type]
        _session_workspace_id(session)
        _ensure_workspace_name(session)

        run_output_dir = _new_run_output_dir(session)
        result = execute_script(
            resolved_script_path,
            capture_dir=run_output_dir,
            python_executable=_resolve_python_executable(session),
        )

        session.current_plot = result.plot_path or ""
        session.plot_type = result.plot_type or "svg"

        if result.success and result.plot_path:
            _clear_plot_mode_state()
            _session = session
            _init_version_graph(
                session,
                script=script_content,
                plot_path=result.plot_path,
                plot_type=result.plot_type or "svg",
            )
            _touch_session(session)
            _persist_session(session, promote=True)
            _set_active_session(session.id, clear_plot_mode=False)
        else:
            _session = None

        return result

    if _bound_runtime is resolved_runtime:
        result = _run()
        if not _runtime_is_shared(resolved_runtime):
            _sync_runtime_from_globals(resolved_runtime)
        return result
    return _with_runtime(resolved_runtime, _run)


def write_port_file(port: int) -> None:
    """Write the server port to ~/.openplot/port for MCP discovery."""
    runtime = get_shared_runtime()
    runtime.infra.port_file_path = _port_file
    write_runtime_port_file(runtime, port)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


# ---- API / WebSocket handlers ----


async def get_bootstrap_state(request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return session_services.build_bootstrap_payload(runtime)


async def get_plot_mode_state(request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return plot_mode_services.get_plot_mode_state(runtime)


async def set_plot_mode_files():
    return await plot_mode_services.set_plot_mode_files()


async def suggest_plot_mode_paths(
    body: PlotModePathSuggestionsRequest,
    request: Request,
):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await plot_mode_services.suggest_plot_mode_paths(body, runtime)


async def select_plot_mode_paths(
    body: PlotModeSelectPathsRequest,
    request: Request,
):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await plot_mode_services.select_plot_mode_paths(body, runtime)


async def update_plot_mode_settings(body: PlotModeSettingsRequest):
    return await plot_mode_services.update_plot_mode_settings(body)


async def submit_plot_mode_tabular_hint(body: PlotModeTabularHintRequest):
    return await plot_mode_services.submit_plot_mode_tabular_hint(body)


async def answer_plot_mode_question(body: PlotModeQuestionAnswerRequest):
    return await plot_mode_services.answer_plot_mode_question(body)


async def run_plot_mode_chat(body: PlotModeChatRequest, request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await plot_mode_services.run_plot_mode_chat(body, runtime)


async def finalize_plot_mode(body: PlotModeFinalizeRequest, request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await plot_mode_services.finalize_plot_mode(body, runtime)


async def rename_plot_mode_workspace(request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    body = await request.json()
    return await plot_mode_services.rename_plot_mode_workspace(runtime, body)


async def delete_plot_mode_workspace(request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    requested_id: str | None = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            requested_id = body.get("id")
    except Exception:
        pass
    return await plot_mode_services.delete_plot_mode_workspace(runtime, requested_id)


async def activate_plot_mode(request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    requested_id: str | None = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            requested_id = body.get("id")
    except Exception:
        pass
    return await plot_mode_services.activate_plot_mode(runtime, requested_id)


async def get_session_state(session_id: str | None = None):
    return session_services.get_session_state(session_id=session_id)


async def list_sessions(request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return session_services.build_sessions_payload(runtime)


async def create_new_session(request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await session_services.create_new_session(runtime)


async def activate_session(session_id: str, request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await session_services.activate_session(runtime, session_id)


async def rename_session(
    session_id: str,
    body: RenameSessionRequest,
    request: Request,
):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return session_services.rename_session(runtime, session_id, body)


async def delete_session(session_id: str, request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await session_services.delete_session(runtime, session_id)


async def get_preferences():
    return await runner_services.get_preferences()


async def set_preferences(body: PreferencesRequest):
    return await runner_services.set_preferences(body)


async def get_runners():
    return await runner_services.get_runners()


async def get_runner_status():
    return await runner_services.get_runner_status()


async def install_runner(body: RunnerInstallRequest, request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await runner_services.install_runner(body, runtime)


async def launch_runner_auth(body: RunnerAuthLaunchRequest):
    return await runner_services.launch_runner_auth(body)


async def open_external_url(body: OpenExternalUrlRequest):
    return await runner_services.open_external_url(body)


async def refresh_update_status(request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await runner_services.refresh_update_status(runtime)


async def get_python_interpreter(request: Request, session_id: str | None = None):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await runner_services.get_python_interpreter(runtime, session_id=session_id)


async def set_python_interpreter(body: PythonInterpreterRequest, request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await runner_services.set_python_interpreter(body, runtime)


async def get_runner_models(runner: str = "opencode", force_refresh: bool = False):
    return await runner_services.get_runner_models(
        runner=runner,
        force_refresh=force_refresh,
    )


async def get_opencode_models(force_refresh: bool = False):
    return await runner_services.get_opencode_models(force_refresh=force_refresh)


async def list_fix_jobs(
    request: Request,
    limit: int = 20,
    session_id: str | None = None,
):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await fix_job_services.list_fix_jobs(
        runtime,
        limit=limit,
        session_id=session_id,
    )


async def get_current_fix_job(request: Request, session_id: str | None = None):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await fix_job_services.get_current_fix_job(runtime, session_id=session_id)


async def start_fix_job(body: StartFixJobRequest, request: Request):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await fix_job_services.start_fix_job(body, runtime)


async def cancel_fix_job(job_id: str, request: Request):
    _ = request
    return await fix_job_services.cancel_fix_job(job_id)


# ---- Plot file serving ----


async def get_plot(
    request: Request,
    session_id: str | None = None,
    version_id: str | None = None,
    plot_mode: bool = False,
    workspace_id: str | None = None,
):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await artifact_services.get_plot(
        runtime,
        session_id=session_id,
        version_id=version_id,
        plot_mode=plot_mode,
        workspace_id=workspace_id,
    )


async def export_plot_mode_workspace(
    request: Request,
    workspace_id: str | None = None,
):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await artifact_services.export_plot_mode_workspace(
        runtime,
        workspace_id=workspace_id,
    )


# ---- Branch / checkout ----


async def checkout_version(body: CheckoutVersionRequest):
    return await versioning_services.checkout_version(body)


async def checkout_branch_head(branch_id: str):
    return await versioning_services.checkout_branch_head(branch_id)


async def rename_branch(
    branch_id: str,
    body: RenameBranchRequest,
    request: Request,
):
    runtime = cast(BackendRuntime, request.app.state.runtime)
    return await versioning_services.rename_branch(branch_id, body, runtime)


# ---- Annotations ----


async def add_annotation(annotation: Annotation):
    return await annotation_services.add_annotation(annotation)


async def export_annotation_plot(annotation_id: str):
    return await annotation_services.export_annotation_plot(annotation_id)


async def delete_annotation(annotation_id: str):
    return await annotation_services.delete_annotation(annotation_id)


async def update_annotation(annotation_id: str, updates: AnnotationUpdateRequest):
    return await annotation_services.update_annotation(annotation_id, updates)


# ---- Feedback compilation ----


async def get_feedback(session_id: str | None = None):
    return await artifact_services.get_feedback(session_id=session_id)


# ---- Script submission (from MCP / agent) ----


async def submit_script(body: SubmitScriptRequest, session_id: str | None = None):
    return await versioning_services.submit_script(body, session_id=session_id)


# ---- Revision history ----


async def get_revisions():
    return await versioning_services.get_revisions()


# ---- WebSocket ----


async def websocket_endpoint(ws: WebSocket):
    runtime = cast(BackendRuntime, ws.app.state.runtime)
    await ws.accept()
    runtime.infra.ws_clients.add(ws)
    with _runtime_context(runtime):
        try:
            while True:
                _ = await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            runtime.infra.ws_clients.discard(ws)


def _register_routes(app: FastAPI) -> None:
    from .api.annotations import router as annotations_router
    from .api.artifacts import router as artifacts_router
    from .api.fix_jobs import router as fix_jobs_router
    from .api.plot_mode import router as plot_mode_router
    from .api.preferences import router as preferences_router
    from .api.runners import router as runners_router
    from .api.runtime import router as runtime_router
    from .api.sessions import router as sessions_router
    from .api.versioning import router as versioning_router
    from .api.ws import router as ws_router

    @app.get("/", response_class=HTMLResponse)
    async def index():
        static_dir = _resolve_static_dir()
        index_file = static_dir / "index.html"
        if index_file.exists():
            return HTMLResponse(_read_file_text(index_file))
        return HTMLResponse(
            "<html><body>"
            "<h1>OpenPlot</h1>"
            "<p>Frontend assets are missing.</p>"
            "<p>If running from source, run <code>npm run build --prefix frontend</code>.</p>"
            "<p>If installed from a package, reinstall a build that includes <code>openplot/static</code>.</p>"
            "</body></html>"
        )

    app.include_router(sessions_router)
    app.include_router(plot_mode_router)
    app.include_router(annotations_router)
    app.include_router(fix_jobs_router)
    app.include_router(runners_router)
    app.include_router(preferences_router)
    app.include_router(artifacts_router)
    app.include_router(versioning_router)
    app.include_router(runtime_router)
    app.include_router(ws_router)
