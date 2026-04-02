"""Runner helper implementations extracted from openplot.server."""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import ssl
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Mapping, cast
from urllib import error as urllib_error
from urllib import request as urllib_request

from .models import FixRunner, OpencodeModelOption, PlotModeState, PlotSession


def _runner_default_model_id(server_module: ModuleType, runner: FixRunner) -> str:
    if runner == "codex":
        return server_module._default_codex_model
    if runner == "claude":
        return server_module._default_claude_model
    return server_module._default_opencode_model


def _normalize_runner_session_id(
    server_module: ModuleType, value: object
) -> str | None:
    candidate = server_module._as_string(value)
    if candidate is None:
        return None
    if len(candidate) > 256:
        return None
    return candidate


def _runner_session_id_for_session(
    server_module: ModuleType,
    session: PlotSession,
    runner: FixRunner,
) -> str | None:
    return server_module._normalize_runner_session_id(
        session.runner_session_ids.get(runner)
    )


def _set_runner_session_id_for_session(
    server_module: ModuleType,
    session: PlotSession,
    *,
    runner: FixRunner,
    session_id: str,
) -> None:
    normalized_session_id = server_module._normalize_runner_session_id(session_id)
    if normalized_session_id is None:
        return
    if session.runner_session_ids.get(runner) == normalized_session_id:
        return
    session.runner_session_ids[runner] = normalized_session_id
    server_module._touch_session(session)
    with suppress(OSError):
        server_module._save_session_snapshot(session)


def _clear_runner_session_id_for_session(
    server_module: ModuleType,
    session: PlotSession,
    runner: FixRunner,
) -> None:
    if runner not in session.runner_session_ids:
        return
    session.runner_session_ids.pop(runner, None)
    server_module._touch_session(session)
    with suppress(OSError):
        server_module._save_session_snapshot(session)


def _runner_session_id_for_plot_mode(
    server_module: ModuleType,
    state: PlotModeState,
    runner: FixRunner,
) -> str | None:
    return server_module._normalize_runner_session_id(
        state.runner_session_ids.get(runner)
    )


def _set_runner_session_id_for_plot_mode(
    server_module: ModuleType,
    state: PlotModeState,
    *,
    runner: FixRunner,
    session_id: str,
) -> None:
    normalized_session_id = server_module._normalize_runner_session_id(session_id)
    if normalized_session_id is None:
        return
    if state.runner_session_ids.get(runner) == normalized_session_id:
        return
    state.runner_session_ids[runner] = normalized_session_id
    server_module._touch_plot_mode(state)


def _clear_runner_session_id_for_plot_mode(
    server_module: ModuleType,
    state: PlotModeState,
    runner: FixRunner,
) -> None:
    if runner not in state.runner_session_ids:
        return
    state.runner_session_ids.pop(runner, None)
    server_module._touch_plot_mode(state)


def _runner_tools_root(server_module: ModuleType) -> Path:
    path = server_module._state_root() / "tools"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _managed_command_path(server_module: ModuleType, command: str) -> str | None:
    if command != "codex":
        return None
    candidate = server_module._runner_tools_root() / "codex" / "current" / "codex"
    if not candidate.exists():
        return None
    return str(candidate)


def _resolve_command_path(server_module: ModuleType, command: str) -> str | None:
    managed = server_module._managed_command_path(command)
    if managed:
        return managed
    return server_module.shutil.which(
        command, path=server_module._command_search_path()
    )


