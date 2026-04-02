import ast
import importlib
import json
from pathlib import Path
from typing import Any, Sequence, TypeAlias

import pytest

import openplot.server as server


EXTRACTED_PYTHON_RUNTIME_HELPERS = (
    "_load_python_interpreter_preference",
    "_save_python_interpreter_preference",
    "_python_context_dir",
    "_probe_python_interpreter",
    "_validated_python_candidate",
    "_discover_python_interpreter_candidates",
    "_probe_python_packages",
    "_resolve_python_interpreter_state",
)

PATCHABLE_SERVER_HELPERS = {
    *EXTRACTED_PYTHON_RUNTIME_HELPERS,
    "_preferences_path",
    "_normalize_preference_value",
    "_load_preferences_data",
    "_resolve_session_file_path",
    "_workspace_for_session",
    "_data_root",
    "_state_root",
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


def _python_runtime_path() -> Path:
    return _server_path().with_name("server_python_runtime.py")


def _server_uses_extracted_python_runtime(module: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == "_server_python_runtime"
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
        "server_python_runtime.py must not cache patchable server helpers at module import time"
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
        else:
            for grandchild in ast.iter_child_nodes(child):
                if isinstance(grandchild, ast.expr):
                    _assert_no_patchable_server_helper_reference(
                        grandchild,
                        server_aliases=server_aliases,
                        openplot_aliases=openplot_aliases,
                    )
                elif isinstance(grandchild, ast.stmt):
                    _assert_no_patchable_server_helper_references_in_statement(
                        grandchild,
                        server_aliases=server_aliases,
                        openplot_aliases=openplot_aliases,
                    )


def _assert_pre_extraction_contract(functions: dict[str, FunctionNode]) -> None:
    for helper_name in EXTRACTED_PYTHON_RUNTIME_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"
        assert len(functions[helper_name].body) > 1, (
            f"Pre-extraction contract expects {helper_name} to still be implemented in server.py"
        )


def _load_python_runtime_module_if_wired() -> Any | None:
    server_module, functions = _read_module_ast(_server_path())
    if not _server_uses_extracted_python_runtime(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _python_runtime_path().exists(), (
            "server_python_runtime.py exists before server.py wires the python-runtime seam"
        )
        return None
    assert _python_runtime_path().exists(), (
        "server.py references _server_python_runtime but server_python_runtime.py is missing"
    )
    return importlib.import_module("openplot.server_python_runtime")


def test_patchable_server_helper_guard_catches_python_runtime_aliases() -> None:
    server_alias_tree = ast.parse("cached = server._load_preferences_data")
    assert _contains_patchable_server_helper_reference(
        server_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    server_module_alias_tree = ast.parse(
        "cached = getattr(server_module, '_probe_python_packages')"
    )
    assert _contains_patchable_server_helper_reference(
        server_module_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    openplot_alias_tree = ast.parse("cached = openplot.server._preferences_path")
    assert _contains_patchable_server_helper_reference(
        openplot_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases={"openplot"},
    )


def test_patchable_server_helper_guard_catches_try_body_aliases() -> None:
    try_body_alias_tree = ast.parse(
        "try:\n"
        "    cached = server._probe_python_interpreter\n"
        "except Exception:\n"
        "    pass\n"
    )

    with pytest.raises(AssertionError):
        _assert_no_patchable_server_helper_references_in_statement(
            try_body_alias_tree.body[0],
            server_aliases={"server", "server_module"},
            openplot_aliases=set(),
        )


def test_python_runtime_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> (
    None
):
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and '_server_python_runtime' in bound_helpers:
        assert set(EXTRACTED_PYTHON_RUNTIME_HELPERS) <= set(bound_helpers['_server_python_runtime'])
        for helper_name in EXTRACTED_PYTHON_RUNTIME_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_module, functions = _read_module_ast(_server_path())

    if not _server_uses_extracted_python_runtime(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _python_runtime_path().exists()
        return

    _, extracted_functions = _read_module_ast(_python_runtime_path())

    for helper_name in EXTRACTED_PYTHON_RUNTIME_HELPERS:
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
        assert call.func.value.id == "_server_python_runtime"
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


def test_python_runtime_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    if _load_python_runtime_module_if_wired() is None:
        return

    module, _ = _read_module_ast(_python_runtime_path())
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


def test_resolve_python_interpreter_state_uses_live_server_runtime_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    python_runtime_module = _load_python_runtime_module_if_wired()
    if python_runtime_module is None:
        return

    calls: list[tuple[str, object]] = []
    built_in_path = Path(server.sys.executable).resolve()

    def fake_python_context_dir(_session=None) -> Path:
        calls.append(("context", tmp_path))
        return tmp_path

    def fake_discover_python_interpreter_candidates(context_dir: Path):
        calls.append(("discover", context_dir))
        return [
            {
                "path": str(tmp_path / "venv/bin/python"),
                "source": "nearest-venv",
                "version": "3.12.0",
            }
        ]

    def fake_load_python_interpreter_preference() -> None:
        calls.append(("load", None))
        return None

    def fake_probe_python_packages(interpreter_path: Path):
        calls.append(("packages", interpreter_path))
        return ["patched_pkg"], None

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "python runtime module should resolve runtime helpers through server"
        )

    monkeypatch.setattr(server, "_python_context_dir", fake_python_context_dir)
    monkeypatch.setattr(
        server,
        "_discover_python_interpreter_candidates",
        fake_discover_python_interpreter_candidates,
    )
    monkeypatch.setattr(
        server,
        "_load_python_interpreter_preference",
        fake_load_python_interpreter_preference,
    )
    monkeypatch.setattr(server, "_probe_python_packages", fake_probe_python_packages)
    monkeypatch.setattr(server, "_data_root", lambda: tmp_path / "data-root")
    monkeypatch.setattr(server, "_state_root", lambda: tmp_path / "state-root")
    monkeypatch.setattr(
        python_runtime_module,
        "_discover_python_interpreter_candidates",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        python_runtime_module,
        "_load_python_interpreter_preference",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        python_runtime_module,
        "_probe_python_packages",
        _failfast,
        raising=False,
    )

    result = server._resolve_python_interpreter_state()

    assert result["mode"] == "builtin"
    assert result["configured_path"] is None
    assert result["default_path"] == str(built_in_path)
    assert result["resolved_path"] == str(built_in_path)
    assert result["default_available_packages"] == ["patched_pkg"]
    assert result["available_packages"] == ["patched_pkg"]
    assert result["context_dir"] == str(tmp_path)
    assert calls == [
        ("context", tmp_path),
        ("discover", tmp_path),
        ("load", None),
        ("packages", built_in_path),
    ]


def test_validated_python_candidate_uses_live_server_probe_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    python_runtime_module = _load_python_runtime_module_if_wired()
    if python_runtime_module is None:
        return

    candidate_path = tmp_path / "manual-python"
    candidate_path.write_text("#!/bin/sh\nexit 0\n")
    candidate_path.chmod(0o755)
    calls: list[Path] = []

    def fake_probe_python_interpreter(interpreter_path: Path):
        calls.append(interpreter_path)
        return "3.12.99", None

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "python runtime module should resolve _probe_python_interpreter through server"
        )

    monkeypatch.setattr(
        server, "_probe_python_interpreter", fake_probe_python_interpreter
    )
    monkeypatch.setattr(
        python_runtime_module,
        "_probe_python_interpreter",
        _failfast,
        raising=False,
    )

    candidate, error = server._validated_python_candidate(
        candidate_path, source="manual"
    )

    assert error is None
    assert candidate == {
        "path": str(candidate_path.absolute()),
        "source": "manual",
        "version": "3.12.99",
    }
    assert calls == [candidate_path.absolute()]


def test_probe_python_interpreter_uses_live_server_app_launcher_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_runtime_module = _load_python_runtime_module_if_wired()
    if python_runtime_module is None:
        return

    interpreter_path = Path(server.sys.executable).resolve()
    calls: list[Path] = []

    def fake_is_openplot_app_launcher_path(path: Path) -> bool:
        calls.append(path)
        return path == interpreter_path

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "python runtime module should resolve _is_openplot_app_launcher_path through server"
        )

    monkeypatch.setattr(
        server,
        "_is_openplot_app_launcher_path",
        fake_is_openplot_app_launcher_path,
    )
    monkeypatch.setattr(
        python_runtime_module,
        "_is_openplot_app_launcher_path",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        server,
        "run_text_subprocess",
        _failfast,
    )

    version, error = server._probe_python_interpreter(interpreter_path)

    assert error is None
    assert version == server.sys.version.split()[0]
    assert calls == [interpreter_path]


def test_save_python_interpreter_preference_uses_live_server_preferences_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    python_runtime_module = _load_python_runtime_module_if_wired()
    if python_runtime_module is None:
        return

    preferences_path = tmp_path / "prefs" / "preferences.json"
    preferences_path.parent.mkdir(parents=True)

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "python runtime module should resolve preferences helpers through server"
        )

    monkeypatch.setattr(server, "_load_preferences_data", lambda: {"theme": "light"})
    monkeypatch.setattr(server, "_preferences_path", lambda: preferences_path)
    monkeypatch.setattr(
        python_runtime_module,
        "_load_preferences_data",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        python_runtime_module,
        "_preferences_path",
        _failfast,
        raising=False,
    )

    server._save_python_interpreter_preference("/tmp/manual-python")

    payload = json.loads(preferences_path.read_text())
    assert payload == {
        "python_interpreter": "/tmp/manual-python",
        "theme": "light",
    }
