import ast
from collections.abc import Iterator
from pathlib import Path
from typing import TypeAlias

import pytest

import openplot.server as server


PLOT_MODE_MESSAGE_HELPERS = (
    "_append_plot_mode_message",
    "_create_plot_mode_message",
    "_remove_plot_mode_message",
    "_set_plot_mode_message_content",
    "_set_plot_mode_message_metadata",
    "_append_plot_mode_activity",
    "_plot_mode_refining_metadata",
    "_append_plot_mode_table_preview",
    "_append_plot_mode_question_set",
    "_mark_question_set_answered",
    "_answer_map_for_question_set",
    "_apply_answers_to_question_set",
    "_first_answer_for_question_set",
    "_question_set_answer_summary",
    "_append_profile_preview_card",
    "_profile_supports_preview_confirmation",
    "_queue_data_preview_confirmation",
    "_append_profile_integrity_activity",
    "_present_profile_for_confirmation",
    "_present_tabular_range_proposal",
    "_queue_tabular_range_confirmation",
    "_apply_tabular_range_proposal",
    "_populate_plot_mode_data_messages",
    "_queue_plot_mode_bundle_kickoff_question",
    "_queue_plot_mode_plan_approval_question",
    "_queue_plot_mode_continue_planning_question",
    "_present_plot_mode_plan_result",
)
PLOT_MODE_MESSAGE_HELPER_SIGNATURES = {
    "_append_plot_mode_message": [
        ("arg", "state", None),
        ("kwonly", "role", None),
        ("kwonly", "content", None),
        ("kwonly", "metadata", "Constant(value=None)"),
    ],
    "_create_plot_mode_message": [
        ("arg", "state", None),
        ("kwonly", "role", None),
        ("kwonly", "content", "Constant(value='')"),
        ("kwonly", "metadata", "Constant(value=None)"),
    ],
    "_remove_plot_mode_message": [
        ("arg", "state", None),
        ("arg", "message_id", None),
    ],
    "_set_plot_mode_message_content": [
        ("arg", "state", None),
        ("arg", "message", None),
        ("arg", "content", None),
        ("kwonly", "final", "Constant(value=False)"),
    ],
    "_set_plot_mode_message_metadata": [
        ("arg", "state", None),
        ("arg", "message", None),
        ("arg", "metadata", None),
    ],
    "_append_plot_mode_activity": [
        ("arg", "state", None),
        ("kwonly", "title", None),
        ("kwonly", "items", None),
    ],
    "_plot_mode_refining_metadata": [
        ("arg", "focus_direction", None),
    ],
    "_append_plot_mode_table_preview": [
        ("arg", "state", None),
        ("kwonly", "source_label", None),
        ("kwonly", "caption", None),
        ("kwonly", "columns", None),
        ("kwonly", "rows", None),
    ],
    "_append_plot_mode_question_set": [
        ("arg", "state", None),
        ("kwonly", "question_set", None),
        ("kwonly", "lead_content", None),
    ],
    "_mark_question_set_answered": [
        ("arg", "state", None),
        ("arg", "question_set_id", None),
        ("kwonly", "answered_questions", None),
    ],
    "_answer_map_for_question_set": [
        ("arg", "body", None),
    ],
    "_apply_answers_to_question_set": [
        ("arg", "question_set", None),
        ("arg", "answer_map", None),
    ],
    "_first_answer_for_question_set": [
        ("arg", "answered_questions", None),
    ],
    "_question_set_answer_summary": [
        ("arg", "answered_questions", None),
    ],
    "_append_profile_preview_card": [
        ("arg", "state", None),
        ("arg", "profile", None),
    ],
    "_profile_supports_preview_confirmation": [
        ("arg", "profile", None),
    ],
    "_queue_data_preview_confirmation": [
        ("arg", "state", None),
        ("arg", "profile", None),
    ],
    "_append_profile_integrity_activity": [
        ("arg", "state", None),
        ("arg", "profile", None),
    ],
    "_present_profile_for_confirmation": [
        ("arg", "state", None),
        ("arg", "profile", None),
    ],
    "_present_tabular_range_proposal": [
        ("arg", "state", None),
        ("arg", "profile", None),
        ("kwonly", "rationale", None),
    ],
    "_queue_tabular_range_confirmation": [
        ("arg", "state", None),
        ("arg", "profile", None),
        ("kwonly", "rationale", None),
    ],
    "_apply_tabular_range_proposal": [
        ("arg", "state", None),
        ("arg", "selector", None),
        ("kwonly", "selected_regions", None),
        ("kwonly", "instruction", None),
        ("kwonly", "activity_title", None),
    ],
    "_populate_plot_mode_data_messages": [
        ("arg", "state", None),
    ],
    "_queue_plot_mode_bundle_kickoff_question": [
        ("arg", "state", None),
    ],
    "_queue_plot_mode_plan_approval_question": [
        ("arg", "state", None),
    ],
    "_queue_plot_mode_continue_planning_question": [
        ("arg", "state", None),
        ("arg", "prompt", None),
    ],
    "_present_plot_mode_plan_result": [
        ("arg", "state", None),
        ("arg", "result", None),
    ],
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


def _server_uses_extracted_plot_mode_messages(module: ast.Module) -> bool:
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0 and (node.module or "") == "":
                if any(
                    alias.name == "server_plot_mode_messages"
                    and alias.asname == "_server_plot_mode_messages"
                    for alias in node.names
                ):
                    return True
        elif isinstance(node, ast.Name) and node.id == "_server_plot_mode_messages":
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
        "server_plot_mode_messages.py must not cache patchable server helpers at module import time"
    )


