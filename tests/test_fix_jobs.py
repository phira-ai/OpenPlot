from __future__ import annotations

import asyncio
import json
import os
import ssl
import subprocess
import sys
import time
from pathlib import Path
from typing import cast
from urllib import error as urllib_error

import pytest
from fastapi.testclient import TestClient

import openplot.server as server
from openplot.models import (
    AnnotationStatus,
    FixJob,
    FixJobStatus,
    FixRunner,
    FixJobStep,
    FixStepStatus,
    OpencodeModelOption,
    PlotSession,
)


@pytest.fixture(autouse=True)
def _mock_default_runner_availability(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENPLOT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": ["opencode", "codex", "claude"],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )


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


def _wait_for_terminal_fix_job(client: TestClient, *, timeout_s: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last_job: dict | None = None
    while time.monotonic() < deadline:
        response = client.get("/api/fix-jobs/current")
        assert response.status_code == 200
        payload = response.json()
        last_job = payload.get("job")
        if last_job and last_job.get("status") in {
            "completed",
            "failed",
            "cancelled",
        }:
            return last_job
        time.sleep(0.05)
    raise AssertionError(f"Fix job did not finish in time: {last_job}")


class _ChunkedBytesReader:
    def __init__(self, payload: bytes, *, chunk_size: int = 1024):
        self._payload = payload
        self._chunk_size = chunk_size
        self._offset = 0

    async def read(self, n: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""

        requested = self._chunk_size if n <= 0 else min(self._chunk_size, n)
        start = self._offset
        end = min(len(self._payload), start + requested)
        self._offset = end
        return self._payload[start:end]


def test_fix_job_processes_pending_annotations_fifo(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    _write_script(script_path, color="steelblue")

    result = server.init_session_from_script(script_path)
    assert result.success

    with TestClient(server.create_app()) as client:
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

            session = server.get_session()
            target = next(
                ann for ann in session.annotations if ann.id == step.annotation_id
            )
            target.status = AnnotationStatus.addressed
            target.addressed_in_version_id = session.checked_out_version_id

        monkeypatch.setattr(server, "_run_opencode_fix_iteration", fake_fix_iteration)

        start_response = client.post(
            "/api/fix-jobs",
            json={"model": "openai/gpt-5.3-codex", "variant": "high"},
        )
        assert start_response.status_code == 200

        completed_job = _wait_for_terminal_fix_job(client)
        assert completed_job["status"] == "completed"
        assert completed_job["completed_annotations"] == 2
        assert len(completed_job["steps"]) == 2
        assert completed_job["steps"][0]["status"] == "completed"
        assert completed_job["steps"][1]["status"] == "completed"

        session = client.get("/api/session").json()
        assert all(ann["status"] == "addressed" for ann in session["annotations"])


def test_fix_job_requires_pending_annotations(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    _write_script(script_path)

    result = server.init_session_from_script(script_path)
    assert result.success

    with TestClient(server.create_app()) as client:
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

        response = client.post(
            "/api/fix-jobs",
            json={"model": "openai/gpt-5.3-codex", "variant": "high"},
        )
        assert response.status_code == 409


def test_fix_preferences_persist_globally(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    _write_script(script_path)

    result = server.init_session_from_script(script_path)
    assert result.success

    monkeypatch.setattr(
        server,
        "_refresh_opencode_models_cache",
        lambda force_refresh=False: [
            OpencodeModelOption(
                id="openai/gpt-5.3-codex",
                provider="openai",
                name="GPT-5.3 Codex",
                variants=["high", "low"],
            )
        ],
    )

    with TestClient(server.create_app()) as client:
        set_response = client.post(
            "/api/preferences",
            json={"fix_model": "openai/gpt-5.3-codex", "fix_variant": "high"},
        )
        assert set_response.status_code == 200

        get_response = client.get("/api/preferences")
        assert get_response.status_code == 200
        assert get_response.json() == {
            "fix_runner": "opencode",
            "fix_model": "openai/gpt-5.3-codex",
            "fix_variant": "high",
        }

        models_response = client.get("/api/opencode/models")
        assert models_response.status_code == 200
        assert models_response.json()["default_model"] == "openai/gpt-5.3-codex"
        assert models_response.json()["default_variant"] == "high"

    with TestClient(server.create_app()) as client:
        get_response = client.get("/api/preferences")
        assert get_response.status_code == 200
        assert get_response.json() == {
            "fix_runner": "opencode",
            "fix_model": "openai/gpt-5.3-codex",
            "fix_variant": "high",
        }


def test_fix_job_accepts_codex_runner(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    _write_script(script_path, color="steelblue")

    result = server.init_session_from_script(script_path)
    assert result.success

    with TestClient(server.create_app()) as client:
        response = client.post(
            "/api/annotations",
            json={"feedback": "first", "region": _new_region()},
        )
        assert response.status_code == 200

        monkeypatch.setattr(
            server,
            "_refresh_runner_models_cache",
            lambda runner, force_refresh=False: (
                [
                    OpencodeModelOption(
                        id="gpt-5.2-codex",
                        provider="openai",
                        name="GPT-5.2 Codex",
                        variants=["low", "medium", "high"],
                    )
                ]
                if runner == "codex"
                else []
            ),
        )

        async def fake_codex_fix_iteration(job, step, *, extra_prompt=None):
            _ = extra_prompt
            step.command = ["codex", "exec", "<plot-fix prompt>"]
            step.exit_code = 0
            step.stdout = "ok"
            step.stderr = ""

            session = server.get_session()
            target = next(
                ann for ann in session.annotations if ann.id == step.annotation_id
            )
            target.status = AnnotationStatus.addressed
            target.addressed_in_version_id = session.checked_out_version_id

        monkeypatch.setattr(
            server, "_run_codex_fix_iteration", fake_codex_fix_iteration
        )

        start_response = client.post(
            "/api/fix-jobs",
            json={"runner": "codex", "model": "gpt-5.2-codex", "variant": "high"},
        )
        assert start_response.status_code == 200

        completed_job = _wait_for_terminal_fix_job(client)
        assert completed_job["status"] == "completed"
        assert completed_job["runner"] == "codex"


def test_fix_job_accepts_claude_runner(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    script_path = tmp_path / "plot.py"
    _write_script(script_path, color="steelblue")

    result = server.init_session_from_script(script_path)
    assert result.success

    with TestClient(server.create_app()) as client:
        response = client.post(
            "/api/annotations",
            json={"feedback": "first", "region": _new_region()},
        )
        assert response.status_code == 200

        monkeypatch.setattr(
            server,
            "_refresh_runner_models_cache",
            lambda runner, force_refresh=False: (
                [
                    OpencodeModelOption(
                        id="claude-sonnet-4-6",
                        provider="anthropic",
                        name="Claude Sonnet 4.6",
                        variants=["low", "medium", "high"],
                    )
                ]
                if runner == "claude"
                else []
            ),
        )

        async def fake_claude_fix_iteration(job, step, *, extra_prompt=None):
            _ = extra_prompt
            step.command = ["claude", "-p", "<plot-fix prompt>"]
            step.exit_code = 0
            step.stdout = "ok"
            step.stderr = ""

            session = server.get_session()
            target = next(
                ann for ann in session.annotations if ann.id == step.annotation_id
            )
            target.status = AnnotationStatus.addressed
            target.addressed_in_version_id = session.checked_out_version_id

        monkeypatch.setattr(
            server, "_run_claude_fix_iteration", fake_claude_fix_iteration
        )

        start_response = client.post(
            "/api/fix-jobs",
            json={"runner": "claude", "model": "claude-sonnet-4-6", "variant": "high"},
        )
        assert start_response.status_code == 200

        completed_job = _wait_for_terminal_fix_job(client)
        assert completed_job["status"] == "completed"
        assert completed_job["runner"] == "claude"


def test_runners_endpoint_reports_available_backends(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": ["opencode"],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )

    with TestClient(server.create_app()) as client:
        response = client.get("/api/runners")
        assert response.status_code == 200
        assert response.json() == {
            "available_runners": ["opencode"],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        }


def test_runner_status_endpoint_surfaces_install_actions_for_supported_host(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": [],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )
    monkeypatch.setattr(server, "_runner_host_platform", lambda: ("darwin", "arm64"))
    monkeypatch.setattr(server, "_winget_available", lambda: False)
    monkeypatch.setattr(server, "_resolve_command_path", lambda command: None)
    monkeypatch.setattr(server, "_resolve_claude_cli_command", lambda: None)

    with TestClient(server.create_app()) as client:
        response = client.get("/api/runners/status")
        assert response.status_code == 200
        payload = response.json()

    assert payload["available_runners"] == []
    assert payload["host_platform"] == "darwin"
    assert payload["host_arch"] == "arm64"
    assert [runner["runner"] for runner in payload["runners"]] == [
        "opencode",
        "codex",
        "claude",
    ]
    assert [runner["primary_action"] for runner in payload["runners"]] == [
        "install",
        "install",
        "install",
    ]


def test_runner_status_endpoint_uses_guide_action_when_click_install_is_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": [],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )
    monkeypatch.setattr(server, "_runner_host_platform", lambda: ("linux", "x86_64"))
    monkeypatch.setattr(server, "_winget_available", lambda: False)

    with TestClient(server.create_app()) as client:
        response = client.get("/api/runners/status")
        assert response.status_code == 200
        payload = response.json()

    assert [runner["primary_action"] for runner in payload["runners"]] == [
        "guide",
        "guide",
        "guide",
    ]
    assert [runner["primary_action_label"] for runner in payload["runners"]] == [
        "See guide",
        "See guide",
        "See guide",
    ]


def test_runner_status_endpoint_uses_guide_action_for_windows_claude(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": [],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )
    monkeypatch.setattr(server, "_runner_host_platform", lambda: ("win32", "arm64"))
    monkeypatch.setattr(server, "_winget_available", lambda: False)
    monkeypatch.setattr(server, "_resolve_command_path", lambda command: None)
    monkeypatch.setattr(server, "_resolve_claude_cli_command", lambda: None)

    with TestClient(server.create_app()) as client:
        response = client.get("/api/runners/status")
        assert response.status_code == 200
        payload = response.json()

    opencode_status = next(
        item for item in payload["runners"] if item["runner"] == "opencode"
    )
    codex_status = next(
        item for item in payload["runners"] if item["runner"] == "codex"
    )
    claude_status = next(
        item for item in payload["runners"] if item["runner"] == "claude"
    )

    assert opencode_status["status"] == "unsupported"
    assert codex_status["status"] == "unsupported"
    assert claude_status["status"] == "unsupported"
    assert claude_status["primary_action"] == "guide"


def test_runner_status_endpoint_surfaces_needs_attention_for_detected_but_unlaunchable_runner(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": [],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )
    monkeypatch.setattr(server, "_runner_host_platform", lambda: ("linux", "x86_64"))
    monkeypatch.setattr(server, "_winget_available", lambda: False)
    monkeypatch.setattr(
        server,
        "_resolve_command_path",
        lambda command: "/tmp/opencode" if command == "opencode" else None,
    )
    monkeypatch.setattr(server, "_resolve_claude_cli_command", lambda: None)
    monkeypatch.setattr(server, "_runner_launch_probe", lambda runner: False)

    with TestClient(server.create_app()) as client:
        response = client.get("/api/runners/status")
        assert response.status_code == 200
        payload = response.json()

    opencode_status = next(
        item for item in payload["runners"] if item["runner"] == "opencode"
    )
    assert opencode_status["status"] == "needs_attention"
    assert opencode_status["executable_path"] == "/tmp/opencode"


def test_detect_runner_availability_excludes_unauthenticated_runner(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        server, "_runner_launch_probe", lambda runner: runner == "claude"
    )
    monkeypatch.setattr(server, "_runner_auth_probe", lambda runner: False)

    def auth_aware_detect() -> dict[str, object]:
        available_runners: list[str] = []
        for runner in cast(tuple[FixRunner, ...], ("opencode", "codex", "claude")):
            if server._runner_launch_probe(runner) and server._runner_auth_probe(
                runner
            ):
                available_runners.append(runner)
        return {
            "available_runners": available_runners,
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": "claude" in available_runners,
        }

    monkeypatch.setattr(server, "_detect_runner_availability", auth_aware_detect)

    payload = server._detect_runner_availability()

    assert payload["available_runners"] == []
    assert payload["supported_runners"] == ["opencode", "codex", "claude"]


def test_runner_status_endpoint_reports_authenticate_action_for_installed_runner_needing_auth(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": [],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )
    monkeypatch.setattr(server, "_runner_host_platform", lambda: ("darwin", "arm64"))
    monkeypatch.setattr(server, "_winget_available", lambda: False)
    monkeypatch.setattr(
        server,
        "_resolve_claude_cli_command",
        lambda: "/tmp/claude",
    )
    monkeypatch.setattr(server, "_resolve_command_path", lambda command: None)
    monkeypatch.setattr(
        server, "_runner_launch_probe", lambda runner: runner == "claude"
    )
    monkeypatch.setattr(server, "_runner_auth_probe", lambda runner: False)

    with TestClient(server.create_app()) as client:
        response = client.get("/api/runners/status")

    assert response.status_code == 200
    payload = response.json()
    claude_status = next(
        item for item in payload["runners"] if item["runner"] == "claude"
    )
    assert claude_status["status"] == "installed_needs_auth"
    assert claude_status["primary_action"] == "authenticate"
    assert claude_status["primary_action_label"] == "Authenticate"
    assert claude_status["auth_command"] == "claude"
    assert "Refresh" in claude_status["auth_instructions"]


def test_runner_status_endpoint_reports_authenticate_action_on_windows(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": [],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )
    monkeypatch.setattr(server, "_runner_host_platform", lambda: ("win32", "arm64"))
    monkeypatch.setattr(server, "_winget_available", lambda: False)
    monkeypatch.setattr(
        server,
        "_resolve_command_path",
        lambda command: (
            "C:/Users/test/.opencode/bin/opencode.exe"
            if command == "opencode"
            else None
        ),
    )
    monkeypatch.setattr(server, "_resolve_claude_cli_command", lambda: None)
    monkeypatch.setattr(
        server, "_runner_launch_probe", lambda runner: runner == "opencode"
    )
    monkeypatch.setattr(server, "_runner_auth_probe", lambda runner: False)

    with TestClient(server.create_app()) as client:
        response = client.get("/api/runners/status")

    assert response.status_code == 200
    payload = response.json()
    opencode_status = next(
        item for item in payload["runners"] if item["runner"] == "opencode"
    )
    assert opencode_status["status"] == "installed_needs_auth"
    assert opencode_status["primary_action"] == "authenticate"
    assert opencode_status["primary_action_label"] == "Authenticate"
    assert opencode_status["auth_command"] == "opencode auth login"


def test_launch_runner_auth_terminal_uses_powershell_on_windows(monkeypatch) -> None:
    launched: dict[str, object] = {}

    class DummyPopen:
        def __init__(self, command, **kwargs):
            launched["command"] = command
            launched["kwargs"] = kwargs

    monkeypatch.setattr(server.sys, "platform", "win32")
    monkeypatch.setattr(server.subprocess, "Popen", DummyPopen)
    monkeypatch.setattr(server.subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)
    monkeypatch.setattr(server, "_resolve_command_path", lambda command: None)

    server._launch_runner_auth_terminal("codex")

    assert launched["command"] == [
        "powershell.exe",
        "-NoExit",
        "-Command",
        "codex",
    ]
    assert launched["kwargs"]["creationflags"] == 16


def test_runner_auth_launch_endpoint_uses_runner_command_on_macos(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_build_runner_status_payload",
        lambda: {
            "available_runners": [],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
            "host_platform": "darwin",
            "host_arch": "arm64",
            "active_install_job_id": None,
            "runners": [
                {
                    "runner": "codex",
                    "status": "installed_needs_auth",
                    "status_label": "Authenticate",
                    "primary_action": "authenticate",
                    "primary_action_label": "Authenticate",
                    "guide_url": "https://developers.openai.com/codex/auth",
                    "installed": False,
                    "executable_path": "/tmp/codex",
                    "install_job": None,
                    "auth_command": "codex",
                    "auth_instructions": "Run the command in Terminal and then click Refresh.",
                }
            ],
        },
    )
    launched_commands: list[str] = []
    monkeypatch.setattr(
        server,
        "_launch_runner_auth_terminal",
        lambda runner: launched_commands.append(runner),
    )

    with TestClient(server.create_app()) as client:
        response = client.post("/api/runners/auth/launch", json={"runner": "codex"})

    assert response.status_code == 200
    assert launched_commands == ["codex"]


def test_runner_auth_command_uses_bare_codex_command() -> None:
    assert server._runner_auth_command("codex") == "codex"


def test_runner_auth_launch_command_uses_resolved_executable_path(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_resolve_command_path",
        lambda command: "/tmp/opencode/bin/opencode" if command == "opencode" else None,
    )

    assert server._runner_auth_launch_command("opencode") == (
        "/tmp/opencode/bin/opencode auth login"
    )


def test_runner_auth_probe_returns_false_when_status_command_errors(
    monkeypatch,
) -> None:
    monkeypatch.setattr(server, "_resolve_command_path", lambda command: "/tmp/codex")

    def raise_timeout(command: list[str], *, shell: bool = False):
        raise subprocess.TimeoutExpired(command, timeout=5)

    monkeypatch.setattr(server, "_run_install_subprocess", raise_timeout)

    assert server._runner_auth_probe("codex") is False


def test_runner_install_endpoint_rejects_guide_only_runners(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": [],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )
    monkeypatch.setattr(server, "_runner_host_platform", lambda: ("linux", "x86_64"))
    monkeypatch.setattr(server, "_winget_available", lambda: False)

    with TestClient(server.create_app()) as client:
        response = client.post("/api/runners/install", json={"runner": "opencode"})

    assert response.status_code == 409
    assert "guide" in response.text.lower()


def test_runner_install_endpoint_rejects_windows_claude_click_install(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": [],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )
    monkeypatch.setattr(server, "_runner_host_platform", lambda: ("win32", "arm64"))
    monkeypatch.setattr(server, "_resolve_command_path", lambda command: None)
    monkeypatch.setattr(server, "_resolve_claude_cli_command", lambda: None)

    with TestClient(server.create_app()) as client:
        response = client.post("/api/runners/install", json={"runner": "claude"})

    assert response.status_code == 409
    assert "does not support click-install" in response.text


def test_runner_install_endpoint_runs_install_job_for_supported_runner(
    monkeypatch,
) -> None:
    installed_runners: set[str] = set()

    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": sorted(installed_runners),
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": "claude" in installed_runners,
        },
    )
    monkeypatch.setattr(server, "_runner_host_platform", lambda: ("darwin", "arm64"))
    monkeypatch.setattr(server, "_winget_available", lambda: False)
    monkeypatch.setattr(server, "_resolve_command_path", lambda command: None)
    monkeypatch.setattr(server, "_resolve_claude_cli_command", lambda: None)
    monkeypatch.setattr(
        server, "_runner_launch_probe", lambda runner: runner in installed_runners
    )

    def fake_install_runner(runner: str, job: dict[str, object]) -> dict[str, object]:
        installed_runners.add(runner)
        return {"executable_path": f"/tmp/{runner}"}

    monkeypatch.setattr(server, "_perform_runner_install", fake_install_runner)

    with TestClient(server.create_app()) as client:
        response = client.post("/api/runners/install", json={"runner": "opencode"})
        assert response.status_code == 200

        deadline = time.monotonic() + 3.0
        install_job = None
        while time.monotonic() < deadline:
            status_response = client.get("/api/runners/status")
            assert status_response.status_code == 200
            payload = status_response.json()
            opencode_status = next(
                item for item in payload["runners"] if item["runner"] == "opencode"
            )
            install_job = opencode_status["install_job"]
            if install_job and install_job["state"] == "succeeded":
                break
            time.sleep(0.05)

    assert install_job is not None
    assert install_job["state"] == "succeeded"
    assert install_job["resolved_path"] == "/tmp/opencode"


def test_command_search_path_includes_common_gui_directories(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    search_entries = server._command_search_path().split(os.pathsep)

    assert "/opt/homebrew/bin" in search_entries
    assert str(Path.home() / ".local" / "bin") in search_entries


def test_resolve_command_path_finds_opencode_vendor_install(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    install_dir = tmp_path / ".opencode" / "bin"
    install_dir.mkdir(parents=True)
    binary = install_dir / "opencode"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)

    assert server._resolve_command_path("opencode") == str(binary)


def test_read_url_bytes_falls_back_to_curl_on_ssl_failure(monkeypatch) -> None:
    def raise_ssl_error(*args, **kwargs):
        raise urllib_error.URLError(
            ssl.SSLCertVerificationError("missing local issuer")
        )

    monkeypatch.setattr(server.urllib_request, "urlopen", raise_ssl_error)

    def fake_run(url: str, *, headers=None):
        assert url == "https://example.com/archive.tgz"
        assert headers is None
        return server.subprocess.CompletedProcess(
            ["curl", "-fsSL", url], 0, stdout=b"payload", stderr=b""
        )

    monkeypatch.setattr(server, "_run_download_subprocess", fake_run)

    assert server._read_url_bytes("https://example.com/archive.tgz") == b"payload"


def test_read_url_bytes_preserves_binary_payload_in_curl_fallback(monkeypatch) -> None:
    def raise_ssl_error(*args, **kwargs):
        raise urllib_error.URLError(
            ssl.SSLCertVerificationError("missing local issuer")
        )

    monkeypatch.setattr(server.urllib_request, "urlopen", raise_ssl_error)

    binary_payload = bytes([0x00, 0x7F, 0x80, 0xFF])

    def fake_run(url: str, *, headers=None):
        assert url == "https://example.com/archive.tgz"
        assert headers is None
        return server.subprocess.CompletedProcess(
            ["curl", "-fsSL", url],
            0,
            stdout=binary_payload,
            stderr=b"",
        )

    monkeypatch.setattr(server, "_run_download_subprocess", fake_run)

    assert server._read_url_bytes("https://example.com/archive.tgz") == binary_payload


def test_runner_models_endpoint_rejects_unavailable_runner(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": ["opencode"],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )

    with TestClient(server.create_app()) as client:
        response = client.get("/api/runners/models?runner=codex")
        assert response.status_code == 503
        assert "Runner 'codex' is not available" in response.text


def test_runner_models_endpoint_falls_back_when_codex_cache_is_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_detect_runner_availability",
        lambda: {
            "available_runners": ["codex"],
            "supported_runners": ["opencode", "codex", "claude"],
            "claude_code_available": False,
        },
    )

    def raise_missing_cache(runner: str, *, force_refresh: bool = False):
        assert runner == "codex"
        raise RuntimeError(
            "Codex model cache not found. Run `codex` once to initialise it."
        )

    monkeypatch.setattr(server, "_refresh_runner_models_cache", raise_missing_cache)
    monkeypatch.setattr(server, "_load_fix_preferences", lambda: ("codex", None, None))

    with TestClient(server.create_app()) as client:
        response = client.get("/api/runners/models?runner=codex")

    assert response.status_code == 200
    assert response.json() == {
        "runner": "codex",
        "models": [],
        "default_model": server._runner_default_model_id("codex"),
        "default_variant": "",
    }


def test_build_fix_command_uses_json_streaming() -> None:
    command = server._build_opencode_plot_fix_command(
        model="openai/gpt-5.3-codex",
        variant="high",
    )
    assert "--format" in command
    format_index = command.index("--format")
    assert command[format_index + 1] == "json"
    assert "--thinking" not in command
    assert "--agent" not in command
    assert command[-1] == server._build_codex_plot_fix_prompt()


def test_build_codex_plot_fix_prompt_references_actual_mcp_tool_names() -> None:
    prompt = server._build_codex_plot_fix_prompt()

    assert "get_pending_feedback_with_images" in prompt
    assert "get_pending_feedback" in prompt
    assert "get_plot_context" in prompt
    assert "submit_updated_script" in prompt
    assert "openplot_get_pending_feedback" not in prompt
    assert "openplot_get_plot_context" not in prompt
    assert "openplot_submit_updated_script" not in prompt


def test_build_opencode_fix_command_uses_resume_session() -> None:
    command = server._build_opencode_plot_fix_command(
        model="openai/gpt-5.3-codex",
        variant="high",
        resume_session_id="ses_123",
    )

    assert "--session" in command
    session_index = command.index("--session")
    assert command[session_index + 1] == "ses_123"


def test_opencode_fix_config_content_enables_openplot_mcp_tools() -> None:
    payload = json.loads(server._opencode_fix_config_content())
    mcp_command = payload["mcp"]["openplot"]["command"]
    assert isinstance(mcp_command, list)
    assert len(mcp_command) >= 1
    assert payload["mcp"]["openplot"]["enabled"] is True
    assert payload["tools"]["openplot_*"] is True


def test_opencode_fix_config_content_denies_builtin_question_tool() -> None:
    payload = json.loads(server._opencode_fix_config_content())

    assert payload["permission"]["question"] == "deny"


def test_opencode_plot_mode_config_only_disables_builtin_question_tool() -> None:
    payload = json.loads(server._opencode_question_tool_disabled_config_content())

    assert payload == {
        "$schema": "https://opencode.ai/config.json",
        "permission": {"question": "deny"},
    }


def test_runner_output_detects_opencode_question_tool_event() -> None:
    line = json.dumps(
        {
            "type": "tool_call",
            "part": {"type": "tool", "tool_name": "question", "name": "question"},
        }
    )

    assert server._runner_output_used_builtin_question_tool("opencode", f"{line}\n")


def test_build_codex_fix_command_skips_git_repo_check() -> None:
    command = server._build_codex_plot_fix_command(
        model="gpt-5.2-codex",
        variant="high",
    )
    assert "--skip-git-repo-check" in command
    mcp_cmd_args = [arg for arg in command if arg.startswith("mcp_servers.openplot.")]
    assert any("command=" in arg for arg in mcp_cmd_args)
    assert any("args=" in arg for arg in mcp_cmd_args)


def test_build_codex_fix_command_uses_resume_subcommand() -> None:
    command = server._build_codex_plot_fix_command(
        model="gpt-5.2-codex",
        variant="high",
        resume_session_id="019ce234-1eaa-7151-9a2c-a98071f65579",
    )

    command_name = Path(command[0]).name.lower()
    assert command_name in {"codex", "codex.cmd", "codex.exe"}
    assert command[1:3] == ["exec", "resume"]
    assert "--cd" not in command
    assert "--sandbox" not in command
    assert "019ce234-1eaa-7151-9a2c-a98071f65579" in command
    assert command[-1] == server._build_codex_plot_fix_prompt()


def test_build_claude_fix_command_uses_stream_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server, "_resolve_claude_cli_command", lambda: "claude")

    command = server._build_claude_plot_fix_command(
        model="claude-sonnet-4-6",
        variant="high",
        workspace_dir=tmp_path,
    )

    assert "--output-format" in command
    output_format_index = command.index("--output-format")
    assert command[output_format_index + 1] == "stream-json"
    assert "--effort" in command
    assert "--strict-mcp-config" in command

    assert "--add-dir" in command
    add_dir_index = command.index("--add-dir")
    assert Path(command[add_dir_index + 1]) == tmp_path.resolve()

    assert "--mcp-config" in command
    config_index = command.index("--mcp-config")
    config_path = Path(command[config_index + 1])
    assert config_path.exists()
    mcp_config = json.loads(config_path.read_text(encoding="utf-8"))
    openplot_server = mcp_config["mcpServers"]["openplot"]
    assert openplot_server["type"] == "stdio"
    assert isinstance(openplot_server["command"], str)
    assert isinstance(openplot_server["args"], list)


def test_build_claude_fix_command_uses_resume_session(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server, "_resolve_claude_cli_command", lambda: "claude")

    command = server._build_claude_plot_fix_command(
        model="claude-sonnet-4-6",
        variant="high",
        workspace_dir=tmp_path,
        resume_session_id="f326437b-19b6-42d6-b7ae-a025731e8f72",
    )

    assert "--resume" in command
    resume_index = command.index("--resume")
    assert command[resume_index + 1] == "f326437b-19b6-42d6-b7ae-a025731e8f72"


def test_build_claude_fix_command_disables_ask_user_question(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(server, "_resolve_claude_cli_command", lambda: "claude")

    command = server._build_claude_plot_fix_command(
        model="claude-sonnet-4-6",
        variant="high",
        workspace_dir=tmp_path,
    )

    assert "--disallowedTools" in command
    disallowed_tools_index = command.index("--disallowedTools")
    assert command[disallowed_tools_index + 1] == "AskUserQuestion"


@pytest.mark.anyio
async def test_run_claude_fix_iteration_retries_after_builtin_question_tool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(server, "_resolve_claude_cli_command", lambda: "claude")

    session = PlotSession(
        id="session-123", source_script_path=str(tmp_path / "plot.py")
    )
    job = FixJob(
        runner="claude",
        model="claude-sonnet-4-6",
        variant="high",
        session_id=session.id,
        workspace_dir=str(tmp_path),
        branch_id="branch-main",
        branch_name="main",
    )
    step = FixJobStep(index=0, annotation_id="annotation-1")

    commands: list[list[str]] = []
    cleared_sessions: list[tuple[str, str]] = []
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

    async def fake_run_fix_iteration_command(**kwargs):
        command = list(cast(list[str], kwargs["command"]))
        commands.append(command)
        if len(commands) == 1:
            step.exit_code = 1
            return (f"{question_tool_line}\n", "")
        step.exit_code = 0
        return ("done\n", "")

    monkeypatch.setattr(server, "_session_for_fix_job", lambda _job: session)
    monkeypatch.setattr(
        server, "_workspace_dir_for_fix_job", lambda _job, _session: tmp_path
    )
    monkeypatch.setattr(server, "_fix_runner_env_overrides", lambda _job, _session: {})
    monkeypatch.setattr(
        server, "_runner_session_id_for_session", lambda _session, _runner: "resume-123"
    )
    monkeypatch.setattr(
        server,
        "_clear_runner_session_id_for_session",
        lambda _session, runner: cleared_sessions.append((_session.id, runner)),
    )
    monkeypatch.setattr(
        server, "_run_fix_iteration_command", fake_run_fix_iteration_command
    )
    monkeypatch.setattr(
        server, "_extract_runner_session_id_from_output", lambda _runner, _stdout: None
    )
    monkeypatch.setattr(
        server,
        "_extract_runner_reported_error",
        lambda _runner, stdout_text, stderr_text: None,
    )

    await server._run_claude_fix_iteration(job, step)

    assert len(commands) == 2
    assert "--resume" in commands[0]
    assert "--resume" not in commands[1]
    assert cleared_sessions == [(session.id, "claude")]
    assert "--disallowedTools" in commands[1]
    assert "AskUserQuestion" in commands[1]
    assert "Do not use AskUserQuestion" in commands[1][2]


def test_workspace_dir_for_fix_job_prefers_session_context(tmp_path: Path) -> None:
    session_workspace = tmp_path / "session-workspace"
    session_workspace.mkdir(parents=True)
    script_path = session_workspace / "plot.py"
    script_path.write_text("print('ok')\n")

    session = PlotSession(source_script_path=str(script_path))
    job = FixJob(
        model="openai/gpt-5.3-codex",
        branch_id="branch-main",
        branch_name="main",
        workspace_dir=str(tmp_path / "runtime" / "fix_runner" / "job-id"),
    )

    resolved = server._workspace_dir_for_fix_job(job, session)
    assert resolved == session_workspace.resolve()


def test_fix_runner_env_overrides_include_runtime_shims(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime" / "fix_runner" / "job-123"
    session = PlotSession(id="session-123")
    job = FixJob(
        model="openai/gpt-5.3-codex",
        branch_id="branch-main",
        branch_name="main",
        session_id=session.id,
        workspace_dir=str(runtime_dir),
    )

    monkeypatch.setattr(
        server,
        "_backend_url_from_port_file",
        lambda: "http://127.0.0.1:17623",
    )

    overrides = server._fix_runner_env_overrides(job, session)

    assert overrides["OPENPLOT_SESSION_ID"] == "session-123"
    assert overrides["OPENPLOT_SERVER_URL"] == "http://127.0.0.1:17623"
    assert (
        json.loads(overrides["OPENCODE_CONFIG_CONTENT"])["tools"]["openplot_*"] is True
    )
    assert (
        json.loads(overrides["OPENCODE_CONFIG_CONTENT"])["permission"]["question"]
        == "deny"
    )
    assert "PYTHONPATH" in overrides

    path_parts = overrides["PATH"].split(os.pathsep)
    assert path_parts[0] == str((runtime_dir / "bin").resolve())
    if sys.platform == "win32":
        assert (runtime_dir / "bin" / "openplot.cmd").exists()
        assert (runtime_dir / "bin" / "uv.cmd").exists()
    else:
        assert (runtime_dir / "bin" / "openplot").exists()
        assert (runtime_dir / "bin" / "uv").exists()


def test_resolve_openplot_mcp_launch_command_for_python_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    python_path = tmp_path / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\nexit 0\n")
    python_path.chmod(0o755)

    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(server.sys, "executable", str(python_path.resolve()))
    command = server._resolve_openplot_mcp_launch_command()

    assert command == [str(python_path.resolve()), "-m", "openplot.cli", "mcp"]


@pytest.mark.skipif(sys.platform == "win32", reason="macOS .app bundle path test")
def test_resolve_openplot_mcp_launch_command_for_packaged_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    launcher_path = tmp_path / "OpenPlot.app" / "Contents" / "MacOS" / "OpenPlot"
    launcher_path.parent.mkdir(parents=True)
    launcher_path.write_text("#!/bin/sh\nexit 0\n")
    launcher_path.chmod(0o755)

    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(server.sys, "executable", str(launcher_path.resolve()))
    command = server._resolve_openplot_mcp_launch_command()

    assert command == [str(launcher_path.resolve()), "--internal-run-mcp"]


def test_resolve_openplot_mcp_launch_command_prefers_virtualenv_python(
    monkeypatch,
    tmp_path: Path,
) -> None:
    venv_python = tmp_path / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\nexit 0\n")
    venv_python.chmod(0o755)

    fallback_python = tmp_path / "fallback" / "python"
    fallback_python.parent.mkdir(parents=True)
    fallback_python.write_text("#!/bin/sh\nexit 0\n")
    fallback_python.chmod(0o755)

    monkeypatch.setenv("VIRTUAL_ENV", str((tmp_path / "venv").resolve()))
    monkeypatch.setattr(server.sys, "executable", str(fallback_python.resolve()))

    command = server._resolve_openplot_mcp_launch_command()
    assert command == [str(venv_python.resolve()), "-m", "openplot.cli", "mcp"]


def test_resolve_openplot_mcp_launch_command_prefers_windows_virtualenv_python(
    monkeypatch,
    tmp_path: Path,
) -> None:
    venv_python = tmp_path / "venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("placeholder")

    fallback_python = tmp_path / "fallback" / "python.exe"
    fallback_python.parent.mkdir(parents=True)
    fallback_python.write_text("placeholder")

    monkeypatch.setenv("VIRTUAL_ENV", str((tmp_path / "venv").resolve()))
    monkeypatch.setattr(server.sys, "executable", str(fallback_python.resolve()))
    monkeypatch.setattr(
        server.os, "access", lambda path, mode: Path(path) == venv_python
    )

    command = server._resolve_openplot_mcp_launch_command()
    assert command == [str(venv_python.resolve()), "-m", "openplot.cli", "mcp"]


def test_claude_models_cache_uses_pinned_defaults() -> None:
    models = server._refresh_claude_models_cache(force_refresh=True)
    ids = [entry.id for entry in models]
    assert ids == [
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-haiku-4-5",
    ]

    haiku = next(entry for entry in models if entry.id == "claude-haiku-4-5")
    assert haiku.variants == []


def test_parse_opencode_json_event_line() -> None:
    parsed = server._parse_opencode_json_event_line(
        '{"type":"message","content":"hello"}\n'
    )
    assert parsed == {"type": "message", "content": "hello"}
    assert server._parse_opencode_json_event_line("not-json\n") is None


def test_extract_runner_session_id_from_output() -> None:
    opencode_output = (
        '{"type":"step_start","sessionID":"ses_abc123"}\n'
        '{"type":"text","part":{"text":"ok"}}\n'
    )
    codex_output = (
        '{"type":"thread.started","thread_id":"019ce234-1eaa-7151-9a2c-a98071f65579"}\n'
    )
    claude_output = '{"type":"system","subtype":"init","session_id":"f326437b-19b6-42d6-b7ae-a025731e8f72"}\n'

    assert (
        server._extract_runner_session_id_from_output("opencode", opencode_output)
        == "ses_abc123"
    )
    assert (
        server._extract_runner_session_id_from_output("codex", codex_output)
        == "019ce234-1eaa-7151-9a2c-a98071f65579"
    )
    assert (
        server._extract_runner_session_id_from_output("claude", claude_output)
        == "f326437b-19b6-42d6-b7ae-a025731e8f72"
    )


def test_extract_runner_reported_error_from_claude_result() -> None:
    output = '{"type":"result","is_error":true,"result":"invalid session id"}\n'

    assert (
        server._extract_runner_reported_error(
            "claude",
            stdout_text=output,
            stderr_text="",
        )
        == "invalid session id"
    )


def test_consume_fix_stream_handles_long_json_lines(monkeypatch) -> None:
    long_text = "x" * 100_000
    line = (
        json.dumps(
            {
                "type": "text",
                "part": {
                    "type": "text",
                    "text": long_text,
                },
            }
        )
        + "\n"
    )

    reader = _ChunkedBytesReader(line.encode("utf-8"), chunk_size=2048)
    sink: list[str] = []

    captured_logs: list[dict] = []

    async def fake_broadcast_fix_job_log(**kwargs):
        captured_logs.append(kwargs)

    monkeypatch.setattr(server, "_broadcast_fix_job_log", fake_broadcast_fix_job_log)
    monkeypatch.setattr(server, "_terminate_fix_process", lambda process: None)

    job = FixJob(
        model="openai/gpt-5.3-codex",
        branch_id="branch-main",
        branch_name="main",
    )
    step = FixJobStep(index=1, annotation_id="ann-1")

    asyncio.run(
        server._consume_fix_stream(
            job=job,
            step=step,
            runner="opencode",
            process=cast(asyncio.subprocess.Process, object()),
            stream_name="stdout",
            stream=cast(asyncio.StreamReader, reader),
            sink=sink,
        )
    )

    assert "".join(sink) == line
    assert len(captured_logs) == 1
    assert captured_logs[0]["chunk"] == line
    assert captured_logs[0]["parsed"] is not None


def test_reconcile_stale_active_fix_job_marks_failed() -> None:
    job = FixJob(
        model="openai/gpt-5.3-codex",
        branch_id="branch-main",
        branch_name="main",
        status=FixJobStatus.running,
    )
    job.steps.append(
        FixJobStep(
            index=1,
            annotation_id="ann-1",
            status=FixStepStatus.running,
            started_at=job.created_at,
        )
    )

    prev_jobs = dict(server._fix_jobs)
    prev_tasks = dict(server._fix_job_tasks)
    prev_processes = dict(server._fix_job_processes)
    prev_active_by_session = dict(server._active_fix_job_ids_by_session)

    try:
        server._fix_jobs.clear()
        server._fix_job_tasks.clear()
        server._fix_job_processes.clear()
        server._active_fix_job_ids_by_session.clear()

        session_key = "session-main"
        job.session_id = session_key
        server._fix_jobs[job.id] = job
        server._active_fix_job_ids_by_session[session_key] = job.id

        asyncio.run(server._reconcile_active_fix_job_state())

        assert server._active_fix_job_ids_by_session == {}
        assert job.status == FixJobStatus.failed
        assert job.finished_at is not None
        assert job.last_error is not None
        assert job.steps[-1].status == FixStepStatus.failed
        assert job.steps[-1].finished_at is not None
    finally:
        server._fix_jobs.clear()
        server._fix_jobs.update(prev_jobs)
        server._fix_job_tasks.clear()
        server._fix_job_tasks.update(prev_tasks)
        server._fix_job_processes.clear()
        server._fix_job_processes.update(prev_processes)
        server._active_fix_job_ids_by_session.clear()
        server._active_fix_job_ids_by_session.update(prev_active_by_session)
