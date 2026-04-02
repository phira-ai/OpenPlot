import ast
import importlib
from pathlib import Path
from typing import Any, Sequence, TypeAlias

import pytest

import openplot.server as server
from openplot.models import Branch, PlotSession, VersionNode


EXTRACTED_VERSION_ARTIFACT_HELPERS = (
    "_session_artifacts_root",
    "_is_managed_workspace_path",
    "_version_artifact_dir",
    "_new_run_output_dir",
    "_write_version_artifacts",
    "_delete_version_artifacts",
    "_find_branch",
    "_get_branch",
    "_active_branch",
    "_find_version",
    "_get_version",
    "_safe_read_text",
    "_media_type_for_plot_path",
    "_branch_chain",
    "_rebuild_revision_history",
    "_checkout_version",
    "_next_branch_name",
    "_create_branch",
    "_resolve_target_annotation",
    "_init_version_graph",
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


def _version_artifacts_path() -> Path:
    return _server_path().with_name("server_version_artifacts.py")


def _server_uses_extracted_version_artifacts(module: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == "_server_version_artifacts"
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
        "server_version_artifacts.py must not cache patchable server helpers at module import time"
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
    for helper_name in EXTRACTED_VERSION_ARTIFACT_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"

    for helper_name in (
        "_session_artifacts_root",
        "_new_run_output_dir",
        "_rebuild_revision_history",
        "_checkout_version",
        "_init_version_graph",
    ):
        assert len(functions[helper_name].body) > 1, (
            f"Pre-extraction contract expects {helper_name} to still be implemented in server.py"
        )


def _load_version_artifacts_module_if_wired() -> Any | None:
    server_module, functions = _read_module_ast(_server_path())
    if not _server_uses_extracted_version_artifacts(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _version_artifacts_path().exists(), (
            "server_version_artifacts.py exists before server.py wires the version-artifacts seam"
        )
        return None
    assert _version_artifacts_path().exists(), (
        "server.py references _server_version_artifacts but server_version_artifacts.py is missing"
    )
    return importlib.import_module("openplot.server_version_artifacts")


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


def test_patchable_server_helper_guard_catches_version_artifact_aliases() -> None:
    server_alias_tree = ast.parse("cached = server._checkout_version")
    assert _contains_patchable_server_helper_reference(
        server_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    server_module_alias_tree = ast.parse("cached = server_module._safe_read_text")
    assert _contains_patchable_server_helper_reference(
        server_module_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    openplot_alias_tree = ast.parse("cached = openplot.server._session_artifacts_root")
    assert _contains_patchable_server_helper_reference(
        openplot_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases={"openplot"},
    )


def test_patchable_server_helper_guard_catches_nested_aliases() -> None:
    try_body_alias_tree = ast.parse(
        "try:\n"
        "    cached = server._rebuild_revision_history\n"
        "except Exception:\n"
        "    pass\n"
    )

    with pytest.raises(AssertionError):
        _assert_no_patchable_server_helper_references_in_statement(
            try_body_alias_tree.body[0],
            server_aliases={"server", "server_module"},
            openplot_aliases=set(),
        )


def test_version_artifact_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> (
    None
):
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and '_server_version_artifacts' in bound_helpers:
        assert set(EXTRACTED_VERSION_ARTIFACT_HELPERS) <= set(bound_helpers['_server_version_artifacts'])
        for helper_name in EXTRACTED_VERSION_ARTIFACT_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_module, functions = _read_module_ast(_server_path())

    if not _server_uses_extracted_version_artifacts(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _version_artifacts_path().exists()
        return

    _, extracted_functions = _read_module_ast(_version_artifacts_path())

    for helper_name in EXTRACTED_VERSION_ARTIFACT_HELPERS:
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
        assert call.func.value.id == "_server_version_artifacts"
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


def test_version_artifacts_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    if _load_version_artifacts_module_if_wired() is None:
        return

    module, _ = _read_module_ast(_version_artifacts_path())
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


def test_init_version_graph_uses_live_server_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_artifacts_module = _load_version_artifacts_module_if_wired()
    if version_artifacts_module is None:
        return

    generated_ids = iter(("branch-1", "version-1"))
    write_calls: list[tuple[PlotSession, str, str | None, str]] = []
    checkout_calls: list[tuple[PlotSession, str, str | None]] = []
    session = PlotSession(id="session-1")

    monkeypatch.setattr(server, "_new_id", lambda: next(generated_ids))
    monkeypatch.setattr(
        server,
        "_write_version_artifacts",
        lambda current_session, version_id, *, script, plot_path: (
            write_calls.append((current_session, version_id, script, plot_path))
            or ("/tmp/script.py", "/tmp/plot.svg")
        ),
    )
    monkeypatch.setattr(
        server,
        "_checkout_version",
        lambda current_session, version_id, *, branch_id=None: (
            checkout_calls.append((current_session, version_id, branch_id))
            or current_session.versions[0]
        ),
    )
    _patch_fail_fast_if_present(monkeypatch, version_artifacts_module, "_new_id")
    _patch_fail_fast_if_present(
        monkeypatch, version_artifacts_module, "_write_version_artifacts"
    )
    _patch_fail_fast_if_present(
        monkeypatch, version_artifacts_module, "_checkout_version"
    )

    server._init_version_graph(
        session,
        script="print('hi')",
        plot_path="/tmp/input.svg",
        plot_type="svg",
    )

    assert write_calls == [(session, "version-1", "print('hi')", "/tmp/input.svg")]
    assert len(session.versions) == 1
    assert len(session.branches) == 1
    assert session.root_version_id == "version-1"
    assert session.active_branch_id == "branch-1"
    assert session.checked_out_version_id == "version-1"
    assert checkout_calls == [(session, "version-1", "branch-1")]


def test_checkout_version_uses_live_server_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_artifacts_module = _load_version_artifacts_module_if_wired()
    if version_artifacts_module is None:
        return

    version = VersionNode(
        id="version-1",
        branch_id="branch-1",
        plot_artifact_path="/tmp/plot.svg",
        plot_type="svg",
    )
    session = PlotSession(
        id="session-1",
        branches=[
            Branch(
                id="branch-1",
                name="main",
                base_version_id="version-1",
                head_version_id="version-1",
            )
        ],
        versions=[version],
    )
    rebuild_calls: list[str] = []

    monkeypatch.setattr(server, "_get_version", lambda *args, **kwargs: version)
    monkeypatch.setattr(
        server,
        "_rebuild_revision_history",
        lambda current_session: rebuild_calls.append(current_session.id),
    )
    _patch_fail_fast_if_present(monkeypatch, version_artifacts_module, "_get_version")
    _patch_fail_fast_if_present(
        monkeypatch, version_artifacts_module, "_rebuild_revision_history"
    )

    result = server._checkout_version(session, "version-1", branch_id="branch-1")

    assert result is version
    assert session.active_branch_id == "branch-1"
    assert session.checked_out_version_id == "version-1"
    assert session.current_plot == "/tmp/plot.svg"
    assert session.plot_type == "svg"
    assert rebuild_calls == ["session-1"]


def test_rebuild_revision_history_uses_live_server_safe_read_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_artifacts_module = _load_version_artifacts_module_if_wired()
    if version_artifacts_module is None:
        return

    version = VersionNode(
        id="version-1",
        branch_id="branch-1",
        plot_artifact_path="/tmp/plot.svg",
        plot_type="svg",
        script_artifact_path="/tmp/script.py",
    )
    session = PlotSession(
        id="session-1",
        active_branch_id="branch-1",
        branches=[
            Branch(
                id="branch-1",
                name="main",
                base_version_id="version-1",
                head_version_id="version-1",
            )
        ],
        versions=[version],
    )

    monkeypatch.setattr(server, "_safe_read_text", lambda path: f"loaded:{path}")
    _patch_fail_fast_if_present(
        monkeypatch, version_artifacts_module, "_safe_read_text"
    )

    server._rebuild_revision_history(session)

    assert len(session.revision_history) == 1
    assert session.revision_history[0].script == "loaded:/tmp/script.py"
    assert session.revision_history[0].plot_path == "/tmp/plot.svg"


def test_session_artifacts_root_uses_live_server_state_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    version_artifacts_module = _load_version_artifacts_module_if_wired()
    if version_artifacts_module is None:
        return

    state_root = tmp_path / "custom-state"
    session = PlotSession(id="session-1")

    monkeypatch.setattr(server, "_state_root", lambda: state_root)
    _patch_fail_fast_if_present(monkeypatch, version_artifacts_module, "_state_root")

    root = server._session_artifacts_root(session)

    assert root == state_root / "sessions" / "session-1"
    assert root.is_dir()
    assert session.artifacts_root == str(root)
