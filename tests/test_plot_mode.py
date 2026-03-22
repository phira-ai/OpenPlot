from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

import openplot.server as server
from openplot.executor import ExecutionResult


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


def _create_persisted_plot_workspace(
    workspace_dir: Path,
    *,
    plot_bytes: bytes | None = None,
    question_set: server.PlotModeQuestionSet | None = None,
    phase: server.PlotModePhase | None = None,
) -> server.PlotModeState:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    state = server.init_plot_mode_session(
        workspace_dir=workspace_dir,
        persist_workspace=True,
    )
    if plot_bytes is not None:
        plot_path = workspace_dir / "captures" / "preview.png"
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        plot_path.write_bytes(plot_bytes)
        state.current_plot = str(plot_path)
        state.plot_type = "raster"
    if question_set is not None:
        state.pending_question_set = question_set
    if phase is not None:
        state.phase = phase
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


def test_bootstrap_without_session_defaults_to_plot_mode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")

    with TestClient(server.create_app()) as client:
        response = client.get("/api/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "plot"
    assert payload["session"] is None
    assert payload["plot_mode"] is not None
    assert payload["plot_mode"]["phase"] == "awaiting_files"


def test_plot_mode_path_suggestions_filter_data_and_scripts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    (workspace / "inputs").mkdir(parents=True, exist_ok=True)
    (workspace / "data.csv").write_text("x,y\n1,2\n")
    (workspace / "plot.py").write_text(_script_code())

    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        query = f"{workspace.as_posix()}/"

        data_response = client.post(
            "/api/plot-mode/path-suggestions",
            json={"selection_type": "data", "query": query},
        )
        script_response = client.post(
            "/api/plot-mode/path-suggestions",
            json={"selection_type": "script", "query": query},
        )

    assert data_response.status_code == 200
    assert script_response.status_code == 200

    data_suggestions = {
        Path(item["path"]).name: item for item in data_response.json()["suggestions"]
    }
    script_suggestions = {
        Path(item["path"]).name: item for item in script_response.json()["suggestions"]
    }

    assert "inputs" in data_suggestions
    assert "data.csv" in data_suggestions
    assert "plot.py" not in data_suggestions

    assert "inputs" in script_suggestions
    assert "plot.py" in script_suggestions
    assert "data.csv" not in script_suggestions


def test_plot_mode_activate_updates_picker_root_to_target_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    (workspace_a / "alpha.csv").parent.mkdir(parents=True, exist_ok=True)
    (workspace_a / "alpha.csv").write_text("x,y\n1,2\n")
    (workspace_b / "beta.csv").parent.mkdir(parents=True, exist_ok=True)
    (workspace_b / "beta.csv").write_text("x,y\n3,4\n")

    state_a = _create_persisted_plot_workspace(workspace_a)
    state_b = _create_persisted_plot_workspace(workspace_b)

    with TestClient(server.create_app()) as client:
        activate_response = client.post(
            "/api/plot-mode/activate",
            json={"id": state_a.id},
        )
        assert activate_response.status_code == 200

        suggestions_response = client.post(
            "/api/plot-mode/path-suggestions",
            json={"selection_type": "data", "query": ""},
        )

    assert suggestions_response.status_code == 200
    payload = suggestions_response.json()
    assert payload["base_dir"] == str(workspace_a.resolve())
    suggested_names = {Path(item["path"]).name for item in payload["suggestions"]}
    assert "alpha.csv" in suggested_names
    assert "beta.csv" not in suggested_names
    assert state_b.id != state_a.id


def test_plot_mode_empty_query_defaults_to_home_for_fresh_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / "sample.csv").write_text("x,y\n1,2\n")
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    server.init_plot_mode_session()

    with TestClient(server.create_app()) as client:
        response = client.post(
            "/api/plot-mode/path-suggestions",
            json={"selection_type": "data", "query": ""},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_dir"] == str(home_dir.resolve())
    suggested_names = {Path(item["path"]).name for item in payload["suggestions"]}
    assert "sample.csv" in suggested_names


def test_plot_mode_relative_paths_resolve_from_home_for_fresh_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    data_path = home_dir / "dataset.csv"
    data_path.write_text("x,y\n1,2\n")
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    server.init_plot_mode_session()

    with TestClient(server.create_app()) as client:
        response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": ["dataset.csv"]},
        )

    assert response.status_code == 200
    payload = response.json()["plot_mode"]
    assert payload["files"][0]["stored_path"] == str(data_path.resolve())


def test_plot_mode_tilde_query_uses_home_directory_across_platforms(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / "chart.py").write_text(_script_code())
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    server.init_plot_mode_session()

    with TestClient(server.create_app()) as client:
        response = client.post(
            "/api/plot-mode/path-suggestions",
            json={"selection_type": "script", "query": "~/"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_dir"] == str(home_dir.resolve())
    suggested_names = {Path(item["path"]).name for item in payload["suggestions"]}
    assert "chart.py" in suggested_names


class _ChunkedTextReader:
    def __init__(self, payload: str):
        self._payload = payload.encode("utf-8")
        self._offset = 0

    async def read(self, n: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        if n <= 0:
            n = len(self._payload) - self._offset
        start = self._offset
        end = min(len(self._payload), start + n)
        self._offset = end
        return self._payload[start:end]


class _FakeProcess:
    def __init__(self, *, stdout_text: str, stderr_text: str = "", returncode: int = 0):
        self.stdout = _ChunkedTextReader(stdout_text)
        self.stderr = _ChunkedTextReader(stderr_text)
        self.returncode = returncode
        self.pid = 0

    async def wait(self) -> int:
        return self.returncode


@pytest.mark.anyio
async def test_run_plot_mode_runner_prompt_retries_after_builtin_question_tool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(server, "_resolve_claude_cli_command", lambda: "claude")

    state = server.init_plot_mode_session(workspace_dir=tmp_path)
    state.runner_session_ids["claude"] = "resume-123"
    question_tool_line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "AskUserQuestion",
                        "input": {
                            "questions": [
                                {
                                    "question": "Which mode?",
                                    "header": "Mode",
                                    "multiSelect": False,
                                    "options": [
                                        {"label": "A", "description": "a"},
                                        {"label": "B", "description": "b"},
                                    ],
                                }
                            ]
                        },
                    }
                ]
            },
        }
    )

    commands: list[list[str]] = []
    processes = [
        _FakeProcess(
            stdout_text=f"{question_tool_line}\n",
            returncode=1,
        ),
        _FakeProcess(stdout_text="done\n", returncode=0),
    ]

    async def fake_create_subprocess_exec(*command, **kwargs):
        _ = kwargs
        commands.append(list(command))
        return processes.pop(0)

    cleared_sessions: list[str] = []

    monkeypatch.setattr(
        server.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )
    monkeypatch.setattr(
        server,
        "_clear_runner_session_id_for_plot_mode",
        lambda _state, _runner: cleared_sessions.append(_runner),
    )

    assistant_text, runner_error = await server._run_plot_mode_runner_prompt(
        state=state,
        runner="claude",
        prompt="Plan the next plot step.",
        model="claude-sonnet-4-6",
        variant="high",
    )

    assert runner_error is None
    assert assistant_text == "done"
    assert len(commands) == 2
    assert "--resume" in commands[0]
    assert "--resume" not in commands[1]
    assert cleared_sessions == ["claude"]
    assert "--disallowedTools" in commands[1]
    assert "AskUserQuestion" in commands[1]
    assert "Do not use AskUserQuestion" in commands[1][2]


