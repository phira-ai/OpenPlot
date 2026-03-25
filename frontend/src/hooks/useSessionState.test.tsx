// @vitest-environment jsdom

import { act, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BootstrapState,
  Branch,
  FixJob,
  PlotModeState,
  PythonInterpreterState,
  RunnerStatusState,
  PlotSession,
} from "../types";

type PreferencesResponse = {
  fix_runner?: "opencode" | "codex" | "claude";
  fix_model?: string;
  fix_variant?: string | null;
};

vi.mock("../api/sessions", () => ({
  fetchBootstrap: vi.fn(),
  createSession: vi.fn(),
  activateAnnotationSession: vi.fn(),
  updateAnnotationWorkspace: vi.fn(),
  deleteAnnotationWorkspace: vi.fn(),
}));

vi.mock("../api/plotMode", () => ({
  activatePlotWorkspace: vi.fn(),
  fetchPlotModePathSuggestions: vi.fn(),
  selectPlotModePaths: vi.fn(),
  sendPlotModeMessage: vi.fn(),
  submitPlotModeTabularHint: vi.fn(),
  updatePlotModeSettings: vi.fn(),
  answerPlotModeQuestion: vi.fn(),
  finalizePlotMode: vi.fn(),
  updatePlotWorkspace: vi.fn(),
  deletePlotWorkspace: vi.fn(),
}));

vi.mock("../api/fixJobs", () => ({
  fetchCurrentFixJob: vi.fn(),
  startFixJob: vi.fn(),
  cancelFixJob: vi.fn(),
}));

vi.mock("../api/runners", () => ({
  fetchRunnerStatus: vi.fn(),
  installRunner: vi.fn(),
  launchRunnerAuth: vi.fn(),
  fetchRunnerModels: vi.fn(),
}));

vi.mock("../api/preferences", () => ({
  fetchPreferences: vi.fn(),
  updateFixPreferences: vi.fn(),
}));

vi.mock("../api/annotations", () => ({
  createAnnotation: vi.fn(),
  deleteAnnotation: vi.fn(),
  updateAnnotation: vi.fn(),
}));

vi.mock("../api/versioning", () => ({
  checkoutVersion: vi.fn(),
  checkoutBranch: vi.fn(),
  renameBranch: vi.fn(),
}));

vi.mock("../api/artifacts", () => ({
  downloadAnnotationArtifact: vi.fn(),
  downloadPlotModeArtifact: vi.fn(),
}));

vi.mock("../api/runtime", () => ({
  openExternalUrl: vi.fn(),
  refreshUpdateStatus: vi.fn(),
  fetchPythonInterpreter: vi.fn(),
  updatePythonInterpreter: vi.fn(),
}));

import {
  createAnnotation,
  deleteAnnotation,
  updateAnnotation,
} from "../api/annotations";
import {
  downloadAnnotationArtifact,
  downloadPlotModeArtifact,
} from "../api/artifacts";
import {
  cancelFixJob,
  fetchCurrentFixJob,
  startFixJob,
} from "../api/fixJobs";
import {
  activatePlotWorkspace,
  answerPlotModeQuestion,
  deletePlotWorkspace,
  fetchPlotModePathSuggestions,
  finalizePlotMode,
  selectPlotModePaths,
  sendPlotModeMessage,
  submitPlotModeTabularHint,
  updatePlotModeSettings,
  updatePlotWorkspace,
} from "../api/plotMode";
import { fetchPreferences, updateFixPreferences } from "../api/preferences";
import {
  fetchRunnerModels,
  fetchRunnerStatus,
  installRunner,
  launchRunnerAuth,
} from "../api/runners";
import {
  fetchPythonInterpreter,
  openExternalUrl,
  refreshUpdateStatus,
  updatePythonInterpreter,
} from "../api/runtime";
import {
  activateAnnotationSession,
  createSession,
  deleteAnnotationWorkspace,
  fetchBootstrap,
  updateAnnotationWorkspace,
} from "../api/sessions";
import {
  checkoutBranch,
  checkoutVersion,
  renameBranch,
} from "../api/versioning";
import { useSessionState } from "./useSessionState";
import { subscribeToRawWsEvents } from "./useWebSocket";

