import ast
from pathlib import Path
from typing import TypeAlias

import pandas as pd
import pytest

import openplot.server as server


EXTRACTED_PLOT_MODE_PROFILE_HELPERS = (
    "_stringify_preview_value",
    "_sample_integrity_notes",
    "_column_label",
    "_format_sheet_bounds",
    "_format_sheet_region_label",
    "_normalize_preview_grid",
    "_non_empty_cell_count",
    "_detect_non_empty_blocks",
    "_rows_for_bounds",
    "_looks_like_numeric_text",
    "_dataframe_from_block_rows",
    "_build_data_profile",
    "_build_tabular_region_from_frame",
    "_build_data_profile_from_grid",
    "_build_grouped_data_profile_from_regions",
    "_build_sheet_preview",
    "_read_delimited_grid",
    "_build_tabular_selector",
    "_tabular_regions_for_profile",
    "_profile_delimited_file",
    "_profile_json_file",
    "_profile_excel_file",
    "_profile_selected_data_files",
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


def _server_uses_extracted_plot_mode_profiles(module: ast.Module) -> bool:
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0 and (node.module or "") == "":
                if any(
                    alias.name == "server_plot_mode_profiles"
                    and alias.asname == "_server_plot_mode_profiles"
                    for alias in node.names
                ):
                    return True
        elif isinstance(node, ast.Name) and node.id == "_server_plot_mode_profiles":
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
        "server_plot_mode_profiles.py must not cache patchable server helpers at module import time"
    )


def _assert_pre_extraction_contract(
    module: ast.Module, functions: dict[str, FunctionNode]
) -> None:
    assert not _server_uses_extracted_plot_mode_profiles(module)
    expected_signatures = {
        "_stringify_preview_value": [("arg", "value", None)],
        "_sample_integrity_notes": [("arg", "frame", None)],
        "_column_label": [("arg", "index", None)],
        "_format_sheet_bounds": [("arg", "bounds", None)],
        "_format_sheet_region_label": [
            ("arg", "sheet_name", None),
            ("arg", "bounds", None),
        ],
        "_normalize_preview_grid": [("arg", "rows", None)],
        "_non_empty_cell_count": [("arg", "row", None)],
        "_detect_non_empty_blocks": [("arg", "rows", None)],
        "_rows_for_bounds": [("arg", "rows", None), ("arg", "bounds", None)],
        "_looks_like_numeric_text": [("arg", "value", None)],
        "_dataframe_from_block_rows": [("arg", "rows", None)],
        "_build_data_profile": [
            ("kwonly", "file_path", None),
            ("kwonly", "file_id", None),
            ("kwonly", "source_kind", None),
            ("kwonly", "source_label", None),
            ("kwonly", "table_name", None),
            ("kwonly", "frame", None),
            ("kwonly", "inferred_bounds", "Constant(value=None)"),
        ],
        "_build_tabular_region_from_frame": [
            ("kwonly", "file_path", None),
            ("kwonly", "source_kind", None),
            ("kwonly", "sheet_name", None),
            ("kwonly", "bounds", None),
            ("kwonly", "frame", None),
        ],
        "_build_data_profile_from_grid": [
            ("kwonly", "file_path", None),
            ("kwonly", "file_id", None),
            ("kwonly", "source_kind", None),
            ("kwonly", "sheet_name", None),
            ("kwonly", "bounds", None),
            ("kwonly", "rows", None),
        ],
        "_build_grouped_data_profile_from_regions": [
            ("kwonly", "file_path", None),
            ("kwonly", "file_id", None),
            ("kwonly", "source_kind", None),
            ("kwonly", "region_profiles", None),
        ],
        "_build_sheet_preview": [
            ("kwonly", "sheet_name", None),
            ("kwonly", "rows", None),
            ("kwonly", "total_rows", None),
            ("kwonly", "total_cols", None),
        ],
        "_read_delimited_grid": [("arg", "path", None), ("kwonly", "delimiter", None)],
        "_build_tabular_selector": [
            ("kwonly", "file", None),
            ("kwonly", "path", None),
            ("kwonly", "source_kind", None),
            ("kwonly", "sheets", None),
        ],
        "_tabular_regions_for_profile": [("arg", "profile", None)],
        "_profile_delimited_file": [
            ("arg", "file", None),
            ("arg", "path", None),
            ("kwonly", "delimiter", None),
            ("kwonly", "source_kind", None),
        ],
        "_profile_json_file": [("arg", "path", None)],
        "_profile_excel_file": [("arg", "file", None), ("arg", "path", None)],
        "_profile_selected_data_files": [("arg", "files", None)],
    }

    for helper_name in EXTRACTED_PLOT_MODE_PROFILE_HELPERS:
        assert helper_name in functions, f"Missing server helper {helper_name}"
        assert (
            _parameter_shape(functions[helper_name]) == expected_signatures[helper_name]
        )


