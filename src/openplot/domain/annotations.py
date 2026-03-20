"""Shared helpers for annotation ordering and context filtering."""

from __future__ import annotations

from typing import Any, Mapping

from ..models import Annotation, AnnotationStatus, PlotSession


def pending_annotations_for_context(session: PlotSession) -> list[Annotation]:
    """Pending annotations in the active branch, ordered FIFO."""
    active_branch_id = session.active_branch_id
    pending = [
        ann
        for ann in session.annotations
        if ann.status == AnnotationStatus.pending
        and (not ann.branch_id or ann.branch_id == active_branch_id)
    ]
    return sorted(pending, key=lambda ann: (ann.created_at, ann.id))


def pending_annotation_dicts_for_context(
    session: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Pending annotation payloads in the active branch, ordered FIFO."""
    annotations = session.get("annotations", [])
    if not isinstance(annotations, list):
        return []

    active_branch_id = session.get("active_branch_id")
    pending = [
        ann
        for ann in annotations
        if isinstance(ann, dict)
        and ann.get("status") == AnnotationStatus.pending.value
        and (
            not active_branch_id
            or not ann.get("branch_id")
            or ann.get("branch_id") == active_branch_id
        )
    ]
    return sorted(
        pending,
        key=lambda ann: (str(ann.get("created_at") or ""), str(ann.get("id") or "")),
    )
