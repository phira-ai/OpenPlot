"""FastAPI backend — REST endpoints, WebSocket, and static file serving."""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import os
import platform
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
from . import server_events as _server_events
from . import server_app_routes as _server_app_routes
from . import server_fix_execution as _server_fix_execution
from . import server_path_picker as _server_path_picker
from . import server_runner_io as _server_runner_io
from . import server_plot_mode_messages as _server_plot_mode_messages
from . import server_plot_mode_inference as _server_plot_mode_inference
from . import server_plot_mode_planning as _server_plot_mode_planning
from . import server_plot_mode_profiles as _server_plot_mode_profiles
from . import server_plot_mode_review as _server_plot_mode_review
from . import server_response_utils as _server_response_utils
from . import server_sessions_misc as _server_sessions_misc
from . import server_plot_mode_state as _server_plot_mode_state
from . import server_python_runtime as _server_python_runtime
from . import server_runtime_bootstrap as _server_runtime_bootstrap
from . import server_runners as _server_runners
from . import server_version_artifacts as _server_version_artifacts

_BOUND_SERVER_HELPERS = {
    "_server_app_routes": "_register_routes".split(),
    "_server_events": "_broadcast_plot_mode_message_update _broadcast_plot_mode_preview _broadcast".split(),
    "_server_fix_execution": "_is_terminal_fix_job_status _build_opencode_plot_fix_command _build_codex_plot_fix_prompt _build_codex_plot_fix_command _build_claude_plot_fix_command _broadcast_fix_job _cancel_fix_job_execution _reconcile_active_fix_job_state _broadcast_fix_job_log _session_for_fix_job _workspace_dir_for_fix_job _runtime_dir_for_fix_job _fix_runner_env_overrides _fix_job_session_key _prepare_fix_runner_workspace _run_opencode_fix_iteration _run_codex_fix_iteration _run_claude_fix_iteration _terminate_fix_process _fix_retry_context _run_fix_job_loop".split(),
    "_server_path_picker": "_common_parent_dir _resolved_home_dir _picker_default_base_dir _expanduser_if_needed _resolve_local_picker_path _picker_parent_and_fragment _display_picker_path _is_fuzzy_subsequence _path_suggestion_score _list_path_suggestions _resolve_selected_file_path".split(),
    "_server_plot_mode_inference": "_sheet_excerpt_for_prompt _build_tabular_range_inference_prompt _extract_plot_mode_tabular_range_result _propose_profile_from_selector_hint _build_plot_mode_input_bundle _build_resolved_source_for_profile _build_multi_file_collection_source _build_mixed_bundle_source _build_plot_mode_resolved_sources _propose_grouped_profile_from_selector_regions".split(),
    "_server_plot_mode_messages": "_append_plot_mode_message _create_plot_mode_message _remove_plot_mode_message _set_plot_mode_message_content _set_plot_mode_message_metadata _append_plot_mode_activity _plot_mode_refining_metadata _append_plot_mode_table_preview _append_plot_mode_question_set _mark_question_set_answered _answer_map_for_question_set _apply_answers_to_question_set _first_answer_for_question_set _question_set_answer_summary _queue_tabular_range_confirmation _append_profile_preview_card _profile_supports_preview_confirmation _queue_data_preview_confirmation _append_profile_integrity_activity _present_profile_for_confirmation _present_tabular_range_proposal _queue_tabular_range_confirmation _apply_tabular_range_proposal _populate_plot_mode_data_messages _queue_plot_mode_plan_approval_question _queue_plot_mode_continue_planning_question _queue_plot_mode_bundle_kickoff_question _present_plot_mode_plan_result".split(),
    "_server_plot_mode_planning": "_build_plot_mode_prompt _build_plot_mode_planning_prompt _extract_plot_mode_plan_result _run_plot_mode_generation _run_plot_mode_planning _store_plot_mode_plan _execute_plot_mode_draft _continue_plot_mode_planning _default_plot_mode_planning_message _continue_plot_mode_planning_with_selected_runner _start_plot_mode_planning_for_profile _apply_plot_mode_result".split(),
    "_server_plot_mode_profiles": "_stringify_preview_value _sample_integrity_notes _column_label _format_sheet_bounds _format_sheet_region_label _normalize_preview_grid _non_empty_cell_count _detect_non_empty_blocks _rows_for_bounds _looks_like_numeric_text _dataframe_from_block_rows _build_data_profile _build_tabular_region_from_frame _build_data_profile_from_grid _build_grouped_data_profile_from_regions _build_sheet_preview _read_delimited_grid _build_tabular_selector _tabular_regions_for_profile _profile_delimited_file _profile_json_file _profile_excel_file _profile_selected_data_files".split(),
    "_server_plot_mode_review": "_build_plot_mode_review_prompt _run_plot_mode_autonomous_reviews".split(),
    "_server_plot_mode_state": "_plot_mode_root_dir _plot_mode_artifacts_dir _plot_mode_captures_dir _plot_mode_generated_script_path _plot_mode_snapshot_path _plot_mode_artifacts_path_for_id _plot_mode_workspace_snapshot_path_for_id _plot_mode_workspace_snapshot_path _plot_mode_has_user_content _plot_mode_is_workspace _promote_plot_mode_workspace _ensure_plot_mode_workspace_name _is_active_plot_mode_state _save_plot_mode_snapshot _load_plot_mode_state_from_payload _load_plot_mode_state_from_path _infer_plot_mode_state_from_artifacts_dir _load_plot_mode_snapshot _load_all_plot_mode_workspaces _load_plot_mode_workspace_by_id _resolve_plot_mode_workspace _plot_mode_picker_base_dir _plot_mode_workspace_base_dir _delete_plot_mode_snapshot _touch_plot_mode _get_plot_mode_state _clear_plot_mode_state _broadcast_plot_mode_state _plot_mode_summary _plot_mode_sort_key".split(),
    "_server_python_runtime": "_load_python_interpreter_preference _save_python_interpreter_preference _python_context_dir _probe_python_interpreter _validated_python_candidate _discover_python_interpreter_candidates _probe_python_packages _resolve_python_interpreter_state".split(),
    "_server_response_utils": "_append_active_resolved_source_context _append_profile_region_details _json_object_candidates _coerce_bool _suggest_plot_mode_question_options _extract_structured_plot_mode_result _extract_python_script_from_text _extract_plot_mode_script_result _as_record _as_string _as_non_empty_string _read_path _collect_text _join_collected_text _truncate_output _resolve_plot_response".split(),
    "_server_runner_io": "_extract_runner_session_id_from_event _extract_runner_session_id_from_output _extract_runner_reported_error _is_resume_session_error _is_rate_limit_error _format_rate_limit_error _tool_name_is_builtin_question_tool _candidate_tool_names_from_parsed_event _parsed_runner_uses_builtin_question_tool _append_retry_instruction _plot_mode_question_tool_retry_instruction _fix_mode_question_tool_retry_instruction _extract_plot_mode_assistant_text _extract_codex_plot_mode_stream_fragment _extract_opencode_plot_mode_stream_fragment _extract_claude_plot_mode_stream_fragment _extract_plot_mode_stream_fragment _consume_plot_mode_text_stream _resolve_plot_mode_final_assistant_text _run_plot_mode_runner_prompt _parse_json_event_line _parse_opencode_json_event_line _consume_fix_stream _run_fix_iteration_command".split(),
    "_server_runners": "_runner_default_model_id _normalize_runner_session_id _runner_session_id_for_session _set_runner_session_id_for_session _clear_runner_session_id_for_session _runner_session_id_for_plot_mode _set_runner_session_id_for_plot_mode _clear_runner_session_id_for_plot_mode _runner_tools_root _managed_command_path _resolve_command_path _subprocess_env _no_window_kwargs _hidden_window_kwargs _shell_join _resolve_openplot_mcp_launch_command _backend_url_from_port_file _write_fix_runner_shims _write_fix_runner_shims_unix _write_fix_runner_shims_windows _resolve_claude_cli_command _runner_launch_probe _opencode_auth_file_path _opencode_auth_file_has_credentials _opencode_auth_list_has_credentials _runner_auth_command _runner_auth_launch_parts _runner_auth_launch_command _powershell_quote _runner_auth_windows_command _runner_auth_guide_url _runner_auth_instructions _runner_auth_probe _runner_auth_launch_supported _apple_script_quote _launch_runner_auth_terminal _detect_runner_availability _runner_host_platform _winget_available _runner_guide_url _runner_install_supported _runner_default_status _runner_install_job_snapshot _latest_runner_install_job_snapshot _build_runner_status_payload _create_runner_install_job _update_runner_install_job _append_runner_install_log _run_install_subprocess _resolve_runner_executable_path _install_runner_via_script _download_url_to_file _run_download_subprocess _read_url_bytes _parse_semver_parts _normalize_release_version _fetch_latest_release_payload _default_update_status_payload _update_status_cache_path _load_update_status_disk_cache _store_update_status_cache _build_update_status_payload_impl _build_update_status_payload _install_codex_release _perform_runner_install _run_runner_install_job _runner_output_used_builtin_question_tool _parse_opencode_verbose_models _refresh_opencode_models_cache _parse_codex_models_cache _refresh_codex_models_cache _refresh_claude_models_cache _refresh_runner_models_cache _resolve_runner_default_model_and_variant _validate_runner_model_selection _opencode_fix_config_content _opencode_question_tool_disabled_config_content _merge_opencode_config_objects _merged_opencode_config_content".split(),
    "_server_runtime_bootstrap": "_runtime_is_shared _runtime_context _current_runtime _runtime_sessions_map _runtime_fix_jobs_map _runtime_fix_job_tasks_map _runtime_fix_job_processes_map _runtime_active_fix_jobs_map _runtime_workspace_dir _runtime_ws_clients _runtime_plot_mode_state_value _runtime_active_session_value _runtime_active_session_id_value _path_from_override_env _default_data_root _default_state_root _state_root _sync_runtime_from_globals _sync_globals_from_runtime _runtime_snapshot _restore_runtime_snapshot _activate_runtime _with_runtime _with_runtime_async _clear_shared_shutdown_runtime_state get_session _get_session_by_id _resolve_request_session _ensure_session_store_loaded_impl _resolve_python_executable _resolve_static_dir _lifespan create_app init_session_from_script".split(),
    "_server_sessions_misc": "init_plot_mode_session _touch_session _default_workspace_name _ensure_workspace_name _session_workspace_id _workspace_for_session _session_sort_key _load_session_snapshot _save_session_registry _save_session_snapshot _set_active_session _session_summary _bootstrap_payload".split(),
    "_server_version_artifacts": "_session_artifacts_root _is_managed_workspace_path _version_artifact_dir _new_run_output_dir _write_version_artifacts _delete_version_artifacts _find_branch _get_branch _active_branch _find_version _get_version _safe_read_text _media_type_for_plot_path _branch_chain _rebuild_revision_history _checkout_version _next_branch_name _create_branch _resolve_target_annotation _init_version_graph".split(),
}

