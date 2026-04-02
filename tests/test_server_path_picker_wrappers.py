import ast
import importlib
from pathlib import Path
from typing import Any, Sequence, TypeAlias

import pytest

import openplot.server as server


EXTRACTED_PATH_PICKER_HELPERS = (
    "_resolved_home_dir",
    "_picker_default_base_dir",
    "_expanduser_if_needed",
    "_resolve_local_picker_path",
    "_picker_parent_and_fragment",
    "_display_picker_path",
    "_is_fuzzy_subsequence",
    "_path_suggestion_score",
    "_list_path_suggestions",
    "_resolve_selected_file_path",
)

PATCHABLE_SERVER_HELPERS = set(EXTRACTED_PATH_PICKER_HELPERS)

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


def _path_picker_path() -> Path:
    return _server_path().with_name("server_path_picker.py")


def _server_uses_extracted_path_picker(module: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == "_server_path_picker"
        for node in ast.walk(module)
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
        if posonlyargs:
            if posonlyargs[0] != "server_module":
                raise AssertionError("Extracted helper must accept server_module first")
            posonlyargs = posonlyargs[1:]
        else:
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
        "server_path_picker.py must not cache patchable server helpers at module import time"
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
    for helper_name in EXTRACTED_PATH_PICKER_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"


def _load_path_picker_module_if_wired() -> Any | None:
    server_module, functions = _read_module_ast(_server_path())
    if not _server_uses_extracted_path_picker(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _path_picker_path().exists(), (
            "server_path_picker.py exists before server.py wires the path-picker seam"
        )
        return None
    assert _path_picker_path().exists(), (
        "server.py references _server_path_picker but server_path_picker.py is missing"
    )
    return importlib.import_module("openplot.server_path_picker")


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


def _call_targets_extracted_helper(call: ast.Call, helper_name: str) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "_server_path_picker"
        and call.func.attr == helper_name
    )


def _iter_wrapper_calls(function: FunctionNode) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and _call_targets_extracted_helper(node, function.name)
    ]


def _assert_wrapper_forwards_parameters(function: FunctionNode, call: ast.Call) -> None:
    positional_parameter_names = _positional_parameter_names(function)
    assert len(call.args) == len(positional_parameter_names) + 1

    server_module_arg = call.args[0]
    assert isinstance(server_module_arg, ast.Subscript)
    assert isinstance(server_module_arg.value, ast.Attribute)
    assert isinstance(server_module_arg.value.value, ast.Name)
    assert server_module_arg.value.value.id == "sys"
    assert server_module_arg.value.attr == "modules"
    assert isinstance(server_module_arg.slice, ast.Name)
    assert server_module_arg.slice.id == "__name__"

    for argument, parameter_name in zip(
        call.args[1:], positional_parameter_names, strict=True
    ):
        assert isinstance(argument, ast.Name)
        assert argument.id == parameter_name

    kwonly_keywords = [keyword for keyword in call.keywords if keyword.arg is not None]
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


