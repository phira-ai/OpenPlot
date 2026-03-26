"""MCP stdio server for OpenPlot agent integration."""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Image

from .domain.annotations import pending_annotation_dicts_for_context
from .domain.regions import region_bounds_from_points, region_zone_hint_from_bounds
from .runtime_text import decode_bytes

PORT_FILE = Path.home() / ".openplot" / "port"


class BackendError(RuntimeError):
    """Raised when the OpenPlot backend request fails."""


@dataclass(slots=True)
class BackendClient:
    """Small HTTP client for talking to the OpenPlot FastAPI backend."""

    base_url: str
    timeout_s: float = 20.0
    session_id: str | None = None

    def _with_session(self, path: str) -> str:
        normalized = path.strip()
        if not self.session_id:
            return normalized

        separator = "&" if "?" in normalized else "?"
        encoded_session_id = quote(self.session_id, safe="")
        return f"{normalized}{separator}session_id={encoded_session_id}"

    def get(self, path: str) -> dict:
        req = Request(f"{self.base_url}{self._with_session(path)}", method="GET")
        return _request_json(req, timeout_s=self.timeout_s)

    def post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            f"{self.base_url}{self._with_session(path)}",
            method="POST",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        return _request_json(req, timeout_s=self.timeout_s)


def _decode_data_url(data_url_or_base64: str) -> tuple[str, bytes]:
    """Decode a data URL (or raw base64 string) into MIME type + bytes."""
    payload = data_url_or_base64.strip()
    mime_type = "image/png"

    if payload.startswith("data:"):
        try:
            header, payload = payload.split(",", 1)
        except ValueError as exc:
            raise ValueError("Invalid data URL payload") from exc

        # Example: data:image/png;base64
        meta = header[5:]
        first = meta.split(";", 1)[0].strip().lower()
        if first:
            mime_type = first

    payload = "".join(payload.split())
    if not payload:
        raise ValueError("Empty base64 payload")

    try:
        image_bytes = base64.b64decode(payload, validate=True)
    except binascii.Error:
        # Some encoders omit padding; fallback to permissive decode.
        try:
            image_bytes = base64.b64decode(payload, validate=False)
        except binascii.Error as exc:
            raise ValueError("Invalid base64 image payload") from exc

    if not image_bytes:
        raise ValueError("Decoded image payload is empty")

    return mime_type, image_bytes


def _image_format_from_mime(mime_type: str) -> str:
    """Map MIME type to FastMCP Image format token."""
    normalized = mime_type.strip().lower()
    if "/" in normalized:
        normalized = normalized.split("/", 1)[1]
    normalized = normalized.split(";", 1)[0]

    if normalized in {"jpg", "jpeg"}:
        return "jpeg"
    if normalized in {"png", "gif", "webp"}:
        return normalized
    return "png"


def _request_json(req: Request, *, timeout_s: float) -> dict:
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            body = decode_bytes(resp.read())
            try:
                return json.loads(body) if body else {}
            except json.JSONDecodeError as exc:
                raise BackendError(
                    f"Invalid JSON from backend at {req.full_url}: {body}"
                ) from exc
    except HTTPError as exc:
        body = decode_bytes(exc.read())
        raise BackendError(f"HTTP {exc.code} for {req.full_url}: {body}") from exc
    except URLError as exc:
        raise BackendError(
            f"Could not connect to backend at {req.full_url}: {exc}"
        ) from exc


def _normalize_optional_env(key: str) -> str | None:
    raw_value = os.getenv(key)
    if raw_value is None:
        return None
    normalized = raw_value.strip()
    return normalized or None


def discover_server_url(explicit_url: str | None = None) -> str:
    """Resolve the OpenPlot backend URL from explicit arg, env, or port file."""
    if explicit_url:
        return explicit_url.rstrip("/")

    env_url = os.getenv("OPENPLOT_SERVER_URL")
    if env_url:
        return env_url.rstrip("/")

    if PORT_FILE.exists():
        raw = PORT_FILE.read_text().strip()
        try:
            port = int(raw)
        except ValueError as exc:
            raise BackendError(f"Invalid port in {PORT_FILE}: {raw!r}") from exc
        return f"http://127.0.0.1:{port}"

    raise BackendError(
        "Could not find a running OpenPlot server. Start one with "
        "`openplot serve` or set OPENPLOT_SERVER_URL."
    )