def _bind_server_helper(module: object, helper_name: str):
    target = getattr(module, helper_name)

    if inspect.iscoroutinefunction(target):

        async def _bound_async(*args, __target=target, **kwargs):
            return await __target(sys.modules[__name__], *args, **kwargs)

        bound = _bound_async
    else:

        def _bound_sync(*args, __target=target, **kwargs):
            return __target(sys.modules[__name__], *args, **kwargs)

        bound = _bound_sync

    bound.__name__ = helper_name
    bound.__qualname__ = helper_name
    bound.__module__ = __name__
    bound.__doc__ = getattr(target, "__doc__", None)
    return bound

def _register_bound_server_helpers() -> None:
    modules = {
        "_server_app_routes": _server_app_routes,
        "_server_events": _server_events,
        "_server_fix_execution": _server_fix_execution,
        "_server_path_picker": _server_path_picker,
        "_server_plot_mode_inference": _server_plot_mode_inference,
        "_server_plot_mode_messages": _server_plot_mode_messages,
        "_server_plot_mode_planning": _server_plot_mode_planning,
        "_server_plot_mode_profiles": _server_plot_mode_profiles,
        "_server_plot_mode_review": _server_plot_mode_review,
        "_server_plot_mode_state": _server_plot_mode_state,
        "_server_python_runtime": _server_python_runtime,
        "_server_response_utils": _server_response_utils,
        "_server_runner_io": _server_runner_io,
        "_server_runners": _server_runners,
        "_server_runtime_bootstrap": _server_runtime_bootstrap,
        "_server_sessions_misc": _server_sessions_misc,
        "_server_version_artifacts": _server_version_artifacts,
    }
    for alias, helper_names in _BOUND_SERVER_HELPERS.items():
        module = modules[alias]
        for helper_name in helper_names:
            globals()[helper_name] = _bind_server_helper(module, helper_name)

