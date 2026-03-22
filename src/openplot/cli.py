"""CLI entry point for OpenPlot."""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import click
import uvicorn

from . import __version__

DEFAULT_SERVE_PORT = 17623


def _show_update_notice() -> None:
    try:
        from .server import _build_update_status_payload

        payload = _build_update_status_payload(allow_network=True)
    except Exception:
        return

    if payload.get("update_available") is not True:
        return

    latest_version = str(payload.get("latest_version") or "").strip()
    if not latest_version:
        return

    latest_release_url = str(payload.get("latest_release_url") or "").strip()
    if not latest_release_url:
        return

    click.echo(
        f"Update available: OpenPlot {latest_version} (current {__version__}) - {latest_release_url}"
    )


@click.group()
@click.version_option(package_name="openplot")
def main() -> None:
    """The agentic plotting "IDE" built for everyone."""


@main.command()
@click.argument("file", required=False)
@click.option(
    "--port",
    "-p",
    default=DEFAULT_SERVE_PORT,
    help=(f"Port to serve on (default: {DEFAULT_SERVE_PORT}; use 0 to auto-pick)."),
)
@click.option("--host", "-h", default="127.0.0.1", help="Host to bind to.")
@click.option("--no-browser", is_flag=True, help="Don't auto-open the browser.")
def serve(file: str | None, port: int, host: str, no_browser: bool) -> None:
    """Start the OpenPlot server for FILE or by restoring a workspace.

    FILE can be a Python script (.py).
    If FILE is omitted, OpenPlot restores the most recently updated workspace.
    If no workspace exists, OpenPlot starts in plot mode.
    """
    _show_update_notice()

    from .server import (
        create_app,
        init_session_from_script,
        set_workspace_dir,
        write_port_file,
    )

    if file is not None:
        file_path = Path(file).expanduser().resolve()
        if not file_path.exists():
            click.secho(f"Error: File not found: {file_path}", fg="red")
            sys.exit(1)

        ext = file_path.suffix.lower()
        if ext != ".py":
            click.secho(
                f"Error: OpenPlot serve only accepts Python scripts (.py), got: {file_path.name}",
                fg="red",
            )
            sys.exit(1)

        click.echo(f"Executing {file_path.name} ...")
        result = init_session_from_script(file_path)
        if not result.success:
            click.secho(f"Error: {result.error}", fg="red")
            if result.stderr:
                click.echo(result.stderr)
            sys.exit(1)
        click.echo(f"Detected output: {result.plot_path} ({result.plot_type})")
    else:
        set_workspace_dir(Path.cwd())
        click.echo(
            "Starting OpenPlot. The web UI will restore the most recently updated workspace or start a new plot workspace."
        )

    # Pick a free port if 0.
    if port == 0:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

    write_port_file(port)

    url = f"http://{host}:{port}"
    click.echo(f"OpenPlot server running at {url}")

    if not no_browser:
        # Delay browser open slightly so the server is ready.
        import threading

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="warning")


@main.command()
@click.argument("file", required=False)
@click.option(
    "--port",
    "-p",
    default=DEFAULT_SERVE_PORT,
    help=(f"Port to serve on (default: {DEFAULT_SERVE_PORT}; use 0 to auto-pick)."),
)
@click.option("--host", "-h", default="127.0.0.1", help="Host to bind to.")
def desktop(file: str | None, port: int, host: str) -> None:
    """Launch OpenPlot in a native desktop window."""
    _show_update_notice()

    from .desktop import launch_desktop

    launch_desktop(file, host=host, port=port)


@main.command()
@click.option(
    "--server-url",
    default=None,
    help=(
        "OpenPlot backend URL to proxy (default: auto-discover from "
        "OPENPLOT_SERVER_URL or ~/.openplot/port)."
    ),
)
def mcp(server_url: str | None) -> None:
    """Launch the MCP stdio server (for agent integration).

    This connects to a running OpenPlot server to proxy tool calls.
    """
    from .mcp_server import BackendError, discover_server_url, run_mcp_stdio

    try:
        resolved_url = discover_server_url(server_url)
    except BackendError as exc:
        click.secho(f"Error: {exc}", fg="red", err=True)
        sys.exit(1)

    click.echo(f"Starting OpenPlot MCP server (backend: {resolved_url})", err=True)
    run_mcp_stdio(resolved_url)


if __name__ == "__main__":
    main()
