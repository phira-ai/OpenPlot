"""Plot-mode planning and draft helpers extracted from openplot.server."""

from __future__ import annotations

import ast
import asyncio
import json
import re
from contextlib import suppress
from pathlib import Path
from types import ModuleType
from typing import cast


def _build_plot_mode_prompt(server_module: ModuleType, state, user_message: str) -> str:
    python_state = server_module._resolve_python_interpreter_state(None)
    resolved_path = str(python_state.get("resolved_path") or "").strip()
    resolved_version = str(python_state.get("resolved_version") or "").strip()
    available_packages_raw = python_state.get("available_packages")
    available_packages = (
        [str(item) for item in available_packages_raw]
        if isinstance(available_packages_raw, list)
        else []
    )

    lines: list[str] = [
        "You are helping OpenPlot generate a complete Python plotting script for publication-quality figures.",
        "",
        "Preferred return format:",
        "- Prefer one JSON object between OPENPLOT_RESULT_BEGIN and OPENPLOT_RESULT_END.",
        '- Preferred keys: {"summary": string, "script": string, "done": boolean}.',
        "- If JSON formatting fails, return exactly one fenced Python block containing the full script.",
        "- The summary should be a short user-facing explanation of what you drafted or improved.",
        "- Write in plain language and avoid implementation jargon.",
        "- If you describe actions or changes, use bullet points or numbered items.",
        "",
        "Script rules:",
        "- Use only local files listed below (absolute paths).",
        "- Do not invent file paths that are not listed.",
        "- Treat the listed source data files as immutable. Never modify them.",
        "- Any data cleaning must happen in-memory inside the generated script.",
        "- Use conservative data-integrity fixes only: drop fully empty rows/columns, normalize headers, parse dates safely, and coerce obvious numeric/date types.",
        "- Do not impute, interpolate, aggregate, or deduplicate unless the user explicitly requested it.",
        "- Produce one figure and save it to 'plot.png'.",
        "- Include imports and executable top-level code.",
        "- Do not request interactive input.",
        "- Never use built-in question tools such as AskUserQuestion or question.",
        "- If user input is absolutely required, return it only in the structured OpenPlot response format requested above so OpenPlot can render a question card.",
        "- Aim for a polished grant-application / top-conference-paper visual standard.",
        "",
        "Python runtime constraints (strict, must follow):",
        f"- Runtime path: {resolved_path or '<unknown>'}",
        f"- Python version: {resolved_version or '<unknown>'}",
        "- Use Python standard library plus third-party packages listed below.",
        "- Treat this list as a strict allowlist for third-party imports.",
        "- Any non-stdlib import not listed is forbidden.",
        "- If a package is unavailable, rewrite using stdlib or listed packages only.",
        "- Do not ask to install packages or change environments.",
        (
            "- Available third-party packages: "
            + (", ".join(available_packages) if available_packages else "<none>")
        ),
    ]

    if state.files:
        lines.append("")
        lines.append("Available data files:")
        for entry in state.files[: server_module._plot_mode_prompt_files_limit]:
            lines.append(f"- {Path(entry.stored_path).resolve()}")
        if len(state.files) > server_module._plot_mode_prompt_files_limit:
            remaining = len(state.files) - server_module._plot_mode_prompt_files_limit
            lines.append(f"- ... and {remaining} more files")

    selected_profile = next(
        (
            profile
            for profile in state.data_profiles
            if profile.id == state.selected_data_profile_id
        ),
        None,
    )
    if selected_profile is not None:
        lines.extend(
            [
                "",
                "Confirmed data source:",
                f"- Label: {selected_profile.source_label}",
                f"- Path: {selected_profile.file_path}",
                f"- Kind: {selected_profile.source_kind}",
            ]
        )
        if selected_profile.table_name:
            lines.append(f"- Table/sheet: {selected_profile.table_name}")
        if selected_profile.columns:
            lines.append(
                "- Sampled columns: " + ", ".join(selected_profile.columns[:16])
            )
        server_module._append_profile_region_details(lines, selected_profile)
        if len(server_module._tabular_regions_for_profile(selected_profile)) > 1:
            lines.append(
                "- Treat the listed regions as one logical datasource assembled from multiple sheet/range fragments."
            )
        if selected_profile.integrity_notes:
            lines.append("- Integrity notes:")
            for note in selected_profile.integrity_notes[:8]:
                lines.append(f"  - {note}")
    else:
        server_module._append_active_resolved_source_context(
            lines,
            state,
            heading="Confirmed datasource(s):",
        )

    if state.current_script:
        lines.extend(
            [
                "",
                "Current script to refine:",
                state.current_script.rstrip(),
            ]
        )

    lines.extend(
        [
            "",
            f"Execution mode: {state.execution_mode.value}",
            f"Latest approved plotting goal: {state.latest_user_goal or user_message.strip()}",
        ]
    )
    lines.extend(["", "User request:", user_message.strip()])
    return "\n".join(lines).strip()


