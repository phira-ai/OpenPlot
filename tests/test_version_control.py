from __future__ import annotations

import io
import importlib
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import openplot.server as server
from openplot.models import FixJob
from openplot.services.runtime import build_test_runtime, get_shared_runtime
from openplot.server import create_app, init_session_from_script


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


def _write_script(path: Path, *, color: str = "steelblue") -> None:
    path.write_text(_script_code(color=color))


def _new_region() -> dict:
    return {
        "type": "rect",
        "points": [
            {"x": 0.2, "y": 0.2},
            {"x": 0.6, "y": 0.6},
        ],
        "crop_base64": "",
    }


def test_tip_only_undo_rewinds_branch_head(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    _write_script(script_path, color="steelblue")

    result = init_session_from_script(script_path)
    assert result.success

    client = TestClient(create_app())

    session = client.get("/api/session").json()
    root_version_id = session["checked_out_version_id"]

    add_resp = client.post(
        "/api/annotations",
        json={"feedback": "make this line darker", "region": _new_region()},
    )
    assert add_resp.status_code == 200
    annotation_id = add_resp.json()["id"]

    submit_resp = client.post(
        "/api/script",
        json={"code": _script_code(color="black"), "annotation_id": annotation_id},
    )
    assert submit_resp.status_code == 200
    version_id = submit_resp.json()["version_id"]
    assert script_path.read_text() == _script_code(color="steelblue")

    session_after_submit = client.get("/api/session").json()
    assert session_after_submit["checked_out_version_id"] == version_id
    assert any(
        ann["id"] == annotation_id
        and ann["status"] == "addressed"
        and ann["addressed_in_version_id"] == version_id
        for ann in session_after_submit["annotations"]
    )

    delete_resp = client.delete(f"/api/annotations/{annotation_id}")
    assert delete_resp.status_code == 200

    session_after_delete = client.get("/api/session").json()
    assert session_after_delete["checked_out_version_id"] == root_version_id
    assert script_path.read_text() == _script_code(color="steelblue")
    assert all(
        ann["id"] != annotation_id for ann in session_after_delete["annotations"]
    )
    assert len(session_after_delete["versions"]) == 1


def test_annotating_old_version_creates_new_branch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    _write_script(script_path, color="steelblue")

    result = init_session_from_script(script_path)
    assert result.success

    client = TestClient(create_app())

    session0 = client.get("/api/session").json()
    main_branch_id = session0["active_branch_id"]
    root_version_id = session0["checked_out_version_id"]

    add_main_resp = client.post(
        "/api/annotations",
        json={"feedback": "increase contrast", "region": _new_region()},
    )
    assert add_main_resp.status_code == 200
    main_annotation_id = add_main_resp.json()["id"]

    submit_main_resp = client.post(
        "/api/script",
        json={"code": _script_code(color="black"), "annotation_id": main_annotation_id},
    )
    assert submit_main_resp.status_code == 200
    main_version_id = submit_main_resp.json()["version_id"]

    checkout_root_resp = client.post(
        "/api/checkout",
        json={"version_id": root_version_id, "branch_id": main_branch_id},
    )
    assert checkout_root_resp.status_code == 200

    add_branch_resp = client.post(
        "/api/annotations",
        json={"feedback": "use a red line", "region": _new_region()},
    )
    assert add_branch_resp.status_code == 200
    branch_annotation_id = add_branch_resp.json()["id"]

    session_after_branch_annotation = client.get("/api/session").json()
    assert len(session_after_branch_annotation["branches"]) == 2
    new_branch_id = session_after_branch_annotation["active_branch_id"]
    assert new_branch_id != main_branch_id

    submit_branch_resp = client.post(
        "/api/script",
        json={
            "code": _script_code(color="crimson"),
            "annotation_id": branch_annotation_id,
        },
    )
    assert submit_branch_resp.status_code == 200
    branch_version_id = submit_branch_resp.json()["version_id"]

    session_final = client.get("/api/session").json()
    main_branch = next(
        branch for branch in session_final["branches"] if branch["id"] == main_branch_id
    )
    new_branch = next(
        branch for branch in session_final["branches"] if branch["id"] == new_branch_id
    )

    assert main_branch["head_version_id"] == main_version_id
    assert new_branch["head_version_id"] == branch_version_id

    branch_version = next(
        version
        for version in session_final["versions"]
        if version["id"] == branch_version_id
    )
    assert branch_version["parent_version_id"] == root_version_id


def test_branch_name_can_be_edited(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    _write_script(script_path, color="steelblue")

    result = init_session_from_script(script_path)
    assert result.success

    client = TestClient(create_app())

    session0 = client.get("/api/session").json()
    main_branch_id = session0["active_branch_id"]
    root_version_id = session0["checked_out_version_id"]

    add_main_resp = client.post(
        "/api/annotations",
        json={"feedback": "increase contrast", "region": _new_region()},
    )
    assert add_main_resp.status_code == 200
    main_annotation_id = add_main_resp.json()["id"]

    submit_main_resp = client.post(
        "/api/script",
        json={"code": _script_code(color="black"), "annotation_id": main_annotation_id},
    )
    assert submit_main_resp.status_code == 200

    checkout_root_resp = client.post(
        "/api/checkout",
        json={"version_id": root_version_id, "branch_id": main_branch_id},
    )
    assert checkout_root_resp.status_code == 200

    add_branch_resp = client.post(
        "/api/annotations",
        json={"feedback": "use a red line", "region": _new_region()},
    )
    assert add_branch_resp.status_code == 200

    branch_session = client.get("/api/session").json()
    branch_id = branch_session["active_branch_id"]
    assert branch_id != main_branch_id

    rename_resp = client.patch(
        f"/api/branches/{branch_id}",
        json={"name": "contrast-pass"},
    )
    assert rename_resp.status_code == 200
    assert rename_resp.json()["branch"]["name"] == "contrast-pass"

    refreshed_session = client.get("/api/session").json()
    renamed_branch = next(
        branch for branch in refreshed_session["branches"] if branch["id"] == branch_id
    )
    assert renamed_branch["name"] == "contrast-pass"

    duplicate_resp = client.patch(
        f"/api/branches/{branch_id}",
        json={"name": "main"},
    )
    assert duplicate_resp.status_code == 409

    with TestClient(create_app()) as restarted_client:
        restarted_session = restarted_client.get("/api/session").json()
        restarted_branch = next(
            branch
            for branch in restarted_session["branches"]
            if branch["id"] == branch_id
        )
        assert restarted_branch["name"] == "contrast-pass"


def test_branch_rename_updates_injected_runtime_fix_jobs_only(tmp_path: Path) -> None:
    runtime = build_test_runtime(store_root=tmp_path / "isolated-state")
    shared_runtime = get_shared_runtime()
    shared_runtime.store.fix_jobs.clear()

    script_path = tmp_path / "plot.py"
    _write_script(script_path, color="steelblue")
    assert init_session_from_script(script_path, runtime=runtime).success
    session = runtime.store.active_session
    assert session is not None
    branch_id = session.active_branch_id
    assert branch_id is not None

    job = FixJob(
        model="openai/gpt-5.3-codex",
        session_id=session.id,
        workspace_dir=str(tmp_path),
        branch_id=branch_id,
        branch_name="main",
    )
    runtime.store.fix_jobs[job.id] = job

    with TestClient(server.create_app(runtime=runtime)) as client:
        response = client.patch(
            f"/api/branches/{branch_id}",
            json={"name": "runtime-branch"},
        )
        assert response.status_code == 200
        assert runtime.store.fix_jobs[job.id].branch_name == "runtime-branch"

    assert shared_runtime.store.fix_jobs == {}


def test_versioning_router_delegates_submit_script_to_service(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    versioning_service = importlib.import_module("openplot.services.versioning")

    called: dict[str, object] = {}

    async def fake_submit_script(body, *, session_id=None):
        called["code"] = body.code
        called["session_id"] = session_id
        return {"status": "ok", "version_id": "version-delegated"}

    monkeypatch.setattr(versioning_service, "submit_script", fake_submit_script)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/script",
            json={"code": "print('delegated')", "annotation_id": "annotation-1"},
            params={"session_id": "session-1"},
        )

    assert response.status_code == 200
    assert response.json()["version_id"] == "version-delegated"
    assert called["code"] == "print('delegated')"
    assert called["session_id"] == "session-1"


def test_annotations_router_delegates_update_to_service(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    annotations_service = importlib.import_module("openplot.services.annotations")

    called: dict[str, object] = {}

    async def fake_update_annotation(annotation_id, updates):
        called["annotation_id"] = annotation_id
        called["feedback"] = updates.feedback
        return {"status": "ok"}

    monkeypatch.setattr(
        annotations_service, "update_annotation", fake_update_annotation
    )

    with TestClient(create_app()) as client:
        response = client.patch(
            "/api/annotations/annotation-1",
            json={"feedback": "delegated"},
        )

    assert response.status_code == 200
    assert called["annotation_id"] == "annotation-1"
    assert called["feedback"] == "delegated"


def test_script_revision_checkout_and_branch_endpoints_round_trip(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    _write_script(script_path, color="steelblue")

    result = init_session_from_script(script_path)
    assert result.success

    with TestClient(create_app()) as client:
        session0 = client.get("/api/session").json()
        main_branch_id = session0["active_branch_id"]
        root_version_id = session0["checked_out_version_id"]

        add_resp = client.post(
            "/api/annotations",
            json={"feedback": "increase contrast", "region": _new_region()},
        )
        assert add_resp.status_code == 200
        annotation_id = add_resp.json()["id"]

        submit_resp = client.post(
            "/api/script",
            json={"code": _script_code(color="black"), "annotation_id": annotation_id},
        )
        assert submit_resp.status_code == 200
        main_version_id = submit_resp.json()["version_id"]

        revisions_resp = client.get("/api/revisions")
        assert revisions_resp.status_code == 200
        revisions = revisions_resp.json()
        assert len(revisions) == 2
        assert revisions[0]["script"] == _script_code(color="steelblue")
        assert revisions[1]["script"] == _script_code(color="black")

        checkout_root_resp = client.post(
            "/api/checkout",
            json={"version_id": root_version_id, "branch_id": main_branch_id},
        )
        assert checkout_root_resp.status_code == 200

        branch_annotation_resp = client.post(
            "/api/annotations",
            json={"feedback": "use a red line", "region": _new_region()},
        )
        assert branch_annotation_resp.status_code == 200

        branch_session = client.get("/api/session").json()
        branch_id = branch_session["active_branch_id"]
        assert branch_id != main_branch_id

        rename_resp = client.patch(
            f"/api/branches/{branch_id}",
            json={"name": "contrast-pass"},
        )
        assert rename_resp.status_code == 200
        assert rename_resp.json()["branch"]["name"] == "contrast-pass"

        checkout_main_branch_resp = client.post(
            f"/api/branches/{main_branch_id}/checkout"
        )
        assert checkout_main_branch_resp.status_code == 200
        assert checkout_main_branch_resp.json()["branch_id"] == main_branch_id

        refreshed_session = client.get("/api/session").json()
        renamed_branch = next(
            branch
            for branch in refreshed_session["branches"]
            if branch["id"] == branch_id
        )
        assert renamed_branch["name"] == "contrast-pass"
        assert refreshed_session["active_branch_id"] == main_branch_id
        assert refreshed_session["checked_out_version_id"] == main_version_id


def test_annotation_status_is_system_managed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    _write_script(script_path, color="steelblue")

    result = init_session_from_script(script_path)
    assert result.success

    client = TestClient(create_app())

    add_resp = client.post(
        "/api/annotations",
        json={
            "feedback": "do not allow manual status toggles",
            "region": _new_region(),
        },
    )
    assert add_resp.status_code == 200
    annotation_id = add_resp.json()["id"]

    patch_resp = client.patch(
        f"/api/annotations/{annotation_id}",
        json={"status": "addressed"},
    )
    assert patch_resp.status_code == 400

    session = client.get("/api/session").json()
    ann = next(a for a in session["annotations"] if a["id"] == annotation_id)
    assert ann["status"] == "pending"


def test_submit_without_target_uses_fifo_pending_order(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    _write_script(script_path, color="steelblue")

    result = init_session_from_script(script_path)
    assert result.success

    client = TestClient(create_app())
    main_branch_id = client.get("/api/session").json()["active_branch_id"]

    first_resp = client.post(
        "/api/annotations",
        json={"feedback": "first", "region": _new_region()},
    )
    second_resp = client.post(
        "/api/annotations",
        json={"feedback": "second", "region": _new_region()},
    )
    assert first_resp.status_code == 200
    assert second_resp.status_code == 200

    first_id = first_resp.json()["id"]
    second_id = second_resp.json()["id"]

    submit_first = client.post(
        "/api/script",
        json={"code": _script_code(color="black"), "annotation_id": first_id},
    )
    assert submit_first.status_code == 200
    first_version_id = submit_first.json()["version_id"]

    third_resp = client.post(
        "/api/annotations",
        json={"feedback": "third-latest", "region": _new_region()},
    )
    assert third_resp.status_code == 200
    third_id = third_resp.json()["id"]

    submit_auto = client.post(
        "/api/script",
        json={"code": _script_code(color="crimson")},
    )
    assert submit_auto.status_code == 200
    assert submit_auto.json()["addressed_annotation_id"] == second_id
    second_version_id = submit_auto.json()["version_id"]

    session = client.get("/api/session").json()
    by_id = {ann["id"]: ann for ann in session["annotations"]}
    assert by_id[first_id]["status"] == "addressed"
    assert by_id[second_id]["status"] == "addressed"
    assert by_id[third_id]["status"] == "pending"

    assert by_id[first_id]["addressed_in_version_id"] == first_version_id
    assert by_id[second_id]["addressed_in_version_id"] == second_version_id

    assert len(session["branches"]) == 1
    branch = session["branches"][0]
    assert branch["id"] == main_branch_id
    assert branch["head_version_id"] == second_version_id

    by_version_id = {version["id"]: version for version in session["versions"]}
    assert by_version_id[second_version_id]["parent_version_id"] == first_version_id


def test_export_only_allows_addressed_annotations(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    _write_script(script_path, color="steelblue")

    result = init_session_from_script(script_path)
    assert result.success

    client = TestClient(create_app())

    addressed_resp = client.post(
        "/api/annotations",
        json={"feedback": "addressed annotation", "region": _new_region()},
    )
    pending_resp = client.post(
        "/api/annotations",
        json={"feedback": "pending annotation", "region": _new_region()},
    )
    assert addressed_resp.status_code == 200
    assert pending_resp.status_code == 200

    addressed_id = addressed_resp.json()["id"]
    pending_id = pending_resp.json()["id"]

    submit_resp = client.post(
        "/api/script",
        json={"code": _script_code(color="black"), "annotation_id": addressed_id},
    )
    assert submit_resp.status_code == 200

    export_addressed = client.get(f"/api/annotations/{addressed_id}/export")
    assert export_addressed.status_code == 200
    assert export_addressed.content
    disposition = export_addressed.headers.get("content-disposition", "")
    assert "filename=" in disposition
    assert ".zip" in disposition

    with zipfile.ZipFile(io.BytesIO(export_addressed.content)) as archive:
        names = set(archive.namelist())
    assert "script.py" in names
    assert any(name.startswith("plot") for name in names)

    export_pending = client.get(f"/api/annotations/{pending_id}/export")
    assert export_pending.status_code == 409
