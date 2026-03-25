"""Plot mode workflow service helpers."""

from __future__ import annotations

import asyncio
import mimetypes
import re
from pathlib import Path
from typing import TYPE_CHECKING, cast

from fastapi import HTTPException

from ..models import PlotModeState
from . import sessions as session_services
from .naming import normalize_workspace_name

if TYPE_CHECKING:
    from ..api.schemas import (
        PlotModeChatRequest,
        PlotModeFinalizeRequest,
        PlotModePathSuggestionsRequest,
        PlotModeQuestionAnswerRequest,
        PlotModeSelectPathsRequest,
        PlotModeSettingsRequest,
        PlotModeTabularHintRequest,
    )
    from .runtime import BackendRuntime


def get_plot_mode_state(runtime: "BackendRuntime") -> dict[str, object]:
    return session_services.build_plot_mode_payload(runtime)


async def set_plot_mode_files() -> None:
    raise HTTPException(
        status_code=410,
        detail=(
            "File uploads are no longer supported in plot mode. "
            "Use path selection endpoints instead."
        ),
    )


async def suggest_plot_mode_paths(
    body: "PlotModePathSuggestionsRequest",
    runtime: "BackendRuntime",
) -> dict[str, object]:
    from .. import server

    def _suggest() -> dict[str, object]:
        server._ensure_session_store_loaded()
        if server._runtime_active_session_value() is not None:
            raise HTTPException(
                status_code=409,
                detail="Annotation mode is active; restart without a script to use plot mode.",
            )

        selection_type = body.selection_type
        query = body.query.strip()
        base_dir = server._plot_mode_workspace_base_dir(body.workspace_id)
        parent_dir, suggestions = server._list_path_suggestions(
            query=query,
            selection_type=selection_type,
            base_dir=base_dir,
        )
        return {
            "query": query,
            "selection_type": selection_type,
            "base_dir": str(parent_dir.resolve()),
            "suggestions": suggestions,
        }

    return server._with_runtime(runtime, _suggest)


async def select_plot_mode_paths(
    body: "PlotModeSelectPathsRequest",
    runtime: "BackendRuntime",
) -> dict[str, object]:
    from .. import server

    normalized_paths: list[str] = []
    for item in body.paths:
        text = item.strip()
        if text:
            normalized_paths.append(text)

    selection_type = body.selection_type
    if not normalized_paths:
        raise HTTPException(status_code=400, detail="No paths provided")

    if selection_type == "script":

        def _select_script_path() -> dict[str, object]:
            if len(normalized_paths) != 1:
                raise HTTPException(
                    status_code=400,
                    detail="Script selection expects exactly one .py path",
                )

            state = server._resolve_plot_mode_workspace(
                body.workspace_id,
                create_if_missing=True,
            )
            base_dir = server._plot_mode_picker_base_dir(state)
            script_path = server._resolve_selected_file_path(
                raw_path=normalized_paths[0],
                selection_type="script",
                base_dir=base_dir,
            )
            discard_empty_workspace = not server._plot_mode_has_user_content(state)
            result = server.init_session_from_script(script_path, runtime=runtime)
            if result.success and discard_empty_workspace:
                server._delete_plot_mode_snapshot(
                    state=state, clear_active_snapshot=False
                )
            if not result.success:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": result.error,
                        "stderr": result.stderr,
                        "stdout": result.stdout,
                    },
                )

            session = server.get_session()
            server._rebuild_revision_history(session)
            return server._bootstrap_payload(
                mode="annotation", session=session, plot_mode=None
            )

        return server._with_runtime(runtime, _select_script_path)

    def _select_data_paths() -> tuple[object, dict[str, object]]:
        server._ensure_session_store_loaded()
        if server._runtime_active_session_value() is not None:
            raise HTTPException(
                status_code=409,
                detail="Annotation mode is active; restart without a script to use plot mode.",
            )

        state = server._resolve_plot_mode_workspace(
            body.workspace_id, create_if_missing=True
        )
        base_dir = server._plot_mode_picker_base_dir(state)

        if state.files:
            raise HTTPException(
                status_code=409,
                detail="No more files can be added to this workspace. Use New workspace to start over.",
            )

        selected_files = []
        seen_paths: set[str] = set()
        for raw_path in normalized_paths:
            resolved_path = server._resolve_selected_file_path(
                raw_path=raw_path,
                selection_type="data",
                base_dir=base_dir,
            )
            key = str(resolved_path)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            try:
                size_bytes = resolved_path.stat().st_size
            except OSError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Failed to inspect file '{resolved_path}': {exc}",
                ) from exc

            content_type = mimetypes.guess_type(str(resolved_path))[0] or ""
            selected_files.append(
                server.PlotModeFile(
                    name=resolved_path.name,
                    stored_path=key,
                    size_bytes=size_bytes,
                    content_type=content_type,
                    is_python=False,
                )
            )

        if not selected_files:
            raise HTTPException(status_code=400, detail="No data files selected")

        state.files = selected_files
        state.phase = server.PlotModePhase.profiling_data
        server._promote_plot_mode_workspace(state)
        server._populate_plot_mode_data_messages(state)
        server._touch_plot_mode(state)
        return state, server._bootstrap_payload(
            mode="plot", session=None, plot_mode=state
        )

    state, payload = server._with_runtime(runtime, _select_data_paths)
    await server._broadcast_plot_mode_state(state)
    return payload