_register_bound_server_helpers()

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
from .api import annotations as annotations_api
from .api import artifacts as artifacts_api
from .api import fix_jobs as fix_jobs_api
from .api import plot_mode as plot_mode_api
from .api import runtime as runtime_api
from .api import runners as runners_api
from .api import sessions as sessions_api
from .api import versioning as versioning_api
from .api import ws as ws_api
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
from .runtime_text import decode_bytes, read_text_file, run_text_subprocess
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
    """Read a text file with robust encoding detection."""
    return read_text_file(path)

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
_opencode_fix_agent_name = "openplot-fix-runner"
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

def _is_command_available(command: str) -> bool:
    return _resolve_command_path(command) is not None

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

def _data_root() -> Path:
    return _path_from_override_env("OPENPLOT_DATA_DIR") or _default_data_root()

def _iso_from_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()

def _is_internal_plot_mode_workspace_dir(path: Path) -> bool:
    resolved_path = path.resolve()
    plot_mode_root = _plot_mode_root_dir().resolve()
    try:
        resolved_path.relative_to(plot_mode_root)
        return True
    except ValueError:
        return False

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

def _reset_plot_mode_runtime_state() -> None:
    global _plot_mode
    _plot_mode = None

def _plot_mode_sandbox_dir(state: PlotModeState) -> Path:
    sandbox_dir = Path(state.workspace_dir) / ".openplot-plot-mode" / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    return sandbox_dir