const fetchBootstrapMock = vi.mocked(fetchBootstrap);
const createSessionMock = vi.mocked(createSession);
const activateAnnotationSessionMock = vi.mocked(activateAnnotationSession);
const updateAnnotationWorkspaceMock = vi.mocked(updateAnnotationWorkspace);
const deleteAnnotationWorkspaceMock = vi.mocked(deleteAnnotationWorkspace);
const activatePlotWorkspaceMock = vi.mocked(activatePlotWorkspace);
const fetchPlotModePathSuggestionsMock = vi.mocked(fetchPlotModePathSuggestions);
const selectPlotModePathsMock = vi.mocked(selectPlotModePaths);
const sendPlotModeMessageMock = vi.mocked(sendPlotModeMessage);
const submitPlotModeTabularHintMock = vi.mocked(submitPlotModeTabularHint);
const updatePlotModeSettingsMock = vi.mocked(updatePlotModeSettings);
const answerPlotModeQuestionMock = vi.mocked(answerPlotModeQuestion);
const finalizePlotModeMock = vi.mocked(finalizePlotMode);
const updatePlotWorkspaceMock = vi.mocked(updatePlotWorkspace);
const deletePlotWorkspaceMock = vi.mocked(deletePlotWorkspace);
const fetchCurrentFixJobMock = vi.mocked(fetchCurrentFixJob);
const startFixJobMock = vi.mocked(startFixJob);
const cancelFixJobMock = vi.mocked(cancelFixJob);
const fetchRunnerStatusMock = vi.mocked(fetchRunnerStatus);
const installRunnerMock = vi.mocked(installRunner);
const launchRunnerAuthMock = vi.mocked(launchRunnerAuth);
const fetchRunnerModelsMock = vi.mocked(fetchRunnerModels);
const fetchPreferencesMock = vi.mocked(fetchPreferences);
const updateFixPreferencesMock = vi.mocked(updateFixPreferences);
const createAnnotationMock = vi.mocked(createAnnotation);
const deleteAnnotationMock = vi.mocked(deleteAnnotation);
const updateAnnotationMock = vi.mocked(updateAnnotation);
const checkoutVersionMock = vi.mocked(checkoutVersion);
const checkoutBranchMock = vi.mocked(checkoutBranch);
const renameBranchMock = vi.mocked(renameBranch);
const downloadAnnotationArtifactMock = vi.mocked(downloadAnnotationArtifact);
const downloadPlotModeArtifactMock = vi.mocked(downloadPlotModeArtifact);
const openExternalUrlMock = vi.mocked(openExternalUrl);
const refreshUpdateStatusMock = vi.mocked(refreshUpdateStatus);
const fetchPythonInterpreterMock = vi.mocked(fetchPythonInterpreter);
const updatePythonInterpreterMock = vi.mocked(updatePythonInterpreter);

interface AnswerPlotModeQuestionRequestBody {
  workspace_id?: string | null;
  question_set_id?: string;
}

function createPlotModeState(id: string, workspaceName: string): PlotModeState {
  return {
    id,
    phase: "ready",
    workspace_name: workspaceName,
    workspace_dir: `/tmp/${id}`,
    files: [],
    input_bundle: null,
    messages: [],
    data_profiles: [],
    resolved_sources: [],
    active_resolved_source_ids: [],
    selected_data_profile_id: null,
    tabular_selector: null,
    pending_question_set: null,
    execution_mode: "quick",
    latest_plan_summary: "",
    latest_plan_outline: [],
    latest_plan_plot_type: "svg",
    latest_plan_actions: [],
    current_script: null,
    current_script_path: null,
    current_plot: `/tmp/${id}.png`,
    plot_type: "svg",
    latest_user_goal: "",
    selected_runner: "opencode",
    selected_model: "",
    selected_variant: "",
    runner_session_ids: {},
    last_error: null,
    created_at: "2026-03-18T18:00:00Z",
    updated_at: "2026-03-18T19:00:00Z",
  };
}

function createPlotBootstrap(activeId: string): BootstrapState {
  return {
    mode: "plot",
    plot_mode: createPlotModeState(activeId, `Workspace ${activeId}`),
    session: null,
    active_session_id: null,
    active_workspace_id: activeId,
    sessions: [
      {
        id: "plot-a",
        session_id: null,
        workspace_mode: "plot",
        plot_phase: "ready",
        workspace_name: "Workspace A",
        source_script_path: null,
        plot_type: "svg",
        annotation_count: 0,
        pending_annotation_count: 0,
        checked_out_version_id: "",
        created_at: "2026-03-18T18:00:00Z",
        updated_at: activeId === "plot-a" ? "2026-03-18T19:10:00Z" : "2026-03-18T19:00:00Z",
      },
      {
        id: "plot-b",
        session_id: null,
        workspace_mode: "plot",
        plot_phase: "ready",
        workspace_name: "Workspace B",
        source_script_path: null,
        plot_type: "svg",
        annotation_count: 0,
        pending_annotation_count: 0,
        checked_out_version_id: "",
        created_at: "2026-03-18T18:05:00Z",
        updated_at: activeId === "plot-b" ? "2026-03-18T19:10:00Z" : "2026-03-18T19:00:00Z",
      },
    ],
  };
}

function createAnnotationBootstrap(): BootstrapState {
  const session: PlotSession = {
    id: "annotation-1",
    workspace_id: "annotation-1",
    workspace_name: "Annotation Workspace",
    source_script: "print('hi')",
    source_script_path: "/tmp/annotation.py",
    current_plot: "/tmp/annotation.png",
    plot_type: "svg",
    annotations: [],
    versions: [],
    branches: [],
    root_version_id: "",
    active_branch_id: "",
    checked_out_version_id: "",
    runner_session_ids: {},
    artifacts_root: "/tmp/annotation-artifacts",
    revision_history: [],
    created_at: "2026-03-18T18:00:00Z",
    updated_at: "2026-03-18T19:00:00Z",
  };

  return {
    mode: "annotation",
    session,
    plot_mode: null,
    active_session_id: session.id,
    active_workspace_id: session.workspace_id,
    sessions: [
      {
        id: session.workspace_id,
        session_id: session.id,
        workspace_mode: "annotation",
        workspace_name: session.workspace_name,
        source_script_path: session.source_script_path,
        plot_type: session.plot_type,
        annotation_count: 0,
        pending_annotation_count: 0,
        checked_out_version_id: "",
        created_at: session.created_at,
        updated_at: session.updated_at,
      },
      {
        id: "plot-b",
        session_id: null,
        workspace_mode: "plot",
        plot_phase: "ready",
        workspace_name: "Workspace B",
        source_script_path: null,
        plot_type: "svg",
        annotation_count: 0,
        pending_annotation_count: 0,
        checked_out_version_id: "",
        created_at: "2026-03-18T18:05:00Z",
        updated_at: "2026-03-18T19:10:00Z",
      },
    ],
  };
}

