import ast
import json
from pathlib import Path
from typing import Any, Sequence, TypeAlias, cast

import pytest

import openplot.server as server
import openplot.server_fix_execution as server_fix_execution
import openplot.server_runners as server_runners
from openplot.models import PlotSession


RUNNER_HELPERS = (
    "_install_codex_release",
    "_perform_runner_install",
    "_run_runner_install_job",
    "_parse_opencode_verbose_models",
    "_parse_codex_models_cache",
    "_resolve_runner_default_model_and_variant",
    "_merge_opencode_config_objects",
    "_merged_opencode_config_content",
)

FIX_EXECUTION_HELPERS = ("_prepare_fix_runner_workspace",)

HELPER_TO_MODULE_ALIAS = {
    **{helper_name: "_server_runners" for helper_name in RUNNER_HELPERS},
    **{helper_name: "_server_fix_execution" for helper_name in FIX_EXECUTION_HELPERS},
}

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


def _module_path(module: Any) -> Path:
    return Path(module.__file__).resolve()


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


def _unwrap_wrapper_call(function: FunctionNode) -> ast.Call | None:
    if len(function.body) != 1:
        return None

    statement = function.body[0]
    if isinstance(statement, ast.Return):
        if statement.value is None:
            return None
        value: ast.expr = statement.value
    elif isinstance(statement, ast.Expr):
        value = statement.value
    else:
        return None

    if isinstance(value, ast.Await):
        value = value.value
    if not isinstance(value, ast.Call):
        return None
    return value


def _is_expected_wrapper(function: FunctionNode, helper_name: str) -> bool:
    call = _unwrap_wrapper_call(function)
    if call is None:
        return False
    if not isinstance(call.func, ast.Attribute):
        return False
    if not isinstance(call.func.value, ast.Name):
        return False
    if call.func.value.id != HELPER_TO_MODULE_ALIAS[helper_name]:
        return False
    if call.func.attr != helper_name:
        return False
    if not call.args:
        return False
    return _server_module_reference(call.args[0])


def _assert_pre_extraction_contract(
    helper_name: str,
    functions: dict[str, FunctionNode],
) -> None:
    function = functions.get(helper_name)
    assert function is not None, f"Missing server helper {helper_name}"
    assert not _is_expected_wrapper(function, helper_name), (
        f"Pre-extraction contract expects {helper_name} to still be implemented in server.py"
    )
    assert len(function.body) > 1, (
        f"Pre-extraction contract expects {helper_name} to remain non-wrapper code"
    )


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
    ), "Extracted modules must not cache patchable server helpers at module import time"


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


def _assert_module_has_no_top_level_cached_server_helpers(module: Any) -> None:
    tree, _ = _read_module_ast(_module_path(module))
    server_aliases = {"server", "server_module"}
    openplot_aliases: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openplot":
                    openplot_aliases.add(alias.asname or alias.name)
                if alias.name == "openplot.server":
                    server_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "openplot":
            for alias in node.names:
                if alias.name == "openplot":
                    openplot_aliases.add(alias.asname or alias.name)
                if alias.name == "server":
                    server_aliases.add(alias.asname or alias.name)

    for node in tree.body:
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
            function = node
            for default in function.args.defaults:
                _assert_no_patchable_server_helper_reference(
                    default,
                    server_aliases=server_aliases,
                    openplot_aliases=openplot_aliases,
                )
            for default in function.args.kw_defaults:
                _assert_no_patchable_server_helper_reference(
                    default,
                    server_aliases=server_aliases,
                    openplot_aliases=openplot_aliases,
                )
            for decorator in function.decorator_list:
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


def _patch_fail_fast_if_present(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    helper_name: str,
) -> None:
    def _fail_fast(*args: object, **kwargs: object) -> object:
        raise AssertionError(
            f"cached extracted helper should not be used: {helper_name}"
        )

    monkeypatch.setattr(module, helper_name, _fail_fast, raising=False)


