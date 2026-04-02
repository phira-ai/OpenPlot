"""Plot-mode inference and resolved-source helpers extracted from openplot.server."""

from __future__ import annotations

import json
import re
from contextlib import suppress
from pathlib import Path
from types import ModuleType
from typing import Literal, cast

from fastapi import HTTPException

from .models import (
    PlotModeDataProfile,
    PlotModeFile,
    PlotModeInputBundle,
    PlotModeResolvedDataSource,
    PlotModeSheetBounds,
    PlotModeSheetPreview,
    PlotModeState,
    PlotModeTabularSelectionRegion,
    PlotModeTabularSelector,
)


def _candidate_summaries_for_prompt(
    server_module: ModuleType,
    sheet: PlotModeSheetPreview,
    hint_tuple: tuple[int, int, int, int],
) -> list[str]:
    summaries: list[str] = []
    for candidate in sheet.candidate_tables[:8]:
        candidate_bounds = server_module._bounds_from_sheet_bounds(candidate.bounds)
        overlap = server_module._overlap_area(candidate_bounds, hint_tuple)
        summaries.append(
            f"- {candidate.label}: overlap_with_hint={overlap}, summary={candidate.summary or 'detected non-empty region'}"
        )
    return summaries or ["- No candidate table regions were detected."]


def _compact_cell_text(value: str, *, max_chars: int = 32) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if not compact:
        return ""
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _sheet_excerpt_for_prompt(
    server_module: ModuleType,
    rows: list[list[str]],
    bounds: tuple[int, int, int, int],
    *,
    max_rows: int = 16,
    max_cols: int = 10,
) -> str:
    grid = server_module._normalize_preview_grid(rows)
    if not grid:
        return "<empty sheet>"

    row_indices = list(range(bounds[0], bounds[1] + 1))
    col_indices = list(range(bounds[2], bounds[3] + 1))
    if not row_indices or not col_indices:
        return "<empty selection>"

    if len(row_indices) > max_rows:
        keep = max_rows // 2
        row_indices = row_indices[:keep] + row_indices[-keep:]
    if len(col_indices) > max_cols:
        keep = max_cols // 2
        col_indices = col_indices[:keep] + col_indices[-keep:]

    header = ["#", *(server_module._column_label(index) for index in col_indices)]
    lines = ["\t".join(header)]
    displayed_rows = set(row_indices)
    previous_row: int | None = None

    for row_index in row_indices:
        if previous_row is not None and row_index - previous_row > 1:
            lines.append("...")
        cells = [str(row_index + 1)]
        for col_index in col_indices:
            cells.append(_compact_cell_text(grid[row_index][col_index]) or "-")
        lines.append("\t".join(cells))
        previous_row = row_index

    full_col_indices = list(range(bounds[2], bounds[3] + 1))
    if len(full_col_indices) > len(col_indices):
        hidden = len(full_col_indices) - len(col_indices)
        lines.append(f"... ({hidden} additional column(s) omitted)")
    hidden_rows = (bounds[1] - bounds[0] + 1) - len(displayed_rows)
    if hidden_rows > 0:
        lines.append(f"... ({hidden_rows} additional row(s) omitted)")
    return "\n".join(lines)


