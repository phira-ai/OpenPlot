import ast
import asyncio
import importlib
import json
from pathlib import Path
from typing import Any, Sequence, TypeAlias, cast

import pytest

import openplot.server as server
from openplot.models import FixJob, FixJobStep


EXTRACTED_RUNNER_IO_HELPERS = (
    "_parse_json_event_line",
    "_parse_opencode_json_event_line",
    "_extract_runner_session_id_from_event",
    "_extract_runner_session_id_from_output",
    "_extract_runner_reported_error",
    "_is_resume_session_error",
    "_is_rate_limit_error",
    "_format_rate_limit_error",
    "_append_retry_instruction",
    "_plot_mode_question_tool_retry_instruction",
    "_fix_mode_question_tool_retry_instruction",
    "_extract_plot_mode_assistant_text",
    "_extract_codex_plot_mode_stream_fragment",
    "_extract_opencode_plot_mode_stream_fragment",
    "_extract_claude_plot_mode_stream_fragment",
    "_extract_plot_mode_stream_fragment",
    "_consume_plot_mode_text_stream",
    "_resolve_plot_mode_final_assistant_text",
    "_run_plot_mode_runner_prompt",
    "_consume_fix_stream",
    "_run_fix_iteration_command",
)

FunctionNode: TypeAlias = ast.FunctionDef | ast.AsyncFunctionDef


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
    def __init__(
        self, *, stdout_text: str = "", stderr_text: str = "", returncode: int = 0
    ):
        self.stdout = _ChunkedTextReader(stdout_text)
        self.stderr = _ChunkedTextReader(stderr_text)
        self.returncode = returncode
        self.pid = 0

    async def wait(self) -> int:
        return self.returncode


def _read_module_ast(module_path: Path) -> tuple[ast.Module, dict[str, FunctionNode]]:
    tree = ast.parse(module_path.read_text(), filename=str(module_path))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    return tree, functions


def _server_path() -> Path:
    return Path(server.__file__).resolve()


def _runner_io_path() -> Path:
    return _server_path().with_name("server_runner_io.py")


def _server_uses_extracted_runner_io(module: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == "_server_runner_io"
        for node in ast.walk(module)
    )


def _server_module_reference(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "sys"
        and node.value.attr == "modules"
        and isinstance(node.slice, ast.Name)
        and node.slice.id == "__name__"
    )


def _dump_nodes(nodes: Sequence[ast.expr | None]) -> list[str | None]:
    return [None if node is None else ast.dump(node) for node in nodes]


def _signature_shape(
    function: FunctionNode,
    *,
    drop_leading_server_module: bool = False,
) -> dict[str, object]:
    posonlyargs = [arg.arg for arg in function.args.posonlyargs]
    args = [arg.arg for arg in function.args.args]
    if drop_leading_server_module:
        if not args or args[0] != "server_module":
            raise AssertionError("Extracted helper must accept server_module first")
        args = args[1:]
    return {
        "posonlyargs": posonlyargs,
        "args": args,
        "vararg": None if function.args.vararg is None else function.args.vararg.arg,
        "kwonlyargs": [arg.arg for arg in function.args.kwonlyargs],
        "kwarg": None if function.args.kwarg is None else function.args.kwarg.arg,
        "defaults": _dump_nodes(function.args.defaults),
        "kw_defaults": _dump_nodes(function.args.kw_defaults),
    }


def _returns_none(function: FunctionNode) -> bool:
    return (
        function.returns is not None
        and isinstance(function.returns, ast.Constant)
        and function.returns.value is None
    )


def _positional_parameter_names(function: FunctionNode) -> list[str]:
    return [
        *(arg.arg for arg in function.args.posonlyargs),
        *(arg.arg for arg in function.args.args),
    ]