@pytest.mark.anyio
async def test_run_plot_mode_runner_prompt_passes_opencode_question_disable_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(server, "_resolve_command_path", lambda command: command)

    state = server.init_plot_mode_session(workspace_dir=tmp_path)
    captured_env: dict[str, str] = {}

    async def fake_create_subprocess_exec(*command, **kwargs):
        _ = command
        captured_env.update(kwargs["env"])
        return _FakeProcess(stdout_text="plain text response\n", returncode=0)

    monkeypatch.setattr(
        server.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )

    assistant_text, runner_error = await server._run_plot_mode_runner_prompt(
        state=state,
        runner="opencode",
        prompt="Plan the next plot step.",
        model="openai/gpt-5.3-codex",
        variant="high",
    )

    assert runner_error is None
    assert assistant_text == "plain text response"
    assert "OPENCODE_CONFIG_CONTENT" in captured_env
    assert json.loads(captured_env["OPENCODE_CONFIG_CONTENT"]) == {
        "$schema": "https://opencode.ai/config.json",
        "permission": {"question": "deny"},
    }


def test_plot_mode_answer_targets_requested_workspace_when_another_is_active(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"

    question_set_a = server.PlotModeQuestionSet(
        purpose="continue_plot_planning",
        title="Continue planning",
        questions=[
            server.PlotModeQuestionItem(
                prompt="Should I keep planning?",
                options=[
                    server.PlotModeQuestionOption(
                        id="continue_planning",
                        label="Continue",
                    ),
                    server.PlotModeQuestionOption(
                        id="revise_goal",
                        label="Revise goal",
                    ),
                ],
            )
        ],
    )
    question_set_b = server.PlotModeQuestionSet(
        purpose="continue_plot_planning",
        title="Continue planning",
        questions=[
            server.PlotModeQuestionItem(
                prompt="Keep going?",
                options=[
                    server.PlotModeQuestionOption(
                        id="continue_planning",
                        label="Continue",
                    )
                ],
            )
        ],
    )

    state_a = _create_persisted_plot_workspace(
        workspace_a,
        question_set=question_set_a,
        phase=server.PlotModePhase.awaiting_plan_approval,
    )
    _create_persisted_plot_workspace(
        workspace_b,
        question_set=question_set_b,
        phase=server.PlotModePhase.awaiting_plan_approval,
    )

    with TestClient(server.create_app()) as client:
        response = client.post(
            "/api/plot-mode/answer",
            json={
                "workspace_id": state_a.id,
                "question_set_id": question_set_a.id,
                "answers": [
                    {
                        "question_id": question_set_a.questions[0].id,
                        "option_ids": ["revise_goal"],
                    }
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()["plot_mode"]
    assert payload["id"] == state_a.id
    assert payload["phase"] == "awaiting_prompt"
    assert payload["pending_question_set"] is None


def test_plot_mode_preview_uses_requested_workspace_instead_of_active_plot_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    state_a = _create_persisted_plot_workspace(workspace_a, plot_bytes=b"plot-a")
    _create_persisted_plot_workspace(workspace_b, plot_bytes=b"plot-b")

    with TestClient(server.create_app()) as client:
        response = client.get(
            "/api/plot",
            params={"plot_mode": "1", "workspace_id": state_a.id},
        )

    assert response.status_code == 200
    assert response.content == b"plot-a"


def test_plot_mode_script_path_selection_transitions_to_annotation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    script_path = workspace / "plot.py"
    script_path.write_text(_script_code())

    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        response = client.post(
            "/api/plot-mode/select-paths",
            json={
                "selection_type": "script",
                "paths": [str(script_path)],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "annotation"
    assert payload["session"] is not None
    assert payload["plot_mode"] is None
    assert payload["session"]["source_script_path"] == str(script_path)

    versions = payload["session"]["versions"]
    assert len(versions) == 1
    script_artifact_path = versions[0]["script_artifact_path"]
    assert script_artifact_path is not None
    assert Path(script_artifact_path).exists()


def test_plot_mode_data_path_selection_keeps_original_local_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_path = workspace / "data.csv"
    data_path.write_text("x,y\n1,2\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        response = client.post(
            "/api/plot-mode/select-paths",
            json={
                "selection_type": "data",
                "paths": [str(data_path)],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "plot"
    selected_file = payload["plot_mode"]["files"][0]
    stored_path = Path(selected_file["stored_path"]).resolve()
    expected_state_root = (tmp_path / "state" / "openplot").resolve()

    assert stored_path == data_path.resolve()
    assert expected_state_root not in stored_path.parents


def test_plot_mode_single_csv_preview_is_not_duplicated(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_path = workspace / "data.csv"
    data_path.write_text("x,y\n1,2\n3,4\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        response = client.post(
            "/api/plot-mode/select-paths",
            json={
                "selection_type": "data",
                "paths": [str(data_path)],
            },
        )

    assert response.status_code == 200
    payload = response.json()["plot_mode"]
    table_previews = [
        message
        for message in payload["messages"]
        if (message.get("metadata") or {}).get("kind") == "table_preview"
    ]
    assert len(table_previews) == 1


def test_plot_mode_rejects_adding_more_files_after_initial_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    first_data_path = workspace / "data.csv"
    second_data_path = workspace / "more-data.csv"
    first_data_path.write_text("x,y\n1,2\n")
    second_data_path.write_text("x,y\n3,4\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        first_response = client.post(
            "/api/plot-mode/select-paths",
            json={
                "selection_type": "data",
                "paths": [str(first_data_path)],
            },
        )
        second_response = client.post(
            "/api/plot-mode/select-paths",
            json={
                "selection_type": "data",
                "paths": [str(second_data_path)],
            },
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["detail"] == (
        "No more files can be added to this workspace. Use New workspace to start over."
    )


def test_plot_mode_multi_csv_bundle_resolves_to_a_combined_bundle_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    paths = [
        workspace / "first.csv",
        workspace / "second.csv",
        workspace / "third.csv",
        workspace / "fourth.csv",
    ]
    for index, path in enumerate(paths, start=1):
        path.write_text(f"x,y\n{index},{index + 1}\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(path) for path in paths]},
        )

    assert response.status_code == 200
    plot_mode = response.json()["plot_mode"]
    assert plot_mode["phase"] == "awaiting_data_choice"
    assert plot_mode["pending_question_set"] is not None
    assert plot_mode["pending_question_set"]["purpose"] == "kickoff_plot_planning"
    assert (
        plot_mode["pending_question_set"]["questions"][0]["options"][0]["id"]
        == "proceed_to_planning"
    )
    assert plot_mode["selected_data_profile_id"] is None
    table_previews = [
        message
        for message in plot_mode["messages"]
        if (message.get("metadata") or {}).get("kind") == "table_preview"
    ]
    assert len(table_previews) == 4
    assert plot_mode["input_bundle"] is not None
    assert plot_mode["input_bundle"]["file_count"] == 4
    assert len(plot_mode["resolved_sources"]) == 1
    resolved_source = plot_mode["resolved_sources"][0]
    assert resolved_source["kind"] == "multi_file_collection"
    assert resolved_source["file_count"] == 4
    assert resolved_source["file_ids"] == plot_mode["input_bundle"]["file_ids"]
    assert plot_mode["active_resolved_source_ids"] == [resolved_source["id"]]


def test_plot_mode_multi_csv_bundle_tolerates_reordered_headers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    first = workspace / "first.csv"
    second = workspace / "second.csv"
    first.write_text("x,y\n1,2\n")
    second.write_text("y,x\n3,2\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(first), str(second)]},
        )

    assert response.status_code == 200
    plot_mode = response.json()["plot_mode"]
    assert plot_mode["phase"] == "awaiting_data_choice"
    assert plot_mode["pending_question_set"] is not None
    assert plot_mode["pending_question_set"]["purpose"] == "kickoff_plot_planning"
    assert len(plot_mode["resolved_sources"]) == 1
    assert plot_mode["resolved_sources"][0]["kind"] == "multi_file_collection"


def test_plot_mode_chat_accepts_a_combined_multi_file_bundle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    first = workspace / "first.csv"
    second = workspace / "second.csv"
    first.write_text("x,y\n1,2\n")
    second.write_text("x,y\n2,3\n")

    seen: dict[str, object] = {}

    async def _fake_planning(
        *,
        state,
        runner,
        user_message,
        model,
        variant,
    ):
        _ = (runner, model, variant)
        seen["message"] = user_message
        seen["selected_data_profile_id"] = state.selected_data_profile_id
        seen["active_resolved_source_ids"] = list(state.active_resolved_source_ids)
        return server.PlotModePlanResult(
            assistant_text="I inspected the multi-file dataset and prepared a plan.",
            summary="I can compare the two CSV files as separate series.",
            plot_type="line chart",
            plan_outline=["Compare the files as separate lines on one chart."],
            data_actions=["Inspect both CSV files and align their shared columns."],
            ready_to_plot=False,
        )

    monkeypatch.setattr(server, "_run_plot_mode_planning", _fake_planning)
    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(first), str(second)]},
        )
        assert select_response.status_code == 200
        kickoff_question = select_response.json()["plot_mode"]["pending_question_set"]

        answer_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": kickoff_question["id"],
                "answers": [
                    {
                        "question_id": kickoff_question["questions"][0]["id"],
                        "text": "Compare both files as two lines.",
                    }
                ],
            },
        )

    assert answer_response.status_code == 200
    assert seen["message"] == "Compare both files as two lines."
    assert seen["selected_data_profile_id"] is None
    assert len(cast(list[str], seen["active_resolved_source_ids"])) == 1
    payload = answer_response.json()["plot_mode"]
    assert payload["latest_user_goal"] == "Compare both files as two lines."
    question_messages = [
        message
        for message in payload["messages"]
        if (message.get("metadata") or {}).get("kind") == "question"
    ]
    assert question_messages
    assert question_messages[-1]["metadata"]["questions"][0]["answered"] is True
    assert question_messages[-1]["metadata"]["questions"][0]["answer_text"] == (
        "Compare both files as two lines."
    )
    user_messages = [
        message["content"]
        for message in payload["messages"]
        if message["role"] == "user"
    ]
    assert user_messages == ["Compare both files as two lines."]


def test_plot_mode_kickoff_answer_proceeds_to_planning_for_bundle_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    first = workspace / "first.csv"
    second = workspace / "second.csv"
    first.write_text("x,y\n1,2\n")
    second.write_text("x,y\n2,3\n")

    seen: dict[str, object] = {}

    async def _fake_planning(
        *,
        state,
        runner,
        user_message,
        model,
        variant,
    ):
        _ = (runner, model, variant)
        seen["message"] = user_message
        seen["selected_data_profile_id"] = state.selected_data_profile_id
        seen["active_resolved_source_ids"] = list(state.active_resolved_source_ids)
        return server.PlotModePlanResult(
            assistant_text="I inspected the source bundle and prepared a plan.",
            summary="I can compare the files as separate series.",
            plot_type="line chart",
            plan_outline=["Compare the files as separate lines on one chart."],
            data_actions=["Inspect both CSV files and align their shared columns."],
            ready_to_plot=False,
            clarification_question="Should I refine the comparison before drafting?",
        )

    monkeypatch.setattr(server, "_run_plot_mode_planning", _fake_planning)
    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(first), str(second)]},
        )
        assert select_response.status_code == 200
        kickoff_question = select_response.json()["plot_mode"]["pending_question_set"]

        answer_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": kickoff_question["id"],
                "answers": [
                    {
                        "question_id": kickoff_question["questions"][0]["id"],
                        "option_ids": ["proceed_to_planning"],
                    }
                ],
            },
        )

    assert answer_response.status_code == 200
    assert seen["message"] == "Proceed to plot planning."
    assert seen["selected_data_profile_id"] is None
    assert len(cast(list[str], seen["active_resolved_source_ids"])) == 1
    payload = answer_response.json()["plot_mode"]
    assert payload["phase"] == "awaiting_data_choice"
    assert payload["pending_question_set"]["purpose"] == "continue_plot_planning"
    assert payload["latest_user_goal"] == "Proceed to plot planning."
    question_messages = [
        message
        for message in payload["messages"]
        if (message.get("metadata") or {}).get("kind") == "question"
    ]
    assert question_messages
    assert question_messages[0]["metadata"]["questions"][0]["answered"] is True
    user_messages = [
        message["content"]
        for message in payload["messages"]
        if message["role"] == "user"
    ]
    assert user_messages == ["Proceed to plot planning."]


