"""Response/parsing helpers extracted from openplot.server."""

from __future__ import annotations

import json
import re
from contextlib import suppress
from pathlib import Path
from types import ModuleType
from typing import cast

from fastapi import HTTPException

from .models import PlotModeQuestionOption


def _append_active_resolved_source_context(
    server_module: ModuleType,
    lines: list[str],
    state,
    *,
    heading: str,
) -> None:
    sources = server_module._active_resolved_sources(state)
    if not sources:
        return

    lines.extend(["", heading])
    for source in sources[:4]:
        lines.append(f"- Label: {source.label}")
        lines.append(f"- Kind: {source.kind}")
        if source.summary:
            lines.append(f"- Summary: {source.summary}")
        if source.columns:
            lines.append("- Columns: " + ", ".join(source.columns[:16]))
        if source.file_paths:
            lines.append("- Files:")
            for path in source.file_paths[
                : server_module._plot_mode_prompt_files_limit
            ]:
                lines.append(f"  - {path}")
            if len(source.file_paths) > server_module._plot_mode_prompt_files_limit:
                remaining = (
                    len(source.file_paths) - server_module._plot_mode_prompt_files_limit
                )
                lines.append(f"  - ... and {remaining} more files")
        if source.integrity_notes:
            lines.append("- Integrity notes:")
            for note in source.integrity_notes[:8]:
                lines.append(f"  - {note}")


def _append_profile_region_details(
    server_module: ModuleType,
    lines: list[str],
    profile,
) -> None:
    tabular_regions = server_module._tabular_regions_for_profile(profile)
    if not tabular_regions:
        return
    lines.append("- Selected regions:")
    for region in tabular_regions[:8]:
        bounds = (
            server_module._bounds_from_sheet_bounds(region.bounds)
            if region.bounds is not None
            else None
        )
        lines.append(
            f"  - {server_module._format_sheet_region_label(region.sheet_name, bounds)}"
        )
        if region.columns:
            lines.append("    Columns: " + ", ".join(region.columns[:12]))


def _json_object_candidates(
    server_module: ModuleType,
    text: str,
) -> list[dict[str, object]]:
    del server_module
    candidates: list[dict[str, object]] = []
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            candidates.append(cast(dict[str, object], payload))
    return candidates


def _coerce_bool(server_module: ModuleType, value: object) -> bool | None:
    del server_module
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "ready", "done"}:
            return True
        if normalized in {"false", "no", "n", "not_ready", "pending"}:
            return False
    return None