def _build_plot_mode_planning_prompt(
    server_module: ModuleType, state, user_message: str
) -> str:
    profile = server_module._selected_data_profile(state)
    lines: list[str] = [
        "You are planning a publication-quality OpenPlot figure before script generation.",
        "",
        "Planning workflow requirements:",
        "- Inspect selected local data files directly before proposing a plot plan.",
        "- For Excel and complex structures, reason about candidate sheets/tables/ranges.",
        "- Infer the most suitable chart type(s), layout, style direction, and color strategy.",
        "- Include conservative in-script data integrity handling plans when needed.",
        "- Do not generate or return Python code in this phase.",
        "",
        "Preferred response format:",
        "- Return one JSON object between OPENPLOT_PLAN_BEGIN and OPENPLOT_PLAN_END.",
        "- Suggested keys: summary, plot_type, data_actions, plan_outline, questions, question_purpose, clarification_question, ready_to_plot.",
        "- If formatting fails, return plain text; OpenPlot will attempt recovery.",
        "- Use plain language for the summary and questions; avoid implementation jargon.",
        "- Write any action list as bullet points or numbered items.",
        "- If you need user input or approval, return one or more questions. Each question should have prompt, options, allow_custom_answer, and multiple.",
        "- Keep the JSON keys literal: use prompt and options, not question or choices.",
        "- Each options entry should be either a string label or an object with label plus optional id, description, and recommended.",
        "- Never use built-in question tools such as AskUserQuestion or question.",
        "- Do not ask the user for missing inputs in free-form prose alone. Put every user-facing choice into the questions array so OpenPlot can render an interactive question card.",
        "- When asking a question, propose 2-5 discrete options first whenever possible, then allow a custom answer only as a fallback.",
        "- Use question_purpose='continue_plot_planning' when you need more user input before drafting.",
        "- Use question_purpose='approve_plot_plan' when the plan is ready and you want permission to start drafting.",
    ]

    if state.files:
        lines.append("")
        lines.append("Available data files:")
        for entry in state.files[: server_module._plot_mode_prompt_files_limit]:
            lines.append(f"- {Path(entry.stored_path).resolve()}")
        if len(state.files) > server_module._plot_mode_prompt_files_limit:
            remaining = len(state.files) - server_module._plot_mode_prompt_files_limit
            lines.append(f"- ... and {remaining} more files")

    if profile is not None:
        lines.extend(
            [
                "",
                "Current selected source:",
                f"- {profile.source_label}",
                f"- Path: {profile.file_path}",
            ]
        )
        if profile.table_name:
            lines.append(f"- Sheet/table hint: {profile.table_name}")
        if profile.columns:
            lines.append("- Previewed columns: " + ", ".join(profile.columns[:16]))
        server_module._append_profile_region_details(lines, profile)
        if len(server_module._tabular_regions_for_profile(profile)) > 1:
            lines.append(
                "- Treat the listed regions as one logical datasource assembled from multiple sheet/range fragments."
            )
        if profile.integrity_notes:
            lines.append("- Preview integrity notes:")
            for note in profile.integrity_notes[:8]:
                lines.append(f"  - {note}")
    else:
        server_module._append_active_resolved_source_context(
            lines,
            state,
            heading="Confirmed datasource(s):",
        )

    if state.latest_plan_summary:
        lines.extend(
            [
                "",
                "Latest plan summary:",
                state.latest_plan_summary,
            ]
        )
        if state.latest_plan_outline:
            lines.append("Latest plan outline:")
            for item in state.latest_plan_outline[:8]:
                lines.append(f"- {item}")

    lines.extend(["", "User message:", user_message.strip()])
    return "\n".join(lines).strip()