def _plot_mode_autonomous_focus_direction(pass_index: int) -> str:
    offset = max(pass_index - 2, 0)
    return _plot_mode_autonomous_focus_directions[
        offset % len(_plot_mode_autonomous_focus_directions)
    ]

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

def _plot_mode_plan_result_has_selectable_options(
    result: PlotModePlanResult | None,
) -> bool:
    if result is None or not result.questions:
        return False
    return any(question.options for question in result.questions)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

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

def _ensure_session_store_loaded(*, force_reload: "'bool'" = False) -> "'None'":
    return session_services.ensure_session_store_loaded(
        _current_runtime(), force_reload=force_reload
    )

def _session_title(session: PlotSession) -> str:
    _ensure_workspace_name(session)
    return session.workspace_name

def _safe_export_stem(name: str, *, default: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()).strip("._-")
    return sanitized or default

def _workspace_summary_sort_key(summary: Mapping[str, object]) -> tuple[str, str, str]:
    updated_at = str(summary.get("updated_at") or summary.get("created_at") or "")
    created_at = str(summary.get("created_at") or "")
    workspace_id = str(summary.get("id") or "")
    return (updated_at, created_at, workspace_id)

def _list_session_summaries() -> "'list[dict[str, object]]'":
    return session_services.list_session_summaries(_current_runtime())

