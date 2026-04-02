"""Fix-job execution helpers extracted from openplot.server."""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path
from types import ModuleType
from typing import Literal, Mapping
from contextlib import suppress

from .models import (
    AnnotationStatus,
    FixJob,
    FixJobStatus,
    FixJobStep,
    FixStepStatus,
    PlotSession,
)


async def _terminate_fix_process(server_module: ModuleType, process: object) -> None:
    if process.returncode is not None:
        return

    used_process_group = False
    if sys.platform != "win32" and process.pid > 0:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            used_process_group = True
        except ProcessLookupError:
            return
        except OSError:
            used_process_group = False

    if not used_process_group:
        process.terminate()

    try:
        await server_module.asyncio.wait_for(process.wait(), timeout=5.0)
        return
    except server_module.asyncio.TimeoutError:
        pass

    if process.returncode is not None:
        return

    if used_process_group and process.pid > 0:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError:
            process.kill()
    else:
        process.kill()

    with suppress(Exception):
        await process.wait()


def _is_terminal_fix_job_status(
    server_module: ModuleType, status: FixJobStatus
) -> bool:
    _ = server_module
    return status in {
        FixJobStatus.completed,
        FixJobStatus.failed,
        FixJobStatus.cancelled,
    }


def _build_opencode_plot_fix_command(
    server_module: ModuleType,
    *,
    model: str,
    variant: str | None,
    workspace_dir: str | Path | None = None,
    resume_session_id: str | None = None,
    extra_prompt: str | None = None,
) -> list[str]:
    resolved_workspace_dir = (
        Path(workspace_dir).resolve() if workspace_dir else server_module._workspace_dir
    )
    opencode_command = server_module._resolve_command_path("opencode") or "opencode"
    command = [
        opencode_command,
        "run",
        "--dir",
        str(resolved_workspace_dir),
        "--format",
        "json",
        "--agent",
        server_module._opencode_fix_agent_name,
        "--model",
        model,
    ]
    normalized_resume_session_id = server_module._normalize_runner_session_id(
        resume_session_id
    )
    if normalized_resume_session_id:
        command.extend(["--session", normalized_resume_session_id])
    normalized_variant = (variant or "").strip()
    if normalized_variant:
        command.extend(["--variant", normalized_variant])
    command.append(
        server_module._build_codex_plot_fix_prompt(extra_prompt=extra_prompt)
    )
    return command


def _build_codex_plot_fix_prompt(
    server_module: ModuleType, *, extra_prompt: str | None = None
) -> str:
    _ = server_module
    prompt = (
        "Call MCP tools in this order: "
        "(1) get_pending_feedback_with_images, "
        "(2) get_pending_feedback, "
        "(3) get_plot_context. "
        "If step (1) fails, continue with step (2). "
        "Use target_annotation_id from get_pending_feedback as the FIFO "
        "annotation to address. "
        "Read python_interpreter from get_plot_context and treat "
        "python_interpreter.available_packages as a strict allowlist for "
        "third-party imports. Use Python standard library freely, but never "
        "import a third-party package unless it appears in "
        "python_interpreter.available_packages. "
        "Treat the current branch-head script and all previously addressed annotations as the source of truth. "
        "Preserve every earlier accepted fix unless changing it is strictly necessary to satisfy the current annotation. "
        "Make the smallest targeted change needed for the FIFO pending annotation. "
        "Then update the plotting script to address exactly that one pending "
        "annotation and call submit_updated_script with the complete "
        "updated script and annotation_id=target_annotation_id. "
        "For raster-region feedback, use the crop image as primary grounding and "
        "apply ambiguous references (for example, 'this', 'these', 'each line') "
        "only to elements visible in that selected region unless the feedback "
        "explicitly requests global edits. "
        "Never use built-in interactive question tools such as AskUserQuestion or question. "
        "Do not ask the user for interactive input during fix mode. "
        "If the annotation is ambiguous, infer the most conservative interpretation from the current script, pending annotation, and existing accepted fixes, then continue. "
        "Never execute shell commands named openplot_*; these are MCP tools."
    )
    if extra_prompt:
        prompt += f" Retry context: {extra_prompt.strip()}"
    return prompt


