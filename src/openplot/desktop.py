"""Desktop launcher for OpenPlot."""

from __future__ import annotations

import atexit
import importlib
import json
import os
import socket
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

import click
import uvicorn

DEFAULT_DESKTOP_PORT = 17623
_ALLOWED_SUFFIXES = {".py", ".svg", ".png", ".jpg", ".jpeg", ".pdf"}
_DESKTOP_FILE_DROP_EVENT = "openplot-desktop-file-drop"


def _strip_macos_process_serial_arg() -> None:
    """Remove Finder's process serial argument before Click parses argv."""
    if sys.platform != "darwin":
        return
    if len(sys.argv) < 2:
        return
    if sys.argv[1].startswith("-psn_"):
        del sys.argv[1]


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return int(sock.getsockname()[1])


def _configure_linux_qt_runtime() -> None:
    if not sys.platform.startswith("linux"):
        return

    os.environ.setdefault("PYWEBVIEW_GUI", "qt")
    os.environ.setdefault("QT_API", "pyqt6")
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

    chromium_default = (
        "--disable-gpu --disable-gpu-compositing --disable-features=Vulkan --no-sandbox"
    )
    existing_chromium_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    if existing_chromium_flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
            f"{existing_chromium_flags} {chromium_default}"
        )
    else:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = chromium_default

    appdir = os.environ.get("APPDIR", "").strip()
    if appdir:
        bundled_xkb = Path(appdir) / "usr" / "share" / "X11" / "xkb"
        if bundled_xkb.is_dir():
            os.environ.setdefault("XKB_CONFIG_ROOT", str(bundled_xkb))


def _resolve_input_file(raw_file: str | None) -> Path | None:
    if not raw_file:
        return None

    path = Path(raw_file).expanduser().resolve()

    if not path.exists():
        raise click.ClickException(f"File not found: {path}")

    ext = path.suffix.lower()
    if ext not in _ALLOWED_SUFFIXES:
        supported = ", ".join(sorted(_ALLOWED_SUFFIXES))
        raise click.ClickException(
            f"Unsupported file type '{ext}'. Expected one of: {supported}"
        )
    return path


def _desktop_file_drop_script(paths: list[str]) -> str:
    payload = json.dumps({"paths": paths})
    return (
        "window.dispatchEvent("
        f"new CustomEvent({_DESKTOP_FILE_DROP_EVENT!r}, {{ detail: {payload} }})"
        ");"
    )


def _desktop_dropped_file_paths(event: object) -> list[str]:
    if not isinstance(event, dict):
        return []

    data_transfer = event.get("dataTransfer")
    if not isinstance(data_transfer, dict):
        return []

    raw_files = data_transfer.get("files")
    if not isinstance(raw_files, list):
        return []

    paths: list[str] = []
    seen: set[str] = set()
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        raw_path = item.get("pywebviewFullPath")
        if not isinstance(raw_path, str):
            continue
        normalized = raw_path.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        paths.append(normalized)
    return paths


def _bind_macos_file_drop_bridge(window: object) -> None:
    if sys.platform != "darwin":
        return

    try:
        from webview.dom import DOMEventHandler
    except ImportError:
        return

    document = getattr(getattr(window, "dom", None), "document", None)
    if document is None:
        return

    def _ignore_drag(_event: object) -> None:
        return

    def _on_drop(event: object) -> None:
        paths = _desktop_dropped_file_paths(event)
        if not paths:
            return
        evaluate_js = getattr(window, "evaluate_js", None)
        if not callable(evaluate_js):
            return
        with suppress(Exception):
            evaluate_js(_desktop_file_drop_script(paths))

    document.events.dragenter += DOMEventHandler(_ignore_drag, True, True)
    document.events.dragover += DOMEventHandler(_ignore_drag, True, True, debounce=500)
    document.events.drop += DOMEventHandler(_on_drop, True, True)


def _restore_stdio_for_windowed_app() -> None:
    """Restore sys.stdin/stdout/stderr from OS handles.

    PyInstaller windowed apps (console=False) set these to None, but when a
    parent process spawns us with pipes the OS-level handles are valid.
    Re-wrapping them lets stdio-based transports (MCP, click.echo) work.
    """
    if sys.platform == "win32":
        _restore_stdio_win32()
    else:
        _restore_stdio_posix()


def _restore_stdio_posix() -> None:
    for fd, mode, attr in ((0, "r", "stdin"), (1, "w", "stdout"), (2, "w", "stderr")):
        if getattr(sys, attr) is None:
            try:
                setattr(sys, attr, os.fdopen(fd, mode, closefd=False))
            except OSError:
                pass


def _restore_stdio_win32() -> None:
    """Restore stdio on Windows using the Win32 standard handles.

    In a GUI-subsystem process (console=False) the C-runtime file descriptors
    0/1/2 may not be mapped, but the Win32 standard handles that the parent
    provided via STARTUPINFO *are* present.  We use GetStdHandle -> msvcrt
    open_osfhandle -> os.fdopen to reconnect them.
    """
    try:
        import ctypes
        import msvcrt
    except ImportError:
        return

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    STD_HANDLES = (
        (-10, 0, "r", "stdin"),  # STD_INPUT_HANDLE
        (-11, 1, "w", "stdout"),  # STD_OUTPUT_HANDLE
        (-12, 2, "w", "stderr"),  # STD_ERROR_HANDLE
    )

    for std_id, fallback_fd, mode, attr in STD_HANDLES:
        if getattr(sys, attr) is not None:
            continue

        handle = kernel32.GetStdHandle(std_id)
        if handle in (0, INVALID_HANDLE_VALUE, None):
            continue

        try:
            fd = msvcrt.open_osfhandle(handle, 0)
        except OSError:
            fd = fallback_fd

        try:
            setattr(sys, attr, os.fdopen(fd, mode, closefd=False))
        except OSError:
            pass


