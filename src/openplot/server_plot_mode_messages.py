"""Plot-mode message and question-history helpers extracted from openplot.server."""

from __future__ import annotations

from collections.abc import Mapping
from types import ModuleType
from typing import Literal, cast

from .api.schemas import PlotModeQuestionAnswerRequest
from .models import (
    PlotModeChatMessage,
    PlotModeDataProfile,
    PlotModeMessageKind,
    PlotModeMessageMetadata,
    PlotModePhase,
    PlotModeQuestionItem,
    PlotModeQuestionOption,
    PlotModeQuestionSet,
)


def _append_plot_mode_message(
    server_module: ModuleType,
    state,
    *,
    role: Literal["user", "assistant", "error"],
    content: str,
    metadata: PlotModeMessageMetadata | None = None,
) -> None:
    text = content.strip()
    if not text and metadata is None:
        return
    state.messages.append(
        PlotModeChatMessage(role=role, content=text, metadata=metadata)
    )
    server_module._touch_plot_mode(state)


def _create_plot_mode_message(
    server_module: ModuleType,
    state,
    *,
    role: Literal["user", "assistant", "error"],
    content: str = "",
    metadata: PlotModeMessageMetadata | None = None,
) -> PlotModeChatMessage:
    message = PlotModeChatMessage(role=role, content=content, metadata=metadata)
    state.messages.append(message)
    server_module._touch_plot_mode(state)
    return message


def _remove_plot_mode_message(
    server_module: ModuleType, state, message_id: str
) -> None:
    original_len = len(state.messages)
    state.messages = [message for message in state.messages if message.id != message_id]
    if len(state.messages) != original_len:
        server_module._touch_plot_mode(state)


def _set_plot_mode_message_content(
    server_module: ModuleType,
    state,
    message,
    content: str,
    *,
    final: bool = False,
) -> bool:
    normalized = content.strip() if final else content.lstrip("\n")
    if message.content == normalized:
        return False
    message.content = normalized
    server_module._touch_plot_mode(state)
    return True


def _set_plot_mode_message_metadata(
    server_module: ModuleType,
    state,
    message,
    metadata: PlotModeMessageMetadata | None,
) -> bool:
    if message.metadata == metadata:
        return False
    message.metadata = metadata
    server_module._touch_plot_mode(state)
    return True


def _append_plot_mode_activity(
    server_module: ModuleType,
    state,
    *,
    title: str,
    items: list[str],
) -> None:
    metadata = PlotModeMessageMetadata(
        kind=PlotModeMessageKind.activity,
        title=title,
        items=items,
    )
    server_module._append_plot_mode_message(
        state,
        role="assistant",
        content=title,
        metadata=metadata,
    )


def _plot_mode_refining_metadata(
    server_module: ModuleType,
    focus_direction: str,
) -> PlotModeMessageMetadata:
    return PlotModeMessageMetadata(
        kind=PlotModeMessageKind.status,
        title="Refining plot",
        items=[f"Target: {focus_direction}."],
    )


def _append_plot_mode_table_preview(
    server_module: ModuleType,
    state,
    *,
    source_label: str,
    caption: str,
    columns: list[str],
    rows: list[list[str]],
) -> None:
    metadata = PlotModeMessageMetadata(
        kind=PlotModeMessageKind.table_preview,
        title=source_label,
        table_columns=columns,
        table_rows=rows,
        table_caption=caption,
        table_source_label=source_label,
    )
    server_module._append_plot_mode_message(
        state,
        role="assistant",
        content=caption,
        metadata=metadata,
    )


def _append_plot_mode_question_set(
    server_module: ModuleType,
    state,
    *,
    question_set: PlotModeQuestionSet,
    lead_content: str,
) -> None:
    state.pending_question_set = question_set
    metadata = PlotModeMessageMetadata(
        kind=PlotModeMessageKind.question,
        title=question_set.title,
        question_set_id=question_set.id,
        question_set_title=question_set.title,
        questions=question_set.questions,
    )
    server_module._append_plot_mode_message(
        state,
        role="assistant",
        content=lead_content,
        metadata=metadata,
    )


def _mark_question_set_answered(
    server_module: ModuleType,
    state,
    question_set_id: str,
    *,
    answered_questions: list[PlotModeQuestionItem],
) -> None:
    for message in reversed(state.messages):
        metadata = message.metadata
        if metadata is None or metadata.kind != PlotModeMessageKind.question:
            continue
        if metadata.question_set_id != question_set_id:
            continue
        metadata.questions = answered_questions
        break
    server_module._touch_plot_mode(state)


