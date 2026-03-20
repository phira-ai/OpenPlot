"""Naming and rename-related validation helpers."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException

from ..models import Branch, FixJob

_MAX_NAME_LENGTH = 120


def _normalize_name(
    raw_name: object | None,
    *,
    missing_detail: str,
    empty_detail: str,
    too_long_detail: str,
) -> str:
    if raw_name is None:
        raise HTTPException(status_code=400, detail=missing_detail)

    next_name = str(raw_name).strip()
    if not next_name:
        raise HTTPException(status_code=400, detail=empty_detail)
    if len(next_name) > _MAX_NAME_LENGTH:
        raise HTTPException(status_code=400, detail=too_long_detail)
    return next_name


def normalize_workspace_name(raw_name: object | None) -> str:
    return _normalize_name(
        raw_name,
        missing_detail="Missing workspace_name",
        empty_detail="Workspace name cannot be empty",
        too_long_detail="Workspace name must be 120 characters or fewer",
    )


def normalize_branch_name(raw_name: object | None) -> str:
    return _normalize_name(
        raw_name,
        missing_detail="Missing branch name",
        empty_detail="Branch name cannot be empty",
        too_long_detail="Branch name must be 120 characters or fewer",
    )


def ensure_unique_branch_name(
    branches: Iterable[Branch],
    *,
    current_branch_id: str,
    candidate: str,
) -> None:
    if any(
        branch.id != current_branch_id and branch.name == candidate
        for branch in branches
    ):
        raise HTTPException(
            status_code=409,
            detail="A branch with that name already exists",
        )


def sync_fix_job_branch_names(
    jobs: Iterable[FixJob],
    *,
    session_id: str,
    branch_id: str,
    branch_name: str,
) -> None:
    for job in jobs:
        if job.session_id == session_id and job.branch_id == branch_id:
            job.branch_name = branch_name