def _build_codex_plot_fix_command(
    server_module: ModuleType,
    *,
    model: str,
    variant: str | None,
    workspace_dir: str | Path | None = None,
    resume_session_id: str | None = None,
    extra_prompt: str | None = None,
) -> list[str]:
    resolved_workspace_dir = (
        Path(workspace_dir).resolve() if workspace_dir else server_module._workspace_dir
    )
    codex_command = server_module._resolve_command_path("codex") or "codex"
    normalized_resume_session_id = server_module._normalize_runner_session_id(
        resume_session_id
    )
    mcp_launch = server_module._resolve_openplot_mcp_launch_command()
    mcp_cmd = json.dumps(mcp_launch[0])
    mcp_args = json.dumps(mcp_launch[1:])
    command = [codex_command, "exec"]
    if normalized_resume_session_id:
        command.extend(
            [
                "resume",
                "--skip-git-repo-check",
                "--json",
                "-c",
                'approval_policy="never"',
                "-c",
                f"mcp_servers.openplot.command={mcp_cmd}",
                "-c",
                f"mcp_servers.openplot.args={mcp_args}",
                "-c",
                "mcp_servers.openplot.enabled=true",
                "-c",
                "mcp_servers.openplot.startup_timeout_sec=20",
                "--model",
                model,
                normalized_resume_session_id,
            ]
        )
    else:
        command.extend(
            [
                "--cd",
                str(resolved_workspace_dir),
                "--skip-git-repo-check",
                "--json",
                "--sandbox",
                "workspace-write",
                "-c",
                'approval_policy="never"',
                "-c",
                f"mcp_servers.openplot.command={mcp_cmd}",
                "-c",
                f"mcp_servers.openplot.args={mcp_args}",
                "-c",
                "mcp_servers.openplot.enabled=true",
                "-c",
                "mcp_servers.openplot.startup_timeout_sec=20",
                "--model",
                model,
            ]
        )
    normalized_variant = (variant or "").strip()
    if normalized_variant:
        command.extend(
            [
                "-c",
                f"model_reasoning_effort={json.dumps(normalized_variant)}",
            ]
        )
    command.append(
        server_module._build_codex_plot_fix_prompt(extra_prompt=extra_prompt)
    )
    return command


def _build_claude_plot_fix_command(
    server_module: ModuleType,
    *,
    model: str,
    variant: str | None,
    workspace_dir: str | Path | None = None,
    resume_session_id: str | None = None,
    extra_prompt: str | None = None,
) -> list[str]:
    claude_command = server_module._resolve_claude_cli_command() or "claude"
    prompt = server_module._build_codex_plot_fix_prompt(extra_prompt=extra_prompt)
    mcp_launch = server_module._resolve_openplot_mcp_launch_command()
    mcp_config_data = {
        "mcpServers": {
            "openplot": {
                "type": "stdio",
                "command": mcp_launch[0],
                "args": mcp_launch[1:],
            }
        }
    }

    resolved_workspace = (
        Path(workspace_dir).resolve() if workspace_dir else server_module._workspace_dir
    )
    mcp_config_path = resolved_workspace / ".openplot_mcp_config.json"
    mcp_config_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_config_path.write_text(json.dumps(mcp_config_data), encoding="utf-8")

    command = [
        claude_command,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--permission-mode",
        "bypassPermissions",
        "--disallowedTools",
        "AskUserQuestion",
        "--strict-mcp-config",
        "--add-dir",
        str(resolved_workspace),
        "--mcp-config",
        str(mcp_config_path),
        "--model",
        model,
    ]

    normalized_resume_session_id = server_module._normalize_runner_session_id(
        resume_session_id
    )
    if normalized_resume_session_id:
        command.extend(["--resume", normalized_resume_session_id])

    normalized_variant = (variant or "").strip()
    if normalized_variant:
        command.extend(["--effort", normalized_variant])

    return command


