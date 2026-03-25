// @vitest-environment jsdom

import { act, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FixJob } from "../types";

vi.mock("../api/fixJobs", () => ({
  cancelFixJob: vi.fn(),
  fetchCurrentFixJob: vi.fn(),
  startFixJob: vi.fn(),
}));

import { fetchCurrentFixJob } from "../api/fixJobs";
import { useFixJobState } from "./useFixJobState";

const fetchCurrentFixJobMock = vi.mocked(fetchCurrentFixJob);

function createFixJob(jobId = "job-1", sessionId = "annotation-1"): FixJob {
  return {
    id: jobId,
    session_id: sessionId,
    workspace_dir: `/tmp/${sessionId}`,
    branch_id: `branch-${sessionId}`,
    branch_name: `Branch ${sessionId}`,
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

describe("useFixJobState", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let latestState: ReturnType<typeof useFixJobState> | null;
  let activeSessionIdForTest: string | null;

  function Harness({ activeSessionId }: { activeSessionId: string | null }) {
    const state = useFixJobState({ activeSessionId });

    useEffect(() => {
      latestState = state;
    }, [state]);

    return null;
  }

  async function flushPromises() {
    await Promise.resolve();
    await Promise.resolve();
  }

  async function renderHarness() {
    await act(async () => {
      root.render(<Harness activeSessionId={activeSessionIdForTest} />);
      await flushPromises();
    });
  }

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    latestState = null;
    activeSessionIdForTest = "annotation-1";
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("setInterval", vi.fn(() => 1));
    vi.stubGlobal("clearInterval", vi.fn());
    vi.stubGlobal("setTimeout", vi.fn(() => 1));
    vi.stubGlobal("clearTimeout", vi.fn());

    fetchCurrentFixJobMock.mockResolvedValue({ job: null } as never);
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
      await flushPromises();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  it("ignores a stale refresh response after switching sessions", async () => {
    let resolveSessionOne: ((value: { job: FixJob }) => void) | null = null;
    fetchCurrentFixJobMock.mockImplementation(
      (sessionId: string) =>
        new Promise((resolve) => {
          if (sessionId === "annotation-1") {
            resolveSessionOne = resolve;
            return;
          }

          resolve({ job: createFixJob("job-2", "annotation-2") });
        }),
    );

    await renderHarness();

    await act(async () => {
      void latestState?.refreshFixJob();
      await flushPromises();
    });

    expect(resolveSessionOne).not.toBeNull();

    await act(async () => {
      activeSessionIdForTest = "annotation-2";
      root.render(<Harness activeSessionId={activeSessionIdForTest} />);
      await flushPromises();
    });

    await act(async () => {
      await latestState?.refreshFixJob();
      await flushPromises();
    });

    expect(latestState?.fixJob?.id).toBe("job-2");
    expect(latestState?.fixJob?.session_id).toBe("annotation-2");

    await act(async () => {
      resolveSessionOne?.({ job: createFixJob("job-1", "annotation-1") });
      await flushPromises();
    });

    expect(latestState?.fixJob?.id).toBe("job-2");
    expect(latestState?.fixJob?.session_id).toBe("annotation-2");
  });
});
