import ast
import importlib
from pathlib import Path
from typing import Any, Sequence, TypeAlias

import pytest

import openplot.server as server


EXTRACTED_PLOT_MODE_INFERENCE_HELPERS = (
    "_build_tabular_range_inference_prompt",
    "_extract_plot_mode_tabular_range_result",
    "_propose_profile_from_selector_hint",
    "_propose_grouped_profile_from_selector_regions",
    "_build_plot_mode_input_bundle",
    "_build_resolved_source_for_profile",
    "_build_multi_file_collection_source",
    "_build_mixed_bundle_source",
    "_build_plot_mode_resolved_sources",
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


def _inference_path() -> Path:
    return _server_path().with_name("server_plot_mode_inference.py")


def _server_uses_extracted_plot_mode_inference(module: ast.Module) -> bool:
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0 and (node.module or "") == "":
                if any(
                    alias.name == "server_plot_mode_inference"
                    and alias.asname == "_server_plot_mode_inference"
                    for alias in node.names
                ):
                    return True
        elif isinstance(node, ast.Name) and node.id == "_server_plot_mode_inference":
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
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "getattr"
            and len(child.args) >= 2
        ):
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
        "server_plot_mode_inference.py must not cache patchable server helpers at module import time"
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
    expected_signatures = {
        "_build_tabular_range_inference_prompt": {
            "posonlyargs": [],
            "args": [],
            "vararg": None,
            "kwonlyargs": ["file_name", "sheet", "hint_bounds", "instruction"],
            "kwarg": None,
            "defaults": [],
            "kw_defaults": [None, None, None, None],
        },
        "_extract_plot_mode_tabular_range_result": {
            "posonlyargs": [],
            "args": ["text"],
            "vararg": None,
            "kwonlyargs": ["max_row_index", "max_col_index"],
            "kwarg": None,
            "defaults": [],
            "kw_defaults": [None, None],
        },
        "_propose_profile_from_selector_hint": {
            "posonlyargs": [],
            "args": [],
            "vararg": None,
            "kwonlyargs": [
                "state",
                "selector",
                "sheet_id",
                "hint_bounds",
                "instruction",
            ],
            "kwarg": None,
            "defaults": [],
            "kw_defaults": [None, None, None, None, None],
        },
        "_propose_grouped_profile_from_selector_regions": {
            "posonlyargs": [],
            "args": [],
            "vararg": None,
            "kwonlyargs": ["state", "selector", "selected_regions", "instruction"],
            "kwarg": None,
            "defaults": [],
            "kw_defaults": [None, None, None, None],
        },
        "_build_plot_mode_input_bundle": {
            "posonlyargs": [],
            "args": ["files"],
            "vararg": None,
            "kwonlyargs": [],
            "kwarg": None,
            "defaults": [],
            "kw_defaults": [],
        },
        "_build_resolved_source_for_profile": {
            "posonlyargs": [],
            "args": ["profile"],
            "vararg": None,
            "kwonlyargs": [],
            "kwarg": None,
            "defaults": [],
            "kw_defaults": [],
        },
        "_build_multi_file_collection_source": {
            "posonlyargs": [],
            "args": ["files", "profiles"],
            "vararg": None,
            "kwonlyargs": [],
            "kwarg": None,
            "defaults": [],
            "kw_defaults": [],
        },
        "_build_mixed_bundle_source": {
            "posonlyargs": [],
            "args": ["files", "profiles"],
            "vararg": None,
            "kwonlyargs": [],
            "kwarg": None,
            "defaults": [],
            "kw_defaults": [],
        },
        "_build_plot_mode_resolved_sources": {
            "posonlyargs": [],
            "args": ["files", "profiles", "selector"],
            "vararg": None,
            "kwonlyargs": [],
            "kwarg": None,
            "defaults": [],
            "kw_defaults": [],
        },
    }

    for helper_name in EXTRACTED_PLOT_MODE_INFERENCE_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"
        assert (
            _signature_shape(functions[helper_name]) == expected_signatures[helper_name]
        )

    for helper_name in (
        "_propose_profile_from_selector_hint",
        "_build_plot_mode_resolved_sources",
        "_propose_grouped_profile_from_selector_regions",
    ):
        assert len(functions[helper_name].body) > 1, (
            f"Pre-extraction contract expects {helper_name} to still be implemented in server.py"
        )


