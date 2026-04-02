import ast
from collections.abc import Iterator
from pathlib import Path
from typing import TypeAlias

import pytest

import openplot.server as server


PLOT_MODE_REVIEW_HELPERS = (
    "_build_plot_mode_review_prompt",
    "_run_plot_mode_autonomous_reviews",
)
PLOT_MODE_REVIEW_HELPER_SIGNATURES = {
    "_build_plot_mode_review_prompt": [
        ("arg", "state", None),
        ("kwonly", "iteration_index", None),
        ("kwonly", "focus_direction", None),
    ],
    "_run_plot_mode_autonomous_reviews": [
        ("kwonly", "state", None),
        ("kwonly", "runner", None),
        ("kwonly", "model", None),
        ("kwonly", "variant", None),
        ("kwonly", "summary_message", None),
    ],
}
ASYNC_PLOT_MODE_REVIEW_HELPERS = {"_run_plot_mode_autonomous_reviews"}
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


def _server_uses_extracted_plot_mode_review(module: ast.Module) -> bool:
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0 and (node.module or "") == "":
                if any(
                    alias.name == "server_plot_mode_review"
                    and alias.asname == "_server_plot_mode_review"
                    for alias in node.names
                ):
                    return True
        elif isinstance(node, ast.Name) and node.id == "_server_plot_mode_review":
            return True
    return False


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
        ("kwonly", arg.arg, _dump_node(default))
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
        "server_plot_mode_review.py must not cache patchable server helpers at module import time"
    )


def _assert_no_patchable_server_helper_references_in_statement(
    statement: ast.stmt,
    *,
    server_aliases: set[str],
    openplot_aliases: set[str],
) -> None:
    for child in ast.iter_child_nodes(statement):
        if isinstance(child, ast.expr):
            _assert_no_patchable_server_helper_reference(
                child,
                server_aliases=server_aliases,
                openplot_aliases=openplot_aliases,
            )
            continue
        if isinstance(child, ast.stmt):
            _assert_no_patchable_server_helper_references_in_statement(
                child,
                server_aliases=server_aliases,
                openplot_aliases=openplot_aliases,
            )
            continue
        for grandchild in ast.walk(child):
            if isinstance(grandchild, ast.expr):
                _assert_no_patchable_server_helper_reference(
                    grandchild,
                    server_aliases=server_aliases,
                    openplot_aliases=openplot_aliases,
                )
            elif isinstance(grandchild, ast.stmt) and grandchild is not statement:
                _assert_no_patchable_server_helper_references_in_statement(
                    grandchild,
                    server_aliases=server_aliases,
                    openplot_aliases=openplot_aliases,
                )


def _assert_pre_extraction_contract(
    module: ast.Module, functions: dict[str, FunctionNode]
) -> None:
    assert not _server_uses_extracted_plot_mode_review(module)
    for helper_name in PLOT_MODE_REVIEW_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"
        assert (
            _parameter_shape(functions[helper_name])
            == PLOT_MODE_REVIEW_HELPER_SIGNATURES[helper_name]
        )


def _review_module_ready() -> tuple[bool, Path, ast.Module, dict[str, FunctionNode]]:
    server_path = Path(server.__file__).resolve()
    server_module, functions = _read_module_ast(server_path)
    return (
        _server_uses_extracted_plot_mode_review(server_module),
        server_path.with_name("server_plot_mode_review.py"),
        server_module,
        functions,
    )