def _wrapper_body_statements(function: FunctionNode) -> list[ast.stmt]:
    statements = list(function.body)
    if statements and isinstance(statements[0], ast.Expr):
        value = statements[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            statements = statements[1:]
    return statements


def test_patchable_server_helper_guard_catches_path_picker_aliases() -> None:
    server_alias_tree = ast.parse("cached = server._resolve_local_picker_path")
    assert _contains_patchable_server_helper_reference(
        server_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    server_module_alias_tree = ast.parse(
        "cached = server_module._list_path_suggestions"
    )
    assert _contains_patchable_server_helper_reference(
        server_module_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    openplot_alias_tree = ast.parse(
        "cached = openplot.server._resolve_selected_file_path"
    )
    assert _contains_patchable_server_helper_reference(
        openplot_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases={"openplot"},
    )


def test_patchable_server_helper_guard_catches_nested_aliases() -> None:
    try_body_alias_tree = ast.parse(
        "try:\n"
        "    cached = getattr(server_module, '_display_picker_path')\n"
        "except Exception:\n"
        "    pass\n"
    )

    with pytest.raises(AssertionError):
        _assert_no_patchable_server_helper_references_in_statement(
            try_body_alias_tree.body[0],
            server_aliases={"server", "server_module"},
            openplot_aliases=set(),
        )


def test_path_picker_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> None:
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and '_server_path_picker' in bound_helpers:
        assert set(EXTRACTED_PATH_PICKER_HELPERS) <= set(bound_helpers['_server_path_picker'])
        for helper_name in EXTRACTED_PATH_PICKER_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_module, functions = _read_module_ast(_server_path())

    if not _server_uses_extracted_path_picker(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _path_picker_path().exists()
        return

    _, extracted_functions = _read_module_ast(_path_picker_path())

    for helper_name in EXTRACTED_PATH_PICKER_HELPERS:
        function = functions[helper_name]
        extracted_function = extracted_functions.get(helper_name)
        assert extracted_function is not None, (
            f"Missing extracted helper for {helper_name}"
        )
        assert _signature_shape(function) == _signature_shape(
            extracted_function, drop_leading_server_module=True
        )
        matching_calls = _iter_wrapper_calls(function)
        assert matching_calls, (
            f"{helper_name} should delegate to _server_path_picker.{helper_name}"
        )
        assert len(matching_calls) == 1, (
            f"{helper_name} should delegate through a single extracted-helper call"
        )
        wrapper_body = _wrapper_body_statements(function)
        assert len(wrapper_body) == 1, (
            f"{helper_name} should keep exactly one delegating statement"
        )
        statement = wrapper_body[0]
        assert isinstance(statement, (ast.Return, ast.Expr)), (
            f"{helper_name} should delegate with a return or expression statement"
        )
        assert statement.value is matching_calls[0]
        _assert_wrapper_forwards_parameters(function, matching_calls[0])


def test_path_picker_seam_is_wired_after_extraction() -> None:
    server_module, _ = _read_module_ast(_server_path())

    assert _server_uses_extracted_path_picker(server_module), (
        "Task 2 should wire server.py through _server_path_picker"
    )
    assert _path_picker_path().exists(), "Task 2 should create server_path_picker.py"


def test_path_picker_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    if _load_path_picker_module_if_wired() is None:
        return

    module, _ = _read_module_ast(_path_picker_path())
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
                "server_path_picker.py must not import private helpers directly from openplot.server"
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


def test_resolve_local_picker_path_uses_live_server_expanduser_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path_picker_module = _load_path_picker_module_if_wired()
    if path_picker_module is None:
        return

    patched = (tmp_path / "patched-home" / "dataset.csv").resolve()
    calls: list[Path] = []

    def fake_expanduser_if_needed(path: Path) -> Path:
        calls.append(path)
        return patched

    monkeypatch.setattr(server, "_expanduser_if_needed", fake_expanduser_if_needed)
    _patch_fail_fast_if_present(
        monkeypatch,
        path_picker_module,
        "_expanduser_if_needed",
    )

    resolved = server._resolve_local_picker_path("~/dataset.csv", base_dir=tmp_path)

    assert resolved == patched
    assert calls == [Path("~/dataset.csv")]


def test_list_path_suggestions_uses_live_server_display_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path_picker_module = _load_path_picker_module_if_wired()
    if path_picker_module is None:
        return

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "alpha.csv").write_text("x,y\n1,2\n")
    (workspace / "nested").mkdir()
    calls: list[tuple[Path, bool]] = []

    def fake_display_picker_path(path: Path, *, as_dir: bool) -> str:
        calls.append((path, as_dir))
        suffix = "/" if as_dir else ""
        return f"patched::{path.name}{suffix}"

    monkeypatch.setattr(server, "_display_picker_path", fake_display_picker_path)
    _patch_fail_fast_if_present(
        monkeypatch,
        path_picker_module,
        "_display_picker_path",
    )

    parent_dir, suggestions = server._list_path_suggestions(
        query="",
        selection_type="data",
        base_dir=workspace,
    )

    assert parent_dir == workspace.resolve()
    assert suggestions
    assert {item["display_path"] for item in suggestions} == {
        "patched::alpha.csv",
        "patched::nested/",
    }
    assert sorted((path.name, as_dir) for path, as_dir in calls) == [
        ("alpha.csv", False),
        ("nested", True),
    ]


def test_resolve_selected_file_path_uses_live_server_path_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path_picker_module = _load_path_picker_module_if_wired()
    if path_picker_module is None:
        return

    selected = tmp_path / "patched.csv"
    selected.write_text("x,y\n1,2\n")
    calls: list[tuple[str, Path | None]] = []

    def fake_resolve_local_picker_path(
        raw_path: str,
        *,
        base_dir: Path | None = None,
    ) -> Path:
        calls.append((raw_path, base_dir))
        return selected

    monkeypatch.setattr(
        server,
        "_resolve_local_picker_path",
        fake_resolve_local_picker_path,
    )
    _patch_fail_fast_if_present(
        monkeypatch,
        path_picker_module,
        "_resolve_local_picker_path",
    )

    resolved = server._resolve_selected_file_path(
        raw_path="  ignored.csv  ",
        selection_type="data",
        base_dir=tmp_path,
    )

    assert resolved == selected.resolve()
    assert calls == [("ignored.csv", tmp_path)]
