from __future__ import annotations

from fastapi import APIRouter, Request

from ..services import versioning as versioning_service
from .schemas import CheckoutVersionRequest, RenameBranchRequest, SubmitScriptRequest

router = APIRouter()


@router.post("/api/script")
async def submit_script(body: SubmitScriptRequest, session_id: str | None = None):
    return await versioning_service.submit_script(body, session_id=session_id)


@router.post("/api/checkout")
async def checkout_version(body: CheckoutVersionRequest):
    return await versioning_service.checkout_version(body)


@router.get("/api/revisions")
async def get_revisions():
    return await versioning_service.get_revisions()


@router.post("/api/branches/{branch_id}/checkout")
async def checkout_branch_head(branch_id: str):
    return await versioning_service.checkout_branch_head(branch_id)


@router.patch("/api/branches/{branch_id}")
async def rename_branch(
    branch_id: str,
    body: RenameBranchRequest,
    request: Request,
):
    return await versioning_service.rename_branch(
        branch_id,
        body,
        request.app.state.runtime,
    )