def _build_tabular_range_inference_prompt(
    server_module: ModuleType,
    *,
    file_name: str,
    sheet: PlotModeSheetPreview,
    hint_bounds: PlotModeSheetBounds,
    instruction: str | None,
) -> str:
    hint_tuple = server_module._bounds_from_sheet_bounds(hint_bounds)
    max_row_index = len(sheet.preview_rows) - 1
    max_col_index = max((len(row) for row in sheet.preview_rows), default=0) - 1
    surrounding_bounds = server_module._expand_bounds(
        hint_tuple,
        max_row_index=max_row_index,
        max_col_index=max_col_index,
        row_padding=3,
        col_padding=3,
    )
    lines = [
        "You infer the intended spreadsheet table range for OpenPlot.",
        "Return exactly one JSON object between OPENPLOT_TABULAR_RANGE_BEGIN and OPENPLOT_TABULAR_RANGE_END.",
        "Required JSON keys: row_start, row_end, col_start, col_end, rationale, confidence.",
        "Use zero-based inclusive indexes for rows and columns.",
        "Rules:",
        "- Prefer explicit user instructions over structural heuristics.",
        "- Treat the drag selection as a rough hint, but do not widen to unrelated nearby columns just because they are non-empty.",
        "- Stay on the selected sheet and return one contiguous rectangle.",
        "- The proposed rectangle must overlap the user hint.",
        "- If unsure, stay conservative and close to the hint.",
        "",
        f"File: {file_name}",
        f"Sheet: {sheet.name}",
        f"Sheet preview size: {len(sheet.preview_rows)} row(s) x {max_col_index + 1 if max_col_index >= 0 else 0} column(s)",
        f"User hint range: {server_module._format_sheet_bounds(hint_tuple)}",
        f"User instruction: {(instruction or 'None').strip() or 'None'}",
        "",
        "Detected candidate regions:",
        *_candidate_summaries_for_prompt(server_module, sheet, hint_tuple),
        "",
        f"Exact hint excerpt ({server_module._format_sheet_bounds(hint_tuple)}):",
        server_module._sheet_excerpt_for_prompt(
            sheet.preview_rows, hint_tuple, max_rows=12, max_cols=8
        ),
        "",
        f"Surrounding context ({server_module._format_sheet_bounds(surrounding_bounds)}):",
        server_module._sheet_excerpt_for_prompt(
            sheet.preview_rows,
            surrounding_bounds,
            max_rows=18,
            max_cols=12,
        ),
        "",
        "Respond with JSON only inside the markers.",
    ]
    return "\n".join(lines)


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        with suppress(ValueError):
            return int(float(stripped))
    return None


def _extract_plot_mode_tabular_range_result(
    server_module: ModuleType,
    text: str,
    *,
    max_row_index: int,
    max_col_index: int,
) -> tuple[tuple[int, int, int, int], str] | None:
    candidate_dicts: list[dict[str, object]] = []
    strict_match = re.search(
        r"OPENPLOT_TABULAR_RANGE_BEGIN\s*(\{.*?\})\s*OPENPLOT_TABULAR_RANGE_END",
        text,
        flags=re.DOTALL,
    )
    if strict_match:
        with suppress(json.JSONDecodeError):
            payload = json.loads(strict_match.group(1))
            if isinstance(payload, dict):
                candidate_dicts.append(cast(dict[str, object], payload))

    with suppress(json.JSONDecodeError):
        payload = json.loads(text.strip())
        if isinstance(payload, dict):
            candidate_dicts.append(cast(dict[str, object], payload))

    candidate_dicts.extend(server_module._json_object_candidates(text))

    for payload in candidate_dicts:
        bounds_payload = server_module._as_record(payload.get("bounds")) or payload
        row_start = _coerce_int(bounds_payload.get("row_start"))
        row_end = _coerce_int(bounds_payload.get("row_end"))
        col_start = _coerce_int(bounds_payload.get("col_start"))
        col_end = _coerce_int(bounds_payload.get("col_end"))
        if None in {row_start, row_end, col_start, col_end}:
            continue
        clipped_bounds = server_module._clip_bounds_to_sheet(
            cast(tuple[int, int, int, int], (row_start, row_end, col_start, col_end)),
            max_row_index=max_row_index,
            max_col_index=max_col_index,
        )
        rationale_parts: list[str] = []
        rationale = server_module._as_string(payload.get("rationale"))
        confidence = server_module._as_string(payload.get("confidence"))
        if rationale:
            rationale_parts.append(rationale)
        if confidence:
            rationale_parts.append(f"Confidence: {confidence}.")
        return clipped_bounds, " ".join(rationale_parts).strip()
    return None


