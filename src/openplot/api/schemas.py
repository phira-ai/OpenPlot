"""Typed request payloads for the OpenPlot FastAPI server."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..models import FixRunner


class PlotModePathSuggestionsRequest(BaseModel):
    selection_type: Literal["data", "script"] = "data"
    query: str = ""
    workspace_id: str | None = None


class PlotModeSelectPathsRequest(BaseModel):
    selection_type: Literal["data", "script"]
    paths: list[str]
    workspace_id: str | None = None


class PlotModeChatRequest(BaseModel):
    message: str = ""
    workspace_id: str | None = None
    runner: FixRunner | None = None
    model: str | None = None
    variant: str | None = None


class PlotModeSettingsRequest(BaseModel):
    execution_mode: Literal["quick", "autonomous"]
    workspace_id: str | None = None


class PlotModeQuestionAnswerItemRequest(BaseModel):
    question_id: str
    option_ids: list[str] = []
    text: str | None = None


class PlotModeQuestionAnswerRequest(BaseModel):
    question_set_id: str
    answers: list[PlotModeQuestionAnswerItemRequest] = []
    workspace_id: str | None = None
    runner: FixRunner | None = None
    model: str | None = None
    variant: str | None = None


class PlotModeTabularHintRegionRequest(BaseModel):
    sheet_id: str
    row_start: int
    row_end: int
    col_start: int
    col_end: int


class PlotModeTabularHintRequest(BaseModel):
    selector_id: str
    regions: list[PlotModeTabularHintRegionRequest] = []
    workspace_id: str | None = None
    sheet_id: str | None = None
    row_start: int | None = None
    row_end: int | None = None
    col_start: int | None = None
    col_end: int | None = None
    note: str | None = None
    runner: FixRunner | None = None
    model: str | None = None
    variant: str | None = None


class PlotModeFinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    workspace_id: str | None = None


class RenameSessionRequest(BaseModel):
    workspace_name: str | None = None
    name: str | None = None


class RenameBranchRequest(BaseModel):
    name: str | None = None
    branch_name: str | None = None


class PreferencesRequest(BaseModel):
    fix_runner: FixRunner | None = None
    fix_model: str | None = None
    fix_variant: str | None = None


class PythonInterpreterRequest(BaseModel):
    mode: Literal["builtin", "manual", "auto"] = "builtin"
    path: str | None = None


class RunnerInstallRequest(BaseModel):
    runner: FixRunner


class RunnerAuthLaunchRequest(BaseModel):
    runner: FixRunner


class OpenExternalUrlRequest(BaseModel):
    url: str


class StartFixJobRequest(BaseModel):
    session_id: str | None = None
    runner: FixRunner | None = None
    model: str = ""
    variant: str | None = None


class CheckoutVersionRequest(BaseModel):
    version_id: str = ""
    branch_id: str | None = None


class AnnotationUpdateRequest(BaseModel):
    feedback: str | None = None
    status: str | None = None


class SubmitScriptRequest(BaseModel):
    code: str = ""
    annotation_id: str | None = None
