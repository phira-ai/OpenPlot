// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const useSessionStateMock = vi.fn();
const useWebSocketMock = vi.fn();
const useWorkspaceActionsMock = vi.fn();

vi.mock("./hooks/useSessionState", () => ({
  useSessionState: () => useSessionStateMock(),
}));

vi.mock("./hooks/useWebSocket", () => ({
  useWebSocket: () => useWebSocketMock(),
}));

vi.mock("./hooks/useWorkspaceActions", () => ({
  useWorkspaceActions: () => useWorkspaceActionsMock(),
}));

vi.mock("./components/Toolbar", () => ({
  default: ({ onOpenRunnerManager }: { onOpenRunnerManager?: () => void }) => (
    <button type="button" onClick={onOpenRunnerManager}>
      Open runners
    </button>
  ),
}));

vi.mock("./components/PlotViewer", () => ({
  default: () => <div>PlotViewer</div>,
}));

vi.mock("./components/PlotModePreview", () => ({
  default: () => <div>PlotModePreview</div>,
}));

vi.mock("./components/PlotModeSidebar", () => ({
  default: () => <div>PlotModeSidebar</div>,
}));

vi.mock("./components/SessionSidebar", () => ({
  default: () => <div>SessionSidebar</div>,
}));

vi.mock("./components/FeedbackSidebar", () => ({
  default: () => <div>FeedbackSidebar</div>,
}));

vi.mock("./components/FixStepLiveModal", () => ({
  default: () => <div>FixStepLiveModal</div>,
}));

vi.mock("./components/NotificationBubbleStack", () => ({
  default: () => <div>NotificationBubbleStack</div>,
}));

vi.mock("./components/WalkthroughPromptModal", () => ({
  default: () => <div>WalkthroughPromptModal</div>,
}));

vi.mock("./components/WalkthroughTour", () => ({
  default: () => <div>WalkthroughTour</div>,
}));

vi.mock("./components/PlotModeWalkthroughTour", () => ({
  default: () => <div>PlotModeWalkthroughTour</div>,
}));

import App from "./App";

function createRunnerStatus({
  status = "available_to_install",
  primaryAction = "install",
  primaryActionLabel = "Install",
  installed = false,
  executablePath = null,
  authCommand = null,
  authInstructions = null,
}: {
  status?: "available_to_install" | "installed_needs_auth";
  primaryAction?: "install" | "authenticate";
  primaryActionLabel?: string;
  installed?: boolean;
  executablePath?: string | null;
  authCommand?: string | null;
  authInstructions?: string | null;
} = {}) {
  return {
    available_runners: [],
    supported_runners: ["opencode", "codex", "claude"] as const,
    claude_code_available: false,
    host_platform: "darwin",
    host_arch: "arm64",
    active_install_job_id: null,
    runners: [
      {
        runner: "codex" as const,
        status,
        status_label: status === "installed_needs_auth" ? "Sign-in required" : "Available to install",
        primary_action: primaryAction,
        primary_action_label: primaryActionLabel,
        guide_url: "https://developers.openai.com/codex/auth",
        installed,
        executable_path: executablePath,
        install_job: null,
        auth_command: authCommand,
        auth_instructions: authInstructions,
      },
    ],
  };
}

