"""Pydantic data models for OpenPlot sessions, annotations, and revisions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# SVG element info (click-to-select mode)
# ---------------------------------------------------------------------------


class ElementInfo(BaseModel):
    """Metadata extracted from a clicked SVG DOM element."""

    tag: str  # e.g. "text", "rect", "path"
    text_content: str = ""  # inner text if any
    attributes: dict[str, str] = Field(default_factory=dict)  # font-size, fill, …
    xpath: str = ""  # for precise re-selection
    bbox: dict[str, float] | None = (
        None  # {x, y, width, height} from getBoundingClientRect
    )


# ---------------------------------------------------------------------------
# Raster region info (freeform annotation mode)
# ---------------------------------------------------------------------------


class RegionType(str, Enum):
    rect = "rect"
    ellipse = "ellipse"
    freeform = "freeform"


class RegionInfo(BaseModel):
    """A drawn region on a raster plot."""

    type: RegionType
    # Normalized coordinates (0-1 relative to image dimensions)
    points: list[dict[str, float]]  # [{x, y}, …]
    crop_base64: str = ""  # base64-encoded PNG crop of the region


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------


class AnnotationStatus(str, Enum):
    pending = "pending"
    addressed = "addressed"


class Annotation(BaseModel):
    """A single piece of user feedback attached to a plot element or region."""

    id: str = Field(default_factory=_new_id)
    plot_id: str = ""
    element_info: ElementInfo | None = None  # SVG mode
    region: RegionInfo | None = None  # Raster mode
    feedback: str = ""  # natural-language feedback
    status: AnnotationStatus = AnnotationStatus.pending
    base_version_id: str = ""  # version where annotation was created
    branch_id: str = ""  # branch this annotation belongs to
    addressed_in_version_id: str | None = None  # version that addressed this annotation
    created_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# Revision history
# ---------------------------------------------------------------------------


class Revision(BaseModel):
    """A snapshot of a script + its rendered plot at a point in time."""

    script: str
    plot_path: str
    plot_type: Literal["svg", "raster"]
    timestamp: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------------
# Version graph
# ---------------------------------------------------------------------------


class VersionNode(BaseModel):
    """A version node in the script/plot history graph."""

    id: str = Field(default_factory=_new_id)
    parent_version_id: str | None = None
    branch_id: str = ""
    annotation_id: str | None = None
    script_artifact_path: str | None = None
    plot_artifact_path: str = ""
    plot_type: Literal["svg", "raster"]
    timestamp: str = Field(default_factory=_now_iso)


class Branch(BaseModel):
    """A named branch with a movable head pointer."""

    id: str = Field(default_factory=_new_id)
    name: str
    base_version_id: str
    head_version_id: str
    created_at: str = Field(default_factory=_now_iso)


class OpencodeModelOption(BaseModel):
    """An opencode model option and its available variants."""

    id: str
    provider: str
    name: str
    variants: list[str] = Field(default_factory=list)


FixRunner = Literal["opencode", "codex", "claude"]


class FixStepStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class FixJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class FixJobStep(BaseModel):
    """One background fix iteration targeting one annotation."""

    index: int
    annotation_id: str
    status: FixStepStatus = FixStepStatus.queued
    command: list[str] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None


class FixJob(BaseModel):
    """A background queue job that repeatedly runs one /plot-fix iteration."""

    id: str = Field(default_factory=_new_id)
    runner: FixRunner = "opencode"
    model: str
    variant: str | None = None
    status: FixJobStatus = FixJobStatus.queued
    session_id: str = ""
    workspace_dir: str = ""
    branch_id: str
    branch_name: str
    total_annotations: int = 0
    completed_annotations: int = 0
    created_at: str = Field(default_factory=_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    last_error: str | None = None
    steps: list[FixJobStep] = Field(default_factory=list)


class PlotModePhase(str, Enum):
    awaiting_files = "awaiting_files"
    profiling_data = "profiling_data"
    awaiting_data_choice = "awaiting_data_choice"
    planning = "planning"
    awaiting_prompt = "awaiting_prompt"
    awaiting_plan_approval = "awaiting_plan_approval"
    drafting = "drafting"
    self_review = "self_review"
    ready = "ready"


class PlotModeExecutionMode(str, Enum):
    quick = "quick"
    autonomous = "autonomous"


class PlotModeMessageKind(str, Enum):
    markdown = "markdown"
    status = "status"
    activity = "activity"
    table_preview = "table_preview"
    question = "question"


class PlotModeQuestionOption(BaseModel):
    id: str
    label: str
    description: str = ""
    recommended: bool = False


class PlotModeQuestionItem(BaseModel):
    id: str = Field(default_factory=_new_id)
    title: str | None = None
    prompt: str
    options: list[PlotModeQuestionOption] = Field(default_factory=list)
    allow_custom_answer: bool = True
    multiple: bool = False
    answered: bool = False
    selected_option_ids: list[str] = Field(default_factory=list)
    answer_text: str | None = None


class PlotModeQuestionSet(BaseModel):
    id: str = Field(default_factory=_new_id)
    purpose: Literal[
        "select_data_source",
        "confirm_tabular_range",
        "confirm_data_preview",
        "continue_plot_planning",
        "approve_plot_plan",
    ]
    title: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    questions: list[PlotModeQuestionItem] = Field(default_factory=list)


class PlotModeInputBundle(BaseModel):
    id: str = Field(default_factory=_new_id)
    label: str = ""
    summary: str = ""
    selection_kind: str = "data"
    file_ids: list[str] = Field(default_factory=list)
    file_paths: list[str] = Field(default_factory=list)
    file_count: int = 0
    file_kinds: list[str] = Field(default_factory=list)


class PlotModeResolvedDataSource(BaseModel):
    id: str = Field(default_factory=_new_id)
    kind: Literal[
        "single_file",
        "multi_file_collection",
        "excel_region",
        "multi_region_excel_source",
        "unstructured_file",
        "mixed_bundle",
    ]
    label: str
    summary: str = ""
    file_ids: list[str] = Field(default_factory=list)
    file_paths: list[str] = Field(default_factory=list)
    file_count: int = 0
    profile_ids: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    integrity_notes: list[str] = Field(default_factory=list)


class PlotModeMessageMetadata(BaseModel):
    kind: PlotModeMessageKind = PlotModeMessageKind.markdown
    title: str | None = None
    items: list[str] = Field(default_factory=list)
    table_columns: list[str] = Field(default_factory=list)
    table_rows: list[list[str]] = Field(default_factory=list)
    table_caption: str | None = None
    table_source_label: str | None = None
    question_set_id: str | None = None
    question_set_title: str | None = None
    questions: list[PlotModeQuestionItem] = Field(default_factory=list)


class PlotModeDataProfile(BaseModel):
    id: str = Field(default_factory=_new_id)
    file_path: str
    file_name: str
    source_label: str
    source_kind: str
    table_name: str | None = None
    summary: str = ""
    columns: list[str] = Field(default_factory=list)
    preview_rows: list[list[str]] = Field(default_factory=list)
    integrity_notes: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False
    source_file_id: str | None = None
    inferred_sheet_name: str | None = None
    inferred_bounds: tuple[int, int, int, int] | None = None
    tabular_regions: list["PlotModeDataRegion"] = Field(default_factory=list)


class PlotModeSheetBounds(BaseModel):
    row_start: int
    row_end: int
    col_start: int
    col_end: int


class PlotModeSheetCandidate(BaseModel):
    id: str = Field(default_factory=_new_id)
    label: str
    bounds: PlotModeSheetBounds
    summary: str = ""


class PlotModeSheetPreview(BaseModel):
    id: str = Field(default_factory=_new_id)
    name: str
    total_rows: int = 0
    total_cols: int = 0
    preview_rows: list[list[str]] = Field(default_factory=list)
    candidate_tables: list[PlotModeSheetCandidate] = Field(default_factory=list)


class PlotModeTabularSelectionRegion(BaseModel):
    id: str = Field(default_factory=_new_id)
    sheet_id: str
    sheet_name: str = ""
    bounds: PlotModeSheetBounds


class PlotModeDataRegion(BaseModel):
    id: str = Field(default_factory=_new_id)
    sheet_name: str | None = None
    source_label: str
    summary: str = ""
    bounds: PlotModeSheetBounds | None = None
    columns: list[str] = Field(default_factory=list)
    preview_rows: list[list[str]] = Field(default_factory=list)


class PlotModeTabularSelector(BaseModel):
    id: str = Field(default_factory=_new_id)
    file_id: str
    file_path: str
    file_name: str
    source_kind: str
    sheets: list[PlotModeSheetPreview] = Field(default_factory=list)
    selected_sheet_id: str | None = None
    selected_regions: list[PlotModeTabularSelectionRegion] = Field(default_factory=list)
    inferred_profile_id: str | None = None
    status_text: str = ""
    requires_user_hint: bool = False


class PlotModeFile(BaseModel):
    id: str = Field(default_factory=_new_id)
    name: str
    stored_path: str
    size_bytes: int
    content_type: str = ""
    is_python: bool = False


class PlotModeChatMessage(BaseModel):
    id: str = Field(default_factory=_new_id)
    role: Literal["user", "assistant", "error"]
    content: str
    metadata: PlotModeMessageMetadata | None = None
    created_at: str = Field(default_factory=_now_iso)


class PlotModeState(BaseModel):
    id: str = Field(default_factory=_new_id)
    phase: PlotModePhase = PlotModePhase.awaiting_files
    is_workspace: bool = False
    workspace_name: str = ""
    workspace_dir: str
    files: list[PlotModeFile] = Field(default_factory=list)
    input_bundle: PlotModeInputBundle | None = None
    messages: list[PlotModeChatMessage] = Field(default_factory=list)
    data_profiles: list[PlotModeDataProfile] = Field(default_factory=list)
    resolved_sources: list[PlotModeResolvedDataSource] = Field(default_factory=list)
    active_resolved_source_ids: list[str] = Field(default_factory=list)
    selected_data_profile_id: str | None = None
    tabular_selector: PlotModeTabularSelector | None = None
    pending_question_set: PlotModeQuestionSet | None = None
    execution_mode: PlotModeExecutionMode = PlotModeExecutionMode.quick
    latest_plan_summary: str = ""
    latest_plan_outline: list[str] = Field(default_factory=list)
    latest_plan_plot_type: str = ""
    latest_plan_actions: list[str] = Field(default_factory=list)
    current_script: str | None = None
    current_script_path: str | None = None
    current_plot: str | None = None
    plot_type: Literal["svg", "raster"] | None = None
    latest_user_goal: str = ""
    selected_runner: FixRunner = "opencode"
    selected_model: str = ""
    selected_variant: str = ""
    runner_session_ids: dict[str, str] = Field(default_factory=dict)
    last_error: str | None = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


PlotModeDataProfile.model_rebuild()


# ---------------------------------------------------------------------------
# Plot session (top-level state)
# ---------------------------------------------------------------------------


class PlotSession(BaseModel):
    """The full state of a debugging session."""

    id: str = Field(default_factory=_new_id)
    workspace_id: str = ""
    workspace_name: str = ""
    source_script: str | None = None  # script content
    source_script_path: str | None = None  # original file path
    current_plot: str = ""  # path or URL to current plot file
    plot_type: Literal["svg", "raster"] = "svg"
    annotations: list[Annotation] = Field(default_factory=list)
    versions: list[VersionNode] = Field(default_factory=list)
    branches: list[Branch] = Field(default_factory=list)
    root_version_id: str = ""
    active_branch_id: str = ""
    checked_out_version_id: str = ""
    runner_session_ids: dict[str, str] = Field(default_factory=dict)
    artifacts_root: str = ""
    revision_history: list[Revision] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
