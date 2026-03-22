import { describe, expect, it } from "vitest";

import {
  computePlotPreviewViewport,
  createInitialWalkthroughPromptState,
  dismissWalkthroughPromptForMode,
  getPlotChatScrollIntent,
  isPlotWorkspacePhaseBusy,
  shouldActivateCompletedPlotWorkspace,
  shouldApplyPlotModeWorkspaceResponse,
  shouldApplyPlotModeWorkspaceUpdate,
  shouldRevealPlotComposer,
} from "./plotModeUi";

describe("createInitialWalkthroughPromptState", () => {
  it("shows both prompts when suppression is off", () => {
    expect(createInitialWalkthroughPromptState(false)).toEqual({
      annotation: true,
      plot: true,
    });
  });

  it("hides both prompts when suppression is on", () => {
    expect(createInitialWalkthroughPromptState(true)).toEqual({
      annotation: false,
      plot: false,
    });
  });
});

describe("dismissWalkthroughPromptForMode", () => {
  it("dismisses only the current mode prompt", () => {
    expect(
      dismissWalkthroughPromptForMode(
        { annotation: true, plot: true },
        "plot",
      ),
    ).toEqual({ annotation: true, plot: false });
  });
});

describe("shouldApplyPlotModeWorkspaceUpdate", () => {
  it("applies updates for the active visible plot workspace", () => {
    expect(
      shouldApplyPlotModeWorkspaceUpdate({
        activeWorkspaceId: "plot-a",
        incomingWorkspaceId: "plot-a",
        mode: "plot",
        visiblePlotModeId: "plot-a",
      }),
    ).toBe(true);
  });

  it("ignores background plot workspace updates", () => {
    expect(
      shouldApplyPlotModeWorkspaceUpdate({
        activeWorkspaceId: "plot-b",
        incomingWorkspaceId: "plot-a",
        mode: "plot",
        visiblePlotModeId: "plot-b",
      }),
    ).toBe(false);
  });

  it("does not force annotation mode back into plot mode", () => {
    expect(
      shouldApplyPlotModeWorkspaceUpdate({
        activeWorkspaceId: "annotation-1",
        incomingWorkspaceId: "plot-a",
        mode: "annotation",
        visiblePlotModeId: null,
      }),
    ).toBe(false);
  });
});

describe("shouldApplyPlotModeWorkspaceResponse", () => {
  it("applies a response for the active visible plot workspace", () => {
    expect(
      shouldApplyPlotModeWorkspaceResponse({
        activeWorkspaceId: "plot-a",
        requestWorkspaceId: "plot-a",
        responseWorkspaceId: "plot-a",
        mode: "plot",
        visiblePlotModeId: "plot-a",
      }),
    ).toBe(true);
  });

  it("ignores a late response after the user switches to another plot workspace", () => {
    expect(
      shouldApplyPlotModeWorkspaceResponse({
        activeWorkspaceId: "plot-b",
        requestWorkspaceId: "plot-a",
        responseWorkspaceId: "plot-a",
        mode: "plot",
        visiblePlotModeId: "plot-b",
      }),
    ).toBe(false);
  });

  it("ignores a late response after the user switches back to annotation", () => {
    expect(
      shouldApplyPlotModeWorkspaceResponse({
        activeWorkspaceId: "annotation-1",
        requestWorkspaceId: "plot-a",
        responseWorkspaceId: "plot-a",
        mode: "annotation",
        visiblePlotModeId: null,
      }),
    ).toBe(false);
  });
});

describe("shouldActivateCompletedPlotWorkspace", () => {
  it("switches into annotation only for the visible plot workspace", () => {
    expect(
      shouldActivateCompletedPlotWorkspace({
        activeWorkspaceId: "plot-a",
        completedWorkspaceId: "plot-a",
        mode: "plot",
        visiblePlotModeId: "plot-a",
      }),
    ).toBe(true);
  });

  it("keeps background completions from taking over the UI", () => {
    expect(
      shouldActivateCompletedPlotWorkspace({
        activeWorkspaceId: "plot-b",
        completedWorkspaceId: "plot-a",
        mode: "plot",
        visiblePlotModeId: "plot-b",
      }),
    ).toBe(false);
  });
});