async def update_plot_mode_settings(
    body: "PlotModeSettingsRequest",
    runtime: "BackendRuntime",
) -> dict[str, object]:
    from .. import server

    def _update() -> PlotModeState:
        server._ensure_session_store_loaded()
        if server._runtime_active_session_value() is not None:
            raise HTTPException(
                status_code=409,
                detail="Annotation mode is active; plot mode settings are unavailable.",
            )

        state = server._resolve_plot_mode_workspace(
            body.workspace_id, create_if_missing=True
        )
        state.execution_mode = server.PlotModeExecutionMode(body.execution_mode)
        server._touch_plot_mode(state)
        return state

    state = cast(PlotModeState, server._with_runtime(runtime, _update))
    await server._broadcast_plot_mode_state(state)
    return {"status": "ok", "plot_mode": state.model_dump(mode="json")}


async def submit_plot_mode_tabular_hint(
    body: "PlotModeTabularHintRequest",
    runtime: "BackendRuntime",
) -> dict[str, object]:
    from .. import server

    def _resolve() -> tuple[PlotModeState, object]:
        server._ensure_session_store_loaded()
        if server._runtime_active_session_value() is not None:
            raise HTTPException(
                status_code=409,
                detail="Annotation mode is active; tabular selection is unavailable.",
            )

        state = server._resolve_plot_mode_workspace(body.workspace_id)
        server._sync_plot_mode_runner_selection(
            state, runner=body.runner, model=body.model, variant=body.variant
        )
        selector = state.tabular_selector
        if selector is None or selector.id != body.selector_id:
            raise HTTPException(
                status_code=409,
                detail="No matching tabular source selector is active.",
            )
        return state, selector

    state, selector = cast(
        tuple[PlotModeState, object],
        server._with_runtime(runtime, _resolve),
    )

    regions_payload = [
        {
            "sheet_id": region.sheet_id,
            "row_start": region.row_start,
            "row_end": region.row_end,
            "col_start": region.col_start,
            "col_end": region.col_end,
        }
        for region in body.regions
    ]
    if not regions_payload:
        singular_values = [
            body.sheet_id,
            body.row_start,
            body.row_end,
            body.col_start,
            body.col_end,
        ]
        if all(value is not None for value in singular_values):
            regions_payload = [
                {
                    "sheet_id": cast(str, body.sheet_id),
                    "row_start": cast(int, body.row_start),
                    "row_end": cast(int, body.row_end),
                    "col_start": cast(int, body.col_start),
                    "col_end": cast(int, body.col_end),
                }
            ]
    if not regions_payload:
        raise HTTPException(
            status_code=400,
            detail="Mark at least one spreadsheet region before continuing.",
        )

    selected_regions = []
    for region_payload in regions_payload:
        sheet = next(
            (
                sheet
                for sheet in selector.sheets
                if sheet.id == cast(str, region_payload["sheet_id"])
            ),
            None,
        )
        if sheet is None or not sheet.preview_rows:
            raise HTTPException(
                status_code=400,
                detail="Selected sheet preview is unavailable.",
            )

        max_row_index = len(sheet.preview_rows) - 1
        max_col_index = max((len(row) for row in sheet.preview_rows), default=0) - 1
        if max_row_index < 0 or max_col_index < 0:
            raise HTTPException(
                status_code=400,
                detail="Selected sheet does not contain previewable cells.",
            )

        row_start = max(
            0,
            min(
                cast(int, region_payload["row_start"]),
                cast(int, region_payload["row_end"]),
                max_row_index,
            ),
        )
        row_end = max(
            0,
            min(
                max(
                    cast(int, region_payload["row_start"]),
                    cast(int, region_payload["row_end"]),
                ),
                max_row_index,
            ),
        )
        col_start = max(
            0,
            min(
                cast(int, region_payload["col_start"]),
                cast(int, region_payload["col_end"]),
                max_col_index,
            ),
        )
        col_end = max(
            0,
            min(
                max(
                    cast(int, region_payload["col_start"]),
                    cast(int, region_payload["col_end"]),
                ),
                max_col_index,
            ),
        )
        selected_regions.append(
            server.PlotModeTabularSelectionRegion(
                sheet_id=sheet.id,
                sheet_name=sheet.name,
                bounds=server.PlotModeSheetBounds(
                    row_start=row_start,
                    row_end=row_end,
                    col_start=col_start,
                    col_end=col_end,
                ),
            )
        )

    instruction = (body.note or "").strip() or None
    await server._apply_tabular_range_proposal(
        state,
        selector,
        selected_regions=selected_regions,
        instruction=instruction,
        activity_title="Range proposal",
    )
    server._promote_plot_mode_workspace(state)
    await server._broadcast_plot_mode_state(state)
    return {"status": "ok", "plot_mode": state.model_dump(mode="json")}