def _answer_map_for_question_set(
    server_module: ModuleType,
    body: PlotModeQuestionAnswerRequest,
) -> dict[str, tuple[list[str], str | None]]:
    del server_module
    answers: dict[str, tuple[list[str], str | None]] = {}
    for item in body.answers:
        answers[item.question_id] = (
            [option_id.strip() for option_id in item.option_ids if option_id.strip()],
            (item.text or "").strip() or None,
        )
    return answers


def _apply_answers_to_question_set(
    server_module: ModuleType,
    question_set: PlotModeQuestionSet,
    answer_map: Mapping[str, tuple[list[str], str | None]],
) -> list[PlotModeQuestionItem]:
    del server_module
    answered_questions: list[PlotModeQuestionItem] = []
    for question in question_set.questions:
        option_ids, answer_text = answer_map.get(question.id, ([], None))
        answered_questions.append(
            question.model_copy(
                update={
                    "answered": bool(option_ids or answer_text),
                    "selected_option_ids": option_ids,
                    "answer_text": answer_text,
                }
            )
        )
    return answered_questions


def _first_answer_for_question_set(
    server_module: ModuleType,
    answered_questions: list[PlotModeQuestionItem],
) -> tuple[list[str], str | None]:
    del server_module
    if not answered_questions:
        return [], None
    question = answered_questions[0]
    return question.selected_option_ids, question.answer_text


def _question_set_answer_summary(
    server_module: ModuleType,
    answered_questions: list[PlotModeQuestionItem],
) -> str:
    del server_module
    lines: list[str] = []
    for question in answered_questions:
        if not question.answered:
            continue
        answers: list[str] = []
        if question.selected_option_ids:
            label_by_id = {option.id: option.label for option in question.options}
            answers.extend(
                label_by_id.get(option_id, option_id)
                for option_id in question.selected_option_ids
            )
        if question.answer_text:
            answers.append(question.answer_text)
        if not answers:
            continue
        lines.append(f"- {question.prompt}: {'; '.join(answers)}")
    return "\n".join(lines)


def _append_profile_preview_card(
    server_module: ModuleType,
    state,
    profile: PlotModeDataProfile,
) -> None:
    tabular_regions = server_module._tabular_regions_for_profile(profile)
    if tabular_regions:
        for index, region in enumerate(tabular_regions[:4]):
            if not region.columns or not region.preview_rows:
                continue
            caption = region.summary
            if index == 0 and profile.integrity_notes:
                caption += " Integrity notes: " + " ".join(profile.integrity_notes[:2])
            server_module._append_plot_mode_table_preview(
                state,
                source_label=region.source_label,
                caption=caption,
                columns=region.columns,
                rows=region.preview_rows,
            )
        return
    if not profile.columns or not profile.preview_rows:
        return
    caption = profile.summary
    if profile.integrity_notes:
        caption += " Integrity notes: " + " ".join(profile.integrity_notes[:2])
    server_module._append_plot_mode_table_preview(
        state,
        source_label=profile.source_label,
        caption=caption,
        columns=profile.columns,
        rows=profile.preview_rows,
    )


def _profile_supports_preview_confirmation(
    server_module: ModuleType,
    profile: PlotModeDataProfile,
) -> bool:
    if profile.source_kind == "file":
        return False

    tabular_regions = server_module._tabular_regions_for_profile(profile)
    if tabular_regions:
        return any(region.columns or region.preview_rows for region in tabular_regions)

    return bool(profile.columns or profile.preview_rows)


def _queue_data_preview_confirmation(
    server_module: ModuleType,
    state,
    profile: PlotModeDataProfile,
) -> None:
    question_set = PlotModeQuestionSet(
        purpose="confirm_data_preview",
        title="Data confirmation",
        source_ids=[profile.id],
    )
    options = [
        PlotModeQuestionOption(
            id="use_preview",
            label="Use this preview",
            description="Continue with this inferred source.",
        )
    ]
    if (
        state.tabular_selector is not None
        and profile.source_file_id == state.tabular_selector.file_id
    ):
        options.append(
            PlotModeQuestionOption(
                id="adjust_selection",
                label="Adjust selection",
                description="Reopen the sheet grid and revise the marked regions.",
            )
        )
    elif len(state.data_profiles) > 1:
        options.append(
            PlotModeQuestionOption(
                id="choose_other_source",
                label="Choose another source",
                description="Go back to the available source previews.",
            )
        )

    if len(server_module._tabular_regions_for_profile(profile)) > 1:
        prompt = f"I sampled `{profile.source_label}` from multiple spreadsheet regions. Does this combined source look right for plotting?"
    else:
        prompt = f"I sampled `{profile.source_label}`. Does this preview look like the source you want to plot?"
    question_set.questions = [
        PlotModeQuestionItem(
            title="Confirm preview",
            prompt=prompt,
            options=options,
            allow_custom_answer=True,
        )
    ]
    server_module._append_plot_mode_question_set(
        state,
        question_set=question_set,
        lead_content=prompt,
    )