def _run_internal_script_execution(
    *,
    script_path: str,
    work_dir: str | None,
    capture_dir: str | None,
) -> int:
    from openplot.executor import execute_script_inline

    _restore_stdio_for_windowed_app()

    result = execute_script_inline(
        script_path,
        work_dir=work_dir,
        capture_dir=capture_dir,
    )
    click.echo(
        json.dumps(
            {
                "type": "openplot_internal_script_result",
                "success": result.success,
                "plot_path": result.plot_path,
                "plot_type": result.plot_type,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "duration_s": result.duration_s,
                "error": result.error,
            }
        )
    )

    if result.returncode != 0:
        return result.returncode
    return 0


def _run_internal_mcp_stdio(server_url: str | None) -> int:
    from openplot.mcp_server import BackendError, discover_server_url, run_mcp_stdio

    _restore_stdio_for_windowed_app()

    try:
        resolved_url = discover_server_url(server_url)
    except BackendError as exc:
        click.echo(f"Error: {exc}", err=True)
        return 1

    run_mcp_stdio(resolved_url)
    return 0


def launch_desktop(
    file: str | None,
    *,
    host: str = "127.0.0.1",
    port: int = DEFAULT_DESKTOP_PORT,
) -> None:
    """Launch OpenPlot in a native webview window."""
    file_path = _resolve_input_file(file)
    if file_path is not None and file_path.suffix.lower() != ".py":
        raise click.ClickException(
            f"OpenPlot desktop only accepts Python scripts (.py), got: {file_path.name}"
        )

    _configure_linux_qt_runtime()

    try:
        webview = importlib.import_module("webview")
    except ModuleNotFoundError as exc:
        raise click.ClickException(
            "Desktop mode requires 'pywebview'. Install with: uv sync --extra desktop"
        ) from exc

    from openplot.server import (
        create_app,
        init_session_from_script,
        set_workspace_dir,
        write_port_file,
    )

    if file_path is None:
        set_workspace_dir(Path.home())
    else:
        set_workspace_dir(file_path.parent)

        click.echo(f"Executing {file_path.name} ...")
        result = init_session_from_script(file_path)
        if not result.success:
            details = result.error or "Failed to execute script"
            if result.stderr:
                details = f"{details}\n{result.stderr.strip()}"
            raise click.ClickException(details)

    if port == 0:
        port = _pick_free_port()

    write_port_file(port)
    url = f"http://{host}:{port}"

    app = create_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    uvicorn_server = uvicorn.Server(config)
    server_thread = threading.Thread(
        target=uvicorn_server.run,
        name="openplot-uvicorn",
        daemon=True,
    )
    server_thread.start()

    started_deadline = time.monotonic() + 15.0
    while not uvicorn_server.started and server_thread.is_alive():
        if time.monotonic() >= started_deadline:
            break
        time.sleep(0.05)

    shutdown_once = threading.Event()

    def _shutdown_server() -> None:
        if shutdown_once.is_set():
            return
        shutdown_once.set()
        uvicorn_server.should_exit = True
        server_thread.join(timeout=8.0)

    if not uvicorn_server.started:
        _shutdown_server()
        raise click.ClickException("Failed to start local OpenPlot backend")

    click.echo(f"OpenPlot desktop running at {url}")

    atexit.register(_shutdown_server)

    window = webview.create_window(
        "OpenPlot",
        url=url,
        width=1440,
        height=920,
        min_size=(980, 700),
        zoomable=True,
    )
    window.events.closed += _shutdown_server

    try:
        webview.start(_bind_macos_file_drop_bridge, window, debug=False)
    finally:
        _shutdown_server()
        with suppress(Exception):
            atexit.unregister(_shutdown_server)


@click.command()
@click.argument("file", required=False)
@click.option(
    "--port",
    "-p",
    default=DEFAULT_DESKTOP_PORT,
    help=(f"Port to serve on (default: {DEFAULT_DESKTOP_PORT}; use 0 to auto-pick)."),
)
@click.option("--host", "-h", default="127.0.0.1", help="Host to bind to.")
@click.option(
    "--internal-execute-script",
    "internal_execute_script",
    type=click.Path(path_type=str),
    hidden=True,
)
@click.option(
    "--internal-work-dir",
    "internal_work_dir",
    type=click.Path(path_type=str),
    hidden=True,
)
@click.option(
    "--internal-capture-dir",
    "internal_capture_dir",
    type=click.Path(path_type=str),
    hidden=True,
)
@click.option(
    "--internal-run-mcp",
    "internal_run_mcp",
    is_flag=True,
    hidden=True,
)
@click.option(
    "--internal-mcp-server-url",
    "internal_mcp_server_url",
    type=str,
    hidden=True,
)
def main(
    file: str | None,
    port: int,
    host: str,
    internal_execute_script: str | None,
    internal_work_dir: str | None,
    internal_capture_dir: str | None,
    internal_run_mcp: bool,
    internal_mcp_server_url: str | None,
) -> None:
    """Launch OpenPlot in a native desktop window."""
    if internal_execute_script is not None:
        raise SystemExit(
            _run_internal_script_execution(
                script_path=internal_execute_script,
                work_dir=internal_work_dir,
                capture_dir=internal_capture_dir,
            )
        )

    if internal_run_mcp:
        raise SystemExit(_run_internal_mcp_stdio(internal_mcp_server_url))

    launch_desktop(file, host=host, port=port)


if __name__ == "__main__":
    _strip_macos_process_serial_arg()
    main()