def test_plot_mode_kickoff_answer_requires_proceed_or_guidance(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    first = workspace / "first.csv"
    second = workspace / "second.csv"
    first.write_text("x,y\n1,2\n")
    second.write_text("x,y\n2,3\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(first), str(second)]},
        )
        assert select_response.status_code == 200
        kickoff_question = select_response.json()["plot_mode"]["pending_question_set"]

        answer_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": kickoff_question["id"],
                "answers": [
                    {
                        "question_id": kickoff_question["questions"][0]["id"],
                        "option_ids": [],
                        "text": "   ",
                    }
                ],
            },
        )

    assert answer_response.status_code == 400
    assert answer_response.json()["detail"] == (
        "Choose whether to proceed to planning or add guidance first."
    )


def test_plot_mode_kickoff_answer_prefers_custom_guidance_over_proceed_option(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    first = workspace / "first.csv"
    second = workspace / "second.csv"
    first.write_text("x,y\n1,2\n")
    second.write_text("x,y\n2,3\n")

    seen: dict[str, object] = {}

    async def _fake_planning(
        *,
        state,
        runner,
        user_message,
        model,
        variant,
    ):
        _ = (state, runner, model, variant)
        seen["message"] = user_message
        return server.PlotModePlanResult(
            assistant_text="I refined the plot direction.",
            summary="The comparison should highlight the smaller model.",
            plot_type="line chart",
            plan_outline=["Compare both files and emphasize the smaller model."],
            data_actions=["Align shared columns before plotting."],
            ready_to_plot=False,
        )

    monkeypatch.setattr(server, "_run_plot_mode_planning", _fake_planning)
    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(first), str(second)]},
        )
        assert select_response.status_code == 200
        kickoff_question = select_response.json()["plot_mode"]["pending_question_set"]

        answer_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": kickoff_question["id"],
                "answers": [
                    {
                        "question_id": kickoff_question["questions"][0]["id"],
                        "option_ids": ["proceed_to_planning"],
                        "text": "Compare accuracy, but call out the smallest model.",
                    }
                ],
            },
        )

    assert answer_response.status_code == 200
    assert seen["message"] == "Compare accuracy, but call out the smallest model."
    payload = answer_response.json()["plot_mode"]
    assert payload["latest_user_goal"] == (
        "Compare accuracy, but call out the smallest model."
    )
    user_messages = [
        message["content"]
        for message in payload["messages"]
        if message["role"] == "user"
    ]
    assert user_messages == ["Compare accuracy, but call out the smallest model."]