def _load_inference_module_if_wired() -> Any | None:
    server_module, functions = _read_module_ast(_server_path())
    if not _server_uses_extracted_plot_mode_inference(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _inference_path().exists(), (
            "server_plot_mode_inference.py exists before server.py wires the inference seam"
        )
        return None
    assert _inference_path().exists(), (
        "server.py references _server_plot_mode_inference but server_plot_mode_inference.py is missing"
    )
    return importlib.import_module("openplot.server_plot_mode_inference")


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


def _plot_mode_file(
    *,
    file_id: str = "file-1",
    name: str = "data.csv",
    suffix: str = ".csv",
) -> server.PlotModeFile:
    return server.PlotModeFile(
        id=file_id,
        name=name,
        stored_path=f"/tmp/{file_id}{suffix}",
        size_bytes=128,
        content_type="text/csv",
    )


def _data_profile(
    *,
    profile_id: str = "profile-1",
    source_kind: str = "csv",
    source_file_id: str = "file-1",
    columns: list[str] | None = None,
) -> server.PlotModeDataProfile:
    return server.PlotModeDataProfile(
        id=profile_id,
        file_path=f"/tmp/{profile_id}.csv",
        file_name=f"{profile_id}.csv",
        source_label=f"Source {profile_id}",
        source_kind=source_kind,
        summary=f"Summary for {profile_id}",
        columns=columns or ["x", "y"],
        preview_rows=[["1", "2"]],
        source_file_id=source_file_id,
    )


def _resolved_source(
    *,
    source_id: str = "resolved-1",
    kind: str = "single_file",
) -> server.PlotModeResolvedDataSource:
    return server.PlotModeResolvedDataSource(
        id=source_id,
        kind=kind,
        label=f"Resolved {source_id}",
        summary=f"Summary for {source_id}",
        file_ids=["file-1"],
        file_paths=["/tmp/file-1.csv"],
        file_count=1,
        profile_ids=["profile-1"],
        columns=["x", "y"],
    )


def _sheet_bounds(
    *,
    row_start: int = 1,
    row_end: int = 3,
    col_start: int = 0,
    col_end: int = 1,
) -> server.PlotModeSheetBounds:
    return server.PlotModeSheetBounds(
        row_start=row_start,
        row_end=row_end,
        col_start=col_start,
        col_end=col_end,
    )


def _tabular_selector(*, file_id: str = "file-1") -> server.PlotModeTabularSelector:
    return server.PlotModeTabularSelector(
        file_id=file_id,
        file_path=f"/tmp/{file_id}.xlsx",
        file_name="book.xlsx",
        source_kind="excel",
        sheets=[
            server.PlotModeSheetPreview(
                id="sheet-1",
                name="Sheet1",
                total_rows=6,
                total_cols=3,
                preview_rows=[
                    ["name", "value", "flag"],
                    ["a", "1", "yes"],
                    ["b", "2", "no"],
                    ["c", "3", "yes"],
                ],
            ),
            server.PlotModeSheetPreview(
                id="sheet-2",
                name="Sheet2",
                total_rows=4,
                total_cols=2,
                preview_rows=[["x", "y"], ["1", "2"]],
            ),
        ],
    )


def _selection_region(
    *,
    sheet_id: str = "sheet-1",
    sheet_name: str = "Sheet1",
    bounds: server.PlotModeSheetBounds | None = None,
) -> server.PlotModeTabularSelectionRegion:
    return server.PlotModeTabularSelectionRegion(
        sheet_id=sheet_id,
        sheet_name=sheet_name,
        bounds=bounds or _sheet_bounds(),
    )


def _state(tmp_path: Path) -> server.PlotModeState:
    return server.PlotModeState(
        workspace_dir=str(tmp_path / "workspace"),
        selected_runner="opencode",
        selected_model="patched-model",
    )


def test_patchable_server_helper_guard_catches_inference_aliases() -> None:
    server_alias_tree = ast.parse("cached = server._build_mixed_bundle_source")
    assert _contains_patchable_server_helper_reference(
        server_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    server_module_alias_tree = ast.parse(
        "cached = server_module._extract_plot_mode_tabular_range_result"
    )
    assert _contains_patchable_server_helper_reference(
        server_module_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases=set(),
    )

    openplot_alias_tree = ast.parse(
        "cached = openplot.server._propose_profile_from_selector_hint"
    )
    assert _contains_patchable_server_helper_reference(
        openplot_alias_tree,
        server_aliases={"server", "server_module"},
        openplot_aliases={"openplot"},
    )


def test_patchable_server_helper_guard_catches_nested_aliases() -> None:
    try_body_alias_tree = ast.parse(
        "try:\n"
        "    cached = getattr(server_module, '_build_resolved_source_for_profile')\n"
        "except Exception:\n"
        "    pass\n"
    )

    with pytest.raises(AssertionError):
        _assert_no_patchable_server_helper_references_in_statement(
            try_body_alias_tree.body[0],
            server_aliases={"server", "server_module"},
            openplot_aliases=set(),
        )


def test_plot_mode_inference_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> (
    None
):
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and '_server_plot_mode_inference' in bound_helpers:
        assert set(EXTRACTED_PLOT_MODE_INFERENCE_HELPERS) <= set(bound_helpers['_server_plot_mode_inference'])
        for helper_name in EXTRACTED_PLOT_MODE_INFERENCE_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_module, functions = _read_module_ast(_server_path())

    if not _server_uses_extracted_plot_mode_inference(server_module):
        _assert_pre_extraction_contract(functions)
        assert not _inference_path().exists()
        return

    _, extracted_functions = _read_module_ast(_inference_path())

    for helper_name in EXTRACTED_PLOT_MODE_INFERENCE_HELPERS:
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
        assert isinstance(statement, ast.Return)
        call = statement.value
        if isinstance(function, ast.AsyncFunctionDef):
            assert isinstance(call, ast.Await), (
                f"{helper_name} should await the extracted async helper"
            )
            call = call.value

        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Attribute)
        assert isinstance(call.func.value, ast.Name)
        assert call.func.value.id == "_server_plot_mode_inference"
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


def test_plot_mode_inference_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    if _load_inference_module_if_wired() is None:
        return

    module, _ = _read_module_ast(_inference_path())
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
                "server_plot_mode_inference.py must not import private helpers directly from openplot.server"
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


@pytest.mark.anyio
async def test_propose_profile_from_selector_hint_uses_live_runner_and_profile_builder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inference_module = _load_inference_module_if_wired()
    if inference_module is None:
        return

    state = _state(tmp_path)
    selector = _tabular_selector()
    hint_bounds = _sheet_bounds()
    built_profile = _data_profile(profile_id="profile-from-runner")
    calls: list[object] = []

    monkeypatch.setattr(server, "_ensure_runner_is_available", lambda runner: None)

    async def fake_run_plot_mode_runner_prompt(
        *, state, runner, prompt, model, variant
    ):
        calls.append(("runner", state, runner, model, variant, prompt))
        return (
            "OPENPLOT_TABULAR_RANGE_BEGIN"
            '{"row_start": 0, "row_end": 2, "col_start": 0, "col_end": 1, '
            '"rationale": "Patched runner rationale.", "confidence": "high"}'
            "OPENPLOT_TABULAR_RANGE_END",
            None,
        )

    def fake_build_data_profile_from_grid(
        *, file_path, file_id, source_kind, sheet_name, bounds, rows
    ):
        calls.append(
            (
                "profile",
                file_path,
                file_id,
                source_kind,
                sheet_name,
                bounds,
                rows,
            )
        )
        return built_profile

    monkeypatch.setattr(
        server, "_run_plot_mode_runner_prompt", fake_run_plot_mode_runner_prompt
    )
    monkeypatch.setattr(
        server, "_build_data_profile_from_grid", fake_build_data_profile_from_grid
    )

    proposal = await server._propose_profile_from_selector_hint(
        state=state,
        selector=selector,
        sheet_id="sheet-1",
        hint_bounds=hint_bounds,
        instruction="Use the main table.",
    )

    assert proposal.profile is built_profile
    assert proposal.used_agent is True
    assert proposal.rationale == "Patched runner rationale. Confidence: high."
    assert calls[0][0] == "runner"
    assert calls[1] == (
        "profile",
        Path(selector.file_path),
        selector.file_id,
        selector.source_kind,
        "Sheet1",
        (0, 2, 0, 1),
        selector.sheets[0].preview_rows,
    )


@pytest.mark.anyio
async def test_propose_profile_from_selector_hint_uses_live_server_parser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inference_module = _load_inference_module_if_wired()
    if inference_module is None:
        return

    state = _state(tmp_path)
    selector = _tabular_selector()
    built_profile = _data_profile(profile_id="profile-from-parser")
    calls: list[object] = []

    monkeypatch.setattr(server, "_ensure_runner_is_available", lambda runner: None)

    async def fake_run_plot_mode_runner_prompt(
        *, state, runner, prompt, model, variant
    ):
        calls.append(("runner", prompt))
        return "ignored runner text", None

    def fake_extract_plot_mode_tabular_range_result(
        text: str, *, max_row_index: int, max_col_index: int
    ) -> tuple[tuple[int, int, int, int], str] | None:
        calls.append(("parser", text, max_row_index, max_col_index))
        return (2, 3, 0, 1), "Patched parser rationale."

    def fake_build_data_profile_from_grid(
        *, file_path, file_id, source_kind, sheet_name, bounds, rows
    ):
        calls.append(("profile", bounds, sheet_name, rows))
        return built_profile

    monkeypatch.setattr(
        server, "_run_plot_mode_runner_prompt", fake_run_plot_mode_runner_prompt
    )
    monkeypatch.setattr(
        server,
        "_extract_plot_mode_tabular_range_result",
        fake_extract_plot_mode_tabular_range_result,
    )
    monkeypatch.setattr(
        server, "_build_data_profile_from_grid", fake_build_data_profile_from_grid
    )
    _patch_fail_fast_if_present(
        monkeypatch, inference_module, "_extract_plot_mode_tabular_range_result"
    )

    proposal = await server._propose_profile_from_selector_hint(
        state=state,
        selector=selector,
        sheet_id="sheet-1",
        hint_bounds=_sheet_bounds(),
        instruction=None,
    )

    assert proposal.profile is built_profile
    assert proposal.used_agent is True
    assert proposal.rationale == "Patched parser rationale."
    assert len(calls) == 3
    assert calls[0][0] == "runner"
    assert isinstance(calls[0][1], str)
    assert calls[1] == ("parser", "ignored runner text", 3, 2)
    assert calls[2] == (
        "profile",
        (2, 3, 0, 1),
        "Sheet1",
        selector.sheets[0].preview_rows,
    )


@pytest.mark.anyio
async def test_grouped_profile_proposal_uses_live_single_region_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inference_module = _load_inference_module_if_wired()
    if inference_module is None:
        return

    state = _state(tmp_path)
    selector = _tabular_selector()
    selected_regions = [
        _selection_region(sheet_id="sheet-1", sheet_name="Sheet1"),
        _selection_region(
            sheet_id="sheet-2",
            sheet_name="Sheet2",
            bounds=_sheet_bounds(row_start=0, row_end=1, col_start=0, col_end=1),
        ),
    ]
    region_profiles = [
        _data_profile(profile_id="region-1", source_kind="excel"),
        _data_profile(profile_id="region-2", source_kind="excel"),
    ]
    grouped_profile = _data_profile(
        profile_id="grouped-profile",
        source_kind="excel",
        source_file_id=selector.file_id,
    )
    calls: list[object] = []

    async def fake_propose_profile_from_selector_hint(
        *, state, selector, sheet_id, hint_bounds, instruction
    ):
        calls.append(("region", sheet_id, hint_bounds, instruction))
        profile = region_profiles[0] if sheet_id == "sheet-1" else region_profiles[1]
        return server.PlotModeTabularProposalResult(
            profile=profile,
            rationale=f"Rationale for {sheet_id}",
            used_agent=(sheet_id == "sheet-2"),
        )

    def fake_build_grouped_data_profile_from_regions(
        *, file_path, file_id, source_kind, region_profiles
    ):
        calls.append(
            (
                "group",
                file_path,
                file_id,
                source_kind,
                tuple(region.id for region in region_profiles),
            )
        )
        return grouped_profile

    monkeypatch.setattr(
        server,
        "_propose_profile_from_selector_hint",
        fake_propose_profile_from_selector_hint,
    )
    monkeypatch.setattr(
        server,
        "_build_grouped_data_profile_from_regions",
        fake_build_grouped_data_profile_from_regions,
    )
    _patch_fail_fast_if_present(
        monkeypatch, inference_module, "_propose_profile_from_selector_hint"
    )

    proposal = await server._propose_grouped_profile_from_selector_regions(
        state=state,
        selector=selector,
        selected_regions=selected_regions,
        instruction="Use both highlighted ranges.",
    )

    assert proposal.profile is grouped_profile
    assert proposal.used_agent is True
    assert proposal.rationale == (
        "Sheet1!A2:B4: Rationale for sheet-1 Sheet2!A1:B2: Rationale for sheet-2"
    )
    assert calls == [
        (
            "region",
            "sheet-1",
            selected_regions[0].bounds,
            "Use both highlighted ranges.",
        ),
        (
            "region",
            "sheet-2",
            selected_regions[1].bounds,
            "Use both highlighted ranges.",
        ),
        (
            "group",
            Path(selector.file_path),
            selector.file_id,
            selector.source_kind,
            ("region-1", "region-2"),
        ),
    ]


def test_build_plot_mode_resolved_sources_uses_live_bundle_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inference_module = _load_inference_module_if_wired()
    if inference_module is None:
        return

    files = [
        _plot_mode_file(file_id="file-1", suffix=".csv"),
        _plot_mode_file(file_id="file-2", name="notes.json", suffix=".json"),
    ]
    profiles = [
        _data_profile(
            profile_id="profile-1", source_kind="csv", source_file_id="file-1"
        ),
        _data_profile(
            profile_id="profile-2", source_kind="json", source_file_id="file-2"
        ),
    ]
    bundle_source = _resolved_source(source_id="bundle-1", kind="mixed_bundle")
    calls: list[object] = []

    def fake_build_mixed_bundle_source(current_files, current_profiles):
        calls.append(
            (
                tuple(file.id for file in current_files),
                tuple(profile.id for profile in current_profiles),
            )
        )
        return bundle_source

    monkeypatch.setattr(
        server, "_build_mixed_bundle_source", fake_build_mixed_bundle_source
    )
    _patch_fail_fast_if_present(
        monkeypatch, inference_module, "_build_mixed_bundle_source"
    )

    resolved_sources, active_ids = server._build_plot_mode_resolved_sources(
        files,
        profiles,
        None,
    )

    assert resolved_sources == [bundle_source]
    assert active_ids == [bundle_source.id]
    assert calls == [(("file-1", "file-2"), ("profile-1", "profile-2"))]


def test_build_plot_mode_resolved_sources_uses_live_profile_source_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inference_module = _load_inference_module_if_wired()
    if inference_module is None:
        return

    files = [_plot_mode_file(file_id="file-1")]
    profiles = [
        _data_profile(profile_id="profile-1", source_file_id="file-1"),
        _data_profile(profile_id="profile-2", source_file_id="file-1"),
    ]
    built_sources = {
        "profile-1": _resolved_source(source_id="resolved-1"),
        "profile-2": _resolved_source(source_id="resolved-2"),
    }
    calls: list[str] = []

    def fake_build_resolved_source_for_profile(profile):
        calls.append(profile.id)
        return built_sources[profile.id]

    monkeypatch.setattr(
        server,
        "_build_resolved_source_for_profile",
        fake_build_resolved_source_for_profile,
    )
    _patch_fail_fast_if_present(
        monkeypatch, inference_module, "_build_resolved_source_for_profile"
    )

    resolved_sources, active_ids = server._build_plot_mode_resolved_sources(
        files,
        profiles,
        None,
    )

    assert resolved_sources == [built_sources["profile-1"], built_sources["profile-2"]]
    assert active_ids == []
    assert calls == ["profile-1", "profile-2"]