def test_patchable_server_helper_guard_catches_non_inventory_aliases() -> None:
    server_alias_tree = ast.parse("cached = server._build_sheet_preview")
    assert _contains_patchable_server_helper_reference(
        server_alias_tree,
        server_aliases={"server"},
        openplot_aliases=set(),
    )

    openplot_alias_tree = ast.parse("cached = openplot.server._profile_delimited_file")
    assert _contains_patchable_server_helper_reference(
        openplot_alias_tree,
        server_aliases=set(),
        openplot_aliases={"openplot"},
    )


def test_plot_mode_profile_helpers_are_pre_extraction_aware_and_thin_when_extracted() -> (
    None
):
    bound_helpers = getattr(server, "_BOUND_SERVER_HELPERS", None)
    if isinstance(bound_helpers, dict) and '_server_plot_mode_profiles' in bound_helpers:
        assert set(EXTRACTED_PLOT_MODE_PROFILE_HELPERS) <= set(bound_helpers['_server_plot_mode_profiles'])
        for helper_name in EXTRACTED_PLOT_MODE_PROFILE_HELPERS:
            assert callable(getattr(server, helper_name))
            assert getattr(server, helper_name).__module__ == server.__name__
        return

    server_path = Path(server.__file__).resolve()
    profiles_path = server_path.with_name("server_plot_mode_profiles.py")
    server_module, functions = _read_module_ast(server_path)

    if not _server_uses_extracted_plot_mode_profiles(server_module):
        _assert_pre_extraction_contract(server_module, functions)
        return

    assert profiles_path.exists(), (
        "server.py references _server_plot_mode_profiles but server_plot_mode_profiles.py is missing"
    )

    _, profile_functions = _read_module_ast(profiles_path)

    for helper_name in EXTRACTED_PLOT_MODE_PROFILE_HELPERS:
        function = functions[helper_name]
        profile_function = profile_functions.get(helper_name)
        assert profile_function is not None, (
            f"Missing extracted helper for {helper_name}"
        )
        assert _parameter_shape(function) == _parameter_shape(
            profile_function, drop_leading_server_module=True
        )
        assert len(function.body) == 1, (
            f"{helper_name} should stay a one-statement wrapper"
        )

        statement = function.body[0]
        assert isinstance(statement, ast.Return)
        call = statement.value
        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Attribute)
        assert isinstance(call.func.value, ast.Name)
        assert call.func.value.id == "_server_plot_mode_profiles"
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