async def _broadcast_fix_job(server_module: ModuleType, job: FixJob) -> None:
    await server_module._broadcast({"type": "fix_job_updated", "job": job.model_dump()})


async def _cancel_fix_job_execution(
    server_module: ModuleType, job: FixJob, *, reason: str
) -> None:
    if server_module._is_terminal_fix_job_status(job.status):
        server_module._clear_active_fix_job_for_session(
            job.session_id, expected_job_id=job.id
        )
        return

    job.status = FixJobStatus.cancelled
    job.last_error = reason
    if not job.finished_at:
        job.finished_at = server_module._now_iso()

    if job.steps and job.steps[-1].status == FixStepStatus.running:
        job.steps[-1].status = FixStepStatus.cancelled
        job.steps[-1].finished_at = server_module._now_iso()
        if not job.steps[-1].error:
            job.steps[-1].error = reason

    process = server_module._runtime_fix_job_processes_map().get(job.id)
    if process is not None:
        await server_module._terminate_fix_process(process)

    server_module._clear_active_fix_job_for_session(
        job.session_id, expected_job_id=job.id
    )
    await server_module._broadcast_fix_job(job)


async def _reconcile_active_fix_job_state(server_module: ModuleType) -> None:
    active_fix_jobs = server_module._runtime_active_fix_jobs_map()
    fix_jobs = server_module._runtime_fix_jobs_map()
    fix_job_tasks = server_module._runtime_fix_job_tasks_map()
    fix_job_processes = server_module._runtime_fix_job_processes_map()

    if not active_fix_jobs:
        return

    for session_key, job_id in list(active_fix_jobs.items()):
        job = fix_jobs.get(job_id)
        if job is None:
            active_fix_jobs.pop(session_key, None)
            continue

        if server_module._is_terminal_fix_job_status(job.status):
            active_fix_jobs.pop(session_key, None)
            fix_job_tasks.pop(job.id, None)
            fix_job_processes.pop(job.id, None)
            continue

        task = fix_job_tasks.get(job.id)
        process = fix_job_processes.get(job.id)

        task_running = task is not None and not task.done()
        process_running = process is not None and process.returncode is None
        if task_running or process_running:
            continue

        message = "Fix job worker state was lost; marking as failed."
        if job.steps and job.steps[-1].status == FixStepStatus.running:
            job.steps[-1].status = FixStepStatus.failed
            job.steps[-1].finished_at = server_module._now_iso()
            if not job.steps[-1].error:
                job.steps[-1].error = message

        job.status = FixJobStatus.failed
        if not job.last_error:
            job.last_error = message
        if not job.finished_at:
            job.finished_at = server_module._now_iso()

        active_fix_jobs.pop(session_key, None)
        fix_job_tasks.pop(job.id, None)
        fix_job_processes.pop(job.id, None)
        await server_module._broadcast_fix_job(job)


async def _broadcast_fix_job_log(
    server_module: ModuleType,
    *,
    job_id: str,
    step_index: int,
    annotation_id: str,
    stream: Literal["stdout", "stderr"],
    chunk: str,
    parsed: dict | None,
) -> None:
    await server_module._broadcast(
        {
            "type": "fix_job_log",
            "job_id": job_id,
            "step_index": step_index,
            "annotation_id": annotation_id,
            "stream": stream,
            "chunk": chunk,
            "timestamp": server_module._now_iso(),
            "parsed": parsed,
        }
    )


def _session_for_fix_job(server_module: ModuleType, job: FixJob) -> PlotSession:
    if job.session_id:
        return server_module._get_session_by_id(job.session_id)
    return server_module.get_session()


def _workspace_dir_for_fix_job(
    server_module: ModuleType, job: FixJob, session: PlotSession
) -> Path:
    context_workspace = server_module._workspace_for_session(session).resolve()
    try:
        context_workspace.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    else:
        if context_workspace.exists() and context_workspace.is_dir():
            return context_workspace

    if job.workspace_dir:
        workspace_dir = Path(job.workspace_dir).resolve()
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return workspace_dir

    fallback_workspace = server_module._runtime_workspace_dir().resolve()
    try:
        fallback_workspace.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return fallback_workspace