describe("shouldRevealPlotComposer", () => {
  it("hides the composer on desktop until the pointer reaches the reveal zone", () => {
    expect(
      shouldRevealPlotComposer({
        desktopViewport: true,
        hasHistory: true,
        hasMessage: false,
        isFocused: false,
        isHovered: false,
        isNearRevealZone: false,
        isSending: false,
        touchInput: false,
      }),
    ).toBe(false);
  });

  it("keeps the composer visible while focused or sending", () => {
    expect(
      shouldRevealPlotComposer({
        desktopViewport: true,
        forceVisible: false,
        hasHistory: true,
        hasMessage: false,
        isFocused: true,
        isHovered: false,
        isNearRevealZone: false,
        isSending: false,
        touchInput: false,
      }),
    ).toBe(true);

    expect(
      shouldRevealPlotComposer({
        desktopViewport: true,
        forceVisible: false,
        hasHistory: true,
        hasMessage: false,
        isFocused: false,
        isHovered: false,
        isNearRevealZone: false,
        isSending: true,
        touchInput: false,
      }),
    ).toBe(true);
  });

  it("keeps the composer visible on touch or small-screen layouts", () => {
    expect(
      shouldRevealPlotComposer({
        desktopViewport: false,
        forceVisible: false,
        hasHistory: true,
        hasMessage: false,
        isFocused: false,
        isHovered: false,
        isNearRevealZone: false,
        isSending: false,
        touchInput: true,
      }),
    ).toBe(true);
  });

  it("pins the composer open when there is no chat history yet", () => {
    expect(
      shouldRevealPlotComposer({
        desktopViewport: true,
        forceVisible: false,
        hasHistory: false,
        hasMessage: false,
        isFocused: false,
        isHovered: false,
        isNearRevealZone: false,
        isSending: false,
        touchInput: false,
      }),
    ).toBe(true);
  });

  it("forces the composer open for walkthrough steps inside the prompt pill", () => {
    expect(
      shouldRevealPlotComposer({
        desktopViewport: true,
        forceVisible: true,
        hasHistory: true,
        hasMessage: false,
        isFocused: false,
        isHovered: false,
        isNearRevealZone: false,
        isSending: false,
        touchInput: false,
      }),
    ).toBe(true);
  });
});

describe("isPlotWorkspacePhaseBusy", () => {
  it("treats active server phases as busy", () => {
    expect(isPlotWorkspacePhaseBusy("profiling_data")).toBe(true);
    expect(isPlotWorkspacePhaseBusy("planning")).toBe(true);
    expect(isPlotWorkspacePhaseBusy("drafting")).toBe(true);
    expect(isPlotWorkspacePhaseBusy("self_review")).toBe(true);
  });

  it("treats idle or waiting phases as not busy", () => {
    expect(isPlotWorkspacePhaseBusy("awaiting_prompt")).toBe(false);
    expect(isPlotWorkspacePhaseBusy("ready")).toBe(false);
    expect(isPlotWorkspacePhaseBusy(undefined)).toBe(false);
  });
});

describe("computePlotPreviewViewport", () => {
  it("fits the image to the available frame before zooming", () => {
    expect(
      computePlotPreviewViewport({
        containerHeight: 720,
        containerWidth: 1200,
        framePadding: 48,
        naturalHeight: 1200,
        naturalWidth: 2400,
        zoom: 1,
      }),
    ).toEqual({
      displayHeight: 576,
      displayWidth: 1152,
    });
  });

  it("keeps 100% as the largest stable fit inside the available pane", () => {
    expect(
      computePlotPreviewViewport({
        containerHeight: 701,
        containerWidth: 907,
        framePadding: 48,
        naturalHeight: 800,
        naturalWidth: 1200,
        zoom: 1,
      }),
    ).toEqual({
      displayHeight: 572,
      displayWidth: 859,
    });
  });

  it("treats 110% as a modest increase from the fitted baseline", () => {
    expect(
      computePlotPreviewViewport({
        containerHeight: 701,
        containerWidth: 907,
        framePadding: 48,
        naturalHeight: 800,
        naturalWidth: 1200,
        zoom: 1.1,
      }),
    ).toEqual({
      displayHeight: 629,
      displayWidth: 944,
    });
  });

  it("applies zoom on top of the fitted size", () => {
    expect(
      computePlotPreviewViewport({
        containerHeight: 720,
        containerWidth: 1200,
        framePadding: 48,
        naturalHeight: 1200,
        naturalWidth: 2400,
        zoom: 1.5,
      }),
    ).toEqual({
      displayHeight: 864,
      displayWidth: 1728,
    });
  });
});