async def _propose_profile_from_selector_hint(
    server_module: ModuleType,
    *,
    state: PlotModeState,
    selector: PlotModeTabularSelector,
    sheet_id: str,
    hint_bounds: PlotModeSheetBounds,
    instruction: str | None,
):
    sheet = next((sheet for sheet in selector.sheets if sheet.id == sheet_id), None)
    if sheet is None:
        raise HTTPException(status_code=400, detail="Selected sheet is unavailable.")

    hint_tuple = server_module._bounds_from_sheet_bounds(hint_bounds)
    chosen_bounds = hint_tuple
    rationale = "Used your selected hint directly as a conservative range proposal."
    used_agent = False
    max_row_index = len(sheet.preview_rows) - 1
    max_col_index = max((len(row) for row in sheet.preview_rows), default=0) - 1

    if max_row_index >= 0 and max_col_index >= 0:
        runner = server_module._normalize_fix_runner(
            state.selected_runner, default=server_module._default_fix_runner
        )
        try:
            server_module._ensure_runner_is_available(runner)
        except HTTPException:
            runner = ""

        if runner:
            model = str(
                state.selected_model or ""
            ).strip() or server_module._runner_default_model_id(runner)
            normalized_variant = (
                str(state.selected_variant).strip() if state.selected_variant else ""
            )
            prompt = server_module._build_tabular_range_inference_prompt(
                file_name=selector.file_name,
                sheet=sheet,
                hint_bounds=hint_bounds,
                instruction=instruction,
            )
            (
                assistant_text,
                runner_error,
            ) = await server_module._run_plot_mode_runner_prompt(
                state=state,
                runner=runner,
                prompt=prompt,
                model=model,
                variant=normalized_variant or None,
            )
            if runner_error is None:
                parsed = server_module._extract_plot_mode_tabular_range_result(
                    assistant_text,
                    max_row_index=max_row_index,
                    max_col_index=max_col_index,
                )
                if parsed is not None:
                    proposed_bounds, proposed_rationale = parsed
                    if server_module._overlap_area(proposed_bounds, hint_tuple) > 0:
                        chosen_bounds = proposed_bounds
                        rationale = (
                            proposed_rationale
                            or "Proposed a range from the hint and surrounding sheet context."
                        )
                        used_agent = True

    profile = server_module._build_data_profile_from_grid(
        file_path=Path(selector.file_path),
        file_id=selector.file_id,
        source_kind=selector.source_kind,
        sheet_name=sheet.name,
        bounds=chosen_bounds,
        rows=sheet.preview_rows,
    )
    return server_module.PlotModeTabularProposalResult(
        profile=profile,
        rationale=rationale,
        used_agent=used_agent,
    )


def _plot_mode_file_kind(file: PlotModeFile) -> str:
    suffix = Path(file.stored_path).suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".tsv":
        return "tsv"
    if suffix in {".xls", ".xlsx"}:
        return "excel"
    if suffix in {".json", ".jsonl"}:
        return "json"
    if suffix == ".txt":
        return "txt"
    return suffix.lstrip(".") or "file"


def _build_plot_mode_input_bundle(
    server_module: ModuleType,
    files: list[PlotModeFile],
) -> PlotModeInputBundle | None:
    del server_module
    if not files:
        return None

    file_kinds: list[str] = []
    for file in files:
        kind = _plot_mode_file_kind(file)
        if kind not in file_kinds:
            file_kinds.append(kind)

    file_count = len(files)
    kind_label = "/".join(file_kinds[:3]) if file_kinds else "file"
    label = f"{file_count} selected file{'s' if file_count != 1 else ''}"
    summary = f"{file_count} {kind_label} file{'s' if file_count != 1 else ''} selected for this workspace."
    return PlotModeInputBundle(
        label=label,
        summary=summary,
        file_ids=[file.id for file in files],
        file_paths=[str(Path(file.stored_path).resolve()) for file in files],
        file_count=file_count,
        file_kinds=file_kinds,
    )


def _resolved_source_kind_for_profile(
    server_module: ModuleType,
    profile: PlotModeDataProfile,
) -> str:
    if profile.source_kind == "file":
        return "unstructured_file"
    if len(server_module._tabular_regions_for_profile(profile)) > 1:
        return "multi_region_excel_source"
    if profile.source_kind == "excel" or profile.table_name is not None:
        return "excel_region"
    return "single_file"


def _build_resolved_source_for_profile(
    server_module: ModuleType,
    profile: PlotModeDataProfile,
) -> PlotModeResolvedDataSource:
    return PlotModeResolvedDataSource(
        kind=cast(
            Literal[
                "single_file",
                "multi_file_collection",
                "excel_region",
                "multi_region_excel_source",
                "unstructured_file",
                "mixed_bundle",
            ],
            _resolved_source_kind_for_profile(server_module, profile),
        ),
        label=profile.source_label,
        summary=profile.summary,
        file_ids=[profile.source_file_id] if profile.source_file_id else [],
        file_paths=[profile.file_path],
        file_count=1,
        profile_ids=[profile.id],
        columns=profile.columns,
        integrity_notes=profile.integrity_notes,
    )


