from __future__ import annotations

import asyncio
import re
import time
from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.routing import APIWebSocketRoute
from fastapi.testclient import TestClient

import openplot.api.runners as runners_api
import openplot.api.runtime as runtime_api
import openplot.api.sessions as sessions_api
import openplot.api.preferences as preferences_api
import openplot.server as server
from openplot.models import AnnotationStatus, OpencodeModelOption
from openplot.api.schemas import PreferencesRequest, PythonInterpreterRequest
from openplot.services import sessions as session_services
from openplot.services.runtime import (
    BackendRuntime,
    build_test_runtime,
    build_update_status_payload,
    get_shared_runtime,
)


def test_create_app_registers_router_modules() -> None:
    app = server.create_app()
    expected = {
        ("GET", "/api/bootstrap"): "openplot.api.sessions",
        ("GET", "/api/session"): "openplot.api.sessions",
        ("GET", "/api/sessions"): "openplot.api.sessions",
        ("POST", "/api/sessions/new"): "openplot.api.sessions",
        ("POST", "/api/sessions/{session_id}/activate"): "openplot.api.sessions",
        ("PATCH", "/api/sessions/{session_id}"): "openplot.api.sessions",
        ("DELETE", "/api/sessions/{session_id}"): "openplot.api.sessions",
        ("GET", "/api/plot-mode"): "openplot.api.plot_mode",
        ("POST", "/api/plot-mode/files"): "openplot.api.plot_mode",
        ("POST", "/api/plot-mode/path-suggestions"): "openplot.api.plot_mode",
        ("POST", "/api/plot-mode/select-paths"): "openplot.api.plot_mode",
        ("PATCH", "/api/plot-mode/settings"): "openplot.api.plot_mode",
        ("POST", "/api/plot-mode/tabular-hint"): "openplot.api.plot_mode",
        ("POST", "/api/plot-mode/answer"): "openplot.api.plot_mode",
        ("POST", "/api/plot-mode/chat"): "openplot.api.plot_mode",
        ("POST", "/api/plot-mode/finalize"): "openplot.api.plot_mode",
        ("PATCH", "/api/plot-mode/workspace"): "openplot.api.plot_mode",
        ("DELETE", "/api/plot-mode"): "openplot.api.plot_mode",
        ("POST", "/api/plot-mode/activate"): "openplot.api.plot_mode",
        ("POST", "/api/annotations"): "openplot.api.annotations",
        ("GET", "/api/annotations/{annotation_id}/export"): "openplot.api.annotations",
        ("DELETE", "/api/annotations/{annotation_id}"): "openplot.api.annotations",
        ("PATCH", "/api/annotations/{annotation_id}"): "openplot.api.annotations",
        ("GET", "/api/fix-jobs"): "openplot.api.fix_jobs",
        ("GET", "/api/fix-jobs/current"): "openplot.api.fix_jobs",
        ("POST", "/api/fix-jobs"): "openplot.api.fix_jobs",
        ("POST", "/api/fix-jobs/{job_id}/cancel"): "openplot.api.fix_jobs",
        ("GET", "/api/runners"): "openplot.api.runners",
        ("GET", "/api/runners/status"): "openplot.api.runners",
        ("POST", "/api/runners/install"): "openplot.api.runners",
        ("POST", "/api/runners/auth/launch"): "openplot.api.runners",
        ("GET", "/api/runners/models"): "openplot.api.runners",
        ("GET", "/api/opencode/models"): "openplot.api.runners",
        ("GET", "/api/preferences"): "openplot.api.preferences",
        ("POST", "/api/preferences"): "openplot.api.preferences",
        ("GET", "/api/plot"): "openplot.api.artifacts",
        ("GET", "/api/plot-mode/export"): "openplot.api.artifacts",
        ("GET", "/api/feedback"): "openplot.api.artifacts",
        ("POST", "/api/script"): "openplot.api.versioning",
        ("POST", "/api/checkout"): "openplot.api.versioning",
        ("GET", "/api/revisions"): "openplot.api.versioning",
        ("POST", "/api/branches/{branch_id}/checkout"): "openplot.api.versioning",
        ("PATCH", "/api/branches/{branch_id}"): "openplot.api.versioning",
        ("POST", "/api/open-external-url"): "openplot.api.runtime",
        ("POST", "/api/update-status/refresh"): "openplot.api.runtime",
        ("GET", "/api/python/interpreter"): "openplot.api.runtime",
        ("POST", "/api/python/interpreter"): "openplot.api.runtime",
        ("WS", "/ws"): "openplot.api.ws",
    }
    actual: dict[tuple[str, str], str] = {}

    for route in app.routes:
        if isinstance(route, APIWebSocketRoute):
            key = ("WS", route.path)
            if route.path == "/ws":
                actual[key] = getattr(cast(Any, route), "endpoint").__module__
            continue

        route_with_endpoint = cast(Any, route)
        methods = getattr(route, "methods", None) or set()
        for method in methods:
            key = (method, getattr(route, "path", ""))
            if getattr(route, "path", "").startswith("/api/"):
                actual[key] = getattr(route_with_endpoint, "endpoint").__module__

    assert actual == expected


def test_preferences_router_delegates_to_runner_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(preferences_api.router)

    calls: list[str] = []

    async def fake_get_preferences() -> dict[str, object]:
        calls.append("get")
        return {
            "fix_runner": "opencode",
            "fix_model": "openai/gpt-5.3-codex",
            "fix_variant": "high",
        }

    monkeypatch.setattr(
        preferences_api.runner_services, "get_preferences", fake_get_preferences
    )

    with TestClient(app) as client:
        response = client.get("/api/preferences")

    assert response.status_code == 200
    assert response.json() == {
        "fix_runner": "opencode",
        "fix_model": "openai/gpt-5.3-codex",
        "fix_variant": "high",
    }
    assert calls == ["get"]


def _request_with_runtime(runtime: object) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=runtime)))


def test_preferences_router_passes_body_through_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = PreferencesRequest(
        fix_runner="opencode",
        fix_model="openai/gpt-5.3-codex",
        fix_variant="high",
    )
    calls: list[object] = []

    async def fake_set_preferences(received_body: object) -> dict[str, object]:
        calls.append(received_body)
        return {"status": "ok"}

    monkeypatch.setattr(
        preferences_api.runner_services,
        "set_preferences",
        fake_set_preferences,
    )

    response = asyncio.run(preferences_api.set_preferences(body))

    assert response == {"status": "ok"}
    assert calls == [body]


def test_sessions_router_passes_runtime_through_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = object()
    request = _request_with_runtime(runtime)
    calls: list[object] = []

    def fake_build_bootstrap_payload(received_runtime: object) -> dict[str, object]:
        calls.append(received_runtime)
        return {"status": "ok"}

    monkeypatch.setattr(
        sessions_api.session_services,
        "build_bootstrap_payload",
        fake_build_bootstrap_payload,
    )

    response = asyncio.run(sessions_api.get_bootstrap_state(cast(Any, request)))

    assert response == {"status": "ok"}
    assert calls == [runtime]


def test_sessions_router_passes_runtime_body_and_path_args_through_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = object()
    request = _request_with_runtime(runtime)
    body = sessions_api.RenameSessionRequest(name="Renamed workspace")
    calls: list[tuple[object, object, object]] = []

    def fake_rename_session(
        received_runtime: object,
        received_session_id: object,
        received_body: object,
    ) -> dict[str, object]:
        calls.append((received_runtime, received_session_id, received_body))
        return {"status": "ok"}

    monkeypatch.setattr(
        sessions_api.session_services,
        "rename_session",
        fake_rename_session,
    )

    response = asyncio.run(
        sessions_api.rename_session("session-123", body, cast(Any, request))
    )

    assert response == {"status": "ok"}
    assert calls == [(runtime, "session-123", body)]


