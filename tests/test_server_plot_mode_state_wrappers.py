import ast
from pathlib import Path
from types import SimpleNamespace
from collections.abc import Iterator
from typing import TypeAlias

import pytest

import openplot.server as server


EXTRACTED_PLOT_MODE_STATE_HELPERS = (
    "_plot_mode_root_dir",
    "_plot_mode_artifacts_dir",
    "_plot_mode_captures_dir",
    "_plot_mode_generated_script_path",
    "_plot_mode_snapshot_path",
    "_plot_mode_artifacts_path_for_id",
    "_plot_mode_workspace_snapshot_path_for_id",
    "_plot_mode_workspace_snapshot_path",
    "_plot_mode_has_user_content",
    "_plot_mode_is_workspace",
    "_promote_plot_mode_workspace",
    "_ensure_plot_mode_workspace_name",
    "_is_active_plot_mode_state",
    "_save_plot_mode_snapshot",
    "_load_plot_mode_state_from_payload",
    "_load_plot_mode_state_from_path",
    "_infer_plot_mode_state_from_artifacts_dir",
    "_load_plot_mode_snapshot",
    "_load_all_plot_mode_workspaces",
    "_load_plot_mode_workspace_by_id",
    "_resolve_plot_mode_workspace",
    "_plot_mode_picker_base_dir",
    "_plot_mode_workspace_base_dir",
    "_delete_plot_mode_snapshot",
    "_touch_plot_mode",
    "_get_plot_mode_state",
    "_clear_plot_mode_state",
    "_broadcast_plot_mode_state",
    "_plot_mode_summary",
    "_plot_mode_sort_key",
)
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


def _server_uses_extracted_plot_mode_state(module: ast.Module) -> bool:
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0 and (node.module or "") == "":
                if any(
                    alias.name == "server_plot_mode_state"
                    and alias.asname == "_server_plot_mode_state"
                    for alias in node.names
                ):
                    return True
        elif isinstance(node, ast.Name) and node.id == "_server_plot_mode_state":
            return True
    return False


def _assert_pre_extraction_contract(
    module: ast.Module, functions: dict[str, FunctionNode]
) -> None:
    assert not _server_uses_extracted_plot_mode_state(module)
    for helper_name in EXTRACTED_PLOT_MODE_STATE_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"


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


def _returns_none(function: FunctionNode) -> bool:
    return (
        function.returns is not None
        and isinstance(function.returns, ast.Constant)
        and function.returns.value is None
    )


def _dump_node(node: ast.expr | None) -> str | None:
    return None if node is None else ast.dump(node)


def _parameter_shape(
    function: FunctionNode,
    *,
    drop_leading_server_module: bool = False,
) -> list[tuple[str, str, str | None]]:
    positional = [
        *(("posonly", arg.arg) for arg in function.args.posonlyargs),
        *(("arg", arg.arg) for arg in function.args.args),
    ]
    positional_defaults = [
        *([None] * (len(positional) - len(function.args.defaults))),
        *(_dump_node(default) for default in function.args.defaults),
    ]
    parameters = [
        (kind, name, default)
        for (kind, name), default in zip(positional, positional_defaults, strict=True)
    ]
    if drop_leading_server_module:
        assert parameters, "Extracted helper must accept server_module first"
        first_kind, first_name, first_default = parameters[0]
        assert first_kind in {"posonly", "arg"}
        assert first_name == "server_module"
        assert first_default is None
        parameters = parameters[1:]
    if function.args.vararg is not None:
        parameters.append(("vararg", function.args.vararg.arg, None))
    parameters.extend(
        (
            "kwonly",
            arg.arg,
            _dump_node(default),
        )
        for arg, default in zip(
            function.args.kwonlyargs, function.args.kw_defaults, strict=True
        )
    )
    if function.args.kwarg is not None:
        parameters.append(("kwarg", function.args.kwarg.arg, None))
    return parameters


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
        if isinstance(child, ast.Attribute) and child.attr.startswith("_"):
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
                and helper_name.value.startswith("_")
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
        "server_plot_mode_state.py must not cache patchable server helpers at module import time"
    )


def test_patchable_server_helper_guard_catches_non_inventory_aliases() -> None:
    server_alias_tree = ast.parse("cached = server._broadcast")
    assert _contains_patchable_server_helper_reference(
        server_alias_tree,
        server_aliases={"server"},
        openplot_aliases=set(),
    )

    openplot_alias_tree = ast.parse(
        "cached = openplot.server._runtime_plot_mode_state_value"
    )
    assert _contains_patchable_server_helper_reference(
        openplot_alias_tree,
        server_aliases=set(),
        openplot_aliases={"openplot"},
    )


