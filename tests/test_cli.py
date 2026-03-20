from __future__ import annotations

from pathlib import Path

import click
import pytest

from openplot import cli as cli_module
from openplot import desktop as desktop_module
import openplot.server as server


@pytest.fixture(autouse=True)
def _reset_server_state():
    prev_session = server._session
    prev_sessions = dict(server._sessions)
    prev_session_order = list(server._session_order)
    prev_active_session_id = server._active_session_id
    prev_plot_mode = server._plot_mode
    prev_workspace = server._workspace_dir
    prev_loaded_store_root = server._loaded_session_store_root

    server._session = None
    server._sessions.clear()
    server._session_order.clear()
    server._active_session_id = None
    server._plot_mode = None
    server._loaded_session_store_root = None

    try:
        yield
    finally:
        server._session = prev_session
        server._sessions.clear()
        server._sessions.update(prev_sessions)
        server._session_order.clear()
        server._session_order.extend(prev_session_order)
        server._active_session_id = prev_active_session_id
        server._plot_mode = prev_plot_mode
        server._workspace_dir = prev_workspace
        server._loaded_session_store_root = prev_loaded_store_root


def test_serve_without_file_preserves_existing_plot_mode_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    state = server.init_plot_mode_session(
        workspace_dir=workspace, persist_workspace=True
    )
    preview_plot = workspace / "captures" / "preview.png"
    preview_plot.parent.mkdir(parents=True, exist_ok=True)
    preview_plot.write_bytes(b"preview")

    state.current_script = "print('preview')\n"
    state.current_plot = str(preview_plot)
    state.plot_type = "raster"
    server._touch_plot_mode(state)

    active_snapshot_path = tmp_path / "state" / "openplot" / "plot-mode" / "active.json"
    workspace_snapshot_path = (
        tmp_path / "state" / "openplot" / "plot-mode" / state.id / "workspace.json"
    )
    assert active_snapshot_path.exists()
    assert workspace_snapshot_path.exists()

    monkeypatch.setattr(cli_module.uvicorn, "run", lambda *_args, **_kwargs: None)

    serve_callback = cli_module.serve.callback
    assert serve_callback is not None

    serve_callback(
        file=None,
        port=0,
        host="127.0.0.1",
        no_browser=True,
    )

    assert active_snapshot_path.exists()
    assert workspace_snapshot_path.exists()

    restored = server._load_plot_mode_snapshot()
    assert restored is not None
    assert restored.id == state.id
    assert restored.current_plot == str(preview_plot)


def test_serve_rejects_non_python_file(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "plot.png"
    image_path.write_bytes(b"png")

    serve_callback = cli_module.serve.callback
    assert serve_callback is not None

    def _unexpected_run(*_args, **_kwargs):
        raise AssertionError("serve should reject non-Python files before startup")

    monkeypatch.setattr(cli_module.uvicorn, "run", _unexpected_run)

    with pytest.raises(SystemExit) as exc_info:
        serve_callback(
            file=str(image_path),
            port=0,
            host="127.0.0.1",
            no_browser=True,
        )

    assert exc_info.value.code == 1


def test_desktop_rejects_non_python_file_before_loading_webview(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "plot.png"
    image_path.write_bytes(b"png")

    def _unexpected_import(name: str):
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(desktop_module.importlib, "import_module", _unexpected_import)

    with pytest.raises(click.ClickException, match="Python script"):
        desktop_module.launch_desktop(str(image_path))


def test_serve_and_desktop_commands_do_not_expose_no_exec_option() -> None:
    serve_param_names = {param.name for param in cli_module.serve.params}
    cli_desktop_param_names = {param.name for param in cli_module.desktop.params}
    desktop_param_names = {param.name for param in desktop_module.main.params}

    assert "no_exec" not in serve_param_names
    assert "no_exec" not in cli_desktop_param_names
    assert "no_exec" not in desktop_param_names