def _profile_column_signature(profile: PlotModeDataProfile) -> tuple[str, ...]:
    return tuple(
        sorted({column.strip().lower() for column in profile.columns if column.strip()})
    )


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _build_multi_file_collection_source(
    server_module: ModuleType,
    files: list[PlotModeFile],
    profiles: list[PlotModeDataProfile],
) -> PlotModeResolvedDataSource:
    del server_module
    columns = profiles[0].columns[:] if profiles else []
    integrity_notes = _dedupe_preserving_order(
        [note for profile in profiles for note in profile.integrity_notes]
    )
    label = f"{len(files)} CSV files"
    summary = f"Treat these {len(files)} CSV files as one multi-file dataset."
    if columns:
        summary += " Shared columns: " + ", ".join(columns[:6]) + "."
    return PlotModeResolvedDataSource(
        kind="multi_file_collection",
        label=label,
        summary=summary,
        file_ids=[file.id for file in files],
        file_paths=[str(Path(file.stored_path).resolve()) for file in files],
        file_count=len(files),
        profile_ids=[profile.id for profile in profiles],
        columns=columns,
        integrity_notes=integrity_notes,
    )


def _build_mixed_bundle_source(
    server_module: ModuleType,
    files: list[PlotModeFile],
    profiles: list[PlotModeDataProfile],
) -> PlotModeResolvedDataSource:
    del server_module
    kinds = _dedupe_preserving_order([_plot_mode_file_kind(file) for file in files])
    label = f"{len(files)} selected files"
    summary = f"Treat these {len(files)} files as one input bundle until the plotting relationship is clarified."
    if kinds:
        summary += " Source kinds: " + ", ".join(kinds[:6]) + "."
    return PlotModeResolvedDataSource(
        kind="mixed_bundle",
        label=label,
        summary=summary,
        file_ids=[file.id for file in files],
        file_paths=[str(Path(file.stored_path).resolve()) for file in files],
        file_count=len(files),
        profile_ids=[profile.id for profile in profiles],
        columns=_dedupe_preserving_order(
            [column for profile in profiles for column in profile.columns]
        )[:16],
        integrity_notes=_dedupe_preserving_order(
            [note for profile in profiles for note in profile.integrity_notes]
        ),
    )


def _build_plot_mode_resolved_sources(
    server_module: ModuleType,
    files: list[PlotModeFile],
    profiles: list[PlotModeDataProfile],
    selector: PlotModeTabularSelector | None,
) -> tuple[list[PlotModeResolvedDataSource], list[str]]:
    if len(files) > 1 and selector is None:
        signatures = {_profile_column_signature(profile) for profile in profiles}
        if (
            len(profiles) == len(files)
            and profiles
            and all(profile.source_kind == "csv" for profile in profiles)
            and len(signatures) == 1
            and all(signature for signature in signatures)
        ):
            source = server_module._build_multi_file_collection_source(files, profiles)
            return [source], [source.id]

        source = server_module._build_mixed_bundle_source(files, profiles)
        return [source], [source.id]

    return [
        server_module._build_resolved_source_for_profile(profile)
        for profile in profiles
    ], []


async def _propose_grouped_profile_from_selector_regions(
    server_module: ModuleType,
    *,
    state: PlotModeState,
    selector: PlotModeTabularSelector,
    selected_regions: list[PlotModeTabularSelectionRegion],
    instruction: str | None,
):
    normalized_regions = server_module._dedupe_selection_regions(selected_regions)
    if not normalized_regions:
        raise HTTPException(status_code=400, detail="No tabular regions were provided.")

    region_profiles: list[PlotModeDataProfile] = []
    rationale_parts: list[str] = []
    used_agent = False
    for region in normalized_regions:
        proposal = await server_module._propose_profile_from_selector_hint(
            state=state,
            selector=selector,
            sheet_id=region.sheet_id,
            hint_bounds=region.bounds,
            instruction=instruction,
        )
        region_profiles.append(proposal.profile)
        used_agent = used_agent or proposal.used_agent
        if proposal.rationale.strip():
            rationale_parts.append(
                f"{server_module._format_sheet_region_label(region.sheet_name, server_module._bounds_from_sheet_bounds(region.bounds))}: {proposal.rationale.strip()}"
            )

    profile = server_module._build_grouped_data_profile_from_regions(
        file_path=Path(selector.file_path),
        file_id=selector.file_id,
        source_kind=selector.source_kind,
        region_profiles=region_profiles,
    )
    return server_module.PlotModeTabularProposalResult(
        profile=profile,
        rationale=" ".join(rationale_parts).strip(),
        used_agent=used_agent,
    )
