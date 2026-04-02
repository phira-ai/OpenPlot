"""Version artifact and revision helpers extracted from openplot.server."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import ModuleType
from typing import Literal

from .models import Annotation, Branch, PlotSession, Revision, VersionNode


def _session_artifacts_root(server_module: ModuleType, session: PlotSession) -> Path:
    if session.artifacts_root:
        root = Path(session.artifacts_root)
    else:
        root = server_module._state_root() / "sessions" / session.id
        session.artifacts_root = str(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _is_managed_workspace_path(server_module: ModuleType, path: Path) -> bool:
    resolved = path.resolve()
    for root in (
        server_module._sessions_root_dir().resolve(),
        server_module._plot_mode_root_dir().resolve(),
    ):
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _version_artifact_dir(
    server_module: ModuleType, session: PlotSession, version_id: str
) -> Path:
    version_dir = (
        server_module._session_artifacts_root(session) / "versions" / version_id
    )
    version_dir.mkdir(parents=True, exist_ok=True)
    return version_dir


def _new_run_output_dir(server_module: ModuleType, session: PlotSession) -> Path:
    run_dir = (
        server_module._session_artifacts_root(session)
        / "runs"
        / server_module._new_id()
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_version_artifacts(
    server_module: ModuleType,
    session: PlotSession,
    version_id: str,
    *,
    script: str | None,
    plot_path: str,
) -> tuple[str | None, str]:
    """Persist immutable script/plot artifacts for one version."""
    plot_src = Path(plot_path).resolve()
    if not plot_src.exists():
        raise server_module.HTTPException(
            status_code=500,
            detail=f"Plot artifact not found on disk: {plot_src}",
        )

    version_dir = server_module._version_artifact_dir(session, version_id)

    script_artifact_path: str | None = None
    if script is not None:
        script_file = version_dir / "script.py"
        script_file.write_text(script, encoding="utf-8")
        script_artifact_path = str(script_file)

    ext = plot_src.suffix.lower() or ".png"
    plot_file = version_dir / f"plot{ext}"
    shutil.copy2(plot_src, plot_file)

    return script_artifact_path, str(plot_file)


def _delete_version_artifacts(
    server_module: ModuleType, session: PlotSession, version_id: str
) -> None:
    version_dir = (
        server_module._session_artifacts_root(session) / "versions" / version_id
    )
    shutil.rmtree(version_dir, ignore_errors=True)


def _find_branch(
    server_module: ModuleType, session: PlotSession, branch_id: str
) -> Branch | None:
    del server_module
    return next((b for b in session.branches if b.id == branch_id), None)


def _get_branch(
    server_module: ModuleType, session: PlotSession, branch_id: str
) -> Branch:
    branch = server_module._find_branch(session, branch_id)
    if branch is None:
        raise server_module.HTTPException(
            status_code=404,
            detail=f"Branch not found: {branch_id}",
        )
    return branch


def _active_branch(server_module: ModuleType, session: PlotSession) -> Branch:
    if not session.active_branch_id:
        raise server_module.HTTPException(
            status_code=409,
            detail="Session has no active branch",
        )
    return server_module._get_branch(session, session.active_branch_id)


def _find_version(
    server_module: ModuleType, session: PlotSession, version_id: str
) -> VersionNode | None:
    del server_module
    return next((v for v in session.versions if v.id == version_id), None)


def _get_version(
    server_module: ModuleType, session: PlotSession, version_id: str
) -> VersionNode:
    version = server_module._find_version(session, version_id)
    if version is None:
        raise server_module.HTTPException(
            status_code=404,
            detail=f"Version not found: {version_id}",
        )
    return version


def _safe_read_text(server_module: ModuleType, path: str | None) -> str | None:
    if not path:
        return None
    resolved_path = Path(path)
    if not resolved_path.exists():
        return None
    return server_module._read_file_text(resolved_path)


def _media_type_for_plot_path(server_module: ModuleType, plot_path: Path) -> str:
    del server_module
    media_types = {
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".pdf": "application/pdf",
    }
    return media_types.get(plot_path.suffix.lower(), "application/octet-stream")


def _branch_chain(
    server_module: ModuleType, session: PlotSession, head_version_id: str
) -> list[VersionNode]:
    del server_module
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


def _rebuild_revision_history(server_module: ModuleType, session: PlotSession) -> None:
    """Keep legacy linear revision list aligned with active branch."""
    if not session.active_branch_id:
        session.revision_history = []
        return
    branch = server_module._get_branch(session, session.active_branch_id)
    chain = server_module._branch_chain(session, branch.head_version_id)
    revisions: list[Revision] = []
    for node in chain:
        revisions.append(
            Revision(
                script=server_module._safe_read_text(node.script_artifact_path) or "",
                plot_path=node.plot_artifact_path,
                plot_type=node.plot_type,
                timestamp=node.timestamp,
            )
        )
    session.revision_history = revisions


def _checkout_version(
    server_module: ModuleType,
    session: PlotSession,
    version_id: str,
    *,
    branch_id: str | None = None,
) -> VersionNode:
    """Set session view pointers to one version."""
    if branch_id is not None:
        server_module._get_branch(session, branch_id)
        session.active_branch_id = branch_id
    version = server_module._get_version(session, version_id)
    session.checked_out_version_id = version.id
    session.current_plot = version.plot_artifact_path
    session.plot_type = version.plot_type
    session.source_script = server_module._safe_read_text(version.script_artifact_path)
    server_module._rebuild_revision_history(session)
    return version


def _next_branch_name(server_module: ModuleType, session: PlotSession) -> str:
    del server_module
    taken = {b.name for b in session.branches}
    index = 1
    while True:
        name = f"branch-{index}"
        if name not in taken:
            return name
        index += 1


def _create_branch(
    server_module: ModuleType, session: PlotSession, *, base_version_id: str
) -> Branch:
    branch = Branch(
        id=server_module._new_id(),
        name=server_module._next_branch_name(session),
        base_version_id=base_version_id,
        head_version_id=base_version_id,
    )
    session.branches.append(branch)
    return branch


def _resolve_target_annotation(
    server_module: ModuleType,
    session: PlotSession,
    annotation_id: str | None,
) -> Annotation:
    if annotation_id:
        annotation = next(
            (
                candidate
                for candidate in session.annotations
                if candidate.id == annotation_id
            ),
            None,
        )
        if annotation is None:
            raise server_module.HTTPException(
                status_code=404,
                detail="Annotation not found",
            )
        if annotation.status != server_module.AnnotationStatus.pending:
            raise server_module.HTTPException(
                status_code=409,
                detail="Target annotation is already addressed",
            )
        return annotation

    pending = server_module.pending_annotations_for_context(session)
    if not pending:
        raise server_module.HTTPException(
            status_code=409,
            detail="No pending annotations in the current branch/context",
        )
    return pending[0]


def _init_version_graph(
    server_module: ModuleType,
    session: PlotSession,
    *,
    script: str | None,
    plot_path: str,
    plot_type: Literal["svg", "raster"],
) -> None:
    main_branch_id = server_module._new_id()
    root_version_id = server_module._new_id()
    script_artifact, plot_artifact = server_module._write_version_artifacts(
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
    server_module._checkout_version(session, root_version_id, branch_id=main_branch_id)