def _extract_plot_mode_plan_result(server_module: ModuleType, text: str):
    def _first_non_empty_string(*values: object) -> str | None:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _strip_option_marker(value: str) -> str:
        return re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+|[A-Za-z][.)]\s+)", "", value).strip()

    def _build_question_option(
        label: str,
        *,
        option_id: object = None,
        description: object = None,
        recommended: object = None,
    ):
        normalized_label = _strip_option_marker(label).rstrip(":").strip()
        normalized_id = (
            option_id.strip()
            if isinstance(option_id, str) and option_id.strip()
            else re.sub(r"[^a-z0-9]+", "_", normalized_label.lower()).strip("_")
            or server_module._new_id()
        )
        return server_module.PlotModeQuestionOption(
            id=normalized_id,
            label=normalized_label,
            description=description.strip() if isinstance(description, str) else "",
            recommended=bool(recommended is True),
        )

    def _parse_question_options(value: object):
        if isinstance(value, str):
            parts: list[str] = []
            if "\n" in value:
                parts = [line.strip() for line in value.splitlines() if line.strip()]
            elif "|" in value:
                parts = [part.strip() for part in value.split("|") if part.strip()]
            elif ";" in value:
                parts = [part.strip() for part in value.split(";") if part.strip()]
            else:
                comma_parts = [
                    part.strip() for part in value.split(",") if part.strip()
                ]
                if len(comma_parts) >= 2:
                    parts = comma_parts
            normalized_parts = [
                _strip_option_marker(part).rstrip(":").strip()
                for part in parts
                if _strip_option_marker(part).rstrip(":").strip()
            ]
            if len(normalized_parts) >= 2:
                return [_build_question_option(part) for part in normalized_parts]
            return []

        if not isinstance(value, list):
            return []

        options = []
        for option_entry in value:
            if isinstance(option_entry, str) and option_entry.strip():
                options.append(_build_question_option(option_entry))
                continue
            if not isinstance(option_entry, dict):
                continue
            label_value = _first_non_empty_string(
                option_entry.get("label"),
                option_entry.get("text"),
                option_entry.get("title"),
                option_entry.get("name"),
                option_entry.get("option"),
                option_entry.get("value"),
            )
            if label_value is None:
                continue
            options.append(
                _build_question_option(
                    label_value,
                    option_id=(
                        option_entry.get("id")
                        if option_entry.get("id") is not None
                        else option_entry.get("value")
                    ),
                    description=_first_non_empty_string(
                        option_entry.get("description"),
                        option_entry.get("details"),
                        option_entry.get("reason"),
                        option_entry.get("summary"),
                    ),
                    recommended=(
                        option_entry.get("recommended")
                        if option_entry.get("recommended") is not None
                        else option_entry.get("default")
                    ),
                )
            )
        return options

    def _extract_inline_question_options(prompt: str):
        match = re.match(
            r"^(.*?)(?:\s+|\s*[-:]\s*)(?:options?|choices?|answers?)\s*:\s*(.+)$",
            prompt.strip(),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return prompt.strip(), []

        prompt_text = match.group(1).strip().rstrip(":")
        option_text = match.group(2).strip()
        if "?" not in prompt_text and not re.search(
            r"\b(which|what|would you like|should i|do you want|choose|select|pick|confirm)\b",
            prompt_text,
            flags=re.IGNORECASE,
        ):
            return prompt.strip(), []
        return prompt_text or prompt.strip(), _parse_question_options(option_text)

    candidate_dicts: list[dict[str, object]] = []
    strict_match = re.search(
        r"OPENPLOT_PLAN_BEGIN\s*(\{.*?\})\s*OPENPLOT_PLAN_END",
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
        summary_value = payload.get("summary")
        if not isinstance(summary_value, str) or not summary_value.strip():
            continue
        plot_type_value = payload.get("plot_type")
        plot_type = ""
        if isinstance(plot_type_value, str) and plot_type_value.strip():
            plot_type = plot_type_value.strip()
        elif isinstance(plot_type_value, dict):
            primary = plot_type_value.get("primary")
            if isinstance(primary, str) and primary.strip():
                plot_type = primary.strip()

        def _string_list(value: object) -> list[str]:
            if not isinstance(value, list):
                return []
            return [
                str(item).strip()
                for item in value
                if isinstance(item, str) and str(item).strip()
            ]

        plan_outline = _string_list(payload.get("plan_outline"))
        if not plan_outline:
            plan_outline = _string_list(payload.get("plan_steps"))

        data_actions = _string_list(payload.get("data_actions"))
        if not data_actions:
            data_actions = _string_list(payload.get("inspected_sources"))

        questions_raw = payload.get("questions")
        parsed_questions = []
        if isinstance(questions_raw, list):
            for entry in questions_raw:
                if not isinstance(entry, dict):
                    continue
                prompt_value = _first_non_empty_string(
                    entry.get("prompt"),
                    entry.get("question"),
                    entry.get("clarification_question"),
                    entry.get("text"),
                )
                if prompt_value is None:
                    continue
                options_raw = next(
                    (
                        entry.get(key)
                        for key in (
                            "options",
                            "choices",
                            "answers",
                            "suggested_answers",
                            "suggested_options",
                            "selections",
                        )
                        if entry.get(key) is not None
                    ),
                    None,
                )
                options = _parse_question_options(options_raw)
                prompt_text = prompt_value.strip()
                if not options:
                    prompt_text, options = _extract_inline_question_options(prompt_text)
                if not options:
                    options = server_module._suggest_plot_mode_question_options(
                        prompt_text
                    )
                parsed_questions.append(
                    server_module.PlotModeQuestionItem(
                        title=(
                            _first_non_empty_string(
                                entry.get("title"), entry.get("label")
                            )
                        ),
                        prompt=prompt_text,
                        options=options,
                        allow_custom_answer=bool(
                            entry.get(
                                "allow_custom_answer",
                                entry.get("allow_custom", entry.get("freeform", True)),
                            )
                        ),
                        multiple=bool(
                            entry.get("multiple", entry.get("multi_select", False))
                        ),
                    )
                )

        question_purpose_value = payload.get("question_purpose")
        question_purpose = (
            question_purpose_value.strip()
            if isinstance(question_purpose_value, str)
            and question_purpose_value.strip()
            else None
        )

        clarification_question_value = payload.get("clarification_question")
        clarification_question = (
            clarification_question_value.strip()
            if isinstance(clarification_question_value, str)
            and clarification_question_value.strip()
            else None
        )

        ready_to_plot = server_module._coerce_bool(payload.get("ready_to_plot"))
        if ready_to_plot is None:
            ready_to_plot = server_module._coerce_bool(payload.get("approved_to_draft"))
        if ready_to_plot is None:
            ready_to_plot = clarification_question is None

        return server_module.PlotModePlanResult(
            assistant_text=text,
            summary=summary_value.strip(),
            plot_type=plot_type,
            plan_outline=plan_outline,
            data_actions=data_actions,
            questions=parsed_questions or None,
            question_purpose=question_purpose,
            clarification_question=clarification_question,
            ready_to_plot=bool(ready_to_plot),
        )

    stripped = text.strip()
    if not stripped:
        return None
    lines = [
        line.strip()
        for line in stripped.splitlines()
        if line.strip()
        and line.strip() not in {"OPENPLOT_PLAN_BEGIN", "OPENPLOT_PLAN_END"}
    ]
    if not lines:
        return None

    def _extract_inline_numbered_items(value: str):
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized:
            return None, []

        matches = list(
            re.finditer(
                r"(?:(?<=^)|(?<=\s))(\d+[.)])\s+(.+?)(?=(?:\s+\d+[.)]\s+)|$)",
                normalized,
            )
        )
        if len(matches) < 2:
            return None, []

        summary = normalized[: matches[0].start()].strip()
        items = [match.group(2).strip().rstrip(":") for match in matches]
        return summary or None, [item for item in items if item]

    def _extract_option_label(line: str) -> str | None:
        match = re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$", line)
        if not match:
            return None
        label = match.group(1).strip().rstrip(":")
        return label or None

    def _looks_like_prompt(line: str) -> bool:
        normalized = line.strip().lower()
        if not normalized:
            return False
        if "?" in normalized:
            return True
        prompt_markers = (
            "please provide",
            "which ",
            "what ",
            "would you like",
            "should i",
            "do you want",
            "choose ",
            "select ",
            "pick ",
            "let me know",
            "confirm ",
        )
        return any(marker in normalized for marker in prompt_markers)

    inline_summary, inline_numbered_items = _extract_inline_numbered_items(stripped)
    if len(inline_numbered_items) >= 2:
        question_like_items = sum(
            1
            for item in inline_numbered_items
            if "?" in item or ":" in item or _looks_like_prompt(item)
        )
        intro_text = (inline_summary or "").lower()
        intro_requests_answers = any(
            marker in intro_text
            for marker in (
                "please answer",
                "answer these",
                "i need",
                "more input",
                "questions",
                "before script generation",
                "before drafting",
            )
        )
        if intro_requests_answers or question_like_items >= max(
            2, len(inline_numbered_items) - 1
        ):
            return server_module.PlotModePlanResult(
                assistant_text=stripped,
                summary=inline_summary or "I need a few details before drafting.",
                plan_outline=[],
                data_actions=[],
                questions=[
                    server_module.PlotModeQuestionItem(
                        prompt=item,
                        options=server_module._suggest_plot_mode_question_options(item),
                        allow_custom_answer=True,
                    )
                    for item in inline_numbered_items
                ],
                question_purpose="continue_plot_planning",
                clarification_question=inline_summary,
                ready_to_plot=False,
            )

    option_start_index: int | None = None
    option_labels: list[str] = []
    for index, line in enumerate(lines):
        option_label = _extract_option_label(line)
        if option_label is None:
            if option_start_index is not None:
                break
            continue
        if option_start_index is None:
            option_start_index = index
        option_labels.append(option_label)

    if option_start_index is not None and len(option_labels) >= 2:
        if all(_looks_like_prompt(label) for label in option_labels):
            summary = (
                " ".join(lines[:option_start_index]).strip()
                or "I need a few details before drafting."
            )
            return server_module.PlotModePlanResult(
                assistant_text=stripped,
                summary=summary,
                plan_outline=[],
                data_actions=[],
                questions=[
                    server_module.PlotModeQuestionItem(
                        prompt=label,
                        options=server_module._suggest_plot_mode_question_options(
                            label
                        ),
                        allow_custom_answer=True,
                    )
                    for label in option_labels
                ],
                question_purpose="continue_plot_planning",
                clarification_question=(
                    summary
                    if summary != "I need a few details before drafting."
                    else None
                ),
                ready_to_plot=False,
            )

        prompt_index: int | None = None
        for index in range(option_start_index - 1, -1, -1):
            if _looks_like_prompt(lines[index]):
                prompt_index = index
                break

        if prompt_index is not None:
            prompt = lines[prompt_index].rstrip(" :")
            summary = " ".join(lines[:prompt_index]).strip() or prompt
            return server_module.PlotModePlanResult(
                assistant_text=stripped,
                summary=summary,
                plan_outline=[],
                data_actions=[],
                questions=[
                    server_module.PlotModeQuestionItem(
                        prompt=prompt,
                        options=[
                            server_module.PlotModeQuestionOption(
                                id=(
                                    re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
                                    or server_module._new_id()
                                ),
                                label=label,
                            )
                            for label in option_labels
                        ],
                        allow_custom_answer=True,
                    )
                ],
                question_purpose="continue_plot_planning",
                clarification_question=prompt,
                ready_to_plot=False,
            )

    for index in range(len(lines) - 1, -1, -1):
        if not _looks_like_prompt(lines[index]):
            continue
        prompt = lines[index].rstrip(" :")
        summary = " ".join(lines[:index]).strip() or prompt
        return server_module.PlotModePlanResult(
            assistant_text=stripped,
            summary=summary,
            plan_outline=[],
            data_actions=[],
            question_purpose="continue_plot_planning",
            clarification_question=prompt,
            ready_to_plot=False,
        )

    summary = lines[0]
    plan_outline = [
        line.lstrip("- ").strip() for line in lines[1:] if line.startswith("-")
    ]
    return server_module.PlotModePlanResult(
        assistant_text=stripped,
        summary=summary,
        plan_outline=plan_outline,
        data_actions=[],
        clarification_question=None,
        ready_to_plot=False,
    )


async def _run_plot_mode_generation(
    server_module: ModuleType,
    *,
    state,
    runner,
    message: str,
    model: str,
    variant: str | None,
    assistant_message,
):
    _ = assistant_message
    prompt = server_module._build_plot_mode_prompt(state, message)

    for attempt_index in range(1, server_module._plot_mode_execution_retry_limit + 1):
        del attempt_index
        assistant_text, runner_error = await server_module._run_plot_mode_runner_prompt(
            state=state,
            runner=runner,
            prompt=prompt,
            model=model,
            variant=variant,
        )
        if runner_error is not None:
            return server_module.PlotModeGenerationResult(
                assistant_text=assistant_text,
                error_message=runner_error,
            )

        script_result = server_module._extract_plot_mode_script_result(assistant_text)
        if script_result is None:
            prompt = (
                f"{prompt}\n\n"
                "Your previous reply was not usable. Resend either OPENPLOT_RESULT JSON with "
                "summary and script, or one complete fenced python block containing the full script."
            )
            continue

        summary_text, script, done_hint = script_result

        try:
            ast.parse(script)
        except SyntaxError as exc:
            prompt = (
                f"{prompt}\n\n"
                "The previous script had a Python syntax error."
                f"\nError: {exc}\n"
                "Fix the script and resend the full corrected version."
            )
            continue

        script_path = server_module._plot_mode_generated_script_path(state)
        script_path.write_text(script, encoding="utf-8")

        capture_dir = (
            server_module._plot_mode_captures_dir(state) / server_module._new_id()
        )
        capture_dir.mkdir(parents=True, exist_ok=True)
        server_module.set_workspace_dir(Path(state.workspace_dir))
        protected_paths = [
            str(Path(file.stored_path).resolve()) for file in state.files
        ]
        execution_result = await asyncio.to_thread(
            server_module.execute_script,
            script_path,
            work_dir=server_module._plot_mode_sandbox_dir(state),
            capture_dir=capture_dir,
            python_executable=server_module._resolve_python_executable(None),
            protected_paths=protected_paths,
        )

        if execution_result.success and execution_result.plot_path:
            return server_module.PlotModeGenerationResult(
                assistant_text=summary_text,
                script=script,
                execution_result=execution_result,
                done_hint=done_hint,
            )

        failure_parts = [execution_result.error or "Script execution failed"]
        if execution_result.stderr.strip():
            failure_parts.append(execution_result.stderr.strip())
        prompt = (
            f"{prompt}\n\n"
            "The previous script did not run successfully. "
            "Revise the script using this execution feedback and resend the full corrected script.\n"
            + "\n".join(failure_parts)
        )

    return server_module.PlotModeGenerationResult(
        assistant_text="",
        error_message="I couldn't produce a runnable plotting script after several tries.",
    )


async def _run_plot_mode_planning(
    server_module: ModuleType,
    *,
    state,
    runner,
    user_message: str,
    model: str,
    variant: str | None,
):
    prompt = server_module._build_plot_mode_planning_prompt(state, user_message)
    assistant_text, runner_error = await server_module._run_plot_mode_runner_prompt(
        state=state,
        runner=runner,
        prompt=prompt,
        model=model,
        variant=variant,
    )
    if runner_error is not None:
        return server_module.PlotModePlanResult(
            assistant_text=assistant_text,
            error_message=runner_error,
        )

    parsed = server_module._extract_plot_mode_plan_result(assistant_text)
    needs_option_recovery = (
        parsed is not None
        and parsed.questions is not None
        and not server_module._plot_mode_plan_result_has_selectable_options(parsed)
    )
    if parsed is None or needs_option_recovery:
        recovery_prompt = (
            f"{prompt}\n\n"
            "FORMAT RECOVERY: Resend the planning response as JSON with keys "
            "summary, plot_type, data_actions, plan_outline, questions, question_purpose, clarification_question, and ready_to_plot. "
            "If you need user input, do not ask only in prose; include the prompt and choices in questions. "
            "Every question should include 2-5 selectable options in the options array whenever a discrete choice is possible."
        )
        (
            recovered_text,
            recovery_error,
        ) = await server_module._run_plot_mode_runner_prompt(
            state=state,
            runner=runner,
            prompt=recovery_prompt,
            model=model,
            variant=variant,
        )
        if recovery_error is not None:
            return server_module.PlotModePlanResult(
                assistant_text=assistant_text,
                error_message=recovery_error,
            )
        recovered_parsed = server_module._extract_plot_mode_plan_result(recovered_text)
        if recovered_parsed is not None and (
            parsed is None
            or server_module._plot_mode_plan_result_has_selectable_options(
                recovered_parsed
            )
        ):
            parsed = recovered_parsed
            assistant_text = recovered_text

    if parsed is None:
        fallback_summary = (
            assistant_text.strip() or "I need more context before drafting."
        )
        return server_module.PlotModePlanResult(
            assistant_text=assistant_text,
            summary=fallback_summary[:480],
            plan_outline=[],
            data_actions=[],
            ready_to_plot=False,
        )

    parsed.assistant_text = assistant_text
    return parsed


def _store_plot_mode_plan(server_module: ModuleType, state, result) -> None:
    del server_module
    state.latest_plan_summary = result.summary.strip()
    state.latest_plan_plot_type = result.plot_type.strip()
    state.latest_plan_outline = [
        item for item in (result.plan_outline or []) if item.strip()
    ]
    state.latest_plan_actions = [
        item for item in (result.data_actions or []) if item.strip()
    ]


async def _execute_plot_mode_draft(
    server_module: ModuleType,
    *,
    state,
    runner,
    model: str,
    variant: str | None,
    draft_message: str,
):
    state.phase = server_module.PlotModePhase.drafting
    state.last_error = None
    await server_module._broadcast_plot_mode_state(state)

    result = await server_module._run_plot_mode_generation(
        state=state,
        runner=runner,
        message=draft_message,
        model=model,
        variant=variant,
        assistant_message=server_module.PlotModeChatMessage(
            role="assistant", content=""
        ),
    )

    ok, error_message = server_module._apply_plot_mode_result(state, result=result)
    if not ok:
        state.phase = server_module.PlotModePhase.awaiting_prompt
        details = error_message or "Plot generation failed"
        stderr_text = (
            result.execution_result.stderr.strip() if result.execution_result else ""
        )
        error_body = server_module._truncate_output(
            "\n".join(part for part in [details, stderr_text] if part)
        )
        server_module._append_plot_mode_message(state, role="error", content=error_body)
        await server_module._broadcast_plot_mode_state(state)
        return False, details

    summary_message = None
    summary_text = server_module._truncate_output(result.assistant_text.strip())
    if summary_text:
        summary_message = server_module._create_plot_mode_message(
            state,
            role="assistant",
            content=summary_text,
        )
    await server_module._broadcast_plot_mode_preview(state)

    if state.execution_mode == server_module.PlotModeExecutionMode.autonomous:
        await server_module._run_plot_mode_autonomous_reviews(
            state=state,
            runner=runner,
            model=model,
            variant=variant,
            summary_message=summary_message,
        )

    state.phase = server_module.PlotModePhase.ready
    await server_module._broadcast_plot_mode_state(state)
    return True, None


async def _continue_plot_mode_planning(
    server_module: ModuleType,
    *,
    state,
    runner,
    model: str,
    variant: str | None,
    planning_message: str,
):
    state.phase = server_module.PlotModePhase.planning
    state.last_error = None
    await server_module._broadcast_plot_mode_state(state)

    result = await server_module._run_plot_mode_planning(
        state=state,
        runner=runner,
        user_message=planning_message,
        model=model,
        variant=variant,
    )
    if result.error_message is not None:
        state.phase = server_module.PlotModePhase.awaiting_prompt
        server_module._append_plot_mode_message(
            state,
            role="error",
            content=server_module._truncate_output(result.error_message),
        )
        await server_module._broadcast_plot_mode_state(state)
        return False, result.error_message

    server_module._present_plot_mode_plan_result(state, result)
    server_module._touch_plot_mode(state)
    await server_module._broadcast_plot_mode_state(state)
    return True, None


def _default_plot_mode_planning_message(
    server_module: ModuleType, *, bundle: bool
) -> str:
    del server_module
    if bundle:
        return (
            "Inspect the confirmed source bundle, suggest the strongest figure, "
            "and ask before drafting."
        )
    return "Inspect the confirmed source, suggest the strongest figure, and ask before drafting."


async def _continue_plot_mode_planning_with_selected_runner(
    server_module: ModuleType,
    *,
    state,
    planning_message: str,
):
    runner = server_module._resolve_available_runner(
        server_module._normalize_fix_runner(
            state.selected_runner, default=server_module._default_fix_runner
        )
    )
    state.selected_runner = runner
    server_module._ensure_runner_is_available(runner)
    model = str(
        state.selected_model or ""
    ).strip() or server_module._runner_default_model_id(runner)
    normalized_variant = (
        str(state.selected_variant).strip() if state.selected_variant else ""
    )
    return await server_module._continue_plot_mode_planning(
        state=state,
        runner=runner,
        model=model,
        variant=normalized_variant or None,
        planning_message=planning_message,
    )


async def _start_plot_mode_planning_for_profile(
    server_module: ModuleType, state, profile
):
    state.selected_data_profile_id = profile.id
    server_module._set_active_resolved_source_for_profile(state, profile)
    planning_message = (
        state.latest_user_goal.strip()
        or server_module._default_plot_mode_planning_message(bundle=False)
    )
    return await server_module._continue_plot_mode_planning_with_selected_runner(
        state=state,
        planning_message=planning_message,
    )


def _apply_plot_mode_result(server_module: ModuleType, state, *, result):
    if result.script is not None:
        state.current_script = result.script
        state.current_script_path = str(
            server_module._plot_mode_generated_script_path(state)
        )

    if result.execution_result is None:
        error_message = result.error_message or "Plot generation failed"
        state.last_error = error_message
        server_module._promote_plot_mode_workspace(state)
        return False, error_message

    if not result.execution_result.success or not result.execution_result.plot_path:
        error_message = result.execution_result.error or "Script execution failed"
        state.last_error = error_message
        server_module._promote_plot_mode_workspace(state)
        return False, error_message

    state.current_plot = result.execution_result.plot_path
    state.plot_type = result.execution_result.plot_type
    state.last_error = None
    server_module._promote_plot_mode_workspace(state)
    return True, None