async def answer_plot_mode_question(
    body: "PlotModeQuestionAnswerRequest",
    runtime: "BackendRuntime",
) -> dict[str, object]:
    from .. import server

    def _resolve() -> tuple[PlotModeState, object, object, list[str], str | None, str]:
        server._ensure_session_store_loaded()
        if server._runtime_active_session_value() is not None:
            raise HTTPException(
                status_code=409,
                detail="Annotation mode is active; plot mode questions are unavailable.",
            )

        state = server._resolve_plot_mode_workspace(body.workspace_id)
        server._sync_plot_mode_runner_selection(
            state, runner=body.runner, model=body.model, variant=body.variant
        )
        pending = state.pending_question_set
        if pending is None or pending.id != body.question_set_id:
            raise HTTPException(
                status_code=409, detail="No matching plot-mode question is pending."
            )

        answer_map = server._answer_map_for_question_set(body)
        answered_questions = server._apply_answers_to_question_set(pending, answer_map)
        first_option_ids, first_answer_text = server._first_answer_for_question_set(
            answered_questions
        )
        answer_summary = server._question_set_answer_summary(answered_questions)
        return (
            state,
            pending,
            answered_questions,
            first_option_ids,
            first_answer_text,
            answer_summary,
        )

    (
        state,
        pending,
        answered_questions,
        first_option_ids,
        first_answer_text,
        answer_summary,
    ) = cast(
        tuple[PlotModeState, object, object, list[str], str | None, str],
        server._with_runtime(runtime, _resolve),
    )

    if pending.purpose == "select_data_source":
        option_ids = first_option_ids
        answer_text = first_answer_text or ""
        if not option_ids:
            if not answer_text:
                raise HTTPException(
                    status_code=400,
                    detail="Select one of the proposed data sources before continuing.",
                )
            lowered_answer = answer_text.lower()
            inferred = next(
                (
                    profile.id
                    for profile in state.data_profiles
                    if lowered_answer in profile.source_label.lower()
                    or lowered_answer in profile.file_name.lower()
                    or (
                        profile.table_name is not None
                        and lowered_answer in profile.table_name.lower()
                    )
                ),
                None,
            )
            if inferred is None:
                raise HTTPException(
                    status_code=400,
                    detail="I could not map that answer to one of the proposed data sources.",
                )
            option_ids = [inferred]
        selected_id = option_ids[0]
        profile = next(
            (profile for profile in state.data_profiles if profile.id == selected_id),
            None,
        )
        if profile is None:
            raise HTTPException(
                status_code=400,
                detail="Selected data source is no longer available.",
            )

        state.pending_question_set = None
        server._clear_selected_plot_mode_source_context(state)
        state.latest_plan_summary = ""
        state.latest_plan_outline = []
        state.latest_plan_plot_type = ""
        state.latest_plan_actions = []
        server._mark_question_set_answered(
            state,
            body.question_set_id,
            answered_questions=answered_questions,
        )
        server._append_plot_mode_message(
            state, role="user", content=f"Use {profile.source_label}."
        )
        state.phase = server.PlotModePhase.awaiting_data_choice
        server._present_profile_for_confirmation(state, profile)
        await server._broadcast_plot_mode_state(state)
        return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

    if pending.purpose == "confirm_tabular_range":
        profile_id = pending.source_ids[0] if pending.source_ids else ""
        profile = next(
            (profile for profile in state.data_profiles if profile.id == profile_id),
            None,
        )
        if profile is None:
            raise HTTPException(
                status_code=400,
                detail="The proposed spreadsheet range is no longer available.",
            )

        decision = first_option_ids[0] if first_option_ids else ""
        answer_text = first_answer_text or ""
        if not decision and answer_text:
            lowered = answer_text.lower()
            looks_like_range_note = (
                any(
                    token in lowered
                    for token in ["column", "columns", "row", "rows", "only"]
                )
                or bool(
                    re.search(r"\b[a-z]{1,3}\s*(?::|-|and)\s*[a-z]{1,3}\b", lowered)
                )
                or bool(re.search(r"\b[a-z]{1,3}\d+\s*:\s*[a-z]{1,3}\d+\b", lowered))
            )
            if looks_like_range_note:
                decision = "re_infer_from_note"
            elif any(
                token in lowered
                for token in ["use", "yes", "confirm", "correct", "looks good"]
            ):
                decision = "use_proposed_range"
            elif any(
                token in lowered
                for token in ["adjust", "redraw", "reselect", "new hint", "mark"]
            ):
                decision = "adjust_selection"
            else:
                decision = "re_infer_from_note"

        if decision not in {
            "use_proposed_range",
            "adjust_selection",
            "re_infer_from_note",
        }:
            raise HTTPException(
                status_code=400,
                detail="Confirm the proposed regions, mark new regions, or give a note to re-infer them.",
            )

        state.pending_question_set = None
        server._mark_question_set_answered(
            state,
            body.question_set_id,
            answered_questions=answered_questions,
        )

        if decision == "use_proposed_range":
            ok, error_message = await server._start_plot_mode_planning_for_profile(
                state,
                profile,
            )
            if not ok:
                return {
                    "status": "error",
                    "plot_mode": state.model_dump(mode="json"),
                    "error": error_message or "Planning failed",
                }
            return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

        server._clear_selected_plot_mode_source_context(state)
        if decision == "adjust_selection":
            if state.tabular_selector is None:
                raise HTTPException(
                    status_code=400,
                    detail="Range selection is unavailable for this source.",
                )
            state.tabular_selector.requires_user_hint = True
            state.tabular_selector.inferred_profile_id = None
            state.phase = server.PlotModePhase.awaiting_data_choice
            await server._broadcast_plot_mode_state(state)
            return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

        if state.tabular_selector is None:
            raise HTTPException(
                status_code=400,
                detail="Range re-inference is unavailable for this source.",
            )
        if not state.tabular_selector.selected_regions:
            raise HTTPException(
                status_code=400,
                detail="No tabular regions are available to re-infer the range.",
            )
        note_text = answer_text.strip()
        if not note_text:
            raise HTTPException(
                status_code=400,
                detail="Add a note describing how the range should change.",
            )
        await server._apply_tabular_range_proposal(
            state,
            state.tabular_selector,
            selected_regions=state.tabular_selector.selected_regions,
            instruction=note_text,
            activity_title="Range re-proposal",
        )
        await server._broadcast_plot_mode_state(state)
        return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

    if pending.purpose == "confirm_data_preview":
        profile_id = pending.source_ids[0] if pending.source_ids else ""
        profile = next(
            (profile for profile in state.data_profiles if profile.id == profile_id),
            None,
        )
        if profile is None:
            raise HTTPException(
                status_code=400,
                detail="The previewed data source is no longer available.",
            )

        decision = first_option_ids[0] if first_option_ids else ""
        answer_text = first_answer_text or ""
        if not decision and answer_text:
            lowered = answer_text.lower()
            if any(token in lowered for token in ["use", "yes", "confirm", "correct"]):
                decision = "use_preview"
            elif any(
                token in lowered
                for token in ["adjust", "different", "change", "another"]
            ):
                if (
                    state.tabular_selector is not None
                    and profile.source_file_id == state.tabular_selector.file_id
                ):
                    decision = "adjust_selection"
                else:
                    decision = "choose_other_source"

        if decision not in {"use_preview", "adjust_selection", "choose_other_source"}:
            raise HTTPException(
                status_code=400,
                detail="Confirm the preview or choose how to adjust the source.",
            )

        state.pending_question_set = None
        server._mark_question_set_answered(
            state,
            body.question_set_id,
            answered_questions=answered_questions,
        )

        if decision == "use_preview":
            ok, error_message = await server._start_plot_mode_planning_for_profile(
                state,
                profile,
            )
            if not ok:
                return {
                    "status": "error",
                    "plot_mode": state.model_dump(mode="json"),
                    "error": error_message or "Planning failed",
                }
            return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

        server._clear_selected_plot_mode_source_context(state)
        if decision == "adjust_selection":
            if state.tabular_selector is None:
                raise HTTPException(
                    status_code=400,
                    detail="Range selection is unavailable for this source.",
                )
            state.tabular_selector.requires_user_hint = True
            state.tabular_selector.inferred_profile_id = None
            state.phase = server.PlotModePhase.awaiting_data_choice
            await server._broadcast_plot_mode_state(state)
            return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

        state.phase = server.PlotModePhase.awaiting_data_choice
        question_set = server.PlotModeQuestionSet(
            purpose="select_data_source",
            title="Choose a source",
            source_ids=[profile.id for profile in state.data_profiles],
        )
        options = [
            server.PlotModeQuestionOption(
                id=item.id,
                label=item.source_label,
                description=", ".join(item.columns[:4])
                if item.columns
                else item.summary,
            )
            for item in state.data_profiles[:8]
        ]
        question_set.questions = [
            server.PlotModeQuestionItem(
                title="Available sources",
                prompt="Which data source should I preview next?",
                options=options,
                allow_custom_answer=True,
            )
        ]
        server._append_plot_mode_question_set(
            state,
            question_set=question_set,
            lead_content="Which data source should I preview next?",
        )
        await server._broadcast_plot_mode_state(state)
        return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

    if pending.purpose == "continue_plot_planning":
        decision = first_option_ids[0] if first_option_ids else ""
        answer_text = first_answer_text or ""
        if not decision and answer_text:
            lowered = answer_text.lower()
            if any(token in lowered for token in ["approve", "continue", "go", "yes"]):
                decision = "continue_planning"
            elif any(token in lowered for token in ["revise", "change", "adjust"]):
                decision = "revise_goal"

        if decision not in {"continue_planning", "revise_goal"} and answer_summary:
            lowered_summary = answer_summary.lower()
            if any(
                token in lowered_summary for token in ["revise", "change", "adjust"]
            ):
                decision = "revise_goal"
            else:
                decision = "continue_planning"

        if decision not in {"continue_planning", "revise_goal"}:
            raise HTTPException(
                status_code=400,
                detail="Choose whether to continue planning or revise the goal.",
            )

        state.pending_question_set = None
        server._mark_question_set_answered(
            state,
            body.question_set_id,
            answered_questions=answered_questions,
        )

        if decision == "revise_goal":
            state.phase = server.PlotModePhase.awaiting_prompt
            if answer_summary:
                server._append_plot_mode_message(
                    state, role="user", content=answer_summary
                )
            await server._broadcast_plot_mode_state(state)
            return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

        approval_message = answer_summary or answer_text or "Approved. Continue."
        server._append_plot_mode_message(state, role="user", content=approval_message)

        planning_message = (
            state.latest_user_goal.strip()
            or state.latest_plan_summary.strip()
            or approval_message
        )
        if answer_summary:
            planning_message = f"{planning_message}\n\nUser answers:\n{answer_summary}"

        (
            ok,
            error_message,
        ) = await server._continue_plot_mode_planning_with_selected_runner(
            state=state,
            planning_message=planning_message,
        )
        if not ok:
            return {
                "status": "error",
                "plot_mode": state.model_dump(mode="json"),
                "error": error_message or "Planning failed",
            }
        return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

    if pending.purpose == "kickoff_plot_planning":
        decision = first_option_ids[0] if first_option_ids else ""
        answer_text = (first_answer_text or "").strip()
        if not decision and answer_text:
            lowered = answer_text.lower()
            if any(token in lowered for token in ["proceed", "continue", "go", "yes"]):
                decision = "proceed_to_planning"
            else:
                decision = "custom_guidance"

        if decision not in {"proceed_to_planning", "custom_guidance"}:
            raise HTTPException(
                status_code=400,
                detail="Choose whether to proceed to planning or add guidance first.",
            )

        state.pending_question_set = None
        server._mark_question_set_answered(
            state,
            body.question_set_id,
            answered_questions=answered_questions,
        )

        planning_message = answer_text or "Proceed to plot planning."
        state.latest_user_goal = planning_message
        server._append_plot_mode_message(state, role="user", content=planning_message)

        (
            ok,
            error_message,
        ) = await server._continue_plot_mode_planning_with_selected_runner(
            state=state,
            planning_message=planning_message,
        )
        if not ok:
            return {
                "status": "error",
                "plot_mode": state.model_dump(mode="json"),
                "error": error_message or "Planning failed",
            }
        return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

    if pending.purpose == "approve_plot_plan":
        decision = first_option_ids[0] if first_option_ids else ""
        answer_text = first_answer_text or ""
        if not decision and answer_text:
            lowered = answer_text.lower()
            if any(token in lowered for token in ["start", "go", "yes", "approve"]):
                decision = "start_draft"
            elif any(token in lowered for token in ["revise", "change", "adjust"]):
                decision = "revise_plan"

        if decision not in {"start_draft", "revise_plan"} and answer_summary:
            lowered_summary = answer_summary.lower()
            if any(
                token in lowered_summary for token in ["revise", "change", "adjust"]
            ):
                decision = "revise_plan"
            else:
                decision = "start_draft"

        if decision not in {"start_draft", "revise_plan"}:
            raise HTTPException(
                status_code=400,
                detail="Choose whether to start drafting or revise the plan.",
            )

        state.pending_question_set = None
        server._mark_question_set_answered(
            state,
            body.question_set_id,
            answered_questions=answered_questions,
        )

        if decision == "revise_plan":
            state.phase = server.PlotModePhase.awaiting_prompt
            if answer_summary:
                server._append_plot_mode_message(
                    state, role="user", content=answer_summary
                )
            server._append_plot_mode_message(
                state,
                role="assistant",
                content=(
                    "Got it. Tell me what to adjust in plot type, style, data scope, or layout, "
                    "and I will update the plan."
                ),
            )
            await server._broadcast_plot_mode_state(state)
            return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

        approval_message = (
            answer_summary or answer_text or "Approved. Start drafting now."
        )
        server._append_plot_mode_message(state, role="user", content=approval_message)

        runner = server._resolve_available_runner(
            server._normalize_fix_runner(
                state.selected_runner, default=server._default_fix_runner
            )
        )
        state.selected_runner = runner
        server._ensure_runner_is_available(runner)
        model = str(
            state.selected_model or ""
        ).strip() or server._runner_default_model_id(runner)
        normalized_variant = (
            str(state.selected_variant).strip() if state.selected_variant else ""
        )
        variant = normalized_variant or None

        draft_message = (
            state.latest_user_goal or state.latest_plan_summary or approval_message
        )
        if answer_summary:
            draft_message = f"{draft_message}\n\nUser answers:\n{answer_summary}"

        ok, error_message = await server._execute_plot_mode_draft(
            state=state,
            runner=runner,
            model=model,
            variant=variant,
            draft_message=draft_message,
        )
        if not ok:
            return {
                "status": "error",
                "plot_mode": state.model_dump(mode="json"),
                "error": error_message or "Plot generation failed",
            }
        return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

    raise HTTPException(status_code=400, detail="Unsupported plot-mode question type")