def _question_set() -> server.PlotModeQuestionSet:
    return server.PlotModeQuestionSet(
        purpose="continue_plot_planning",
        title="Continue planning",
        questions=[
            server.PlotModeQuestionItem(
                prompt="Keep going?",
                options=[
                    server.PlotModeQuestionOption(
                        id="continue_planning",
                        label="Continue",
                    )
                ],
            )
        ],
    )


def _plot_mode_file(*, file_id: str = "file-1") -> server.PlotModeFile:
    return server.PlotModeFile(
        id=file_id,
        name="data.csv",
        stored_path=f"/tmp/{file_id}.csv",
        size_bytes=128,
        content_type="text/csv",
    )


def _data_profile(
    *,
    profile_id: str = "profile-1",
    source_kind: str = "csv",
    source_file_id: str = "file-1",
) -> server.PlotModeDataProfile:
    return server.PlotModeDataProfile(
        id=profile_id,
        file_path=f"/tmp/{profile_id}.csv",
        file_name=f"{profile_id}.csv",
        source_label=f"Source {profile_id}",
        source_kind=source_kind,
        summary="Profile summary",
        columns=["x", "y"],
        preview_rows=[["1", "2"]],
        source_file_id=source_file_id,
    )


def _selection_region(
    *, sheet_id: str = "sheet-1"
) -> server.PlotModeTabularSelectionRegion:
    return server.PlotModeTabularSelectionRegion(
        sheet_id=sheet_id,
        sheet_name="Sheet1",
        bounds=server.PlotModeSheetBounds(
            row_start=1,
            row_end=4,
            col_start=1,
            col_end=2,
        ),
    )


def _tabular_selector(*, file_id: str = "file-1") -> server.PlotModeTabularSelector:
    return server.PlotModeTabularSelector(
        file_id=file_id,
        file_path=f"/tmp/{file_id}.xlsx",
        file_name="book.xlsx",
        source_kind="excel",
    )


def _assert_pre_extraction_contract(
    module: ast.Module, functions: dict[str, FunctionNode]
) -> None:
    assert not _server_uses_extracted_plot_mode_messages(module)
    for helper_name in PLOT_MODE_MESSAGE_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"
        assert (
            _parameter_shape(functions[helper_name])
            == PLOT_MODE_MESSAGE_HELPER_SIGNATURES[helper_name]
        )


