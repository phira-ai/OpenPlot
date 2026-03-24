"""Annotation workflow service helpers."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.responses import FileResponse

if TYPE_CHECKING:
    from ..api.schemas import AnnotationUpdateRequest
    from ..models import Annotation


async def add_annotation(annotation: "Annotation") -> dict[str, object]:
    from .. import server

    session = server.get_session()

    active_branch = server._active_branch(session)
    base_version_id = session.checked_out_version_id or active_branch.head_version_id

    if base_version_id and base_version_id != active_branch.head_version_id:
        active_branch = server._create_branch(session, base_version_id=base_version_id)
        session.active_branch_id = active_branch.id

    annotation.plot_id = session.id
    annotation.base_version_id = base_version_id
    annotation.branch_id = active_branch.id
    session.annotations.append(annotation)
    server._touch_session(session)
    server._persist_session(session, promote=True)

    await server._broadcast(
        {
            "type": "annotation_added",
            "session_id": session.id,
            "annotation": annotation.model_dump(),
            "active_branch_id": session.active_branch_id,
            "checked_out_version_id": session.checked_out_version_id,
        }
    )
    return {"status": "ok", "id": annotation.id}


async def export_annotation_plot(annotation_id: str) -> FileResponse:
    from .. import server

    session = server.get_session()
    ann = next((a for a in session.annotations if a.id == annotation_id), None)
    if ann is None:
        raise HTTPException(status_code=404, detail="Annotation not found")

    if (
        ann.status != server.AnnotationStatus.addressed
        or not ann.addressed_in_version_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Only addressed annotations can be exported",
        )

    version = server._get_version(session, ann.addressed_in_version_id)
    plot_path = Path(version.plot_artifact_path)
    if not plot_path.exists():
        raise HTTPException(status_code=404, detail="Plot artifact not found")

    if not version.script_artifact_path:
        raise HTTPException(status_code=404, detail="Script artifact not found")
    script_path = Path(version.script_artifact_path)
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="Script artifact not found")

    ext = plot_path.suffix.lower() or ".png"
    branch_part = ann.branch_id or "branch"
    filename = f"openplot_{branch_part}_annotation_{ann.id}.zip"

    export_dir = server._session_artifacts_root(session) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_zip_path = export_dir / f"{ann.id}_{version.id}.zip"

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
        filename=filename,
    )


async def delete_annotation(annotation_id: str) -> dict[str, object]:
    from .. import server

    session = server.get_session()
    ann = next((a for a in session.annotations if a.id == annotation_id), None)
    if ann is None:
        raise HTTPException(status_code=404, detail="Annotation not found")

    deleted_ids = {annotation_id}

    if ann.status == server.AnnotationStatus.addressed:
        if not ann.addressed_in_version_id:
            raise HTTPException(
                status_code=409,
                detail="Addressed annotation has no version reference",
            )

        active_branch = server._active_branch(session)
        tip_version_id = active_branch.head_version_id
        if ann.addressed_in_version_id != tip_version_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Tip-only undo: only the active branch head annotation "
                    "can be deleted"
                ),
            )

        tip_version = server._get_version(session, tip_version_id)
        parent_id = tip_version.parent_version_id
        if not parent_id:
            raise HTTPException(
                status_code=409,
                detail="Cannot undo the root version",
            )

        active_branch.head_version_id = parent_id
        session.versions = [v for v in session.versions if v.id != tip_version_id]
        server._delete_version_artifacts(session, tip_version_id)

        stale_pending_ids = {
            a.id
            for a in session.annotations
            if a.status == server.AnnotationStatus.pending
            and a.base_version_id == tip_version_id
        }
        deleted_ids.update(stale_pending_ids)
        session.annotations = [
            a for a in session.annotations if a.id not in deleted_ids
        ]

        server._checkout_version(session, parent_id, branch_id=active_branch.id)

        await server._broadcast(
            {
                "type": "plot_updated",
                "session_id": session.id,
                "version_id": session.checked_out_version_id,
                "plot_type": session.plot_type,
                "revision": len(session.revision_history),
                "active_branch_id": session.active_branch_id,
                "checked_out_version_id": session.checked_out_version_id,
                "reason": "undo_tip",
            }
        )
    else:
        session.annotations = [a for a in session.annotations if a.id != annotation_id]

    server._touch_session(session)
    server._persist_session(session, promote=True)

    await server._broadcast(
        {
            "type": "annotation_deleted",
            "session_id": session.id,
            "id": annotation_id,
            "deleted_ids": sorted(deleted_ids),
        }
    )

    return {"status": "ok", "deleted_ids": sorted(deleted_ids)}


async def update_annotation(
    annotation_id: str,
    updates: "AnnotationUpdateRequest",
) -> dict[str, object]:
    from .. import server

    session = server.get_session()
    for ann in session.annotations:
        if ann.id == annotation_id:
            if updates.feedback is not None:
                ann.feedback = updates.feedback
            if "status" in updates.model_fields_set:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Annotation status is system-managed. "
                        "Use script submission to address feedback and tip undo to rewind."
                    ),
                )
            server._touch_session(session)
            server._persist_session(session, promote=True)
            await server._broadcast(
                {
                    "type": "annotation_updated",
                    "session_id": session.id,
                    "annotation": ann.model_dump(),
                }
            )
            return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Annotation not found")
