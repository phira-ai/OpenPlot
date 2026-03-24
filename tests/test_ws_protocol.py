from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

import openplot.server as server
from openplot.models import (
    FixJob,
    FixJobStep,
    FixJobStatus,
    FixStepStatus,
    PlotModeChatMessage,
)
from openplot.services.runtime import build_test_runtime


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


def _new_region() -> dict:
    return {
        "type": "rect",
        "points": [
            {"x": 0.2, "y": 0.2},
            {"x": 0.6, "y": 0.6},
        ],
        "crop_base64": "",
    }


def test_ws_annotation_and_plot_events_preserve_shape_and_order(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    script_path.write_text(_script_code(color="steelblue"))
    result = server.init_session_from_script(script_path)
    assert result.success

    with TestClient(server.create_app()) as client:
        initial_session = client.get("/api/session").json()
        with client.websocket_connect("/ws") as websocket:
            add_response = client.post(
                "/api/annotations",
                json={"feedback": "first note", "region": _new_region()},
            )
            assert add_response.status_code == 200
            annotation_id = add_response.json()["id"]
            added_event = websocket.receive_json()

            update_response = client.patch(
                f"/api/annotations/{annotation_id}",
                json={"feedback": "updated note"},
            )
            assert update_response.status_code == 200
            updated_event = websocket.receive_json()

            delete_response = client.delete(f"/api/annotations/{annotation_id}")
            assert delete_response.status_code == 200
            deleted_event = websocket.receive_json()

            second_add_response = client.post(
                "/api/annotations",
                json={"feedback": "submit me", "region": _new_region()},
            )
            assert second_add_response.status_code == 200
            submit_annotation_id = second_add_response.json()["id"]
            _ = websocket.receive_json()

            submit_response = client.post(
                "/api/script",
                json={
                    "code": _script_code(color="black"),
                    "annotation_id": submit_annotation_id,
                },
            )
            assert submit_response.status_code == 200
            plot_event = websocket.receive_json()

    assert added_event["type"] == "annotation_added"
    assert added_event["session_id"] == server.get_session().id
    assert added_event["annotation"]["id"] == annotation_id
    assert (
        added_event["checked_out_version_id"]
        == initial_session["checked_out_version_id"]
    )

    assert updated_event["type"] == "annotation_updated"
    assert updated_event["session_id"] == server.get_session().id
    assert updated_event["annotation"]["id"] == annotation_id
    assert updated_event["annotation"]["feedback"] == "updated note"

    assert deleted_event["type"] == "annotation_deleted"
    assert deleted_event["session_id"] == server.get_session().id
    assert deleted_event["id"] == annotation_id
    assert deleted_event["deleted_ids"] == [annotation_id]

    assert plot_event["type"] == "plot_updated"
    assert plot_event["session_id"] == server.get_session().id
    assert plot_event["annotation_id"] == submit_annotation_id
    assert plot_event["reason"] == "new_version"
    assert plot_event["version_id"] == submit_response.json()["version_id"]
    assert plot_event["checked_out_version_id"] == submit_response.json()["version_id"]


def test_ws_deleting_addressed_tip_annotation_preserves_undo_event_order(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    script_path.write_text(_script_code(color="steelblue"))
    result = server.init_session_from_script(script_path)
    assert result.success

    with TestClient(server.create_app()) as client:
        with client.websocket_connect("/ws") as websocket:
            add_response = client.post(
                "/api/annotations",
                json={"feedback": "tip undo", "region": _new_region()},
            )
            assert add_response.status_code == 200
            annotation_id = add_response.json()["id"]
            _ = websocket.receive_json()

            submit_response = client.post(
                "/api/script",
                json={
                    "code": _script_code(color="black"),
                    "annotation_id": annotation_id,
                },
            )
            assert submit_response.status_code == 200
            created_version_event = websocket.receive_json()

            delete_response = client.delete(f"/api/annotations/{annotation_id}")
            assert delete_response.status_code == 200
            undo_plot_event = websocket.receive_json()
            deleted_event = websocket.receive_json()

        session_payload = client.get("/api/session").json()

    assert created_version_event["type"] == "plot_updated"
    assert created_version_event["reason"] == "new_version"

    assert undo_plot_event["type"] == "plot_updated"
    assert undo_plot_event["reason"] == "undo_tip"
    assert undo_plot_event["session_id"] == session_payload["id"]
    assert (
        undo_plot_event["checked_out_version_id"]
        == session_payload["checked_out_version_id"]
    )

    assert deleted_event["type"] == "annotation_deleted"
    assert deleted_event["session_id"] == session_payload["id"]
    assert deleted_event["id"] == annotation_id
    assert deleted_event["deleted_ids"] == [annotation_id]


def test_ws_version_control_checkout_and_branch_switch_events_preserve_contract(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    script_path.write_text(_script_code(color="steelblue"))
    result = server.init_session_from_script(script_path)
    assert result.success

    with TestClient(server.create_app()) as client:
        session0 = client.get("/api/session").json()
        main_branch_id = session0["active_branch_id"]
        root_version_id = session0["checked_out_version_id"]

        add_main_response = client.post(
            "/api/annotations",
            json={"feedback": "increase contrast", "region": _new_region()},
        )
        assert add_main_response.status_code == 200
        main_annotation_id = add_main_response.json()["id"]

        with client.websocket_connect("/ws") as websocket:
            submit_main_response = client.post(
                "/api/script",
                json={
                    "code": _script_code(color="black"),
                    "annotation_id": main_annotation_id,
                },
            )
            assert submit_main_response.status_code == 200
            _ = websocket.receive_json()

            checkout_response = client.post(
                "/api/checkout",
                json={"version_id": root_version_id, "branch_id": main_branch_id},
            )
            assert checkout_response.status_code == 200
            checkout_event = websocket.receive_json()

            add_branch_response = client.post(
                "/api/annotations",
                json={"feedback": "use a red line", "region": _new_region()},
            )
            assert add_branch_response.status_code == 200
            _ = websocket.receive_json()

            branch_session = client.get("/api/session").json()
            branch_id = branch_session["active_branch_id"]
            assert branch_id != main_branch_id

            branch_checkout_response = client.post(
                f"/api/branches/{main_branch_id}/checkout"
            )
            assert branch_checkout_response.status_code == 200
            branch_switch_event = websocket.receive_json()

        final_session = client.get("/api/session").json()

    assert checkout_event["type"] == "plot_updated"
    assert checkout_event["reason"] == "checkout"
    assert checkout_event["session_id"] == final_session["id"]
    assert checkout_event["version_id"] == root_version_id
    assert checkout_event["active_branch_id"] == main_branch_id
    assert checkout_event["checked_out_version_id"] == root_version_id

    assert branch_switch_event["type"] == "plot_updated"
    assert branch_switch_event["reason"] == "branch_switch"
    assert branch_switch_event["session_id"] == final_session["id"]
    assert branch_switch_event["version_id"] == final_session["checked_out_version_id"]
    assert branch_switch_event["active_branch_id"] == main_branch_id
    assert (
        branch_switch_event["checked_out_version_id"]
        == final_session["checked_out_version_id"]
    )


def test_ws_fix_job_events_preserve_shape_and_order() -> None:
    job = FixJob(
        id="job-123",
        model="openai/gpt-5.3-codex",
        branch_id="branch-main",
        branch_name="main",
        session_id="session-123",
        status=FixJobStatus.running,
    )
    job.steps.append(
        FixJobStep(
            index=0,
            annotation_id="annotation-123",
            status=FixStepStatus.running,
        )
    )

    with TestClient(server.create_app()) as client:
        with client.websocket_connect("/ws") as websocket:
            asyncio.run(server._broadcast_fix_job(job))
            asyncio.run(
                server._broadcast_fix_job_log(
                    job_id=job.id,
                    step_index=0,
                    annotation_id="annotation-123",
                    stream="stdout",
                    chunk='{"type":"text","part":{"text":"ok"}}\n',
                    parsed={"type": "text", "part": {"text": "ok"}},
                )
            )
            job.status = FixJobStatus.completed
            job.completed_annotations = 1
            asyncio.run(server._broadcast_fix_job(job))

            started_event = websocket.receive_json()
            log_event = websocket.receive_json()
            completed_event = websocket.receive_json()

    assert [started_event["type"], log_event["type"], completed_event["type"]] == [
        "fix_job_updated",
        "fix_job_log",
        "fix_job_updated",
    ]
    assert started_event["job"]["id"] == "job-123"
    assert started_event["job"]["status"] == "running"
    assert log_event["job_id"] == "job-123"
    assert log_event["step_index"] == 0
    assert log_event["annotation_id"] == "annotation-123"
    assert log_event["stream"] == "stdout"
    assert log_event["chunk"].endswith("\n")
    assert log_event["parsed"] == {"type": "text", "part": {"text": "ok"}}
    assert isinstance(log_event["timestamp"], str) and log_event["timestamp"]
    assert completed_event["job"]["status"] == "completed"
    assert completed_event["job"]["completed_annotations"] == 1


def test_ws_plot_mode_events_preserve_shape_and_order(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    state = server.init_plot_mode_session(
        workspace_dir=workspace, persist_workspace=True
    )
    message = PlotModeChatMessage(role="assistant", content="Draft ready")

    with TestClient(server.create_app()) as client:
        with client.websocket_connect("/ws") as websocket:
            asyncio.run(server._broadcast_plot_mode_state(state))
            asyncio.run(server._broadcast_plot_mode_message_update(state, message))

            script_path = workspace / "generated.py"
            generated_script = _script_code(color="darkorange")
            script_path.write_text(generated_script)
            result = server.init_session_from_script(
                script_path,
                inherit_workspace_id=state.id,
            )
            assert result.success

            asyncio.run(
                server._broadcast(
                    {
                        "type": "plot_mode_completed",
                        "session": server.get_session().model_dump(mode="json"),
                    }
                )
            )

            updated_event = websocket.receive_json()
            message_event = websocket.receive_json()
            completed_event = websocket.receive_json()

    assert [updated_event["type"], message_event["type"], completed_event["type"]] == [
        "plot_mode_updated",
        "plot_mode_message_updated",
        "plot_mode_completed",
    ]
    assert updated_event["plot_mode"]["id"] == state.id
    assert updated_event["plot_mode"]["workspace_dir"] == str(workspace.resolve())
    assert message_event["plot_mode_id"] == state.id
    assert message_event["updated_at"] == state.updated_at
    assert message_event["message"]["id"] == message.id
    assert message_event["message"]["content"] == "Draft ready"
    assert completed_event["session"]["workspace_id"] == state.id
    assert completed_event["session"]["source_script"] == generated_script


def test_ws_plot_mode_preview_preserves_event_order_and_payload_shape(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    preview_path = workspace / "captures" / "preview.png"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_bytes(b"preview")

    state = server.init_plot_mode_session(
        workspace_dir=workspace, persist_workspace=True
    )
    state.current_plot = str(preview_path)
    state.plot_type = "raster"

    with TestClient(server.create_app()) as client:
        with client.websocket_connect("/ws") as websocket:
            asyncio.run(server._broadcast_plot_mode_preview(state))

            state_event = websocket.receive_json()
            preview_event = websocket.receive_json()

    assert state_event["type"] == "plot_mode_updated"
    assert state_event["plot_mode"]["id"] == state.id
    assert state_event["plot_mode"]["current_plot"] == str(preview_path)
    assert state_event["plot_mode"]["plot_type"] == "raster"

    assert preview_event["type"] == "plot_updated"
    assert preview_event["plot_type"] == "raster"
    assert preview_event["revision"] == 0
    assert preview_event["reason"] == "plot_mode_preview"
    assert "session_id" not in preview_event
    assert "version_id" not in preview_event
    assert "checked_out_version_id" not in preview_event


def test_websocket_registration_and_cleanup_use_runtime_ws_clients(
    tmp_path: Path,
) -> None:
    runtime = build_test_runtime(store_root=tmp_path)

    with TestClient(server.create_app(runtime=runtime)) as client:
        assert runtime.infra.ws_clients == set()

        with client.websocket_connect("/ws") as websocket:
            assert len(runtime.infra.ws_clients) == 1
            assert websocket is not None

        assert runtime.infra.ws_clients == set()