def _prepare_fix_runner_workspace(
    server_module: ModuleType, session: PlotSession, *, job_id: str
) -> Path:
    """Create a per-job runtime directory for external fix runners."""
    workspace_root = (
        server_module._session_artifacts_root(session) / "fix_runner" / job_id
    )
    workspace_root.mkdir(parents=True, exist_ok=True)

    context_dir = server_module._workspace_for_session(session)
    context_note = workspace_root / "OPENPLOT_CONTEXT_DIR.txt"
    try:
        context_note.write_text(str(context_dir), encoding="utf-8")
    except OSError:
        pass

    context_link = workspace_root / "project"
    try:
        if context_link.is_symlink():
            try:
                if context_link.resolve() != context_dir.resolve():
                    context_link.unlink()
            except OSError:
                context_link.unlink(missing_ok=True)
        elif context_link.exists() and not context_link.is_dir():
            context_link.unlink(missing_ok=True)

        if not context_link.exists() and context_dir.exists():
            context_link.symlink_to(context_dir, target_is_directory=True)
    except OSError:
        pass

    return workspace_root.resolve()


def _runtime_dir_for_fix_job(
    server_module: ModuleType, job: FixJob, session: PlotSession
) -> Path:
    if job.workspace_dir:
        runtime_dir = Path(job.workspace_dir).resolve()
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return runtime_dir
    return server_module._prepare_fix_runner_workspace(session, job_id=job.id)


def _fix_runner_env_overrides(
    server_module: ModuleType, job: FixJob, session: PlotSession
) -> dict[str, str]:
    runtime_dir = server_module._runtime_dir_for_fix_job(job, session)
    shim_bin = server_module._write_fix_runner_shims(runtime_dir)

    path_entries = [str(shim_bin), server_module._command_search_path()]
    overrides: dict[str, str] = {
        "OPENPLOT_SESSION_ID": session.id,
        "PATH": os.pathsep.join(path_entries),
    }

    if job.runner == "opencode":
        overrides.update(
            {
                "OPENCODE_CONFIG_CONTENT": server_module._merged_opencode_config_content(
                    os.getenv("OPENCODE_CONFIG_CONTENT"),
                    server_module._opencode_fix_config_content(),
                ),
                "OPENCODE_DISABLE_CLAUDE_CODE": "1",
            }
        )

    runtime_executable = Path(sys.executable).expanduser().resolve()
    if not server_module._is_openplot_app_launcher_path(runtime_executable):
        package_src_root = Path(server_module.__file__).resolve().parent.parent
        current_pythonpath = os.getenv("PYTHONPATH") or ""
        if current_pythonpath:
            overrides["PYTHONPATH"] = (
                f"{package_src_root}{os.pathsep}{current_pythonpath}"
            )
        else:
            overrides["PYTHONPATH"] = str(package_src_root)

    backend_url = server_module._backend_url_from_port_file()
    if backend_url:
        overrides["OPENPLOT_SERVER_URL"] = backend_url

    return overrides


def _fix_job_session_key(server_module: ModuleType, session_id: str | None) -> str:
    _ = server_module
    normalized = (session_id or "").strip()
    return normalized or "__legacy__"