def test_patchable_server_helper_guard_catches_non_inventory_aliases() -> None:
    server_alias_tree = ast.parse("cached = server._touch_plot_mode")
    assert _contains_patchable_server_helper_reference(
        server_alias_tree,
        server_aliases={"server"},
        openplot_aliases=set(),
    )

    openplot_alias_tree = ast.parse(
        "cached = openplot.server._append_plot_mode_message"
    )
    assert _contains_patchable_server_helper_reference(
        openplot_alias_tree,
        server_aliases=set(),
        openplot_aliases={"openplot"},
    )


def test_plot_mode_message_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> (
    None
):
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if (
        isinstance(bound_helpers, dict)
        and "_server_plot_mode_messages" in bound_helpers
    ):
        assert set(PLOT_MODE_MESSAGE_HELPERS) <= set(
            bound_helpers["_server_plot_mode_messages"]
        )
        for helper_name in PLOT_MODE_MESSAGE_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_path = Path(server.__file__).resolve()
    messages_path = server_path.with_name("server_plot_mode_messages.py")
    server_module, functions = _read_module_ast(server_path)

    if not _server_uses_extracted_plot_mode_messages(server_module):
        _assert_pre_extraction_contract(server_module, functions)
        return

    assert messages_path.exists(), (
        "server.py references _server_plot_mode_messages but server_plot_mode_messages.py is missing"
    )

    _, message_functions = _read_module_ast(messages_path)
    extracted_helpers: set[str] = set()

    for helper_name in PLOT_MODE_MESSAGE_HELPERS:
        function = functions[helper_name]
        assert (
            _parameter_shape(function)
            == PLOT_MODE_MESSAGE_HELPER_SIGNATURES[helper_name]
        )

        assert len(function.body) == 1, (
            f"{helper_name} should stay a one-statement wrapper"
        )

        statement = function.body[0]
        assert isinstance(statement, (ast.Expr, ast.Return)), (
            f"{helper_name} should use a single expression or return statement"
        )

        call = statement.value
        if isinstance(function, ast.AsyncFunctionDef):
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
            f"{helper_name} should delegate through _server_plot_mode_messages"
        )
        assert isinstance(call.func.value, ast.Name), (
            f"{helper_name} should reference _server_plot_mode_messages by name"
        )
        assert call.func.value.id == "_server_plot_mode_messages", (
            f"{helper_name} should delegate through _server_plot_mode_messages"
        )
        assert call.func.attr == helper_name, (
            f"{helper_name} should call _server_plot_mode_messages.{helper_name}"
        )

        extracted_helpers.add(helper_name)
        message_function = message_functions.get(helper_name)
        assert message_function is not None, (
            f"Missing extracted helper for {helper_name}"
        )
        assert _parameter_shape(function) == _parameter_shape(
            message_function, drop_leading_server_module=True
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

    assert extracted_helpers == set(PLOT_MODE_MESSAGE_HELPERS), (
        "Expected every helper in the message inventory to use _server_plot_mode_messages"
    )


def test_plot_mode_message_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    server_path = Path(server.__file__).resolve()
    messages_path = server_path.with_name("server_plot_mode_messages.py")
    server_module, _ = _read_module_ast(server_path)

    if not _server_uses_extracted_plot_mode_messages(server_module):
        return

    assert messages_path.exists(), (
        "server.py references _server_plot_mode_messages but server_plot_mode_messages.py is missing"
    )

    module, _ = _read_module_ast(messages_path)
    server_aliases: set[str] = set()
    openplot_aliases: set[str] = set()

    for node in module.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openplot":
                    openplot_aliases.add(alias.asname or alias.name)
                if alias.name == "openplot.server":
                    raise AssertionError(
                        "Forbidden import-time binding source in server_plot_mode_messages.py: openplot.server"
                    )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name == "openplot" and any(
                alias.name == "server" for alias in node.names
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_messages.py: from openplot import server"
                )
            if module_name == "openplot.server":
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_messages.py: direct import from openplot.server"
                )
            if (
                node.level > 0
                and module_name == ""
                and any(alias.name == "server" for alias in node.names)
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_messages.py: from . import server"
                )
            if node.level > 0 and module_name == "server":
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_messages.py: direct relative import from server"
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


