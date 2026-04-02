"""Plot-mode autonomous review helpers extracted from openplot.server."""

from __future__ import annotations

import time
from types import ModuleType

from .models import FixRunner, PlotModeChatMessage, PlotModePhase, PlotModeState


def _build_plot_mode_review_prompt(
    server_module: ModuleType,
    state: PlotModeState,
    *,
    iteration_index: int,
    focus_direction: str,
) -> str:
    profile = server_module._selected_data_profile(state)
    lines = [
        "Review and improve the current OpenPlot draft for publication quality.",
        "Preferred response format is OPENPLOT_RESULT_BEGIN/END JSON with summary, script, and optional done boolean.",
        "If the plot is already strong, you may keep the same script and set done=true.",
        "Write the user-facing summary in plain language and avoid internal implementation jargon.",
        f"Autonomous review pass: {iteration_index}",
        f"Current review focus: {focus_direction}.",
    ]
    if profile is not None:
        lines.extend(
            [
                f"Confirmed source: {profile.source_label}",
                f"Source path: {profile.file_path}",
            ]
        )
        for region in server_module._tabular_regions_for_profile(profile)[:8]:
            bounds = (
                server_module._bounds_from_sheet_bounds(region.bounds)
                if region.bounds
                else None
            )
            lines.append(
                f"Confirmed region: {server_module._format_sheet_region_label(region.sheet_name, bounds)}"
            )
    else:
        server_module._append_active_resolved_source_context(
            lines,
            state,
            heading="Confirmed datasource(s):",
        )
    if state.current_plot:
        lines.append(f"Latest rendered preview path: {state.current_plot}")
        lines.append(
            "If your runner can inspect local files, use that preview as grounding for typography, spacing, legend placement, and visual polish."
        )
    lines.append(
        "Focus on typography, label clarity, margins, legend placement, and overall visual polish for grant applications or top-conference papers."
    )
    return "\n".join(lines)


async def _run_plot_mode_autonomous_reviews(
    server_module: ModuleType,
    *,
    state: PlotModeState,
    runner: FixRunner,
    model: str,
    variant: str | None,
    summary_message: PlotModeChatMessage | None,
) -> None:
    pass_index = 2
    stalled_passes = 0
    started_at = time.monotonic()
    latest_summary = (
        summary_message.content if summary_message is not None else ""
    ).strip()
    initial_focus = server_module._plot_mode_autonomous_focus_direction(pass_index)
    status_message = server_module._create_plot_mode_message(
        state,
        role="assistant",
        content=f"Refining plot: {initial_focus}.",
        metadata=server_module._plot_mode_refining_metadata(initial_focus),
    )

    async def _finalize_refining_status() -> None:
        nonlocal summary_message
        final_summary = server_module._truncate_output(latest_summary)
        if final_summary:
            if summary_message is None:
                server_module._append_plot_mode_message(
                    state,
                    role="assistant",
                    content=final_summary,
                )
            else:
                server_module._set_plot_mode_message_content(
                    state,
                    summary_message,
                    final_summary,
                    final=True,
                )
        server_module._remove_plot_mode_message(state, status_message.id)
        await server_module._broadcast_plot_mode_state(state)

    while True:
        elapsed = time.monotonic() - started_at
        if elapsed >= server_module._plot_mode_autonomous_watchdog_s:
            await _finalize_refining_status()
            return

        focus_direction = server_module._plot_mode_autonomous_focus_direction(
            pass_index
        )
        previous_script = (state.current_script or "").strip()
        state.phase = PlotModePhase.self_review
        server_module._set_plot_mode_message_content(
            state,
            status_message,
            f"Refining plot: {focus_direction}.",
            final=True,
        )
        server_module._set_plot_mode_message_metadata(
            state,
            status_message,
            server_module._plot_mode_refining_metadata(focus_direction),
        )
        await server_module._broadcast_plot_mode_state(state)

        result = await server_module._run_plot_mode_generation(
            state=state,
            runner=runner,
            message=server_module._build_plot_mode_review_prompt(
                state,
                iteration_index=pass_index,
                focus_direction=focus_direction,
            ),
            model=model,
            variant=variant,
            assistant_message=PlotModeChatMessage(role="assistant", content=""),
        )
        ok, error_message = server_module._apply_plot_mode_result(state, result=result)
        if not ok:
            if latest_summary and summary_message is not None:
                server_module._set_plot_mode_message_content(
                    state,
                    summary_message,
                    server_module._truncate_output(latest_summary),
                    final=True,
                )
            server_module._remove_plot_mode_message(state, status_message.id)
            server_module._append_plot_mode_message(
                state,
                role="error",
                content=error_message or "Autonomous review failed",
            )
            await server_module._broadcast_plot_mode_state(state)
            return

        if result.assistant_text.strip():
            latest_summary = result.assistant_text.strip()
        await server_module._broadcast_plot_mode_preview(state)

        current_script = (state.current_script or "").strip()
        if current_script == previous_script:
            stalled_passes += 1
        else:
            stalled_passes = 0

        if result.done_hint is True and stalled_passes >= 1:
            await _finalize_refining_status()
            return

        if stalled_passes >= server_module._plot_mode_autonomous_stall_limit:
            await _finalize_refining_status()
            return

        pass_index += 1
