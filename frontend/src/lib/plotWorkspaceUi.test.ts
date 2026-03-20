import { describe, expect, it } from "vitest";

import {
  getPlotWorkspaceActionState,
  isPlotWorkspaceBusy,
  updatePlotWorkspaceActionState,
} from "./plotWorkspaceUi";

describe("updatePlotWorkspaceActionState", () => {
  it("sets one workspace busy without affecting another", () => {
    const current = {
      "plot-b": {
        selectingFiles: false,
        sendingMessage: true,
        finalizing: false,
      },
    };

    const next = updatePlotWorkspaceActionState(current, "plot-a", {
      sendingMessage: true,
    });

    expect(getPlotWorkspaceActionState(next, "plot-a")).toEqual({
      selectingFiles: false,
      sendingMessage: true,
      finalizing: false,
    });
    expect(getPlotWorkspaceActionState(next, "plot-b")).toEqual({
      selectingFiles: false,
      sendingMessage: true,
      finalizing: false,
    });
  });

  it("preserves unrelated flags when one action clears", () => {
    const current = {
      "plot-a": {
        selectingFiles: true,
        sendingMessage: true,
        finalizing: false,
      },
    };

    const next = updatePlotWorkspaceActionState(current, "plot-a", {
      sendingMessage: false,
    });

    expect(getPlotWorkspaceActionState(next, "plot-a")).toEqual({
      selectingFiles: true,
      sendingMessage: false,
      finalizing: false,
    });
  });

  it("removes the workspace entry when the last active flag clears", () => {
    const current = {
      "plot-a": {
        selectingFiles: false,
        sendingMessage: true,
        finalizing: false,
      },
    };

    const next = updatePlotWorkspaceActionState(current, "plot-a", {
      sendingMessage: false,
    });

    expect(next).toEqual({});
    expect(getPlotWorkspaceActionState(next, "plot-a")).toEqual({
      selectingFiles: false,
      sendingMessage: false,
      finalizing: false,
    });
    expect(isPlotWorkspaceBusy(getPlotWorkspaceActionState(next, "plot-a"))).toBe(false);
  });
});