def test_plot_mode_unsupported_preview_file_skips_data_confirmation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_path = workspace / "notes.txt"
    data_path.write_text("x y\n1 2\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        response = client.post(
            "/api/plot-mode/select-paths",
            json={
                "selection_type": "data",
                "paths": [str(data_path)],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "plot"
    plot_mode = payload["plot_mode"]
    assert plot_mode["phase"] == "awaiting_prompt"
    assert plot_mode["pending_question_set"] is None
    assert len(plot_mode["data_profiles"]) == 1
    profile = plot_mode["data_profiles"][0]
    assert profile["source_kind"] == "file"
    assert plot_mode["selected_data_profile_id"] == profile["id"]


def test_plot_mode_mixed_file_selection_resolves_to_a_bundle_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    csv_path = workspace / "data.csv"
    txt_path = workspace / "notes.txt"
    csv_path.write_text("x,y\n1,2\n")
    txt_path.write_text("x y\n1 2\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={
                "selection_type": "data",
                "paths": [str(csv_path), str(txt_path)],
            },
        )
        assert select_response.status_code == 200
        plot_mode = select_response.json()["plot_mode"]
        assert plot_mode["phase"] == "awaiting_data_choice"
        assert plot_mode["pending_question_set"] is not None
        assert plot_mode["pending_question_set"]["purpose"] == "kickoff_plot_planning"
        assert (
            plot_mode["pending_question_set"]["questions"][0]["options"][0]["id"]
            == "proceed_to_planning"
        )
        assert plot_mode["selected_data_profile_id"] is None
        assert len(plot_mode["resolved_sources"]) == 1
        resolved_source = plot_mode["resolved_sources"][0]
        assert resolved_source["kind"] == "mixed_bundle"
        assert resolved_source["file_count"] == 2
        assert plot_mode["active_resolved_source_ids"] == [resolved_source["id"]]


def test_plot_mode_dataset_chat_and_finalize(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    server.init_plot_mode_session(workspace_dir=workspace)

    data_path = workspace / "data.csv"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text("x,y\n1,2\n2,3\n")

    preview_plot = workspace / "captures" / "preview.png"
    preview_plot.parent.mkdir(parents=True, exist_ok=True)
    preview_plot.write_bytes(b"preview")

    generated_script = _script_code(color="crimson")

    async def _fake_planning(
        *,
        state,
        runner,
        user_message,
        model,
        variant,
    ):
        _ = (state, runner, user_message, model, variant)
        if "crimson" not in user_message:
            return server.PlotModePlanResult(
                assistant_text="I inspected the data and prepared a first pass.",
                summary="I found a clean x/y table and can draft a line chart once you confirm the visual direction.",
                plot_type="line chart",
                plan_outline=[
                    "Check the numeric columns and keep the chart focused on the x/y trend.",
                ],
                data_actions=["Read data.csv and previewed sampled rows and columns."],
                ready_to_plot=False,
            )
        return server.PlotModePlanResult(
            assistant_text="I inspected the data and prepared a plan.",
            summary="Use a clean line chart of x vs y with publication-style typography.",
            plot_type="line chart",
            plan_outline=[
                "Load the confirmed CSV source and validate numeric columns.",
                "Plot x against y with clear axis labels and balanced margins.",
            ],
            data_actions=["Read data.csv and previewed sampled rows and columns."],
            ready_to_plot=True,
        )

    async def _fake_generation(
        *,
        state,
        message,
        model,
        variant,
        runner,
        assistant_message,
    ):
        _ = assistant_message
        assistant = (
            "Generated script based on your datasets.\n\n"
            f"```python\n{generated_script}\n```"
        )
        return server.PlotModeGenerationResult(
            assistant_text=assistant,
            script=generated_script,
            execution_result=ExecutionResult(
                success=True,
                plot_path=str(preview_plot),
                plot_type="raster",
            ),
        )

    monkeypatch.setattr(server, "_run_plot_mode_planning", _fake_planning)
    monkeypatch.setattr(server, "_run_plot_mode_generation", _fake_generation)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(data_path)]},
        )
        assert select_response.status_code == 200
        assert select_response.json()["mode"] == "plot"
        assert select_response.json()["session"] is None
        select_plot_mode = select_response.json()["plot_mode"]
        assert select_plot_mode["phase"] == "awaiting_data_choice"
        preview_question_id = select_plot_mode["pending_question_set"]["id"]

        preview_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": preview_question_id,
                "answers": [
                    {
                        "question_id": select_plot_mode["pending_question_set"][
                            "questions"
                        ][0]["id"],
                        "option_ids": ["use_preview"],
                    }
                ],
            },
        )
        assert preview_response.status_code == 200
        assert preview_response.json()["plot_mode"]["phase"] == "awaiting_prompt"

        chat_response = client.post(
            "/api/plot-mode/chat",
            json={"message": "Plot x vs y with a crimson line."},
        )
        assert chat_response.status_code == 200
        chat_payload = chat_response.json()
        assert chat_payload["status"] == "ok"
        assert chat_payload["plot_mode"]["phase"] == "awaiting_plan_approval"
        assert chat_payload["plot_mode"]["current_plot"] is None
        assert chat_payload["plot_mode"]["current_script"] is None
        pending_question = chat_payload["plot_mode"]["pending_question_set"]
        assert pending_question is not None

        approve_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": pending_question["id"],
                "answers": [
                    {
                        "question_id": pending_question["questions"][0]["id"],
                        "option_ids": ["start_draft"],
                    }
                ],
            },
        )
        assert approve_response.status_code == 200
        approve_payload = approve_response.json()
        assert approve_payload["status"] == "ok"
        assert approve_payload["plot_mode"]["current_plot"] == str(preview_plot)
        assert approve_payload["plot_mode"]["current_script"] == generated_script

        plot_response = client.get("/api/plot")
        assert plot_response.status_code == 200

        finalize_response = client.post("/api/plot-mode/finalize", json={})
        assert finalize_response.status_code == 200
        finalize_payload = finalize_response.json()
        assert finalize_payload["mode"] == "annotation"
        assert finalize_payload["plot_mode"] is None
        assert [
            line
            for line in str(finalize_payload["session"]["source_script"])
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .split("\n")
            if line.strip()
        ] == [line for line in generated_script.split("\n") if line.strip()]