async def run_plot_mode_chat(
    body: "PlotModeChatRequest",
    runtime: "BackendRuntime",
) -> dict[str, object]:
    from .. import server

    async def _chat() -> dict[str, object]:
        server._ensure_session_store_loaded()
        if server._runtime_active_session_value() is not None:
            raise HTTPException(
                status_code=409,
                detail="Annotation mode is active; plot mode chat is unavailable.",
            )

        state = server._resolve_plot_mode_workspace(body.workspace_id)
        if state.phase == server.PlotModePhase.awaiting_files or not state.files:
            raise HTTPException(
                status_code=409,
                detail="Select dataset files before starting chat.",
            )
        if state.pending_question_set is not None:
            raise HTTPException(
                status_code=409,
                detail="Answer the pending plot-mode confirmation before sending a new prompt.",
            )
        if (
            state.tabular_selector is not None
            and state.tabular_selector.requires_user_hint
        ):
            raise HTTPException(
                status_code=409,
                detail="Mark the relevant cells in the tabular selector before continuing.",
            )
        if (
            server._selected_data_profile(state) is None
            and state.data_profiles
            and not state.active_resolved_source_ids
        ):
            raise HTTPException(
                status_code=409,
                detail="Choose the data source to plot before drafting a figure.",
            )

        message = body.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="Missing message")

        runner = server._resolve_available_runner(
            server._normalize_fix_runner(
                body.runner or state.selected_runner,
                default=server._default_fix_runner,
            )
        )
        state.selected_runner = runner
        server._ensure_runner_is_available(runner)
        model = str(body.model or state.selected_model or "").strip()
        if not model:
            model = server._runner_default_model_id(runner)

        variant_raw = body.variant
        variant = str(variant_raw).strip() if variant_raw is not None else ""
        normalized_variant = variant or None

        try:
            available_models = await asyncio.to_thread(
                server._refresh_runner_models_cache,
                runner,
            )
        except RuntimeError:
            available_models = []

        if not body.model and available_models:
            selected_model = next(
                (entry for entry in available_models if entry.id == model),
                None,
            )
            if selected_model is None:
                resolved_model, resolved_variant = (
                    server._resolve_runner_default_model_and_variant(
                        runner=runner,
                        models=available_models,
                        preferred_runner=runner,
                        preferred_model=model,
                        preferred_variant=normalized_variant,
                    )
                )
                model = resolved_model or model
                if normalized_variant and resolved_variant:
                    normalized_variant = resolved_variant
                elif selected_model is None:
                    normalized_variant = ""

        server._validate_runner_model_selection(
            runner=runner,
            model=model,
            variant=normalized_variant,
            models=available_models,
        )

        state.selected_runner = runner
        state.selected_model = model
        state.selected_variant = normalized_variant or ""
        state.latest_user_goal = message
        state.last_error = None
        server._promote_plot_mode_workspace(state)
        server._append_plot_mode_message(state, role="user", content=message)
        ok, error_message = await server._continue_plot_mode_planning(
            state=state,
            runner=runner,
            model=model,
            variant=normalized_variant,
            planning_message=message,
        )
        if not ok:
            return {
                "status": "error",
                "plot_mode": state.model_dump(mode="json"),
                "error": error_message or "Planning failed",
            }

        return {
            "status": "ok",
            "plot_mode": state.model_dump(mode="json"),
        }

    return await server._with_runtime_async(runtime, _chat)