def _suggest_plot_mode_question_options(
    server_module: ModuleType,
    prompt: str,
) -> list[PlotModeQuestionOption]:
    del server_module
    normalized = re.sub(r"\s+", " ", prompt).strip().lower()
    if not normalized:
        return []

    def _option(
        option_id: str,
        label: str,
        description: str = "",
        *,
        recommended: bool = False,
    ) -> PlotModeQuestionOption:
        return PlotModeQuestionOption(
            id=option_id,
            label=label,
            description=description,
            recommended=recommended,
        )

    if any(token in normalized for token in ("figure type", "chart type", "plot type")):
        return [
            _option(
                "line_chart",
                "Line chart",
                "Best for ordered or time-based trends.",
                recommended=True,
            ),
            _option(
                "scatter_plot",
                "Scatter plot",
                "Best for relationships between two variables.",
            ),
            _option("bar_chart", "Bar chart", "Best for category comparisons."),
            _option("heatmap", "Heatmap", "Best for dense matrix-style comparisons."),
            _option("multi_panel", "Multi-panel", "Split related views across panels."),
        ]

    if "data source" in normalized or (
        "source" in normalized
        and any(
            token in normalized
            for token in ("file", "path", "table", "schema", "column")
        )
    ):
        return [
            _option(
                "use_selected_source",
                "Use selected source",
                "Proceed with the dataset already previewed.",
                recommended=True,
            ),
            _option(
                "choose_another_source",
                "Choose another source",
                "Switch to a different file, sheet, or range.",
            ),
            _option(
                "describe_schema",
                "Describe schema",
                "I will type the columns and units manually.",
            ),
        ]

    if any(
        token in normalized
        for token in ("layout", "single panel", "multi-panel", "shared axes")
    ):
        return [
            _option(
                "single_panel", "Single panel", "One main chart only.", recommended=True
            ),
            _option("two_panel", "1x2 panels", "Two related panels side by side."),
            _option(
                "small_multiples",
                "2x2 small multiples",
                "Compare several facets at once.",
            ),
            _option(
                "custom_layout",
                "Custom layout",
                "I will describe the panel arrangement.",
            ),
        ]

    if any(
        token in normalized
        for token in ("axes", "x/y", "scales", "ranges", "transforms")
    ):
        return [
            _option(
                "use_default_axes",
                "Use obvious x/y mapping",
                "Infer the clearest x and y variables from the data.",
                recommended=True,
            ),
            _option(
                "linear_scales",
                "Keep linear scales",
                "Avoid log transforms unless clearly needed.",
            ),
            _option(
                "allow_log_scale",
                "Allow log scaling",
                "Use log scaling if it improves readability.",
            ),
            _option(
                "custom_axes",
                "I need custom axes",
                "I will specify variables, ranges, or transforms manually.",
            ),
        ]

    if any(
        token in normalized
        for token in (
            "styling",
            "journal",
            "venue style",
            "font",
            "palette",
            "line widths",
            "marker styles",
        )
    ):
        return [
            _option(
                "publication_neutral",
                "Publication-neutral",
                "Clean, restrained defaults for papers.",
                recommended=True,
            ),
            _option(
                "presentation_bold",
                "Presentation-forward",
                "Higher contrast and larger labels for slides.",
            ),
            _option(
                "print_safe",
                "Print-safe monochrome",
                "Works well in grayscale or print.",
            ),
            _option(
                "match_reference_style",
                "Match a reference style",
                "I will point to an example to follow.",
            ),
        ]

    if any(
        token in normalized
        for token in (
            "annotations",
            "legend",
            "error bars",
            "statistical markers",
            "reference lines",
        )
    ):
        return [
            _option(
                "minimal_annotations",
                "Minimal annotations",
                "Only essential labels and a simple legend.",
                recommended=True,
            ),
            _option(
                "full_annotations",
                "Legend and labels",
                "Include fuller explanatory labelling.",
            ),
            _option(
                "uncertainty_annotations",
                "Include uncertainty markers",
                "Add error bars or statistical markers if relevant.",
            ),
            _option(
                "custom_annotations",
                "Custom annotations",
                "I will specify exact callouts or reference lines.",
            ),
        ]

    if any(
        token in normalized
        for token in ("output", "dpi", "file format", "transparent", "background")
    ):
        return [
            _option(
                "vector_output",
                "PDF/SVG vector output",
                "Best for publication workflows.",
                recommended=True,
            ),
            _option("png_output", "High-res PNG", "Best for quick sharing and slides."),
            _option(
                "both_outputs",
                "Both vector and PNG",
                "Export both publication and preview formats.",
            ),
            _option(
                "transparent_bg",
                "Transparent background",
                "Useful for compositing in other layouts.",
            ),
        ]

    if any(
        token in normalized
        for token in (
            "constraint",
            "examples to match",
            "example to match",
            "strict constraints",
        )
    ):
        return [
            _option(
                "no_strict_constraints",
                "No strict constraints",
                "Use best judgment from the dataset and goal.",
                recommended=True,
            ),
            _option(
                "match_example",
                "Match an example",
                "I have a reference figure or house style.",
            ),
            _option(
                "journal_constraints",
                "Journal or brand constraints",
                "Follow explicit formatting requirements.",
            ),
            _option(
                "custom_constraints",
                "Custom constraints",
                "I will describe the limits manually.",
            ),
        ]

    if "audience" in normalized:
        return [
            _option(
                "academic_audience",
                "Academic readers",
                "Optimize for publication-style clarity.",
                recommended=True,
            ),
            _option(
                "executive_audience",
                "Executive audience",
                "Optimize for quick takeaway and contrast.",
            ),
            _option(
                "technical_internal",
                "Technical internal audience",
                "Balance detail and readability.",
            ),
        ]

    if "tone" in normalized:
        return [
            _option(
                "academic_tone", "Academic", "Formal and restrained.", recommended=True
            ),
            _option("executive_tone", "Executive", "Direct and presentation-oriented."),
            _option(
                "exploratory_tone",
                "Exploratory",
                "More flexible and analysis-forward.",
            ),
        ]

    if any(
        token in normalized
        for token in ("metric matters most", "which metric", "key metric")
    ):
        return [
            _option(
                "trend_focus",
                "Trend over time",
                "Emphasize directional change.",
                recommended=True,
            ),
            _option(
                "comparison_focus",
                "Group comparison",
                "Emphasize differences between categories.",
            ),
            _option(
                "distribution_focus",
                "Distribution or uncertainty",
                "Emphasize spread, range, or variability.",
            ),
            _option(
                "custom_metric_focus",
                "Custom metric",
                "I will specify the main metric.",
            ),
        ]

    if "print or slides" in normalized or (
        "print" in normalized and "slides" in normalized
    ):
        return [
            _option(
                "print_first",
                "Print-first",
                "Optimize for papers or PDFs.",
                recommended=True,
            ),
            _option(
                "slides_first",
                "Slides-first",
                "Optimize for projection and speaking contexts.",
            ),
            _option(
                "balanced_output", "Balanced for both", "Try to work in both settings."
            ),
        ]

    return []