def test_plot_mode_profile_module_avoids_top_level_server_helper_aliases_when_extracted() -> (
    None
):
    server_path = Path(server.__file__).resolve()
    profiles_path = server_path.with_name("server_plot_mode_profiles.py")
    server_module, _ = _read_module_ast(server_path)

    if not _server_uses_extracted_plot_mode_profiles(server_module):
        return

    assert profiles_path.exists(), (
        "server.py references _server_plot_mode_profiles but server_plot_mode_profiles.py is missing"
    )

    module, _ = _read_module_ast(profiles_path)
    server_aliases = {"server"}
    openplot_aliases: set[str] = set()

    for node in module.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openplot":
                    openplot_aliases.add(alias.asname or alias.name)
                if alias.name == "openplot.server" or alias.name.startswith(
                    "openplot.server_"
                ):
                    raise AssertionError(
                        f"Forbidden import-time binding source in server_plot_mode_profiles.py: {alias.name}"
                    )
                if alias.name.startswith("openplot.services"):
                    raise AssertionError(
                        f"Forbidden service import in server_plot_mode_profiles.py: {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name == "openplot" and any(
                alias.name == "server" or alias.name.startswith("server_")
                for alias in node.names
            ):
                raise AssertionError(
                    "Forbidden import-time binding source in server_plot_mode_profiles.py: from openplot import server/server_*"
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
                    "Forbidden import-time binding source in server_plot_mode_profiles.py: from . import server/server_*"
                )
            if module_name == "openplot.server" or module_name.startswith(
                "openplot.server_"
            ):
                raise AssertionError(
                    f"Forbidden import-time binding source in server_plot_mode_profiles.py: {module_name}"
                )
            if module_name.startswith("openplot.services"):
                raise AssertionError(
                    f"Forbidden service import in server_plot_mode_profiles.py: {module_name}"
                )
            if node.level > 0 and (
                module_name == "server"
                or module_name.startswith("server_")
                or module_name.startswith("services")
            ):
                raise AssertionError(
                    f"Forbidden relative import in server_plot_mode_profiles.py: {module_name or '.'}"
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


def test_build_data_profile_from_grid_uses_live_server_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, object]] = []
    sentinel_rows = [["patched", "rows"]]
    sentinel_profile = server.PlotModeDataProfile(
        file_path=str(tmp_path / "data.csv"),
        file_name="data.csv",
        source_label="sentinel-profile-source",
        source_kind="csv",
        summary="sentinel-profile-summary",
        columns=["sentinel"],
        source_file_id="file-1",
    )

    def fake_rows_for_bounds(rows, bounds):
        calls.append(("rows_for_bounds", bounds))
        assert rows == [["ignored"]]
        return sentinel_rows

    def fake_dataframe_from_block_rows(rows):
        calls.append(("dataframe_from_block_rows", tuple(tuple(row) for row in rows)))
        assert rows == sentinel_rows
        return pd.DataFrame([[1]], columns=["patched_column"])

    def fake_build_tabular_region_from_frame(**kwargs):
        calls.append(
            ("build_tabular_region_from_frame", tuple(kwargs["frame"].columns))
        )
        return server.PlotModeDataRegion(
            sheet_name=kwargs["sheet_name"],
            source_label="patched-source-label",
            summary="patched-summary",
            bounds=server.PlotModeSheetBounds(
                row_start=kwargs["bounds"][0],
                row_end=kwargs["bounds"][1],
                col_start=kwargs["bounds"][2],
                col_end=kwargs["bounds"][3],
            ),
            columns=["patched_column"],
            preview_rows=[["1"]],
        )

    def fake_build_data_profile(**kwargs):
        calls.append(
            (
                "build_data_profile",
                (
                    kwargs["source_label"],
                    kwargs["table_name"],
                    kwargs["inferred_bounds"],
                ),
            )
        )
        return sentinel_profile

    monkeypatch.setattr(server, "_rows_for_bounds", fake_rows_for_bounds)
    monkeypatch.setattr(
        server, "_dataframe_from_block_rows", fake_dataframe_from_block_rows
    )
    monkeypatch.setattr(
        server,
        "_build_tabular_region_from_frame",
        fake_build_tabular_region_from_frame,
    )
    monkeypatch.setattr(server, "_build_data_profile", fake_build_data_profile)

    profile = server._build_data_profile_from_grid(
        file_path=tmp_path / "data.csv",
        file_id="file-1",
        source_kind="csv",
        sheet_name="Sheet1",
        bounds=(1, 2, 3, 4),
        rows=[["ignored"]],
    )

    assert calls == [
        ("rows_for_bounds", (1, 2, 3, 4)),
        ("dataframe_from_block_rows", (("patched", "rows"),)),
        ("build_tabular_region_from_frame", ("patched_column",)),
        (
            "build_data_profile",
            ("patched-source-label", "Sheet1", (1, 2, 3, 4)),
        ),
    ]
    assert profile is sentinel_profile
    assert profile.source_label == "sentinel-profile-source"
    assert profile.summary == "patched-summary"
    assert profile.tabular_regions[0].source_label == "patched-source-label"
    assert profile.columns == ["sentinel"]