def _last_modified_session() -> PlotSession | None:
    _ensure_session_store_loaded()
    sessions = _runtime_sessions_map()
    if not sessions:
        return None
    return max(sessions.values(), key=_session_sort_key)

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
    "\"tuple[Literal['annotation', 'plot'], PlotSession | PlotModeState] | None\""
):
    return session_services.restore_latest_workspace(_current_runtime())

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

def _is_openplot_app_launcher_path(path: Path) -> bool:
    if getattr(sys, "frozen", False):
        try:
            return path.resolve() == Path(sys.executable).resolve()
        except OSError:
            return False
    normalized = str(path).lower()
    return path.name.lower() == "openplot" and ".app/contents/macos/" in normalized

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Session initialisation helpers (called from CLI)
# ---------------------------------------------------------------------------

def write_port_file(port: int) -> None:
    """Write the server port to ~/.openplot/port for MCP discovery."""
    runtime = get_shared_runtime()
    runtime.infra.port_file_path = _port_file
    write_runtime_port_file(runtime, port)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# ---- API / WebSocket handlers ----

get_bootstrap_state = sessions_api.get_bootstrap_state

get_plot_mode_state = plot_mode_api.get_plot_mode_state

set_plot_mode_files = plot_mode_services.set_plot_mode_files

suggest_plot_mode_paths = plot_mode_api.suggest_plot_mode_paths

select_plot_mode_paths = plot_mode_api.select_plot_mode_paths

update_plot_mode_settings = plot_mode_services.update_plot_mode_settings

submit_plot_mode_tabular_hint = plot_mode_services.submit_plot_mode_tabular_hint

answer_plot_mode_question = plot_mode_services.answer_plot_mode_question

run_plot_mode_chat = plot_mode_api.run_plot_mode_chat

finalize_plot_mode = plot_mode_api.finalize_plot_mode

rename_plot_mode_workspace = plot_mode_api.rename_plot_mode_workspace

delete_plot_mode_workspace = plot_mode_api.delete_plot_mode_workspace

activate_plot_mode = plot_mode_api.activate_plot_mode

get_session_state = session_services.get_session_state

list_sessions = sessions_api.list_sessions

create_new_session = sessions_api.create_new_session

activate_session = sessions_api.activate_session

rename_session = sessions_api.rename_session

delete_session = sessions_api.delete_session

get_preferences = runner_services.get_preferences

set_preferences = runner_services.set_preferences

get_runners = runner_services.get_runners

get_runner_status = runner_services.get_runner_status

install_runner = runners_api.install_runner

launch_runner_auth = runner_services.launch_runner_auth

open_external_url = runner_services.open_external_url

refresh_update_status = runtime_api.refresh_update_status

get_python_interpreter = runtime_api.get_python_interpreter

set_python_interpreter = runtime_api.set_python_interpreter

async def get_runner_models(
    runner: "'str'" = "opencode", force_refresh: "'bool'" = False
):
    return await runner_services.get_runner_models(
        runner=runner,
        force_refresh=force_refresh,
    )

get_opencode_models = runner_services.get_opencode_models

list_fix_jobs = fix_jobs_api.list_fix_jobs

get_current_fix_job = fix_jobs_api.get_current_fix_job

start_fix_job = fix_jobs_api.start_fix_job

cancel_fix_job = fix_jobs_api.cancel_fix_job

# ---- Plot file serving ----

get_plot = artifacts_api.get_plot

export_plot_mode_workspace = artifacts_api.export_plot_mode_workspace

# ---- Branch / checkout ----

checkout_version = versioning_services.checkout_version

checkout_branch_head = versioning_services.checkout_branch_head

rename_branch = versioning_api.rename_branch

# ---- Annotations ----

add_annotation = annotation_services.add_annotation

export_annotation_plot = annotation_services.export_annotation_plot

delete_annotation = annotation_services.delete_annotation

update_annotation = annotation_services.update_annotation

# ---- Feedback compilation ----

get_feedback = artifact_services.get_feedback

# ---- Script submission (from MCP / agent) ----

submit_script = versioning_services.submit_script

# ---- Revision history ----

get_revisions = versioning_services.get_revisions

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