def test_plot_mode_file_upload_endpoint_is_gone(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")

    with TestClient(server.create_app()) as client:
        response = client.post("/api/plot-mode/files")

    assert response.status_code == 410


def test_finalize_plot_mode_creates_independent_annotation_session_in_shared_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    state = server.init_plot_mode_session(
        workspace_dir=workspace, persist_workspace=True
    )
    state.current_script = _script_code(color="teal")
    state.runner_session_ids = {
        "claude": "b567aeb3-28e7-4d60-bad5-56498bcac9ce",
        "codex": "019ce234-1eaa-7151-9a2c-a98071f65579",
    }
    server._touch_plot_mode(state)

    with TestClient(server.create_app()) as client:
        response = client.post("/api/plot-mode/finalize", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "annotation"
    assert payload["session"]["id"] != state.id
    assert payload["session"]["workspace_id"] == state.id
    assert payload["active_session_id"] == payload["session"]["id"]
    assert payload["active_workspace_id"] == state.id
    assert payload["session"]["runner_session_ids"] == {}
    assert payload["session"]["artifacts_root"] == str(
        server._plot_mode_artifacts_dir(state).resolve()
    )
    matching = [entry for entry in payload["sessions"] if entry["id"] == state.id]
    assert len(matching) == 1
    assert matching[0]["workspace_mode"] == "annotation"
    assert matching[0]["session_id"] == payload["session"]["id"]


def test_plot_mode_workspace_persists_across_restart_after_draft(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    server.init_plot_mode_session(workspace_dir=workspace)

    data_path = workspace / "data.csv"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text("x,y\n1,2\n2,3\n")

    preview_plot = workspace / "captures" / "preview.png"
    preview_plot.parent.mkdir(parents=True, exist_ok=True)
    preview_plot.write_bytes(b"preview")

    generated_script = _script_code(color="darkorange")

    async def _fake_planning(
        *,
        state,
        runner,
        user_message,
        model,
        variant,
    ):
        _ = (state, runner, user_message, model, variant)
        if "dark orange" not in user_message:
            return server.PlotModePlanResult(
                assistant_text="I prepared a first-pass plan.",
                summary="I can keep refining the chart direction before drafting.",
                plot_type="line chart",
                plan_outline=["Confirm the desired visual treatment before drafting."],
                data_actions=["Inspect the selected x/y table."],
                ready_to_plot=False,
            )
        return server.PlotModePlanResult(
            assistant_text="I prepared a line chart draft plan.",
            summary="I can draft a line chart from the selected x/y columns.",
            plot_type="line chart",
            plan_outline=["Use the selected table and render a clean line chart."],
            data_actions=["Confirm the source, then draft the first pass."],
            ready_to_plot=True,
        )

    async def _fake_generation(
        *,
        state,
        message,
        model,
        variant,
        runner,
        assistant_message,
    ):
        _ = (state, message, model, variant, runner, assistant_message)
        return server.PlotModeGenerationResult(
            assistant_text="Generated a polished first draft.",
            script=generated_script,
            execution_result=ExecutionResult(
                success=True,
                plot_path=str(preview_plot),
                plot_type="raster",
            ),
        )

    monkeypatch.setattr(server, "_run_plot_mode_planning", _fake_planning)
    monkeypatch.setattr(server, "_run_plot_mode_generation", _fake_generation)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(data_path)]},
        )
        assert select_response.status_code == 200
        plot_mode = select_response.json()["plot_mode"]

        preview_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": plot_mode["pending_question_set"]["id"],
                "answers": [
                    {
                        "question_id": plot_mode["pending_question_set"]["questions"][
                            0
                        ]["id"],
                        "option_ids": ["use_preview"],
                    }
                ],
            },
        )
        assert preview_response.status_code == 200

        chat_response = client.post(
            "/api/plot-mode/chat",
            json={"message": "Plot x vs y with a dark orange line."},
        )
        assert chat_response.status_code == 200
        pending_question = chat_response.json()["plot_mode"]["pending_question_set"]

        approve_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": pending_question["id"],
                "answers": [
                    {
                        "question_id": pending_question["questions"][0]["id"],
                        "option_ids": ["start_draft"],
                    }
                ],
            },
        )
        assert approve_response.status_code == 200
        approved_plot_mode = approve_response.json()["plot_mode"]
        plot_mode_id = approved_plot_mode["id"]

        active_snapshot = tmp_path / "state" / "openplot" / "plot-mode" / "active.json"
        workspace_snapshot = (
            tmp_path
            / "state"
            / "openplot"
            / "plot-mode"
            / plot_mode_id
            / "workspace.json"
        )
        assert active_snapshot.exists()
        assert workspace_snapshot.exists()

    with TestClient(server.create_app()) as restarted_client:
        sessions_response = restarted_client.get("/api/sessions")
        assert sessions_response.status_code == 200
        sessions_payload = sessions_response.json()
        plot_entries = [
            entry
            for entry in sessions_payload["sessions"]
            if entry["workspace_mode"] == "plot"
        ]
        assert any(entry["id"] == plot_mode_id for entry in plot_entries)

        bootstrap_response = restarted_client.get("/api/bootstrap")
        assert bootstrap_response.status_code == 200
        bootstrap_payload = bootstrap_response.json()
        assert bootstrap_payload["mode"] == "plot"
        assert bootstrap_payload["plot_mode"] is not None
        assert bootstrap_payload["plot_mode"]["id"] == plot_mode_id
        assert bootstrap_payload["plot_mode"]["current_plot"] == str(preview_plot)
        assert bootstrap_payload["plot_mode"]["current_script"] == generated_script


def test_plot_mode_settings_toggle_updates_execution_mode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")

    with TestClient(server.create_app()) as client:
        response = client.patch(
            "/api/plot-mode/settings",
            json={"execution_mode": "autonomous"},
        )

    assert response.status_code == 200
    assert response.json()["plot_mode"]["execution_mode"] == "autonomous"


def test_plot_mode_multiple_csvs_skip_the_source_selection_question(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    first = workspace / "first.csv"
    second = workspace / "second.csv"
    first.write_text("x,y\n1,2\n")
    second.write_text("x,y\n2,3\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(first), str(second)]},
        )
        assert select_response.status_code == 200

    payload = select_response.json()["plot_mode"]
    assert payload["phase"] == "awaiting_data_choice"
    assert payload["pending_question_set"] is not None
    assert payload["pending_question_set"]["purpose"] == "kickoff_plot_planning"
    assert payload["selected_data_profile_id"] is None
    assert len(payload["resolved_sources"]) == 1
    assert payload["resolved_sources"][0]["kind"] == "multi_file_collection"


def test_plot_mode_preview_confirmation_advances_to_prompt_phase(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_path = workspace / "data.csv"
    data_path.write_text("x,y\n1,2\n2,3\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    async def _fake_planning(
        *,
        state,
        runner,
        user_message,
        model,
        variant,
    ):
        _ = (state, runner, user_message, model, variant)
        return server.PlotModePlanResult(
            assistant_text="Plan prepared.",
            summary="A simple line chart is the strongest fit.",
            plot_type="line chart",
            plan_outline=["Plot x against y with clear labels."],
            data_actions=[
                "Read the confirmed CSV source and validate the numeric columns."
            ],
            ready_to_plot=False,
            clarification_question="Would you like me to keep refining the plan before drafting?",
        )

    monkeypatch.setattr(server, "_run_plot_mode_planning", _fake_planning)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(data_path)]},
        )
        assert select_response.status_code == 200
        plot_mode = select_response.json()["plot_mode"]
        question_id = plot_mode["pending_question_set"]["id"]

        answer_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": question_id,
                "answers": [
                    {
                        "question_id": plot_mode["pending_question_set"]["questions"][
                            0
                        ]["id"],
                        "option_ids": ["use_preview"],
                    }
                ],
            },
        )

    assert answer_response.status_code == 200
    payload = answer_response.json()["plot_mode"]
    assert payload["phase"] == "awaiting_data_choice"
    assert payload["selected_data_profile_id"] == payload["data_profiles"][0]["id"]
    assert payload["pending_question_set"]["purpose"] == "continue_plot_planning"


def test_plot_mode_tabular_hint_infers_preview_for_ambiguous_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_path = workspace / "ambiguous.csv"
    data_path.write_text("year,value,,group,count\n2020,1,,A,3\n2021,2,,B,4\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    seen_instructions: list[str | None] = []

    async def _fake_proposal(*, state, selector, sheet_id, hint_bounds, instruction):
        _ = (state, hint_bounds)
        seen_instructions.append(instruction)
        sheet = next(sheet for sheet in selector.sheets if sheet.id == sheet_id)
        profile = server._build_data_profile_from_grid(
            file_path=Path(selector.file_path),
            file_id=selector.file_id,
            source_kind=selector.source_kind,
            sheet_name=sheet.name,
            bounds=(0, 2, 3, 4),
            rows=sheet.preview_rows,
        )
        return server.PlotModeTabularProposalResult(
            profile=profile,
            rationale="Focused on the hinted right-hand columns.",
            used_agent=True,
        )

    monkeypatch.setattr(server, "_propose_profile_from_selector_hint", _fake_proposal)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(data_path)]},
        )
        assert select_response.status_code == 200
        plot_mode = select_response.json()["plot_mode"]
        selector = plot_mode["tabular_selector"]
        assert selector is not None
        assert selector["requires_user_hint"] is True

        hint_response = client.post(
            "/api/plot-mode/tabular-hint",
            json={
                "selector_id": selector["id"],
                "regions": [
                    {
                        "sheet_id": selector["sheets"][0]["id"],
                        "row_start": 0,
                        "row_end": 2,
                        "col_start": 3,
                        "col_end": 4,
                    }
                ],
                "note": "use the group/count table",
            },
        )

    assert hint_response.status_code == 200
    payload = hint_response.json()["plot_mode"]
    assert payload["tabular_selector"]["requires_user_hint"] is False
    assert len(payload["tabular_selector"]["selected_regions"]) == 1
    assert seen_instructions == ["use the group/count table"]
    assert payload["pending_question_set"]["purpose"] == "confirm_tabular_range"
    assert payload["data_profiles"]
    assert payload["data_profiles"][0]["inferred_bounds"] == [0, 2, 3, 4]
    assert len(payload["data_profiles"][0]["tabular_regions"]) == 1