def test_plot_mode_review_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> (
    None
):
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and '_server_plot_mode_review' in bound_helpers:
        assert set(PLOT_MODE_REVIEW_HELPERS) <= set(bound_helpers['_server_plot_mode_review'])
        for helper_name in PLOT_MODE_REVIEW_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    uses_extracted_review, review_path, server_module, functions = (
        _review_module_ready()
    )

    if not uses_extracted_review:
        _assert_pre_extraction_contract(server_module, functions)
        return

    assert review_path.exists(), (
        "server.py references _server_plot_mode_review but server_plot_mode_review.py is missing"
    )

    _, review_functions = _read_module_ast(review_path)
    extracted_helpers: set[str] = set()

    for helper_name in PLOT_MODE_REVIEW_HELPERS:
        function = functions[helper_name]
        assert (
            _parameter_shape(function)
            == PLOT_MODE_REVIEW_HELPER_SIGNATURES[helper_name]
        )
        assert len(function.body) == 1, (
            f"{helper_name} should stay a one-statement wrapper"
        )

        statement = function.body[0]
        assert isinstance(statement, (ast.Expr, ast.Return)), (
            f"{helper_name} should use a single expression or return statement"
        )

        call = statement.value
        if helper_name in ASYNC_PLOT_MODE_REVIEW_HELPERS:
            assert isinstance(function, ast.AsyncFunctionDef), (
                f"{helper_name} should remain async"
            )
            assert isinstance(call, ast.Await), (
                f"{helper_name} should await the extracted async helper"
            )
            call = call.value
        elif isinstance(call, ast.Await):
            call = call.value

        assert isinstance(call, ast.Call), (
            f"{helper_name} should call the extracted helper directly"
        )
        assert isinstance(call.func, ast.Attribute), (
            f"{helper_name} should delegate through _server_plot_mode_review"
        )
        assert isinstance(call.func.value, ast.Name), (
            f"{helper_name} should reference _server_plot_mode_review by name"
        )
        assert call.func.value.id == "_server_plot_mode_review", (
            f"{helper_name} should delegate through _server_plot_mode_review"
        )
        assert call.func.attr == helper_name, (
            f"{helper_name} should call _server_plot_mode_review.{helper_name}"
        )

        extracted_helpers.add(helper_name)
        review_function = review_functions.get(helper_name)
        assert review_function is not None, (
            f"Missing extracted helper for {helper_name}"
        )
        assert _parameter_shape(function) == _parameter_shape(
            review_function, drop_leading_server_module=True
        )
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

    assert extracted_helpers == set(PLOT_MODE_REVIEW_HELPERS), (
        "Expected every helper in the review inventory to use _server_plot_mode_review"
    )


def test_plot_mode_review_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    uses_extracted_review, review_path, _server_module, _functions = (
        _review_module_ready()
    )

    if not uses_extracted_review:
        return

    assert review_path.exists(), (
        "server.py references _server_plot_mode_review but server_plot_mode_review.py is missing"
    )

    module, _ = _read_module_ast(review_path)
    server_aliases: set[str] = {"server"}
    openplot_aliases: set[str] = set()

    for node in module.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openplot":
                    openplot_aliases.add(alias.asname or alias.name)
                if (
                    alias.name == "openplot.server"
                    or alias.name.startswith("openplot.server_")
                    or alias.name.startswith("openplot.services")
                ):
                    raise AssertionError(
                        "Forbidden import-time binding source in server_plot_mode_review.py"
                    )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            imported_names = {alias.name for alias in node.names}
            if module_name == "openplot" and any(
                name == "server" or name.startswith("server_")
                for name in imported_names
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_review.py"
                )
            if (
                module_name == "openplot.server"
                or module_name.startswith("openplot.server_")
                or module_name.startswith("openplot.services")
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_review.py"
                )
            if (
                node.level > 0
                and module_name == ""
                and any(
                    name == "server" or name.startswith("server_")
                    for name in imported_names
                )
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_review.py"
                )
            if node.level > 0 and (
                module_name == "server"
                or module_name.startswith("server_")
                or module_name.startswith("services")
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_review.py"
                )

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