def _subprocess_env(
    server_module: ModuleType,
    *,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = server_module.os.environ.copy()
    env["PATH"] = server_module._command_search_path()
    if overrides:
        env.update(overrides)
    return env


def _no_window_kwargs(server_module: ModuleType) -> dict[str, object]:
    if server_module.sys.platform == "win32":
        return {"creationflags": server_module.subprocess.CREATE_NO_WINDOW}
    return {}


def _hidden_window_kwargs(server_module: ModuleType) -> dict[str, object]:
    if server_module.sys.platform == "win32":
        si = server_module.subprocess.STARTUPINFO()
        si.dwFlags |= server_module.subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = server_module.subprocess.SW_HIDE
        return {"startupinfo": si}
    return {}


def _shell_join(server_module: ModuleType, parts: list[str]) -> str:
    return " ".join(server_module.shlex.quote(part) for part in parts)


def _backend_url_from_port_file(server_module: ModuleType) -> str | None:
    try:
        raw_port = server_module._read_file_text(server_module._port_file).strip()
    except OSError:
        return None

    if not raw_port:
        return None

    try:
        port = int(raw_port)
    except ValueError:
        return None

    if port <= 0:
        return None

    return f"http://127.0.0.1:{port}"


def _resolve_openplot_mcp_launch_command(server_module: ModuleType) -> list[str]:
    executable = Path(server_module.sys.executable).expanduser()
    if server_module._is_openplot_app_launcher_path(executable):
        return [str(executable), "--internal-run-mcp"]

    virtual_env = os.getenv("VIRTUAL_ENV")
    if virtual_env:
        venv_root = Path(virtual_env).expanduser()
        venv_candidates = [
            venv_root / "bin" / "python",
            venv_root / "bin" / "python3",
            venv_root / "Scripts" / "python.exe",
            venv_root / "Scripts" / "python",
        ]
        for venv_python in venv_candidates:
            if venv_python.is_file() and os.access(venv_python, os.X_OK):
                return [str(venv_python), "-m", "openplot.cli", "mcp"]

    return [str(executable), "-m", "openplot.cli", "mcp"]


def _write_fix_runner_shims(server_module: ModuleType, runtime_dir: Path) -> Path:
    shim_bin = runtime_dir / "bin"
    shim_bin.mkdir(parents=True, exist_ok=True)

    mcp_command = server_module._resolve_openplot_mcp_launch_command()

    if server_module.sys.platform == "win32":
        server_module._write_fix_runner_shims_windows(shim_bin, mcp_command)
    else:
        server_module._write_fix_runner_shims_unix(shim_bin, mcp_command)

    return shim_bin


def _write_fix_runner_shims_unix(
    server_module: ModuleType,
    shim_bin: Path,
    mcp_command: list[str],
) -> None:
    openplot_script = "\n".join(
        [
            "#!/bin/sh",
            "set -e",
            'if [ "$#" -ge 1 ] && [ "$1" = "mcp" ]; then',
            "  shift",
            f'  exec {server_module._shell_join(mcp_command)} "$@"',
            "fi",
            'echo "openplot shim supports only the mcp subcommand" >&2',
            "exit 2",
            "",
        ]
    )
    openplot_path = shim_bin / "openplot"
    openplot_path.write_text(openplot_script, encoding="utf-8")
    openplot_path.chmod(0o755)

    real_uv = server_module._resolve_command_path("uv")
    uv_script_lines = [
        "#!/bin/sh",
        "set -e",
        'if [ "$#" -ge 1 ] && [ "$1" = "run" ]; then',
        "  shift",
        '  if [ "$#" -eq 0 ]; then',
        "    echo 'uv shim: missing command after \"run\"' >&2",
        "    exit 2",
        "  fi",
        '  exec "$@"',
        "fi",
    ]

    if real_uv:
        uv_script_lines.extend(
            [
                f'exec {server_module.shlex.quote(real_uv)} "$@"',
                "",
            ]
        )
    else:
        uv_script_lines.extend(
            [
                "echo 'uv shim supports only the \"run\" command when uv is unavailable' >&2",
                "exit 2",
                "",
            ]
        )

    uv_path = shim_bin / "uv"
    uv_path.write_text("\n".join(uv_script_lines), encoding="utf-8")
    uv_path.chmod(0o755)


def _write_fix_runner_shims_windows(
    server_module: ModuleType,
    shim_bin: Path,
    mcp_command: list[str],
) -> None:
    mcp_cmd_line = server_module.subprocess.list2cmdline(mcp_command)
    openplot_script = "\r\n".join(
        [
            "@echo off",
            'if /i "%~1"=="mcp" (',
            f"    {mcp_cmd_line}",
            "    exit /b %errorlevel%",
            ")",
            "echo openplot shim supports only the mcp subcommand 1>&2",
            "exit /b 2",
            "",
        ]
    )
    openplot_path = shim_bin / "openplot.cmd"
    openplot_path.write_text(openplot_script, encoding="utf-8")

    real_uv = server_module._resolve_command_path("uv")
    if real_uv:
        uv_script = "\r\n".join(
            [
                "@echo off",
                'if /i "%~1"=="run" (',
                "    shift",
                "    %1 %2 %3 %4 %5 %6 %7 %8 %9",
                "    exit /b %errorlevel%",
                ")",
                f"{server_module.subprocess.list2cmdline([real_uv])} %*",
                "exit /b %errorlevel%",
                "",
            ]
        )
    else:
        uv_script = "\r\n".join(
            [
                "@echo off",
                'if /i "%~1"=="run" (',
                "    shift",
                "    %1 %2 %3 %4 %5 %6 %7 %8 %9",
                "    exit /b %errorlevel%",
                ")",
                "echo uv shim supports only the run command when uv is unavailable 1>&2",
                "exit /b 2",
                "",
            ]
        )
    uv_path = shim_bin / "uv.cmd"
    uv_path.write_text(uv_script, encoding="utf-8")


def _resolve_claude_cli_command(server_module: ModuleType) -> str | None:
    for command in ("claude", "claude-code"):
        resolved = server_module._resolve_command_path(command)
        if resolved:
            return resolved
    return None


def _runner_launch_probe(server_module: ModuleType, runner: FixRunner) -> bool:
    command = (
        server_module._resolve_claude_cli_command()
        if runner == "claude"
        else server_module._resolve_command_path(runner)
    )
    if not command:
        return False
    try:
        result = server_module._run_install_subprocess([command, "--version"])
    except Exception:
        return False
    return result.returncode == 0


def _opencode_auth_file_path(server_module: ModuleType) -> Path:
    return server_module.Path.home() / ".local" / "share" / "opencode" / "auth.json"


def _opencode_auth_file_has_credentials(server_module: ModuleType) -> bool:
    path = server_module._opencode_auth_file_path()
    if not path.exists():
        return False
    try:
        payload = server_module.json.loads(server_module._read_file_text(path))
    except (OSError, server_module.json.JSONDecodeError, UnicodeDecodeError):
        return False
    if isinstance(payload, dict):
        return any(bool(value) for value in payload.values())
    if isinstance(payload, list):
        return len(payload) > 0
    return bool(payload)


def _opencode_auth_list_has_credentials(
    server_module: ModuleType,
    output: str,
) -> bool:
    normalized = output.strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    return not any(
        token in lowered
        for token in (
            "no authenticated providers",
            "no providers configured",
            "no credentials found",
        )
    )


def _runner_auth_command(server_module: ModuleType, runner: FixRunner) -> str:
    if runner == "claude":
        return "claude"
    if runner == "codex":
        return "codex"
    return "opencode auth login"


def _runner_auth_launch_parts(
    server_module: ModuleType, runner: FixRunner
) -> list[str]:
    executable = (
        server_module._resolve_claude_cli_command()
        if runner == "claude"
        else server_module._resolve_command_path(runner)
    ) or ("claude" if runner == "claude" else runner)
    if runner == "claude":
        return [executable]
    if runner == "codex":
        return [executable]
    return [executable, "auth", "login"]


def _runner_auth_launch_command(server_module: ModuleType, runner: FixRunner) -> str:
    return server_module._shell_join(server_module._runner_auth_launch_parts(runner))


def _powershell_quote(server_module: ModuleType, text: str) -> str:
    escaped = text.replace("`", "``").replace('"', '`"')
    return f'"{escaped}"'


def _runner_auth_windows_command(server_module: ModuleType, runner: FixRunner) -> str:
    parts = server_module._runner_auth_launch_parts(runner)
    executable, *args = parts
    if any(token in executable for token in ("/", "\\", " ")):
        rendered_executable = f"& {server_module._powershell_quote(executable)}"
    else:
        rendered_executable = executable
    rendered_args = [
        server_module._powershell_quote(arg)
        if any(token in arg for token in (" ", '"', "&"))
        else arg
        for arg in args
    ]
    return " ".join([rendered_executable, *rendered_args])


def _runner_auth_guide_url(server_module: ModuleType, runner: FixRunner) -> str:
    if runner == "claude":
        return "https://code.claude.com/docs/en/authentication"
    if runner == "codex":
        return "https://developers.openai.com/codex/auth"
    return "https://opencode.ai/docs/providers"


def _runner_auth_instructions(
    server_module: ModuleType,
    runner: FixRunner,
    *,
    terminal_launch_supported: bool,
) -> str:
    command = server_module._runner_auth_command(runner)
    if not terminal_launch_supported:
        return (
            f'Open a terminal and run "{command}". '
            "Finish the sign-in steps there, then come back to OpenPlot and click Refresh."
        )
    return (
        f'OpenPlot will open Terminal and run "{command}" for you. '
        "Finish the sign-in steps there, close Terminal, then come back here and click Refresh."
    )


def _runner_auth_probe(server_module: ModuleType, runner: FixRunner) -> bool:
    if runner == "claude":
        command = server_module._resolve_claude_cli_command()
        if not command:
            return False
        try:
            result = server_module._run_install_subprocess(
                [command, "auth", "status", "--text"]
            )
        except Exception:
            return False
        return result.returncode == 0

    command = server_module._resolve_command_path(runner)
    if not command:
        return False

    if runner == "codex":
        try:
            result = server_module._run_install_subprocess([command, "login", "status"])
        except Exception:
            return False
        return result.returncode == 0

    if server_module._opencode_auth_file_has_credentials():
        return True
    try:
        result = server_module._run_install_subprocess([command, "auth", "list"])
    except Exception:
        return False
    return result.returncode == 0 and server_module._opencode_auth_list_has_credentials(
        result.stdout
    )


def _runner_auth_launch_supported(
    server_module: ModuleType, host_platform: str
) -> bool:
    return host_platform in {"darwin", "win32"}


def _apple_script_quote(server_module: ModuleType, text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _launch_runner_auth_terminal(server_module: ModuleType, runner: FixRunner) -> None:
    if server_module.sys.platform == "win32":
        command = server_module._runner_auth_windows_command(runner)
        try:
            server_module.subprocess.Popen(
                ["powershell.exe", "-NoExit", "-Command", command],
                env=server_module._subprocess_env(),
                creationflags=getattr(
                    server_module.subprocess, "CREATE_NEW_CONSOLE", 0
                ),
                stdout=server_module.subprocess.DEVNULL,
                stderr=server_module.subprocess.DEVNULL,
            )
        except OSError as exc:
            raise RuntimeError(
                "Failed to launch PowerShell for runner authentication"
            ) from exc
        return

    command = server_module._runner_auth_launch_command(runner)
    if server_module.sys.platform != "darwin":
        raise RuntimeError(
            "Launching authentication in Terminal is only supported on macOS and Windows"
        )

    result = server_module.run_text_subprocess(
        [
            "osascript",
            "-e",
            'tell application "Terminal" to activate',
            "-e",
            f'tell application "Terminal" to do script {server_module._apple_script_quote(command)}',
        ],
        env=server_module._subprocess_env(),
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        raise RuntimeError(
            stderr or stdout or "Failed to launch Terminal for runner authentication"
        )


def _detect_runner_availability(server_module: ModuleType) -> dict[str, object]:
    opencode_available = server_module._runner_launch_probe(
        "opencode"
    ) and server_module._runner_auth_probe("opencode")
    codex_available = server_module._runner_launch_probe(
        "codex"
    ) and server_module._runner_auth_probe("codex")
    claude_code_available = server_module._runner_launch_probe(
        "claude"
    ) and server_module._runner_auth_probe("claude")

    available_runners: list[FixRunner] = []
    if opencode_available:
        available_runners.append("opencode")
    if codex_available:
        available_runners.append("codex")
    if claude_code_available:
        available_runners.append("claude")

    return {
        "available_runners": available_runners,
        "supported_runners": ["opencode", "codex", "claude"],
        "claude_code_available": claude_code_available,
    }


def _runner_host_platform(server_module: ModuleType) -> tuple[str, str]:
    machine = server_module.platform.machine().strip().lower() or "unknown"
    if server_module.sys.platform == "darwin":
        return "darwin", machine
    if server_module.os.name == "nt":
        return "win32", machine
    if server_module.sys.platform.startswith("linux"):
        return "linux", machine
    return server_module.sys.platform, machine


def _winget_available(server_module: ModuleType) -> bool:
    if server_module.os.name != "nt":
        return False
    return server_module._is_command_available("winget")


def _runner_guide_url(server_module: ModuleType, runner: FixRunner) -> str:
    if runner == "claude":
        return (
            "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview"
        )
    if runner == "codex":
        return "https://developers.openai.com/codex"
    return "https://opencode.ai/docs"


def _runner_install_supported(
    server_module: ModuleType,
    *,
    runner: FixRunner,
    host_platform: str,
    host_arch: str,
) -> bool:
    _ = runner
    normalized_arch = host_arch.lower()
    if host_platform == "darwin" and normalized_arch in {"arm64", "aarch64"}:
        return True
    return False


def _runner_default_status(
    server_module: ModuleType,
    *,
    runner: FixRunner,
    host_platform: str,
    host_arch: str,
) -> tuple[str, str, str, str]:
    _ = runner
    if host_platform == "darwin" and host_arch.lower() in {"arm64", "aarch64"}:
        return "available_to_install", "Available to install", "install", "Install"
    if host_platform == "win32":
        return "unsupported", "Guide available", "guide", "See guide"
    return "manual", "Guide available", "guide", "See guide"


def _runner_install_job_snapshot(
    server_module: ModuleType,
    job_id: str | None,
) -> dict[str, object] | None:
    if not job_id:
        return None
    with server_module._runner_install_jobs_lock:
        job = server_module._runner_install_jobs.get(job_id)
        if job is None:
            return None
        return dict(job)


def _latest_runner_install_job_snapshot(
    server_module: ModuleType,
    runner: FixRunner,
) -> dict[str, object] | None:
    with server_module._runner_install_jobs_lock:
        matching_jobs = [
            dict(job)
            for job in server_module._runner_install_jobs.values()
            if job.get("runner") == runner
        ]
    if not matching_jobs:
        return None
    matching_jobs.sort(key=lambda job: str(job.get("created_at") or ""))
    return matching_jobs[-1]


def _build_runner_status_payload(server_module: ModuleType) -> dict[str, object]:
    availability = server_module._detect_runner_availability()
    available_runners = cast(
        list[FixRunner], availability.get("available_runners") or []
    )
    supported_runners = cast(
        list[FixRunner],
        availability.get("supported_runners") or ["opencode", "codex", "claude"],
    )
    host_platform, host_arch = server_module._runner_host_platform()
    active_job = server_module._runner_install_job_snapshot(
        server_module._active_runner_install_job_id
    )

    runners: list[dict[str, object]] = []
    for runner in supported_runners:
        latest_job = server_module._latest_runner_install_job_snapshot(runner)
        latest_job_state = str(latest_job.get("state")) if latest_job else None
        resolved_path = (
            server_module._resolve_claude_cli_command()
            if runner == "claude"
            else server_module._resolve_command_path(runner)
        )
        auth_command: str | None = None
        auth_instructions: str | None = None
        install_supported = server_module._runner_install_supported(
            runner=runner,
            host_platform=host_platform,
            host_arch=host_arch,
        )
        can_launch_auth = server_module._runner_auth_launch_supported(host_platform)
        is_installed = runner in available_runners
        status, status_label, primary_action, primary_action_label = (
            server_module._runner_default_status(
                runner=runner,
                host_platform=host_platform,
                host_arch=host_arch,
            )
        )
        if is_installed:
            status = "installed"
            status_label = "Installed"
            primary_action = "none"
            primary_action_label = "Installed"
        elif latest_job_state in {"queued", "running"}:
            status = "installing"
            status_label = "Installing"
            primary_action = "none"
            primary_action_label = "Installing"
        elif resolved_path:
            if server_module._runner_launch_probe(runner):
                status = "installed_needs_auth"
                status_label = "Sign-in required"
                primary_action = "authenticate" if can_launch_auth else "guide"
                primary_action_label = (
                    "Authenticate" if can_launch_auth else "See guide"
                )
                auth_command = server_module._runner_auth_command(runner)
                auth_instructions = server_module._runner_auth_instructions(
                    runner,
                    terminal_launch_supported=can_launch_auth,
                )
            else:
                status = "needs_attention"
                status_label = "Needs attention"
                primary_action = "guide"
                primary_action_label = "See guide"
        elif latest_job_state == "failed":
            primary_action = "install" if install_supported else "guide"
            primary_action_label = "Retry" if install_supported else "See guide"
            status = "needs_attention"
            status_label = "Needs attention"

        runners.append(
            {
                "runner": runner,
                "status": status,
                "status_label": status_label,
                "primary_action": primary_action,
                "primary_action_label": primary_action_label,
                "guide_url": (
                    server_module._runner_auth_guide_url(runner)
                    if status == "installed_needs_auth"
                    else server_module._runner_guide_url(runner)
                ),
                "installed": is_installed or resolved_path is not None,
                "executable_path": resolved_path,
                "install_job": latest_job,
                "auth_command": auth_command,
                "auth_instructions": auth_instructions,
            }
        )

    return {
        "available_runners": available_runners,
        "supported_runners": supported_runners,
        "claude_code_available": availability.get("claude_code_available", False),
        "host_platform": host_platform,
        "host_arch": host_arch,
        "active_install_job_id": active_job.get("id") if active_job else None,
        "runners": runners,
    }


def _create_runner_install_job(
    server_module: ModuleType,
    runner: FixRunner,
    *,
    runtime: object | None = None,
) -> dict[str, object]:
    resolved_runtime = (
        runtime or server_module._bound_runtime or server_module.get_shared_runtime()
    )

    with server_module._runner_install_jobs_lock:
        active_job = server_module._runner_install_jobs.get(
            server_module._active_runner_install_job_id or ""
        )
        if active_job is not None and active_job.get("state") in {"queued", "running"}:
            raise server_module.HTTPException(
                status_code=409,
                detail="Another runner install is already in progress.",
            )

        job = {
            "id": server_module.uuid.uuid4().hex,
            "runner": runner,
            "state": "queued",
            "logs": [f"Queued install for {runner}."],
            "error": None,
            "created_at": server_module.datetime.now(
                server_module.timezone.utc
            ).isoformat(),
            "started_at": None,
            "finished_at": None,
        }
        server_module._runner_install_jobs[str(job["id"])] = job
        server_module._active_runner_install_job_id = str(job["id"])
        server_module.threading.Thread(
            target=server_module._run_runner_install_job,
            args=(str(job["id"]), resolved_runtime),
            name=f"runner-install-{runner}",
            daemon=True,
        ).start()
        return dict(job)


def _update_runner_install_job(
    server_module: ModuleType,
    job_id: str,
    **updates: object,
) -> dict[str, object] | None:
    with server_module._runner_install_jobs_lock:
        job = server_module._runner_install_jobs.get(job_id)
        if job is None:
            return None
        job.update(updates)
        if (
            job.get("state") in {"succeeded", "failed"}
            and server_module._active_runner_install_job_id == job_id
        ):
            server_module._active_runner_install_job_id = None
        return dict(job)


def _append_runner_install_log(
    server_module: ModuleType, job_id: str, message: str
) -> None:
    with server_module._runner_install_jobs_lock:
        job = server_module._runner_install_jobs.get(job_id)
        if job is None:
            return
        logs = cast(list[str], job.setdefault("logs", []))
        logs.append(message)
        if len(logs) > 200:
            del logs[:-200]


def _run_install_subprocess(
    server_module: ModuleType,
    command: list[str],
    *,
    shell: bool = False,
):
    no_window_kwargs = server_module._no_window_kwargs()
    creationflags = cast(int, no_window_kwargs.get("creationflags", 0))
    if shell:
        return server_module.run_text_subprocess(
            command[0],
            shell=True,
            check=False,
            timeout=900,
            env=server_module._subprocess_env(),
            creationflags=creationflags,
        )
    return server_module.run_text_subprocess(
        command,
        check=False,
        timeout=900,
        env=server_module._subprocess_env(),
        creationflags=creationflags,
    )


def _resolve_runner_executable_path(
    server_module: ModuleType, runner: FixRunner
) -> str | None:
    if runner == "claude":
        return server_module._resolve_claude_cli_command()
    return server_module._resolve_command_path(runner)


def _install_runner_via_script(
    server_module: ModuleType,
    *,
    runner: FixRunner,
    script_url: str,
    job_id: str,
) -> dict[str, object]:
    server_module._append_runner_install_log(
        job_id, f"Running official installer from {script_url}"
    )
    if server_module.os.name == "nt":
        raise RuntimeError(
            f"{runner} script installer is not supported on this platform"
        )
    result = server_module._run_install_subprocess(
        [f"curl -fsSL {server_module.shlex.quote(script_url)} | bash"],
        shell=True,
    )
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if stdout:
        server_module._append_runner_install_log(job_id, stdout[-1000:])
    if stderr:
        server_module._append_runner_install_log(job_id, stderr[-1000:])
    if result.returncode != 0:
        raise RuntimeError(
            stderr or stdout or f"Installer exited with code {result.returncode}"
        )
    executable_path = server_module._resolve_runner_executable_path(runner)
    if not executable_path:
        raise RuntimeError(
            "Installer completed, but OpenPlot still could not find the runner executable"
        )
    return {"executable_path": executable_path}


def _install_codex_release(server_module: ModuleType, job_id: str) -> dict[str, object]:
    host_platform, host_arch = server_module._runner_host_platform()
    if host_platform != "darwin" or host_arch.lower() not in {"arm64", "aarch64"}:
        raise RuntimeError(
            "Codex click-install is only supported on macOS Apple Silicon"
        )

    server_module._append_runner_install_log(
        job_id, "Fetching latest Codex release metadata"
    )
    payload = json.loads(
        server_module.decode_bytes(
            server_module._read_url_bytes(
                "https://api.github.com/repos/openai/codex/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
        )
    )

    assets = payload.get("assets") or []
    asset_name = "codex-aarch64-apple-darwin.tar.gz"
    asset = next((item for item in assets if item.get("name") == asset_name), None)
    if asset is None:
        raise RuntimeError(f"Could not find {asset_name} in the latest Codex release")

    with tempfile.TemporaryDirectory(prefix="openplot-codex-") as temp_dir:
        temp_root = Path(temp_dir)
        archive_path = temp_root / asset_name
        server_module._append_runner_install_log(job_id, f"Downloading {asset_name}")
        server_module._download_url_to_file(
            str(asset["browser_download_url"]), archive_path
        )

        extract_dir = temp_root / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(extract_dir)

        binary_candidates = [path for path in extract_dir.rglob("*") if path.is_file()]
        binary_path = next(
            (path for path in binary_candidates if path.name.startswith("codex-")), None
        )
        if binary_path is None:
            raise RuntimeError("Codex archive did not contain an executable")

        target_path = server_module._runner_tools_root() / "codex" / "current" / "codex"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary_path, target_path)
        target_path.chmod(0o755)
        server_module._append_runner_install_log(
            job_id, f"Installed Codex to {target_path}"
        )

    executable_path = server_module._resolve_runner_executable_path("codex")
    if not executable_path:
        raise RuntimeError(
            "Codex install finished, but OpenPlot still could not find the executable"
        )
    return {"executable_path": executable_path}


def _perform_runner_install(
    server_module: ModuleType,
    runner: FixRunner,
    job: dict[str, object],
) -> dict[str, object]:
    job_id = str(job["id"])
    host_platform, host_arch = server_module._runner_host_platform()
    if runner == "opencode":
        if host_platform == "darwin" and host_arch.lower() in {"arm64", "aarch64"}:
            return server_module._install_runner_via_script(
                runner=runner,
                script_url="https://opencode.ai/install",
                job_id=job_id,
            )
        raise RuntimeError("OpenCode click-install is not supported on this machine")
    if runner == "claude":
        if host_platform == "darwin" and host_arch.lower() in {"arm64", "aarch64"}:
            return server_module._install_runner_via_script(
                runner=runner,
                script_url="https://claude.ai/install.sh",
                job_id=job_id,
            )
        raise RuntimeError(
            "Claude click-install is only supported on macOS Apple Silicon"
        )
    if runner == "codex":
        return server_module._install_codex_release(job_id)
    raise RuntimeError(f"Unknown runner: {runner}")


def _run_runner_install_job(
    server_module: ModuleType,
    job_id: str,
    runtime: object | None = None,
) -> None:
    resolved_runtime = (
        runtime or server_module._bound_runtime or server_module.get_shared_runtime()
    )

    def _run() -> None:
        job = server_module._update_runner_install_job(
            job_id,
            state="running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        if job is None:
            return

        runner = cast(FixRunner, job["runner"])
        try:
            result = server_module._perform_runner_install(runner, job)
            resolved_path = result.get(
                "executable_path"
            ) or server_module._resolve_runner_executable_path(runner)
            if not server_module._runner_launch_probe(runner):
                raise RuntimeError(
                    "Install completed, but the runner still does not pass a launch probe"
                )
            server_module._update_runner_install_job(
                job_id,
                state="succeeded",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error=None,
                resolved_path=resolved_path,
            )
        except Exception as exc:
            server_module._append_runner_install_log(job_id, str(exc))
            server_module._update_runner_install_job(
                job_id,
                state="failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error=str(exc),
            )

    server_module._with_runtime(resolved_runtime, _run)


def _download_url_to_file(server_module: ModuleType, url: str, target: Path) -> None:
    target.write_bytes(server_module._read_url_bytes(url))


def _run_download_subprocess(
    server_module: ModuleType,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
):
    command = ["curl", "-fsSL"]
    if headers:
        for key, value in headers.items():
            command.extend(["-H", f"{key}: {value}"])
    command.append(url)
    creationflags = (
        server_module.subprocess.CREATE_NO_WINDOW
        if server_module.sys.platform == "win32"
        else 0
    )
    return server_module.subprocess.run(
        command,
        capture_output=True,
        text=False,
        timeout=900,
        env=server_module._subprocess_env(),
        check=False,
        creationflags=creationflags,
    )


def _read_url_bytes(
    server_module: ModuleType,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> bytes:
    request_headers = {"User-Agent": "OpenPlot"}
    if headers:
        request_headers.update(headers)
    request = server_module.urllib_request.Request(url, headers=request_headers)
    try:
        with server_module.urllib_request.urlopen(request, timeout=60) as response:
            return response.read()
    except server_module.urllib_error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if not isinstance(reason, server_module.ssl.SSLCertVerificationError):
            raise
        fallback = server_module._run_download_subprocess(url, headers=headers)
        if fallback.returncode != 0:
            stderr = fallback.stderr.decode("utf-8", errors="replace").strip()
            stdout = fallback.stdout.decode("utf-8", errors="replace").strip()
            raise RuntimeError(stderr or stdout or f"Failed to download {url}") from exc
        return fallback.stdout


def _parse_semver_parts(
    server_module: ModuleType,
    value: object,
) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = server_module.re.fullmatch(
        r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)",
        value.strip(),
    )
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def _normalize_release_version(server_module: ModuleType, value: object) -> str | None:
    parts = server_module._parse_semver_parts(value)
    if parts is None:
        return None
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def _fetch_latest_release_payload(server_module: ModuleType) -> dict[str, object]:
    payload = server_module.json.loads(
        server_module.decode_bytes(
            server_module._read_url_bytes(
                server_module._latest_release_api_url,
                headers={"Accept": "application/vnd.github+json"},
            )
        )
    )
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub release payload was not an object")
    return payload


def _default_update_status_payload(server_module: ModuleType) -> dict[str, object]:
    return {
        "current_version": server_module.__version__,
        "latest_version": None,
        "latest_release_url": server_module._latest_release_page_url,
        "update_available": False,
        "checked_at": None,
        "error": None,
    }


def _update_status_cache_path(server_module: ModuleType) -> Path:
    root = server_module._state_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "update-status.json"


def _load_update_status_disk_cache(
    server_module: ModuleType,
    *,
    require_fresh: bool,
) -> dict[str, object] | None:
    path = server_module._update_status_cache_path()
    if not path.exists():
        return None
    if (
        require_fresh
        and server_module.time.time() - path.stat().st_mtime
        >= server_module._update_status_cache_ttl_s
    ):
        return None
    try:
        payload = server_module.json.loads(server_module._read_file_text(path))
    except (OSError, server_module.json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _store_update_status_cache(
    server_module: ModuleType, payload: Mapping[str, object]
) -> None:
    cached = dict(payload)
    server_module._update_status_cache = cached
    server_module._update_status_cache_expires_at = (
        server_module.time.monotonic() + server_module._update_status_cache_ttl_s
    )
    try:
        server_module._update_status_cache_path().write_text(
            server_module.json.dumps(cached),
            encoding="utf-8",
        )
    except OSError:
        pass


def _build_update_status_payload_impl(
    server_module: ModuleType,
    *,
    force_refresh: bool = False,
    allow_network: bool = True,
) -> dict[str, object]:
    now = server_module.time.monotonic()
    if (
        not force_refresh
        and server_module._update_status_cache is not None
        and now < server_module._update_status_cache_expires_at
    ):
        return dict(server_module._update_status_cache)

    if not force_refresh:
        disk_cached = server_module._load_update_status_disk_cache(require_fresh=True)
        if disk_cached is not None:
            server_module._update_status_cache = dict(disk_cached)
            server_module._update_status_cache_expires_at = (
                now + server_module._update_status_cache_ttl_s
            )
            return dict(disk_cached)

    stale_cached = (
        None
        if force_refresh
        else server_module._load_update_status_disk_cache(require_fresh=False)
    )
    if not allow_network:
        if stale_cached is not None:
            return dict(stale_cached)
        return server_module._default_update_status_payload()

    checked_at = server_module._now_iso()
    payload: dict[str, object] = server_module._default_update_status_payload()
    payload["checked_at"] = checked_at

    try:
        release = server_module._fetch_latest_release_payload()
        if release.get("draft") is True or release.get("prerelease") is True:
            raise RuntimeError("No stable GitHub release is currently published")

        latest_version = server_module._normalize_release_version(
            release.get("tag_name")
        )
        if latest_version is None:
            latest_version = server_module._normalize_release_version(
                release.get("name")
            )
        if latest_version is None:
            raise RuntimeError(
                "Latest GitHub release did not expose a semantic version"
            )

        release_url = release.get("html_url")
        if isinstance(release_url, str) and release_url.startswith(
            ("https://", "http://")
        ):
            payload["latest_release_url"] = release_url

        current_parts = server_module._parse_semver_parts(server_module.__version__)
        latest_parts = server_module._parse_semver_parts(latest_version)
        if current_parts is None or latest_parts is None:
            raise RuntimeError("Could not compare semantic versions")

        payload["latest_version"] = latest_version
        payload["update_available"] = latest_parts > current_parts
    except Exception as exc:
        payload["error"] = str(exc) or "Failed to check for updates"

    server_module._store_update_status_cache(payload)
    return dict(payload)


def _build_update_status_payload(
    server_module: ModuleType,
    *,
    force_refresh: bool = False,
    allow_network: bool = True,
) -> dict[str, object]:
    return server_module.build_update_status_payload(
        server_module._bound_runtime or server_module.get_shared_runtime(),
        allow_network=allow_network,
        force_refresh=force_refresh,
    )


def _runner_output_used_builtin_question_tool(
    server_module: ModuleType,
    runner: FixRunner,
    text: str,
) -> bool:
    for line in text.splitlines():
        parsed = server_module._parse_json_event_line(line)
        if parsed is None:
            continue
        if server_module._parsed_runner_uses_builtin_question_tool(runner, parsed):
            return True
    return False


def _parse_opencode_verbose_models(
    server_module: ModuleType, raw: str
) -> list[OpencodeModelOption]:
    _ = server_module
    options_by_id: dict[str, OpencodeModelOption] = {}
    lines = raw.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if "/" not in line or line.startswith("{") or line.startswith("}"):
            index += 1
            continue

        model_id = line
        index += 1

        while index < len(lines) and not lines[index].strip():
            index += 1

        model_meta: dict = {}
        if index < len(lines) and lines[index].lstrip().startswith("{"):
            brace_depth = 0
            block: list[str] = []
            while index < len(lines):
                current = lines[index]
                brace_depth += current.count("{")
                brace_depth -= current.count("}")
                block.append(current)
                index += 1
                if brace_depth <= 0:
                    break
            try:
                model_meta = json.loads("\n".join(block))
            except json.JSONDecodeError:
                model_meta = {}

        variants_raw = model_meta.get("variants")
        variants = (
            sorted(str(key) for key in variants_raw.keys())
            if isinstance(variants_raw, dict)
            else []
        )
        provider = str(model_meta.get("providerID") or model_id.split("/", 1)[0])
        name = str(model_meta.get("name") or model_id)
        options_by_id[model_id] = OpencodeModelOption(
            id=model_id,
            provider=provider,
            name=name,
            variants=variants,
        )

    if options_by_id:
        return sorted(options_by_id.values(), key=lambda option: option.id)

    for line in lines:
        candidate = line.strip()
        if not candidate or "/" not in candidate or candidate.startswith("opencode "):
            continue
        options_by_id[candidate] = OpencodeModelOption(
            id=candidate,
            provider=candidate.split("/", 1)[0],
            name=candidate,
            variants=[],
        )

    return sorted(options_by_id.values(), key=lambda option: option.id)


def _refresh_opencode_models_cache(
    server_module: ModuleType,
    *,
    force_refresh: bool = False,
) -> list[OpencodeModelOption]:
    now = server_module.time.monotonic()
    if (
        not force_refresh
        and server_module._opencode_models_cache is not None
        and now < server_module._opencode_models_cache_expires_at
    ):
        return server_module._opencode_models_cache

    opencode_command = server_module._resolve_command_path("opencode")
    if opencode_command is None:
        raise RuntimeError("opencode command not found")

    attempts = [
        [opencode_command, "models", "--verbose"],
        [opencode_command, "models"],
    ]
    last_error: str | None = None

    for command in attempts:
        try:
            hidden_window_kwargs = server_module._hidden_window_kwargs()
            creationflags = cast(int, hidden_window_kwargs.get("creationflags", 0))
            result = server_module.run_text_subprocess(
                command,
                cwd=str(server_module._workspace_dir),
                env=server_module._subprocess_env(),
                check=False,
                creationflags=creationflags,
            )
        except (OSError, UnicodeDecodeError) as exc:
            last_error = str(exc)
            continue

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if stderr:
                last_error = stderr
            continue

        parsed = server_module._parse_opencode_verbose_models(result.stdout)
        if parsed:
            server_module._opencode_models_cache = parsed
            server_module._opencode_models_cache_expires_at = (
                now + server_module._opencode_models_cache_ttl_s
            )
            return parsed

        if result.stdout.strip():
            last_error = "No parseable model entries returned by opencode"

    raise RuntimeError(last_error or "Failed to load models from opencode")


def _parse_codex_models_cache(
    server_module: ModuleType, raw: object
) -> list[OpencodeModelOption]:
    _ = server_module
    if not isinstance(raw, dict):
        return []

    models_raw = raw.get("models")
    if not isinstance(models_raw, list):
        return []

    options: dict[str, OpencodeModelOption] = {}
    for entry in models_raw:
        if not isinstance(entry, dict):
            continue

        model_id = str(entry.get("slug") or "").strip()
        if not model_id:
            continue

        visibility = str(entry.get("visibility") or "").strip().lower()
        if visibility and visibility != "list":
            continue

        levels_raw = entry.get("supported_reasoning_levels")
        variants: list[str] = []
        if isinstance(levels_raw, list):
            for level in levels_raw:
                if not isinstance(level, dict):
                    continue
                effort = str(level.get("effort") or "").strip()
                if effort and effort not in variants:
                    variants.append(effort)

        options[model_id] = OpencodeModelOption(
            id=model_id,
            provider="openai",
            name=str(entry.get("display_name") or model_id),
            variants=variants,
        )

    return sorted(options.values(), key=lambda option: option.id)


def _refresh_codex_models_cache(
    server_module: ModuleType,
    *,
    force_refresh: bool = False,
) -> list[OpencodeModelOption]:
    now = server_module.time.monotonic()
    if (
        not force_refresh
        and server_module._codex_models_cache is not None
        and now < server_module._codex_models_cache_expires_at
    ):
        return server_module._codex_models_cache

    cache_path = server_module.Path.home() / ".codex" / "models_cache.json"
    if not cache_path.exists():
        raise RuntimeError(
            "Codex model cache not found. Run `codex` once to initialise it."
        )

    try:
        parsed_json = server_module.json.loads(
            server_module._read_file_text(cache_path)
        )
    except OSError as exc:
        raise RuntimeError(f"Failed to read Codex model cache: {exc}") from exc
    except server_module.json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse Codex model cache: {exc}") from exc

    parsed = server_module._parse_codex_models_cache(parsed_json)
    if not parsed:
        raise RuntimeError("No parseable model entries returned by Codex")

    server_module._codex_models_cache = parsed
    server_module._codex_models_cache_expires_at = (
        now + server_module._codex_models_cache_ttl_s
    )
    return parsed


def _refresh_claude_models_cache(
    server_module: ModuleType,
    *,
    force_refresh: bool = False,
) -> list[OpencodeModelOption]:
    now = server_module.time.monotonic()
    if (
        not force_refresh
        and server_module._claude_models_cache is not None
        and now < server_module._claude_models_cache_expires_at
    ):
        return server_module._claude_models_cache

    variants = ["low", "medium", "high"]
    parsed = [
        OpencodeModelOption(
            id="claude-sonnet-4-6",
            provider="anthropic",
            name="Claude Sonnet 4.6",
            variants=variants,
        ),
        OpencodeModelOption(
            id="claude-opus-4-6",
            provider="anthropic",
            name="Claude Opus 4.6",
            variants=variants,
        ),
        OpencodeModelOption(
            id="claude-haiku-4-5",
            provider="anthropic",
            name="Claude Haiku 4.5",
            variants=[],
        ),
    ]

    server_module._claude_models_cache = parsed
    server_module._claude_models_cache_expires_at = (
        now + server_module._claude_models_cache_ttl_s
    )
    return parsed


def _refresh_runner_models_cache(
    server_module: ModuleType,
    runner: FixRunner,
    *,
    force_refresh: bool = False,
) -> list[OpencodeModelOption]:
    if runner == "codex":
        return server_module._refresh_codex_models_cache(force_refresh=force_refresh)
    if runner == "claude":
        return server_module._refresh_claude_models_cache(force_refresh=force_refresh)
    return server_module._refresh_opencode_models_cache(force_refresh=force_refresh)


def _resolve_runner_default_model_and_variant(
    server_module: ModuleType,
    *,
    runner: FixRunner,
    models: list[OpencodeModelOption],
    preferred_runner: FixRunner,
    preferred_model: str | None,
    preferred_variant: str | None,
) -> tuple[str, str]:
    model_ids = {model.id for model in models}
    runner_default_model = server_module._runner_default_model_id(runner)

    if not models:
        if preferred_runner == runner and preferred_model:
            return preferred_model, preferred_variant or ""
        return runner_default_model, ""

    if preferred_runner == runner and preferred_model in model_ids:
        default_model = preferred_model
    elif runner_default_model in model_ids:
        default_model = runner_default_model
    else:
        default_model = models[0].id if models else ""

    default_variant = ""
    if default_model and preferred_runner == runner and preferred_variant:
        selected_default_model = next(
            (model for model in models if model.id == default_model),
            None,
        )
        if selected_default_model is not None and selected_default_model.variants:
            if preferred_variant in selected_default_model.variants:
                default_variant = preferred_variant
        elif default_model in model_ids:
            default_variant = preferred_variant

    return default_model, default_variant


def _validate_runner_model_selection(
    server_module: ModuleType,
    *,
    runner: FixRunner,
    model: str,
    variant: str | None,
    models: list[OpencodeModelOption],
) -> None:
    selected_model = next((entry for entry in models if entry.id == model), None)
    if models and selected_model is None:
        raise server_module.HTTPException(
            status_code=400,
            detail=f"Unknown model for {runner}: {model}",
        )

    if (
        selected_model is not None
        and variant is not None
        and selected_model.variants
        and variant not in selected_model.variants
    ):
        raise server_module.HTTPException(
            status_code=400,
            detail=(
                f"Variant '{variant}' is not available for model '{model}' "
                f"on runner '{runner}'"
            ),
        )


def _merge_opencode_config_objects(
    server_module: ModuleType, base: object, override: object
) -> object:
    _ = server_module
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override

    merged = dict(base)
    for key, value in override.items():
        merged[key] = server_module._merge_opencode_config_objects(
            merged.get(key), value
        )
    return merged


def _merged_opencode_config_content(
    server_module: ModuleType,
    base_content: str | None,
    override_content: str,
) -> str:
    try:
        override_payload = json.loads(override_content)
    except json.JSONDecodeError:
        return override_content
    if not isinstance(override_payload, dict):
        return override_content

    if not base_content:
        return override_content

    try:
        base_payload = json.loads(base_content)
    except json.JSONDecodeError:
        return override_content
    if not isinstance(base_payload, dict):
        return override_content

    merged = server_module._merge_opencode_config_objects(
        base_payload, override_payload
    )
    if not isinstance(merged, dict):
        return override_content
    return json.dumps(merged)


def _opencode_fix_config_content(server_module: ModuleType) -> str:
    mcp_launch = server_module._resolve_openplot_mcp_launch_command()
    config = {
        "$schema": "https://opencode.ai/config.json",
        "default_agent": server_module._opencode_fix_agent_name,
        "mcp": {
            "openplot": {
                "type": "local",
                "enabled": True,
                "command": mcp_launch,
                "timeout": 20000,
            }
        },
        "permission": {"question": "deny"},
        "tools": {
            "write": True,
            "edit": True,
            "patch": True,
            "bash": True,
            "read": True,
            "grep": True,
            "glob": True,
            "list": True,
            "webfetch": True,
            "openplot_*": True,
        },
        "agent": {
            server_module._opencode_fix_agent_name: {
                "mode": "primary",
                "tools": {
                    "write": True,
                    "edit": True,
                    "patch": True,
                    "bash": True,
                    "read": True,
                    "grep": True,
                    "glob": True,
                    "list": True,
                    "webfetch": True,
                    "openplot_*": True,
                },
                "permission": {"question": "deny"},
            }
        },
    }
    return server_module.json.dumps(config)


def _opencode_question_tool_disabled_config_content(server_module: ModuleType) -> str:
    return server_module.json.dumps(
        {
            "$schema": "https://opencode.ai/config.json",
            "permission": {"question": "deny"},
        }
    )
