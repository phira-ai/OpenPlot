from __future__ import annotations

import asyncio
import re
import time
from datetime import timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import openplot.server as server
from openplot.models import AnnotationStatus, OpencodeModelOption


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
def _reset_server_state():
    prev_session = server._session
    prev_sessions = dict(server._sessions)
    prev_session_order = list(server._session_order)
    prev_active_session_id = server._active_session_id
    prev_plot_mode = server._plot_mode
    prev_workspace = server._workspace_dir
    prev_loaded_store_root = server._loaded_session_store_root
    prev_fix_jobs = dict(server._fix_jobs)
    prev_fix_job_tasks = dict(server._fix_job_tasks)
    prev_fix_job_processes = dict(server._fix_job_processes)
    prev_active_fix_jobs_by_session = dict(server._active_fix_job_ids_by_session)

    server._session = None
    server._sessions.clear()
    server._session_order.clear()
    server._active_session_id = None
    server._plot_mode = None
    server._loaded_session_store_root = None
    server._fix_jobs.clear()
    server._fix_job_tasks.clear()
    server._fix_job_processes.clear()
    server._active_fix_job_ids_by_session.clear()

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
        server._fix_jobs.clear()
        server._fix_jobs.update(prev_fix_jobs)
        server._fix_job_tasks.clear()
        server._fix_job_tasks.update(prev_fix_job_tasks)
        server._fix_job_processes.clear()
        server._fix_job_processes.update(prev_fix_job_processes)
        server._active_fix_job_ids_by_session.clear()
        server._active_fix_job_ids_by_session.update(prev_active_fix_jobs_by_session)


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

        session = server._sessions[job.session_id]
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

        session = server._sessions[job.session_id]
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

        session = server._sessions[job.session_id]
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

    server._plot_mode = None
    server._session = None
    server._active_session_id = None
    server._loaded_session_store_root = None

    with TestClient(server.create_app()) as restarted_client:
        bootstrap_response = restarted_client.get("/api/bootstrap")

    assert bootstrap_response.status_code == 200
    payload = bootstrap_response.json()
    assert payload["mode"] == "plot"
    assert payload["plot_mode"]["id"] == state_b.id
    assert payload["plot_mode"]["workspace_name"] != "Archived Plot"


def test_deleting_non_active_plot_workspace_preserves_active_plot_workspace_pointer(
    monkeypatch,
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

    server._plot_mode = None
    server._session = None
    server._active_session_id = None
    server._loaded_session_store_root = None

    with TestClient(server.create_app()) as restarted_client:
        bootstrap_response = restarted_client.get("/api/bootstrap")

    assert bootstrap_response.status_code == 200
    payload = bootstrap_response.json()
    assert payload["mode"] == "plot"
    assert payload["plot_mode"]["id"] == state_b.id