def _append_profile_integrity_activity(
    server_module: ModuleType,
    state,
    profile: PlotModeDataProfile,
) -> None:
    if not profile.integrity_notes:
        return
    server_module._append_plot_mode_activity(
        state,
        title="Integrity check",
        items=[
            *profile.integrity_notes,
            "Source files stay immutable; conservative fixes happen only inside the generated script.",
        ],
    )


def _present_profile_for_confirmation(
    server_module: ModuleType,
    state,
    profile: PlotModeDataProfile,
) -> None:
    if not server_module._profile_supports_preview_confirmation(profile):
        state.pending_question_set = None
        state.selected_data_profile_id = profile.id
        server_module._set_active_resolved_source_for_profile(state, profile)
        state.phase = PlotModePhase.awaiting_prompt
        server_module._append_plot_mode_message(
            state,
            role="assistant",
            content=(
                f"I registered `{profile.source_label}`, but this file type does not support preview. "
                "I will use its path directly while planning the plot."
            ),
        )
        return

    server_module._append_profile_preview_card(state, profile)
    server_module._append_profile_integrity_activity(state, profile)
    server_module._queue_data_preview_confirmation(state, profile)


def _present_tabular_range_proposal(
    server_module: ModuleType,
    state,
    profile: PlotModeDataProfile,
    *,
    rationale: str,
) -> None:
    server_module._append_profile_preview_card(state, profile)
    server_module._append_profile_integrity_activity(state, profile)
    server_module._queue_tabular_range_confirmation(
        state,
        profile,
        rationale=rationale,
    )


def _queue_tabular_range_confirmation(
    server_module: ModuleType,
    state,
    profile: PlotModeDataProfile,
    *,
    rationale: str,
) -> None:
    tabular_regions = server_module._tabular_regions_for_profile(profile)
    region_labels = [
        server_module._format_sheet_region_label(
            region.sheet_name,
            server_module._bounds_from_sheet_bounds(region.bounds)
            if region.bounds is not None
            else None,
        )
        for region in tabular_regions
    ]
    question_set = PlotModeQuestionSet(
        purpose="confirm_tabular_range",
        title="Confirm inferred regions",
        source_ids=[profile.id],
    )
    if len(region_labels) > 1:
        prompt = "I think the relevant table regions are " + ", ".join(
            f"`{label}`" for label in region_labels
        )
        prompt += "."
    else:
        bounds_label = region_labels[0] if region_labels else profile.source_label
        prompt = f"I think the relevant table range is `{bounds_label}`."
    if rationale.strip():
        prompt = f"{prompt} {rationale.strip()}"
    prompt += " Use this proposal, mark new regions, or type a note to refine it."
    question_set.questions = [
        PlotModeQuestionItem(
            title="Confirm inferred regions",
            prompt=prompt,
            options=[
                PlotModeQuestionOption(
                    id="use_proposed_range",
                    label="Use proposed regions",
                    description="Continue with these inferred spreadsheet regions.",
                    recommended=True,
                ),
                PlotModeQuestionOption(
                    id="adjust_selection",
                    label="Mark new regions",
                    description="Reopen the sheet grid and revise the marked regions.",
                ),
            ],
            allow_custom_answer=True,
        )
    ]
    server_module._append_plot_mode_question_set(
        state,
        question_set=question_set,
        lead_content=prompt,
    )