def test_plot_mode_tabular_range_confirmation_advances_to_prompt_phase(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_path = workspace / "ambiguous.csv"
    data_path.write_text("year,value,,group,count\n2020,1,,A,3\n2021,2,,B,4\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    async def _fake_proposal(*, state, selector, sheet_id, hint_bounds, instruction):
        _ = (state, hint_bounds, instruction)
        sheet = next(sheet for sheet in selector.sheets if sheet.id == sheet_id)
        profile = server._build_data_profile_from_grid(
            file_path=Path(selector.file_path),
            file_id=selector.file_id,
            source_kind=selector.source_kind,
            sheet_name=sheet.name,
            bounds=(0, 2, 3, 4),
            rows=sheet.preview_rows,
        )
        return server.PlotModeTabularProposalResult(
            profile=profile,
            rationale="Focused on the hinted right-hand columns.",
            used_agent=True,
        )

    async def _fake_planning(
        *,
        state,
        runner,
        user_message,
        model,
        variant,
    ):
        _ = (state, runner, user_message, model, variant)
        return server.PlotModePlanResult(
            assistant_text="Plan prepared.",
            summary="A grouped comparison plot is a good fit.",
            plot_type="grouped bar chart",
            plan_outline=["Compare count by group."],
            data_actions=["Read the confirmed spreadsheet range."],
            ready_to_plot=False,
            clarification_question="Should I keep refining the plan before drafting?",
        )

    monkeypatch.setattr(server, "_propose_profile_from_selector_hint", _fake_proposal)
    monkeypatch.setattr(server, "_run_plot_mode_planning", _fake_planning)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(data_path)]},
        )
        selector = select_response.json()["plot_mode"]["tabular_selector"]

        hint_response = client.post(
            "/api/plot-mode/tabular-hint",
            json={
                "selector_id": selector["id"],
                "regions": [
                    {
                        "sheet_id": selector["sheets"][0]["id"],
                        "row_start": 0,
                        "row_end": 2,
                        "col_start": 3,
                        "col_end": 4,
                    }
                ],
            },
        )
        assert hint_response.status_code == 200
        pending_question = hint_response.json()["plot_mode"]["pending_question_set"]

        answer_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": pending_question["id"],
                "answers": [
                    {
                        "question_id": pending_question["questions"][0]["id"],
                        "option_ids": ["use_proposed_range"],
                    }
                ],
            },
        )

    assert answer_response.status_code == 200
    payload = answer_response.json()["plot_mode"]
    assert payload["selected_data_profile_id"] == payload["data_profiles"][0]["id"]
    assert payload["pending_question_set"]["purpose"] == "continue_plot_planning"


def test_plot_mode_tabular_range_reinference_uses_note_text(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_path = workspace / "ambiguous.csv"
    data_path.write_text("year,value,,group,count\n2020,1,,A,3\n2021,2,,B,4\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    seen_instructions: list[str | None] = []

    async def _fake_proposal(*, state, selector, sheet_id, hint_bounds, instruction):
        _ = (state, hint_bounds)
        seen_instructions.append(instruction)
        sheet = next(sheet for sheet in selector.sheets if sheet.id == sheet_id)
        bounds = (0, 2, 3, 4) if not instruction else (0, 2, 0, 1)
        profile = server._build_data_profile_from_grid(
            file_path=Path(selector.file_path),
            file_id=selector.file_id,
            source_kind=selector.source_kind,
            sheet_name=sheet.name,
            bounds=bounds,
            rows=sheet.preview_rows,
        )
        return server.PlotModeTabularProposalResult(
            profile=profile,
            rationale="Adjusted the proposal using the note."
            if instruction
            else "Initial proposal.",
            used_agent=True,
        )

    monkeypatch.setattr(server, "_propose_profile_from_selector_hint", _fake_proposal)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(data_path)]},
        )
        selector = select_response.json()["plot_mode"]["tabular_selector"]

        hint_response = client.post(
            "/api/plot-mode/tabular-hint",
            json={
                "selector_id": selector["id"],
                "regions": [
                    {
                        "sheet_id": selector["sheets"][0]["id"],
                        "row_start": 0,
                        "row_end": 2,
                        "col_start": 3,
                        "col_end": 4,
                    }
                ],
            },
        )
        assert hint_response.status_code == 200
        pending_question = hint_response.json()["plot_mode"]["pending_question_set"]

        answer_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": pending_question["id"],
                "answers": [
                    {
                        "question_id": pending_question["questions"][0]["id"],
                        "option_ids": [],
                        "text": "use columns A and B only",
                    }
                ],
            },
        )

    assert answer_response.status_code == 200
    payload = answer_response.json()["plot_mode"]
    assert seen_instructions == [None, "use columns A and B only"]
    assert payload["pending_question_set"]["purpose"] == "confirm_tabular_range"
    assert payload["data_profiles"][0]["inferred_bounds"] == [0, 2, 0, 1]


def test_plot_mode_tabular_hint_supports_multiple_regions_for_one_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_path = workspace / "ambiguous.csv"
    data_path.write_text("year,value,,group,count\n2020,1,,A,3\n2021,2,,B,4\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    seen_calls: list[tuple[str, tuple[int, int, int, int], str | None]] = []

    async def _fake_proposal(*, state, selector, sheet_id, hint_bounds, instruction):
        _ = state
        sheet = next(sheet for sheet in selector.sheets if sheet.id == sheet_id)
        bounds = (
            hint_bounds.row_start,
            hint_bounds.row_end,
            hint_bounds.col_start,
            hint_bounds.col_end,
        )
        seen_calls.append((sheet.name, bounds, instruction))
        profile = server._build_data_profile_from_grid(
            file_path=Path(selector.file_path),
            file_id=selector.file_id,
            source_kind=selector.source_kind,
            sheet_name=sheet.name,
            bounds=bounds,
            rows=sheet.preview_rows,
        )
        return server.PlotModeTabularProposalResult(
            profile=profile,
            rationale=f"Used {sheet.name}!{server._format_sheet_bounds(bounds)}.",
            used_agent=True,
        )

    monkeypatch.setattr(server, "_propose_profile_from_selector_hint", _fake_proposal)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(data_path)]},
        )
        selector = select_response.json()["plot_mode"]["tabular_selector"]

        hint_response = client.post(
            "/api/plot-mode/tabular-hint",
            json={
                "selector_id": selector["id"],
                "regions": [
                    {
                        "sheet_id": selector["sheets"][0]["id"],
                        "row_start": 0,
                        "row_end": 2,
                        "col_start": 0,
                        "col_end": 1,
                    },
                    {
                        "sheet_id": selector["sheets"][0]["id"],
                        "row_start": 0,
                        "row_end": 2,
                        "col_start": 3,
                        "col_end": 4,
                    },
                ],
                "note": "treat both blocks as one source",
            },
        )

    assert hint_response.status_code == 200
    payload = hint_response.json()["plot_mode"]
    assert payload["tabular_selector"]["requires_user_hint"] is False
    assert len(payload["tabular_selector"]["selected_regions"]) == 2
    assert payload["pending_question_set"]["purpose"] == "confirm_tabular_range"
    assert payload["data_profiles"][0]["inferred_bounds"] is None
    assert len(payload["data_profiles"][0]["tabular_regions"]) == 2
    assert {
        (region["sheet_name"], tuple(region["bounds"].values()))
        for region in payload["data_profiles"][0]["tabular_regions"]
    } == {
        (selector["sheets"][0]["name"], (0, 2, 0, 1)),
        (selector["sheets"][0]["name"], (0, 2, 3, 4)),
    }
    assert seen_calls == [
        (
            selector["sheets"][0]["name"],
            (0, 2, 0, 1),
            "treat both blocks as one source",
        ),
        (
            selector["sheets"][0]["name"],
            (0, 2, 3, 4),
            "treat both blocks as one source",
        ),
    ]