def test_append_plot_mode_message_uses_live_touch_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    calls: list[str] = []

    monkeypatch.setattr(
        server,
        "_touch_plot_mode",
        lambda current: calls.append(current.id),
    )

    server._append_plot_mode_message(state, role="assistant", content="  Draft ready  ")

    assert [message.content for message in state.messages] == ["Draft ready"]
    assert calls == [state.id]


def test_append_plot_mode_question_set_uses_live_append_message_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    question_set = _question_set()
    calls: list[dict[str, object]] = []

    def fake_append_message(current_state, *, role, content, metadata=None) -> None:
        calls.append(
            {
                "state": current_state,
                "role": role,
                "content": content,
                "metadata": metadata,
            }
        )

    monkeypatch.setattr(server, "_append_plot_mode_message", fake_append_message)

    server._append_plot_mode_question_set(
        state,
        question_set=question_set,
        lead_content="Need one more answer.",
    )

    assert state.pending_question_set is question_set
    assert len(calls) == 1
    assert calls[0]["state"] is state
    assert calls[0]["role"] == "assistant"
    assert calls[0]["content"] == "Need one more answer."
    metadata = calls[0]["metadata"]
    assert isinstance(metadata, server.PlotModeMessageMetadata)
    assert metadata.kind == server.PlotModeMessageKind.question
    assert metadata.question_set_id == question_set.id
    assert metadata.questions == question_set.questions


def test_mark_question_set_answered_uses_live_touch_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    original_question_set = _question_set()
    other_question_set = _question_set()
    state.messages = [
        server.PlotModeChatMessage(
            role="assistant",
            content="Other question",
            metadata=server.PlotModeMessageMetadata(
                kind=server.PlotModeMessageKind.question,
                question_set_id=other_question_set.id,
                questions=other_question_set.questions,
            ),
        ),
        server.PlotModeChatMessage(
            role="assistant",
            content="Target question",
            metadata=server.PlotModeMessageMetadata(
                kind=server.PlotModeMessageKind.question,
                question_set_id=original_question_set.id,
                questions=original_question_set.questions,
            ),
        ),
    ]
    answered_questions = [
        original_question_set.questions[0].model_copy(
            update={
                "answered": True,
                "selected_option_ids": ["continue_planning"],
            }
        )
    ]
    calls: list[str] = []

    monkeypatch.setattr(
        server,
        "_touch_plot_mode",
        lambda current: calls.append(current.id),
    )

    server._mark_question_set_answered(
        state,
        original_question_set.id,
        answered_questions=answered_questions,
    )

    assert state.messages[0].metadata is not None
    assert state.messages[0].metadata.questions == other_question_set.questions
    assert state.messages[1].metadata is not None
    assert state.messages[1].metadata.questions == answered_questions
    assert calls == [state.id]


def test_populate_plot_mode_data_messages_uses_live_profile_and_bundle_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    state.files = [_plot_mode_file()]
    state.messages = [server.PlotModeChatMessage(role="assistant", content="stale")]
    state.latest_user_goal = "goal"
    state.latest_plan_summary = "summary"
    state.latest_plan_outline = ["outline"]
    state.latest_plan_plot_type = "line"
    state.latest_plan_actions = ["action"]
    state.current_script = "print('draft')"
    state.current_script_path = "/tmp/draft.py"
    state.current_plot = "/tmp/draft.svg"
    state.plot_type = "svg"
    state.last_error = "boom"
    calls: list[object] = []
    input_bundle = server.PlotModeInputBundle(label="Patched bundle")

    def fake_profile_selected_data_files(files):
        calls.append(("profile", tuple(file.id for file in files)))
        return [], [], None

    def fake_build_plot_mode_input_bundle(files):
        calls.append(("input_bundle", tuple(file.id for file in files)))
        return input_bundle

    def fake_build_plot_mode_resolved_sources(files, profiles, selector):
        calls.append(
            (
                "resolved_sources",
                tuple(file.id for file in files),
                tuple(profile.id for profile in profiles),
                selector,
            )
        )
        return [], []

    monkeypatch.setattr(
        server, "_profile_selected_data_files", fake_profile_selected_data_files
    )
    monkeypatch.setattr(
        server, "_build_plot_mode_input_bundle", fake_build_plot_mode_input_bundle
    )
    monkeypatch.setattr(
        server,
        "_build_plot_mode_resolved_sources",
        fake_build_plot_mode_resolved_sources,
    )

    server._populate_plot_mode_data_messages(state)

    assert calls == [
        ("profile", ("file-1",)),
        ("input_bundle", ("file-1",)),
        ("resolved_sources", ("file-1",), (), None),
    ]
    assert state.input_bundle is input_bundle
    assert state.messages == []
    assert state.phase == server.PlotModePhase.awaiting_prompt
    assert state.current_script is None
    assert state.current_script_path is None
    assert state.current_plot is None
    assert state.plot_type is None
    assert state.last_error is None
    assert state.latest_user_goal == ""
    assert state.latest_plan_summary == ""
    assert state.latest_plan_outline == []
    assert state.latest_plan_plot_type == ""
    assert state.latest_plan_actions == []