def test_runtime_router_passes_runtime_and_session_id_through_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = object()
    request = _request_with_runtime(runtime)
    calls: list[tuple[object, str | None]] = []

    async def fake_get_python_interpreter(
        received_runtime: object,
        *,
        session_id: str | None = None,
    ) -> dict[str, object]:
        calls.append((received_runtime, session_id))
        return {"mode": "builtin"}

    monkeypatch.setattr(
        runtime_api.runner_services,
        "get_python_interpreter",
        fake_get_python_interpreter,
    )

    response = asyncio.run(
        runtime_api.get_python_interpreter(cast(Any, request), session_id="session-123")
    )

    assert response == {"mode": "builtin"}
    assert calls == [(runtime, "session-123")]


def test_runtime_router_passes_runtime_and_body_through_to_set_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = object()
    request = _request_with_runtime(runtime)
    body = PythonInterpreterRequest(mode="auto")
    calls: list[tuple[object, object]] = []

    async def fake_set_python_interpreter(
        received_body: object,
        received_runtime: object,
    ) -> dict[str, object]:
        calls.append((received_body, received_runtime))
        return {"mode": "auto"}

    monkeypatch.setattr(
        runtime_api.runner_services,
        "set_python_interpreter",
        fake_set_python_interpreter,
    )

    response = asyncio.run(runtime_api.set_python_interpreter(body, cast(Any, request)))

    assert response == {"mode": "auto"}
    assert calls == [(body, runtime)]


def test_runners_router_passes_runtime_and_body_through_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = object()
    request = _request_with_runtime(runtime)
    body = runners_api.RunnerInstallRequest(runner="opencode")
    calls: list[tuple[object, object]] = []

    async def fake_install_runner(
        received_body: object,
        *,
        runtime: object,
    ) -> dict[str, object]:
        calls.append((received_body, runtime))
        return {"job": {"id": "job-1"}}

    monkeypatch.setattr(
        runners_api.runner_services,
        "install_runner",
        fake_install_runner,
    )

    response = asyncio.run(runners_api.install_runner(body, cast(Any, request)))

    assert response == {"job": {"id": "job-1"}}
    assert calls == [(body, runtime)]


def test_runners_router_passes_query_args_through_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    async def fake_get_runner_models(
        *, runner: str = "opencode", force_refresh: bool = False
    ) -> dict[str, object]:
        calls.append((runner, force_refresh))
        return {"runner": runner, "models": []}

    monkeypatch.setattr(
        runners_api.runner_services,
        "get_runner_models",
        fake_get_runner_models,
    )

    response = asyncio.run(
        runners_api.get_runner_models(runner="codex", force_refresh=True)
    )

    assert response == {"runner": "codex", "models": []}
    assert calls == [("codex", True)]


def test_server_runtime_wrapper_passes_query_args_through_to_runner_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    async def fake_get_runner_models(
        *, runner: str = "opencode", force_refresh: bool = False
    ) -> dict[str, object]:
        calls.append((runner, force_refresh))
        return {"runner": runner, "models": []}

    monkeypatch.setattr(
        server.runner_services, "get_runner_models", fake_get_runner_models
    )

    response = asyncio.run(
        server.get_runner_models(runner="claude", force_refresh=True)
    )

    assert response == {"runner": "claude", "models": []}
    assert calls == [("claude", True)]


def test_server_session_wrapper_passes_runtime_body_and_path_args_through_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = object()
    request = _request_with_runtime(runtime)
    body = sessions_api.RenameSessionRequest(name="Server wrapper rename")
    calls: list[tuple[object, object, object]] = []

    def fake_rename_session(
        received_runtime: object,
        received_session_id: object,
        received_body: object,
    ) -> dict[str, object]:
        calls.append((received_runtime, received_session_id, received_body))
        return {"status": "ok"}

    monkeypatch.setattr(server.session_services, "rename_session", fake_rename_session)

    response = asyncio.run(
        server.rename_session("session-999", body, cast(Any, request))
    )

    assert response == {"status": "ok"}
    assert calls == [(runtime, "session-999", body)]


def _script_code(*, color: str = "steelblue") -> str:
    return (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.figure(figsize=(3, 2))\n"
        f"plt.plot([1, 2, 3], [2, 1, 3], color='{color}')\n"
        "plt.tight_layout()\n"
        "plt.savefig('plot.png')\n"
    )


def _create_persisted_plot_workspace(workspace_dir: Path) -> server.PlotModeState:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    state = server.init_plot_mode_session(
        workspace_dir=workspace_dir,
        persist_workspace=True,
    )
    server._touch_plot_mode(state)
    return state


@pytest.fixture(autouse=True)
def _stub_runner_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": ["opencode"],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )


def test_runtime_reset_fixture_starts_clean(backend_runtime_reset) -> None:
    assert server._session is None
    assert server._sessions == {}
    assert server._session_order == []
    assert server._active_session_id is None
    assert server._plot_mode is None
    assert server._workspace_dir == Path.cwd()
    assert server._loaded_session_store_root is None
    assert server._fix_jobs == {}
    assert server._fix_job_tasks == {}
    assert server._fix_job_processes == {}
    assert server._active_fix_job_ids_by_session == {}


def test_create_app_accepts_injected_runtime(tmp_path: Path) -> None:
    runtime = build_test_runtime(store_root=tmp_path)

    app = server.create_app(runtime=runtime)

    assert app.state.runtime is runtime