def test_plot_mode_tabular_hint_supports_multiple_sheets_for_one_xlsx_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_path = workspace / "multi_sheet.xlsx"

    workbook = Workbook()
    sheet_one = workbook.active
    assert sheet_one is not None
    sheet_one.title = "Summary"
    sheet_one["A1"] = "year"
    sheet_one["B1"] = "value"
    sheet_one["A2"] = 2020
    sheet_one["B2"] = 1
    sheet_one["A3"] = 2021
    sheet_one["B3"] = 2

    sheet_two = workbook.create_sheet("Metadata")
    sheet_two["D1"] = "group"
    sheet_two["E1"] = "count"
    sheet_two["D2"] = "A"
    sheet_two["E2"] = 3
    sheet_two["D3"] = "B"
    sheet_two["E3"] = 4
    workbook.save(data_path)

    server.init_plot_mode_session(workspace_dir=workspace)

    async def _fake_proposal(*, state, selector, sheet_id, hint_bounds, instruction):
        _ = (state, instruction)
        sheet = next(sheet for sheet in selector.sheets if sheet.id == sheet_id)
        bounds = (
            hint_bounds.row_start,
            hint_bounds.row_end,
            hint_bounds.col_start,
            hint_bounds.col_end,
        )
        profile = server._build_data_profile_from_grid(
            file_path=Path(selector.file_path),
            file_id=selector.file_id,
            source_kind=selector.source_kind,
            sheet_name=sheet.name,
            bounds=bounds,
            rows=sheet.preview_rows,
        )
        return server.PlotModeTabularProposalResult(
            profile=profile,
            rationale=f"Used {sheet.name}!{server._format_sheet_bounds(bounds)}.",
            used_agent=True,
        )

    monkeypatch.setattr(server, "_propose_profile_from_selector_hint", _fake_proposal)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(data_path)]},
        )
        selector = select_response.json()["plot_mode"]["tabular_selector"]
        assert selector is not None
        assert len(selector["sheets"]) >= 2

        hint_response = client.post(
            "/api/plot-mode/tabular-hint",
            json={
                "selector_id": selector["id"],
                "regions": [
                    {
                        "sheet_id": selector["sheets"][0]["id"],
                        "row_start": 0,
                        "row_end": 2,
                        "col_start": 0,
                        "col_end": 1,
                    },
                    {
                        "sheet_id": selector["sheets"][1]["id"],
                        "row_start": 0,
                        "row_end": 2,
                        "col_start": 3,
                        "col_end": 4,
                    },
                ],
            },
        )

    assert hint_response.status_code == 200
    payload = hint_response.json()["plot_mode"]
    assert len(payload["tabular_selector"]["selected_regions"]) == 2
    assert len(payload["data_profiles"][0]["tabular_regions"]) == 2
    assert {
        region["sheet_name"]
        for region in payload["data_profiles"][0]["tabular_regions"]
    } == {selector["sheets"][0]["name"], selector["sheets"][1]["name"]}


def test_plot_mode_chat_stays_in_planning_before_approval(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_path = workspace / "data.csv"
    data_path.write_text("x,y\n1,2\n2,3\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    async def _fake_planning(
        *,
        state,
        runner,
        user_message,
        model,
        variant,
    ):
        _ = (state, runner, user_message, model, variant)
        if "trend story" not in user_message:
            return server.PlotModePlanResult(
                assistant_text="Initial planning pass.",
                summary="I found a clean table and can keep refining the figure direction before drafting.",
                plot_type="line chart",
                plan_outline=["Confirm the narrative focus before drafting."],
                data_actions=["Read data.csv"],
                ready_to_plot=False,
            )
        return server.PlotModePlanResult(
            assistant_text="Plan prepared.",
            summary="Line chart with publication styling.",
            plot_type="line chart",
            plan_outline=["Plan step"],
            data_actions=["Read data.csv"],
            ready_to_plot=True,
        )

    monkeypatch.setattr(server, "_run_plot_mode_planning", _fake_planning)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(data_path)]},
        )
        assert select_response.status_code == 200

        preview_question_id = select_response.json()["plot_mode"][
            "pending_question_set"
        ]["id"]
        preview_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": preview_question_id,
                "answers": [
                    {
                        "question_id": select_response.json()["plot_mode"][
                            "pending_question_set"
                        ]["questions"][0]["id"],
                        "option_ids": ["use_preview"],
                    }
                ],
            },
        )
        assert preview_response.status_code == 200

        chat_response = client.post(
            "/api/plot-mode/chat",
            json={"message": "Can we focus on a clean trend story?"},
        )

    assert chat_response.status_code == 200
    payload = chat_response.json()["plot_mode"]
    assert payload["phase"] == "awaiting_plan_approval"
    assert payload["pending_question_set"] is not None
    assert payload["current_script"] is None
    assert payload["current_plot"] is None


def test_extract_plot_mode_plan_result_recovers_plain_text_question_options() -> None:
    result = server._extract_plot_mode_plan_result(
        "\n".join(
            [
                "Got it.",
                "Which direction should I optimize for?",
                "1. Publication style",
                "2. Presentation style",
                "3. Exploratory analysis",
            ]
        )
    )

    assert result is not None
    assert result.summary == "Got it."
    assert result.clarification_question == "Which direction should I optimize for?"
    assert result.question_purpose == "continue_plot_planning"
    assert result.questions is not None
    assert [option.label for option in result.questions[0].options] == [
        "Publication style",
        "Presentation style",
        "Exploratory analysis",
    ]


def test_extract_plot_mode_plan_result_accepts_codex_choice_schema() -> None:
    result = server._extract_plot_mode_plan_result(
        "\n".join(
            [
                "OPENPLOT_PLAN_BEGIN",
                json.dumps(
                    {
                        "summary": "I found a clear time-series trend.",
                        "questions": [
                            {
                                "question": "Which direction should I optimize for?",
                                "choices": [
                                    {
                                        "value": "publication_style",
                                        "text": "Publication style",
                                        "description": "Conservative typography and restrained color.",
                                    },
                                    {
                                        "value": "presentation_style",
                                        "text": "Presentation style",
                                    },
                                    {
                                        "value": "exploratory_analysis",
                                        "text": "Exploratory analysis",
                                    },
                                ],
                                "freeform": True,
                            }
                        ],
                        "question_purpose": "continue_plot_planning",
                        "ready_to_plot": False,
                    }
                ),
                "OPENPLOT_PLAN_END",
            ]
        )
    )

    assert result is not None
    assert result.questions is not None
    assert result.questions[0].prompt == "Which direction should I optimize for?"
    assert [option.id for option in result.questions[0].options] == [
        "publication_style",
        "presentation_style",
        "exploratory_analysis",
    ]
    assert [option.label for option in result.questions[0].options] == [
        "Publication style",
        "Presentation style",
        "Exploratory analysis",
    ]
    assert result.questions[0].allow_custom_answer is True


