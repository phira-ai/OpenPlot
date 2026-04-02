"""Runner I/O helper implementations extracted from openplot.server."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from types import ModuleType
from typing import Literal, Mapping, cast

from .models import FixJob, FixJobStep, FixRunner, PlotModeState


def _tool_name_is_builtin_question_tool(
    server_module: ModuleType, name: str | None
) -> bool:
    _ = server_module
    normalized = (name or "").strip().lower().replace("_", "").replace("-", "")
    if not normalized:
        return False
    return normalized in {"askuserquestion", "question"}


def _candidate_tool_names_from_parsed_event(
    server_module: ModuleType, parsed: dict[str, object]
) -> list[str]:
    part = server_module._as_record(parsed.get("part")) or parsed
    item = server_module._as_record(parsed.get("item"))
    candidates: list[str] = []
    for candidate in (
        server_module._read_path(parsed, "part.tool_name"),
        server_module._read_path(parsed, "part.toolName"),
        server_module._read_path(parsed, "part.tool"),
        server_module._read_path(parsed, "part.tool.name"),
        server_module._read_path(parsed, "tool_name"),
        server_module._read_path(parsed, "toolName"),
        server_module._read_path(parsed, "tool"),
        server_module._read_path(parsed, "tool.name"),
        server_module._read_path(parsed, "name"),
        server_module._read_path(part, "name"),
        server_module._read_path(item, "tool") if item is not None else None,
        server_module._read_path(item, "name") if item is not None else None,
        server_module._read_path(item, "function.name") if item is not None else None,
    ):
        text = server_module._as_string(candidate)
        if text:
            candidates.append(text)
    return candidates


def _parsed_runner_uses_builtin_question_tool(
    server_module: ModuleType, runner: FixRunner, parsed: dict[str, object]
) -> bool:
    if runner == "claude":
        root_type = (
            (server_module._as_string(parsed.get("type")) or "")
            .lower()
            .replace("_", "-")
        )
        if root_type == "stream-event":
            event = server_module._as_record(parsed.get("event"))
            if event is None:
                return False
            event_type = (
                (server_module._as_string(event.get("type")) or "")
                .lower()
                .replace("_", "-")
            )
            if event_type != "content-block-start":
                return False
            content_block = server_module._as_record(event.get("content_block"))
            if content_block is None:
                return False
            block_type = (
                (server_module._as_string(content_block.get("type")) or "")
                .lower()
                .replace("_", "-")
            )
            return (
                block_type == "tool-use"
                and server_module._tool_name_is_builtin_question_tool(
                    server_module._as_string(content_block.get("name"))
                )
            )

        message = server_module._as_record(parsed.get("message"))
        if message is not None and isinstance(message.get("content"), list):
            for block_value in cast(list[object], message.get("content")):
                block = server_module._as_record(block_value)
                if block is None:
                    continue
                block_type = (
                    (server_module._as_string(block.get("type")) or "")
                    .lower()
                    .replace("_", "-")
                )
                if block_type not in {"tool-use", "tool_use"}:
                    continue
                if server_module._tool_name_is_builtin_question_tool(
                    server_module._as_string(block.get("name"))
                ):
                    return True
        return False

    part = server_module._as_record(parsed.get("part")) or parsed
    event_type = (
        (
            server_module._as_string(parsed.get("type"))
            or server_module._as_string(parsed.get("event"))
            or ""
        )
        .lower()
        .replace("_", "-")
    )
    part_type = (
        (server_module._as_string(part.get("type")) or "").lower().replace("_", "-")
    )
    item = server_module._as_record(parsed.get("item"))
    item_type = (
        ((server_module._as_string(item.get("type")) or "") if item is not None else "")
        .lower()
        .replace("_", "-")
    )
    if "tool" not in event_type and "tool" not in part_type and "tool" not in item_type:
        return False

    return any(
        server_module._tool_name_is_builtin_question_tool(candidate)
        for candidate in server_module._candidate_tool_names_from_parsed_event(parsed)
    )


def _parse_json_event_line(server_module: ModuleType, line: str) -> dict | None:
    _ = server_module
    stripped = line.strip()
    if not stripped or not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _parse_opencode_json_event_line(
    server_module: ModuleType, line: str
) -> dict | None:
    return server_module._parse_json_event_line(line)


def _extract_runner_session_id_from_event(
    server_module: ModuleType,
    runner: FixRunner,
    parsed: dict[str, object],
) -> str | None:
    candidate_paths: list[str]
    if runner == "codex":
        candidate_paths = [
            "thread_id",
            "threadId",
            "session_id",
            "sessionId",
            "session.id",
        ]
    elif runner == "claude":
        candidate_paths = [
            "session_id",
            "sessionId",
            "session.id",
        ]
    else:
        candidate_paths = [
            "sessionID",
            "sessionId",
            "session_id",
            "session.id",
        ]

    for path in candidate_paths:
        value = server_module._read_path(parsed, path)
        candidate = server_module._normalize_runner_session_id(value)
        if candidate is not None:
            return candidate
    return None


def _extract_runner_session_id_from_output(
    server_module: ModuleType,
    runner: FixRunner,
    output_text: str,
) -> str | None:
    for line in output_text.splitlines():
        parsed = server_module._parse_json_event_line(line)
        if parsed is None:
            continue
        session_id = server_module._extract_runner_session_id_from_event(runner, parsed)
        if session_id is not None:
            return session_id
    return None


def _extract_runner_reported_error(
    server_module: ModuleType,
    runner: FixRunner,
    *,
    stdout_text: str,
    stderr_text: str,
) -> str | None:
    if runner != "claude":
        return None

    for line in stdout_text.splitlines():
        parsed = server_module._parse_json_event_line(line)
        if parsed is None:
            continue

        root_type = (
            (server_module._as_string(parsed.get("type")) or "")
            .lower()
            .replace("_", "-")
        )
        if root_type != "result" or parsed.get("is_error") is not True:
            continue

        for candidate in (parsed.get("result"), parsed.get("error")):
            message = server_module._as_string(candidate)
            if message:
                return message
            if candidate is not None:
                try:
                    return json.dumps(candidate)
                except TypeError:
                    continue

        stderr_message = server_module._as_string(stderr_text)
        if stderr_message:
            return stderr_message
        return "Claude reported an error result"

    return None


def _is_resume_session_error(
    server_module: ModuleType,
    runner: FixRunner,
    *,
    stdout_text: str,
    stderr_text: str,
) -> bool:
    _ = server_module
    combined = f"{stderr_text}\n{stdout_text}".lower()
    if not combined:
        return False

    runner_keywords: tuple[str, ...]
    if runner == "codex":
        runner_keywords = ("thread", "session", "resume")
    elif runner == "claude":
        runner_keywords = ("session", "conversation", "resume")
    else:
        runner_keywords = ("session", "conversation", "resume")

    if not any(keyword in combined for keyword in runner_keywords):
        return False

    error_markers = (
        "not found",
        "does not exist",
        "doesn't exist",
        "unknown",
        "invalid",
        "expired",
        "failed to resume",
        "unable to resume",
        "cannot resume",
        "context length exceeded",
        "maximum context length",
        "context window",
        "too many tokens",
        "prompt is too long",
        "conversation is too long",
    )
    return any(marker in combined for marker in error_markers)


def _is_rate_limit_error(
    server_module: ModuleType,
    runner: FixRunner,
    *,
    stdout_text: str,
    stderr_text: str,
) -> bool:
    _ = server_module
    combined = f"{stderr_text}\n{stdout_text}".lower()
    if not combined:
        return False

    rate_limit_markers = (
        "rate_limit",
        "rate limit",
        "ratelimit",
        "too many requests",
        "you've hit your limit",
        "you\u2019ve hit your limit",
        "usage limit",
        "quota exceeded",
        "quota_exceeded",
        "overloaded",
    )

    if any(marker in combined for marker in rate_limit_markers):
        return True

    if runner == "claude" and '"status":"rejected"' in f"{stderr_text}\n{stdout_text}":
        return True

    return False


def _format_rate_limit_error(server_module: ModuleType, runner: FixRunner) -> str:
    _ = server_module
    return f"Backend rate limit reached ({runner}). Please wait a few minutes and try again."


def _append_retry_instruction(
    server_module: ModuleType,
    prompt: str,
    instruction: str,
) -> str:
    _ = server_module
    normalized_instruction = instruction.strip()
    if not normalized_instruction:
        return prompt
    if normalized_instruction in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\nAdditional instruction: {normalized_instruction}"


def _plot_mode_question_tool_retry_instruction(server_module: ModuleType) -> str:
    _ = server_module
    return (
        "The previous attempt tried to use a built-in interactive question tool. "
        "OpenPlot cannot answer built-in runner questions in CLI mode. "
        "Do not use AskUserQuestion or question tools. "
        "If user input is required, return it only in the structured OpenPlot response format requested above so OpenPlot can render a question card."
    )


def _fix_mode_question_tool_retry_instruction(server_module: ModuleType) -> str:
    _ = server_module
    return (
        "The previous attempt tried to use a built-in interactive question tool. "
        "OpenPlot cannot answer built-in runner questions during fix mode. "
        "Do not use AskUserQuestion or question tools. "
        "Do not ask the user for interactive input. "
        "Infer the most conservative interpretation from the current annotation, current script, and existing accepted fixes, then continue."
    )


def _extract_plot_mode_assistant_text(
    server_module: ModuleType,
    parsed: dict[str, object],
    part: dict[str, object],
) -> str | None:
    candidates = [
        server_module._read_path(part, "text"),
        server_module._read_path(part, "content"),
        server_module._read_path(part, "delta"),
        server_module._read_path(part, "message"),
        server_module._read_path(parsed, "text"),
        server_module._read_path(parsed, "content"),
        server_module._read_path(parsed, "message"),
        server_module._read_path(parsed, "output_text"),
    ]

    for candidate in candidates:
        lines = server_module._collect_text(candidate)
        if lines:
            return "".join(lines).strip()
    return None


def _extract_codex_plot_mode_stream_fragment(
    server_module: ModuleType,
    parsed: dict[str, object],
) -> tuple[str, bool] | None:
    event_type = (
        (
            server_module._as_string(parsed.get("type"))
            or server_module._as_string(parsed.get("event"))
            or ""
        )
        .lower()
        .strip()
    )
    if not event_type.startswith("item."):
        return None

    item = server_module._as_record(parsed.get("item"))
    if item is None:
        return None

    item_type = (server_module._as_string(item.get("type")) or "").lower().strip()
    if item_type != "agent_message":
        return None

    assistant_text = (
        server_module._as_string(item.get("text"))
        or server_module._as_string(server_module._read_path(item, "message"))
        or server_module._as_string(server_module._read_path(item, "output_text"))
        or server_module._join_collected_text(item.get("content"))
        or server_module._join_collected_text(item.get("result"))
    )
    if not assistant_text:
        return None
    return assistant_text, False


def _extract_opencode_plot_mode_stream_fragment(
    server_module: ModuleType,
    parsed: dict[str, object],
) -> tuple[str, bool] | None:
    part = server_module._as_record(parsed.get("part")) or parsed
    event_type_raw = (
        server_module._as_string(parsed.get("type"))
        or server_module._as_string(parsed.get("event"))
        or server_module._as_string(part.get("type"))
        or "event"
    )
    event_type = event_type_raw.lower().replace("_", "-")
    if "error" in event_type or "fail" in event_type or "tool" in event_type:
        return None

    assistant_text = server_module._extract_plot_mode_assistant_text(parsed, part)
    if not assistant_text:
        return None
    return assistant_text, False


def _extract_claude_plot_mode_stream_fragment(
    server_module: ModuleType,
    parsed: dict[str, object],
) -> tuple[str, bool] | None:
    root_type = (
        (server_module._as_string(parsed.get("type")) or "").lower().replace("_", "-")
    )

    if root_type == "stream-event":
        event = server_module._as_record(parsed.get("event"))
        if event is None:
            return None

        event_type = (
            (server_module._as_string(event.get("type")) or "event")
            .lower()
            .replace("_", "-")
        )
        if event_type == "content-block-delta":
            delta = server_module._as_record(event.get("delta"))
            delta_type = (
                (server_module._as_string(delta.get("type")) or "")
                .lower()
                .replace("_", "-")
                if delta
                else ""
            )
            if delta_type == "text-delta":
                text = (
                    server_module._as_non_empty_string(delta.get("text"))
                    if delta
                    else None
                )
                if text:
                    return text, True
            return None

        return None

    if root_type == "assistant":
        message = server_module._as_record(parsed.get("message"))
        if message is None:
            return None

        content = message.get("content")
        if not isinstance(content, list):
            return None

        text_parts: list[str] = []
        for block_value in content:
            block = server_module._as_record(block_value)
            if block is None:
                continue
            block_type = (
                (server_module._as_string(block.get("type")) or "")
                .lower()
                .replace("_", "-")
            )
            if block_type != "text":
                continue
            text = server_module._as_non_empty_string(
                block.get("text")
            ) or server_module._join_collected_text(block)
            if text:
                text_parts.append(text)

        if text_parts:
            return "".join(text_parts), False
        return None

    message = server_module._as_record(parsed.get("message"))
    content_block = server_module._as_record(parsed.get("content_block"))
    part = (
        server_module._as_record(parsed.get("part"))
        or content_block
        or message
        or parsed
    )
    event_type = (
        (
            server_module._as_string(parsed.get("type"))
            or server_module._as_string(parsed.get("event"))
            or server_module._as_string(part.get("type"))
            or "event"
        )
        .lower()
        .replace("_", "-")
    )
    part_type = (
        (server_module._as_string(part.get("type")) or "").lower().replace("_", "-")
    )
    if "tool" in event_type or "tool" in part_type:
        return None

    assistant_text = (
        server_module._as_string(server_module._read_path(parsed, "delta.text"))
        or server_module._as_string(
            server_module._read_path(parsed, "content_block.text")
        )
        or server_module._as_string(server_module._read_path(parsed, "text"))
        or server_module._join_collected_text(
            server_module._read_path(parsed, "message.content")
        )
        or server_module._extract_plot_mode_assistant_text(parsed, part)
    )
    if not assistant_text:
        return None
    return assistant_text, False


def _extract_plot_mode_stream_fragment(
    server_module: ModuleType,
    runner: FixRunner,
    parsed: dict[str, object],
) -> tuple[str, bool] | None:
    if runner == "codex":
        return server_module._extract_codex_plot_mode_stream_fragment(parsed)
    if runner == "claude":
        return server_module._extract_claude_plot_mode_stream_fragment(parsed)
    return server_module._extract_opencode_plot_mode_stream_fragment(parsed)


async def _consume_plot_mode_text_stream(
    server_module: ModuleType,
    stream: asyncio.StreamReader | None,
    sink: list[str],
    *,
    runner: FixRunner | None = None,
    process: asyncio.subprocess.Process | None = None,
) -> None:
    if stream is None:
        return

    buffered = ""
    question_tool_seen = False

    while True:
        chunk_bytes = await stream.read(8192)
        if not chunk_bytes:
            break

        chunk = chunk_bytes.decode("utf-8", errors="replace")
        sink.append(chunk)

        if runner is None or process is None or question_tool_seen:
            continue

        buffered += chunk
        while True:
            newline_index = buffered.find("\n")
            if newline_index < 0:
                break
            line = buffered[: newline_index + 1]
            buffered = buffered[newline_index + 1 :]
            parsed = server_module._parse_json_event_line(line)
            if parsed is None:
                continue
            if server_module._parsed_runner_uses_builtin_question_tool(runner, parsed):
                question_tool_seen = True
                await server_module._terminate_fix_process(process)
                break

    if runner is None or process is None or question_tool_seen or not buffered:
        return
    parsed = server_module._parse_json_event_line(buffered)
    if parsed is not None and server_module._parsed_runner_uses_builtin_question_tool(
        runner, parsed
    ):
        await server_module._terminate_fix_process(process)


def _resolve_plot_mode_final_assistant_text(
    server_module: ModuleType,
    *,
    runner: FixRunner,
    stdout_text: str,
    output_path: Path | None,
) -> str:
    if runner == "codex" and output_path is not None:
        try:
            file_text = server_module._read_file_text(output_path).strip()
        except OSError:
            file_text = ""
        if file_text:
            return file_text

    collected_text = ""
    for line in stdout_text.splitlines():
        parsed = server_module._parse_json_event_line(line)
        if parsed is None:
            continue
        fragment = server_module._extract_plot_mode_stream_fragment(
            runner, cast(dict[str, object], parsed)
        )
        if fragment is None:
            continue
        text, append = fragment
        collected_text = server_module._join_streaming_text(
            collected_text, text, append=append
        )
    if collected_text.strip():
        return collected_text.strip()

    raw_stdout = stdout_text.strip()
    if not raw_stdout:
        return ""

    if not any(line.lstrip().startswith("{") for line in raw_stdout.splitlines()):
        return raw_stdout

    return ""


async def _run_plot_mode_runner_prompt(
    server_module: ModuleType,
    *,
    state: PlotModeState,
    runner: FixRunner,
    prompt: str,
    model: str,
    variant: str | None,
) -> tuple[str, str | None]:
    current_resume_session_id = server_module._runner_session_id_for_plot_mode(
        state, runner
    )
    current_prompt = prompt
    question_tool_retry_count = 0
    return_code: int | None = None
    stdout_text = ""
    stderr_text = ""
    assistant_text = ""

    while True:
        output_path: Path | None = None
        normalized_resume_session_id = server_module._normalize_runner_session_id(
            current_resume_session_id
        )

        if runner == "codex":
            codex_command = server_module._resolve_command_path("codex")
            if codex_command is None:
                return "", "Failed to launch codex: command not found"
            if normalized_resume_session_id:
                command = [
                    codex_command,
                    "exec",
                    "resume",
                    "--skip-git-repo-check",
                    "--json",
                    "-c",
                    'approval_policy="never"',
                    "--model",
                    model,
                    normalized_resume_session_id,
                ]
            else:
                output_file = tempfile.NamedTemporaryFile(delete=False)
                output_file.close()
                output_path = Path(output_file.name)
                command = [
                    codex_command,
                    "exec",
                    "--cd",
                    str(state.workspace_dir),
                    "--skip-git-repo-check",
                    "--json",
                    "--sandbox",
                    "workspace-write",
                    "-c",
                    'approval_policy="never"',
                    "--model",
                    model,
                    "--output-last-message",
                    str(output_path),
                ]
            normalized_variant = (variant or "").strip()
            if normalized_variant:
                command.extend(
                    [
                        "-c",
                        f"model_reasoning_effort={json.dumps(normalized_variant)}",
                    ]
                )
            command.append(current_prompt)
        elif runner == "claude":
            claude_command = server_module._resolve_claude_cli_command()
            if claude_command is None:
                return "", "Failed to launch claude: command not found"

            command = [
                claude_command,
                "-p",
                current_prompt,
                "--output-format",
                "stream-json",
                "--verbose",
                "--include-partial-messages",
                "--permission-mode",
                "bypassPermissions",
                "--disallowedTools",
                "AskUserQuestion",
                "--model",
                model,
            ]
            if normalized_resume_session_id:
                command.extend(["--resume", normalized_resume_session_id])

            normalized_variant = (variant or "").strip()
            if normalized_variant:
                command.extend(["--effort", normalized_variant])
        else:
            opencode_command = server_module._resolve_command_path("opencode")
            if opencode_command is None:
                return "", "Failed to launch opencode: command not found"
            command = [
                opencode_command,
                "run",
                "--dir",
                str(state.workspace_dir),
                "--format",
                "json",
                "--model",
                model,
            ]
            if normalized_resume_session_id:
                command.extend(["--session", normalized_resume_session_id])
            if variant:
                command.extend(["--variant", variant])
            command.append(current_prompt)

        env_overrides = (
            {
                "OPENCODE_CONFIG_CONTENT": server_module._opencode_question_tool_disabled_config_content()
            }
            if runner == "opencode"
            else None
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(state.workspace_dir),
                env=server_module._subprocess_env(overrides=env_overrides),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **server_module._hidden_window_kwargs(),
                **({"start_new_session": True} if sys.platform != "win32" else {}),
            )
        except OSError as exc:
            if output_path is not None:
                output_path.unlink(missing_ok=True)
            return "", f"Failed to launch {runner}: {exc}"

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        stdout_task = asyncio.create_task(
            server_module._consume_plot_mode_text_stream(
                process.stdout,
                stdout_chunks,
                runner=runner,
                process=process,
            )
        )
        stderr_task = asyncio.create_task(
            server_module._consume_plot_mode_text_stream(process.stderr, stderr_chunks)
        )

        try:
            await process.wait()
            results = await asyncio.gather(
                stdout_task,
                stderr_task,
                return_exceptions=True,
            )
            for label, result in (("stdout", results[0]), ("stderr", results[1])):
                if isinstance(result, Exception):
                    stderr_chunks.append(
                        f"[openplot warning] failed to read {label} stream: {result}\n"
                    )
        finally:
            if output_path is not None and runner != "codex":
                output_path.unlink(missing_ok=True)

        return_code = process.returncode
        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)

        discovered_session_id = server_module._extract_runner_session_id_from_output(
            runner, stdout_text
        )
        if discovered_session_id is not None:
            server_module._set_runner_session_id_for_plot_mode(
                state,
                runner=runner,
                session_id=discovered_session_id,
            )

        assistant_text = server_module._resolve_plot_mode_final_assistant_text(
            runner=runner,
            stdout_text=stdout_text,
            output_path=output_path,
        )

        if output_path is not None:
            output_path.unlink(missing_ok=True)

        if server_module._runner_output_used_builtin_question_tool(runner, stdout_text):
            server_module._clear_runner_session_id_for_plot_mode(state, runner)
            if question_tool_retry_count >= 1:
                return assistant_text, (
                    "Runner attempted an unsupported built-in question tool. "
                    "Please try again after clarifying the request in plain language."
                )
            current_resume_session_id = None
            current_prompt = server_module._append_retry_instruction(
                current_prompt,
                server_module._plot_mode_question_tool_retry_instruction(),
            )
            question_tool_retry_count += 1
            continue

        if (
            return_code != 0
            and normalized_resume_session_id
            and server_module._is_resume_session_error(
                runner,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
            )
        ):
            server_module._clear_runner_session_id_for_plot_mode(state, runner)
            current_resume_session_id = None
            continue

        break

    if return_code != 0:
        if server_module._is_rate_limit_error(
            runner,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
        ):
            return assistant_text, server_module._format_rate_limit_error(runner)
        details = (
            stderr_text.strip()
            or stdout_text.strip()
            or f"{runner} exited with {return_code}"
        )
        return assistant_text, f"Runner request failed: {details}"

    return assistant_text, None


async def _consume_fix_stream(
    server_module: ModuleType,
    *,
    job: FixJob,
    step: FixJobStep,
    runner: FixRunner,
    process: asyncio.subprocess.Process,
    stream_name: Literal["stdout", "stderr"],
    stream: asyncio.StreamReader | None,
    sink: list[str],
) -> None:
    if stream is None:
        return

    buffered = ""
    question_tool_seen = False

    while True:
        chunk_bytes = await stream.read(8192)
        if not chunk_bytes:
            break

        chunk = chunk_bytes.decode("utf-8", errors="replace")
        sink.append(chunk)

        buffered += chunk
        while True:
            newline_index = buffered.find("\n")
            if newline_index < 0:
                break
            line = buffered[: newline_index + 1]
            buffered = buffered[newline_index + 1 :]

            parsed = (
                server_module._parse_json_event_line(line)
                if stream_name == "stdout"
                else None
            )
            if (
                parsed is not None
                and not question_tool_seen
                and server_module._parsed_runner_uses_builtin_question_tool(
                    runner, parsed
                )
            ):
                question_tool_seen = True
                await server_module._terminate_fix_process(process)
            await server_module._broadcast_fix_job_log(
                job_id=job.id,
                step_index=step.index,
                annotation_id=step.annotation_id,
                stream=stream_name,
                chunk=line,
                parsed=parsed,
            )

    if buffered:
        parsed = (
            server_module._parse_json_event_line(buffered)
            if stream_name == "stdout"
            else None
        )
        if (
            parsed is not None
            and not question_tool_seen
            and server_module._parsed_runner_uses_builtin_question_tool(runner, parsed)
        ):
            await server_module._terminate_fix_process(process)
        await server_module._broadcast_fix_job_log(
            job_id=job.id,
            step_index=step.index,
            annotation_id=step.annotation_id,
            stream=stream_name,
            chunk=buffered,
            parsed=parsed,
        )


async def _run_fix_iteration_command(
    server_module: ModuleType,
    *,
    job: FixJob,
    step: FixJobStep,
    command: list[str],
    display_command: list[str] | None = None,
    cwd: Path | None = None,
    env_overrides: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    step.command = display_command or command

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    resolved_cwd = (cwd or server_module._workspace_dir).resolve()
    process_env = server_module._subprocess_env(overrides=env_overrides)

    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(resolved_cwd),
        env=process_env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **server_module._hidden_window_kwargs(),
        **({"start_new_session": True} if sys.platform != "win32" else {}),
    )
    server_module._runtime_fix_job_processes_map()[job.id] = process

    stdout_task = asyncio.create_task(
        server_module._consume_fix_stream(
            job=job,
            step=step,
            runner=job.runner,
            process=process,
            stream_name="stdout",
            stream=process.stdout,
            sink=stdout_chunks,
        )
    )
    stderr_task = asyncio.create_task(
        server_module._consume_fix_stream(
            job=job,
            step=step,
            runner=job.runner,
            process=process,
            stream_name="stderr",
            stream=process.stderr,
            sink=stderr_chunks,
        )
    )

    try:
        await process.wait()
        await asyncio.sleep(0)
    finally:
        for stream_label, task in (("stdout", stdout_task), ("stderr", stderr_task)):
            if task.done():
                with suppress(asyncio.CancelledError):
                    try:
                        _ = task.result()
                    except Exception as exc:
                        stderr_chunks.append(
                            (
                                "[openplot warning] "
                                f"failed to read {stream_label} stream: {exc}\n"
                            )
                        )
                continue
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        server_module._runtime_fix_job_processes_map().pop(job.id, None)

    step.exit_code = process.returncode
    raw_stdout = "".join(stdout_chunks)
    raw_stderr = "".join(stderr_chunks)
    step.stdout = server_module._truncate_output(raw_stdout)
    step.stderr = server_module._truncate_output(raw_stderr)
    return raw_stdout, raw_stderr