const pythonInterpreterState: PythonInterpreterState = {
  mode: "builtin",
  configured_path: null,
  configured_error: null,
  resolved_path: "/usr/bin/python3",
  resolved_source: "builtin",
  resolved_version: "3.12.0",
  default_path: "/usr/bin/python3",
  default_version: "3.12.0",
  default_available_packages: [],
  default_available_package_count: 0,
  default_package_probe_error: null,
  available_packages: [],
  available_package_count: 0,
  package_probe_error: null,
  data_root: "/tmp/data",
  state_root: "/tmp/state",
  context_dir: "/tmp/context",
  candidates: [],
};

function createRunnerStatusState(
  overrides: Partial<RunnerStatusState> = {},
): RunnerStatusState {
  return {
    available_runners: [],
    supported_runners: ["opencode", "codex", "claude"],
    claude_code_available: false,
    host_platform: "darwin",
    host_arch: "arm64",
    active_install_job_id: null,
    runners: [
      {
        runner: "opencode",
        status: "available_to_install",
        status_label: "Available to install",
        primary_action: "install",
        primary_action_label: "Install",
        guide_url: "https://opencode.ai/docs",
        installed: false,
        executable_path: null,
        install_job: null,
        auth_command: null,
        auth_instructions: null,
      },
      {
        runner: "codex",
        status: "available_to_install",
        status_label: "Available to install",
        primary_action: "install",
        primary_action_label: "Install",
        guide_url: "https://developers.openai.com/codex",
        installed: false,
        executable_path: null,
        install_job: null,
        auth_command: null,
        auth_instructions: null,
      },
      {
        runner: "claude",
        status: "available_to_install",
        status_label: "Available to install",
        primary_action: "install",
        primary_action_label: "Install",
        guide_url: "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview",
        installed: false,
        executable_path: null,
        install_job: null,
        auth_command: null,
        auth_instructions: null,
      },
    ],
    ...overrides,
  };
}

function createFixJob(jobId = "job-1"): FixJob {
  return {
    id: jobId,
    session_id: "annotation-1",
    workspace_dir: "/tmp/annotation-1",
    branch_id: "branch-1",
    branch_name: "Branch 1",
    runner: "codex",
    model: "gpt-4.1",
    variant: null,
    status: "running",
    total_annotations: 1,
    completed_annotations: 0,
    started_at: "2026-03-18T18:10:00Z",
    finished_at: null,
    created_at: "2026-03-18T18:10:00Z",
    last_error: null,
    steps: [],
  };
}

function createDownloadResponse() {
  return {
    blob: vi.fn().mockResolvedValue(new Blob(["zip"])),
    headers: {
      get: vi.fn((name: string) =>
        name === "Content-Disposition" ? 'attachment; filename="artifact.zip"' : null,
      ),
    },
  };
}

function createBranch(name = "Renamed Branch"): Branch {
  return {
    id: "branch-1",
    name,
    base_version_id: "version-0",
    head_version_id: "version-1",
    created_at: "2026-03-18T18:00:00Z",
  };
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}