def test_run_plot_mode_planning_recovers_optionless_questions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    server.init_plot_mode_session(workspace_dir=workspace)
    state = server._get_plot_mode_state()

    responses = iter(
        [
            (
                json.dumps(
                    {
                        "summary": "I need one decision before drafting.",
                        "questions": [
                            {
                                "prompt": "Which direction should I optimize for?",
                                "allow_custom_answer": True,
                            }
                        ],
                        "question_purpose": "continue_plot_planning",
                        "ready_to_plot": False,
                    }
                ),
                None,
            ),
            (
                json.dumps(
                    {
                        "summary": "I need one decision before drafting.",
                        "questions": [
                            {
                                "prompt": "Which direction should I optimize for?",
                                "options": [
                                    "Publication style",
                                    "Presentation style",
                                    "Exploratory analysis",
                                ],
                                "allow_custom_answer": True,
                            }
                        ],
                        "question_purpose": "continue_plot_planning",
                        "ready_to_plot": False,
                    }
                ),
                None,
            ),
        ]
    )
    prompts: list[str] = []

    async def _fake_runner_prompt(*, state, runner, prompt, model, variant):
        _ = (state, runner, model, variant)
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(server, "_run_plot_mode_runner_prompt", _fake_runner_prompt)

    result = asyncio.run(
        server._run_plot_mode_planning(
            state=state,
            runner="codex",
            user_message="Help me choose the best direction.",
            model="gpt-5.2-codex",
            variant=None,
        )
    )

    assert result.questions is not None
    assert [option.label for option in result.questions[0].options] == [
        "Publication style",
        "Presentation style",
        "Exploratory analysis",
    ]
    assert len(prompts) == 2


def test_plot_mode_plain_text_planning_question_creates_question_card(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_path = workspace / "data.csv"
    data_path.write_text("x,y\n1,2\n2,3\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    async def _fake_runner_prompt(*, state, runner, prompt, model, variant):
        _ = (state, runner, prompt, model, variant)
        return (
            "\n".join(
                [
                    "Got it.",
                    "Which direction should I optimize for?",
                    "1. Publication style",
                    "2. Presentation style",
                    "3. Exploratory analysis",
                ]
            ),
            None,
        )

    monkeypatch.setattr(server, "_run_plot_mode_runner_prompt", _fake_runner_prompt)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(data_path)]},
        )
        assert select_response.status_code == 200

        preview_question = select_response.json()["plot_mode"]["pending_question_set"]
        answer_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": preview_question["id"],
                "answers": [
                    {
                        "question_id": preview_question["questions"][0]["id"],
                        "option_ids": ["use_preview"],
                    }
                ],
            },
        )

    assert answer_response.status_code == 200
    payload = answer_response.json()["plot_mode"]
    assert payload["phase"] == "awaiting_data_choice"
    assert payload["pending_question_set"] is not None
    assert payload["pending_question_set"]["purpose"] == "continue_plot_planning"
    assert payload["pending_question_set"]["questions"][0]["prompt"] == (
        "Which direction should I optimize for?"
    )
    assert [
        option["label"]
        for option in payload["pending_question_set"]["questions"][0]["options"]
    ] == [
        "Publication style",
        "Presentation style",
        "Exploratory analysis",
    ]


def test_extract_plot_mode_plan_result_recovers_plain_text_question_list() -> None:
    result = server._extract_plot_mode_plan_result(
        "\n".join(
            [
                "Got it. Please provide:",
                "1. What audience is this chart for?",
                "2. Should the tone feel academic or executive?",
                "3. Which metric matters most?",
                "4. Do you want a single panel or small multiples?",
                "5. Should I optimize for print or slides?",
            ]
        )
    )

    assert result is not None
    assert result.summary == "Got it. Please provide:"
    assert result.question_purpose == "continue_plot_planning"
    assert result.questions is not None
    assert [question.prompt for question in result.questions] == [
        "What audience is this chart for?",
        "Should the tone feel academic or executive?",
        "Which metric matters most?",
        "Do you want a single panel or small multiples?",
        "Should I optimize for print or slides?",
    ]
    assert [option.label for option in result.questions[0].options] == [
        "Academic readers",
        "Executive audience",
        "Technical internal audience",
    ]
    assert [option.label for option in result.questions[1].options] == [
        "Academic",
        "Executive",
        "Exploratory",
    ]


def test_extract_plot_mode_plan_result_recovers_inline_numbered_question_list() -> None:
    result = server._extract_plot_mode_plan_result(
        (
            "Got it. Before script generation, let's lock down the figure spec. "
            "Please answer these so I can draft a publication-quality plan: "
            "1. Figure type(s): line, scatter, bar, heatmap, histogram, box/violin, image, multi-panel? "
            "2. Data source: file path(s), table schema, or a brief description of columns and units. "
            "3. Axes: x/y variables, scales (linear/log), ranges, and any transforms. "
            "4. Layout: single panel or multi-panel (rows/cols), shared axes? "
            "5. Styling: target journal/venue style, font family/size, color palette, line widths, marker styles. "
            "6. Annotations: legends, labels, error bars, statistical markers, reference lines. "
            "7. Output: size (inches/cm), DPI, file format (PDF/SVG/PNG), background (transparent/white). "
            "8. Any strict constraints or examples to match?"
        )
    )

    assert result is not None
    assert result.question_purpose == "continue_plot_planning"
    assert result.questions is not None
    assert [question.prompt for question in result.questions] == [
        "Figure type(s): line, scatter, bar, heatmap, histogram, box/violin, image, multi-panel?",
        "Data source: file path(s), table schema, or a brief description of columns and units.",
        "Axes: x/y variables, scales (linear/log), ranges, and any transforms.",
        "Layout: single panel or multi-panel (rows/cols), shared axes?",
        "Styling: target journal/venue style, font family/size, color palette, line widths, marker styles.",
        "Annotations: legends, labels, error bars, statistical markers, reference lines.",
        "Output: size (inches/cm), DPI, file format (PDF/SVG/PNG), background (transparent/white).",
        "Any strict constraints or examples to match?",
    ]
    assert [option.label for option in result.questions[0].options] == [
        "Line chart",
        "Scatter plot",
        "Bar chart",
        "Heatmap",
        "Multi-panel",
    ]
    assert [option.label for option in result.questions[3].options] == [
        "Single panel",
        "1x2 panels",
        "2x2 small multiples",
        "Custom layout",
    ]


def test_plot_mode_plain_text_question_list_creates_multi_question_card(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    data_path = workspace / "data.csv"
    data_path.write_text("x,y\n1,2\n2,3\n")

    server.init_plot_mode_session(workspace_dir=workspace)

    async def _fake_runner_prompt(*, state, runner, prompt, model, variant):
        _ = (state, runner, prompt, model, variant)
        return (
            "\n".join(
                [
                    "Got it. Please provide:",
                    "1. What audience is this chart for?",
                    "2. Should the tone feel academic or executive?",
                    "3. Which metric matters most?",
                    "4. Do you want a single panel or small multiples?",
                    "5. Should I optimize for print or slides?",
                ]
            ),
            None,
        )

    monkeypatch.setattr(server, "_run_plot_mode_runner_prompt", _fake_runner_prompt)

    with TestClient(server.create_app()) as client:
        select_response = client.post(
            "/api/plot-mode/select-paths",
            json={"selection_type": "data", "paths": [str(data_path)]},
        )
        assert select_response.status_code == 200

        preview_question = select_response.json()["plot_mode"]["pending_question_set"]
        answer_response = client.post(
            "/api/plot-mode/answer",
            json={
                "question_set_id": preview_question["id"],
                "answers": [
                    {
                        "question_id": preview_question["questions"][0]["id"],
                        "option_ids": ["use_preview"],
                    }
                ],
            },
        )

    assert answer_response.status_code == 200
    payload = answer_response.json()["plot_mode"]
    assert payload["phase"] == "awaiting_data_choice"
    assert payload["pending_question_set"] is not None
    assert payload["pending_question_set"]["purpose"] == "continue_plot_planning"
    assert [
        question["prompt"] for question in payload["pending_question_set"]["questions"]
    ] == [
        "What audience is this chart for?",
        "Should the tone feel academic or executive?",
        "Which metric matters most?",
        "Do you want a single panel or small multiples?",
        "Should I optimize for print or slides?",
    ]