def test_server_plot_mode_state_module_exists() -> None:
    server_path = Path(server.__file__).resolve()
    state_path = server_path.with_name("server_plot_mode_state.py")

    assert state_path.exists()


def test_plot_mode_state_helpers_are_thin_wrappers_when_extracted() -> None:
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and "_server_plot_mode_state" in bound_helpers:
        assert set(EXTRACTED_PLOT_MODE_STATE_HELPERS) <= set(
            bound_helpers["_server_plot_mode_state"]
        )
        for helper_name in EXTRACTED_PLOT_MODE_STATE_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_path = Path(server.__file__).resolve()
    state_path = server_path.with_name("server_plot_mode_state.py")
    server_module, functions = _read_module_ast(server_path)
    assert _server_uses_extracted_plot_mode_state(server_module)

    assert state_path.exists(), (
        "server.py references _server_plot_mode_state but server_plot_mode_state.py is missing"
    )

    _, state_functions = _read_module_ast(state_path)

    for helper_name in EXTRACTED_PLOT_MODE_STATE_HELPERS:
        function = functions[helper_name]
        state_function = state_functions.get(helper_name)
        assert state_function is not None, f"Missing extracted helper for {helper_name}"
        assert _parameter_shape(function) == _parameter_shape(
            state_function, drop_leading_server_module=True
        )
        assert len(function.body) == 1, (
            f"{helper_name} should stay a one-statement wrapper"
        )

        statement = function.body[0]
        if _returns_none(state_function):
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
        assert call.func.value.id == "_server_plot_mode_state"
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


def test_plot_mode_state_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    server_path = Path(server.__file__).resolve()
    state_path = server_path.with_name("server_plot_mode_state.py")
    server_module, functions = _read_module_ast(server_path)
    assert _server_uses_extracted_plot_mode_state(server_module)

    assert state_path.exists(), (
        "server.py references _server_plot_mode_state but server_plot_mode_state.py is missing"
    )

    module, _ = _read_module_ast(state_path)
    server_aliases: set[str] = set()
    openplot_aliases: set[str] = set()

    for node in module.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openplot":
                    openplot_aliases.add(alias.asname or alias.name)
                if alias.name == "openplot.server":
                    raise AssertionError(
                        "Forbidden import-time binding source in server_plot_mode_state.py: openplot.server"
                    )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name == "openplot" and any(
                alias.name == "server" for alias in node.names
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_state.py: from openplot import server"
                )
            if (
                node.level > 0
                and module_name == ""
                and any(alias.name == "server" for alias in node.names)
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_state.py: from . import server"
                )

    server_aliases.add("server")
    for node in module.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
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


def test_touch_plot_mode_uses_live_server_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    calls: list[str] = []

    monkeypatch.setattr(server, "_plot_mode_has_user_content", lambda current: True)
    monkeypatch.setattr(
        server,
        "_promote_plot_mode_workspace",
        lambda current: calls.append(f"promote:{current.id}"),
    )
    monkeypatch.setattr(
        server,
        "_ensure_plot_mode_workspace_name",
        lambda current: calls.append(f"name:{current.id}"),
    )
    monkeypatch.setattr(server, "_now_iso", lambda: "2026-03-26T00:00:00Z")
    monkeypatch.setattr(
        server,
        "_save_plot_mode_snapshot",
        lambda current: calls.append(f"save:{current.id}"),
    )

    server._touch_plot_mode(state)

    assert state.updated_at == "2026-03-26T00:00:00Z"
    assert calls == [
        f"promote:{state.id}",
        f"name:{state.id}",
        f"save:{state.id}",
    ]


def test_resolve_plot_mode_workspace_uses_live_server_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_state = SimpleNamespace(id="active-workspace")
    loaded_state = SimpleNamespace(id="loaded-workspace")
    calls: list[str] = []

    monkeypatch.setattr(server, "_runtime_plot_mode_state_value", lambda: active_state)
    monkeypatch.setattr(
        server,
        "_load_plot_mode_workspace_by_id",
        lambda workspace_id: calls.append(workspace_id) or loaded_state,
    )

    active_resolved = server._resolve_plot_mode_workspace("active-workspace")
    resolved = server._resolve_plot_mode_workspace("loaded-workspace")

    assert active_resolved is active_state
    assert resolved is loaded_state
    assert calls == ["loaded-workspace"]