describe("getPlotChatScrollIntent", () => {
  it("restores the chat to the bottom when switching workspaces", () => {
    expect(
      getPlotChatScrollIntent({
        nextMessages: [
          { id: "assistant-1", role: "assistant" },
          { id: "assistant-2", role: "assistant" },
        ],
        nextWorkspaceId: "plot-b",
        previousMessages: [{ id: "assistant-1", role: "assistant" }],
        previousWorkspaceId: "plot-a",
        userNearBottom: false,
      }),
    ).toBe("restore-bottom");
  });

  it("does not use workspace-switch restore on the initial mount", () => {
    expect(
      getPlotChatScrollIntent({
        nextMessages: [{ id: "assistant-1", role: "assistant" }],
        nextWorkspaceId: "plot-a",
        pendingRestoreWorkspaceId: null,
        previousMessages: [],
        previousWorkspaceId: "plot-a",
        userNearBottom: true,
      }),
    ).toBe("preserve-position");
  });

  it("keeps a workspace-switch restore pending until the new workspace messages mount", () => {
    expect(
      getPlotChatScrollIntent({
        nextMessages: [],
        nextWorkspaceId: "plot-b",
        pendingRestoreWorkspaceId: "plot-b",
        previousMessages: [{ id: "assistant-1", role: "assistant" }],
        previousWorkspaceId: "plot-a",
        userNearBottom: false,
      }),
    ).toBe("preserve-position");

    expect(
      getPlotChatScrollIntent({
        nextMessages: [{ id: "assistant-2", role: "assistant" }],
        nextWorkspaceId: "plot-b",
        pendingRestoreWorkspaceId: "plot-b",
        previousMessages: [],
        previousWorkspaceId: "plot-b",
        userNearBottom: false,
      }),
    ).toBe("restore-bottom");
  });

  it("auto-follows same-workspace assistant output only when already near the bottom", () => {
    expect(
      getPlotChatScrollIntent({
        nextMessages: [
          { id: "user-1", role: "user", content: "Prompt" },
          { id: "assistant-1", role: "assistant", content: "Draft one" },
          { id: "assistant-2", role: "assistant", content: "Draft two" },
        ],
        nextWorkspaceId: "plot-a",
        previousMessages: [
          { id: "user-1", role: "user", content: "Prompt" },
          { id: "assistant-1", role: "assistant", content: "Draft one" },
        ],
        previousWorkspaceId: "plot-a",
        userNearBottom: true,
      }),
    ).toBe("follow-bottom");

    expect(
      getPlotChatScrollIntent({
        nextMessages: [
          { id: "user-1", role: "user", content: "Prompt" },
          { id: "assistant-1", role: "assistant", content: "Draft one" },
          { id: "assistant-2", role: "assistant", content: "Draft two" },
        ],
        nextWorkspaceId: "plot-a",
        previousMessages: [
          { id: "user-1", role: "user", content: "Prompt" },
          { id: "assistant-1", role: "assistant", content: "Draft one" },
        ],
        previousWorkspaceId: "plot-a",
        userNearBottom: false,
      }),
    ).toBe("preserve-position");
  });

  it("treats assistant updates to an existing message as followable output", () => {
    expect(
      getPlotChatScrollIntent({
        nextMessages: [
          { id: "assistant-1", role: "assistant", content: "Expanded draft" },
        ],
        nextWorkspaceId: "plot-a",
        previousMessages: [
          { id: "assistant-1", role: "assistant", content: "Initial draft" },
        ],
        previousWorkspaceId: "plot-a",
        userNearBottom: true,
      }),
    ).toBe("follow-bottom");
  });
});
