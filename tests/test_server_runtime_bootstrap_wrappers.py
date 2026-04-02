import ast
import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence, TypeAlias, cast

import pytest

import openplot.server as server
from openplot.executor import ExecutionResult
from openplot.models import PlotSession
from openplot.services.runtime import build_test_runtime


EXTRACTED_RUNTIME_BOOTSTRAP_HELPERS = (
    "_sync_runtime_from_globals",
    "_sync_globals_from_runtime",
    "_runtime_snapshot",
    "_restore_runtime_snapshot",
    "_activate_runtime",
    "_with_runtime",
    "_with_runtime_async",
    "_clear_shared_shutdown_runtime_state",
    "_ensure_session_store_loaded_impl",
    "get_session",
    "_get_session_by_id",
    "_resolve_request_session",
    "_resolve_python_executable",
    "_resolve_static_dir",
    "_lifespan",
    "create_app",
    "init_session_from_script",
)

PATCHABLE_SERVER_HELPERS = {
    "_sync_runtime_from_globals",
    "_sync_globals_from_runtime",
    "_runtime_snapshot",
    "_restore_runtime_snapshot",
    "_activate_runtime",
    "_with_runtime",
    "_with_runtime_async",
    "_clear_shared_shutdown_runtime_state",
    "_ensure_session_store_loaded",
    "_ensure_session_store_loaded_impl",
    "get_session",
    "_get_session_by_id",
    "_resolve_request_session",
    "_resolve_python_executable",
    "_resolve_static_dir",
    "_lifespan",
    "create_app",
    "init_session_from_script",
    "_new_run_output_dir",
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


def _runtime_bootstrap_path() -> Path:
    return _server_path().with_name("server_runtime_bootstrap.py")


def _server_uses_extracted_runtime_bootstrap(module: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == "_server_runtime_bootstrap"
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
        "server_runtime_bootstrap.py must not cache patchable server helpers at module import time"
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
    for helper_name in EXTRACTED_RUNTIME_BOOTSTRAP_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"

    for helper_name in (
        "_sync_runtime_from_globals",
        "get_session",
        "_ensure_session_store_loaded_impl",
        "_lifespan",
        "create_app",
        "init_session_from_script",
    ):
        assert len(functions[helper_name].body) > 1, (
            f"Pre-extraction contract expects {helper_name} to still be implemented in server.py"
        )


def _load_runtime_bootstrap_module_if_wired() -> Any | None:
    server_module, functions = _read_module_ast(_server_path())
    if not _server_uses_extracted_runtime_bootstrap(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _runtime_bootstrap_path().exists(), (
            "server_runtime_bootstrap.py exists before server.py wires the runtime/bootstrap seam"
        )
        return None
    assert _runtime_bootstrap_path().exists(), (
        "server.py references _server_runtime_bootstrap but server_runtime_bootstrap.py is missing"
    )
    return importlib.import_module("openplot.server_runtime_bootstrap")


def test_patchable_server_helper_guard_catches_runtime_bootstrap_aliases() -> None:
    server_alias_tree = ast.parse("cached = server._sync_runtime_from_globals")
    assert _contains_patchable_server_helper_reference(
        server_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    server_module_alias_tree = ast.parse(
        "cached = server_module._ensure_session_store_loaded"
    )
    assert _contains_patchable_server_helper_reference(
        server_module_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    openplot_alias_tree = ast.parse(
        "cached = openplot.server._resolve_python_executable"
    )
    assert _contains_patchable_server_helper_reference(
        openplot_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases={"openplot"},
    )


def test_patchable_server_helper_guard_catches_try_body_aliases() -> None:
    try_body_alias_tree = ast.parse(
        "try:\n"
        "    cached = server._ensure_session_store_loaded\n"
        "except Exception:\n"
        "    pass\n"
    )

    with pytest.raises(AssertionError):
        _assert_no_patchable_server_helper_references_in_statement(
            try_body_alias_tree.body[0],
            server_aliases={"server", "server_module"},
            openplot_aliases=set(),
        )


def test_runtime_bootstrap_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> (
    None
):
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and '_server_runtime_bootstrap' in bound_helpers:
        assert set(EXTRACTED_RUNTIME_BOOTSTRAP_HELPERS) <= set(bound_helpers['_server_runtime_bootstrap'])
        for helper_name in EXTRACTED_RUNTIME_BOOTSTRAP_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_module, functions = _read_module_ast(_server_path())

    if not _server_uses_extracted_runtime_bootstrap(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _runtime_bootstrap_path().exists()
        return

    _, extracted_functions = _read_module_ast(_runtime_bootstrap_path())

    for helper_name in EXTRACTED_RUNTIME_BOOTSTRAP_HELPERS:
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
        assert call.func.value.id == "_server_runtime_bootstrap"
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


def test_runtime_bootstrap_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    if _load_runtime_bootstrap_module_if_wired() is None:
        return

    module, _ = _read_module_ast(_runtime_bootstrap_path())
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


@pytest.mark.anyio
async def test_lifespan_uses_live_server_session_store_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_bootstrap_module = _load_runtime_bootstrap_module_if_wired()
    if runtime_bootstrap_module is None:
        return

    runtime = build_test_runtime(store_root=tmp_path / "isolated-state")
    app = SimpleNamespace(state=SimpleNamespace(runtime=runtime))
    calls: list[tuple[str, object]] = []

    def fake_ensure_session_store_loaded(*, force_reload: bool = False) -> None:
        calls.append(("ensure", force_reload))

    def fake_restore_latest_workspace_into_runtime(runtime_arg) -> None:
        calls.append(("restore", runtime_arg))

    async def fake_teardown_runtime(runtime_arg) -> None:
        calls.append(("teardown", runtime_arg))

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "runtime bootstrap module should resolve _ensure_session_store_loaded through server"
        )

    monkeypatch.setattr(
        server, "_ensure_session_store_loaded", fake_ensure_session_store_loaded
    )
    monkeypatch.setattr(
        server.session_services,
        "should_restore_session_store",
        lambda runtime_arg: True,
    )
    monkeypatch.setattr(
        server.session_services,
        "restore_latest_workspace_into_runtime",
        fake_restore_latest_workspace_into_runtime,
    )
    monkeypatch.setattr(
        server.session_services,
        "teardown_runtime",
        fake_teardown_runtime,
    )
    monkeypatch.setattr(
        runtime_bootstrap_module,
        "_ensure_session_store_loaded",
        _failfast,
        raising=False,
    )

    async with server._lifespan(app=cast(Any, app)):
        pass

    assert calls == [
        ("ensure", False),
        ("restore", runtime),
        ("teardown", runtime),
    ]


def test_init_session_from_script_uses_live_server_runtime_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_bootstrap_module = _load_runtime_bootstrap_module_if_wired()
    if runtime_bootstrap_module is None:
        return

    runtime = build_test_runtime(store_root=tmp_path / "isolated-state")
    script_path = tmp_path / "workspace" / "plot.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("print('hello')\n")
    capture_dir = tmp_path / "captures"
    calls: list[tuple[str, object]] = []

    def fake_ensure_session_store_loaded(*, force_reload: bool = False) -> None:
        calls.append(("ensure", force_reload))

    def fake_new_run_output_dir(_session: PlotSession) -> Path:
        calls.append(("capture_dir", capture_dir))
        return capture_dir

    def fake_resolve_python_executable(_session: PlotSession | None = None) -> str:
        calls.append(("python", "patched-python"))
        return "patched-python"

    def fake_execute_script(path: Path, *, capture_dir: Path, python_executable: str):
        calls.append(("execute", (path.resolve(), capture_dir, python_executable)))
        return ExecutionResult(success=False, error="expected-test-failure")

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "runtime bootstrap module should resolve runtime helpers through server"
        )

    monkeypatch.setattr(
        server, "_ensure_session_store_loaded", fake_ensure_session_store_loaded
    )
    monkeypatch.setattr(server, "_read_file_text", lambda _path: "print('hello')\n")
    monkeypatch.setattr(server, "_new_run_output_dir", fake_new_run_output_dir)
    monkeypatch.setattr(
        server, "_resolve_python_executable", fake_resolve_python_executable
    )
    monkeypatch.setattr(server, "execute_script", fake_execute_script)
    monkeypatch.setattr(server, "_clear_plot_mode_state", lambda: None)
    monkeypatch.setattr(
        runtime_bootstrap_module,
        "_new_run_output_dir",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        runtime_bootstrap_module,
        "_resolve_python_executable",
        _failfast,
        raising=False,
    )

    result = server.init_session_from_script(script_path, runtime=runtime)

    assert result.success is False
    assert calls == [
        ("ensure", False),
        ("capture_dir", capture_dir),
        ("python", "patched-python"),
        ("execute", (script_path.resolve(), capture_dir, "patched-python")),
    ]


def test_with_runtime_uses_live_server_sync_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_bootstrap_module = _load_runtime_bootstrap_module_if_wired()
    if runtime_bootstrap_module is None:
        return

    runtime = build_test_runtime(store_root=tmp_path / "isolated-state")
    calls: list[tuple[str, object]] = []

    def fake_sync_globals_from_runtime(runtime_arg) -> None:
        calls.append(("sync_globals", runtime_arg))

    def fake_sync_runtime_from_globals(runtime_arg) -> None:
        calls.append(("sync_runtime", runtime_arg))

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "runtime bootstrap module should resolve sync helpers through server"
        )

    monkeypatch.setattr(
        server, "_sync_globals_from_runtime", fake_sync_globals_from_runtime
    )
    monkeypatch.setattr(
        server, "_sync_runtime_from_globals", fake_sync_runtime_from_globals
    )
    monkeypatch.setattr(
        runtime_bootstrap_module,
        "_sync_globals_from_runtime",
        _failfast,
        raising=False,
    )
    monkeypatch.setattr(
        runtime_bootstrap_module,
        "_sync_runtime_from_globals",
        _failfast,
        raising=False,
    )

    result = server._with_runtime(
        runtime, lambda: calls.append(("callback", runtime)) or "ok"
    )

    assert result == "ok"
    assert calls == [
        ("sync_globals", runtime),
        ("callback", runtime),
        ("sync_runtime", runtime),
    ]


def test_get_session_uses_live_server_session_store_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_bootstrap_module = _load_runtime_bootstrap_module_if_wired()
    if runtime_bootstrap_module is None:
        return

    calls: list[str] = []
    session = PlotSession(id="session-live", workspace_name="Live workspace")

    def fake_ensure_session_store_loaded(*, force_reload: bool = False) -> None:
        assert force_reload is False
        calls.append("ensure")

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "runtime bootstrap module should resolve _ensure_session_store_loaded through server"
        )

    monkeypatch.setattr(
        server, "_ensure_session_store_loaded", fake_ensure_session_store_loaded
    )
    monkeypatch.setattr(server, "_session", session)
    monkeypatch.setattr(server, "_active_session_id", session.id)
    monkeypatch.setattr(server, "_sessions", {session.id: session})
    monkeypatch.setattr(
        runtime_bootstrap_module,
        "_ensure_session_store_loaded",
        _failfast,
        raising=False,
    )

    assert server.get_session() is session
    assert calls == ["ensure"]