def _contains_patchable_server_helper_reference(
    node: ast.AST,
    *,
    server_aliases: set[str],
    openplot_aliases: set[str],
) -> bool:
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Attribute)
            and child.attr.startswith("_")
            and isinstance(child.value, ast.Name)
            and child.value.id in server_aliases
        ):
            return True
        if (
            isinstance(child, ast.Attribute)
            and child.attr.startswith("_")
            and isinstance(child.value, ast.Attribute)
            and child.value.attr == "server"
            and isinstance(child.value.value, ast.Name)
            and child.value.value.id in openplot_aliases
        ):
            return True
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "getattr"
            and len(child.args) >= 2
        ):
            target = child.args[0]
            helper_name = child.args[1]
            if not (
                isinstance(helper_name, ast.Constant)
                and isinstance(helper_name.value, str)
                and helper_name.value.startswith("_")
            ):
                continue
            if isinstance(target, ast.Name) and target.id in server_aliases:
                return True
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "server"
                and isinstance(target.value, ast.Name)
                and target.value.id in openplot_aliases
            ):
                return True
    return False


def _assert_no_patchable_server_helper_reference(
    node: ast.AST | None,
    *,
    server_aliases: set[str],
    openplot_aliases: set[str],
) -> None:
    if node is None:
        return
    assert not _contains_patchable_server_helper_reference(
        node,
        server_aliases=server_aliases,
        openplot_aliases=openplot_aliases,
    ), (
        "server_runner_io.py must not cache patchable server helpers at module import time"
    )


def _assert_no_patchable_server_helper_references_in_statement(
    node: ast.stmt,
    *,
    server_aliases: set[str],
    openplot_aliases: set[str],
) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.expr):
            _assert_no_patchable_server_helper_reference(
                child,
                server_aliases=server_aliases,
                openplot_aliases=openplot_aliases,
            )
        elif isinstance(child, ast.stmt):
            _assert_no_patchable_server_helper_references_in_statement(
                child,
                server_aliases=server_aliases,
                openplot_aliases=openplot_aliases,
            )


def _assert_pre_extraction_contract(functions: dict[str, FunctionNode]) -> None:
    for helper_name in EXTRACTED_RUNNER_IO_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"


def _load_runner_io_module_if_wired() -> Any | None:
    server_module, _ = _read_module_ast(_server_path())
    if not _server_uses_extracted_runner_io(server_module):
        assert not _runner_io_path().exists(), (
            "server_runner_io.py exists before server.py wires the runner-I/O seam"
        )
        return None
    assert _runner_io_path().exists(), (
        "server.py references _server_runner_io but server_runner_io.py is missing"
    )
    return importlib.import_module("openplot.server_runner_io")


