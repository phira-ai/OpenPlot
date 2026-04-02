import ast
import importlib
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence, TypeAlias, cast

import pytest

import openplot.server as server
from openplot.models import FixJob, FixJobStatus, FixJobStep, PlotSession
from openplot.services.runtime import build_test_runtime


EXTRACTED_FIX_EXECUTION_HELPERS = (
    "_is_terminal_fix_job_status",
    "_build_opencode_plot_fix_command",
    "_build_codex_plot_fix_prompt",
    "_build_codex_plot_fix_command",
    "_build_claude_plot_fix_command",
    "_broadcast_fix_job",
    "_cancel_fix_job_execution",
    "_reconcile_active_fix_job_state",
    "_broadcast_fix_job_log",
    "_session_for_fix_job",
    "_workspace_dir_for_fix_job",
    "_runtime_dir_for_fix_job",
    "_prepare_fix_runner_workspace",
    "_fix_runner_env_overrides",
    "_fix_job_session_key",
    "_run_opencode_fix_iteration",
    "_run_codex_fix_iteration",
    "_run_claude_fix_iteration",
    "_fix_retry_context",
    "_run_fix_job_loop",
)

FunctionNode: TypeAlias = ast.FunctionDef | ast.AsyncFunctionDef


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


def _fix_execution_path() -> Path:
    return _server_path().with_name("server_fix_execution.py")


