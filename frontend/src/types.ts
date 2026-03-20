/** Shared TypeScript types mirroring the Python Pydantic models. */

export interface ElementInfo {
  tag: string;
  text_content: string;
  attributes: Record<string, string>;
  xpath: string;
  bbox: { x: number; y: number; width: number; height: number } | null;
}

export type RegionType = "rect" | "ellipse" | "freeform";

export interface RegionInfo {
  type: RegionType;
  points: Array<{ x: number; y: number }>;
  crop_base64: string;
}

export type AnnotationStatus = "pending" | "addressed";

export interface Annotation {
  id: string;
  plot_id: string;
  element_info: ElementInfo | null;
  region: RegionInfo | null;
  feedback: string;
  status: AnnotationStatus;
  base_version_id: string;
  branch_id: string;
  addressed_in_version_id: string | null;
  created_at: string;
}

export type PlotType = "svg" | "raster";

export interface Revision {
  script: string;
  plot_path: string;
  plot_type: PlotType;
  timestamp: string;
}

export interface VersionNode {
  id: string;
  parent_version_id: string | null;
  branch_id: string;
  annotation_id: string | null;
  script_artifact_path: string | null;
  plot_artifact_path: string;
  plot_type: PlotType;
  timestamp: string;
}

export interface Branch {
  id: string;
  name: string;
  base_version_id: string;
  head_version_id: string;
  created_at: string;
}

export interface PlotSession {
  id: string;
  workspace_id: string;
  workspace_name: string;
  source_script: string | null;
  source_script_path: string | null;
  current_plot: string;
  plot_type: PlotType;
  annotations: Annotation[];
  versions: VersionNode[];
  branches: Branch[];
  root_version_id: string;
  active_branch_id: string;
  checked_out_version_id: string;
  runner_session_ids: Record<string, string>;
  artifacts_root: string;
  revision_history: Revision[];
  created_at: string;
  updated_at: string;
}

export interface SessionSummary {
  id: string;
  session_id?: string | null;
  workspace_mode: AppMode;
  plot_phase?: PlotModePhase | null;
  workspace_name: string;
  source_script_path: string | null;
  plot_type: PlotType;
  annotation_count: number;
  pending_annotation_count: number;
  checked_out_version_id: string;
  created_at: string;
  updated_at: string;
}

export type AppMode = "annotation" | "plot";
export type FixRunner = "opencode" | "codex" | "claude";

export type PlotModePhase =
  | "awaiting_files"
  | "profiling_data"
  | "awaiting_data_choice"
  | "planning"
  | "awaiting_prompt"
  | "awaiting_plan_approval"
  | "drafting"
  | "self_review"
  | "ready";
export type PlotModeExecutionMode = "quick" | "autonomous";

export type PlotModeMessageKind =
  | "markdown"
  | "status"
  | "activity"
  | "table_preview"
  | "question";

export interface PlotModeQuestionOption {
  id: string;
  label: string;
  description: string;
  recommended: boolean;
}

export interface PlotModeQuestionItem {
  id: string;
  title: string | null;
  prompt: string;
  options: PlotModeQuestionOption[];
  allow_custom_answer: boolean;
  multiple: boolean;
  answered: boolean;
  selected_option_ids: string[];
  answer_text: string | null;
}

export interface PlotModeQuestionSet {
  id: string;
  purpose:
    | "select_data_source"
    | "confirm_tabular_range"
    | "confirm_data_preview"
    | "continue_plot_planning"
    | "approve_plot_plan";
  title: string | null;
  source_ids: string[];
  questions: PlotModeQuestionItem[];
}

export interface PlotModeMessageMetadata {
  kind: PlotModeMessageKind;
  title: string | null;
  items: string[];
  table_columns: string[];
  table_rows: string[][];
  table_caption: string | null;
  table_source_label: string | null;
  question_set_id: string | null;
  question_set_title: string | null;
  questions: PlotModeQuestionItem[];
}

export interface PlotModeDataProfile {
  id: string;
  file_path: string;
  file_name: string;
  source_label: string;
  source_kind: string;
  table_name: string | null;
  summary: string;
  columns: string[];
  preview_rows: string[][];
  integrity_notes: string[];
  needs_confirmation: boolean;
  source_file_id: string | null;
  inferred_sheet_name: string | null;
  inferred_bounds: [number, number, number, number] | null;
  tabular_regions: PlotModeDataRegion[];
}

export interface PlotModeSheetBounds {
  row_start: number;
  row_end: number;
  col_start: number;
  col_end: number;
}

export interface PlotModeSheetCandidate {
  id: string;
  label: string;
  bounds: PlotModeSheetBounds;
  summary: string;
}

export interface PlotModeTabularSelectionRegion {
  id: string;
  sheet_id: string;
  sheet_name: string;
  bounds: PlotModeSheetBounds;
}

export interface PlotModeDataRegion {
  id: string;
  sheet_name: string | null;
  source_label: string;
  summary: string;
  bounds: PlotModeSheetBounds | null;
  columns: string[];
  preview_rows: string[][];
}

export interface PlotModeSheetPreview {
  id: string;
  name: string;
  total_rows: number;
  total_cols: number;
  preview_rows: string[][];
  candidate_tables: PlotModeSheetCandidate[];
}

export interface PlotModeTabularSelector {
  id: string;
  file_id: string;
  file_path: string;
  file_name: string;
  source_kind: string;
  sheets: PlotModeSheetPreview[];
  selected_sheet_id: string | null;
  selected_regions: PlotModeTabularSelectionRegion[];
  inferred_profile_id: string | null;
  status_text: string;
  requires_user_hint: boolean;
}