async def finalize_plot_mode(
    body: "PlotModeFinalizeRequest",
    runtime: "BackendRuntime",
) -> dict[str, object]:
    from .. import server

    def _finalize() -> tuple[object, dict[str, object]]:
        server._ensure_session_store_loaded()
        if server._runtime_active_session_value() is not None:
            session = server.get_session()
            server._rebuild_revision_history(session)
            return session, server._bootstrap_payload(
                mode="annotation", session=session, plot_mode=None
            )

        state = server._resolve_plot_mode_workspace(body.workspace_id)
        script = (state.current_script or "").strip()
        if not script:
            raise HTTPException(
                status_code=409,
                detail="No generated script is available yet.",
            )

        script_path = server._plot_mode_generated_script_path(state)
        script_path.write_text(script, encoding="utf-8")

        annotation_session_id = server._new_id()
        result = server.init_session_from_script(
            script_path,
            inherit_id=annotation_session_id,
            inherit_workspace_id=state.id,
            inherit_workspace_name=state.workspace_name or None,
            inherit_artifacts_root=str(server._plot_mode_artifacts_dir(state)),
            runtime=runtime,
        )
        if not result.success:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": result.error,
                    "stderr": result.stderr,
                    "stdout": result.stdout,
                },
            )

        session = server.get_session()
        server._rebuild_revision_history(session)
        return session, server._bootstrap_payload(
            mode="annotation", session=session, plot_mode=None
        )

    session, payload = server._with_runtime(runtime, _finalize)
    await server._broadcast(
        {
            "type": "plot_mode_completed",
            "session": session.model_dump(mode="json"),
        }
    )
    return payload


