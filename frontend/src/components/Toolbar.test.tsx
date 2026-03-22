// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Toolbar from "./Toolbar";

function createUpdateStatus(overrides: Record<string, unknown> = {}) {
  return {
    current_version: "1.1.0",
    latest_version: "1.2.0",
    latest_release_url: "https://github.com/phira-ai/OpenPlot/releases/latest",
    update_available: true,
    checked_at: "2026-03-22T20:00:00Z",
    error: null,
    ...overrides,
  };
}

function renderToolbar(overrides: Record<string, unknown> = {}) {
  return (
    <Toolbar
      mode="plot"
      connected
      wsUrl="ws://127.0.0.1:8000/ws"
      reconnectAttempts={0}
      lastConnectedAt={null}
      lastDisconnectedAt={null}
      opencodeModels={[]}
      opencodeModelsLoading={false}
      opencodeModelsError={null}
      availableRunners={["opencode"]}
      selectedRunner="opencode"
      onChangeRunner={vi.fn()}
      selectedModel=""
      selectedVariant=""
      onChangeModel={vi.fn()}
      onChangeVariant={vi.fn()}
      pythonInterpreterState={null}
      pythonInterpreterLoading={false}
      pythonInterpreterError={null}
      onRefreshPythonInterpreter={vi.fn(async () => {})}
      onSavePythonInterpreter={vi.fn(async () => {})}
      runnerStatus={{
        available_runners: ["opencode"],
        supported_runners: ["opencode", "codex", "claude"],
        claude_code_available: false,
        host_platform: "darwin",
        host_arch: "arm64",
        active_install_job_id: null,
        runners: [],
      }}
      runnerStatusLoading={false}
      runnerStatusError={null}
      onInstallRunner={vi.fn(async () => {})}
      onAuthenticateRunner={vi.fn(async () => {})}
      onOpenRunnerGuide={vi.fn(async () => {})}
      onRefreshRunners={vi.fn(async () => {})}
      updateStatus={createUpdateStatus()}
      updateStatusLoading={false}
      onRefreshUpdateStatus={vi.fn(async () => {})}
      onOpenReleasePage={vi.fn(async () => {})}
      {...overrides}
    />
  );
}

describe("Toolbar settings", () => {
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

  it("shows an icon-only settings button and a small update dot instead of label text", async () => {
    await act(async () => {
      root.render(renderToolbar());
    });

    const settingsButton = document.querySelector('button[aria-label="Settings"]');
    const updateDot = document.querySelector('[data-testid="settings-update-dot"]');

    expect(settingsButton).not.toBeNull();
    expect(updateDot).not.toBeNull();
    expect(document.body.textContent).not.toContain("Settings");
    expect(document.body.textContent).not.toContain("Update");
    expect(document.body.textContent).not.toContain("Runners");
    expect(document.body.textContent).not.toContain("Live Sync");
    expect(document.body.textContent).not.toContain("Python");
  });

  it("opens a tabbed settings dialog with an update action", async () => {
    const onRefreshUpdateStatus = vi.fn(async () => {});
    const onOpenReleasePage = vi.fn(async () => {});

    await act(async () => {
      root.render(
        renderToolbar({
          onRefreshUpdateStatus,
          onOpenReleasePage,
        }),
      );
    });

    const settingsButton = document.querySelector('button[aria-label="Settings"]');
    if (!settingsButton) {
      throw new Error("Expected Settings button");
    }

    await act(async () => {
      settingsButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(document.body.textContent).toContain("Runners");
    expect(document.body.textContent).toContain("Live Sync");
    expect(document.body.textContent).toContain("Python");
    expect(document.body.textContent).toContain("Update");

    const updateTab = Array.from(document.querySelectorAll("button")).find(
      (button) => button.textContent === "Update",
    );
    if (!updateTab) {
      throw new Error("Expected Update tab trigger");
    }

    await act(async () => {
      updateTab.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(document.body.textContent).toContain("Current version");
    expect(document.body.textContent).toContain("Latest version");
    expect(document.body.textContent).toContain("1.2.0");

    const refreshButton = Array.from(document.querySelectorAll("button")).find(
      (button) => button.textContent === "Check again",
    );
    const releaseButton = Array.from(document.querySelectorAll("button")).find(
      (button) => button.textContent === "View Latest Release",
    );
    if (!refreshButton || !releaseButton) {
      throw new Error("Expected update actions");
    }

    await act(async () => {
      refreshButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      releaseButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onRefreshUpdateStatus).toHaveBeenCalledTimes(1);
    expect(onOpenReleasePage).toHaveBeenCalledWith(
      "https://github.com/phira-ai/OpenPlot/releases/latest",
    );
  });

  it("shows an error when re-checking updates fails", async () => {
    const onRefreshUpdateStatus = vi.fn(async () => {
      throw new Error("Failed to check for updates");
    });

    await act(async () => {
      root.render(renderToolbar({ onRefreshUpdateStatus }));
    });

    const settingsButton = document.querySelector('button[aria-label="Settings"]');
    if (!settingsButton) {
      throw new Error("Expected Settings button");
    }

    await act(async () => {
      settingsButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const updateTab = Array.from(document.querySelectorAll("button")).find(
      (button) => button.textContent === "Update",
    );
    if (!updateTab) {
      throw new Error("Expected Update tab trigger");
    }

    await act(async () => {
      updateTab.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const refreshButton = Array.from(document.querySelectorAll("button")).find(
      (button) => button.textContent === "Check again",
    );
    if (!refreshButton) {
      throw new Error("Expected refresh button");
    }

    await act(async () => {
      refreshButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(document.body.textContent).toContain("Failed to check for updates");
  });
});