def test_present_profile_for_confirmation_uses_live_append_message_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    profile = _data_profile(source_kind="file")
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        server,
        "_set_active_resolved_source_for_profile",
        lambda current_state, current_profile: calls.append(
            {
                "kind": "active_source",
                "state": current_state,
                "profile": current_profile,
            }
        ),
    )

    def fake_append_message(current_state, *, role, content, metadata=None) -> None:
        calls.append(
            {
                "kind": "message",
                "state": current_state,
                "role": role,
                "content": content,
                "metadata": metadata,
            }
        )

    monkeypatch.setattr(server, "_append_plot_mode_message", fake_append_message)

    server._present_profile_for_confirmation(state, profile)

    assert state.pending_question_set is None
    assert state.selected_data_profile_id == profile.id
    assert state.phase == server.PlotModePhase.awaiting_prompt
    assert calls[0] == {
        "kind": "active_source",
        "state": state,
        "profile": profile,
    }
    assert calls[1]["kind"] == "message"
    assert calls[1]["state"] is state
    assert calls[1]["role"] == "assistant"
    assert isinstance(calls[1]["content"], str)
    assert profile.source_label in calls[1]["content"]
    assert calls[1]["metadata"] is None


@pytest.mark.anyio
async def test_apply_tabular_range_proposal_uses_live_proposal_and_presentation_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    selector = _tabular_selector()
    selected_regions = [_selection_region()]
    profile = _data_profile(source_file_id=selector.file_id)
    proposal = server.PlotModeTabularProposalResult(
        profile=profile,
        rationale="Use the highlighted range.",
    )
    calls: list[dict[str, object]] = []

    async def fake_propose_grouped_profile_from_selector_regions(
        *, state, selector, selected_regions, instruction
    ):
        calls.append(
            {
                "kind": "propose",
                "state": state,
                "selector": selector,
                "selected_regions": list(selected_regions),
                "instruction": instruction,
            }
        )
        return proposal

    monkeypatch.setattr(
        server,
        "_propose_grouped_profile_from_selector_regions",
        fake_propose_grouped_profile_from_selector_regions,
    )
    monkeypatch.setattr(
        server,
        "_append_plot_mode_activity",
        lambda current_state, *, title, items: calls.append(
            {
                "kind": "activity",
                "state": current_state,
                "title": title,
                "items": items,
            }
        ),
    )
    monkeypatch.setattr(
        server,
        "_present_tabular_range_proposal",
        lambda current_state, current_profile, *, rationale: calls.append(
            {
                "kind": "present",
                "state": current_state,
                "profile": current_profile,
                "rationale": rationale,
            }
        ),
    )

    await server._apply_tabular_range_proposal(
        state,
        selector,
        selected_regions=selected_regions,
        instruction="Prefer the top table.",
        activity_title="Selecting range",
    )

    assert calls[0] == {
        "kind": "propose",
        "state": state,
        "selector": selector,
        "selected_regions": selected_regions,
        "instruction": "Prefer the top table.",
    }
    assert calls[1]["kind"] == "activity"
    assert calls[1]["state"] is state
    assert calls[1]["title"] == "Selecting range"
    assert calls[2] == {
        "kind": "present",
        "state": state,
        "profile": profile,
        "rationale": "Use the highlighted range.",
    }
    assert selector.selected_sheet_id == selected_regions[0].sheet_id
    assert selector.selected_regions == selected_regions
    assert selector.inferred_profile_id == profile.id
    assert selector.requires_user_hint is False
    assert state.data_profiles == [profile]
    assert state.phase == server.PlotModePhase.awaiting_data_choice