def test_profile_selected_data_files_uses_live_server_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, str]] = []
    csv_path = tmp_path / "sample.csv"
    xlsx_path = tmp_path / "sample.xlsx"

    def fake_profile_delimited_file(file, path, *, delimiter, source_kind):
        calls.append(("delimited", f"{path.name}:{delimiter}:{source_kind}"))
        return (
            [
                server.PlotModeDataProfile(
                    file_path=str(path),
                    file_name=path.name,
                    source_label="csv-source",
                    source_kind=source_kind,
                    summary="csv-summary",
                    source_file_id=file.id,
                )
            ],
            None,
            [f"csv:{path.name}"],
        )

    def fake_profile_excel_file(file, path):
        calls.append(("excel", path.name))
        return (
            [],
            server.PlotModeTabularSelector(
                file_id=file.id,
                file_path=str(path),
                file_name=path.name,
                source_kind="excel",
                status_text="needs selection",
            ),
            [f"excel:{path.name}"],
        )

    monkeypatch.setattr(server, "_profile_delimited_file", fake_profile_delimited_file)
    monkeypatch.setattr(server, "_profile_excel_file", fake_profile_excel_file)

    profiles, activity_items, selector = server._profile_selected_data_files(
        [
            server.PlotModeFile(
                id="csv-1",
                name="sample.csv",
                stored_path=str(csv_path),
                size_bytes=1,
                content_type="text/csv",
            ),
            server.PlotModeFile(
                id="xlsx-1",
                name="sample.xlsx",
                stored_path=str(xlsx_path),
                size_bytes=1,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        ]
    )

    assert calls == [
        ("delimited", "sample.csv:,:csv"),
        ("excel", "sample.xlsx"),
    ]
    assert [profile.source_label for profile in profiles] == ["csv-source"]
    assert activity_items == ["csv:sample.csv", "excel:sample.xlsx"]
    assert selector is not None
    assert selector.file_name == "sample.xlsx"


def test_build_sheet_preview_uses_live_server_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def fake_detect_non_empty_blocks(rows):
        calls.append(("detect_non_empty_blocks", rows))
        return [(1, 3, 0, 2)]

    def fake_format_sheet_bounds(bounds):
        calls.append(("format_sheet_bounds", bounds))
        return "PATCHED_BOUNDS"

    def fake_normalize_preview_grid(rows):
        calls.append(("normalize_preview_grid", rows))
        return [["patched-preview-grid"]]

    monkeypatch.setattr(
        server, "_detect_non_empty_blocks", fake_detect_non_empty_blocks
    )
    monkeypatch.setattr(server, "_format_sheet_bounds", fake_format_sheet_bounds)
    monkeypatch.setattr(server, "_normalize_preview_grid", fake_normalize_preview_grid)

    preview = server._build_sheet_preview(
        sheet_name="Sheet1",
        rows=[["header"], ["value"]],
        total_rows=12,
        total_cols=4,
    )

    assert calls == [
        ("detect_non_empty_blocks", [["header"], ["value"]]),
        ("format_sheet_bounds", (1, 3, 0, 2)),
        ("normalize_preview_grid", [["header"], ["value"]]),
    ]
    assert preview.name == "Sheet1"
    assert preview.preview_rows == [["patched-preview-grid"]]
    assert len(preview.candidate_tables) == 1
    assert preview.candidate_tables[0].label == "Candidate 1 (PATCHED_BOUNDS)"
    assert preview.candidate_tables[0].bounds.model_dump() == {
        "row_start": 1,
        "row_end": 3,
        "col_start": 0,
        "col_end": 2,
    }
