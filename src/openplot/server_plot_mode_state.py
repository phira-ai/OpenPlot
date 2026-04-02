"""Plot-mode state and persistence helpers extracted from openplot.server."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import ModuleType
from typing import Literal, cast

from fastapi import HTTPException

from .models import PlotModePhase, PlotModeState


def _plot_mode_root_dir(server_module: ModuleType) -> Path:
    root = server_module._state_root() / "plot-mode"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _plot_mode_artifacts_dir(server_module: ModuleType, state: PlotModeState) -> Path:
    path = server_module._plot_mode_root_dir() / state.id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _plot_mode_captures_dir(server_module: ModuleType, state: PlotModeState) -> Path:
    path = server_module._plot_mode_artifacts_dir(state) / "captures"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _plot_mode_generated_script_path(
    server_module: ModuleType, state: PlotModeState
) -> Path:
    return (
        server_module._plot_mode_artifacts_dir(state)
        / server_module._plot_mode_generated_script_name
    )


def _plot_mode_snapshot_path(server_module: ModuleType) -> Path:
    return (
        server_module._plot_mode_root_dir()
        / server_module._plot_mode_snapshot_file_name
    )


def _plot_mode_artifacts_path_for_id(
    server_module: ModuleType, plot_mode_id: str
) -> Path:
    return server_module._plot_mode_root_dir() / plot_mode_id


def _plot_mode_workspace_snapshot_path_for_id(
    server_module: ModuleType, plot_mode_id: str
) -> Path:
    return (
        server_module._plot_mode_artifacts_path_for_id(plot_mode_id)
        / server_module._plot_mode_workspace_snapshot_file_name
    )


def _plot_mode_workspace_snapshot_path(
    server_module: ModuleType, state: PlotModeState
) -> Path:
    return server_module._plot_mode_workspace_snapshot_path_for_id(state.id)


def _plot_mode_has_user_content(
    server_module: ModuleType, state: PlotModeState
) -> bool:
    del server_module
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


def _plot_mode_is_workspace(server_module: ModuleType, state: PlotModeState) -> bool:
    return state.is_workspace or server_module._plot_mode_has_user_content(state)


def _promote_plot_mode_workspace(
    server_module: ModuleType, state: PlotModeState
) -> None:
    del server_module
    if state.is_workspace:
        return
    state.is_workspace = True


def _ensure_plot_mode_workspace_name(
    server_module: ModuleType, state: PlotModeState
) -> None:
    existing = state.workspace_name.strip()
    if existing:
        state.workspace_name = existing
        return
    state.workspace_name = server_module._default_workspace_name(state.created_at)


def _is_active_plot_mode_state(server_module: ModuleType, state: PlotModeState) -> bool:
    active_plot_mode = server_module._runtime_plot_mode_state_value()
    return active_plot_mode is not None and active_plot_mode.id == state.id


def _save_plot_mode_snapshot(server_module: ModuleType, state: PlotModeState) -> None:
    if not server_module._plot_mode_is_workspace(state):
        return
    server_module._promote_plot_mode_workspace(state)
    server_module._ensure_plot_mode_workspace_name(state)
    payload = cast(dict[str, object], state.model_dump(mode="json"))

    workspace_snapshot_path = server_module._plot_mode_workspace_snapshot_path(state)
    if workspace_snapshot_path != server_module._plot_mode_snapshot_path():
        server_module._write_json_atomic(workspace_snapshot_path, payload)

    if server_module._is_active_plot_mode_state(state):
        server_module._write_json_atomic(
            server_module._plot_mode_snapshot_path(), payload
        )


def _load_plot_mode_state_from_payload(
    server_module: ModuleType, raw: object
) -> PlotModeState | None:
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
        state.is_workspace = server_module._plot_mode_has_user_content(state)
    if server_module._plot_mode_has_user_content(state):
        state.is_workspace = True

    server_module._ensure_plot_mode_workspace_name(state)
    if not state.updated_at:
        state.updated_at = state.created_at or server_module._now_iso()
    if not server_module._plot_mode_is_workspace(state):
        return None
    return state


def _load_plot_mode_state_from_path(
    server_module: ModuleType, snapshot_path: Path
) -> PlotModeState | None:
    if not snapshot_path.exists():
        return None

    try:
        raw = json.loads(server_module._read_file_text(snapshot_path))
    except (OSError, json.JSONDecodeError):
        return None
    return server_module._load_plot_mode_state_from_payload(raw)


def _infer_plot_mode_state_from_artifacts_dir(
    server_module: ModuleType,
    plot_mode_dir: Path,
) -> PlotModeState | None:
    if not plot_mode_dir.is_dir():
        return None

    script_path = plot_mode_dir / server_module._plot_mode_generated_script_name
    current_script = (
        server_module._read_file_text(script_path) if script_path.exists() else None
    )

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
    created_at = server_module._iso_from_timestamp(min(mtimes))
    updated_at = server_module._iso_from_timestamp(max(mtimes))
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
    server_module._ensure_plot_mode_workspace_name(state)
    return state


def _load_plot_mode_snapshot(server_module: ModuleType) -> PlotModeState | None:
    active_state = server_module._load_plot_mode_state_from_path(
        server_module._plot_mode_snapshot_path()
    )
    if active_state is not None:
        return active_state

    candidates: list[PlotModeState] = []
    for child in server_module._plot_mode_root_dir().iterdir():
        if not child.is_dir():
            continue
        state = server_module._load_plot_mode_state_from_path(
            child / server_module._plot_mode_workspace_snapshot_file_name
        )
        if state is None:
            state = server_module._infer_plot_mode_state_from_artifacts_dir(child)
        if state is not None and server_module._plot_mode_is_workspace(state):
            candidates.append(state)

    if not candidates:
        return None

    latest_state = max(candidates, key=server_module._plot_mode_sort_key)
    server_module._save_plot_mode_snapshot(latest_state)
    return latest_state


def _load_all_plot_mode_workspaces(server_module: ModuleType) -> list[PlotModeState]:
    """Load all persisted plot-mode workspaces from disk (not just the active one)."""
    workspaces: list[PlotModeState] = []
    for child in server_module._plot_mode_root_dir().iterdir():
        if not child.is_dir():
            continue
        state = server_module._load_plot_mode_state_from_path(
            child / server_module._plot_mode_workspace_snapshot_file_name
        )
        if state is None:
            state = server_module._infer_plot_mode_state_from_artifacts_dir(child)
        if state is not None and server_module._plot_mode_is_workspace(state):
            workspaces.append(state)
    return workspaces


def _load_plot_mode_workspace_by_id(
    server_module: ModuleType,
    plot_mode_id: str,
) -> PlotModeState | None:
    """Load a specific plot-mode workspace by ID from disk."""
    snapshot_path = server_module._plot_mode_workspace_snapshot_path_for_id(
        plot_mode_id
    )
    state = server_module._load_plot_mode_state_from_path(snapshot_path)
    if state is not None:
        return state
    artifacts_dir = server_module._plot_mode_artifacts_path_for_id(plot_mode_id)
    return server_module._infer_plot_mode_state_from_artifacts_dir(artifacts_dir)


def _resolve_plot_mode_workspace(
    server_module: ModuleType,
    workspace_id: str | None,
    *,
    create_if_missing: bool = False,
) -> PlotModeState:
    normalized_workspace_id = (workspace_id or "").strip()
    active_plot_mode = server_module._runtime_plot_mode_state_value()
    if normalized_workspace_id:
        if (
            active_plot_mode is not None
            and active_plot_mode.id == normalized_workspace_id
        ):
            return active_plot_mode
        state = server_module._load_plot_mode_workspace_by_id(normalized_workspace_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail=f"Plot-mode workspace not found: {normalized_workspace_id}",
            )
        return state

    if create_if_missing:
        return active_plot_mode or server_module.init_plot_mode_session(
            workspace_dir=server_module._runtime_workspace_dir()
        )

    return server_module._get_plot_mode_state()


def _plot_mode_picker_base_dir(server_module: ModuleType, state: PlotModeState) -> Path:
    candidate_paths: list[Path] = []

    current_script_path = (state.current_script_path or "").strip()
    if current_script_path:
        candidate_paths.append(Path(current_script_path))

    for file in state.files:
        stored_path = file.stored_path.strip()
        if stored_path:
            candidate_paths.append(Path(stored_path))

    preferred_dir = server_module._common_parent_dir(candidate_paths)
    if preferred_dir is not None:
        return preferred_dir

    workspace_dir = Path(state.workspace_dir).resolve()
    if server_module._is_internal_plot_mode_workspace_dir(workspace_dir):
        return server_module._picker_default_base_dir()

    return workspace_dir


def _plot_mode_workspace_base_dir(
    server_module: ModuleType, workspace_id: str | None
) -> Path:
    normalized_workspace_id = (workspace_id or "").strip()
    if normalized_workspace_id:
        return server_module._plot_mode_picker_base_dir(
            server_module._resolve_plot_mode_workspace(normalized_workspace_id)
        )
    active_plot_mode = server_module._runtime_plot_mode_state_value()
    if active_plot_mode is not None:
        return server_module._plot_mode_picker_base_dir(active_plot_mode)
    fallback_dir = server_module._runtime_workspace_dir().resolve()
    if server_module._is_internal_plot_mode_workspace_dir(fallback_dir):
        return server_module._picker_default_base_dir()
    return fallback_dir


def _delete_plot_mode_snapshot(
    server_module: ModuleType,
    *,
    state: PlotModeState | None = None,
    clear_active_snapshot: bool = True,
) -> None:
    if clear_active_snapshot:
        server_module._plot_mode_snapshot_path().unlink(missing_ok=True)
    if state is None:
        return
    server_module._plot_mode_workspace_snapshot_path(state).unlink(missing_ok=True)
    shutil.rmtree(
        server_module._plot_mode_artifacts_path_for_id(state.id), ignore_errors=True
    )


def _touch_plot_mode(server_module: ModuleType, state: PlotModeState) -> None:
    if server_module._plot_mode_has_user_content(state):
        server_module._promote_plot_mode_workspace(state)
    server_module._ensure_plot_mode_workspace_name(state)
    state.updated_at = server_module._now_iso()
    if server_module._plot_mode_is_workspace(state):
        server_module._save_plot_mode_snapshot(state)


def _get_plot_mode_state(server_module: ModuleType) -> PlotModeState:
    active_plot_mode = server_module._runtime_plot_mode_state_value()
    if active_plot_mode is None:
        raise HTTPException(status_code=404, detail="Plot mode is not active")
    return active_plot_mode


def _clear_plot_mode_state(server_module: ModuleType) -> None:
    existing = server_module._runtime_plot_mode_state_value()
    runtime = server_module._current_runtime()
    if server_module._runtime_is_shared(runtime):
        server_module._plot_mode = None
    else:
        runtime.store.plot_mode = None

    if existing is not None and server_module._plot_mode_is_workspace(existing):
        server_module._plot_mode_snapshot_path().unlink(missing_ok=True)
    else:
        server_module._delete_plot_mode_snapshot(state=existing)


async def _broadcast_plot_mode_state(
    server_module: ModuleType, state: PlotModeState
) -> None:
    server_module._ensure_plot_mode_workspace_name(state)
    server_module._save_plot_mode_snapshot(state)
    await server_module._broadcast(
        {
            "type": "plot_mode_updated",
            "plot_mode": state.model_dump(mode="json"),
        }
    )


def _plot_mode_summary(
    server_module: ModuleType, state: PlotModeState
) -> dict[str, object]:
    server_module._ensure_plot_mode_workspace_name(state)
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


def _plot_mode_sort_key(
    server_module: ModuleType, state: PlotModeState
) -> tuple[str, str, str]:
    del server_module
    return (state.updated_at or state.created_at, state.created_at, state.id)