def test_present_plot_mode_plan_result_uses_live_plan_storage_and_follow_up_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    result = server.PlotModePlanResult(
        summary="  Plan summary  ",
        ready_to_plot=True,
    )
    calls: list[dict[str, object]] = []

    def fake_store_plot_mode_plan(current_state, current_result) -> None:
        calls.append(
            {
                "kind": "store",
                "state": current_state,
                "result": current_result,
            }
        )
        current_state.latest_plan_summary = "stored"
        current_state.latest_plan_plot_type = ""
        current_state.latest_plan_actions = []
        current_state.latest_plan_outline = []

    def fake_append_message(current_state, *, role, content, metadata=None) -> None:
        calls.append(
            {
                "kind": "message",
                "state": current_state,
                "role": role,
                "content": content,
                "metadata": metadata,
            }
        )

    monkeypatch.setattr(server, "_store_plot_mode_plan", fake_store_plot_mode_plan)
    monkeypatch.setattr(server, "_append_plot_mode_message", fake_append_message)
    monkeypatch.setattr(
        server,
        "_queue_plot_mode_plan_approval_question",
        lambda current_state: calls.append(
            {
                "kind": "approval",
                "state": current_state,
            }
        ),
    )

    server._present_plot_mode_plan_result(state, result)

    assert calls[0] == {
        "kind": "store",
        "state": state,
        "result": result,
    }
    assert calls[1]["kind"] == "message"
    assert calls[1]["state"] is state
    assert calls[1]["role"] == "assistant"
    assert calls[1]["content"] == "Plan summary"
    assert calls[1]["metadata"] is None
    assert calls[2] == {
        "kind": "approval",
        "state": state,
    }
    assert state.phase == server.PlotModePhase.awaiting_plan_approval


def test_present_plot_mode_plan_result_uses_live_continue_planning_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = server.init_plot_mode_session(workspace_dir=tmp_path / "workspace")
    result = server.PlotModePlanResult(
        summary="Need more input",
        clarification_question="Which metric matters most?",
        ready_to_plot=False,
    )
    calls: list[dict[str, object]] = []

    def fake_store_plot_mode_plan(current_state, current_result) -> None:
        calls.append(
            {
                "kind": "store",
                "state": current_state,
                "result": current_result,
            }
        )
        current_state.latest_plan_summary = current_result.summary.strip()
        current_state.latest_plan_plot_type = ""
        current_state.latest_plan_actions = []
        current_state.latest_plan_outline = []

    def fake_append_message(current_state, *, role, content, metadata=None) -> None:
        calls.append(
            {
                "kind": "message",
                "state": current_state,
                "role": role,
                "content": content,
                "metadata": metadata,
            }
        )

    monkeypatch.setattr(server, "_store_plot_mode_plan", fake_store_plot_mode_plan)
    monkeypatch.setattr(server, "_append_plot_mode_message", fake_append_message)
    monkeypatch.setattr(
        server,
        "_queue_plot_mode_continue_planning_question",
        lambda current_state, prompt: calls.append(
            {
                "kind": "continue",
                "state": current_state,
                "prompt": prompt,
            }
        ),
    )

    server._present_plot_mode_plan_result(state, result)

    assert calls[0] == {
        "kind": "store",
        "state": state,
        "result": result,
    }
    assert calls[1]["kind"] == "message"
    assert calls[1]["state"] is state
    assert calls[1]["role"] == "assistant"
    assert calls[1]["content"] == "Need more input"
    assert calls[2] == {
        "kind": "continue",
        "state": state,
        "prompt": "Which metric matters most?",
    }
    assert state.phase == server.PlotModePhase.awaiting_data_choice
