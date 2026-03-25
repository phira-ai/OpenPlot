from __future__ import annotations

from pathlib import Path
import ssl
import tempfile

import click
import pytest
from fastapi.testclient import TestClient

from openplot import cli as cli_module
from openplot import desktop as desktop_module
import openplot.mcp_server as mcp_server
import openplot.server as server


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


def test_create_app_zero_arg_bootstrap_uses_shared_plot_mode_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    state = server.init_plot_mode_session(
        workspace_dir=workspace,
        persist_workspace=True,
    )
    server._touch_plot_mode(state)

    with TestClient(server.create_app()) as client:
        response = client.get("/api/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "plot"
    assert payload["plot_mode"]["id"] == state.id
    assert payload["active_workspace_id"] == state.id


def test_init_session_from_script_initializes_shared_runtime_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "workspace" / "plot.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1, 2, 3], [2, 1, 3])\n"
        "plt.savefig('plot.png')\n",
    )

    result = server.init_session_from_script(script_path)

    assert result.success
    assert server.get_session().source_script_path == str(script_path.resolve())
    assert server._workspace_dir == script_path.parent.resolve()

    with TestClient(server.create_app()) as client:
        response = client.get("/api/session")

    assert response.status_code == 200
    assert response.json()["source_script_path"] == str(script_path.resolve())


def test_serve_and_desktop_commands_do_not_expose_no_exec_option() -> None:
    serve_param_names = {param.name for param in cli_module.serve.params}
    cli_desktop_param_names = {param.name for param in cli_module.desktop.params}
    desktop_param_names = {param.name for param in desktop_module.main.params}

    assert "no_exec" not in serve_param_names
    assert "no_exec" not in cli_desktop_param_names
    assert "no_exec" not in desktop_param_names


def test_cli_no_file_startup_uses_cwd(monkeypatch, tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    calls: list[Path] = []

    monkeypatch.setattr(cli_module.Path, "cwd", staticmethod(lambda: cwd))
    monkeypatch.setattr(
        cli_module,
        "set_runtime_workspace_dir",
        lambda _runtime, path: calls.append(Path(path)),
    )
    monkeypatch.setattr(cli_module, "write_runtime_port_file", lambda *_args: None)
    monkeypatch.setattr(server, "create_app", lambda: object())
    monkeypatch.setattr(cli_module.uvicorn, "run", lambda *_args, **_kwargs: None)

    serve_callback = cli_module.serve.callback
    assert serve_callback is not None

    serve_callback(file=None, port=0, host="127.0.0.1", no_browser=True)

    assert calls == [cwd]


def test_legacy_write_port_file_remains_a_working_compatibility_entry_point(
    monkeypatch,
    tmp_path: Path,
) -> None:
    port_file = tmp_path / ".openplot" / "port"
    monkeypatch.setattr(server, "_port_file", port_file)

    server.write_port_file(17623)

    assert port_file.read_text(encoding="utf-8") == "17623"


def test_create_app_lifespan_removes_shared_port_file_written_by_compat_entry_point(
    monkeypatch,
) -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="openplot-port-file-"))
    port_file = temp_root / ".openplot" / "port"
    monkeypatch.setattr(server, "_port_file", port_file)

    server.write_port_file(17623)
    assert port_file.exists()

    with TestClient(server.create_app()):
        assert port_file.exists()

    assert not port_file.exists()


def test_shared_runtime_lifespan_clears_module_session_globals(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    script_path = tmp_path / "workspace" / "plot.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1], [1])\n"
        "plt.savefig('plot.png')\n"
    )

    result = server.init_session_from_script(script_path)
    assert result.success
    assert server._session is not None
    assert server._active_session_id is not None
    assert server._loaded_session_store_root is not None

    with TestClient(server.create_app()):
        pass

    assert server._session is None
    assert server._active_session_id is None
    assert server._loaded_session_store_root is None


def _sample_update_status(*, update_available: bool = True) -> dict[str, object]:
    return {
        "current_version": "1.1.0",
        "latest_version": "1.2.0" if update_available else "1.1.0",
        "latest_release_url": "https://github.com/phira-ai/OpenPlot/releases/latest",
        "update_available": update_available,
        "checked_at": "2026-03-22T20:00:00Z",
        "error": None,
    }


def test_bootstrap_payload_includes_update_status(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_build_update_status_payload",
        lambda **_kwargs: _sample_update_status(),
    )

    payload = server._bootstrap_payload(mode="plot", session=None, plot_mode=None)

    assert payload["update_status"] == _sample_update_status()


def test_update_status_refresh_endpoint_returns_shared_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "build_update_status_payload",
        lambda *_args, **_kwargs: _sample_update_status(),
    )

    with TestClient(server.create_app()) as client:
        response = client.post("/api/update-status/refresh")

    assert response.status_code == 200
    assert response.json() == _sample_update_status()