def test_patchable_server_helper_guard_catches_runner_io_aliases() -> None:
    server_alias_tree = ast.parse("cached = server._consume_fix_stream")
    assert _contains_patchable_server_helper_reference(
        server_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    server_module_alias_tree = ast.parse(
        "cached = server_module._terminate_fix_process"
    )
    assert _contains_patchable_server_helper_reference(
        server_module_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    openplot_alias_tree = ast.parse(
        "cached = openplot.server._extract_runner_session_id_from_output"
    )
    assert _contains_patchable_server_helper_reference(
        openplot_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases={"openplot"},
    )


def test_runner_io_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> None:
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and "_server_runner_io" in bound_helpers:
        assert set(EXTRACTED_RUNNER_IO_HELPERS) <= set(
            bound_helpers["_server_runner_io"]
        )
        for helper_name in EXTRACTED_RUNNER_IO_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_module, functions = _read_module_ast(_server_path())
    _assert_pre_extraction_contract(functions)

    if not _server_uses_extracted_runner_io(server_module):
        assert not _runner_io_path().exists()
        return

    _, runner_io_functions = _read_module_ast(_runner_io_path())

    for helper_name in EXTRACTED_RUNNER_IO_HELPERS:
        function = functions[helper_name]
        runner_io_function = runner_io_functions.get(helper_name)
        assert runner_io_function is not None, (
            f"Missing extracted helper for {helper_name}"
        )
        assert _signature_shape(function) == _signature_shape(
            runner_io_function, drop_leading_server_module=True
        )
        assert len(function.body) == 1, (
            f"{helper_name} should stay a one-statement wrapper"
        )

        statement = function.body[0]
        if _returns_none(runner_io_function):
            assert isinstance(statement, (ast.Expr, ast.Return))
        else:
            assert isinstance(statement, ast.Return)

        call = statement.value
        if isinstance(function, ast.AsyncFunctionDef):
            assert isinstance(call, ast.Await), (
                f"{helper_name} should await the extracted async helper"
            )
            call = call.value
        elif isinstance(call, ast.Await):
            call = call.value

        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Attribute)
        assert isinstance(call.func.value, ast.Name)
        assert call.func.value.id == "_server_runner_io"
        assert call.func.attr == helper_name
        assert call.args, f"{helper_name} should pass the server module first"
        assert _server_module_reference(call.args[0])

        positional_parameter_names = _positional_parameter_names(function)
        assert len(call.args[1:]) == len(positional_parameter_names)
        for argument, parameter_name in zip(
            call.args[1:], positional_parameter_names, strict=True
        ):
            assert isinstance(argument, ast.Name)
            assert argument.id == parameter_name

        kwonly_keywords = [
            keyword for keyword in call.keywords if keyword.arg is not None
        ]
        assert len(kwonly_keywords) == len(function.args.kwonlyargs)
        for keyword, parameter in zip(
            kwonly_keywords, function.args.kwonlyargs, strict=True
        ):
            assert keyword.arg == parameter.arg
            assert isinstance(keyword.value, ast.Name)
            assert keyword.value.id == parameter.arg

        kwarg_keywords = [keyword for keyword in call.keywords if keyword.arg is None]
        if function.args.kwarg is not None:
            assert len(kwarg_keywords) == 1
            assert isinstance(kwarg_keywords[0].value, ast.Name)
            assert kwarg_keywords[0].value.id == function.args.kwarg.arg
        else:
            assert not kwarg_keywords


def test_task2_runner_io_seam_is_wired() -> None:
    server_module, _ = _read_module_ast(_server_path())

    assert _server_uses_extracted_runner_io(server_module), (
        "Task 2 requires server.py to wire the extracted runner-I/O module"
    )
    assert _runner_io_path().exists(), (
        "Task 2 requires src/openplot/server_runner_io.py to exist"
    )


def test_runner_io_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    if _load_runner_io_module_if_wired() is None:
        return

    module, _ = _read_module_ast(_runner_io_path())
    server_aliases = {"server", "server_module"}
    openplot_aliases: set[str] = set()

    for node in module.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openplot":
                    openplot_aliases.add(alias.asname or alias.name)
                if alias.name == "openplot.server":
                    raise AssertionError(
                        "Forbidden import-time binding source in server_runner_io.py: openplot.server"
                    )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name == "openplot" and any(
                alias.name == "server" for alias in node.names
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_runner_io.py: from openplot import server"
                )
            if module_name == "openplot.server":
                raise AssertionError(
                    "Forbidden import-time binding source in server_runner_io.py: direct import from openplot.server"
                )
            if (
                node.level > 0
                and module_name == ""
                and any(alias.name == "server" for alias in node.names)
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_runner_io.py: from . import server"
                )
            if node.level > 0 and module_name == "server":
                raise AssertionError(
                    "Forbidden import-time binding source in server_runner_io.py: direct relative import from server"
                )

    for node in module.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            _assert_no_patchable_server_helper_reference(
                node.value,
                server_aliases=server_aliases,
                openplot_aliases=openplot_aliases,
            )
        elif isinstance(node, ast.Expr):
            _assert_no_patchable_server_helper_reference(
                node.value,
                server_aliases=server_aliases,
                openplot_aliases=openplot_aliases,
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in node.args.defaults:
                _assert_no_patchable_server_helper_reference(
                    default,
                    server_aliases=server_aliases,
                    openplot_aliases=openplot_aliases,
                )
            for default in node.args.kw_defaults:
                _assert_no_patchable_server_helper_reference(
                    default,
                    server_aliases=server_aliases,
                    openplot_aliases=openplot_aliases,
                )
            for decorator in node.decorator_list:
                _assert_no_patchable_server_helper_reference(
                    decorator,
                    server_aliases=server_aliases,
                    openplot_aliases=openplot_aliases,
                )
        elif isinstance(node, ast.ClassDef):
            for decorator in node.decorator_list:
                _assert_no_patchable_server_helper_reference(
                    decorator,
                    server_aliases=server_aliases,
                    openplot_aliases=openplot_aliases,
                )
            for base in node.bases:
                _assert_no_patchable_server_helper_reference(
                    base,
                    server_aliases=server_aliases,
                    openplot_aliases=openplot_aliases,
                )
            for keyword in node.keywords:
                _assert_no_patchable_server_helper_reference(
                    keyword.value,
                    server_aliases=server_aliases,
                    openplot_aliases=openplot_aliases,
                )
            for statement in node.body:
                if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    _assert_no_patchable_server_helper_reference(
                        statement.value,
                        server_aliases=server_aliases,
                        openplot_aliases=openplot_aliases,
                    )
        elif isinstance(
            node,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.With,
                ast.AsyncWith,
                ast.Try,
                ast.Match,
            ),
        ):
            _assert_no_patchable_server_helper_references_in_statement(
                node,
                server_aliases=server_aliases,
                openplot_aliases=openplot_aliases,
            )


@pytest.mark.anyio
async def test_run_plot_mode_runner_prompt_uses_live_server_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner_io_module = _load_runner_io_module_if_wired()
    if runner_io_module is None:
        return

    state = server.init_plot_mode_session(workspace_dir=tmp_path)
    state.runner_session_ids["opencode"] = "resume-123"

    processes = [
        _FakeProcess(stdout_text='{"attempt": 1}\n'),
        _FakeProcess(stdout_text='{"attempt": 2}\n'),
    ]
    created_commands: list[list[str]] = []
    calls: list[tuple[str, object]] = []

    async def fake_create_subprocess_exec(*command, **kwargs):
        _ = kwargs
        created_commands.append(list(command))
        return processes.pop(0)

    def _failfast(*args, **kwargs):
        raise AssertionError("runner_io module should resolve helpers through server")

    monkeypatch.setattr(
        server.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )
    monkeypatch.setattr(server, "_resolve_command_path", lambda command: command)
    monkeypatch.setattr(
        server, "_subprocess_env", lambda overrides=None: overrides or {}
    )
    monkeypatch.setattr(server, "_hidden_window_kwargs", lambda: {})
    monkeypatch.setattr(
        server,
        "_extract_runner_session_id_from_output",
        lambda runner, text: (
            calls.append(("extract_session", (runner, text))) or "patched-session"
        ),
    )
    monkeypatch.setattr(
        server,
        "_set_runner_session_id_for_plot_mode",
        lambda state, *, runner, session_id: calls.append(
            ("set_session", (runner, session_id, state.id))
        ),
    )
    monkeypatch.setattr(
        server,
        "_resolve_plot_mode_final_assistant_text",
        lambda **kwargs: (
            calls.append(("resolve_text", kwargs["stdout_text"]))
            or kwargs["stdout_text"].strip()
        ),
    )
    question_tool_results = iter([True, False])
    monkeypatch.setattr(
        server,
        "_runner_output_used_builtin_question_tool",
        lambda runner, text: (
            calls.append(("question_tool", text)) or next(question_tool_results)
        ),
    )
    monkeypatch.setattr(
        server,
        "_clear_runner_session_id_for_plot_mode",
        lambda state, runner: calls.append(("clear_session", runner)),
    )
    monkeypatch.setattr(
        server,
        "_append_retry_instruction",
        lambda prompt, instruction: (
            calls.append(("append_retry", instruction))
            or f"{prompt}\nRETRY:{instruction}"
        ),
    )
    monkeypatch.setattr(
        server,
        "_plot_mode_question_tool_retry_instruction",
        lambda: calls.append(("retry_instruction", None)) or "retry-live",
    )

    monkeypatch.setattr(
        runner_io_module,
        "_extract_runner_session_id_from_output",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        runner_io_module,
        "_resolve_plot_mode_final_assistant_text",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        runner_io_module,
        "_runner_output_used_builtin_question_tool",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        runner_io_module,
        "_clear_runner_session_id_for_plot_mode",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        runner_io_module,
        "_append_retry_instruction",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        runner_io_module,
        "_plot_mode_question_tool_retry_instruction",
        _failfast,
        raising=False,
    )

    assistant_text, runner_error = await server._run_plot_mode_runner_prompt(
        state=state,
        runner="opencode",
        prompt="Plan the next step.",
        model="openai/gpt-5.3-codex",
        variant="high",
    )

    assert (assistant_text, runner_error) == ('{"attempt": 2}', None)
    assert len(created_commands) == 2
    assert "--session" in created_commands[0]
    assert "--session" not in created_commands[1]
    assert created_commands[1][-1].endswith("RETRY:retry-live")
    assert ("retry_instruction", None) in calls
    assert ("append_retry", "retry-live") in calls
    assert ("clear_session", "opencode") in calls


@pytest.mark.anyio
async def test_consume_fix_stream_uses_live_broadcast_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_io_module = _load_runner_io_module_if_wired()
    if runner_io_module is None:
        return

    payload = json.dumps({"type": "text", "part": {"text": "hello"}}) + "\n"
    reader = _ChunkedTextReader(payload)
    sink: list[str] = []
    captured_logs: list[dict[str, object]] = []
    job = FixJob(
        model="openai/gpt-5.3-codex", branch_id="branch-main", branch_name="main"
    )
    step = FixJobStep(index=1, annotation_id="ann-1")

    async def fake_broadcast_fix_job_log(**kwargs) -> None:
        captured_logs.append(kwargs)

    async def fake_terminate_fix_process(process) -> None:
        raise AssertionError("terminate should not run")

    def _failfast(*args, **kwargs):
        raise AssertionError("runner_io module should resolve helpers through server")

    monkeypatch.setattr(server, "_broadcast_fix_job_log", fake_broadcast_fix_job_log)
    monkeypatch.setattr(server, "_terminate_fix_process", fake_terminate_fix_process)
    monkeypatch.setattr(
        server,
        "_parsed_runner_uses_builtin_question_tool",
        lambda runner, parsed: False,
    )
    monkeypatch.setattr(
        runner_io_module, "_broadcast_fix_job_log", _failfast, raising=False
    )
    monkeypatch.setattr(
        runner_io_module,
        "_parsed_runner_uses_builtin_question_tool",
        _failfast,
        raising=False,
    )

    await server._consume_fix_stream(
        job=job,
        step=step,
        runner="opencode",
        process=cast(asyncio.subprocess.Process, object()),
        stream_name="stdout",
        stream=cast(asyncio.StreamReader, reader),
        sink=sink,
    )

    assert "".join(sink) == payload
    assert len(captured_logs) == 1
    assert captured_logs[0]["chunk"] == payload
    assert captured_logs[0]["parsed"] is not None


@pytest.mark.anyio
async def test_consume_fix_stream_uses_live_terminate_helper_for_question_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_io_module = _load_runner_io_module_if_wired()
    if runner_io_module is None:
        return

    payload = json.dumps({"type": "text", "part": {"text": "hello"}}) + "\n"
    reader = _ChunkedTextReader(payload)
    sink: list[str] = []
    captured_logs: list[dict[str, object]] = []
    terminated: list[object] = []
    process = cast(asyncio.subprocess.Process, object())
    job = FixJob(
        model="openai/gpt-5.3-codex", branch_id="branch-main", branch_name="main"
    )
    step = FixJobStep(index=1, annotation_id="ann-1")

    async def fake_broadcast_fix_job_log(**kwargs) -> None:
        captured_logs.append(kwargs)

    async def fake_terminate_fix_process(process) -> None:
        terminated.append(process)

    def _failfast(*args, **kwargs):
        raise AssertionError("runner_io module should resolve helpers through server")

    monkeypatch.setattr(server, "_broadcast_fix_job_log", fake_broadcast_fix_job_log)
    monkeypatch.setattr(server, "_terminate_fix_process", fake_terminate_fix_process)
    monkeypatch.setattr(
        server, "_parsed_runner_uses_builtin_question_tool", lambda runner, parsed: True
    )
    monkeypatch.setattr(
        runner_io_module, "_terminate_fix_process", _failfast, raising=False
    )
    monkeypatch.setattr(
        runner_io_module,
        "_parsed_runner_uses_builtin_question_tool",
        _failfast,
        raising=False,
    )

    await server._consume_fix_stream(
        job=job,
        step=step,
        runner="opencode",
        process=process,
        stream_name="stdout",
        stream=cast(asyncio.StreamReader, reader),
        sink=sink,
    )

    assert terminated == [process]
    assert len(captured_logs) == 1


@pytest.mark.anyio
async def test_run_fix_iteration_command_uses_live_consume_fix_stream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner_io_module = _load_runner_io_module_if_wired()
    if runner_io_module is None:
        return

    job = FixJob(
        model="openai/gpt-5.3-codex", branch_id="branch-main", branch_name="main"
    )
    step = FixJobStep(index=1, annotation_id="ann-1")
    process_map: dict[str, asyncio.subprocess.Process] = {}
    captured_calls: list[dict[str, object]] = []

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = object()
            self.stderr = object()
            self.returncode = 7

        async def wait(self) -> int:
            return self.returncode

    process = FakeProcess()
    spawned: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def fake_create_subprocess_exec(*command, **kwargs):
        spawned.append((command, kwargs))
        return process

    async def fake_consume_fix_stream(**kwargs) -> None:
        captured_calls.append(kwargs)
        kwargs["sink"].append(f"{kwargs['stream_name']}-chunk")

    def _failfast(*args, **kwargs):
        raise AssertionError("runner_io module should resolve helpers through server")

    monkeypatch.setattr(
        server.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )
    monkeypatch.setattr(server, "_consume_fix_stream", fake_consume_fix_stream)
    monkeypatch.setattr(
        server, "_subprocess_env", lambda overrides=None: overrides or {}
    )
    monkeypatch.setattr(server, "_hidden_window_kwargs", lambda: {})
    monkeypatch.setattr(server, "_runtime_fix_job_processes_map", lambda: process_map)
    monkeypatch.setattr(
        runner_io_module, "_consume_fix_stream", _failfast, raising=False
    )

    raw_stdout, raw_stderr = await server._run_fix_iteration_command(
        job=job,
        step=step,
        command=["runner", "fix"],
        cwd=tmp_path,
        env_overrides={"X": "Y"},
    )

    assert raw_stdout == "stdout-chunk"
    assert raw_stderr == "stderr-chunk"
    assert step.command == ["runner", "fix"]
    assert step.exit_code == 7
    assert step.stdout == "stdout-chunk"
    assert step.stderr == "stderr-chunk"
    assert process_map == {}
    assert [call["stream_name"] for call in captured_calls] == ["stdout", "stderr"]
    assert spawned[0][0] == ("runner", "fix")
    assert spawned[0][1]["cwd"] == str(tmp_path.resolve())
    assert spawned[0][1]["env"] == {"X": "Y"}


def test_extract_runner_session_id_from_output_uses_live_server_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_io_module = _load_runner_io_module_if_wired()
    if runner_io_module is None:
        return

    calls: list[tuple[str, object]] = []

    def fake_parse_json_event_line(line: str) -> dict[str, object] | None:
        calls.append(("parse", line))
        if "session" not in line:
            return None
        return {"line": line}

    def fake_extract_runner_session_id_from_event(
        runner: str, parsed: dict[str, object]
    ) -> str | None:
        calls.append(("extract", (runner, parsed["line"])))
        return "patched-session"

    def _failfast(*args, **kwargs):
        raise AssertionError("runner_io module should resolve helpers through server")

    monkeypatch.setattr(server, "_parse_json_event_line", fake_parse_json_event_line)
    monkeypatch.setattr(
        server,
        "_extract_runner_session_id_from_event",
        fake_extract_runner_session_id_from_event,
    )
    monkeypatch.setattr(
        runner_io_module, "_parse_json_event_line", _failfast, raising=False
    )
    monkeypatch.setattr(
        runner_io_module,
        "_extract_runner_session_id_from_event",
        _failfast,
        raising=False,
    )

    result = server._extract_runner_session_id_from_output(
        "opencode",
        'noise\n{"session":"abc"}\n',
    )

    assert result == "patched-session"
    assert calls == [
        ("parse", "noise"),
        ("parse", '{"session":"abc"}'),
        ("extract", ("opencode", '{"session":"abc"}')),
    ]
