from __future__ import annotations

from fastapi import APIRouter, WebSocket

from .. import server

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await server.websocket_endpoint(ws)
