"""Artifact and feedback workflow service helpers."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.responses import FileResponse

from ..feedback import compile_feedback

if TYPE_CHECKING:
    from .runtime import BackendRuntime


async def get_plot(
    runtime: "BackendRuntime",
    *,
    session_id: str | None = None,
    version_id: str | None = None,
    plot_mode: bool = False,
    workspace_id: str | None = None,
) -> FileResponse:
    from .. import server

    def _resolve_plot() -> tuple[Path, str]:
        server._ensure_session_store_loaded()
        return server._resolve_plot_response(
            session_id=session_id,
            version_id=version_id,
            plot_mode=plot_mode,
            workspace_id=workspace_id,
        )

    plot_path, _ = server._with_runtime(runtime, _resolve_plot)
    if not plot_path.exists():
        raise HTTPException(status_code=404, detail="Plot file not found")

    media_type = server._media_type_for_plot_path(plot_path)
    return FileResponse(str(plot_path), media_type=media_type)


async def export_plot_mode_workspace(
    runtime: "BackendRuntime",
    *,
    workspace_id: str | None = None,
) -> FileResponse:
    from .. import server

    def _resolve_export() -> tuple[Path, str, str, str, str]:
        server._ensure_session_store_loaded()
        state = server._resolve_plot_mode_workspace(workspace_id)

        plot_path_raw = (state.current_plot or "").strip()
        if not plot_path_raw:
            raise HTTPException(
                status_code=409, detail="No plot preview is available yet"
            )
        plot_path = Path(plot_path_raw)
        if not plot_path.exists():
            raise HTTPException(status_code=404, detail="Plot artifact not found")

        script_path = server._plot_mode_generated_script_path(state)
        if not script_path.exists():
            script = (state.current_script or "").strip()
            if not script:
                raise HTTPException(
                    status_code=409,
                    detail="No generated script is available yet",
                )
            script_path.write_text(script, encoding="utf-8")

        ext = plot_path.suffix.lower() or ".png"
        export_stem = server._safe_export_stem(
            state.workspace_name, default="plot_workspace"
        )
        export_dir = server._plot_mode_artifacts_dir(state) / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_zip_path = export_dir / f"{state.id}.zip"
        return plot_path, str(script_path), str(export_zip_path), ext, export_stem

    plot_path, script_path_str, export_zip_path_str, ext, export_stem = (
        server._with_runtime(
            runtime,
            _resolve_export,
        )
    )
    script_path = Path(script_path_str)
    export_zip_path = Path(export_zip_path_str)

    with zipfile.ZipFile(
        export_zip_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.write(plot_path, arcname=f"plot{ext}")
        archive.write(script_path, arcname="script.py")

    return FileResponse(
        str(export_zip_path),
        media_type="application/zip",
        filename=f"openplot_{export_stem}.zip",
    )


async def get_feedback(*, session_id: str | None = None) -> dict[str, object]:
    from .. import server

    session = server._resolve_request_session(session_id)
    scoped_annotations = server.pending_annotations_for_context(session)

    scoped_session = session.model_copy(deep=True)
    scoped_session.annotations = scoped_annotations
    prompt = compile_feedback(scoped_session)

    return {
        "prompt": prompt,
        "annotation_count": len(scoped_annotations),
        "active_branch_id": session.active_branch_id,
        "checked_out_version_id": session.checked_out_version_id,
        "target_annotation_id": scoped_annotations[0].id
        if scoped_annotations
        else None,
    }