async def _run_opencode_fix_iteration(
    server_module: ModuleType,
    job: FixJob,
    step: FixJobStep,
    *,
    extra_prompt: str | None = None,
) -> None:
    session = server_module._session_for_fix_job(job)
    workspace_dir = server_module._workspace_dir_for_fix_job(job, session)
    runtime_dir = server_module._runtime_dir_for_fix_job(job, session)
    env_overrides = server_module._fix_runner_env_overrides(job, session)
    resume_session_id = server_module._runner_session_id_for_session(
        session, "opencode"
    )
    command = server_module._build_opencode_plot_fix_command(
        model=job.model,
        variant=job.variant,
        workspace_dir=workspace_dir,
        resume_session_id=resume_session_id,
        extra_prompt=extra_prompt,
    )
    display_command = [*command[:-1], "<plot-fix prompt>"]
    raw_stdout, raw_stderr = await server_module._run_fix_iteration_command(
        job=job,
        step=step,
        command=command,
        display_command=display_command,
        cwd=runtime_dir,
        env_overrides=env_overrides,
    )

    if server_module._runner_output_used_builtin_question_tool("opencode", raw_stdout):
        server_module._clear_runner_session_id_for_session(session, "opencode")
        command = server_module._build_opencode_plot_fix_command(
            model=job.model,
            variant=job.variant,
            workspace_dir=workspace_dir,
            resume_session_id=None,
            extra_prompt=server_module._append_retry_instruction(
                extra_prompt or "",
                server_module._fix_mode_question_tool_retry_instruction(),
            ),
        )
        display_command = [*command[:-1], "<plot-fix prompt>"]
        raw_stdout, raw_stderr = await server_module._run_fix_iteration_command(
            job=job,
            step=step,
            command=command,
            display_command=display_command,
            cwd=runtime_dir,
            env_overrides=env_overrides,
        )

    if (
        step.exit_code != 0
        and resume_session_id
        and server_module._is_resume_session_error(
            "opencode", stdout_text=raw_stdout, stderr_text=raw_stderr
        )
    ):
        server_module._clear_runner_session_id_for_session(session, "opencode")
        command = server_module._build_opencode_plot_fix_command(
            model=job.model,
            variant=job.variant,
            workspace_dir=workspace_dir,
            resume_session_id=None,
            extra_prompt=extra_prompt,
        )
        display_command = [*command[:-1], "<plot-fix prompt>"]
        raw_stdout, raw_stderr = await server_module._run_fix_iteration_command(
            job=job,
            step=step,
            command=command,
            display_command=display_command,
            cwd=runtime_dir,
            env_overrides=env_overrides,
        )

    if server_module._runner_output_used_builtin_question_tool("opencode", raw_stdout):
        step.exit_code = 1
        step.stderr = server_module._truncate_output(
            "Runner attempted an unsupported built-in question tool during fix mode."
        )

    discovered_session_id = server_module._extract_runner_session_id_from_output(
        "opencode", raw_stdout
    )
    if discovered_session_id is not None:
        server_module._set_runner_session_id_for_session(
            session,
            runner="opencode",
            session_id=discovered_session_id,
        )


async def _run_codex_fix_iteration(
    server_module: ModuleType,
    job: FixJob,
    step: FixJobStep,
    *,
    extra_prompt: str | None = None,
) -> None:
    session = server_module._session_for_fix_job(job)
    workspace_dir = server_module._workspace_dir_for_fix_job(job, session)
    env_overrides = server_module._fix_runner_env_overrides(job, session)
    resume_session_id = server_module._runner_session_id_for_session(session, "codex")
    command = server_module._build_codex_plot_fix_command(
        model=job.model,
        variant=job.variant,
        workspace_dir=workspace_dir,
        resume_session_id=resume_session_id,
        extra_prompt=extra_prompt,
    )
    display_command = [*command[:-1], "<plot-fix prompt>"]
    raw_stdout, raw_stderr = await server_module._run_fix_iteration_command(
        job=job,
        step=step,
        command=command,
        display_command=display_command,
        cwd=workspace_dir,
        env_overrides=env_overrides,
    )

    if server_module._runner_output_used_builtin_question_tool("codex", raw_stdout):
        server_module._clear_runner_session_id_for_session(session, "codex")
        command = server_module._build_codex_plot_fix_command(
            model=job.model,
            variant=job.variant,
            workspace_dir=workspace_dir,
            resume_session_id=None,
            extra_prompt=server_module._append_retry_instruction(
                extra_prompt or "",
                server_module._fix_mode_question_tool_retry_instruction(),
            ),
        )
        display_command = [*command[:-1], "<plot-fix prompt>"]
        raw_stdout, raw_stderr = await server_module._run_fix_iteration_command(
            job=job,
            step=step,
            command=command,
            display_command=display_command,
            cwd=workspace_dir,
            env_overrides=env_overrides,
        )

    if (
        step.exit_code != 0
        and resume_session_id
        and server_module._is_resume_session_error(
            "codex", stdout_text=raw_stdout, stderr_text=raw_stderr
        )
    ):
        server_module._clear_runner_session_id_for_session(session, "codex")
        command = server_module._build_codex_plot_fix_command(
            model=job.model,
            variant=job.variant,
            workspace_dir=workspace_dir,
            resume_session_id=None,
            extra_prompt=extra_prompt,
        )
        display_command = [*command[:-1], "<plot-fix prompt>"]
        raw_stdout, raw_stderr = await server_module._run_fix_iteration_command(
            job=job,
            step=step,
            command=command,
            display_command=display_command,
            cwd=workspace_dir,
            env_overrides=env_overrides,
        )

    if server_module._runner_output_used_builtin_question_tool("codex", raw_stdout):
        step.exit_code = 1
        step.stderr = server_module._truncate_output(
            "Runner attempted an unsupported built-in question tool during fix mode."
        )

    discovered_session_id = server_module._extract_runner_session_id_from_output(
        "codex", raw_stdout
    )
    if discovered_session_id is not None:
        server_module._set_runner_session_id_for_session(
            session,
            runner="codex",
            session_id=discovered_session_id,
        )


