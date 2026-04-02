"""Event and websocket helper implementations extracted from openplot.server."""

from __future__ import annotations

from types import ModuleType
from typing import Any


async def _broadcast(server_module: ModuleType, event: dict) -> None:
    """Send a JSON event to all connected WebSocket clients."""
    payload = server_module.json.dumps(event)
    dead: list[Any] = []
    ws_clients = server_module._runtime_ws_clients()
    for ws in ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


async def _broadcast_plot_mode_message_update(
    server_module: ModuleType,
    state,
    message,
) -> None:
    await server_module._broadcast(
        {
            "type": "plot_mode_message_updated",
            "plot_mode_id": state.id,
            "updated_at": state.updated_at,
            "message": message.model_dump(mode="json"),
        }
    )


async def _broadcast_plot_mode_preview(server_module: ModuleType, state) -> None:
    await server_module._broadcast_plot_mode_state(state)
    await server_module._broadcast(
        {
            "type": "plot_updated",
            "plot_type": state.plot_type,
            "revision": 0,
            "reason": "plot_mode_preview",
        }
    )