def _extract_structured_plot_mode_result(
    server_module: ModuleType,
    text: str,
) -> tuple[str, str, bool | None] | None:
    candidate_dicts: list[dict[str, object]] = []
    strict_match = re.search(
        r"OPENPLOT_RESULT_BEGIN\s*(\{.*?\})\s*OPENPLOT_RESULT_END",
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
        script = payload.get("script")
        if not isinstance(script, str) or not script.strip():
            continue
        summary_value = payload.get("summary")
        summary = (
            summary_value.strip()
            if isinstance(summary_value, str) and summary_value.strip()
            else "Generated plotting script."
        )
        done_hint = server_module._coerce_bool(payload.get("done"))
        if done_hint is None:
            done_hint = server_module._coerce_bool(payload.get("ready"))
        if done_hint is None:
            done_hint = server_module._coerce_bool(payload.get("satisfied"))
        return summary, script.strip(), done_hint

    return None


def _extract_python_script_from_text(
    server_module: ModuleType, text: str
) -> str | None:
    del server_module
    fenced_python = re.search(
        r"```python\s*(.*?)```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced_python:
        candidate = fenced_python.group(1).strip()
        if candidate:
            return candidate

    fenced_generic = re.search(r"```\s*(.*?)```", text, flags=re.DOTALL)
    if fenced_generic:
        candidate = fenced_generic.group(1).strip()
        if candidate:
            return candidate

    stripped = text.strip()
    if "\n" in stripped and (
        "import " in stripped
        or "plt." in stripped
        or "fig," in stripped
        or "plot.png" in stripped
    ):
        return stripped
    return None


def _extract_plot_mode_script_result(
    server_module: ModuleType,
    text: str,
) -> tuple[str, str, bool | None] | None:
    structured = server_module._extract_structured_plot_mode_result(text)
    if structured is not None:
        return structured

    script = server_module._extract_python_script_from_text(text)
    if script is None:
        return None

    summary = "Generated plotting script from fallback parsing."
    first_non_code_line = next(
        (
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("```")
        ),
        "",
    )
    if first_non_code_line and "import " not in first_non_code_line:
        summary = first_non_code_line[:240]
    return summary, script, None


def _as_record(
    server_module: ModuleType,
    value: object,
) -> dict[str, object] | None:
    del server_module
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return None


def _as_string(server_module: ModuleType, value: object) -> str | None:
    del server_module
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _as_non_empty_string(server_module: ModuleType, value: object) -> str | None:
    del server_module
    if isinstance(value, str) and value:
        return value
    return None


def _read_path(
    server_module: ModuleType, record: dict[str, object], path: str
) -> object | None:
    cursor: object = record
    for key in path.split("."):
        current = server_module._as_record(cursor)
        if current is None or key not in current:
            return None
        cursor = current[key]
    return cursor


def _collect_text(
    server_module: ModuleType, value: object, depth: int = 0
) -> list[str]:
    if value is None or depth > 4:
        return []

    if isinstance(value, str):
        return [value] if value.strip() else []

    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            lines.extend(server_module._collect_text(item, depth + 1))
        return lines

    if isinstance(value, dict):
        record = cast(dict[str, object], value)
        priority_keys = [
            "text",
            "content",
            "message",
            "output_text",
            "delta",
            "summary",
            "result",
            "error",
        ]
        for key in priority_keys:
            if key in record:
                found = server_module._collect_text(record[key], depth + 1)
                if found:
                    return found

        ignored = {
            "type",
            "id",
            "sessionID",
            "sessionId",
            "messageID",
            "messageId",
            "timestamp",
            "time",
            "tokens",
            "cost",
            "snapshot",
            "reason",
        }
        fallback: list[str] = []
        for key, child in record.items():
            if key in ignored:
                continue
            fallback.extend(server_module._collect_text(child, depth + 1))
        return fallback

    return []


def _join_collected_text(server_module: ModuleType, value: object) -> str | None:
    lines = server_module._collect_text(value)
    if not lines:
        return None
    joined = "".join(lines).strip()
    return joined or None


def _truncate_output(
    server_module: ModuleType, text: str, *, max_chars: int = 12_000
) -> str:
    del server_module
    if len(text) <= max_chars:
        return text
    keep_tail = int(max_chars * 0.75)
    omitted = len(text) - keep_tail
    return f"[truncated {omitted} chars]\n{text[-keep_tail:]}"


def _resolve_plot_response(
    server_module: ModuleType,
    *,
    session_id: str | None,
    version_id: str | None,
    plot_mode: bool,
    workspace_id: str | None = None,
) -> tuple[Path, str]:
    if plot_mode:
        state = server_module._resolve_plot_mode_workspace(workspace_id)
        if not state.current_plot:
            raise HTTPException(status_code=404, detail="No plot available")
        plot_path = Path(state.current_plot)
        plot_type = state.plot_type or "raster"
        return plot_path, plot_type

    normalized_session_id = session_id.strip() if session_id is not None else ""
    if normalized_session_id:
        session = server_module._get_session_by_id(normalized_session_id)
    else:
        session = server_module._session

    if session is None:
        plot_mode_state = server_module._plot_mode
        if plot_mode_state is not None and plot_mode_state.current_plot:
            return Path(
                plot_mode_state.current_plot
            ), plot_mode_state.plot_type or "raster"
        raise HTTPException(status_code=404, detail="No plot available")

    normalized_version_id = version_id.strip() if version_id is not None else ""
    if normalized_version_id:
        version = server_module._get_version(session, normalized_version_id)
        return Path(version.plot_artifact_path), version.plot_type

    if not session.current_plot:
        raise HTTPException(status_code=404, detail="No plot available")
    return Path(session.current_plot), session.plot_type
