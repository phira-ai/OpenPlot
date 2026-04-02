import ast
import importlib
from collections.abc import Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeAlias

import pytest

import openplot.server as server
from openplot.models import PlotSession


EXTRACTED_SESSION_MISC_HELPERS = (
    "_touch_session",
    "_default_workspace_name",
    "_ensure_workspace_name",
    "_workspace_for_session",
    "_session_workspace_id",
    "_session_sort_key",
    "_load_session_snapshot",
    "_save_session_registry",
    "_save_session_snapshot",
    "_set_active_session",
    "_session_summary",
    "_bootstrap_payload",
    "init_plot_mode_session",
)

PATCHABLE_SERVER_HELPERS = {
    *EXTRACTED_SESSION_MISC_HELPERS,
    "set_workspace_dir",
}

FunctionNode: TypeAlias = ast.FunctionDef | ast.AsyncFunctionDef


@pytest.fixture(autouse=True)
def _reset_plot_mode_runtime_state() -> Iterator[None]:
    server._reset_plot_mode_runtime_state()
    yield
    server._reset_plot_mode_runtime_state()


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


def _session_misc_path() -> Path:
    return _server_path().with_name("server_sessions_misc.py")


def _session_misc_import_alias(module: ast.Module) -> str | None:
    for node in module.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith("server_sessions_misc"):
                    return alias.asname or alias.name.rsplit(".", 1)[-1]
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "server_sessions_misc":
                    return alias.asname or alias.name
    return None


def _server_uses_extracted_session_misc(module: ast.Module) -> bool:
    return _session_misc_import_alias(module) is not None


def _assert_pre_extraction_contract(
    module: ast.Module, functions: dict[str, FunctionNode]
) -> None:
    assert not _server_uses_extracted_session_misc(module)
    for helper_name in EXTRACTED_SESSION_MISC_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"

    for helper_name in (
        "_default_workspace_name",
        "_workspace_for_session",
        "_load_session_snapshot",
        "_save_session_registry",
        "_set_active_session",
        "_session_summary",
        "_bootstrap_payload",
        "init_plot_mode_session",
    ):
        assert len(functions[helper_name].body) > 1, (
            f"Pre-extraction contract expects {helper_name} to still be implemented in server.py"
        )


def _load_session_misc_module_if_wired() -> Any | None:
    server_module, functions = _read_module_ast(_server_path())
    if not _server_uses_extracted_session_misc(server_module):
        _assert_pre_extraction_contract(server_module, functions)
        assert not _session_misc_path().exists(), (
            "server_sessions_misc.py exists before server.py wires the session/bootstrap misc seam"
        )
        return None
    assert _session_misc_path().exists(), (
        "server.py references _server_sessions_misc but server_sessions_misc.py is missing"
    )
    return importlib.import_module("openplot.server_sessions_misc")


def _resolves_live_server_module(node: ast.AST) -> bool:
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "sys"
        and node.value.attr == "modules"
    ):
        slice_node = node.slice
        return (
            isinstance(slice_node, ast.Name)
            and slice_node.id == "__name__"
            or isinstance(slice_node, ast.Constant)
            and slice_node.value == server.__name__
        )
    return isinstance(node, ast.Name) and node.id == "server"


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
        if isinstance(child, ast.Attribute) and child.attr in PATCHABLE_SERVER_HELPERS:
            if isinstance(child.value, ast.Name) and child.value.id in server_aliases:
                return True
            if (
                isinstance(child.value, ast.Attribute)
                and child.value.attr == "server"
                and isinstance(child.value.value, ast.Name)
                and child.value.value.id in openplot_aliases
            ):
                return True
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            if child.func.id != "getattr" or len(child.args) < 2:
                continue
            helper_name = child.args[1]
            if not (
                isinstance(helper_name, ast.Constant)
                and isinstance(helper_name.value, str)
                and helper_name.value in PATCHABLE_SERVER_HELPERS
            ):
                continue
            target = child.args[0]
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
        "server_sessions_misc.py must not cache patchable server helpers at module import time"
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


def test_session_misc_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> (
    None
):
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and '_server_sessions_misc' in bound_helpers:
        assert set(EXTRACTED_SESSION_MISC_HELPERS) <= set(bound_helpers['_server_sessions_misc'])
        for helper_name in EXTRACTED_SESSION_MISC_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_module, functions = _read_module_ast(_server_path())

    if not _server_uses_extracted_session_misc(server_module):
        _assert_pre_extraction_contract(server_module, functions)
        assert not _session_misc_path().exists()
        return

    extracted_alias = _session_misc_import_alias(server_module)
    assert extracted_alias is not None
    _, extracted_functions = _read_module_ast(_session_misc_path())

    for helper_name in EXTRACTED_SESSION_MISC_HELPERS:
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
        assert call.func.value.id == extracted_alias
        assert call.func.attr == helper_name
        assert call.args, f"{helper_name} should pass the server module first"
        assert _resolves_live_server_module(call.args[0])

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


