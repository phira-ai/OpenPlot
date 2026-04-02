"""Session/bootstrap misc helpers extracted from openplot.server."""

from __future__ import annotations

import json
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from types import ModuleType
from typing import Literal, cast

from fastapi import HTTPException

from .models import AnnotationStatus, PlotModeState, PlotSession


def _touch_session(server_module: ModuleType, session: PlotSession) -> None:
    session.updated_at = server_module._now_iso()


def _default_workspace_name(
    server_module: ModuleType,
    created_at: str,
    *,
    display_tz: tzinfo | None = None,
) -> str:
    del server_module
    normalized = created_at.strip()
    if not normalized:
        normalized = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

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


def _ensure_workspace_name(server_module: ModuleType, session: PlotSession) -> None:
    existing = session.workspace_name.strip()
    if existing:
        session.workspace_name = existing
        return
    session.workspace_name = server_module._default_workspace_name(session.created_at)


def _session_workspace_id(server_module: ModuleType, session: PlotSession) -> str:
    del server_module
    candidate = session.workspace_id.strip()
    if candidate:
        return candidate
    session.workspace_id = session.id
    return session.workspace_id


def _workspace_for_session(server_module: ModuleType, session: PlotSession) -> Path:
    if session.source_script_path:
        script_path = server_module._resolve_session_file_path(
            session, session.source_script_path
        )
        if script_path.parent.exists():
            return script_path.parent

    if session.current_plot:
        plot_path = server_module._resolve_session_file_path(
            session, session.current_plot
        )
        if plot_path.parent.exists():
            return plot_path.parent

    return server_module._workspace_dir


def _session_sort_key(
    server_module: ModuleType, session: PlotSession
) -> tuple[str, str, str]:
    del server_module
    return (session.updated_at or session.created_at, session.created_at, session.id)


def _load_session_snapshot(
    server_module: ModuleType, session_id: str
) -> PlotSession | None:
    snapshot_path = server_module._session_snapshot_path(session_id)
    if not snapshot_path.exists():
        return None

    try:
        raw = json.loads(server_module._read_file_text(snapshot_path))
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
        session.updated_at = session.created_at or server_module._now_iso()
    server_module._ensure_workspace_name(session)
    return session


def _save_session_registry(server_module: ModuleType) -> None:
    filtered_order: list[str] = []
    seen: set[str] = set()
    for session_id in server_module._session_order:
        if session_id in seen or session_id not in server_module._sessions:
            continue
        seen.add(session_id)
        filtered_order.append(session_id)
    for session_id in sorted(
        (sid for sid in server_module._sessions if sid not in seen),
        key=lambda sid: server_module._session_sort_key(server_module._sessions[sid]),
        reverse=True,
    ):
        filtered_order.append(session_id)

    server_module._session_order = filtered_order

    if (
        server_module._active_session_id
        and server_module._active_session_id not in server_module._sessions
    ):
        server_module._active_session_id = None

    payload: dict[str, object] = {
        "order": server_module._session_order,
        "active_session_id": server_module._active_session_id,
    }
    server_module._write_json_atomic(server_module._sessions_registry_path(), payload)


def _save_session_snapshot(server_module: ModuleType, session: PlotSession) -> None:
    snapshot_path = server_module._session_snapshot_path(session.id)
    if not session.artifacts_root:
        session.artifacts_root = str(snapshot_path.parent.resolve())
    server_module._session_workspace_id(session)
    payload = cast(dict[str, object], session.model_dump(mode="json"))
    server_module._write_json_atomic(snapshot_path, payload)


def _set_active_session(
    server_module: ModuleType,
    session_id: str | None,
    *,
    clear_plot_mode: bool,
) -> None:
    if session_id is None:
        server_module._active_session_id = None
        server_module._session = None
    else:
        target = server_module._sessions.get(session_id)
        if target is None:
            raise HTTPException(
                status_code=404, detail=f"Session not found: {session_id}"
            )
        server_module._active_session_id = session_id
        server_module._session = target
        server_module.set_workspace_dir(server_module._workspace_for_session(target))

    if clear_plot_mode:
        server_module._clear_plot_mode_state()

    server_module._save_session_registry()


def _session_summary(
    server_module: ModuleType, session: PlotSession
) -> dict[str, object]:
    server_module._ensure_workspace_name(session)
    workspace_id = server_module._session_workspace_id(session)
    pending_count = sum(
        1
        for annotation in session.annotations
        if annotation.status == AnnotationStatus.pending
    )
    title = server_module._session_title(session)
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


def _bootstrap_payload(
    server_module: ModuleType,
    *,
    mode: Literal["annotation", "plot"],
    session: PlotSession | None,
    plot_mode: PlotModeState | None,
) -> dict[str, object]:
    active_session_id = session.id if session is not None else None
    active_workspace_id = (
        server_module._session_workspace_id(session)
        if session is not None
        else plot_mode.id
        if plot_mode is not None
        else server_module._active_workspace_id()
    )
    return {
        "mode": mode,
        "session": session.model_dump(mode="json") if session is not None else None,
        "plot_mode": (
            plot_mode.model_dump(mode="json") if plot_mode is not None else None
        ),
        "sessions": server_module._list_session_summaries(),
        "active_session_id": active_session_id,
        "active_workspace_id": active_workspace_id,
        "update_status": server_module._build_update_status_payload(
            allow_network=False
        ),
    }


def init_plot_mode_session(
    server_module: ModuleType,
    *,
    workspace_dir: str | Path | None = None,
    persist_workspace: bool = False,
) -> PlotModeState:
    """Initialise plot mode state (no script/image selected yet)."""
    server_module._ensure_session_store_loaded()

    resolved_workspace: Path | None = None
    if workspace_dir is not None:
        resolved_workspace = Path(workspace_dir).resolve()

    if server_module._plot_mode is not None:
        server_module._clear_plot_mode_state()

    server_module._plot_mode = server_module._new_plot_mode_state(
        workspace_dir=resolved_workspace,
        is_workspace=persist_workspace,
    )
    if persist_workspace:
        server_module._save_plot_mode_snapshot(server_module._plot_mode)
    server_module.set_workspace_dir(Path(server_module._plot_mode.workspace_dir))
    server_module._set_active_session(None, clear_plot_mode=False)
    return server_module._plot_mode