export type PlotModePathSelectionType = "data" | "script";

export interface PlotModePathSuggestion {
  path: string;
  display_path: string;
  is_dir: boolean;
  is_file: boolean;
}

export interface PlotModePathSuggestionResponse {
  query: string;
  selection_type: PlotModePathSelectionType;
  base_dir: string;
  suggestions: PlotModePathSuggestion[];
}

export interface PlotModeFile {
  id: string;
  name: string;
  stored_path: string;
  size_bytes: number;
  content_type: string;
  is_python: boolean;
}

export interface PlotModeChatMessage {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  metadata: PlotModeMessageMetadata | null;
  created_at: string;
}

export interface PlotModeState {
  id: string;
  phase: PlotModePhase;
  workspace_name: string;
  workspace_dir: string;
  files: PlotModeFile[];
  messages: PlotModeChatMessage[];
  data_profiles: PlotModeDataProfile[];
  selected_data_profile_id: string | null;
  tabular_selector: PlotModeTabularSelector | null;
  pending_question_set: PlotModeQuestionSet | null;
  execution_mode: PlotModeExecutionMode;
  latest_plan_summary: string;
  latest_plan_outline: string[];
  latest_plan_plot_type: string;
  latest_plan_actions: string[];
  current_script: string | null;
  current_script_path: string | null;
  current_plot: string | null;
  plot_type: PlotType | null;
  latest_user_goal: string;
  selected_runner: FixRunner;
  selected_model: string;
  selected_variant: string;
  runner_session_ids: Record<string, string>;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface BootstrapState {
  mode: AppMode;
  session?: PlotSession | null;
  plot_mode?: PlotModeState | null;
  sessions?: SessionSummary[];
  active_session_id?: string | null;
  active_workspace_id?: string | null;
}

export interface RunnerAvailabilityState {
  available_runners: FixRunner[];
  supported_runners: FixRunner[];
  claude_code_available: boolean;
}

export type RunnerPrimaryAction = "install" | "guide" | "authenticate" | "none";

export type RunnerCapabilityStatus =
  | "installed"
  | "installing"
  | "installed_needs_auth"
  | "available_to_install"
  | "blocked_by_prerequisite"
  | "manual"
  | "needs_attention"
  | "unsupported";

export interface RunnerInstallJobState {
  id: string;
  runner: FixRunner;
  state: "queued" | "running" | "succeeded" | "failed" | "interrupted";
  logs: string[];
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  resolved_path?: string | null;
}

export interface RunnerStatusEntry {
  runner: FixRunner;
  status: RunnerCapabilityStatus;
  status_label: string;
  primary_action: RunnerPrimaryAction;
  primary_action_label: string;
  guide_url: string;
  installed: boolean;
  executable_path: string | null;
  install_job: RunnerInstallJobState | null;
  auth_command: string | null;
  auth_instructions: string | null;
}

export interface RunnerStatusState extends RunnerAvailabilityState {
  host_platform: string;
  host_arch: string;
  active_install_job_id: string | null;
  runners: RunnerStatusEntry[];
}

export interface OpencodeModelOption {
  id: string;
  provider: string;
  name: string;
  variants: string[];
}

export type PythonInterpreterMode = "builtin" | "manual";

export interface PythonInterpreterCandidate {
  path: string;
  source: string;
  version: string;
}

export interface PythonInterpreterState {
  mode: PythonInterpreterMode;
  configured_path: string | null;
  configured_error: string | null;
  resolved_path: string;
  resolved_source: string;
  resolved_version: string;
  default_path: string;
  default_version: string;
  default_available_packages: string[];
  default_available_package_count: number;
  default_package_probe_error: string | null;
  available_packages: string[];
  available_package_count: number;
  package_probe_error: string | null;
  data_root: string;
  state_root: string;
  context_dir: string;
  candidates: PythonInterpreterCandidate[];
}

export type FixStepStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type FixJobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface FixJobStep {
  index: number;
  annotation_id: string;
  status: FixStepStatus;
  command: string[];
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  error: string | null;
}

export interface FixJob {
  id: string;
  runner: FixRunner;
  model: string;
  variant: string | null;
  status: FixJobStatus;
  session_id: string;
  workspace_dir: string;
  branch_id: string;
  branch_name: string;
  total_annotations: number;
  completed_annotations: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
  steps: FixJobStep[];
}

export interface FixJobLogEvent {
  type: "fix_job_log";
  job_id: string;
  step_index: number;
  annotation_id: string;
  stream: "stdout" | "stderr";
  chunk: string;
  timestamp: string;
  parsed: Record<string, unknown> | null;
}

/** WebSocket event types pushed from the server. */
export type WsEvent =
  | {
      type: "plot_updated";
      session_id?: string;
      version_id?: string;
      plot_type?: PlotType;
      revision?: number;
      active_branch_id?: string;
      checked_out_version_id?: string;
      reason?: string;
      annotation_id?: string;
    }
  | { type: "annotation_added"; annotation: Annotation; session_id?: string }
  | { type: "annotation_deleted"; id: string; deleted_ids?: string[]; session_id?: string }
  | { type: "annotation_updated"; annotation: Annotation; session_id?: string }
  | { type: "plot_mode_updated"; plot_mode: PlotModeState }
  | {
      type: "plot_mode_message_updated";
      plot_mode_id: string;
      updated_at: string;
      message: PlotModeChatMessage;
    }
  | { type: "plot_mode_completed"; session: PlotSession }
  | { type: "fix_job_updated"; job: FixJob }
  | FixJobLogEvent;
