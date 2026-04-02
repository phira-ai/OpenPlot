import ast
from collections.abc import Iterator
from pathlib import Path
from typing import TypeAlias
from typing import cast

import pytest

import openplot.server as server


PLOT_MODE_PLANNING_HELPERS = (
    "_build_plot_mode_prompt",
    "_build_plot_mode_planning_prompt",
    "_extract_plot_mode_plan_result",
    "_store_plot_mode_plan",
    "_run_plot_mode_generation",
    "_run_plot_mode_planning",
    "_execute_plot_mode_draft",
    "_continue_plot_mode_planning",
    "_default_plot_mode_planning_message",
    "_continue_plot_mode_planning_with_selected_runner",
    "_start_plot_mode_planning_for_profile",
    "_apply_plot_mode_result",
)
PLOT_MODE_PLANNING_HELPER_SIGNATURES = {
    "_build_plot_mode_prompt": [
        ("arg", "state", None),
        ("arg", "user_message", None),
    ],
    "_build_plot_mode_planning_prompt": [
        ("arg", "state", None),
        ("arg", "user_message", None),
    ],
    "_extract_plot_mode_plan_result": [("arg", "text", None)],
    "_store_plot_mode_plan": [
        ("arg", "state", None),
        ("arg", "result", None),
    ],
    "_run_plot_mode_generation": [
        ("kwonly", "state", None),
        ("kwonly", "runner", None),
        ("kwonly", "message", None),
        ("kwonly", "model", None),
        ("kwonly", "variant", None),
        ("kwonly", "assistant_message", None),
    ],
    "_run_plot_mode_planning": [
        ("kwonly", "state", None),
        ("kwonly", "runner", None),
        ("kwonly", "user_message", None),
        ("kwonly", "model", None),
        ("kwonly", "variant", None),
    ],
    "_execute_plot_mode_draft": [
        ("kwonly", "state", None),
        ("kwonly", "runner", None),
        ("kwonly", "model", None),
        ("kwonly", "variant", None),
        ("kwonly", "draft_message", None),
    ],
    "_continue_plot_mode_planning": [
        ("kwonly", "state", None),
        ("kwonly", "runner", None),
        ("kwonly", "model", None),
        ("kwonly", "variant", None),
        ("kwonly", "planning_message", None),
    ],
    "_default_plot_mode_planning_message": [("kwonly", "bundle", None)],
    "_continue_plot_mode_planning_with_selected_runner": [
        ("kwonly", "state", None),
        ("kwonly", "planning_message", None),
    ],
    "_start_plot_mode_planning_for_profile": [
        ("arg", "state", None),
        ("arg", "profile", None),
    ],
    "_apply_plot_mode_result": [
        ("arg", "state", None),
        ("kwonly", "result", None),
    ],
}
ASYNC_PLOT_MODE_PLANNING_HELPERS = {
    "_run_plot_mode_generation",
    "_run_plot_mode_planning",
    "_execute_plot_mode_draft",
    "_continue_plot_mode_planning",
    "_continue_plot_mode_planning_with_selected_runner",
    "_start_plot_mode_planning_for_profile",
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


def _server_uses_extracted_plot_mode_planning(module: ast.Module) -> bool:
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0 and (node.module or "") == "":
                if any(
                    alias.name == "server_plot_mode_planning"
                    and alias.asname == "_server_plot_mode_planning"
                    for alias in node.names
                ):
                    return True
        elif isinstance(node, ast.Name) and node.id == "_server_plot_mode_planning":
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
        "server_plot_mode_planning.py must not cache patchable server helpers at module import time"
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
    assert not _server_uses_extracted_plot_mode_planning(module)
    for helper_name in PLOT_MODE_PLANNING_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"
        assert (
            _parameter_shape(functions[helper_name])
            == PLOT_MODE_PLANNING_HELPER_SIGNATURES[helper_name]
        )


def test_plot_mode_planning_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> (
    None
):
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and '_server_plot_mode_planning' in bound_helpers:
        assert set(PLOT_MODE_PLANNING_HELPERS) <= set(bound_helpers['_server_plot_mode_planning'])
        for helper_name in PLOT_MODE_PLANNING_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_path = Path(server.__file__).resolve()
    planning_path = server_path.with_name("server_plot_mode_planning.py")
    server_module, functions = _read_module_ast(server_path)

    if not _server_uses_extracted_plot_mode_planning(server_module):
        _assert_pre_extraction_contract(server_module, functions)
        return

    assert planning_path.exists(), (
        "server.py references _server_plot_mode_planning but server_plot_mode_planning.py is missing"
    )

    _, planning_functions = _read_module_ast(planning_path)
    extracted_helpers: set[str] = set()

    for helper_name in PLOT_MODE_PLANNING_HELPERS:
        function = functions[helper_name]
        assert (
            _parameter_shape(function)
            == PLOT_MODE_PLANNING_HELPER_SIGNATURES[helper_name]
        )
        assert len(function.body) == 1, (
            f"{helper_name} should stay a one-statement wrapper"
        )

        statement = function.body[0]
        assert isinstance(statement, (ast.Expr, ast.Return)), (
            f"{helper_name} should use a single expression or return statement"
        )

        call = statement.value
        if helper_name in ASYNC_PLOT_MODE_PLANNING_HELPERS:
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
            f"{helper_name} should delegate through _server_plot_mode_planning"
        )
        assert isinstance(call.func.value, ast.Name), (
            f"{helper_name} should reference _server_plot_mode_planning by name"
        )
        assert call.func.value.id == "_server_plot_mode_planning", (
            f"{helper_name} should delegate through _server_plot_mode_planning"
        )
        assert call.func.attr == helper_name, (
            f"{helper_name} should call _server_plot_mode_planning.{helper_name}"
        )

        extracted_helpers.add(helper_name)
        planning_function = planning_functions.get(helper_name)
        assert planning_function is not None, (
            f"Missing extracted helper for {helper_name}"
        )
        assert _parameter_shape(function) == _parameter_shape(
            planning_function, drop_leading_server_module=True
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

    assert extracted_helpers == set(PLOT_MODE_PLANNING_HELPERS), (
        "Expected every helper in the planning inventory to use _server_plot_mode_planning"
    )


def test_plot_mode_planning_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    server_path = Path(server.__file__).resolve()
    planning_path = server_path.with_name("server_plot_mode_planning.py")
    server_module, _ = _read_module_ast(server_path)

    if not _server_uses_extracted_plot_mode_planning(server_module):
        return

    assert planning_path.exists(), (
        "server.py references _server_plot_mode_planning but server_plot_mode_planning.py is missing"
    )

    module, _ = _read_module_ast(planning_path)
    server_aliases: set[str] = set()
    openplot_aliases: set[str] = set()

    for node in module.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openplot":
                    openplot_aliases.add(alias.asname or alias.name)
                if alias.name == "openplot.server":
                    raise AssertionError(
                        "Forbidden import-time binding source in server_plot_mode_planning.py: openplot.server"
                    )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name == "openplot" and any(
                alias.name == "server" or alias.name.startswith("server_")
                for alias in node.names
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_planning.py: from openplot import server"
                )
            if module_name == "openplot.server" or module_name.startswith(
                "openplot.server_"
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_planning.py: direct import from openplot.server"
                )
            if (
                node.level > 0
                and module_name == ""
                and any(
                    alias.name == "server" or alias.name.startswith("server_")
                    for alias in node.names
                )
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_planning.py: from . import server"
                )
            if node.level > 0 and (
                module_name == "server" or module_name.startswith("server_")
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_planning.py: direct relative import from server"
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
async def test_continue_plot_mode_planning_with_selected_runner_uses_live_continue_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    state.selected_runner = "claude"
    state.selected_model = ""
    state.selected_variant = "  high  "
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(server, "_resolve_available_runner", lambda preferred: "codex")
    monkeypatch.setattr(server, "_ensure_runner_is_available", lambda runner: None)
    monkeypatch.setattr(server, "_runner_default_model_id", lambda runner: "test-model")

    async def fake_continue_plot_mode_planning(**kwargs):
        calls.append(kwargs)
        return True, None

    monkeypatch.setattr(
        server,
        "_continue_plot_mode_planning",
        fake_continue_plot_mode_planning,
    )

    ok, error_message = await server._continue_plot_mode_planning_with_selected_runner(
        state=state,
        planning_message="Plan the strongest trend chart.",
    )

    assert (ok, error_message) == (True, None)
    assert state.selected_runner == "codex"
    assert calls == [
        {
            "state": state,
            "runner": "codex",
            "model": "test-model",
            "variant": "high",
            "planning_message": "Plan the strongest trend chart.",
        }
    ]


@pytest.mark.anyio
async def test_start_plot_mode_planning_for_profile_uses_live_continue_selected_runner_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    state.latest_user_goal = "Compare the trends across cohorts."
    profile = server.PlotModeDataProfile(
        id="profile-1",
        file_path="/tmp/profile-1.csv",
        file_name="profile-1.csv",
        source_label="Profile 1",
        source_kind="csv",
        summary="Profile summary",
        columns=["x", "y"],
        preview_rows=[["1", "2"]],
    )
    calls: list[dict[str, object]] = []

    def fake_set_active_resolved_source_for_profile(
        current_state, current_profile
    ) -> None:
        calls.append(
            {
                "kind": "set_active_source",
                "state": current_state,
                "profile": current_profile,
            }
        )

    async def fake_continue_plot_mode_planning_with_selected_runner(**kwargs):
        calls.append({"kind": "continue", **kwargs})
        return True, None

    monkeypatch.setattr(
        server,
        "_set_active_resolved_source_for_profile",
        fake_set_active_resolved_source_for_profile,
    )
    monkeypatch.setattr(
        server,
        "_continue_plot_mode_planning_with_selected_runner",
        fake_continue_plot_mode_planning_with_selected_runner,
    )

    ok, error_message = await server._start_plot_mode_planning_for_profile(
        state, profile
    )

    assert (ok, error_message) == (True, None)
    assert state.selected_data_profile_id == profile.id
    assert calls == [
        {
            "kind": "set_active_source",
            "state": state,
            "profile": profile,
        },
        {
            "kind": "continue",
            "state": state,
            "planning_message": "Compare the trends across cohorts.",
        },
    ]


@pytest.mark.anyio
async def test_execute_plot_mode_draft_uses_live_generation_and_apply_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    calls: list[dict[str, object]] = []
    generation_result = server.PlotModeGenerationResult(assistant_text="Draft complete")

    async def fake_broadcast_plot_mode_state(current_state) -> None:
        calls.append({"kind": "broadcast_state", "phase": current_state.phase})

    async def fake_broadcast_plot_mode_preview(current_state) -> None:
        calls.append({"kind": "broadcast_preview", "state": current_state})

    async def fake_run_plot_mode_generation(**kwargs):
        calls.append({"kind": "generation", **kwargs})
        return generation_result

    def fake_apply_plot_mode_result(current_state, *, result):
        calls.append({"kind": "apply", "state": current_state, "result": result})
        return True, None

    monkeypatch.setattr(
        server, "_broadcast_plot_mode_state", fake_broadcast_plot_mode_state
    )
    monkeypatch.setattr(
        server,
        "_broadcast_plot_mode_preview",
        fake_broadcast_plot_mode_preview,
    )
    monkeypatch.setattr(
        server, "_run_plot_mode_generation", fake_run_plot_mode_generation
    )
    monkeypatch.setattr(server, "_apply_plot_mode_result", fake_apply_plot_mode_result)

    ok, error_message = await server._execute_plot_mode_draft(
        state=state,
        runner="codex",
        model="test-model",
        variant=None,
        draft_message="Draft a figure.",
    )

    assert (ok, error_message) == (True, None)
    assert state.phase == server.PlotModePhase.ready
    assert calls[0] == {
        "kind": "broadcast_state",
        "phase": server.PlotModePhase.drafting,
    }
    assert calls[1]["kind"] == "generation"
    assert calls[1]["state"] is state
    assert calls[1]["runner"] == "codex"
    assert calls[1]["message"] == "Draft a figure."
    assert calls[1]["model"] == "test-model"
    assert calls[1]["variant"] is None
    assistant_message = cast(server.PlotModeChatMessage, calls[1]["assistant_message"])
    assert assistant_message.role == "assistant"
    assert assistant_message.content == ""
    assert calls[2] == {"kind": "apply", "state": state, "result": generation_result}
    assert calls[3] == {"kind": "broadcast_preview", "state": state}
    assert calls[4] == {
        "kind": "broadcast_state",
        "phase": server.PlotModePhase.ready,
    }


@pytest.mark.anyio
async def test_run_plot_mode_planning_uses_live_runner_prompt_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    calls: list[dict[str, object]] = []
    assistant_text = (
        "OPENPLOT_PLAN_BEGIN\n"
        '{"summary": "Ready to plot", "plot_type": "line", "data_actions": [], '
        '"plan_outline": ["Inspect the trend"], "ready_to_plot": true}\n'
        "OPENPLOT_PLAN_END"
    )

    monkeypatch.setattr(
        server,
        "_build_plot_mode_planning_prompt",
        lambda current_state, message: "patched planning prompt",
    )

    async def fake_run_plot_mode_runner_prompt(**kwargs):
        calls.append(kwargs)
        return assistant_text, None

    monkeypatch.setattr(
        server,
        "_run_plot_mode_runner_prompt",
        fake_run_plot_mode_runner_prompt,
    )

    result = await server._run_plot_mode_planning(
        state=state,
        runner="codex",
        user_message="Plan the figure.",
        model="test-model",
        variant="fast",
    )

    assert calls == [
        {
            "state": state,
            "runner": "codex",
            "prompt": "patched planning prompt",
            "model": "test-model",
            "variant": "fast",
        }
    ]
    assert result.summary == "Ready to plot"
    assert result.plot_type == "line"
    assert result.plan_outline == ["Inspect the trend"]
    assert result.ready_to_plot is True
    assert result.assistant_text == assistant_text


@pytest.mark.anyio
async def test_run_plot_mode_generation_uses_live_script_result_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    calls: list[str] = []

    monkeypatch.setattr(
        server,
        "_build_plot_mode_prompt",
        lambda current_state, message: "patched generation prompt",
    )

    async def fake_run_plot_mode_runner_prompt(**kwargs):
        assert kwargs["prompt"] == "patched generation prompt"
        return "ignored runner text", None

    def fake_extract_plot_mode_script_result(text: str):
        calls.append(text)
        assert text == "ignored runner text"
        return "Patched summary", "print('patched')\n", True

    def fake_execute_script(*args, **kwargs):
        del args, kwargs
        return server.ExecutionResult(
            success=True,
            plot_path=str(tmp_path / "plot.png"),
            plot_type="raster",
        )

    monkeypatch.setattr(
        server,
        "_run_plot_mode_runner_prompt",
        fake_run_plot_mode_runner_prompt,
    )
    monkeypatch.setattr(
        server,
        "_extract_plot_mode_script_result",
        fake_extract_plot_mode_script_result,
    )
    monkeypatch.setattr(server, "execute_script", fake_execute_script)

    result = await server._run_plot_mode_generation(
        state=state,
        runner="codex",
        message="Draft a figure.",
        model="test-model",
        variant="fast",
        assistant_message=server.PlotModeChatMessage(role="assistant", content=""),
    )

    assert calls == ["ignored runner text"]
    assert result.assistant_text == "Patched summary"
    assert result.script == "print('patched')\n"
    assert result.done_hint is True
    assert result.execution_result is not None
    assert result.execution_result.plot_path == str(tmp_path / "plot.png")
