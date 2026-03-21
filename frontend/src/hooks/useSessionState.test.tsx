// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BootstrapState,
  PlotModeState,
  PythonInterpreterState,
  PlotSession,
  RunnerStatusState,
} from "../types";

vi.mock("../api/client", () => ({
  API_BASE: "",
  fetchJSON: vi.fn(),
}));

import { fetchJSON } from "../api/client";
import { useSessionState } from "./useSessionState";

const fetchJSONMock = vi.mocked(fetchJSON);

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
    messages: [],
    data_profiles: [],
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

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}

describe("useSessionState", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let latestState: ReturnType<typeof useSessionState> | null;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    latestState = null;
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("fetch", vi.fn());
    vi.stubGlobal("setInterval", vi.fn(() => 1));
    vi.stubGlobal("clearInterval", vi.fn());
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

    fetchJSONMock.mockImplementation(async (url) => {
      if (url === "/api/bootstrap") {
        return createPlotBootstrap("plot-initial");
      }
      if (url === "/api/runners/status") {
        return runnerStatus;
      }
      if (url === "/api/preferences") {
        return {};
      }
      if (url === "/api/python/interpreter") {
        return pythonInterpreterState;
      }
      throw new Error(`Unhandled fetchJSON call: ${url}`);
    });

    function Harness() {
      latestState = useSessionState();
      return null;
    }

    await act(async () => {
      root.render(<Harness />);
      await flushPromises();
    });

    expect(fetchJSONMock).toHaveBeenCalledWith("/api/runners/status");
    expect(latestState?.runnerStatus).toEqual(runnerStatus);
    expect(latestState?.availableRunners).toEqual([]);
    expect(latestState?.runnerStatusLoading).toBe(false);
    expect(latestState?.runnerStatusError).toBeNull();
    expect(latestState?.backendFatalError).toBe(
      "At least one backend CLI must exist: codex, claude code, opencode.",
    );
  });

  it("exposes runner install, auth launch, and guide actions", async () => {
    const runnerStatus = createRunnerStatusState({ available_runners: ["opencode"] });

    fetchJSONMock.mockImplementation(async (url, init) => {
      if (url === "/api/bootstrap") {
        return createPlotBootstrap("plot-initial");
      }
      if (url === "/api/runners/status") {
        return runnerStatus;
      }
      if (url === "/api/preferences") {
        return {};
      }
      if (url === "/api/python/interpreter") {
        return pythonInterpreterState;
      }
      if (url === "/api/runners/install") {
        expect(init).toMatchObject({ method: "POST" });
        expect(init?.body).toBe(JSON.stringify({ runner: "codex" }));
        return { job: { id: "job-1" } };
      }
      if (url === "/api/runners/auth/launch") {
        expect(init).toMatchObject({ method: "POST" });
        expect(init?.body).toBe(JSON.stringify({ runner: "claude" }));
        return { status: "ok" };
      }
      if (url === "/api/open-external-url") {
        expect(init).toMatchObject({ method: "POST" });
        expect(init?.body).toBe(JSON.stringify({ url: "https://example.com/guide" }));
        return { status: "ok" };
      }
      throw new Error(`Unhandled fetchJSON call: ${url}`);
    });

    function Harness() {
      latestState = useSessionState();
      return null;
    }

    await act(async () => {
      root.render(<Harness />);
      await flushPromises();
    });

    await act(async () => {
      await latestState?.installRunner?.("codex");
      await latestState?.launchRunnerAuth?.("claude");
      await latestState?.openExternalUrl?.("https://example.com/guide");
      await flushPromises();
    });

    expect(fetchJSONMock).toHaveBeenCalledWith(
      "/api/runners/install",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchJSONMock).toHaveBeenCalledWith(
      "/api/runners/auth/launch",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchJSONMock).toHaveBeenCalledWith(
      "/api/open-external-url",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("ignores a late plot activation response after a newer workspace switch", async () => {
    const activationResolvers = new Map<string, (payload: BootstrapState) => void>();

    fetchJSONMock.mockImplementation(async (url, init) => {
      if (url === "/api/bootstrap") {
        return createPlotBootstrap("plot-initial");
      }
      if (url === "/api/runners/status") {
        return createRunnerStatusState();
      }
      if (url === "/api/preferences") {
        return {};
      }
      if (url === "/api/python/interpreter") {
        return pythonInterpreterState;
      }
      if (url === "/api/plot-mode/activate") {
        const workspaceId = JSON.parse(String(init?.body || "{}")) as { id: string };
        return await new Promise<BootstrapState>((resolve) => {
          activationResolvers.set(workspaceId.id, resolve);
        });
      }
      throw new Error(`Unhandled fetchJSON call: ${url}`);
    });

    function Harness() {
      latestState = useSessionState();
      return null;
    }

    await act(async () => {
      root.render(<Harness />);
      await flushPromises();
    });

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

    fetchJSONMock.mockImplementation(async (url, init) => {
      if (url === "/api/bootstrap") {
        return createPlotBootstrap("plot-a");
      }
      if (url === "/api/runners/status") {
        return createRunnerStatusState();
      }
      if (url === "/api/preferences") {
        return {};
      }
      if (url === "/api/python/interpreter") {
        return pythonInterpreterState;
      }
      if (url === "/api/plot-mode/answer") {
        answerRequestBodies.push(JSON.parse(
          String(init?.body || "{}"),
        ) as AnswerPlotModeQuestionRequestBody);
        return {
          status: "ok" as const,
          plot_mode: createPlotModeState("plot-b", "Workspace B"),
        };
      }
      throw new Error(`Unhandled fetchJSON call: ${url}`);
    });

    function Harness() {
      latestState = useSessionState();
      return null;
    }

    await act(async () => {
      root.render(<Harness />);
      await flushPromises();
    });

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

    const answerRequestBody = answerRequestBodies[0];
    if (!answerRequestBody) {
      throw new Error("Expected answer request body to be captured");
    }
    expect(answerRequestBody.workspace_id).toBe("plot-b");
    expect(answerRequestBody.question_set_id).toBe("question-set-b");
  });

  it("ignores a late bootstrap response after a newer workspace switch", async () => {
    let resolveBootstrapRefresh: ((payload: BootstrapState) => void) | null = null;
    const activationResolvers = new Map<string, (payload: BootstrapState) => void>();

    fetchJSONMock.mockImplementation(async (url, init) => {
      if (url === "/api/bootstrap") {
        if (!resolveBootstrapRefresh) {
          return createAnnotationBootstrap();
        }
        return await new Promise<BootstrapState>((resolve) => {
          resolveBootstrapRefresh = resolve;
        });
      }
      if (url === "/api/runners/status") {
        return createRunnerStatusState();
      }
      if (url === "/api/preferences") {
        return {};
      }
      if (url === "/api/python/interpreter") {
        return pythonInterpreterState;
      }
      if (url === "/api/plot-mode/activate") {
        const workspaceId = JSON.parse(String(init?.body || "{}")) as { id: string };
        return await new Promise<BootstrapState>((resolve) => {
          activationResolvers.set(workspaceId.id, resolve);
        });
      }
      throw new Error(`Unhandled fetchJSON call: ${url}`);
    });

    function Harness() {
      latestState = useSessionState();
      return null;
    }

    await act(async () => {
      root.render(<Harness />);
      await flushPromises();
    });

    expect(latestState?.mode).toBe("annotation");

    await act(async () => {
      resolveBootstrapRefresh = (() => {}) as (payload: BootstrapState) => void;
      latestState?.handleWsEvent({
        type: "plot_updated",
        session_id: "annotation-1",
      });
      void latestState?.activateSession("plot-b");
      await flushPromises();
    });

    await act(async () => {
      activationResolvers.get("plot-b")?.(createPlotBootstrap("plot-b"));
      await flushPromises();
    });

    expect(latestState?.activeWorkspaceId).toBe("plot-b");

    await act(async () => {
      resolveBootstrapRefresh?.(createAnnotationBootstrap());
      await flushPromises();
    });

    expect(latestState?.activeWorkspaceId).toBe("plot-b");
    expect(latestState?.plotMode?.id).toBe("plot-b");
  });

  it("ignores a late bootstrap error after a newer workspace switch", async () => {
    let rejectBootstrapRefresh: ((error: Error) => void) | null = null;
    const activationResolvers = new Map<string, (payload: BootstrapState) => void>();

    fetchJSONMock.mockImplementation(async (url, init) => {
      if (url === "/api/bootstrap") {
        if (!rejectBootstrapRefresh) {
          return createAnnotationBootstrap();
        }
        return await new Promise<BootstrapState>((_, reject) => {
          rejectBootstrapRefresh = reject as (error: Error) => void;
        });
      }
      if (url === "/api/runners/status") {
        return createRunnerStatusState();
      }
      if (url === "/api/preferences") {
        return {};
      }
      if (url === "/api/python/interpreter") {
        return pythonInterpreterState;
      }
      if (url === "/api/plot-mode/activate") {
        const workspaceId = JSON.parse(String(init?.body || "{}")) as { id: string };
        return await new Promise<BootstrapState>((resolve) => {
          activationResolvers.set(workspaceId.id, resolve);
        });
      }
      throw new Error(`Unhandled fetchJSON call: ${url}`);
    });

    function Harness() {
      latestState = useSessionState();
      return null;
    }

    await act(async () => {
      root.render(<Harness />);
      await flushPromises();
    });

    await act(async () => {
      rejectBootstrapRefresh = (() => {}) as (error: Error) => void;
      latestState?.handleWsEvent({
        type: "plot_updated",
        session_id: "annotation-1",
      });
      void latestState?.activateSession("plot-b");
      await flushPromises();
    });

    await act(async () => {
      activationResolvers.get("plot-b")?.(createPlotBootstrap("plot-b"));
      await flushPromises();
    });

    expect(latestState?.error).toBeNull();

    await act(async () => {
      rejectBootstrapRefresh?.(new Error("500: stale bootstrap"));
      await flushPromises();
    });

    expect(latestState?.activeWorkspaceId).toBe("plot-b");
    expect(latestState?.error).toBeNull();
  });
});