async def _run_claude_fix_iteration(
    server_module: ModuleType,
    job: FixJob,
    step: FixJobStep,
    *,
    extra_prompt: str | None = None,
) -> None:
    session = server_module._session_for_fix_job(job)
    workspace_dir = server_module._workspace_dir_for_fix_job(job, session)
    env_overrides = server_module._fix_runner_env_overrides(job, session)
    resume_session_id = server_module._runner_session_id_for_session(session, "claude")
    command = server_module._build_claude_plot_fix_command(
        model=job.model,
        variant=job.variant,
        workspace_dir=workspace_dir,
        resume_session_id=resume_session_id,
        extra_prompt=extra_prompt,
    )
    display_command = [*command]
    if len(display_command) >= 3:
        display_command[2] = "<plot-fix prompt>"
    raw_stdout, raw_stderr = await server_module._run_fix_iteration_command(
        job=job,
        step=step,
        command=command,
        display_command=display_command,
        cwd=workspace_dir,
        env_overrides=env_overrides,
    )
    reported_error = server_module._extract_runner_reported_error(
        "claude",
        stdout_text=raw_stdout,
        stderr_text=raw_stderr,
    )

    if server_module._runner_output_used_builtin_question_tool("claude", raw_stdout):
        server_module._clear_runner_session_id_for_session(session, "claude")
        command = server_module._build_claude_plot_fix_command(
            model=job.model,
            variant=job.variant,
            workspace_dir=workspace_dir,
            resume_session_id=None,
            extra_prompt=server_module._append_retry_instruction(
                extra_prompt or "",
                server_module._fix_mode_question_tool_retry_instruction(),
            ),
        )
        display_command = [*command]
        if len(display_command) >= 3:
            display_command[2] = "<plot-fix prompt>"
        raw_stdout, raw_stderr = await server_module._run_fix_iteration_command(
            job=job,
            step=step,
            command=command,
            display_command=display_command,
            cwd=workspace_dir,
            env_overrides=env_overrides,
        )
        reported_error = server_module._extract_runner_reported_error(
            "claude",
            stdout_text=raw_stdout,
            stderr_text=raw_stderr,
        )

    if resume_session_id and (
        (
            step.exit_code != 0
            and server_module._is_resume_session_error(
                "claude",
                stdout_text=raw_stdout,
                stderr_text=raw_stderr,
            )
        )
        or reported_error is not None
    ):
        server_module._clear_runner_session_id_for_session(session, "claude")
        command = server_module._build_claude_plot_fix_command(
            model=job.model,
            variant=job.variant,
            workspace_dir=workspace_dir,
            resume_session_id=None,
            extra_prompt=extra_prompt,
        )
        display_command = [*command]
        if len(display_command) >= 3:
            display_command[2] = "<plot-fix prompt>"
        raw_stdout, raw_stderr = await server_module._run_fix_iteration_command(
            job=job,
            step=step,
            command=command,
            display_command=display_command,
            cwd=workspace_dir,
            env_overrides=env_overrides,
        )
        reported_error = server_module._extract_runner_reported_error(
            "claude",
            stdout_text=raw_stdout,
            stderr_text=raw_stderr,
        )

    if server_module._runner_output_used_builtin_question_tool("claude", raw_stdout):
        step.exit_code = 1
        step.stderr = server_module._truncate_output(
            "Runner attempted an unsupported built-in question tool during fix mode."
        )

    if reported_error is not None and step.exit_code == 0:
        step.exit_code = 1
        existing_stderr = step.stderr.strip()
        if not existing_stderr:
            step.stderr = reported_error
        elif reported_error not in existing_stderr:
            step.stderr = f"{existing_stderr}\n{reported_error}"

    discovered_session_id = server_module._extract_runner_session_id_from_output(
        "claude", raw_stdout
    )
    if discovered_session_id is not None:
        server_module._set_runner_session_id_for_session(
            session,
            runner="claude",
            session_id=discovered_session_id,
        )