def test_test_runtime_is_isolated(
    app_with_test_runtime,
    run_with_test_runtime,
    shared_runtime,
    test_runtime,
    tmp_path: Path,
) -> None:
    isolated_workspace = tmp_path / "isolated-workspace"
    shared_workspace = tmp_path / "shared-workspace"

    isolated_state = run_with_test_runtime(
        lambda: server.init_plot_mode_session(
            workspace_dir=isolated_workspace,
            persist_workspace=False,
        )
    )
    shared_state = server.init_plot_mode_session(
        workspace_dir=shared_workspace,
        persist_workspace=False,
    )

    with TestClient(app_with_test_runtime) as client:
        response = client.get("/api/bootstrap")

    shared_plot_mode = server._with_runtime(
        shared_runtime,
        lambda: server._runtime_plot_mode_state_value(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert cast(BackendRuntime, cast(FastAPI, client.app).state.runtime) is test_runtime
    assert payload["plot_mode"]["id"] == isolated_state.id
    assert payload["plot_mode"]["id"] != shared_state.id
    assert test_runtime.store.plot_mode is None
    assert session_services.should_restore_session_store(test_runtime) is True
    assert shared_plot_mode is not None
    assert shared_plot_mode.id == shared_state.id


def test_zero_arg_app_startup_restores_latest_workspace_into_shared_runtime(
    monkeypatch: pytest.MonkeyPatch,
    reset_shared_runtime_state,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    shared_runtime = get_shared_runtime()

    workspace = tmp_path / "workspace"
    state = server.init_plot_mode_session(
        workspace_dir=workspace,
        persist_workspace=True,
    )
    server._touch_plot_mode(state)

    shared_runtime.store.plot_mode = None
    shared_runtime.store.active_workspace_id = None
    shared_runtime.store.loaded_session_store_root = None
    reset_shared_runtime_state()

    app = server.create_app()
    with TestClient(app) as client:
        assert app.state.runtime.store.plot_mode is not None
        assert app.state.runtime.store.plot_mode.id == state.id
        assert app.state.runtime.store.active_workspace_id == state.id
        response = client.get("/api/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "plot"
    assert payload["plot_mode"]["id"] == state.id
    assert payload["active_workspace_id"] == state.id
    assert shared_runtime.store.plot_mode is not None
    assert shared_runtime.store.plot_mode.id == state.id
    assert shared_runtime.store.active_workspace_id == state.id


def test_zero_arg_app_startup_hydrates_latest_annotation_workspace_before_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    reset_shared_runtime_state,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    shared_runtime = get_shared_runtime()

    plot_workspace = tmp_path / "plot-workspace"
    plot_state = server.init_plot_mode_session(
        workspace_dir=plot_workspace,
        persist_workspace=True,
    )
    server._touch_plot_mode(plot_state)

    script_path = tmp_path / "workspace" / "latest.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(_script_code(color="black"))
    result = server.init_session_from_script(script_path)
    assert result.success
    session = server.get_session()

    shared_runtime.store.plot_mode = None
    shared_runtime.store.active_session = None
    shared_runtime.store.active_session_id = None
    shared_runtime.store.active_workspace_id = None
    shared_runtime.store.loaded_session_store_root = None
    reset_shared_runtime_state()

    app = server.create_app()
    with TestClient(app) as client:
        assert app.state.runtime.store.active_session is not None
        assert app.state.runtime.store.active_session.id == session.id
        assert app.state.runtime.store.active_session_id == session.id
        assert app.state.runtime.store.active_workspace_id == session.workspace_id
        response = client.get("/api/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "annotation"
    assert payload["session"]["id"] == session.id
    assert payload["active_workspace_id"] == session.workspace_id


def test_injected_runtime_without_store_root_skips_shared_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENPLOT_STATE_DIR", str(tmp_path / "shared-state"))

    workspace = tmp_path / "workspace"
    state = server.init_plot_mode_session(
        workspace_dir=workspace,
        persist_workspace=True,
    )
    server._touch_plot_mode(state)

    runtime = BackendRuntime()

    with TestClient(server.create_app(runtime=runtime)) as client:
        response = client.get("/api/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "plot"
    assert payload["plot_mode"] is not None
    assert payload["plot_mode"]["id"] != state.id
    assert payload["active_workspace_id"] == payload["plot_mode"]["id"]
    assert runtime.store.sessions == {}
    assert runtime.store.plot_mode is None
    assert runtime.store.loaded_session_store_root is None
    assert session_services.should_restore_session_store(runtime) is False


def test_bootstrap_reads_from_injected_runtime(
    app_with_test_runtime,
    run_with_test_runtime,
    test_runtime,
    tmp_path: Path,
) -> None:
    seeded_state = run_with_test_runtime(
        lambda: server.init_plot_mode_session(
            workspace_dir=tmp_path / "seeded-workspace",
            persist_workspace=False,
        )
    )
    test_runtime.store.active_workspace_id = seeded_state.id

    with TestClient(app_with_test_runtime) as client:
        response = client.get("/api/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["plot_mode"]["id"] == seeded_state.id
    assert payload["active_workspace_id"] == seeded_state.id


def test_bootstrap_service_restores_latest_persisted_workspace_when_store_is_loaded(
    tmp_path: Path,
) -> None:
    runtime = build_test_runtime(store_root=tmp_path / "isolated-state")
    workspace_dir = tmp_path / "restored-workspace"

    persisted_state = server._with_runtime(
        runtime,
        lambda: server.init_plot_mode_session(
            workspace_dir=workspace_dir,
            persist_workspace=True,
        ),
    )
    server._with_runtime(runtime, lambda: server._touch_plot_mode(persisted_state))
    server._with_runtime(runtime, lambda: server._plot_mode_snapshot_path().unlink())
    server._with_runtime(runtime, lambda: server._ensure_session_store_loaded())

    runtime.store.active_session = None
    runtime.store.active_session_id = None
    runtime.store.active_workspace_id = None
    runtime.store.plot_mode = None
    assert runtime.store.loaded_session_store_root is not None

    payload = session_services.build_bootstrap_payload(runtime)

    assert payload["mode"] == "plot"
    assert cast(dict[str, object], payload["plot_mode"])["id"] == persisted_state.id
    assert payload["active_workspace_id"] == persisted_state.id
    assert runtime.store.plot_mode is not None
    assert runtime.store.plot_mode.id == persisted_state.id


def test_injected_runtime_does_not_load_shared_persisted_state_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shared_state_root = tmp_path / "shared-state"
    isolated_state_root = tmp_path / "isolated-state"
    monkeypatch.setenv("OPENPLOT_STATE_DIR", str(shared_state_root))

    script_path = tmp_path / "workspace" / "shared.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(_script_code(color="navy"))

    result = server.init_session_from_script(script_path)
    assert result.success
    shared_session_id = server.get_session().id

    runtime = build_test_runtime(store_root=isolated_state_root)

    with TestClient(server.create_app(runtime=runtime)) as client:
        response = client.get("/api/sessions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sessions"] == []
    assert payload["active_session_id"] is None
    assert shared_session_id not in {entry["id"] for entry in payload["sessions"]}


def test_injected_runtime_teardown_clears_store_state_for_fresh_restore(
    app_with_test_runtime,
    test_runtime,
    tmp_path: Path,
) -> None:
    script_path = tmp_path / "workspace" / "plot.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(_script_code(color="teal"))

    result = server.init_session_from_script(script_path, runtime=test_runtime)
    assert result.success
    session = test_runtime.store.active_session
    assert session is not None

    with TestClient(app_with_test_runtime) as client:
        response = client.get("/api/sessions")

    assert response.status_code == 200
    assert test_runtime.store.sessions == {}
    assert test_runtime.store.session_order == []
    assert test_runtime.store.active_session_id is None
    assert test_runtime.store.active_workspace_id is None
    assert test_runtime.store.active_session is None
    assert test_runtime.store.plot_mode is None
    assert test_runtime.store.loaded_session_store_root is None
    assert session_services.should_restore_session_store(test_runtime) is True


def test_sessions_endpoint_uses_injected_runtime_state(
    app_with_test_runtime,
    shared_runtime,
    test_runtime,
    tmp_path: Path,
) -> None:
    script_path = tmp_path / "plot.py"
    script_path.write_text(_script_code(color="brown"))
    result = server.init_session_from_script(script_path, runtime=test_runtime)
    assert result.success
    session = test_runtime.store.active_session
    assert session is not None

    shared_runtime.store.sessions.clear()
    shared_runtime.store.session_order.clear()
    shared_runtime.store.active_session_id = None
    shared_runtime.store.active_session = None

    with TestClient(app_with_test_runtime) as client:
        response = client.get("/api/sessions")

    assert response.status_code == 200
    payload = response.json()
    assert [
        entry["session_id"]
        for entry in payload["sessions"]
        if entry["workspace_mode"] == "annotation"
    ] == [session.id]
    assert payload["active_session_id"] == session.id


def test_runtime_cannot_be_reused_across_app_lifecycles(tmp_path: Path) -> None:
    runtime = build_test_runtime(store_root=tmp_path)
    app1 = server.create_app(runtime=runtime)
    app2 = server.create_app(runtime=runtime)

    with TestClient(app1):
        with pytest.raises(RuntimeError):
            with TestClient(app2):
                pass


def test_injected_runtime_does_not_share_update_or_model_caches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shared_runtime = get_shared_runtime()
    injected_runtime = build_test_runtime(store_root=tmp_path)
    shared_runtime.infra.update_status_cache = None
    shared_runtime.infra.update_status_cache_expires_at = 0.0
    shared_runtime.infra.opencode_models_cache = [
        OpencodeModelOption(
            id="shared-model",
            provider="openai",
            name="Shared Model",
            variants=[],
        )
    ]
    shared_runtime.infra.opencode_models_cache_expires_at = time.monotonic() + 60.0

    payload = {
        "tag_name": "v999.0.0",
        "draft": False,
        "prerelease": False,
        "html_url": "https://example.com/releases/v999.0.0",
    }
    monkeypatch.setattr(server, "_fetch_latest_release_payload", lambda: payload)

    injected_status = build_update_status_payload(
        injected_runtime,
        allow_network=True,
    )

    assert injected_status["latest_version"] == "999.0.0"
    assert shared_runtime.infra.update_status_cache is None
    assert [model.id for model in shared_runtime.infra.opencode_models_cache or []] == [
        "shared-model"
    ]


def test_bootstrap_prefers_active_workspace_from_injected_runtime(
    app_with_test_runtime,
    run_with_test_runtime,
    test_runtime,
    tmp_path: Path,
) -> None:
    state = run_with_test_runtime(
        lambda: server.init_plot_mode_session(
            workspace_dir=tmp_path / "workspace",
            persist_workspace=False,
        )
    )
    test_runtime.store.active_workspace_id = state.id

    with TestClient(app_with_test_runtime) as client:
        response = client.get("/api/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "plot"
    assert payload["active_workspace_id"] == state.id


def test_injected_runtime_request_path_does_not_mutate_shared_runtime(
    monkeypatch: pytest.MonkeyPatch,
    app_with_test_runtime,
    run_with_test_runtime,
    shared_runtime,
    test_runtime,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    shared_runtime.store.sessions.clear()
    shared_runtime.store.session_order.clear()
    shared_runtime.store.active_session_id = None
    shared_runtime.store.active_session = None

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    script_path = workspace / "runtime-script.py"
    script_path.write_text(_script_code(color="olive"))

    state = run_with_test_runtime(
        lambda: server.init_plot_mode_session(
            workspace_dir=workspace,
            persist_workspace=False,
        )
    )
    test_runtime.store.active_workspace_id = state.id

    with TestClient(app_with_test_runtime) as client:
        response = client.post(
            "/api/plot-mode/select-paths",
            json={
                "selection_type": "script",
                "paths": [str(script_path)],
                "workspace_id": state.id,
            },
        )

        assert response.status_code == 200
        assert test_runtime.store.active_session is not None
        assert test_runtime.store.active_session.source_script_path == str(
            script_path.resolve()
        )

    assert shared_runtime.store.sessions == {}
    assert shared_runtime.store.active_session_id is None


def test_injected_runtime_request_keeps_shared_workspace_dir_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    app_with_test_runtime,
    run_with_test_runtime,
    shared_runtime,
    test_runtime,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    script_path = workspace / "runtime-script.py"
    script_path.write_text(_script_code(color="goldenrod"))

    state = run_with_test_runtime(
        lambda: server.init_plot_mode_session(
            workspace_dir=workspace,
            persist_workspace=False,
        )
    )
    test_runtime.store.active_workspace_id = state.id
    shared_workspace_dir = tmp_path / "shared-workspace"
    shared_runtime.store.workspace_dir = shared_workspace_dir

    with TestClient(app_with_test_runtime) as client:
        response = client.post(
            "/api/plot-mode/select-paths",
            json={
                "selection_type": "script",
                "paths": [str(script_path)],
                "workspace_id": state.id,
            },
        )
        assert response.status_code == 200
        assert test_runtime.store.workspace_dir == workspace.resolve()

    assert shared_runtime.store.workspace_dir == shared_workspace_dir


def test_injected_runtime_non_request_init_keeps_shared_workspace_dir_unchanged(
    shared_runtime,
    test_runtime,
    tmp_path: Path,
) -> None:
    shared_workspace_dir = tmp_path / "shared-workspace"
    shared_runtime.store.workspace_dir = shared_workspace_dir
    server._workspace_dir = shared_workspace_dir

    script_path = tmp_path / "isolated-workspace" / "plot.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(_script_code(color="crimson"))

    result = server.init_session_from_script(script_path, runtime=test_runtime)

    assert result.success
    assert test_runtime.store.workspace_dir == script_path.parent.resolve()
    assert shared_runtime.store.workspace_dir == shared_workspace_dir
    assert server._workspace_dir == shared_workspace_dir


def test_injected_runtime_lifecycle_does_not_leave_shared_state_behind(
    tmp_path: Path,
) -> None:
    runtime = build_test_runtime(store_root=tmp_path / "isolated-state")
    shared_runtime = get_shared_runtime()
    shared_runtime.store.workspace_dir = tmp_path / "shared-before"
    shared_runtime.store.active_session_id = None
    shared_runtime.store.active_session = None
    server._workspace_dir = shared_runtime.store.workspace_dir
    server._active_session_id = None
    server._session = None

    isolated_workspace = tmp_path / "isolated-workspace"
    isolated_workspace.mkdir(parents=True, exist_ok=True)
    runtime.store.workspace_dir = isolated_workspace

    app = server.create_app(runtime=runtime)
    with TestClient(app):
        runtime.store.active_session_id = "isolated-session"
        runtime.infra.lifecycle_owner_token is not None

    assert shared_runtime.store.workspace_dir == tmp_path / "shared-before"
    assert shared_runtime.store.active_session_id is None
    assert server._workspace_dir == tmp_path / "shared-before"
    assert server._active_session_id is None


def test_injected_runtime_startup_failure_releases_lifecycle_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = build_test_runtime(store_root=tmp_path / "isolated-state")
    app = server.create_app(runtime=runtime)
    calls = {"count": 0}
    original = server._ensure_session_store_loaded

    def flaky_loader(*, force_reload: bool = False) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        original(force_reload=force_reload)

    monkeypatch.setattr(server, "_ensure_session_store_loaded", flaky_loader)

    with pytest.raises(RuntimeError, match="boom"):
        with TestClient(app):
            pass

    assert runtime.infra.lifecycle_owner_token is None

    with TestClient(server.create_app(runtime=runtime)):
        pass

    assert runtime.infra.lifecycle_owner_token is None


def test_injected_runtime_startup_hydrates_persisted_sessions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    store_root = tmp_path / "shared-store"
    runtime1 = build_test_runtime(store_root=store_root)
    script_path = tmp_path / "workspace" / "persisted.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(_script_code(color="indigo"))

    result = server.init_session_from_script(script_path, runtime=runtime1)
    assert result.success
    session = runtime1.store.active_session
    assert session is not None

    runtime2 = build_test_runtime(store_root=store_root)

    with TestClient(server.create_app(runtime=runtime2)) as client:
        response = client.get("/api/sessions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_session_id"] == session.id
    assert [
        entry["session_id"]
        for entry in payload["sessions"]
        if entry["workspace_mode"] == "annotation"
    ] == [session.id]


def test_sessions_new_uses_injected_runtime_state(
    app_with_test_runtime,
    shared_runtime,
    test_runtime,
) -> None:
    shared_runtime.store.plot_mode = None
    shared_runtime.store.active_workspace_id = None

    with TestClient(app_with_test_runtime) as client:
        response = client.post("/api/sessions/new")
        assert response.status_code == 200
        assert test_runtime.store.plot_mode is not None
        assert test_runtime.store.active_workspace_id == test_runtime.store.plot_mode.id

    assert shared_runtime.store.plot_mode is None
    assert shared_runtime.store.active_workspace_id is None


def test_sessions_activate_uses_injected_runtime_state(
    app_with_test_runtime,
    shared_runtime,
    test_runtime,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    script_a = workspace / "a.py"
    script_b = workspace / "b.py"
    script_a.write_text(_script_code(color="maroon"))
    script_b.write_text(_script_code(color="cyan"))

    assert server.init_session_from_script(script_a, runtime=test_runtime).success
    first_session = test_runtime.store.active_session
    assert first_session is not None
    assert server.init_session_from_script(script_b, runtime=test_runtime).success
    second_session = test_runtime.store.active_session
    assert second_session is not None
    assert second_session.id != first_session.id

    shared_runtime.store.active_session_id = None
    shared_runtime.store.active_session = None
    shared_runtime.store.sessions.clear()

    with TestClient(app_with_test_runtime) as client:
        response = client.post(f"/api/sessions/{first_session.id}/activate")
        assert response.status_code == 200
        assert test_runtime.store.active_session_id == first_session.id
        assert test_runtime.store.active_session is not None
        assert test_runtime.store.active_session.id == first_session.id

    assert shared_runtime.store.active_session_id is None
    assert shared_runtime.store.sessions == {}


def test_sessions_sidebar_endpoints_activate_previous_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    script_a = workspace / "alpha_plot.py"
    script_a.write_text(_script_code(color="steelblue"))

    script_b = workspace / "beta_plot.py"
    script_b.write_text(_script_code(color="crimson"))

    first_result = server.init_session_from_script(script_a)
    assert first_result.success

    with TestClient(server.create_app()) as client:
        initial_sessions_resp = client.get("/api/sessions")
        assert initial_sessions_resp.status_code == 200
        initial_sessions_payload = initial_sessions_resp.json()
        assert len(initial_sessions_payload["sessions"]) == 1
        assert initial_sessions_payload["sessions"][0]["workspace_name"]
        first_session_id = initial_sessions_payload["sessions"][0]["id"]

        new_session_resp = client.post("/api/sessions/new")
        assert new_session_resp.status_code == 200
        new_session_payload = new_session_resp.json()
        assert new_session_payload["mode"] == "plot"
        assert new_session_payload["active_session_id"] is None

        script_select_resp = client.post(
            "/api/plot-mode/select-paths",
            json={
                "selection_type": "script",
                "paths": [str(script_b)],
            },
        )
        assert script_select_resp.status_code == 200
        script_select_payload = script_select_resp.json()
        assert script_select_payload["mode"] == "annotation"

        second_session_id = script_select_payload["session"]["id"]
        assert second_session_id != first_session_id

        list_sessions_resp = client.get("/api/sessions")
        assert list_sessions_resp.status_code == 200
        list_sessions_payload = list_sessions_resp.json()
        assert len(list_sessions_payload["sessions"]) == 2
        assert list_sessions_payload["active_session_id"] == second_session_id

        activate_resp = client.post(f"/api/sessions/{first_session_id}/activate")
        assert activate_resp.status_code == 200
        activate_payload = activate_resp.json()
        assert activate_payload["mode"] == "annotation"
        assert activate_payload["session"]["id"] == first_session_id
        assert activate_payload["active_session_id"] == first_session_id

        active_session_resp = client.get("/api/session")
        assert active_session_resp.status_code == 200
        active_session_payload = active_session_resp.json()
        assert active_session_payload["id"] == first_session_id
        assert active_session_payload["source_script_path"] == str(script_a)


def test_workspace_name_defaults_to_created_time_and_can_be_edited(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    script_path = workspace / "rename_me.py"
    script_path.write_text(_script_code(color="purple"))

    result = server.init_session_from_script(script_path)
    assert result.success

    with TestClient(server.create_app()) as client:
        sessions_resp = client.get("/api/sessions")
        assert sessions_resp.status_code == 200
        payload = sessions_resp.json()
        assert len(payload["sessions"]) == 1

        summary = payload["sessions"][0]
        session_id = summary["id"]
        default_name = summary["workspace_name"]
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} [A-Za-z0-9_+:-]+",
            default_name,
        )

        rename_resp = client.patch(
            f"/api/sessions/{session_id}",
            json={"workspace_name": "Revenue Workspace"},
        )
        assert rename_resp.status_code == 200
        renamed_workspace = rename_resp.json()["workspace"]
        assert renamed_workspace["workspace_name"] == "Revenue Workspace"

        sessions_after_rename = client.get("/api/sessions")
        assert sessions_after_rename.status_code == 200
        assert (
            sessions_after_rename.json()["sessions"][0]["workspace_name"]
            == "Revenue Workspace"
        )

        active_session_resp = client.get("/api/session")
        assert active_session_resp.status_code == 200
        assert active_session_resp.json()["workspace_name"] == "Revenue Workspace"


def test_default_workspace_name_uses_localized_timezone_label() -> None:
    pacific = timezone(timedelta(hours=-8), name="PST")

    default_name = server._default_workspace_name(
        "2024-01-15T12:00:00+00:00",
        display_tz=pacific,
    )

    assert default_name == "2024-01-15 04:00 PST"


def test_sessions_persist_across_restarts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    script_a = workspace / "session_a.py"
    script_a.write_text(_script_code(color="black"))
    script_b = workspace / "session_b.py"
    script_b.write_text(_script_code(color="forestgreen"))

    result_a = server.init_session_from_script(script_a)
    assert result_a.success
    session_a_id = server.get_session().id

    server.init_plot_mode_session(workspace_dir=workspace)

    result_b = server.init_session_from_script(script_b)
    assert result_b.success
    session_b_id = server.get_session().id

    with TestClient(server.create_app()) as client:
        activate_resp = client.post(f"/api/sessions/{session_a_id}/activate")
        assert activate_resp.status_code == 200

        before_restart_resp = client.get("/api/sessions")
        assert before_restart_resp.status_code == 200
        before_restart_payload = before_restart_resp.json()
        session_ids = [entry["id"] for entry in before_restart_payload["sessions"]]
        assert session_a_id in session_ids
        assert session_b_id in session_ids
        assert before_restart_payload["active_session_id"] == session_a_id

    with TestClient(server.create_app()) as client:
        after_restart_resp = client.get("/api/sessions")
        assert after_restart_resp.status_code == 200
        after_restart_payload = after_restart_resp.json()
        session_ids = [entry["id"] for entry in after_restart_payload["sessions"]]
        assert session_a_id in session_ids
        assert session_b_id in session_ids
        assert after_restart_payload["active_session_id"] == session_a_id

        active_session_resp = client.get("/api/session")
        assert active_session_resp.status_code == 200
        assert active_session_resp.json()["id"] == session_a_id


def test_bootstrap_restores_last_modified_workspace_across_modes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    script_path = workspace / "annotation.py"
    script_path.write_text(_script_code(color="midnightblue"))

    result = server.init_session_from_script(script_path)
    assert result.success
    session_id = server.get_session().id

    plot_workspace = tmp_path / "plot-workspace"
    plot_workspace.mkdir(parents=True, exist_ok=True)
    plot_state = server.init_plot_mode_session(
        workspace_dir=plot_workspace,
        persist_workspace=True,
    )
    preview_plot = plot_workspace / "captures" / "preview.png"
    preview_plot.parent.mkdir(parents=True, exist_ok=True)
    preview_plot.write_bytes(b"preview")

    plot_state.current_script = _script_code(color="darkorange")
    plot_state.current_plot = str(preview_plot)
    plot_state.plot_type = "raster"
    server._touch_plot_mode(plot_state)

    with TestClient(server.create_app()) as client:
        first_bootstrap_response = client.get("/api/bootstrap")
        assert first_bootstrap_response.status_code == 200
        first_payload = first_bootstrap_response.json()
        assert first_payload["mode"] == "plot"
        assert first_payload["plot_mode"] is not None
        assert first_payload["plot_mode"]["id"] == plot_state.id
        assert first_payload["active_workspace_id"] == plot_state.id

        activate_response = client.post(f"/api/sessions/{session_id}/activate")
        assert activate_response.status_code == 200

        second_bootstrap_response = client.get("/api/bootstrap")
        assert second_bootstrap_response.status_code == 200
        second_payload = second_bootstrap_response.json()
        assert second_payload["mode"] == "annotation"
        assert second_payload["session"] is not None
        assert second_payload["session"]["id"] == session_id
        assert second_payload["active_workspace_id"] == session_id


def test_latest_workspace_restore_and_active_workspace_hydration_still_work(
    monkeypatch,
    reset_shared_runtime_state,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    script_a = workspace / "alpha.py"
    script_b = workspace / "beta.py"
    script_a.write_text(_script_code(color="navy"))
    script_b.write_text(_script_code(color="crimson"))

    first_result = server.init_session_from_script(script_a)
    assert first_result.success
    first_session_id = server.get_session().id

    server.init_plot_mode_session(workspace_dir=workspace)

    second_result = server.init_session_from_script(script_b)
    assert second_result.success
    second_session_id = server.get_session().id

    with TestClient(server.create_app()) as client:
        activate_resp = client.post(f"/api/sessions/{first_session_id}/activate")
        assert activate_resp.status_code == 200

    reset_shared_runtime_state()

    with TestClient(server.create_app()) as client:
        bootstrap_response = client.get("/api/bootstrap")
        active_session_response = client.get("/api/session")
        sessions_response = client.get("/api/sessions")

    assert bootstrap_response.status_code == 200
    bootstrap_payload = bootstrap_response.json()
    assert bootstrap_payload["mode"] == "annotation"
    assert bootstrap_payload["session"]["id"] == first_session_id
    assert bootstrap_payload["active_session_id"] == first_session_id
    assert bootstrap_payload["active_workspace_id"] == first_session_id

    assert active_session_response.status_code == 200
    assert active_session_response.json()["id"] == first_session_id

    assert sessions_response.status_code == 200
    payload = sessions_response.json()
    assert payload["active_session_id"] == first_session_id
    assert {entry["id"] for entry in payload["sessions"]} == {
        first_session_id,
        second_session_id,
    }


def test_plot_endpoint_can_target_specific_workspace_version(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    script_a = workspace / "session_a.py"
    script_a.write_text(_script_code(color="steelblue"))
    script_b = workspace / "session_b.py"
    script_b.write_text(_script_code(color="forestgreen"))

    result_a = server.init_session_from_script(script_a)
    assert result_a.success
    session_a_id = server.get_session().id

    server.init_plot_mode_session(workspace_dir=workspace)

    result_b = server.init_session_from_script(script_b)
    assert result_b.success
    session_b_id = server.get_session().id

    with TestClient(server.create_app()) as client:
        activate_a_resp = client.post(f"/api/sessions/{session_a_id}/activate")
        assert activate_a_resp.status_code == 200

        session_a_root = client.get("/api/session").json()
        main_branch_id = session_a_root["active_branch_id"]
        root_version_id = session_a_root["checked_out_version_id"]

        add_resp = client.post(
            "/api/annotations",
            json={
                "feedback": "Use a red line",
                "region": {
                    "type": "rect",
                    "points": [
                        {"x": 0.2, "y": 0.2},
                        {"x": 0.6, "y": 0.6},
                    ],
                    "crop_base64": "",
                },
            },
        )
        assert add_resp.status_code == 200
        main_annotation_id = add_resp.json()["id"]

        submit_main_resp = client.post(
            "/api/script",
            json={
                "code": _script_code(color="black"),
                "annotation_id": main_annotation_id,
            },
        )
        assert submit_main_resp.status_code == 200

        checkout_root_resp = client.post(
            "/api/checkout",
            json={"version_id": root_version_id, "branch_id": main_branch_id},
        )
        assert checkout_root_resp.status_code == 200

        add_branch_resp = client.post(
            "/api/annotations",
            json={
                "feedback": "Use a crimson line",
                "region": {
                    "type": "rect",
                    "points": [
                        {"x": 0.25, "y": 0.25},
                        {"x": 0.7, "y": 0.7},
                    ],
                    "crop_base64": "",
                },
            },
        )
        assert add_branch_resp.status_code == 200
        branch_annotation_id = add_branch_resp.json()["id"]

        submit_branch_resp = client.post(
            "/api/script",
            json={
                "code": _script_code(color="crimson"),
                "annotation_id": branch_annotation_id,
            },
        )
        assert submit_branch_resp.status_code == 200
        branch_version_id = submit_branch_resp.json()["version_id"]

        activate_b_resp = client.post(f"/api/sessions/{session_b_id}/activate")
        assert activate_b_resp.status_code == 200

        session_b_payload = client.get("/api/session").json()
        active_plot_resp = client.get("/api/plot")
        assert active_plot_resp.status_code == 200
        assert (
            active_plot_resp.content
            == Path(session_b_payload["current_plot"]).read_bytes()
        )

        session_a_payload = client.get(f"/api/session?session_id={session_a_id}").json()
        branch_version = next(
            version
            for version in session_a_payload["versions"]
            if version["id"] == branch_version_id
        )

        explicit_plot_resp = client.get(
            f"/api/plot?session_id={session_a_id}&version_id={branch_version_id}"
        )
        assert explicit_plot_resp.status_code == 200
        assert (
            explicit_plot_resp.content
            == Path(branch_version["plot_artifact_path"]).read_bytes()
        )
        assert explicit_plot_resp.content != active_plot_resp.content


def _wait_for_fix_job_to_finish(
    client: TestClient,
    *,
    session_id: str | None = None,
    timeout_s: float = 4.0,
) -> dict:
    deadline = time.monotonic() + timeout_s
    last_payload: dict | None = None

    while time.monotonic() < deadline:
        endpoint = "/api/fix-jobs/current"
        if session_id:
            endpoint = f"{endpoint}?session_id={session_id}"

        response = client.get(endpoint)
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload
        job = payload.get("job")
        if isinstance(job, dict) and job.get("status") in {
            "completed",
            "failed",
            "cancelled",
        }:
            return job
        time.sleep(0.05)

    raise AssertionError(f"Timed out waiting for fix job: {last_payload}")


def test_switch_workspace_while_fix_job_running(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    script_a = workspace / "workspace_a.py"
    script_b = workspace / "workspace_b.py"
    script_a.write_text(_script_code(color="royalblue"))
    script_b.write_text(_script_code(color="darkorange"))

    result_a = server.init_session_from_script(script_a)
    assert result_a.success
    session_a_id = server.get_session().id

    server.init_plot_mode_session(workspace_dir=workspace)

    result_b = server.init_session_from_script(script_b)
    assert result_b.success
    session_b_id = server.get_session().id

    monkeypatch.setattr(
        server,
        "_refresh_opencode_models_cache",
        lambda force_refresh=False: [
            OpencodeModelOption(
                id="openai/gpt-5.3-codex",
                provider="openai",
                name="GPT-5.3 Codex",
                variants=["high"],
            )
        ],
    )

    async def fake_fix_iteration(job, step, *, extra_prompt=None):
        _ = extra_prompt
        step.command = ["opencode", "run", "--command", "plot-fix"]
        step.exit_code = 0
        step.stdout = "ok"
        step.stderr = ""

        await asyncio.sleep(0.2)

        session = server._session_for_fix_job(job)
        target = next(
            ann for ann in session.annotations if ann.id == step.annotation_id
        )
        target.status = AnnotationStatus.addressed
        target.addressed_in_version_id = session.checked_out_version_id

    monkeypatch.setattr(server, "_run_opencode_fix_iteration", fake_fix_iteration)

    with TestClient(server.create_app()) as client:
        activate_a_response = client.post(f"/api/sessions/{session_a_id}/activate")
        assert activate_a_response.status_code == 200

        add_annotation_response = client.post(
            "/api/annotations",
            json={
                "feedback": "Increase title size",
                "region": {
                    "type": "rect",
                    "points": [
                        {"x": 0.1, "y": 0.1},
                        {"x": 0.5, "y": 0.5},
                    ],
                    "crop_base64": "",
                },
            },
        )
        assert add_annotation_response.status_code == 200

        start_fix_response = client.post(
            "/api/fix-jobs",
            json={"model": "openai/gpt-5.3-codex", "variant": "high"},
        )
        assert start_fix_response.status_code == 200
        job = start_fix_response.json()["job"]
        assert job["session_id"] == session_a_id

        switch_response = client.post(f"/api/sessions/{session_b_id}/activate")
        assert switch_response.status_code == 200
        assert switch_response.json()["session"]["id"] == session_b_id

        completed_job = _wait_for_fix_job_to_finish(client, session_id=session_a_id)
        assert completed_job["status"] == "completed"
        assert completed_job["session_id"] == session_a_id

        active_session_response = client.get("/api/session")
        assert active_session_response.status_code == 200
        assert active_session_response.json()["id"] == session_b_id

        fixed_session_response = client.get(f"/api/session?session_id={session_a_id}")
        assert fixed_session_response.status_code == 200
        annotations = fixed_session_response.json()["annotations"]
        assert annotations
        assert annotations[0]["status"] == "addressed"


def test_fix_jobs_are_scoped_per_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    script_a = workspace / "scope_a.py"
    script_b = workspace / "scope_b.py"
    script_a.write_text(_script_code(color="navy"))
    script_b.write_text(_script_code(color="orange"))

    result_a = server.init_session_from_script(script_a)
    assert result_a.success
    session_a_id = server.get_session().id

    server.init_plot_mode_session(workspace_dir=workspace)

    result_b = server.init_session_from_script(script_b)
    assert result_b.success
    session_b_id = server.get_session().id

    monkeypatch.setattr(
        server,
        "_refresh_opencode_models_cache",
        lambda force_refresh=False: [
            OpencodeModelOption(
                id="openai/gpt-5.3-codex",
                provider="openai",
                name="GPT-5.3 Codex",
                variants=["high"],
            )
        ],
    )

    async def fake_fix_iteration(job, step, *, extra_prompt=None):
        _ = extra_prompt
        step.command = ["opencode", "run", "--command", "plot-fix"]
        step.exit_code = 0
        step.stdout = "ok"
        step.stderr = ""

        await asyncio.sleep(0.25)

        session = server._session_for_fix_job(job)
        target = next(
            ann for ann in session.annotations if ann.id == step.annotation_id
        )
        target.status = AnnotationStatus.addressed
        target.addressed_in_version_id = session.checked_out_version_id

    monkeypatch.setattr(server, "_run_opencode_fix_iteration", fake_fix_iteration)

    with TestClient(server.create_app()) as client:
        assert client.post(f"/api/sessions/{session_a_id}/activate").status_code == 200
        assert (
            client.post(
                "/api/annotations",
                json={
                    "feedback": "workspace a",
                    "region": {
                        "type": "rect",
                        "points": [{"x": 0.1, "y": 0.1}, {"x": 0.6, "y": 0.6}],
                        "crop_base64": "",
                    },
                },
            ).status_code
            == 200
        )

        start_a = client.post(
            "/api/fix-jobs",
            json={"model": "openai/gpt-5.3-codex", "variant": "high"},
        )
        assert start_a.status_code == 200
        job_a = start_a.json()["job"]
        assert job_a["session_id"] == session_a_id
        assert f"/fix_runner/{job_a['id']}" in job_a["workspace_dir"]

        assert client.post(f"/api/sessions/{session_b_id}/activate").status_code == 200
        assert (
            client.post(
                "/api/annotations",
                json={
                    "feedback": "workspace b",
                    "region": {
                        "type": "rect",
                        "points": [{"x": 0.2, "y": 0.2}, {"x": 0.7, "y": 0.7}],
                        "crop_base64": "",
                    },
                },
            ).status_code
            == 200
        )

        start_b = client.post(
            "/api/fix-jobs",
            json={"model": "openai/gpt-5.3-codex", "variant": "high"},
        )
        assert start_b.status_code == 200
        job_b = start_b.json()["job"]
        assert job_b["session_id"] == session_b_id
        assert f"/fix_runner/{job_b['id']}" in job_b["workspace_dir"]
        assert job_b["workspace_dir"] != job_a["workspace_dir"]

        completed_a = _wait_for_fix_job_to_finish(client, session_id=session_a_id)
        completed_b = _wait_for_fix_job_to_finish(client, session_id=session_b_id)
        assert completed_a["status"] == "completed"
        assert completed_b["status"] == "completed"

        active_in_b = client.get(f"/api/fix-jobs/current?session_id={session_b_id}")
        assert active_in_b.status_code == 200
        assert active_in_b.json()["job"]["session_id"] == session_b_id


def test_workspace_still_allows_only_one_active_fix_job(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "one_workspace.py"
    script_path.write_text(_script_code(color="black"))

    result = server.init_session_from_script(script_path)
    assert result.success
    session_id = server.get_session().id

    monkeypatch.setattr(
        server,
        "_refresh_opencode_models_cache",
        lambda force_refresh=False: [
            OpencodeModelOption(
                id="openai/gpt-5.3-codex",
                provider="openai",
                name="GPT-5.3 Codex",
                variants=["high"],
            )
        ],
    )

    async def fake_fix_iteration(job, step, *, extra_prompt=None):
        _ = extra_prompt
        step.command = ["opencode", "run", "--command", "plot-fix"]
        step.exit_code = 0
        step.stdout = "ok"
        step.stderr = ""
        await asyncio.sleep(0.3)

        session = server._session_for_fix_job(job)
        target = next(
            ann for ann in session.annotations if ann.id == step.annotation_id
        )
        target.status = AnnotationStatus.addressed
        target.addressed_in_version_id = session.checked_out_version_id

    monkeypatch.setattr(server, "_run_opencode_fix_iteration", fake_fix_iteration)

    with TestClient(server.create_app()) as client:
        assert (
            client.post(
                "/api/annotations",
                json={
                    "feedback": "first",
                    "region": {
                        "type": "rect",
                        "points": [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.5}],
                        "crop_base64": "",
                    },
                },
            ).status_code
            == 200
        )

        start_first = client.post(
            "/api/fix-jobs",
            json={"model": "openai/gpt-5.3-codex", "variant": "high"},
        )
        assert start_first.status_code == 200

        start_second = client.post(
            "/api/fix-jobs",
            json={
                "model": "openai/gpt-5.3-codex",
                "variant": "high",
                "session_id": session_id,
            },
        )
        assert start_second.status_code == 409
        assert "already running in this workspace" in start_second.text


def test_submit_script_can_target_non_active_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    script_a = workspace / "target_workspace.py"
    script_b = workspace / "active_workspace.py"
    script_a.write_text(_script_code(color="teal"))
    script_b.write_text(_script_code(color="brown"))

    result_a = server.init_session_from_script(script_a)
    assert result_a.success
    session_a_id = server.get_session().id

    server.init_plot_mode_session(workspace_dir=workspace)

    result_b = server.init_session_from_script(script_b)
    assert result_b.success
    session_b_id = server.get_session().id

    with TestClient(server.create_app()) as client:
        activate_a_response = client.post(f"/api/sessions/{session_a_id}/activate")
        assert activate_a_response.status_code == 200

        add_annotation_response = client.post(
            "/api/annotations",
            json={
                "feedback": "Change line color",
                "region": {
                    "type": "rect",
                    "points": [
                        {"x": 0.1, "y": 0.1},
                        {"x": 0.4, "y": 0.4},
                    ],
                    "crop_base64": "",
                },
            },
        )
        assert add_annotation_response.status_code == 200

        switch_response = client.post(f"/api/sessions/{session_b_id}/activate")
        assert switch_response.status_code == 200
        assert switch_response.json()["session"]["id"] == session_b_id

        feedback_response = client.get(f"/api/feedback?session_id={session_a_id}")
        assert feedback_response.status_code == 200
        target_annotation_id = feedback_response.json()["target_annotation_id"]
        assert isinstance(target_annotation_id, str) and target_annotation_id

        submit_response = client.post(
            f"/api/script?session_id={session_a_id}",
            json={
                "code": _script_code(color="teal"),
                "annotation_id": target_annotation_id,
            },
        )
        assert submit_response.status_code == 200

        active_session_response = client.get("/api/session")
        assert active_session_response.status_code == 200
        assert active_session_response.json()["id"] == session_b_id

        fixed_session_response = client.get(f"/api/session?session_id={session_a_id}")
        assert fixed_session_response.status_code == 200
        target_annotation = next(
            annotation
            for annotation in fixed_session_response.json()["annotations"]
            if annotation["id"] == target_annotation_id
        )
        assert target_annotation["status"] == "addressed"


def test_delete_workspace_removes_artifacts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    script_a = workspace / "delete_a.py"
    script_b = workspace / "delete_b.py"
    script_a.write_text(_script_code(color="black"))
    script_b.write_text(_script_code(color="orange"))

    result_a = server.init_session_from_script(script_a)
    assert result_a.success
    session_a = server.get_session()
    session_a_id = session_a.id
    session_a_artifacts = Path(session_a.artifacts_root)
    assert session_a_artifacts.exists()

    server.init_plot_mode_session(workspace_dir=workspace)

    result_b = server.init_session_from_script(script_b)
    assert result_b.success
    session_b_id = server.get_session().id

    with TestClient(server.create_app()) as client:
        assert client.post(f"/api/sessions/{session_a_id}/activate").status_code == 200

        delete_response = client.delete(f"/api/sessions/{session_a_id}")
        assert delete_response.status_code == 200
        payload = delete_response.json()
        assert payload["mode"] == "annotation"
        assert payload["session"]["id"] == session_b_id

        list_response = client.get("/api/sessions")
        assert list_response.status_code == 200
        remaining_ids = [entry["id"] for entry in list_response.json()["sessions"]]
        assert session_a_id not in remaining_ids
        assert session_b_id in remaining_ids

    assert not session_a_artifacts.exists()


def test_new_workspace_uses_isolated_plot_mode_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    script_path = workspace / "existing.py"
    script_path.write_text(_script_code(color="navy"))

    result = server.init_session_from_script(script_path)
    assert result.success

    with TestClient(server.create_app()) as client:
        response = client.post("/api/sessions/new")
        assert response.status_code == 200
        payload = response.json()

        assert payload["mode"] == "plot"
        plot_mode_dir = Path(payload["plot_mode"]["workspace_dir"])
        assert plot_mode_dir.exists()
        assert plot_mode_dir != workspace
        assert "plot-mode" in str(plot_mode_dir)


def test_plot_mode_workspace_can_resume_after_switching_to_annotation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    script_path = workspace / "active.py"
    script_path.write_text(_script_code(color="teal"))

    result = server.init_session_from_script(script_path)
    assert result.success
    active_session_id = server.get_session().id

    with TestClient(server.create_app()) as client:
        create_response = client.post("/api/sessions/new")
        assert create_response.status_code == 200
        created_plot_mode = create_response.json()["plot_mode"]
        assert created_plot_mode is not None

        activate_annotation = client.post(f"/api/sessions/{active_session_id}/activate")
        assert activate_annotation.status_code == 200
        assert activate_annotation.json()["mode"] == "annotation"

        resume_plot_mode = client.post("/api/plot-mode/activate")
    assert resume_plot_mode.status_code == 200
    resume_payload = resume_plot_mode.json()
    assert resume_payload["mode"] == "plot"
    assert resume_payload["plot_mode"]["id"] == created_plot_mode["id"]


def test_renaming_non_active_plot_workspace_does_not_change_restored_active_workspace(
    monkeypatch,
    reset_shared_runtime_state,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    state_a = _create_persisted_plot_workspace(workspace_a)
    state_b = _create_persisted_plot_workspace(workspace_b)

    with TestClient(server.create_app()) as client:
        rename_response = client.patch(
            "/api/plot-mode/workspace",
            json={"id": state_a.id, "workspace_name": "Archived Plot"},
        )
        assert rename_response.status_code == 200

    reset_shared_runtime_state()

    with TestClient(server.create_app()) as restarted_client:
        bootstrap_response = restarted_client.get("/api/bootstrap")

    assert bootstrap_response.status_code == 200
    payload = bootstrap_response.json()
    assert payload["mode"] == "plot"
    assert payload["plot_mode"]["id"] == state_b.id
    assert payload["plot_mode"]["workspace_name"] != "Archived Plot"


def test_deleting_non_active_plot_workspace_preserves_active_plot_workspace_pointer(
    monkeypatch,
    reset_shared_runtime_state,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    state_a = _create_persisted_plot_workspace(workspace_a)
    state_b = _create_persisted_plot_workspace(workspace_b)

    with TestClient(server.create_app()) as client:
        delete_response = client.request(
            "DELETE",
            "/api/plot-mode",
            json={"id": state_a.id},
        )
        assert delete_response.status_code == 200

    reset_shared_runtime_state()

    with TestClient(server.create_app()) as restarted_client:
        bootstrap_response = restarted_client.get("/api/bootstrap")

    assert bootstrap_response.status_code == 200
    payload = bootstrap_response.json()
    assert payload["mode"] == "plot"
    assert payload["plot_mode"]["id"] == state_b.id
