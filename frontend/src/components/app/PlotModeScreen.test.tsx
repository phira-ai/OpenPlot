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

vi.mock("../PlotModePreview", () => ({
  default: ({ workspaceId }: { workspaceId: string }) => <div>PlotModePreview:{workspaceId}</div>,
}));

vi.mock("../PlotModeSidebar", () => ({
  default: ({ desktopViewport }: { desktopViewport: boolean }) => (
    <div>PlotModeSidebar:{desktopViewport ? "desktop" : "mobile"}</div>
  ),
}));

vi.mock("../PlotModeWalkthroughTour", () => ({
  default: () => <div>PlotModeWalkthroughTour</div>,
}));

vi.mock("../WalkthroughPromptModal", () => ({
  default: ({ mode, open }: { mode: string; open: boolean }) => (
    <div>{`WalkthroughPromptModal:${mode}:${open ? "open" : "closed"}`}</div>
  ),
}));

vi.mock("@/components/ui/resizable", () => ({
  ResizablePanelGroup: ({ children }: { children: React.ReactNode }) => <div>ResizablePanelGroup{children}</div>,
  ResizablePanel: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ResizableHandle: () => <div>ResizableHandle</div>,
}));

import PlotModeScreen from "./PlotModeScreen";

function createProps(overrides: Record<string, unknown> = {}): ComponentProps<typeof PlotModeScreen> {
  return {
    notifications: [{ id: "n1", message: "Problem", tone: "error" as const }],
    onDismissNotification: vi.fn(),
    toolbarProps: { mode: "plot" as const } as ComponentProps<typeof PlotModeScreen>["toolbarProps"],
    allowWorkspaceSidebar: true,
    showWorkspaceSidebar: true,
    onWorkspaceHotzoneEnter: vi.fn(),
    onWorkspaceHotzoneLeave: vi.fn(),
    sessionSidebarProps: {} as ComponentProps<typeof PlotModeScreen>["sessionSidebarProps"],
    desktopViewport: true,
    plotModePreviewProps: { workspaceId: "plot-1" } as ComponentProps<typeof PlotModeScreen>["plotModePreviewProps"],
    plotModeSidebarProps: { state: null } as ComponentProps<typeof PlotModeScreen>["plotModeSidebarProps"],
    selectedFileCount: 2,
    onRestartWalkthrough: vi.fn(),
    walkthroughPromptOpen: true,
    onStartWalkthrough: vi.fn(),
    onDismissWalkthroughPrompt: vi.fn(),
    onDontShowWalkthroughAgain: vi.fn(),
    showPlotModeWalkthroughTour: true,
    onClosePlotModeWalkthroughTour: vi.fn(),
    onPlotModeWalkthroughStepTargetChange: vi.fn(),
    runnerAuthDialog: <div>RunnerAuthDialog</div>,
    ...overrides,
  };
}

describe("PlotModeScreen", () => {
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

  it("wires sidebar visibility, desktop layout, footer, walkthrough, and runner auth content", async () => {
    await act(async () => {
      root.render(<PlotModeScreen {...createProps()} />);
    });

    expect(document.body.textContent).toContain("SessionSidebar:open");
    expect(document.body.textContent).toContain("ResizablePanelGroup");
    expect(document.body.textContent).toContain("PlotModeSidebar:desktop");
    expect(document.body.textContent).toContain("2 selected files");
    expect(document.body.textContent).toContain("WalkthroughPromptModal:plot:open");
    expect(document.body.textContent).toContain("PlotModeWalkthroughTour");
    expect(document.body.textContent).toContain("RunnerAuthDialog");
  });

  it("renders the mobile branch without the desktop resizable layout", async () => {
    await act(async () => {
      root.render(
        <PlotModeScreen
          {...createProps({
            allowWorkspaceSidebar: false,
            showWorkspaceSidebar: false,
            desktopViewport: false,
            walkthroughPromptOpen: false,
            showPlotModeWalkthroughTour: false,
          })}
        />,
      );
    });

    expect(document.body.textContent).toContain("SessionSidebar:closed");
    expect(document.body.textContent).toContain("PlotModeSidebar:mobile");
    expect(document.body.textContent).not.toContain("ResizablePanelGroup");
    expect(container.querySelector(".fixed.inset-y-0.left-0.z-30.hidden.w-8.lg\\:block")).toBeNull();
  });
});
