// @vitest-environment jsdom

import { act, type ComponentProps } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../NotificationBubbleStack", () => ({
  default: ({ notifications }: { notifications: Array<{ message: string }> }) => (
    <div>Notifications:{notifications.map((entry) => entry.message).join(",")}</div>
  ),
}));

vi.mock("../Toolbar", () => ({
  default: ({ mode }: { mode: string }) => <div>Toolbar:{mode}</div>,
}));

vi.mock("../SessionSidebar", () => ({
  default: ({ open }: { open: boolean }) => <div>SessionSidebar:{open ? "open" : "closed"}</div>,
}));

vi.mock("../PlotViewer", () => ({
  default: ({ workspaceId }: { workspaceId: string }) => <div>PlotViewer:{workspaceId}</div>,
}));

vi.mock("../FeedbackSidebar", () => ({
  default: () => <div>FeedbackSidebar</div>,
}));

vi.mock("../WalkthroughPromptModal", () => ({
  default: ({ mode, open }: { mode: string; open: boolean }) => (
    <div>{`WalkthroughPromptModal:${mode}:${open ? "open" : "closed"}`}</div>
  ),
}));

vi.mock("../WalkthroughTour", () => ({
  default: () => <div>WalkthroughTour</div>,
}));

vi.mock("../FixStepLiveModal", () => ({
  default: ({ open }: { open: boolean }) => <div>{`FixStepLiveModal:${open ? "open" : "closed"}`}</div>,
}));

vi.mock("@/components/ui/tooltip", () => ({
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

import AnnotationWorkspaceScreen from "./AnnotationWorkspaceScreen";

function createProps(overrides: Record<string, unknown> = {}): ComponentProps<typeof AnnotationWorkspaceScreen> {
  return {
    notifications: [{ id: "n1", message: "Problem", tone: "error" as const }],
    onDismissNotification: vi.fn(),
    toolbarProps: { mode: "annotation" as const } as ComponentProps<typeof AnnotationWorkspaceScreen>["toolbarProps"],
    showWorkspaceSidebar: true,
    onWorkspaceHotzoneEnter: vi.fn(),
    onWorkspaceHotzoneLeave: vi.fn(),
    sessionSidebarProps: {} as ComponentProps<typeof AnnotationWorkspaceScreen>["sessionSidebarProps"],
    plotViewerKey: "plot-1",
    plotViewerProps: { workspaceId: "annotation-1" } as ComponentProps<typeof AnnotationWorkspaceScreen>["plotViewerProps"],
    feedbackSidebarProps: {} as ComponentProps<typeof AnnotationWorkspaceScreen>["feedbackSidebarProps"],
    footerSourcePath: "/tmp/source.py",
    footerPlotType: "SVG",
    footerBranchName: "main",
    footerRevisionCount: 3,
    footerCheckedOutVersionId: "version-2",
    onRestartWalkthrough: vi.fn(),
    walkthroughPromptOpen: true,
    onStartWalkthrough: vi.fn(),
    onDismissWalkthroughPrompt: vi.fn(),
    onDontShowWalkthroughAgain: vi.fn(),
    showWalkthroughTour: true,
    onCloseWalkthroughTour: vi.fn(),
    onWalkthroughStepTargetChange: vi.fn(),
    fixStepLiveModalProps: { open: true } as ComponentProps<typeof AnnotationWorkspaceScreen>["fixStepLiveModalProps"],
    runnerAuthDialog: <div>RunnerAuthDialog</div>,
    ...overrides,
  };
}

describe("AnnotationWorkspaceScreen", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("wires session sidebar visibility, footer metadata, walkthrough, fix modal, and runner auth", async () => {
    await act(async () => {
      root.render(<AnnotationWorkspaceScreen {...createProps()} />);
    });

    expect(document.body.textContent).toContain("SessionSidebar:open");
    expect(document.body.textContent).toContain("PlotViewer:annotation-1");
    expect(document.body.textContent).toContain("FeedbackSidebar");
    expect(document.body.textContent).toContain("/tmp/source.py");
    expect(document.body.textContent).toContain("SVG");
    expect(document.body.textContent).toContain("main");
    expect(document.body.textContent).toContain("Rev 3 · version-2");
    expect(document.body.textContent).toContain("WalkthroughPromptModal:annotation:open");
    expect(document.body.textContent).toContain("WalkthroughTour");
    expect(document.body.textContent).toContain("FixStepLiveModal:open");
    expect(document.body.textContent).toContain("RunnerAuthDialog");
  });

  it("omits the fix modal when no live output props are provided", async () => {
    await act(async () => {
      root.render(
        <AnnotationWorkspaceScreen
          {...createProps({
            showWorkspaceSidebar: false,
            walkthroughPromptOpen: false,
            showWalkthroughTour: false,
            fixStepLiveModalProps: null,
          })}
        />,
      );
    });

    expect(document.body.textContent).toContain("SessionSidebar:closed");
    expect(document.body.textContent).not.toContain("FixStepLiveModal");
  });
});