async def _apply_tabular_range_proposal(
    server_module: ModuleType,
    state,
    selector,
    *,
    selected_regions,
    instruction,
    activity_title,
) -> None:
    normalized_regions = server_module._dedupe_selection_regions(selected_regions)
    proposal = await server_module._propose_grouped_profile_from_selector_regions(
        state=state,
        selector=selector,
        selected_regions=normalized_regions,
        instruction=instruction,
    )
    profile = proposal.profile
    selector.selected_sheet_id = (
        normalized_regions[-1].sheet_id if normalized_regions else None
    )
    selector.selected_regions = normalized_regions
    selector.inferred_profile_id = profile.id
    selector.requires_user_hint = False

    state.pending_question_set = None
    state.selected_data_profile_id = None
    state.data_profiles = [
        existing
        for existing in state.data_profiles
        if existing.source_file_id != profile.source_file_id
    ]
    state.data_profiles.append(profile)
    state.phase = PlotModePhase.awaiting_data_choice

    tabular_regions = server_module._tabular_regions_for_profile(profile)
    region_labels = [
        server_module._format_sheet_region_label(
            region.sheet_name,
            server_module._bounds_from_sheet_bounds(region.bounds)
            if region.bounds is not None
            else None,
        )
        for region in tabular_regions
    ]
    if len(region_labels) > 1:
        activity_items = [
            "Proposed grouped datasource from: " + ", ".join(region_labels) + ".",
        ]
    else:
        proposal_label = region_labels[0] if region_labels else profile.source_label
        activity_items = [f"Proposed {proposal_label} from your selected hint."]
    if instruction and instruction.strip():
        activity_items.append(f"Used note: {instruction.strip()}")
    if proposal.rationale.strip():
        activity_items.append(proposal.rationale.strip())
    server_module._append_plot_mode_activity(
        state,
        title=activity_title,
        items=activity_items,
    )
    server_module._present_tabular_range_proposal(
        state,
        profile,
        rationale=proposal.rationale,
    )


def _populate_plot_mode_data_messages(server_module: ModuleType, state) -> None:
    profiles, activity_items, selector = server_module._profile_selected_data_files(
        state.files
    )
    state.messages = []
    state.input_bundle = server_module._build_plot_mode_input_bundle(state.files)
    state.data_profiles = profiles
    (
        state.resolved_sources,
        state.active_resolved_source_ids,
    ) = server_module._build_plot_mode_resolved_sources(state.files, profiles, selector)
    state.selected_data_profile_id = None
    state.tabular_selector = selector
    state.pending_question_set = None
    state.latest_user_goal = ""
    state.latest_plan_summary = ""
    state.latest_plan_outline = []
    state.latest_plan_plot_type = ""
    state.latest_plan_actions = []
    server_module._reset_plot_mode_draft(state)

    if activity_items:
        server_module._append_plot_mode_activity(
            state,
            title="Data inspection",
            items=activity_items,
        )

    if selector is not None and selector.requires_user_hint:
        state.phase = PlotModePhase.awaiting_data_choice
        server_module._append_plot_mode_message(
            state,
            role="assistant",
            content=selector.status_text,
        )
        return

    if not profiles:
        if state.resolved_sources:
            state.phase = PlotModePhase.awaiting_data_choice
            for source in state.resolved_sources:
                server_module._append_plot_mode_activity(
                    state,
                    title="Source bundle ready",
                    items=[source.summary],
                )
            server_module._queue_plot_mode_bundle_kickoff_question(state)
            return
        state.phase = PlotModePhase.awaiting_prompt
        return

    if len(state.files) > 1 and state.active_resolved_source_ids:
        for profile in profiles:
            server_module._append_profile_preview_card(state, profile)
        for source in server_module._active_resolved_sources(state):
            bundle_activity_items = [source.summary]
            if source.columns:
                bundle_activity_items.append(
                    "Shared columns: " + ", ".join(source.columns[:8])
                )
            server_module._append_plot_mode_activity(
                state,
                title="Source bundle ready",
                items=bundle_activity_items,
            )
        state.phase = PlotModePhase.awaiting_data_choice
        server_module._queue_plot_mode_bundle_kickoff_question(state)
        return

    if len(profiles) == 1:
        state.phase = PlotModePhase.awaiting_data_choice
        server_module._present_profile_for_confirmation(state, profiles[0])
        return

    for profile in profiles[: min(2, len(profiles))]:
        server_module._append_profile_preview_card(state, profile)

    state.selected_data_profile_id = None
    state.phase = PlotModePhase.awaiting_data_choice
    question_set = PlotModeQuestionSet(
        purpose="select_data_source",
        title="Choose a source",
        source_ids=[profile.id for profile in profiles],
    )
    options = [
        PlotModeQuestionOption(
            id=profile.id,
            label=profile.source_label,
            description=(
                ", ".join(profile.columns[:4]) if profile.columns else profile.summary
            ),
        )
        for profile in profiles[:8]
    ]
    question_set.questions = [
        PlotModeQuestionItem(
            title="Available sources",
            prompt="I found several plausible source tables. Which one should I preview?",
            options=options,
            allow_custom_answer=True,
        )
    ]
    server_module._append_plot_mode_question_set(
        state,
        question_set=question_set,
        lead_content="I found several plausible source tables. Which one should I preview?",
    )