async def rename_plot_mode_workspace(
    runtime: "BackendRuntime",
    body: dict[str, object] | None,
) -> dict[str, object]:
    from .. import server

    def _rename() -> dict[str, object]:
        server._ensure_session_store_loaded()
        requested_id = body.get("id") if isinstance(body, dict) else None
        raw_name = (
            (body.get("workspace_name") or body.get("name") or "")
            if isinstance(body, dict)
            else ""
        )

        active_plot_mode = server._runtime_plot_mode_state_value()
        if requested_id and (
            active_plot_mode is None or active_plot_mode.id != requested_id
        ):
            state = server._load_plot_mode_workspace_by_id(requested_id)
            if state is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Plot-mode workspace not found: {requested_id}",
                )
        else:
            state = server._get_plot_mode_state()

        server._promote_plot_mode_workspace(state)
        state.workspace_name = normalize_workspace_name(raw_name)
        server._touch_plot_mode(state)
        workspace_path = server._plot_mode_workspace_snapshot_path(state)
        payload = cast(dict[str, object], state.model_dump(mode="json"))
        server._write_json_atomic(workspace_path, payload)
        return {"status": "ok", "plot_mode": state.model_dump(mode="json")}

    return server._with_runtime(runtime, _rename)


async def delete_plot_mode_workspace(
    runtime: "BackendRuntime",
    requested_id: str | None,
) -> dict[str, object]:
    from .. import server

    def _delete() -> dict[str, object]:
        server._ensure_session_store_loaded()
        active_plot_mode = server._runtime_plot_mode_state_value()

        if requested_id and (
            active_plot_mode is None or active_plot_mode.id != requested_id
        ):
            target = server._load_plot_mode_workspace_by_id(requested_id)
            if target is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Plot-mode workspace not found: {requested_id}",
                )
            server._delete_plot_mode_snapshot(state=target, clear_active_snapshot=False)
        else:
            if active_plot_mode is None:
                raise HTTPException(
                    status_code=404, detail="No active plot-mode workspace"
                )
            doomed = active_plot_mode
            server._reset_plot_mode_runtime_state()
            server._delete_plot_mode_snapshot(state=doomed, clear_active_snapshot=True)

        active_session = server._runtime_active_session_value()
        active_plot_mode = server._runtime_plot_mode_state_value()
        if active_session is not None:
            session = server.get_session()
            server._rebuild_revision_history(session)
            return server._bootstrap_payload(
                mode="annotation", session=session, plot_mode=None
            )

        if active_plot_mode is not None:
            return server._bootstrap_payload(
                mode="plot", session=None, plot_mode=active_plot_mode
            )

        state = server.init_plot_mode_session(workspace_dir=None)
        return server._bootstrap_payload(mode="plot", session=None, plot_mode=state)

    return server._with_runtime(runtime, _delete)


async def activate_plot_mode(
    runtime: "BackendRuntime",
    requested_id: str | None,
) -> dict[str, object]:
    from .. import server

    def _activate() -> dict[str, object]:
        server._ensure_session_store_loaded()
        active_plot_mode = server._runtime_plot_mode_state_value()
        if requested_id and (
            active_plot_mode is None or active_plot_mode.id != requested_id
        ):
            target = server._load_plot_mode_workspace_by_id(requested_id)
            if target is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Plot-mode workspace not found: {requested_id}",
                )
            if active_plot_mode is not None:
                server._clear_plot_mode_state()
            runtime.store.plot_mode = target
            server._sync_globals_from_runtime(runtime)
            server._save_plot_mode_snapshot(target)

        state = server._get_plot_mode_state()
        server._set_active_session(None, clear_plot_mode=False)
        server.set_workspace_dir(Path(state.workspace_dir))
        return server._bootstrap_payload(mode="plot", session=None, plot_mode=state)

    return server._with_runtime(runtime, _activate)