def test_infer_plot_mode_state_from_artifacts_dir_uses_live_iso_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifacts_dir = tmp_path / "workspace"
    artifacts_dir.mkdir()
    (artifacts_dir / server._plot_mode_generated_script_name).write_text("print('ok')")
    iso_calls: list[float] = []

    monkeypatch.setattr(
        server,
        "_iso_from_timestamp",
        lambda value: iso_calls.append(value) or f"patched:{len(iso_calls)}",
    )

    state = server._infer_plot_mode_state_from_artifacts_dir(artifacts_dir)

    assert state is not None
    assert state.created_at == "patched:1"
    assert state.updated_at == "patched:2"
    assert len(iso_calls) == 2


def test_plot_mode_picker_base_dir_uses_live_common_parent_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    first_file = workspace_dir / "inputs" / "alpha.csv"
    first_file.parent.mkdir(parents=True)
    first_file.write_text("x,y\n1,2\n")
    second_file = workspace_dir / "inputs" / "beta.csv"
    second_file.write_text("x,y\n3,4\n")
    state = server.init_plot_mode_session(workspace_dir=workspace_dir)
    state.files = [
        server.PlotModeFile(
            name="alpha.csv",
            stored_path=str(first_file),
            size_bytes=first_file.stat().st_size,
        ),
        server.PlotModeFile(
            name="beta.csv",
            stored_path=str(second_file),
            size_bytes=second_file.stat().st_size,
        ),
    ]
    expected_dir = tmp_path / "patched-base"
    calls: list[list[Path]] = []

    monkeypatch.setattr(
        server,
        "_common_parent_dir",
        lambda paths: calls.append(list(paths)) or expected_dir,
    )

    base_dir = server._plot_mode_picker_base_dir(state)

    assert base_dir == expected_dir
    assert calls == [[first_file, second_file]]


def test_plot_mode_workspace_base_dir_uses_runtime_indirected_state_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_state = server.init_plot_mode_session(
        workspace_dir=tmp_path / "runtime-workspace"
    )
    direct_state = server.init_plot_mode_session(
        workspace_dir=tmp_path / "direct-workspace"
    )
    runtime_workspace_dir = tmp_path / "runtime-fallback"
    runtime_workspace_dir.mkdir()

    monkeypatch.setattr(server, "_plot_mode", direct_state)
    monkeypatch.setattr(server, "_workspace_dir", tmp_path / "direct-fallback")
    monkeypatch.setattr(server, "_runtime_plot_mode_state_value", lambda: runtime_state)
    monkeypatch.setattr(server, "_runtime_workspace_dir", lambda: runtime_workspace_dir)
    monkeypatch.setattr(
        server, "_plot_mode_picker_base_dir", lambda state: Path(state.workspace_dir)
    )
    monkeypatch.setattr(
        server, "_is_internal_plot_mode_workspace_dir", lambda path: False
    )

    assert server._plot_mode_workspace_base_dir(None) == Path(
        runtime_state.workspace_dir
    )

    monkeypatch.setattr(server, "_runtime_plot_mode_state_value", lambda: None)

    assert server._plot_mode_workspace_base_dir(None) == runtime_workspace_dir.resolve()


def test_clear_plot_mode_state_clears_non_shared_runtime_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    existing = server.init_plot_mode_session(
        workspace_dir=tmp_path / "runtime-workspace"
    )
    existing.is_workspace = False
    runtime = SimpleNamespace(store=SimpleNamespace(plot_mode=existing))
    deleted: list[object] = []

    monkeypatch.setattr(server, "_plot_mode", "shared-sentinel")
    monkeypatch.setattr(server, "_runtime_plot_mode_state_value", lambda: existing)
    monkeypatch.setattr(server, "_current_runtime", lambda: runtime)
    monkeypatch.setattr(server, "_runtime_is_shared", lambda current: False)
    monkeypatch.setattr(server, "_plot_mode_is_workspace", lambda state: False)
    monkeypatch.setattr(
        server,
        "_delete_plot_mode_snapshot",
        lambda *, state=None, clear_active_snapshot=True: deleted.append(state),
    )

    server._clear_plot_mode_state()

    assert runtime.store.plot_mode is None
    assert server._plot_mode == "shared-sentinel"
    assert deleted == [existing]


@pytest.mark.anyio
async def test_broadcast_plot_mode_state_uses_live_server_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        server,
        "_ensure_plot_mode_workspace_name",
        lambda current: calls.append(("name", current.id)),
    )
    monkeypatch.setattr(
        server,
        "_save_plot_mode_snapshot",
        lambda current: calls.append(("save", current.id)),
    )

    async def fake_broadcast(event: dict) -> None:
        calls.append((event["type"], event["plot_mode"]["id"]))

    monkeypatch.setattr(server, "_broadcast", fake_broadcast)

    await server._broadcast_plot_mode_state(state)

    assert calls == [
        ("name", state.id),
        ("save", state.id),
        ("plot_mode_updated", state.id),
    ]