def test_update_status_refresh_uses_injected_runtime_cache(
    monkeypatch,
    app_with_test_runtime,
    shared_runtime,
    test_runtime,
    tmp_path: Path,
) -> None:
    shared_runtime.infra.update_status_cache = None
    shared_runtime.infra.update_status_cache_expires_at = 0.0
    test_runtime.infra.update_status_cache = None
    test_runtime.infra.update_status_cache_expires_at = 0.0
    monkeypatch.setattr(
        server,
        "_fetch_latest_release_payload",
        lambda: {
            "tag_name": "v9.9.9",
            "draft": False,
            "prerelease": False,
            "html_url": "https://example.com/releases/v9.9.9",
        },
    )

    with TestClient(app_with_test_runtime) as client:
        response = client.post("/api/update-status/refresh")

    assert response.status_code == 200
    assert test_runtime.infra.update_status_cache is not None
    assert shared_runtime.infra.update_status_cache is None


def test_serve_prints_update_notice_when_newer_release_exists(
    monkeypatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        server,
        "_build_update_status_payload",
        lambda **_kwargs: _sample_update_status(),
    )
    monkeypatch.setattr(cli_module.uvicorn, "run", lambda *_args, **_kwargs: None)

    serve_callback = cli_module.serve.callback
    assert serve_callback is not None

    serve_callback(file=None, port=0, host="127.0.0.1", no_browser=True)

    output = capsys.readouterr().out
    assert "Update available: OpenPlot 1.2.0" in output
    assert "https://github.com/phira-ai/OpenPlot/releases/latest" in output


def test_serve_skips_update_notice_when_current_version_is_latest(
    monkeypatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        server,
        "_build_update_status_payload",
        lambda **_kwargs: _sample_update_status(update_available=False),
    )
    monkeypatch.setattr(cli_module.uvicorn, "run", lambda *_args, **_kwargs: None)

    serve_callback = cli_module.serve.callback
    assert serve_callback is not None

    serve_callback(file=None, port=0, host="127.0.0.1", no_browser=True)

    output = capsys.readouterr().out
    assert "Update available:" not in output


def test_mcp_skips_update_notice_to_keep_stdout_clean(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        server,
        "_build_update_status_payload",
        lambda **_kwargs: _sample_update_status(),
    )
    monkeypatch.setattr(
        mcp_server,
        "discover_server_url",
        lambda server_url=None: server_url or "http://127.0.0.1:17623",
    )
    monkeypatch.setattr(mcp_server, "run_mcp_stdio", lambda server_url: None)

    mcp_callback = cli_module.mcp.callback
    assert mcp_callback is not None

    mcp_callback(server_url="http://127.0.0.1:17623")

    captured = capsys.readouterr()
    assert "Update available:" not in captured.out


def test_update_status_uses_curl_fallback_on_ssl_verification_failure(
    monkeypatch,
) -> None:
    release_payload = (
        '{"tag_name":"v1.2.0","html_url":"https://github.com/phira-ai/OpenPlot/releases/tag/v1.2.0"}'
    ).encode("utf-8")

    def raise_ssl_error(*_args, **_kwargs):
        raise server.urllib_error.URLError(
            ssl.SSLCertVerificationError("missing local issuer")
        )

    def fake_run(*_args, **_kwargs):
        class Result:
            returncode = 0
            stdout = release_payload
            stderr = b""

        return Result()

    monkeypatch.setattr(server.urllib_request, "urlopen", raise_ssl_error)
    monkeypatch.setattr(server, "_run_download_subprocess", fake_run)
    monkeypatch.setattr(server, "_update_status_cache", None)
    monkeypatch.setattr(server, "_update_status_cache_expires_at", 0.0)

    payload = server._build_update_status_payload(force_refresh=True)

    assert payload["error"] is None
    assert payload["latest_version"] == "1.2.0"
    assert payload["update_available"] is True


def test_update_status_payload_without_network_preserves_stale_disk_cache(
    monkeypatch,
) -> None:
    stale_payload = {
        "current_version": "1.1.0",
        "latest_version": "1.2.0",
        "latest_release_url": "https://example.com/releases/latest",
        "update_available": True,
        "checked_at": "2026-03-22T20:00:00Z",
        "error": "cached offline",
    }

    monkeypatch.setattr(server, "_update_status_cache", None)
    monkeypatch.setattr(server, "_update_status_cache_expires_at", 0.0)
    monkeypatch.setattr(
        server,
        "_load_update_status_disk_cache",
        lambda *, require_fresh: None if require_fresh else dict(stale_payload),
    )

    payload = server._build_update_status_payload(allow_network=False)

    assert payload == stale_payload