def create_mcp_server(server_url: str) -> FastMCP:
    """Create an MCP server bound to a specific OpenPlot backend URL."""
    client = BackendClient(
        base_url=server_url,
        session_id=_normalize_optional_env("OPENPLOT_SESSION_ID"),
    )

    mcp = FastMCP(
        name="openplot",
        instructions=(
            "Use OpenPlot tools to read pending visual feedback, inspect plot context, "
            "and submit updated plotting scripts. Treat "
            "python_interpreter.available_packages from plot context as a strict "
            "allowlist for third-party imports. Never import a third-party package "
            "that is not listed there. "
            "For raster-region annotations, treat "
            "attached crop images as authoritative local scope and resolve ambiguous "
            "phrases to crop-visible content unless the user explicitly asks for global edits."
        ),
    )

    @mcp.tool(
        name="get_pending_feedback",
        description=(
            "Return the compiled visual feedback prompt for all pending annotations "
            "from the current OpenPlot session."
        ),
    )
    def get_pending_feedback() -> dict:
        return client.get("/api/feedback")

    @mcp.tool(
        name="get_pending_feedback_with_images",
        description=(
            "Return pending visual feedback with image crops (when available) for "
            "raster region annotations."
        ),
        structured_output=False,
    )
    def get_pending_feedback_with_images(max_images: int = 8) -> Any:
        session = client.get("/api/session")
        feedback = client.get("/api/feedback")

        pending = pending_annotation_dicts_for_context(session)
        script_path = session.get("source_script_path") or "<unknown>"
        plot_type = session.get("plot_type") or "unknown"
        active_branch_id = session.get("active_branch_id") or "<none>"
        checked_out_version_id = session.get("checked_out_version_id") or "<none>"
        target_annotation_id = feedback.get("target_annotation_id") or "<none>"

        content: list[Any] = [
            "\n".join(
                [
                    "## Pending Plot Feedback (Multimodal)",
                    f"- Pending annotations: {len(pending)}",
                    f"- Plot type: {plot_type}",
                    f"- Script path: {script_path}",
                    f"- Active branch: {active_branch_id}",
                    f"- Checked out version: {checked_out_version_id}",
                    f"- FIFO target annotation: {target_annotation_id}",
                    "",
                    "### Scope Rules (must follow)",
                    "- For raster-region annotations, treat attached crop images as authoritative grounding.",
                    "- Scope is LOCAL_REGION: ambiguous references apply only to content visible in the selected region/crop.",
                    '- Do not modify outside-region content unless feedback explicitly requests global scope ("all charts", "entire figure", "across all subplots").',
                    "- Prefer minimal localized edits.",
                    "",
                    "### Compiled Feedback",
                    feedback.get("prompt", "No compiled feedback available."),
                ]
            )
        ]

        images_added = 0
        for index, ann in enumerate(pending, start=1):
            ann_id = ann.get("id", "unknown")
            ann_feedback = ann.get("feedback", "")
            region = ann.get("region")
            element = ann.get("element_info")

            lines = [
                f"### Annotation {index}",
                f"- id: {ann_id}",
                f"- feedback: {ann_feedback}",
            ]

            if element:
                lines.append(f"- mode: svg-element ({element.get('tag', 'unknown')})")
                lines.append("- scope: LOCAL_ELEMENT")
                lines.append(
                    "- disambiguation: ambiguous references resolve to the selected element"
                )
                text = element.get("text_content")
                if text:
                    lines.append(f"- text: {text}")
                xpath = element.get("xpath")
                if xpath:
                    lines.append(f"- xpath: {xpath}")

            if region:
                lines.append(f"- mode: raster-region ({region.get('type', 'unknown')})")
                lines.append("- scope: LOCAL_REGION")
                lines.append("- grounding: use the attached crop image")
                lines.append(
                    "- disambiguation: ambiguous references resolve to crop-visible elements only"
                )
                points = region.get("points")
                bounds = region_bounds_from_points(points)
                if bounds is not None:
                    x0, y0, x1, y1 = bounds
                    lines.append(
                        f"- region(norm): ({x0:.3f}, {y0:.3f}) -> ({x1:.3f}, {y1:.3f})"
                    )
                    lines.append(f"- zone-hint: {region_zone_hint_from_bounds(bounds)}")

            content.append("\n".join(lines))

            crop_data = region.get("crop_base64") if isinstance(region, dict) else None
            if crop_data and images_added < max_images:
                try:
                    mime_type, image_bytes = _decode_data_url(crop_data)
                    image_format = _image_format_from_mime(mime_type)
                    content.append(
                        f"Annotation {index} crop image (mime={mime_type}, id={ann_id})"
                    )
                    content.append(Image(data=image_bytes, format=image_format))
                    images_added += 1
                except ValueError as exc:
                    content.append(
                        f"Annotation {index} crop decode failed: {exc} (id={ann_id})"
                    )

        if len(pending) > 0 and images_added == 0:
            content.append(
                "No decodable raster crop images were attached to pending annotations."
            )
        if len(pending) > max_images:
            content.append(
                f"Only the first {max_images} crop images were attached (limit reached)."
            )

        return content

    @mcp.tool(
        name="get_plot_context",
        description=(
            "Return current session context: script source, plot path/type, annotations, "
            "and revision history."
        ),
    )
    def get_plot_context() -> dict:
        session = client.get("/api/session")
        python_interpreter: dict[str, Any]
        try:
            python_interpreter = client.get("/api/python/interpreter")
        except BackendError as exc:
            python_interpreter = {"error": str(exc)}

        return {
            "session_id": session.get("id"),
            "source_script": session.get("source_script"),
            "source_script_path": session.get("source_script_path"),
            "current_plot": session.get("current_plot"),
            "plot_type": session.get("plot_type"),
            "annotations": session.get("annotations", []),
            "versions": session.get("versions", []),
            "branches": session.get("branches", []),
            "root_version_id": session.get("root_version_id"),
            "active_branch_id": session.get("active_branch_id"),
            "checked_out_version_id": session.get("checked_out_version_id"),
            "artifacts_root": session.get("artifacts_root"),
            "revision_history": session.get("revision_history", []),
            "python_interpreter": python_interpreter,
        }

    @mcp.tool(
        name="submit_updated_script",
        description=(
            "Submit an updated Python plotting script to OpenPlot. "
            "OpenPlot executes it, updates the rendered plot, and marks one feedback annotation addressed. "
            "Use annotation_id to target a specific pending annotation when needed."
        ),
    )
    def submit_updated_script(code: str, annotation_id: str | None = None) -> dict:
        if not code.strip():
            raise ValueError("`code` must not be empty.")
        payload: dict[str, Any] = {"code": code}
        if annotation_id:
            payload["annotation_id"] = annotation_id
        return client.post("/api/script", payload)

    return mcp


def run_mcp_stdio(server_url: str) -> None:
    """Run the MCP server over stdio transport."""
    mcp = create_mcp_server(server_url)
    mcp.run(transport="stdio")
