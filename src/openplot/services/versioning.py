"""Versioning workflow service helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException

from .naming import (
    ensure_unique_branch_name,
    normalize_branch_name,
    sync_fix_job_branch_names,
)

if TYPE_CHECKING:
    from ..api.schemas import (
        CheckoutVersionRequest,
        RenameBranchRequest,
        SubmitScriptRequest,
    )
    from .runtime import BackendRuntime


async def checkout_version(body: "CheckoutVersionRequest") -> dict[str, object]:
    from .. import server

    session = server.get_session()
    version_id = body.version_id.strip()
    branch_id_raw = body.branch_id
    branch_id = str(branch_id_raw).strip() if branch_id_raw else None

    if not version_id:
        raise HTTPException(status_code=400, detail="Missing version_id")

    version = server._checkout_version(session, version_id, branch_id=branch_id)
    server._touch_session(session)
    server._persist_session(session, promote=True)

    await server._broadcast(
        {
            "type": "plot_updated",
            "session_id": session.id,
            "version_id": session.checked_out_version_id,
            "plot_type": session.plot_type,
            "revision": len(session.revision_history),
            "active_branch_id": session.active_branch_id,
            "checked_out_version_id": session.checked_out_version_id,
            "reason": "checkout",
        }
    )

    return {
        "status": "ok",
        "version_id": version.id,
        "active_branch_id": session.active_branch_id,
        "checked_out_version_id": session.checked_out_version_id,
    }


async def checkout_branch_head(branch_id: str) -> dict[str, object]:
    from .. import server

    session = server.get_session()
    branch = server._get_branch(session, branch_id)
    server._checkout_version(session, branch.head_version_id, branch_id=branch.id)
    server._touch_session(session)
    server._persist_session(session, promote=True)

    await server._broadcast(
        {
            "type": "plot_updated",
            "session_id": session.id,
            "version_id": session.checked_out_version_id,
            "plot_type": session.plot_type,
            "revision": len(session.revision_history),
            "active_branch_id": session.active_branch_id,
            "checked_out_version_id": session.checked_out_version_id,
            "reason": "branch_switch",
        }
    )

    return {
        "status": "ok",
        "branch_id": branch.id,
        "checked_out_version_id": session.checked_out_version_id,
    }


async def rename_branch(
    branch_id: str,
    body: "RenameBranchRequest",
    runtime: "BackendRuntime",
) -> dict[str, object]:
    from .. import server

    def _rename_branch_request() -> dict[str, object]:
        session = server.get_session()
        branch = server._get_branch(session, branch_id)

        raw_name = body.name if body.name is not None else body.branch_name
        next_name = normalize_branch_name(raw_name)
        ensure_unique_branch_name(
            session.branches,
            current_branch_id=branch.id,
            candidate=next_name,
        )

        branch.name = next_name
        sync_fix_job_branch_names(
            server._runtime_fix_jobs_map().values(),
            session_id=session.id,
            branch_id=branch.id,
            branch_name=next_name,
        )

        server._touch_session(session)
        server._persist_session(session, promote=True)

        return {
            "status": "ok",
            "branch": branch.model_dump(),
            "active_branch_id": session.active_branch_id,
        }

    return server._with_runtime(runtime, _rename_branch_request)


async def submit_script(
    body: "SubmitScriptRequest",
    *,
    session_id: str | None = None,
) -> dict[str, object]:
    from .. import server

    session = server._resolve_request_session(session_id)
    code = body.code
    if not code.strip():
        raise HTTPException(status_code=400, detail="Empty script")

    target_annotation_id = body.annotation_id
    target_annotation = server._resolve_target_annotation(session, target_annotation_id)

    if not target_annotation.base_version_id:
        target_annotation.base_version_id = (
            session.checked_out_version_id
            or server._active_branch(session).head_version_id
        )
    if not target_annotation.branch_id:
        target_annotation.branch_id = session.active_branch_id

    target_branch = server._get_branch(session, target_annotation.branch_id)
    parent_version_id = target_branch.head_version_id
    target_annotation.base_version_id = parent_version_id

    source_script_path = (
        server._resolve_session_file_path(session, session.source_script_path)
        if session.source_script_path
        else None
    )

    base_dir = (
        source_script_path.parent
        if source_script_path is not None and source_script_path.parent.exists()
        else server._workspace_for_session(session)
    )

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".py",
        prefix="openplot_candidate_",
        dir=base_dir,
        delete=False,
    ) as tmp:
        tmp.write(code)
        candidate_path = Path(tmp.name)

    result = server.execute_script(
        candidate_path,
        work_dir=base_dir,
        capture_dir=server._new_run_output_dir(session),
        python_executable=server._resolve_python_executable(session),
    )

    if not result.success:
        raise HTTPException(
            status_code=422,
            detail={
                "error": result.error,
                "stderr": result.stderr,
                "stdout": result.stdout,
                "candidate_script_path": str(candidate_path),
            },
        )

    candidate_path.unlink(missing_ok=True)

    session.source_script = code
    if not session.source_script_path:
        generated_path = (
            server._session_artifacts_root(session)
            / "working"
            / "openplot_generated.py"
        )
        generated_path.parent.mkdir(parents=True, exist_ok=True)
        session.source_script_path = str(generated_path)

    if not result.plot_path:
        raise HTTPException(
            status_code=500,
            detail="Script succeeded but no plot artifact was produced.",
        )

    session.plot_type = result.plot_type or "svg"

    version_id = server._new_id()
    script_artifact_path, plot_artifact_path = server._write_version_artifacts(
        session,
        version_id,
        script=code,
        plot_path=result.plot_path,
    )
    version_node = server.VersionNode(
        id=version_id,
        parent_version_id=parent_version_id,
        branch_id=target_branch.id,
        annotation_id=target_annotation.id,
        script_artifact_path=script_artifact_path,
        plot_artifact_path=plot_artifact_path,
        plot_type=session.plot_type,
    )
    session.versions.append(version_node)

    target_branch.head_version_id = version_id
    session.active_branch_id = target_branch.id

    target_annotation.status = server.AnnotationStatus.addressed
    target_annotation.addressed_in_version_id = version_id

    server._checkout_version(session, version_id, branch_id=target_branch.id)
    server._touch_session(session)
    server._persist_session(session, promote=True)

    await server._broadcast(
        {
            "type": "plot_updated",
            "session_id": session.id,
            "version_id": session.checked_out_version_id,
            "plot_type": session.plot_type,
            "revision": len(session.revision_history),
            "active_branch_id": session.active_branch_id,
            "checked_out_version_id": session.checked_out_version_id,
            "reason": "new_version",
            "annotation_id": target_annotation.id,
        }
    )

    return {
        "status": "ok",
        "plot_type": session.plot_type,
        "revision": len(session.revision_history),
        "version_id": version_id,
        "active_branch_id": session.active_branch_id,
        "checked_out_version_id": session.checked_out_version_id,
        "addressed_annotation_id": target_annotation.id,
    }


async def get_revisions() -> list[dict[str, object]]:
    from .. import server

    session = server.get_session()
    server._rebuild_revision_history(session)
    return [revision.model_dump() for revision in session.revision_history]