def test_session_misc_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    if _load_session_misc_module_if_wired() is None:
        return

    module, _ = _read_module_ast(_session_misc_path())
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


def test_bootstrap_payload_uses_live_server_update_status_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_misc_module = _load_session_misc_module_if_wired()
    if session_misc_module is None:
        return

    calls: list[tuple[str, object]] = []

    def fake_build_update_status_payload(*, allow_network: bool) -> dict[str, object]:
        calls.append(("update_status", allow_network))
        return {"status": "patched"}

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "server_sessions_misc should resolve _build_update_status_payload through server"
        )

    monkeypatch.setattr(
        server, "_build_update_status_payload", fake_build_update_status_payload
    )
    monkeypatch.setattr(server, "_list_session_summaries", lambda: [{"id": "sentinel"}])
    monkeypatch.setattr(
        session_misc_module,
        "_build_update_status_payload",
        _failfast,
        raising=False,
    )

    payload = server._bootstrap_payload(
        mode="annotation",
        session=PlotSession(id="session-live", workspace_name="Live workspace"),
        plot_mode=None,
    )

    assert payload["update_status"] == {"status": "patched"}
    assert calls == [("update_status", False)]


def test_set_active_session_uses_live_server_registry_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_misc_module = _load_session_misc_module_if_wired()
    if session_misc_module is None:
        return

    calls: list[str] = []

    def fake_save_session_registry() -> None:
        calls.append("save")

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "server_sessions_misc should resolve _save_session_registry through server"
        )

    monkeypatch.setattr(server, "_active_session_id", "session-old")
    monkeypatch.setattr(server, "_session", object())
    monkeypatch.setattr(server, "_save_session_registry", fake_save_session_registry)
    monkeypatch.setattr(
        session_misc_module,
        "_save_session_registry",
        _failfast,
        raising=False,
    )

    server._set_active_session(None, clear_plot_mode=False)

    assert server._active_session_id is None
    assert server._session is None
    assert calls == ["save"]


def test_init_plot_mode_session_uses_live_server_plot_mode_factory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_misc_module = _load_session_misc_module_if_wired()
    if session_misc_module is None:
        return

    workspace_dir = tmp_path / "workspace"
    resolved_workspace = workspace_dir.resolve()
    calls: list[tuple[str, object]] = []
    state = SimpleNamespace(id="plot-mode-live", workspace_dir=str(resolved_workspace))

    def fake_ensure_session_store_loaded(*, force_reload: bool = False) -> None:
        calls.append(("ensure_store", force_reload))

    def fake_new_plot_mode_state(*, workspace_dir: Path | None, is_workspace: bool):
        calls.append(("new_plot_mode_state", (workspace_dir, is_workspace)))
        return state

    def fake_set_workspace_dir(path: Path) -> None:
        calls.append(("set_workspace_dir", path))

    def fake_set_active_session(
        session_id: str | None, *, clear_plot_mode: bool
    ) -> None:
        calls.append(("set_active_session", (session_id, clear_plot_mode)))

    def _failfast(*args, **kwargs):
        raise AssertionError(
            "server_sessions_misc should resolve _new_plot_mode_state through server"
        )

    monkeypatch.setattr(
        server, "_ensure_session_store_loaded", fake_ensure_session_store_loaded
    )
    monkeypatch.setattr(server, "_new_plot_mode_state", fake_new_plot_mode_state)
    monkeypatch.setattr(server, "set_workspace_dir", fake_set_workspace_dir)
    monkeypatch.setattr(server, "_set_active_session", fake_set_active_session)
    monkeypatch.setattr(server, "_plot_mode", None)
    monkeypatch.setattr(
        session_misc_module,
        "_new_plot_mode_state",
        _failfast,
        raising=False,
    )

    result = server.init_plot_mode_session(workspace_dir=workspace_dir)

    assert result is state
    assert calls == [
        ("ensure_store", False),
        ("new_plot_mode_state", (resolved_workspace, False)),
        ("set_workspace_dir", resolved_workspace),
        ("set_active_session", (None, False)),
    ]
