from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

import openplot.server as server
from openplot.services import runners as runner_services
from openplot.services.runtime import build_test_runtime, get_shared_runtime


def _init_workspace(project_dir: Path) -> None:
    server.set_workspace_dir(project_dir)


def _make_manual_wrapper(path: Path) -> Path:
    wrapper = path / "manual-python"
    wrapper.write_text(f'#!/bin/sh\n"{Path(sys.executable).resolve()}" "$@"\n')
    wrapper.chmod(0o755)
    return wrapper


def test_set_workspace_dir_returns_resolved_path_and_updates_shared_workspace(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "nested" / "project"
    project_dir.mkdir(parents=True)

    previous = server._workspace_dir
    try:
        resolved = server.set_workspace_dir(project_dir / ".." / "project")
        assert resolved == project_dir.resolve()
        assert server._workspace_dir == project_dir.resolve()
    finally:
        server._workspace_dir = previous


def test_python_interpreter_defaults_to_built_in_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    _init_workspace(project_dir)

    with TestClient(server.create_app()) as client:
        response = client.get("/api/python/interpreter")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "builtin"
    assert payload["configured_path"] is None
    assert payload["resolved_path"]
    assert payload["resolved_source"] == "built-in"
    assert payload["default_path"] == payload["resolved_path"]
    assert payload["default_version"] == payload["resolved_version"]
    assert isinstance(payload["default_available_packages"], list)
    assert payload["default_available_package_count"] == len(
        payload["default_available_packages"]
    )
    assert payload["available_packages"] == payload["default_available_packages"]
    assert isinstance(payload["available_packages"], list)
    assert payload["available_package_count"] == len(payload["available_packages"])
    assert "state/openplot" in payload["state_root"]


def test_python_interpreter_manual_preference_roundtrip(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    _init_workspace(project_dir)

    manual_wrapper_path = str(_make_manual_wrapper(project_dir))

    with TestClient(server.create_app()) as client:
        initial_payload = client.get("/api/python/interpreter").json()
        default_path = initial_payload["default_path"]
        default_version = initial_payload["default_version"]
        default_packages = initial_payload["default_available_packages"]

        set_manual = client.post(
            "/api/python/interpreter",
            json={"mode": "manual", "path": manual_wrapper_path},
        )
        assert set_manual.status_code == 200
        manual_payload = set_manual.json()
        assert manual_payload["mode"] == "manual"
        assert manual_payload["configured_path"] == manual_wrapper_path
        assert manual_payload["resolved_path"] == manual_wrapper_path
        assert manual_payload["resolved_source"] == "manual"
        assert manual_payload["default_path"] == default_path
        assert manual_payload["default_version"] == default_version
        assert manual_payload["default_available_packages"] == default_packages
        assert manual_payload["default_available_package_count"] == len(
            default_packages
        )

        set_builtin = client.post("/api/python/interpreter", json={"mode": "builtin"})
        assert set_builtin.status_code == 200
        builtin_payload = set_builtin.json()
        assert builtin_payload["mode"] == "builtin"
        assert builtin_payload["configured_path"] is None
        assert builtin_payload["resolved_source"] == "built-in"
        assert builtin_payload["default_path"] == default_path
        assert builtin_payload["resolved_path"] == default_path
        assert builtin_payload["default_available_packages"] == default_packages
        assert builtin_payload["available_packages"] == default_packages

        invalid_path = project_dir / "missing-python"
        invalid_manual = client.post(
            "/api/python/interpreter",
            json={"mode": "manual", "path": str(invalid_path)},
        )
        assert invalid_manual.status_code == 400
        assert "not found" in invalid_manual.text.lower()


def test_python_interpreter_honors_data_and_state_overrides(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "runtime-state"
    data_root = tmp_path / "runtime-data"
    monkeypatch.setenv("OPENPLOT_STATE_DIR", str(state_root))
    monkeypatch.setenv("OPENPLOT_DATA_DIR", str(data_root))

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    _init_workspace(project_dir)

    with TestClient(server.create_app()) as client:
        response = client.get("/api/python/interpreter")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state_root"] == str(state_root.resolve())
    assert payload["data_root"] == str(data_root.resolve())


def test_python_probe_supports_packaged_app_launcher(
    monkeypatch,
    tmp_path: Path,
) -> None:
    launcher_path = tmp_path / "OpenPlot.app" / "Contents" / "MacOS" / "OpenPlot"
    launcher_path.parent.mkdir(parents=True)
    launcher_path.write_text("#!/bin/sh\nexit 0\n")
    launcher_path.chmod(0o755)

    monkeypatch.setattr(server.sys, "executable", str(launcher_path.resolve()))

    version, error = server._probe_python_interpreter(launcher_path)
    assert error is None
    assert version == sys.version.split()[0]

    packages, package_error = server._probe_python_packages(launcher_path)
    assert package_error is None
    assert isinstance(packages, list)


def test_python_interpreter_endpoint_uses_injected_runtime_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    runtime = build_test_runtime(store_root=tmp_path / "isolated-state")
    shared_runtime = get_shared_runtime()

    script_path = tmp_path / "workspace" / "plot.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1], [1])\n"
        "plt.savefig('plot.png')\n"
    )
    assert server.init_session_from_script(script_path, runtime=runtime).success
    shared_runtime.store.active_session = None
    shared_runtime.store.active_session_id = None

    with TestClient(server.create_app(runtime=runtime)) as client:
        response = client.get("/api/python/interpreter")

    assert response.status_code == 200
    assert response.json()["context_dir"] == str(script_path.parent.resolve())


def test_python_interpreter_invalid_mode_error_lists_auto() -> None:
    runtime = build_test_runtime()
    body = type("InvalidInterpreterRequest", (), {"mode": "invalid", "path": None})()

    with pytest.raises(server.HTTPException) as exc_info:
        asyncio.run(runner_services.set_python_interpreter(cast(Any, body), runtime))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Mode must be 'builtin', 'manual', or 'auto'"


def test_python_interpreter_service_uses_injected_runtime_store_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENPLOT_STATE_DIR", str(tmp_path / "shared-state"))
    runtime = build_test_runtime(store_root=tmp_path / "isolated-state")
    assert runtime.state_root is not None
    runtime_state_root = runtime.state_root.resolve()
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    manual_wrapper = _make_manual_wrapper(project_dir)

    server._with_runtime(runtime, lambda: server.set_workspace_dir(project_dir))

    set_payload = asyncio.run(
        runner_services.set_python_interpreter(
            cast(
                Any,
                type(
                    "ManualInterpreterRequest",
                    (),
                    {"mode": "manual", "path": str(manual_wrapper)},
                )(),
            ),
            runtime,
        )
    )
    get_payload = asyncio.run(runner_services.get_python_interpreter(runtime))

    runtime_preferences = runtime_state_root / "preferences.json"
    shared_preferences = (tmp_path / "shared-state" / "preferences.json").resolve()

    assert set_payload["mode"] == "manual"
    assert set_payload["configured_path"] == str(manual_wrapper)
    assert set_payload["state_root"] == str(runtime_state_root)
    assert get_payload["mode"] == "manual"
    assert get_payload["configured_path"] == str(manual_wrapper)
    assert get_payload["state_root"] == str(runtime_state_root)
    assert runtime_preferences.exists()
    assert json.loads(runtime_preferences.read_text())["python_interpreter"] == str(
        manual_wrapper
    )
    assert not shared_preferences.exists()
