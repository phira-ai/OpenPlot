from __future__ import annotations

from fastapi import APIRouter

from ..services import runners as runner_services
from .schemas import PreferencesRequest

router = APIRouter()


@router.get("/api/preferences")
async def get_preferences():
    return await runner_services.get_preferences()


@router.post("/api/preferences")
async def set_preferences(body: PreferencesRequest):
    return await runner_services.set_preferences(body)