def test_patchable_server_helper_guard_catches_residual_runner_aliases() -> None:
    server_alias_tree = ast.parse("cached = server._perform_runner_install")
    assert _contains_patchable_server_helper_reference(
        server_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    server_module_alias_tree = ast.parse(
        "cached = getattr(server_module, '_workspace_for_session')"
    )
    assert _contains_patchable_server_helper_reference(
        server_module_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    openplot_alias_tree = ast.parse(
        "cached = openplot.server._merged_opencode_config_content"
    )
    assert _contains_patchable_server_helper_reference(
        openplot_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases={"openplot"},
    )


def test_residual_runner_helper_wrappers_are_pre_extraction_aware_and_thin_when_extracted() -> (
    None
):
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and "_server_runners" in bound_helpers:
        for helper_name in RUNNER_HELPERS:
            assert helper_name in bound_helpers["_server_runners"]
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        for helper_name in FIX_EXECUTION_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    _, server_functions = _read_module_ast(_server_path())
    _, runner_functions = _read_module_ast(_module_path(server_runners))
    _, fix_execution_functions = _read_module_ast(_module_path(server_fix_execution))
    extracted_functions_by_alias = {
        "_server_runners": runner_functions,
        "_server_fix_execution": fix_execution_functions,
    }

    for helper_name in (*RUNNER_HELPERS, *FIX_EXECUTION_HELPERS):
        function = server_functions.get(helper_name)
        assert function is not None, f"Missing server helper {helper_name}"

        if not _is_expected_wrapper(function, helper_name):
            _assert_pre_extraction_contract(helper_name, server_functions)
            continue

        extracted_function = extracted_functions_by_alias[
            HELPER_TO_MODULE_ALIAS[helper_name]
        ].get(helper_name)
        assert extracted_function is not None, (
            f"Missing extracted helper for {helper_name}"
        )
        assert _signature_shape(function) == _signature_shape(
            extracted_function, drop_leading_server_module=True
        )

        statement = function.body[0]
        if _returns_none(extracted_function):
            assert isinstance(statement, (ast.Expr, ast.Return))
        else:
            assert isinstance(statement, ast.Return)

        if isinstance(function, ast.AsyncFunctionDef):
            assert isinstance(statement.value, ast.Await), (
                f"{helper_name} should await the extracted async helper"
            )
        else:
            assert not isinstance(statement.value, ast.Await), (
                f"{helper_name} should not await a non-async extracted helper"
            )

        call = _unwrap_wrapper_call(function)
        assert call is not None
        assert isinstance(call.func, ast.Attribute)
        assert isinstance(call.func.value, ast.Name)
        assert call.func.value.id == HELPER_TO_MODULE_ALIAS[helper_name]
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


def test_extracted_runner_modules_avoid_top_level_cached_server_helpers() -> None:
    _assert_module_has_no_top_level_cached_server_helpers(server_runners)
    _assert_module_has_no_top_level_cached_server_helpers(server_fix_execution)


def test_run_runner_install_job_runtime_lookup_is_extraction_aware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and "_server_runners" in bound_helpers:
        assert "_run_runner_install_job" in bound_helpers["_server_runners"]
    else:
        _, server_functions = _read_module_ast(_server_path())
        function = server_functions.get("_run_runner_install_job")
        if function is None or not _is_expected_wrapper(
            function, "_run_runner_install_job"
        ):
            _assert_pre_extraction_contract("_run_runner_install_job", server_functions)
            return

    captured: dict[str, object] = {}
    update_calls: list[tuple[str, str]] = []
    job = {"id": "job-1", "runner": "codex"}

    def fake_update(job_id: str, **changes: object) -> dict[str, object] | None:
        state = changes.get("state")
        if isinstance(state, str):
            update_calls.append((job_id, state))
        return cast(dict[str, object], job)

    def fake_perform(runner: str, current_job: dict[str, object]) -> dict[str, object]:
        captured["runner"] = runner
        captured["job"] = current_job
        return {"executable_path": "/tmp/codex"}

    monkeypatch.setattr(server, "_update_runner_install_job", fake_update)
    monkeypatch.setattr(server, "_perform_runner_install", fake_perform)
    monkeypatch.setattr(
        server, "_resolve_runner_executable_path", lambda runner: f"/tmp/{runner}"
    )
    monkeypatch.setattr(server, "_runner_launch_probe", lambda runner: True)
    monkeypatch.setattr(
        server, "_append_runner_install_log", lambda job_id, message: None
    )
    monkeypatch.setattr(server, "_with_runtime", lambda runtime, callback: callback())
    _patch_fail_fast_if_present(monkeypatch, server_runners, "_perform_runner_install")

    server._run_runner_install_job("job-1", runtime=cast(Any, object()))

    assert captured == {"runner": "codex", "job": job}
    assert update_calls == [("job-1", "running"), ("job-1", "succeeded")]


def test_merged_opencode_config_content_runtime_lookup_is_extraction_aware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and "_server_runners" in bound_helpers:
        assert "_merged_opencode_config_content" in bound_helpers["_server_runners"]
    else:
        _, server_functions = _read_module_ast(_server_path())
        function = server_functions.get("_merged_opencode_config_content")
        if function is None or not _is_expected_wrapper(
            function, "_merged_opencode_config_content"
        ):
            _assert_pre_extraction_contract(
                "_merged_opencode_config_content", server_functions
            )
            return

    merge_calls: list[tuple[object, object]] = []

    def fake_merge(base: object, override: object) -> object:
        merge_calls.append((base, override))
        return {"merged": True}

    monkeypatch.setattr(server, "_merge_opencode_config_objects", fake_merge)
    _patch_fail_fast_if_present(
        monkeypatch, server_runners, "_merge_opencode_config_objects"
    )

    content = server._merged_opencode_config_content(
        '{"base": true}', '{"override": true}'
    )

    assert merge_calls == [({"base": True}, {"override": True})]
    assert json.loads(content) == {"merged": True}


def test_prepare_fix_runner_workspace_runtime_lookup_is_extraction_aware(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and "_server_fix_execution" in bound_helpers:
        assert "_prepare_fix_runner_workspace" in bound_helpers["_server_fix_execution"]
    else:
        _, server_functions = _read_module_ast(_server_path())
        function = server_functions.get("_prepare_fix_runner_workspace")
        if function is None or not _is_expected_wrapper(
            function,
            "_prepare_fix_runner_workspace",
        ):
            _assert_pre_extraction_contract(
                "_prepare_fix_runner_workspace", server_functions
            )
            return

    artifacts_root = (tmp_path / "artifacts").resolve()
    context_dir = (tmp_path / "context").resolve()
    context_dir.mkdir(parents=True)

    monkeypatch.setattr(
        server, "_session_artifacts_root", lambda session: artifacts_root
    )
    monkeypatch.setattr(server, "_workspace_for_session", lambda session: context_dir)
    _patch_fail_fast_if_present(
        monkeypatch, server_fix_execution, "_workspace_for_session"
    )

    workspace = server._prepare_fix_runner_workspace(
        PlotSession(id="session-1"), job_id="job-123"
    )

    assert workspace == (artifacts_root / "fix_runner" / "job-123").resolve()
    assert (workspace / "OPENPLOT_CONTEXT_DIR.txt").read_text(encoding="utf-8") == str(
        context_dir
    )