def _fix_retry_context(
    server_module: ModuleType, step: FixJobStep, *, annotation_id: str
) -> str:
    _ = server_module
    details: list[str] = [
        f"The previous attempt for annotation {annotation_id} did not finish successfully.",
    ]
    if step.error:
        details.append(step.error)
    stderr_text = step.stderr.strip()
    if stderr_text:
        details.append(stderr_text[-3000:])
    stdout_text = step.stdout.strip()
    if stdout_text and "error" in stdout_text.lower():
        details.append(stdout_text[-3000:])
    details.append(
        "Use the error details above to correct the script and submit a runnable update for the same annotation."
    )
    return " ".join(part.strip() for part in details if part.strip())


async def _run_fix_job_loop(
    server_module: ModuleType,
    job_id: str,
    *,
    runtime: object | None = None,
) -> None:
    resolved_runtime = (
        runtime or server_module._bound_runtime or server_module.get_shared_runtime()
    )

    async def _run() -> None:
        fix_jobs = server_module._runtime_fix_jobs_map()
        fix_job_processes = server_module._runtime_fix_job_processes_map()
        fix_job_tasks = server_module._runtime_fix_job_tasks_map()
        job = fix_jobs.get(job_id)
        if job is None:
            return

        job.status = FixJobStatus.running
        job.started_at = server_module._now_iso()
        await server_module._broadcast_fix_job(job)

        try:
            while True:
                if job.status == FixJobStatus.cancelled:
                    if not job.finished_at:
                        job.finished_at = server_module._now_iso()
                    await server_module._broadcast_fix_job(job)
                    return

                session = server_module._session_for_fix_job(job)
                target_branch = server_module._get_branch(session, job.branch_id)
                if (
                    session.active_branch_id != job.branch_id
                    or session.checked_out_version_id != target_branch.head_version_id
                ):
                    server_module._checkout_version(
                        session,
                        target_branch.head_version_id,
                        branch_id=job.branch_id,
                    )
                    await server_module._broadcast(
                        {
                            "type": "plot_updated",
                            "session_id": session.id,
                            "version_id": session.checked_out_version_id,
                            "plot_type": session.plot_type,
                            "revision": len(session.revision_history),
                            "active_branch_id": session.active_branch_id,
                            "checked_out_version_id": session.checked_out_version_id,
                            "reason": "fix_job_branch_restore",
                        }
                    )

                pending = server_module.pending_annotations_for_context(session)
                job.total_annotations = max(
                    job.total_annotations,
                    job.completed_annotations + len(pending),
                )
                if not pending:
                    job.status = FixJobStatus.completed
                    job.finished_at = server_module._now_iso()
                    await server_module._broadcast_fix_job(job)
                    return

                target_annotation = pending[0]
                step = FixJobStep(
                    index=len(job.steps) + 1,
                    annotation_id=target_annotation.id,
                    status=FixStepStatus.running,
                    started_at=server_module._now_iso(),
                )
                job.steps.append(step)
                await server_module._broadcast_fix_job(job)

                retry_context: str | None = None
                for attempt_index in range(1, server_module._fix_job_retry_limit + 1):
                    if job.runner == "codex":
                        await server_module._run_codex_fix_iteration(
                            job, step, extra_prompt=retry_context
                        )
                    elif job.runner == "claude":
                        await server_module._run_claude_fix_iteration(
                            job, step, extra_prompt=retry_context
                        )
                    else:
                        await server_module._run_opencode_fix_iteration(
                            job, step, extra_prompt=retry_context
                        )

                    refreshed_session = server_module._session_for_fix_job(job)
                    refreshed_annotation = next(
                        (
                            annotation
                            for annotation in refreshed_session.annotations
                            if annotation.id == target_annotation.id
                        ),
                        None,
                    )
                    addressed = (
                        refreshed_annotation is not None
                        and refreshed_annotation.status == AnnotationStatus.addressed
                    )
                    if step.exit_code == 0 and addressed:
                        break
                    if attempt_index >= server_module._fix_job_retry_limit:
                        break
                    retry_context = server_module._fix_retry_context(
                        step, annotation_id=target_annotation.id
                    )

                step.finished_at = server_module._now_iso()
                if job.status == FixJobStatus.cancelled:
                    step.status = FixStepStatus.cancelled
                    if not job.finished_at:
                        job.finished_at = server_module._now_iso()
                    await server_module._broadcast_fix_job(job)
                    return

                if step.exit_code != 0:
                    step.status = FixStepStatus.failed
                    if server_module._is_rate_limit_error(
                        job.runner,
                        stdout_text=step.stdout,
                        stderr_text=step.stderr,
                    ):
                        step.error = server_module._format_rate_limit_error(job.runner)
                        job.last_error = step.error
                    else:
                        step.error = f"{job.runner} exited with status {step.exit_code}"
                        stderr_summary = step.stderr.strip().splitlines()
                        if stderr_summary:
                            job.last_error = stderr_summary[-1]
                        else:
                            job.last_error = step.error
                    job.status = FixJobStatus.failed
                    job.finished_at = server_module._now_iso()
                    await server_module._broadcast_fix_job(job)
                    return

                refreshed_session = server_module._session_for_fix_job(job)
                refreshed_annotation = next(
                    (
                        annotation
                        for annotation in refreshed_session.annotations
                        if annotation.id == target_annotation.id
                    ),
                    None,
                )
                if (
                    refreshed_annotation is None
                    or refreshed_annotation.status != AnnotationStatus.addressed
                ):
                    step.status = FixStepStatus.failed
                    step.error = "Fix command completed but the target annotation was not addressed."
                    job.last_error = step.error
                    job.status = FixJobStatus.failed
                    job.finished_at = server_module._now_iso()
                    await server_module._broadcast_fix_job(job)
                    return

                step.status = FixStepStatus.completed
                step.error = None
                job.completed_annotations += 1
                remaining = len(
                    server_module.pending_annotations_for_context(refreshed_session)
                )
                job.total_annotations = max(
                    job.total_annotations,
                    job.completed_annotations + remaining,
                )
                await server_module._broadcast_fix_job(job)
        except Exception as exc:
            if not server_module._is_terminal_fix_job_status(job.status):
                if job.steps and job.steps[-1].status == FixStepStatus.running:
                    job.steps[-1].status = FixStepStatus.failed
                    job.steps[-1].finished_at = server_module._now_iso()
                    job.steps[-1].error = str(exc)
                job.status = FixJobStatus.failed
                job.last_error = str(exc)
                job.finished_at = server_module._now_iso()
                await server_module._broadcast_fix_job(job)
        finally:
            fix_job_processes.pop(job.id, None)
            fix_job_tasks.pop(job.id, None)
            server_module._clear_active_fix_job_for_session(
                job.session_id, expected_job_id=job.id
            )

    await server_module._with_runtime_async(resolved_runtime, _run)