def test_build_plot_mode_review_prompt_uses_live_server_helpers_when_extracted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    uses_extracted_review, _review_path, server_module, functions = (
        _review_module_ready()
    )

    if not uses_extracted_review:
        _assert_pre_extraction_contract(server_module, functions)
        return

    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    calls: list[dict[str, object]] = []

    def fake_append_active_resolved_source_context(lines, current_state, *, heading):
        calls.append(
            {
                "lines": lines,
                "state": current_state,
                "heading": heading,
            }
        )
        lines.append(f"{heading} patched source")

    monkeypatch.setattr(server, "_selected_data_profile", lambda current_state: None)
    monkeypatch.setattr(
        server,
        "_append_active_resolved_source_context",
        fake_append_active_resolved_source_context,
    )

    prompt = server._build_plot_mode_review_prompt(
        state,
        iteration_index=2,
        focus_direction="typography",
    )

    assert len(calls) == 1
    assert calls[0]["state"] is state
    assert calls[0]["heading"] == "Confirmed datasource(s):"
    assert "Autonomous review pass: 2" in prompt
    assert "Current review focus: typography." in prompt
    assert "Confirmed datasource(s): patched source" in prompt


def test_plot_mode_review_module_exists_for_extracted_review_helpers() -> None:
    _uses_extracted_review, review_path, _server_module, _functions = (
        _review_module_ready()
    )
    assert review_path.exists(), (
        "Task 2 requires src/openplot/server_plot_mode_review.py"
    )


@pytest.mark.anyio
async def test_run_plot_mode_autonomous_reviews_uses_live_server_helpers_when_extracted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    uses_extracted_review, _review_path, server_module, functions = (
        _review_module_ready()
    )

    if not uses_extracted_review:
        _assert_pre_extraction_contract(server_module, functions)
        return

    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    state.current_script = "print('draft')\n"
    summary_message = server._create_plot_mode_message(
        state,
        role="assistant",
        content="Initial draft summary",
    )
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        server,
        "_build_plot_mode_review_prompt",
        lambda current_state, *, iteration_index, focus_direction: (
            f"patched review prompt {iteration_index} {focus_direction}"
        ),
    )
    monkeypatch.setattr(
        server,
        "_plot_mode_autonomous_focus_direction",
        lambda pass_index: f"focus {pass_index}",
    )
    monkeypatch.setattr(
        server,
        "_plot_mode_refining_metadata",
        lambda focus_direction: server.PlotModeMessageMetadata(
            kind=server.PlotModeMessageKind.status,
            title="Refining plot",
            items=[focus_direction],
        ),
    )

    async def fake_broadcast_plot_mode_state(current_state) -> None:
        calls.append({"kind": "broadcast_state", "phase": current_state.phase})

    async def fake_run_plot_mode_generation(**kwargs):
        calls.append({"kind": "generation", **kwargs})
        return server.PlotModeGenerationResult(
            assistant_text="Improved draft summary",
            script=state.current_script,
            done_hint=True,
        )

    def fake_apply_plot_mode_result(current_state, *, result):
        calls.append({"kind": "apply", "state": current_state, "result": result})
        return True, None

    async def fake_broadcast_plot_mode_preview(current_state) -> None:
        calls.append({"kind": "preview", "state": current_state})

    monkeypatch.setattr(
        server, "_broadcast_plot_mode_state", fake_broadcast_plot_mode_state
    )
    monkeypatch.setattr(
        server, "_run_plot_mode_generation", fake_run_plot_mode_generation
    )
    monkeypatch.setattr(server, "_apply_plot_mode_result", fake_apply_plot_mode_result)
    monkeypatch.setattr(
        server,
        "_broadcast_plot_mode_preview",
        fake_broadcast_plot_mode_preview,
    )

    await server._run_plot_mode_autonomous_reviews(
        state=state,
        runner="codex",
        model="test-model",
        variant="high",
        summary_message=summary_message,
    )

    generation_calls = [call for call in calls if call["kind"] == "generation"]
    assert len(generation_calls) == 1
    assert generation_calls[0]["state"] is state
    assert generation_calls[0]["runner"] == "codex"
    assert generation_calls[0]["model"] == "test-model"
    assert generation_calls[0]["variant"] == "high"
    assert generation_calls[0]["message"] == "patched review prompt 2 focus 2"

    apply_calls = [call for call in calls if call["kind"] == "apply"]
    assert len(apply_calls) == 1
    assert apply_calls[0]["state"] is state

    preview_calls = [call for call in calls if call["kind"] == "preview"]
    assert preview_calls == [{"kind": "preview", "state": state}]
    assert summary_message.content == "Improved draft summary"