def _queue_plot_mode_plan_approval_question(server_module: ModuleType, state) -> None:
    question_set = PlotModeQuestionSet(
        purpose="approve_plot_plan",
        title="Ready to draft",
        questions=[
            PlotModeQuestionItem(
                title="Next step",
                prompt="Plan is ready. Should I start drafting the plot now?",
                options=[
                    PlotModeQuestionOption(
                        id="start_draft",
                        label="Start drafting",
                        description="Generate and execute the first approved plot draft.",
                        recommended=True,
                    ),
                    PlotModeQuestionOption(
                        id="revise_plan",
                        label="Revise the plan",
                        description="Adjust chart type, scope, style, or layout before drafting.",
                    ),
                ],
                allow_custom_answer=True,
            )
        ],
    )
    server_module._append_plot_mode_question_set(
        state,
        question_set=question_set,
        lead_content="Plan is ready. Should I start drafting the plot now?",
    )


def _queue_plot_mode_continue_planning_question(
    server_module: ModuleType,
    state,
    prompt: str,
) -> None:
    question_set = PlotModeQuestionSet(
        purpose="continue_plot_planning",
        title="More input needed",
        questions=[
            PlotModeQuestionItem(
                title="Continue planning",
                prompt=prompt,
                options=[
                    PlotModeQuestionOption(
                        id="continue_planning",
                        label="Continue",
                        description="Inspect the source more closely and refine the plan.",
                        recommended=True,
                    ),
                    PlotModeQuestionOption(
                        id="revise_goal",
                        label="Revise the plan",
                        description="Adjust the goal or constraints before continuing.",
                    ),
                ],
                allow_custom_answer=True,
            )
        ],
    )
    server_module._append_plot_mode_question_set(
        state,
        question_set=question_set,
        lead_content=prompt,
    )


def _queue_plot_mode_bundle_kickoff_question(server_module: ModuleType, state) -> None:
    prompt = (
        "Your source bundle is ready. Proceed to plot planning, "
        "or tell me anything else to consider first."
    )
    question_set = PlotModeQuestionSet(
        purpose="kickoff_plot_planning",
        title="Ready to plan",
        questions=[
            PlotModeQuestionItem(
                title="Next step",
                prompt=prompt,
                options=[
                    PlotModeQuestionOption(
                        id="proceed_to_planning",
                        label="Proceed",
                        description="Start planning the plot from this source bundle now.",
                        recommended=True,
                    )
                ],
                allow_custom_answer=True,
            )
        ],
    )
    server_module._append_plot_mode_question_set(
        state,
        question_set=question_set,
        lead_content=prompt,
    )


def _present_plot_mode_plan_result(server_module: ModuleType, state, result) -> None:
    server_module._store_plot_mode_plan(state, result)

    if result.summary.strip():
        server_module._append_plot_mode_message(
            state,
            role="assistant",
            content=server_module._truncate_output(result.summary.strip()),
        )

    if state.latest_plan_plot_type:
        server_module._append_plot_mode_activity(
            state,
            title="Recommended chart",
            items=[state.latest_plan_plot_type],
        )
    if state.latest_plan_actions:
        server_module._append_plot_mode_activity(
            state,
            title="What I'll check in the data",
            items=state.latest_plan_actions[:8],
        )
    if state.latest_plan_outline:
        server_module._append_plot_mode_activity(
            state,
            title="Proposed plot plan",
            items=state.latest_plan_outline[:8],
        )

    if result.questions:
        question_set = PlotModeQuestionSet(
            purpose=(
                cast(
                    Literal[
                        "select_data_source",
                        "confirm_tabular_range",
                        "confirm_data_preview",
                        "continue_plot_planning",
                        "approve_plot_plan",
                    ],
                    result.question_purpose,
                )
                if result.question_purpose
                in {
                    "select_data_source",
                    "confirm_tabular_range",
                    "confirm_data_preview",
                    "continue_plot_planning",
                    "approve_plot_plan",
                }
                else (
                    "approve_plot_plan"
                    if result.ready_to_plot
                    else "continue_plot_planning"
                )
            ),
            title="Questions",
            questions=result.questions,
        )
        state.phase = PlotModePhase.awaiting_data_choice
        server_module._append_plot_mode_question_set(
            state,
            question_set=question_set,
            lead_content=result.clarification_question
            or "I have a few questions before moving on.",
        )
        return

    if result.ready_to_plot:
        state.phase = PlotModePhase.awaiting_plan_approval
        server_module._queue_plot_mode_plan_approval_question(state)
        return

    state.phase = PlotModePhase.awaiting_prompt
    if result.clarification_question:
        state.phase = PlotModePhase.awaiting_data_choice
        server_module._queue_plot_mode_continue_planning_question(
            state,
            prompt=result.clarification_question,
        )
