import ast
import importlib
from pathlib import Path
from typing import Any, Sequence, TypeAlias

import pytest

import openplot.server as server
from openplot.models import PlotModeResolvedDataSource, PlotModeState


EXTRACTED_RESPONSE_UTIL_HELPERS = (
    "_append_active_resolved_source_context",
    "_append_profile_region_details",
    "_json_object_candidates",
    "_coerce_bool",
    "_suggest_plot_mode_question_options",
    "_extract_structured_plot_mode_result",
    "_extract_python_script_from_text",
    "_extract_plot_mode_script_result",
    "_as_record",
    "_as_string",
    "_as_non_empty_string",
    "_read_path",
    "_collect_text",
    "_join_collected_text",
    "_truncate_output",
    "_resolve_plot_response",
)

PATCHABLE_SERVER_HELPERS = {
    "_append_active_resolved_source_context",
    "_extract_plot_mode_script_result",
    "_resolve_plot_response",
    "_active_resolved_sources",
    "_extract_structured_plot_mode_result",
    "_extract_python_script_from_text",
    "_resolve_plot_mode_workspace",
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


def _response_utils_path() -> Path:
    return _server_path().with_name("server_response_utils.py")


def _server_uses_extracted_response_utils(module: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == "_server_response_utils"
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
            and child.attr in PATCHABLE_SERVER_HELPERS
            and isinstance(child.value, ast.Name)
            and child.value.id in server_aliases
        ):
            return True
        if (
            isinstance(child, ast.Attribute)
            and child.attr in PATCHABLE_SERVER_HELPERS
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
                and helper_name.value in PATCHABLE_SERVER_HELPERS
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
        "server_response_utils.py must not cache patchable server helpers at module import time"
    )


def _assert_no_patchable_server_helper_references_in_statement(
    node: ast.stmt,
    *,
    server_aliases: set[str],
    openplot_aliases: set[str],
) -> None:
    _assert_no_patchable_server_helper_reference(
        node,
        server_aliases=server_aliases,
        openplot_aliases=openplot_aliases,
    )


def _assert_pre_extraction_contract(functions: dict[str, FunctionNode]) -> None:
    for helper_name in EXTRACTED_RESPONSE_UTIL_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"

    for helper_name in (
        "_append_active_resolved_source_context",
        "_extract_plot_mode_script_result",
        "_resolve_plot_response",
    ):
        assert len(functions[helper_name].body) > 1, (
            f"Pre-extraction contract expects {helper_name} to still be implemented in server.py"
        )


def _load_response_utils_module_if_wired() -> Any | None:
    server_module, functions = _read_module_ast(_server_path())
    if not _server_uses_extracted_response_utils(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _response_utils_path().exists(), (
            "server_response_utils.py exists before server.py wires the response-utils seam"
        )
        return None
    assert _response_utils_path().exists(), (
        "server.py references _server_response_utils but server_response_utils.py is missing"
    )
    return importlib.import_module("openplot.server_response_utils")


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


def test_patchable_server_helper_guard_catches_response_utils_aliases() -> None:
    server_alias_tree = ast.parse("cached = server._resolve_plot_response")
    assert _contains_patchable_server_helper_reference(
        server_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    server_module_alias_tree = ast.parse(
        "cached = server_module._extract_plot_mode_script_result"
    )
    assert _contains_patchable_server_helper_reference(
        server_module_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    openplot_alias_tree = ast.parse(
        "cached = openplot.server._append_active_resolved_source_context"
    )
    assert _contains_patchable_server_helper_reference(
        openplot_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases={"openplot"},
    )


def test_patchable_server_helper_guard_catches_nested_aliases() -> None:
    try_body_alias_tree = ast.parse(
        "try:\n"
        "    cached = getattr(server_module, '_resolve_plot_response')\n"
        "except Exception:\n"
        "    pass\n"
    )

    with pytest.raises(AssertionError):
        _assert_no_patchable_server_helper_references_in_statement(
            try_body_alias_tree.body[0],
            server_aliases={"server", "server_module"},
            openplot_aliases=set(),
        )


def test_response_utils_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> (
    None
):
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and '_server_response_utils' in bound_helpers:
        assert set(EXTRACTED_RESPONSE_UTIL_HELPERS) <= set(bound_helpers['_server_response_utils'])
        for helper_name in EXTRACTED_RESPONSE_UTIL_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_module, functions = _read_module_ast(_server_path())

    if not _server_uses_extracted_response_utils(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _response_utils_path().exists()
        return

    _, extracted_functions = _read_module_ast(_response_utils_path())

    for helper_name in EXTRACTED_RESPONSE_UTIL_HELPERS:
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
        assert call.func.value.id == "_server_response_utils"
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


def test_response_utils_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    if _load_response_utils_module_if_wired() is None:
        return

    module, _ = _read_module_ast(_response_utils_path())
    server_aliases = {"server", "server_module"}
    openplot_aliases: set[str] = set()

    for node in module.body:
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
        elif isinstance(node, ast.ImportFrom) and node.module == "openplot.server":
            private_imports = [
                alias.name for alias in node.names if alias.name.startswith("_")
            ]
            assert not private_imports, (
                "server_response_utils.py must not import private helpers directly from openplot.server"
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


def test_resolve_plot_response_uses_live_server_plot_mode_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_utils_module = _load_response_utils_module_if_wired()
    if response_utils_module is None:
        return

    workspace = PlotModeState(
        workspace_dir="/tmp/workspace",
        current_plot="/tmp/from-patched-workspace.svg",
        plot_type="svg",
    )

    monkeypatch.setattr(server, "_resolve_plot_mode_workspace", lambda _id: workspace)
    _patch_fail_fast_if_present(
        monkeypatch, response_utils_module, "_resolve_plot_mode_workspace"
    )

    plot_path, plot_type = server._resolve_plot_response(
        session_id=None,
        version_id=None,
        plot_mode=True,
        workspace_id="workspace-1",
    )

    assert plot_path == Path("/tmp/from-patched-workspace.svg")
    assert plot_type == "svg"


def test_extract_plot_mode_script_result_uses_live_server_parsers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_utils_module = _load_response_utils_module_if_wired()
    if response_utils_module is None:
        return

    calls: list[tuple[str, str]] = []

    def _fake_extract_structured(text: str) -> tuple[str, str, bool | None] | None:
        calls.append(("structured", text))
        return None

    def _fake_extract_script(text: str) -> str | None:
        calls.append(("script", text))
        return "print('from patched parser')"

    monkeypatch.setattr(
        server, "_extract_structured_plot_mode_result", _fake_extract_structured
    )
    monkeypatch.setattr(
        server, "_extract_python_script_from_text", _fake_extract_script
    )
    _patch_fail_fast_if_present(
        monkeypatch, response_utils_module, "_extract_structured_plot_mode_result"
    )
    _patch_fail_fast_if_present(
        monkeypatch, response_utils_module, "_extract_python_script_from_text"
    )

    text = "Patched fallback summary\n```python\nprint('ignored by parser body')\n```"
    result = server._extract_plot_mode_script_result(text)

    assert result == (
        "Patched fallback summary",
        "print('from patched parser')",
        None,
    )
    assert calls == [("structured", text), ("script", text)]


def test_append_active_resolved_source_context_uses_live_server_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_utils_module = _load_response_utils_module_if_wired()
    if response_utils_module is None:
        return

    state = PlotModeState(workspace_dir="/tmp/workspace")
    source = PlotModeResolvedDataSource(
        id="source-1",
        kind="single_file",
        label="Patched source",
        summary="patched summary",
        columns=["alpha", "beta"],
        file_paths=["/tmp/data.csv"],
        integrity_notes=["looks good"],
    )
    lines: list[str] = []

    monkeypatch.setattr(server, "_active_resolved_sources", lambda _state: [source])
    _patch_fail_fast_if_present(
        monkeypatch, response_utils_module, "_active_resolved_sources"
    )

    server._append_active_resolved_source_context(lines, state, heading="Active source")

    assert lines == [
        "",
        "Active source",
        "- Label: Patched source",
        "- Kind: single_file",
        "- Summary: patched summary",
        "- Columns: alpha, beta",
        "- Files:",
        "  - /tmp/data.csv",
        "- Integrity notes:",
        "  - looks good",
    ]
