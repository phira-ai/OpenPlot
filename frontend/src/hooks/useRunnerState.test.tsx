// @vitest-environment jsdom

import { act, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FixRunner, OpencodeModelOption, PythonInterpreterState } from "../types";

vi.mock("../api/runners", () => ({
  fetchRunnerStatus: vi.fn(),
  installRunner: vi.fn(),
  launchRunnerAuth: vi.fn(),
  fetchRunnerModels: vi.fn(),
}));

vi.mock("../api/runtime", () => ({
  openExternalUrl: vi.fn(),
  refreshUpdateStatus: vi.fn(),
  fetchPythonInterpreter: vi.fn(),
  updatePythonInterpreter: vi.fn(),
}));

import { fetchRunnerModels, fetchRunnerStatus } from "../api/runners";
import { fetchPythonInterpreter } from "../api/runtime";
import { useRunnerState } from "./useRunnerState";

const fetchRunnerStatusMock = vi.mocked(fetchRunnerStatus);
const fetchRunnerModelsMock = vi.mocked(fetchRunnerModels);
const fetchPythonInterpreterMock = vi.mocked(fetchPythonInterpreter);

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

describe("useRunnerState", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let latestState: ReturnType<typeof useRunnerState> | null;
  let setSelectedRunnerForTest: ((runner: "opencode" | "codex" | "claude") => void) | null;

  function Harness() {
    const [selectedRunner, setSelectedRunner] = useState<"opencode" | "codex" | "claude">("opencode");
    const state = useRunnerState({ selectedRunner });

    useEffect(() => {
      latestState = state;
      setSelectedRunnerForTest = setSelectedRunner;
    }, [state]);

    return null;
  }

  async function flushPromises() {
    await Promise.resolve();
    await Promise.resolve();
  }

  async function renderHarness() {
    await act(async () => {
      root.render(<Harness />);
      await flushPromises();
    });
  }

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    latestState = null;
    setSelectedRunnerForTest = null;
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("setInterval", vi.fn(() => 1));
    vi.stubGlobal("clearInterval", vi.fn());

    fetchRunnerStatusMock.mockResolvedValue({
      available_runners: ["opencode"],
      installed_runners: ["opencode"],
      auth_status: {},
      active_install_job_id: null,
    } as never);
    fetchPythonInterpreterMock.mockResolvedValue(pythonInterpreterState);
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
      await flushPromises();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  it("ignores a stale model response after the selected runner changes", async () => {
    let resolveModels: ((value: {
      runner: FixRunner;
      models: OpencodeModelOption[];
      default_model: string;
      default_variant: string;
    }) => void) | null = null;
    fetchRunnerModelsMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveModels = resolve;
        }),
    );

    await renderHarness();

    expect(latestState?.opencodeModelsLoading).toBe(true);

    await act(async () => {
      setSelectedRunnerForTest?.("codex");
      await flushPromises();
    });

    expect(latestState?.opencodeModelsLoading).toBe(false);

    await act(async () => {
      resolveModels?.({
        runner: "opencode",
        models: [{ id: "stale-model", name: "Stale model", provider: "openai", variants: [] }],
        default_model: "stale-model",
        default_variant: "stale-variant",
      });
      await flushPromises();
    });

    expect(latestState?.opencodeModels).toEqual([]);
    expect(latestState?.defaultOpencodeModel).toBe("");
    expect(latestState?.defaultOpencodeVariant).toBe("");
  });
});