def _server_uses_extracted_fix_execution(module: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == "_server_fix_execution"
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
        "server_fix_execution.py must not cache patchable server helpers at module import time"
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
    for helper_name in EXTRACTED_FIX_EXECUTION_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"

    assert len(functions["_run_fix_job_loop"].body) > 1
    assert len(functions["_fix_runner_env_overrides"].body) > 1


def _load_fix_execution_module_if_wired() -> Any | None:
    server_module, functions = _read_module_ast(_server_path())
    if not _server_uses_extracted_fix_execution(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _fix_execution_path().exists(), (
            "server_fix_execution.py exists before server.py wires the fix-execution seam"
        )
        return None
    assert _fix_execution_path().exists(), (
        "server.py references _server_fix_execution but server_fix_execution.py is missing"
    )
    return importlib.import_module("openplot.server_fix_execution")


def test_patchable_server_helper_guard_catches_fix_execution_aliases() -> None:
    server_alias_tree = ast.parse("cached = server._run_fix_iteration_command")
    assert _contains_patchable_server_helper_reference(
        server_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    server_module_alias_tree = ast.parse("cached = server_module._broadcast_fix_job")
    assert _contains_patchable_server_helper_reference(
        server_module_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    openplot_alias_tree = ast.parse(
        "cached = openplot.server._extract_runner_reported_error"
    )
    assert _contains_patchable_server_helper_reference(
        openplot_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases={"openplot"},
    )

    imported_server_alias_tree = ast.parse(
        "import openplot.server as server_alias\n"
        "cached = server_alias._run_fix_iteration_command"
    )
    assert _contains_patchable_server_helper_reference(
        imported_server_alias_tree,
        server_aliases={"server", "server_module", "server_alias"},
        openplot_aliases=set(),
    )

    imported_from_server_alias_tree = ast.parse(
        "from openplot import server as server_alias\n"
        "cached = server_alias._broadcast_fix_job"
    )
    assert _contains_patchable_server_helper_reference(
        imported_from_server_alias_tree,
        server_aliases={"server", "server_module", "server_alias"},
        openplot_aliases=set(),
    )


def test_fix_execution_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> (
    None
):
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and '_server_fix_execution' in bound_helpers:
        assert set(EXTRACTED_FIX_EXECUTION_HELPERS) <= set(bound_helpers['_server_fix_execution'])
        for helper_name in EXTRACTED_FIX_EXECUTION_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_module, functions = _read_module_ast(_server_path())

    if not _server_uses_extracted_fix_execution(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _fix_execution_path().exists()
        return

    _, extracted_functions = _read_module_ast(_fix_execution_path())

    for helper_name in EXTRACTED_FIX_EXECUTION_HELPERS:
        function = functions[helper_name]
        extracted_function = extracted_functions.get(helper_name)
        assert extracted_function is not None, (
            f"Missing extracted helper for {helper_name}"
        )
        assert _signature_shape(function) == _signature_shape(
            extracted_function, drop_leading_server_module=True
        )
        assert len(function.body) == 1, (
            f"{helper_name} should stay a one-statement wrapper"
        )

        statement = function.body[0]
        if _returns_none(extracted_function):
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
        assert call.func.value.id == "_server_fix_execution"
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


def test_fix_execution_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    if _load_fix_execution_module_if_wired() is None:
        return

    module, _ = _read_module_ast(_fix_execution_path())
    server_aliases = {"server", "server_module"}
    openplot_aliases: set[str] = set()

    for node in module.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openplot":
                    openplot_aliases.add(alias.asname or alias.name)
                if alias.name == "openplot.server":
                    server_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "openplot":
                for alias in node.names:
                    if alias.name == "openplot":
                        openplot_aliases.add(alias.asname or alias.name)
                    if alias.name == "server":
                        server_aliases.add(alias.asname or alias.name)

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


def test_fix_execution_module_exists_and_exports_helper_inventory() -> None:
    fix_execution_path = _fix_execution_path()
    assert fix_execution_path.exists(), "Task 2 should create server_fix_execution.py"

    fix_execution_module = importlib.import_module("openplot.server_fix_execution")
    for helper_name in EXTRACTED_FIX_EXECUTION_HELPERS:
        assert hasattr(fix_execution_module, helper_name), (
            f"Missing extracted helper {helper_name}"
        )


@pytest.mark.anyio
async def test_run_opencode_fix_iteration_uses_live_server_runner_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fix_execution_module = _load_fix_execution_module_if_wired()
    if fix_execution_module is None:
        return

    workspace_dir = (tmp_path / "workspace").resolve()
    runtime_dir = (tmp_path / "runtime").resolve()
    workspace_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)

    session = PlotSession(id="session-opencode")
    job = FixJob(
        runner="opencode",
        model="openai/gpt-5.3-codex",
        branch_id="branch-main",
        branch_name="main",
        session_id=session.id,
        workspace_dir=str(runtime_dir),
    )
    step = FixJobStep(index=1, annotation_id="ann-1")
    captured: dict[str, object] = {}

    async def fake_run_fix_iteration_command(**kwargs):
        captured.update(kwargs)
        step.exit_code = 0
        return ("done\n", "")

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "fix_execution module should resolve _run_fix_iteration_command through server"
        )

    monkeypatch.setattr(server, "_session_for_fix_job", lambda _job: session)
    monkeypatch.setattr(
        server, "_workspace_dir_for_fix_job", lambda _job, _session: workspace_dir
    )
    monkeypatch.setattr(
        server, "_runtime_dir_for_fix_job", lambda _job, _session: runtime_dir
    )
    monkeypatch.setattr(server, "_fix_runner_env_overrides", lambda _job, _session: {})
    monkeypatch.setattr(
        server, "_runner_session_id_for_session", lambda _session, _runner: None
    )
    monkeypatch.setattr(
        server,
        "_build_opencode_plot_fix_command",
        lambda **kwargs: ["opencode", "run", str(kwargs["workspace_dir"]), "prompt"],
    )
    monkeypatch.setattr(
        server, "_run_fix_iteration_command", fake_run_fix_iteration_command
    )
    monkeypatch.setattr(
        server,
        "_runner_output_used_builtin_question_tool",
        lambda _runner, _stdout: False,
    )
    monkeypatch.setattr(
        server, "_extract_runner_session_id_from_output", lambda _runner, _stdout: None
    )
    monkeypatch.setattr(
        fix_execution_module,
        "_run_fix_iteration_command",
        _failfast,
        raising=False,
    )

    await server._run_opencode_fix_iteration(job, step)

    assert captured["cwd"] == runtime_dir
    assert captured["command"] == ["opencode", "run", str(workspace_dir), "prompt"]
    assert captured["display_command"] == [
        "opencode",
        "run",
        str(workspace_dir),
        "<plot-fix prompt>",
    ]


@pytest.mark.anyio
async def test_run_claude_fix_iteration_uses_live_server_error_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fix_execution_module = _load_fix_execution_module_if_wired()
    if fix_execution_module is None:
        return

    workspace_dir = tmp_path.resolve()
    session = PlotSession(id="session-claude")
    job = FixJob(
        runner="claude",
        model="claude-sonnet-4-6",
        variant="high",
        branch_id="branch-main",
        branch_name="main",
        session_id=session.id,
        workspace_dir=str(workspace_dir),
    )
    step = FixJobStep(index=1, annotation_id="ann-2")
    session_updates: list[tuple[str, str]] = []

    async def fake_run_fix_iteration_command(**kwargs):
        _ = kwargs
        step.exit_code = 0
        return ("stdout\n", "stderr\n")

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "fix_execution module should resolve error/session helpers through server"
        )

    monkeypatch.setattr(server, "_session_for_fix_job", lambda _job: session)
    monkeypatch.setattr(
        server, "_workspace_dir_for_fix_job", lambda _job, _session: workspace_dir
    )
    monkeypatch.setattr(server, "_fix_runner_env_overrides", lambda _job, _session: {})
    monkeypatch.setattr(
        server, "_runner_session_id_for_session", lambda _session, _runner: None
    )
    monkeypatch.setattr(
        server,
        "_build_claude_plot_fix_command",
        lambda **kwargs: ["claude", "-p", f"{kwargs['model']} prompt"],
    )
    monkeypatch.setattr(
        server, "_run_fix_iteration_command", fake_run_fix_iteration_command
    )
    monkeypatch.setattr(
        server,
        "_runner_output_used_builtin_question_tool",
        lambda _runner, _stdout: False,
    )
    monkeypatch.setattr(
        server,
        "_extract_runner_reported_error",
        lambda _runner, stdout_text, stderr_text: (
            "reported-from-server"
            if stdout_text == "stdout\n" and stderr_text == "stderr\n"
            else None
        ),
    )
    monkeypatch.setattr(
        server,
        "_extract_runner_session_id_from_output",
        lambda _runner, _stdout: "claude-session-123",
    )
    monkeypatch.setattr(
        server,
        "_set_runner_session_id_for_session",
        lambda _session, *, runner, session_id: session_updates.append(
            (runner, session_id)
        ),
    )
    monkeypatch.setattr(
        fix_execution_module,
        "_extract_runner_reported_error",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        fix_execution_module,
        "_extract_runner_session_id_from_output",
        _failfast,
        raising=False,
    )

    await server._run_claude_fix_iteration(job, step)

    assert step.exit_code == 1
    assert step.stderr == "reported-from-server"
    assert session_updates == [("claude", "claude-session-123")]


def test_fix_runner_env_overrides_uses_live_server_runtime_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fix_execution_module = _load_fix_execution_module_if_wired()
    if fix_execution_module is None:
        return

    runtime_dir = (tmp_path / "runtime").resolve()
    shim_bin = (runtime_dir / "bin").resolve()
    shim_bin.mkdir(parents=True)

    session = PlotSession(id="session-env")
    job = FixJob(
        runner="codex",
        model="openai/gpt-5.3-codex",
        branch_id="branch-main",
        branch_name="main",
        session_id=session.id,
        workspace_dir=str(runtime_dir),
    )

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "fix_execution module should resolve runtime env helpers through server"
        )

    monkeypatch.setattr(
        server, "_runtime_dir_for_fix_job", lambda _job, _session: runtime_dir
    )
    monkeypatch.setattr(server, "_write_fix_runner_shims", lambda path: shim_bin)
    monkeypatch.setattr(server, "_command_search_path", lambda: "system-path")
    monkeypatch.setattr(
        server, "_backend_url_from_port_file", lambda: "http://127.0.0.1:4040"
    )
    monkeypatch.setattr(server, "_is_openplot_app_launcher_path", lambda _path: False)
    monkeypatch.setattr(
        fix_execution_module,
        "_write_fix_runner_shims",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        fix_execution_module,
        "_backend_url_from_port_file",
        _failfast,
        raising=False,
    )

    overrides = server._fix_runner_env_overrides(job, session)

    assert overrides["OPENPLOT_SESSION_ID"] == session.id
    assert overrides["PATH"] == os.pathsep.join([str(shim_bin), "system-path"])
    assert overrides["OPENPLOT_SERVER_URL"] == "http://127.0.0.1:4040"


def test_fix_runner_env_overrides_uses_live_server_config_merge_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fix_execution_module = _load_fix_execution_module_if_wired()
    if fix_execution_module is None:
        return

    runtime_dir = (tmp_path / "runtime-config-merge").resolve()
    shim_bin = (runtime_dir / "bin").resolve()
    shim_bin.mkdir(parents=True)

    session = PlotSession(id="session-config-merge")
    job = FixJob(
        runner="opencode",
        model="openai/gpt-5.3-codex",
        branch_id="branch-main",
        branch_name="main",
        session_id=session.id,
        workspace_dir=str(runtime_dir),
    )
    merge_calls: list[tuple[str | None, str]] = []

    def fake_merge(base_content: str | None, override_content: str) -> str:
        merge_calls.append((base_content, override_content))
        return "merged-from-server"

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "fix_execution module should resolve _merged_opencode_config_content through server"
        )

    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"existing":true}')
    monkeypatch.setattr(
        server, "_runtime_dir_for_fix_job", lambda _job, _session: runtime_dir
    )
    monkeypatch.setattr(server, "_write_fix_runner_shims", lambda path: shim_bin)
    monkeypatch.setattr(server, "_command_search_path", lambda: "system-path")
    monkeypatch.setattr(server, "_backend_url_from_port_file", lambda: None)
    monkeypatch.setattr(server, "_is_openplot_app_launcher_path", lambda _path: False)
    monkeypatch.setattr(
        server, "_opencode_fix_config_content", lambda: '{"override":true}'
    )
    monkeypatch.setattr(server, "_merged_opencode_config_content", fake_merge)
    monkeypatch.setattr(
        fix_execution_module,
        "_merged_opencode_config_content",
        _failfast,
        raising=False,
    )

    overrides = server._fix_runner_env_overrides(job, session)

    assert merge_calls == [('{"existing":true}', '{"override":true}')]
    assert overrides["OPENCODE_CONFIG_CONTENT"] == "merged-from-server"