describe("useSessionState", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let latestState: ReturnType<typeof useSessionState> | null;

  function Harness() {
    const state = useSessionState();

    useEffect(() => {
      latestState = state;
    }, [state]);

    return null;
  }

  async function renderHarness() {
    await act(async () => {
      root.render(<Harness />);
      await flushPromises();
    });
  }

  beforeEach(() => {
    const annotationBootstrap = createAnnotationBootstrap();
    const annotationWorkspace = annotationBootstrap.sessions?.[0];
    if (!annotationWorkspace) {
      throw new Error("Missing annotation workspace fixture");
    }

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    latestState = null;
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("setInterval", vi.fn(() => 1));
    vi.stubGlobal("clearInterval", vi.fn());

    fetchBootstrapMock.mockResolvedValue(createPlotBootstrap("plot-initial"));
    createSessionMock.mockResolvedValue(createPlotBootstrap("plot-new"));
    activateAnnotationSessionMock.mockResolvedValue(annotationBootstrap);
    updateAnnotationWorkspaceMock.mockResolvedValue({
      status: "ok",
      workspace: {
        ...annotationWorkspace,
        workspace_name: "Renamed Annotation Workspace",
      },
      active_session_id: "annotation-1",
    });
    deleteAnnotationWorkspaceMock.mockResolvedValue(createPlotBootstrap("plot-b"));

    activatePlotWorkspaceMock.mockResolvedValue(createPlotBootstrap("plot-b"));
    fetchPlotModePathSuggestionsMock.mockResolvedValue({ suggestions: [] } as never);
    selectPlotModePathsMock.mockResolvedValue(createPlotBootstrap("plot-a"));
    sendPlotModeMessageMock.mockResolvedValue({
      status: "ok",
      plot_mode: createPlotModeState("plot-a", "Workspace plot-a"),
    });
    submitPlotModeTabularHintMock.mockResolvedValue({
      status: "ok",
      plot_mode: createPlotModeState("plot-a", "Workspace plot-a"),
    });
    updatePlotModeSettingsMock.mockResolvedValue({
      status: "ok",
      plot_mode: createPlotModeState("plot-a", "Workspace plot-a"),
    });
    answerPlotModeQuestionMock.mockResolvedValue({
      status: "ok",
      plot_mode: createPlotModeState("plot-b", "Workspace B"),
    });
    finalizePlotModeMock.mockResolvedValue(createPlotBootstrap("plot-a"));
    updatePlotWorkspaceMock.mockResolvedValue({
      status: "ok",
      plot_mode: createPlotModeState("plot-a", "Renamed Plot Workspace"),
    });
    deletePlotWorkspaceMock.mockResolvedValue(createPlotBootstrap("plot-b"));

    fetchCurrentFixJobMock.mockResolvedValue({ job: null });
    startFixJobMock.mockResolvedValue({ status: "ok", job: createFixJob() });
    cancelFixJobMock.mockResolvedValue({ status: "ok", job: createFixJob("job-2") });

    fetchRunnerStatusMock.mockResolvedValue(createRunnerStatusState());
    installRunnerMock.mockResolvedValue({ job: { id: "install-1" } });
    launchRunnerAuthMock.mockResolvedValue({ status: "ok" });
    fetchRunnerModelsMock.mockResolvedValue({
      runner: "opencode",
      models: [],
      default_model: "",
      default_variant: "",
    });

    fetchPreferencesMock.mockResolvedValue({});
    updateFixPreferencesMock.mockResolvedValue({
      status: "ok",
      fix_runner: "codex",
      fix_model: "gpt-4.1",
      fix_variant: "fast",
    });

    createAnnotationMock.mockResolvedValue({ status: "ok", id: "annotation-2" });
    deleteAnnotationMock.mockResolvedValue({});
    updateAnnotationMock.mockResolvedValue({});

    checkoutVersionMock.mockResolvedValue({});
    checkoutBranchMock.mockResolvedValue({});
    renameBranchMock.mockResolvedValue({
      status: "ok",
      branch: createBranch(),
      active_branch_id: "branch-1",
    });

    downloadAnnotationArtifactMock.mockResolvedValue(createDownloadResponse() as never);
    downloadPlotModeArtifactMock.mockResolvedValue(createDownloadResponse() as never);

    openExternalUrlMock.mockResolvedValue({ status: "ok" });
    refreshUpdateStatusMock.mockResolvedValue({
      current_version: "1.0.0",
      latest_version: "1.0.1",
      latest_release_url: "https://example.com/release",
      update_available: true,
      checked_at: "2026-03-18T20:00:00Z",
      error: null,
    });
    fetchPythonInterpreterMock.mockResolvedValue(pythonInterpreterState);
    updatePythonInterpreterMock.mockResolvedValue({
      ...pythonInterpreterState,
      mode: "manual",
      configured_path: "/custom/python",
    });
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads rich runner status and keeps onboarding state when no runners are available", async () => {
    const runnerStatus = createRunnerStatusState();
    fetchRunnerStatusMock.mockResolvedValue(runnerStatus);

    await renderHarness();

    expect(fetchRunnerStatusMock).toHaveBeenCalledWith();
    expect(fetchPreferencesMock).toHaveBeenCalledWith();
    expect(fetchPythonInterpreterMock).toHaveBeenCalledWith();
    expect(latestState?.runnerStatus).toEqual(runnerStatus);
    expect(latestState?.availableRunners).toEqual([]);
    expect(latestState?.runnerStatusLoading).toBe(false);
    expect(latestState?.runnerStatusError).toBeNull();
    expect(latestState?.backendFatalError).toBe(
      "At least one backend CLI must exist: codex, claude code, opencode.",
    );
  });

  it("keeps the saved runner preference when runner discovery resolves first", async () => {
    let resolvePreferences: ((value: PreferencesResponse) => void) | null = null;
    fetchRunnerStatusMock.mockResolvedValue(
      createRunnerStatusState({ available_runners: ["opencode", "codex"] }),
    );
    fetchPreferencesMock.mockImplementation(
      () =>
        new Promise<PreferencesResponse>((resolve) => {
          resolvePreferences = resolve;
        }),
    );

    await renderHarness();

    expect(latestState?.selectedRunner).toBe("opencode");

    await act(async () => {
      resolvePreferences?.({ fix_runner: "codex" });
      await flushPromises();
    });

    expect(latestState?.selectedRunner).toBe("codex");
  });

  it("ignores a stale runner availability response that resolves after a newer refresh", async () => {
    const runnerStatusResolvers: Array<(value: RunnerStatusState) => void> = [];
    fetchRunnerStatusMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          runnerStatusResolvers.push(resolve);
        }),
    );

    await renderHarness();

    await act(async () => {
      void latestState?.refreshRunnerAvailability();
      await flushPromises();
    });

    await act(async () => {
      runnerStatusResolvers[1]?.(
        createRunnerStatusState({
          available_runners: ["codex"],
        }),
      );
      await flushPromises();
    });

    expect(latestState?.availableRunners).toEqual(["codex"]);

    await act(async () => {
      runnerStatusResolvers[0]?.(
        createRunnerStatusState({
          available_runners: [],
        }),
      );
      await flushPromises();
    });

    expect(latestState?.availableRunners).toEqual(["codex"]);
    expect(latestState?.backendFatalError).toBeNull();
  });

  it("prefers session workspace_id when bootstrap omits active_workspace_id", async () => {
    const annotationBootstrap = createAnnotationBootstrap();
    const distinctWorkspaceBootstrap: BootstrapState = {
      ...annotationBootstrap,
      session: {
        ...annotationBootstrap.session!,
        id: "annotation-session-1",
        workspace_id: "annotation-workspace-1",
      },
      active_session_id: "annotation-session-1",
      sessions: [
        {
          ...annotationBootstrap.sessions![0]!,
          id: "annotation-workspace-1",
          session_id: "annotation-session-1",
        },
        ...annotationBootstrap.sessions!.slice(1),
      ],
    };
    delete (distinctWorkspaceBootstrap as { active_workspace_id?: string | null }).active_workspace_id;
    fetchBootstrapMock.mockResolvedValueOnce(distinctWorkspaceBootstrap);

    await renderHarness();

    expect(latestState?.activeSessionId).toBe("annotation-session-1");
    expect(latestState?.activeWorkspaceId).toBe("annotation-workspace-1");
  });

  it("ignores a stale fix-job refresh after switching sessions", async () => {
    const annotationOneBootstrap = createAnnotationBootstrap();
    const annotationTwoBootstrap: BootstrapState = {
      ...annotationOneBootstrap,
      session: {
        ...annotationOneBootstrap.session!,
        id: "annotation-2",
        workspace_id: "annotation-2",
        workspace_name: "Annotation Workspace Two",
        updated_at: "2026-03-18T19:10:00Z",
      },
      active_session_id: "annotation-2",
      active_workspace_id: "annotation-2",
      sessions: [
        {
          ...annotationOneBootstrap.sessions![0]!,
          id: "annotation-2",
          session_id: "annotation-2",
          workspace_name: "Annotation Workspace Two",
          updated_at: "2026-03-18T19:10:00Z",
        },
      ],
    };
    let resolveAnnotationOneFixJob: ((value: { job: FixJob }) => void) | null = null;
    fetchBootstrapMock.mockResolvedValue(annotationOneBootstrap);
    activateAnnotationSessionMock.mockResolvedValue(annotationTwoBootstrap);
    fetchCurrentFixJobMock.mockImplementation(
      (sessionId: string) =>
        new Promise((resolve) => {
          if (sessionId === "annotation-1") {
            resolveAnnotationOneFixJob = resolve;
            return;
          }

          resolve({
            job: {
              ...createFixJob("job-2"),
              session_id: "annotation-2",
              workspace_dir: "/tmp/annotation-2",
              branch_id: "branch-2",
              branch_name: "Branch 2",
            },
          });
        }),
    );

    await renderHarness();

    await act(async () => {
      void latestState?.refreshFixJob();
      await flushPromises();
    });

    expect(resolveAnnotationOneFixJob).not.toBeNull();

    await act(async () => {
      await latestState?.activateSession("annotation-2");
      await flushPromises();
    });

    await act(async () => {
      await latestState?.refreshFixJob();
      await flushPromises();
    });

    expect(latestState?.activeSessionId).toBe("annotation-2");
    expect(latestState?.fixJob?.session_id).toBe("annotation-2");
    expect(latestState?.fixJob?.id).toBe("job-2");

    await act(async () => {
      resolveAnnotationOneFixJob?.({
        job: {
          ...createFixJob("job-1"),
          session_id: "annotation-1",
        },
      });
      await flushPromises();
    });

    expect(latestState?.activeSessionId).toBe("annotation-2");
    expect(latestState?.fixJob?.session_id).toBe("annotation-2");
    expect(latestState?.fixJob?.id).toBe("job-2");
  });

  it("delegates runner and runtime actions through domain API modules", async () => {
    fetchRunnerStatusMock.mockResolvedValue(
      createRunnerStatusState({ available_runners: ["opencode"] }),
    );

    await renderHarness();

    await act(async () => {
      await latestState?.installRunner("codex");
      await latestState?.launchRunnerAuth("claude");
      await latestState?.openExternalUrl("https://example.com/guide");
      await flushPromises();
    });

    expect(installRunnerMock).toHaveBeenCalledWith("codex");
    expect(launchRunnerAuthMock).toHaveBeenCalledWith("claude");
    expect(openExternalUrlMock).toHaveBeenCalledWith("https://example.com/guide");
  });

  it("delegates annotation, versioning, and annotation export actions through domain API modules", async () => {
    fetchBootstrapMock.mockResolvedValue(createAnnotationBootstrap());

    await renderHarness();

    await act(async () => {
      await latestState?.addAnnotation({ feedback: "note" });
      await latestState?.updateAnnotation("annotation-1", { feedback: "updated" });
      await latestState?.deleteAnnotation("annotation-1");
      await latestState?.checkoutVersion("version-1", "branch-1");
      await latestState?.switchBranch("branch-1");
      await latestState?.renameBranch("branch-1", "Renamed Branch");
      await latestState?.downloadAnnotationPlot("annotation-1");
      await flushPromises();
    });

    expect(createAnnotationMock).toHaveBeenCalledWith({ feedback: "note" });
    expect(updateAnnotationMock).toHaveBeenCalledWith("annotation-1", { feedback: "updated" });
    expect(deleteAnnotationMock).toHaveBeenCalledWith("annotation-1");
    expect(checkoutVersionMock).toHaveBeenCalledWith("version-1", "branch-1");
    expect(checkoutBranchMock).toHaveBeenCalledWith("branch-1");
    expect(renameBranchMock).toHaveBeenCalledWith("branch-1", "Renamed Branch");
    expect(downloadAnnotationArtifactMock).toHaveBeenCalledWith("annotation-1");
  });

  it("delegates preferences, runtime, and fix-job actions through domain API modules", async () => {
    fetchBootstrapMock.mockResolvedValue(createAnnotationBootstrap());

    await renderHarness();

    await act(async () => {
      await latestState?.updateFixPreferences("codex", "gpt-4.1", "fast");
      await latestState?.refreshUpdateStatus();
      await latestState?.setPythonInterpreterPreference("manual", "/custom/python");
      await latestState?.startFixJob("codex", "gpt-4.1", "fast");
      await latestState?.cancelFixJob("job-1");
      await flushPromises();
    });

    expect(updateFixPreferencesMock).toHaveBeenCalledWith({
      fix_runner: "codex",
      fix_model: "gpt-4.1",
      fix_variant: "fast",
    });
    expect(refreshUpdateStatusMock).toHaveBeenCalledWith();
    expect(updatePythonInterpreterMock).toHaveBeenCalledWith("manual", "/custom/python");
    expect(startFixJobMock).toHaveBeenCalledWith("codex", "gpt-4.1", "fast", "annotation-1");
    expect(cancelFixJobMock).toHaveBeenCalledWith("job-1");
  });

  it("delegates plot-mode, plot export, and plot workspace actions through domain API modules", async () => {
    fetchBootstrapMock.mockResolvedValue(createPlotBootstrap("plot-a"));

    await renderHarness();

    await act(async () => {
      await latestState?.fetchPlotModePathSuggestions("plot-a", "sales", "data");
      await latestState?.selectPlotModePaths("plot-a", "data", ["/tmp/data.csv"]);
      await latestState?.sendPlotModeMessage("plot-a", "Plot revenue");
      await latestState?.submitPlotModeTabularHint(
        "plot-a",
        "selector-1",
        [{ sheet_id: "sheet-1", row_start: 1, row_end: 2, col_start: 1, col_end: 2 }],
        "hint",
      );
      await latestState?.updatePlotModeExecutionMode("plot-a", "autonomous");
      await latestState?.answerPlotModeQuestion(
        "plot-a",
        "question-set-1",
        [{ question_id: "question-1", option_ids: ["option-1"] }],
      );
      await latestState?.finalizePlotMode("plot-a", { title: "Revenue" });
      await latestState?.renameWorkspace("plot-a", "Renamed Plot Workspace");
      await latestState?.deleteWorkspace("plot-a");
      await latestState?.downloadPlotModeWorkspace();
      await flushPromises();
    });

    expect(fetchPlotModePathSuggestionsMock).toHaveBeenCalledWith("plot-a", "sales", "data");
    expect(selectPlotModePathsMock).toHaveBeenCalledWith("plot-a", "data", ["/tmp/data.csv"]);
    expect(sendPlotModeMessageMock).toHaveBeenCalledWith({
      message: "Plot revenue",
      workspace_id: "plot-a",
    });
    expect(submitPlotModeTabularHintMock).toHaveBeenCalledWith({
      workspace_id: "plot-a",
      selector_id: "selector-1",
      regions: [{ sheet_id: "sheet-1", row_start: 1, row_end: 2, col_start: 1, col_end: 2 }],
      note: "hint",
    });
    expect(updatePlotModeSettingsMock).toHaveBeenCalledWith("plot-a", "autonomous");
    expect(answerPlotModeQuestionMock).toHaveBeenCalledWith({
      workspace_id: "plot-a",
      question_set_id: "question-set-1",
      answers: [{ question_id: "question-1", option_ids: ["option-1"], text: null }],
    });
    expect(finalizePlotModeMock).toHaveBeenCalledWith("plot-a", { title: "Revenue" });
    expect(updatePlotWorkspaceMock).toHaveBeenCalledWith("plot-a", "Renamed Plot Workspace");
    expect(deletePlotWorkspaceMock).toHaveBeenCalledWith("plot-a");
    expect(downloadPlotModeArtifactMock).toHaveBeenCalledWith("plot-a");
  });

  it("delegates session creation and annotation workspace actions through domain API modules", async () => {
    fetchBootstrapMock.mockResolvedValue(createAnnotationBootstrap());

    await renderHarness();

    await act(async () => {
      await latestState?.createNewSession();
      await latestState?.activateSession("annotation-1");
      await latestState?.renameWorkspace("annotation-1", "Renamed Annotation Workspace");
      await latestState?.deleteWorkspace("annotation-1");
      await flushPromises();
    });

    expect(createSessionMock).toHaveBeenCalledWith();
    expect(activateAnnotationSessionMock).toHaveBeenCalledWith("annotation-1");
    expect(updateAnnotationWorkspaceMock).toHaveBeenCalledWith(
      "annotation-1",
      "Renamed Annotation Workspace",
    );
    expect(deleteAnnotationWorkspaceMock).toHaveBeenCalledWith("annotation-1");
  });

  it("ignores a late plot activation response after a newer workspace switch", async () => {
    const activationResolvers = new Map<string, (payload: BootstrapState) => void>();
    activatePlotWorkspaceMock.mockImplementation(
      (workspaceId: string) =>
        new Promise((resolve) => {
          activationResolvers.set(workspaceId, resolve);
        }),
    );

    await renderHarness();

    expect(latestState?.activeWorkspaceId).toBe("plot-initial");

    await act(async () => {
      void latestState?.activateSession("plot-a");
      void latestState?.activateSession("plot-b");
      await flushPromises();
    });

    await act(async () => {
      activationResolvers.get("plot-b")?.(createPlotBootstrap("plot-b"));
      await flushPromises();
    });

    expect(latestState?.activeWorkspaceId).toBe("plot-b");

    await act(async () => {
      activationResolvers.get("plot-a")?.(createPlotBootstrap("plot-a"));
      await flushPromises();
    });

    expect(latestState?.activeWorkspaceId).toBe("plot-b");
    expect(latestState?.plotMode?.id).toBe("plot-b");
  });

  it("answers plot questions using the explicitly targeted workspace id", async () => {
    const answerRequestBodies: AnswerPlotModeQuestionRequestBody[] = [];
    answerPlotModeQuestionMock.mockImplementation(async (body) => {
      answerRequestBodies.push(body as AnswerPlotModeQuestionRequestBody);
      return {
        status: "ok",
        plot_mode: createPlotModeState("plot-b", "Workspace B"),
      };
    });
    fetchBootstrapMock.mockResolvedValue(createPlotBootstrap("plot-a"));

    await renderHarness();

    await act(async () => {
      latestState?.handleWsEvent({
        type: "plot_mode_updated",
        plot_mode: createPlotModeState("plot-b", "Workspace B"),
      });
      await latestState?.answerPlotModeQuestion(
        "plot-b",
        "question-set-b",
        [{ question_id: "question-b", option_ids: ["option-b"] }],
      );
      await flushPromises();
    });

    expect(answerRequestBodies[0]?.workspace_id).toBe("plot-b");
    expect(answerRequestBodies[0]?.question_set_id).toBe("question-set-b");
  });

  it("ignores a late bootstrap response after a newer workspace switch", async () => {
    let refreshResolver: ((payload: BootstrapState) => void) | null = null;
    fetchBootstrapMock
      .mockResolvedValueOnce(createAnnotationBootstrap())
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            refreshResolver = resolve;
          }),
      );

    const activationResolvers = new Map<string, (payload: BootstrapState) => void>();
    activatePlotWorkspaceMock.mockImplementation(
      (workspaceId: string) =>
        new Promise((resolve) => {
          activationResolvers.set(workspaceId, resolve);
        }),
    );

    await renderHarness();

    expect(latestState?.mode).toBe("annotation");

    await act(async () => {
      latestState?.handleWsEvent({ type: "plot_updated", session_id: "annotation-1" });
      void latestState?.activateSession("plot-b");
      await flushPromises();
    });

    await act(async () => {
      activationResolvers.get("plot-b")?.(createPlotBootstrap("plot-b"));
      await flushPromises();
    });

    expect(latestState?.activeWorkspaceId).toBe("plot-b");

    await act(async () => {
      refreshResolver?.(createAnnotationBootstrap());
      await flushPromises();
    });

    expect(latestState?.activeWorkspaceId).toBe("plot-b");
    expect(latestState?.plotMode?.id).toBe("plot-b");
  });

  it("ignores a late bootstrap error after a newer workspace switch", async () => {
    let refreshRejector: ((error: Error) => void) | null = null;
    fetchBootstrapMock
      .mockResolvedValueOnce(createAnnotationBootstrap())
      .mockImplementationOnce(
        () =>
          new Promise((_, reject) => {
            refreshRejector = reject as (error: Error) => void;
          }),
      );

    const activationResolvers = new Map<string, (payload: BootstrapState) => void>();
    activatePlotWorkspaceMock.mockImplementation(
      (workspaceId: string) =>
        new Promise((resolve) => {
          activationResolvers.set(workspaceId, resolve);
        }),
    );

    await renderHarness();

    await act(async () => {
      latestState?.handleWsEvent({ type: "plot_updated", session_id: "annotation-1" });
      void latestState?.activateSession("plot-b");
      await flushPromises();
    });

    await act(async () => {
      activationResolvers.get("plot-b")?.(createPlotBootstrap("plot-b"));
      await flushPromises();
    });

    expect(latestState?.error).toBeNull();

    await act(async () => {
      refreshRejector?.(new Error("500: stale bootstrap"));
      await flushPromises();
    });

    expect(latestState?.activeWorkspaceId).toBe("plot-b");
    expect(latestState?.error).toBeNull();
  });

  it("keeps the current plot workspace when an older websocket workspace update arrives later", async () => {
    const activationResolvers = new Map<string, (payload: BootstrapState) => void>();
    fetchBootstrapMock.mockResolvedValue(createPlotBootstrap("plot-a"));
    activatePlotWorkspaceMock.mockImplementation(
      (workspaceId: string) =>
        new Promise((resolve) => {
          activationResolvers.set(workspaceId, resolve);
        }),
    );

    await renderHarness();

    expect(latestState?.activeWorkspaceId).toBe("plot-a");

    await act(async () => {
      void latestState?.activateSession("plot-b");
      await flushPromises();
    });

    await act(async () => {
      activationResolvers.get("plot-b")?.(createPlotBootstrap("plot-b"));
      await flushPromises();
    });

    expect(latestState?.activeWorkspaceId).toBe("plot-b");
    expect(latestState?.plotMode?.workspace_name).toBe("Workspace plot-b");

    await act(async () => {
      latestState?.handleWsEvent({
        type: "plot_mode_updated",
        plot_mode: {
          ...createPlotModeState("plot-a", "Workspace A refreshed"),
          updated_at: "2026-03-18T20:30:00Z",
        },
      });
      await flushPromises();
    });

    expect(latestState?.activeWorkspaceId).toBe("plot-b");
    expect(latestState?.plotMode?.id).toBe("plot-b");
    expect(latestState?.plotMode?.workspace_name).toBe("Workspace plot-b");
    expect(latestState?.sessions[0]?.id).toBe("plot-a");
    expect(latestState?.sessions[0]?.workspace_name).toBe("Workspace A refreshed");
  });

  it("keeps the current plot workspace when an older websocket message update arrives later", async () => {
    const activationResolvers = new Map<string, (payload: BootstrapState) => void>();
    fetchBootstrapMock.mockResolvedValue(createPlotBootstrap("plot-a"));
    activatePlotWorkspaceMock.mockImplementation(
      (workspaceId: string) =>
        new Promise((resolve) => {
          activationResolvers.set(workspaceId, resolve);
        }),
    );

    await renderHarness();

    await act(async () => {
      void latestState?.activateSession("plot-b");
      await flushPromises();
    });

    await act(async () => {
      activationResolvers.get("plot-b")?.(createPlotBootstrap("plot-b"));
      await flushPromises();
    });

    await act(async () => {
      latestState?.handleWsEvent({
        type: "plot_mode_message_updated",
        plot_mode_id: "plot-a",
        updated_at: "2026-03-18T20:45:00Z",
        message: {
          id: "message-a-1",
          role: "assistant",
          content: "Late update",
          metadata: null,
          created_at: "2026-03-18T20:45:00Z",
        },
      });
      await flushPromises();
    });

    expect(latestState?.activeWorkspaceId).toBe("plot-b");
    expect(latestState?.plotMode?.id).toBe("plot-b");
    expect(latestState?.plotMode?.messages).toHaveLength(0);
    expect(latestState?.sessions[0]?.id).toBe("plot-a");
    expect(latestState?.sessions[0]?.updated_at).toBe("2026-03-18T20:45:00Z");
  });

  it("does not let a stale plot websocket update reopen plot mode after newer annotation navigation", async () => {
    const activationResolvers = new Map<string, (payload: BootstrapState) => void>();
    activatePlotWorkspaceMock.mockImplementation(
      (workspaceId: string) =>
        new Promise((resolve) => {
          activationResolvers.set(workspaceId, resolve);
        }),
    );

    fetchBootstrapMock.mockResolvedValueOnce(createPlotBootstrap("plot-a"));

    await renderHarness();

    await act(async () => {
      void latestState?.activateSession("annotation-1");
      await flushPromises();
    });

    expect(latestState?.mode).toBe("annotation");
    expect(latestState?.activeWorkspaceId).toBe("annotation-1");

    const plotVersionBeforeStaleEvent = latestState?.plotVersion ?? 0;

    await act(async () => {
      latestState?.handleWsEvent({
        type: "plot_mode_updated",
        plot_mode: {
          ...createPlotModeState("plot-a", "Workspace A stale refresh"),
          updated_at: "2026-03-18T21:00:00Z",
          current_plot: "/tmp/plot-a-new.png",
        },
      });
      await flushPromises();
    });

    expect(latestState?.mode).toBe("annotation");
    expect(latestState?.activeWorkspaceId).toBe("annotation-1");
    expect(latestState?.session?.id).toBe("annotation-1");
    expect(latestState?.plotMode).toBeNull();
    expect(latestState?.plotVersion).toBe(plotVersionBeforeStaleEvent);
    expect(latestState?.sessions[0]?.id).toBe("plot-a");
    expect(latestState?.sessions[0]?.workspace_name).toBe("Workspace A stale refresh");
  });

  it("subscribes raw websocket events in order before reconciliation", () => {
    const listeners = new Set<(event: MessageEvent<string>) => void>();
    const receivedEvents: Array<{ type: string }> = [];
    const socket = {
      addEventListener: vi.fn((type: string, listener: (event: MessageEvent<string>) => void) => {
        if (type === "message") {
          listeners.add(listener);
        }
      }),
      removeEventListener: vi.fn(
        (type: string, listener: (event: MessageEvent<string>) => void) => {
          if (type === "message") {
            listeners.delete(listener);
          }
        },
      ),
    } as Pick<WebSocket, "addEventListener" | "removeEventListener">;

    const unsubscribe = subscribeToRawWsEvents(socket, (event) => {
      receivedEvents.push(event as { type: string });
    });

    listeners.forEach((listener) => {
      listener(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "plot_mode_updated",
            plot_mode: createPlotModeState("plot-a", "Workspace A"),
          }),
        }),
      );
      listener(new MessageEvent("message", { data: "not json" }));
      listener(
        new MessageEvent("message", {
          data: JSON.stringify({ type: "plot_updated", session_id: "annotation-1" }),
        }),
      );
    });

    expect(receivedEvents.map((event) => event.type)).toEqual([
      "plot_mode_updated",
      "plot_updated",
    ]);

    unsubscribe();

    expect(socket.addEventListener).toHaveBeenCalledWith("message", expect.any(Function));
    expect(socket.removeEventListener).toHaveBeenCalledWith("message", expect.any(Function));
  });
});