function createBaseState(overrides: Record<string, unknown> = {}) {
  const session = {
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
    root_version_id: "root-version",
    active_branch_id: "",
    checked_out_version_id: "",
    runner_session_ids: {},
    artifacts_root: "/tmp/artifacts",
    revision_history: [],
    created_at: "2026-03-18T18:00:00Z",
    updated_at: "2026-03-18T19:00:00Z",
  };

  return {
    mode: "annotation",
    session,
    sessions: [],
    activeWorkspaceId: session.workspace_id,
    plotMode: null,
    loading: false,
    error: null,
    selectedRunner: "opencode",
    setSelectedRunner: vi.fn(),
    availableRunners: ["opencode"],
    runnerStatus: null,
    runnerStatusLoading: false,
    runnerStatusError: null,
    backendFatalError: null,
    opencodeModels: [],
    defaultOpencodeModel: "",
    defaultOpencodeVariant: "",
    opencodeModelsLoading: false,
    opencodeModelsError: null,
    pythonInterpreter: null,
    pythonInterpreterLoading: false,
    pythonInterpreterError: null,
    fixJob: null,
    fixStepLogsByKey: {},
    plotVersion: 0,
    refresh: vi.fn(),
    refreshRunnerAvailability: vi.fn(async () => {}),
    installRunner: vi.fn(async () => {}),
    launchRunnerAuth: vi.fn(async () => {}),
    openExternalUrl: vi.fn(async () => {}),
    refreshRunnerModels: vi.fn(async () => {}),
    refreshFixJob: vi.fn(async () => {}),
    refreshPythonInterpreter: vi.fn(async () => {}),
    addAnnotation: vi.fn(async () => {}),
    deleteAnnotation: vi.fn(async () => {}),
    updateAnnotation: vi.fn(async () => {}),
    checkoutVersion: vi.fn(async () => {}),
    switchBranch: vi.fn(async () => {}),
    renameBranch: vi.fn(async () => {}),
    downloadAnnotationPlot: vi.fn(async () => ({ blob: new Blob(), fileName: "plot.zip" })),
    downloadPlotModeWorkspace: vi.fn(async () => ({ blob: new Blob(), fileName: "workspace.zip" })),
    startFixJob: vi.fn(async () => {}),
    cancelFixJob: vi.fn(async () => {}),
    updateFixPreferences: vi.fn(async () => {}),
    setPythonInterpreterPreference: vi.fn(async () => {}),
    fetchPlotModePathSuggestions: vi.fn(async () => ({ suggestions: [], query: "", selection_type: "data", base_dir: "/tmp" })),
    selectPlotModePaths: vi.fn(async () => {}),
    submitPlotModeTabularHint: vi.fn(async () => {}),
    sendPlotModeMessage: vi.fn(async () => {}),
    updatePlotModeExecutionMode: vi.fn(async () => {}),
    answerPlotModeQuestion: vi.fn(async () => {}),
    finalizePlotMode: vi.fn(async () => {}),
    createNewSession: vi.fn(async () => {}),
    activateSession: vi.fn(async () => {}),
    renameWorkspace: vi.fn(async () => {}),
    deleteWorkspace: vi.fn(async () => {}),
    handleWsEvent: vi.fn(),
    ...overrides,
  };
}

describe("App runner onboarding", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    );

    useWebSocketMock.mockReturnValue({
      connected: true,
      wsUrl: "ws://127.0.0.1:8000/ws",
      reconnectAttempts: 0,
      lastConnectedAt: null,
      lastDisconnectedAt: null,
    });

    useWorkspaceActionsMock.mockReturnValue({
      sessionActionPending: false,
      handleCreateSession: vi.fn(async () => {}),
      handleActivateSession: vi.fn(async () => {}),
      handleRenameWorkspace: vi.fn(async () => {}),
      handleDeleteWorkspace: vi.fn(async () => {}),
    });
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("shows the blocking runner manager when no runners are available", async () => {
    useSessionStateMock.mockReturnValue(
      createBaseState({
        availableRunners: [],
        runnerStatus: createRunnerStatus(),
        backendFatalError: "At least one backend CLI must exist: codex, claude code, opencode.",
      }),
    );

    await act(async () => {
      root.render(<App />);
    });

    expect(document.body.textContent).toContain("No runners available");
    expect(document.body.textContent).not.toContain("No Supported Backend Found");
  });

  it("blocks the workspace UI while runner status is still loading", async () => {
    useSessionStateMock.mockReturnValue(
      createBaseState({
        runnerStatus: null,
        runnerStatusLoading: true,
      }),
    );

    await act(async () => {
      root.render(<App />);
    });

    expect(document.body.textContent).toContain("Checking runners");
    expect(document.body.textContent).not.toContain("Open runners");
  });

});