@pytest.mark.anyio
async def test_run_fix_job_loop_uses_live_server_broadcast_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fix_execution_module = _load_fix_execution_module_if_wired()
    if fix_execution_module is None:
        return

    runtime = build_test_runtime(store_root=tmp_path / "isolated-state")
    job = FixJob(
        model="openai/gpt-5.3-codex",
        branch_id="branch-main",
        branch_name="main",
        session_id="session-loop",
    )
    runtime.store.fix_jobs[job.id] = job
    runtime.store.active_fix_job_ids_by_session[job.session_id] = job.id

    session = SimpleNamespace(
        id=job.session_id,
        active_branch_id=job.branch_id,
        checked_out_version_id="version-1",
    )
    branch = SimpleNamespace(head_version_id="version-1")
    broadcast_statuses: list[FixJobStatus] = []

    async def fake_broadcast_fix_job(current_job: FixJob) -> None:
        broadcast_statuses.append(current_job.status)

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "fix_execution module should resolve _broadcast_fix_job through server"
        )

    monkeypatch.setattr(server, "_broadcast_fix_job", fake_broadcast_fix_job)
    monkeypatch.setattr(server, "_session_for_fix_job", lambda _job: cast(Any, session))
    monkeypatch.setattr(server, "_get_branch", lambda _session, _branch_id: branch)
    monkeypatch.setattr(server, "pending_annotations_for_context", lambda _session: [])
    monkeypatch.setattr(server, "_now_iso", lambda: "2026-03-28T00:00:00+00:00")
    monkeypatch.setattr(
        fix_execution_module,
        "_broadcast_fix_job",
        _failfast,
        raising=False,
    )

    await server._run_fix_job_loop(job.id, runtime=runtime)

    assert broadcast_statuses == [FixJobStatus.running, FixJobStatus.completed]
    assert runtime.store.active_fix_job_ids_by_session == {}
