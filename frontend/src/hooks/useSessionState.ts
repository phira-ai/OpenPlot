import { useState, useEffect, useCallback, useRef } from "react";
import type {
  AppMode,
  Branch,
  PlotSession,
  BootstrapState,
  SessionSummary,
  PlotModeState,
  PlotModeChatMessage,
  PlotModeExecutionMode,
  RunnerAvailabilityState,
  Annotation,
  WsEvent,
  FixJob,
  FixJobStatus,
  FixJobLogEvent,
  FixStepStatus,
  FixRunner,
  OpencodeModelOption,
  PlotModePathSelectionType,
  PlotModePathSuggestionResponse,
  PythonInterpreterMode,
  PythonInterpreterState,
} from "../types";
import { API_BASE, fetchJSON } from "../api/client";
import { asErrorMessage } from "../lib/errors";
import {
  shouldActivateCompletedPlotWorkspace,
  shouldApplyPlotModeWorkspaceResponse,
  shouldApplyPlotModeWorkspaceUpdate,
} from "../lib/plotModeUi";

const MAX_FIX_STEP_LOG_EVENTS = 8000;

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function normalizeEventType(value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  return value.trim().toLowerCase().replaceAll("-", "_");
}

function shouldStoreFixLogEvent(event: FixJobLogEvent): boolean {
  if (event.stream !== "stdout") {
    return true;
  }

  const parsed = asRecord(event.parsed);
  if (!parsed) {
    return true;
  }

  const rootType = normalizeEventType(parsed.type);
  if (rootType !== "stream_event") {
    return true;
  }

  const nestedEvent = asRecord(parsed.event);
  if (!nestedEvent) {
    return true;
  }

  const eventType = normalizeEventType(nestedEvent.type);
  if (
    eventType === "message_start" ||
    eventType === "message_delta" ||
    eventType === "message_stop" ||
    eventType === "content_block_stop"
  ) {
    return false;
  }

  if (eventType === "content_block_delta") {
    const delta = asRecord(nestedEvent.delta);
    const deltaType = normalizeEventType(delta?.type);
    if (
      deltaType === "input_json_delta" ||
      deltaType === "thinking_delta" ||
      deltaType === "signature_delta"
    ) {
      return false;
    }
  }

  return true;
}

function defaultWorkspaceName(createdAt: string): string {
  const timestamp = Date.parse(createdAt);
  if (Number.isNaN(timestamp)) {
    return createdAt || "Workspace";
  }

  const dt = new Date(timestamp);
  const year = dt.getUTCFullYear();
  const month = String(dt.getUTCMonth() + 1).padStart(2, "0");
  const day = String(dt.getUTCDate()).padStart(2, "0");
  const hours = String(dt.getUTCHours()).padStart(2, "0");
  const minutes = String(dt.getUTCMinutes()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes} UTC`;
}

function toSessionSummary(session: PlotSession): SessionSummary {
  const name =
    session.workspace_name?.trim() || defaultWorkspaceName(session.created_at);
  const pendingCount = session.annotations.filter((ann) => ann.status === "pending").length;
  const workspaceId = session.workspace_id?.trim() || session.id;
  return {
    id: workspaceId,
    session_id: session.id,
    workspace_mode: "annotation",
    workspace_name: name,
    source_script_path: session.source_script_path,
    plot_type: session.plot_type,
    annotation_count: session.annotations.length,
    pending_annotation_count: pendingCount,
    checked_out_version_id: session.checked_out_version_id,
    created_at: session.created_at,
    updated_at: session.updated_at,
  };
}

function normalizeSessionSummary(summary: SessionSummary): SessionSummary {
  const name =
    summary.workspace_name?.trim() || defaultWorkspaceName(summary.created_at);
  return {
    ...summary,
    session_id:
      summary.workspace_mode === "annotation"
        ? summary.session_id?.trim() || summary.id
        : null,
    workspace_mode: summary.workspace_mode === "plot" ? "plot" : "annotation",
    plot_phase: summary.workspace_mode === "plot" ? summary.plot_phase ?? null : null,
    workspace_name: name,
  };
}

function toPlotModeWorkspaceSummary(plotMode: PlotModeState): SessionSummary {
  const workspaceName = plotMode.workspace_name?.trim() || defaultWorkspaceName(plotMode.created_at);
  const inferredPlotType = plotMode.plot_type ?? "svg";
  return {
    id: plotMode.id,
    session_id: null,
    workspace_mode: "plot",
    plot_phase: plotMode.phase,
    workspace_name: workspaceName,
    source_script_path: plotMode.current_script_path,
    plot_type: inferredPlotType,
    annotation_count: 0,
    pending_annotation_count: 0,
    checked_out_version_id: "",
    created_at: plotMode.created_at,
    updated_at: plotMode.updated_at,
  };
}

function workspaceSummarySortKey(summary: SessionSummary): [string, string, string] {
  return [summary.updated_at || summary.created_at, summary.created_at, summary.id];
}

function sortWorkspaceSummaries(items: SessionSummary[]): SessionSummary[] {
  return [...items].sort((left, right) => {
    const leftKey = workspaceSummarySortKey(left);
    const rightKey = workspaceSummarySortKey(right);
    if (leftKey[0] !== rightKey[0]) {
      return rightKey[0].localeCompare(leftKey[0]);
    }
    if (leftKey[1] !== rightKey[1]) {
      return rightKey[1].localeCompare(leftKey[1]);
    }
    return rightKey[2].localeCompare(leftKey[2]);
  });
}

function upsertWorkspaceSummary(
  current: SessionSummary[],
  summary: SessionSummary,
): SessionSummary[] {
  const normalized = normalizeSessionSummary(summary);
  const remaining = current.filter((entry) => entry.id !== normalized.id);
  return sortWorkspaceSummaries([normalized, ...remaining]);
}

function removeWorkspaceSummary(current: SessionSummary[], workspaceId: string): SessionSummary[] {
  return current.filter((entry) => entry.id !== workspaceId);
}

function touchWorkspaceSummary(
  current: SessionSummary[],
  workspaceId: string,
  updatedAt: string,
): SessionSummary[] {
  return sortWorkspaceSummaries(
    current.map((entry) =>
      entry.id === workspaceId
        ? {
            ...entry,
            updated_at: updatedAt,
          }
        : entry,
    ),
  );
}

function upsertPlotModeMessage(
  current: PlotModeState | null,
  plotModeId: string,
  updatedAt: string,
  message: PlotModeChatMessage,
): PlotModeState | null {
  if (!current || current.id !== plotModeId) {
    return current;
  }

  const currentUpdatedAt = Date.parse(current.updated_at);
  const incomingUpdatedAt = Date.parse(updatedAt);
  if (
    Number.isFinite(currentUpdatedAt) &&
    Number.isFinite(incomingUpdatedAt) &&
    incomingUpdatedAt < currentUpdatedAt
  ) {
    return current;
  }

  const existingIndex = current.messages.findIndex((entry) => entry.id === message.id);
  const nextMessages =
    existingIndex >= 0
      ? current.messages.map((entry, index) => (index === existingIndex ? message : entry))
      : [...current.messages, message];

  return {
    ...current,
    messages: nextMessages,
    updated_at: updatedAt || current.updated_at,
  };
}

function normalizeRunner(value: unknown): FixRunner {
  if (value === "codex") {
    return "codex";
  }
  if (value === "claude") {
    return "claude";
  }
  return "opencode";
}

function extractFileNameFromDisposition(disposition: string | null): string | null {
  if (!disposition) {
    return null;
  }

  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1]);
  }

  const quotedMatch = disposition.match(/filename="([^"]+)"/i);
  if (quotedMatch?.[1]) {
    return quotedMatch[1];
  }

  const bareMatch = disposition.match(/filename=([^;]+)/i);
  if (bareMatch?.[1]) {
    return bareMatch[1].trim();
  }

  return null;
}

const FIX_JOB_STATUS_ORDER: Record<FixJobStatus, number> = {
  queued: 0,
  running: 1,
  completed: 2,
  failed: 2,
  cancelled: 2,
};

const FIX_STEP_STATUS_ORDER: Record<FixStepStatus, number> = {
  queued: 0,
  running: 1,
  completed: 2,
  failed: 2,
  cancelled: 2,
};

function mergeFixJobSnapshot(current: FixJob | null, incoming: FixJob | null): FixJob | null {
  if (!incoming) {
    return current;
  }
  if (!current || current.id !== incoming.id) {
    return incoming;
  }

  const incomingJobOrder = FIX_JOB_STATUS_ORDER[incoming.status];
  const currentJobOrder = FIX_JOB_STATUS_ORDER[current.status];
  if (incomingJobOrder > currentJobOrder) {
    return incoming;
  }
  if (incomingJobOrder < currentJobOrder) {
    return current;
  }

  if (incoming.steps.length > current.steps.length) {
    return incoming;
  }
  if (incoming.steps.length < current.steps.length) {
    return current;
  }

  const incomingLatestStep = incoming.steps[incoming.steps.length - 1] ?? null;
  const currentLatestStep = current.steps[current.steps.length - 1] ?? null;
  if (incomingLatestStep && currentLatestStep) {
    const incomingStepOrder = FIX_STEP_STATUS_ORDER[incomingLatestStep.status];
    const currentStepOrder = FIX_STEP_STATUS_ORDER[currentLatestStep.status];
    if (incomingStepOrder > currentStepOrder) {
      return incoming;
    }
    if (incomingStepOrder < currentStepOrder) {
      return current;
    }
  }

  if (incoming.completed_annotations > current.completed_annotations) {
    return incoming;
  }
  if (incoming.completed_annotations < current.completed_annotations) {
    return current;
  }

  return incoming;
}

/**
 * Manages the current PlotSession state, syncing with the backend.
 */
export function useSessionState() {
  const [mode, setMode] = useState<AppMode>("plot");
  const [session, setSession] = useState<PlotSession | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);
  const [plotMode, setPlotMode] = useState<PlotModeState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRunner, setSelectedRunner] = useState<FixRunner>("opencode");
  const [availableRunners, setAvailableRunners] = useState<FixRunner[]>([]);
  const [backendFatalError, setBackendFatalError] = useState<string | null>(null);
  const [opencodeModels, setOpencodeModels] = useState<OpencodeModelOption[]>([]);
  const [defaultOpencodeModel, setDefaultOpencodeModel] = useState("");
  const [defaultOpencodeVariant, setDefaultOpencodeVariant] = useState("");
  const [opencodeModelsLoading, setOpencodeModelsLoading] = useState(true);
  const [opencodeModelsError, setOpencodeModelsError] = useState<string | null>(null);
  const [pythonInterpreter, setPythonInterpreter] = useState<PythonInterpreterState | null>(
    null,
  );
  const [pythonInterpreterLoading, setPythonInterpreterLoading] = useState(true);
  const [pythonInterpreterError, setPythonInterpreterError] = useState<string | null>(null);
  const [fixJob, setFixJob] = useState<FixJob | null>(null);
  const [fixStepLogsByKey, setFixStepLogsByKey] = useState<Record<string, FixJobLogEvent[]>>({});
  const runnerModelsRequestIdRef = useRef(0);
  const availableRunnersRef = useRef<FixRunner[]>([]);
  const activeWorkspaceIdRef = useRef<string | null>(null);
  const modeRef = useRef<AppMode>("plot");
  const plotModeRef = useRef<PlotModeState | null>(null);
  const sessionsRef = useRef<SessionSummary[]>([]);
  const workspaceNavigationRequestIdRef = useRef(0);

  // Cache-bust for plot reloads.
  const [plotVersion, setPlotVersion] = useState(0);

  const applyBootstrapPayload = useCallback((payload: BootstrapState) => {
    if (Array.isArray(payload.sessions)) {
      setSessions(sortWorkspaceSummaries(payload.sessions.map(normalizeSessionSummary)));
    }

    if ("active_session_id" in payload) {
      setActiveSessionId(payload.active_session_id ?? null);
    } else if (payload.mode === "annotation") {
      setActiveSessionId(payload.session?.id ?? null);
    } else {
      setActiveSessionId(null);
    }

    if ("active_workspace_id" in payload) {
      setActiveWorkspaceId(payload.active_workspace_id ?? null);
    } else if (payload.mode === "annotation") {
      setActiveWorkspaceId(payload.session?.id ?? null);
    } else {
      setActiveWorkspaceId(payload.plot_mode?.id ?? null);
    }

    if (payload.mode === "annotation") {
      setMode("annotation");
      setSession(payload.session ?? null);
      setPlotMode(null);
      return;
    }

    const nextPlotMode = payload.plot_mode ?? null;
    setMode("plot");
    setSession(null);
    setPlotMode(nextPlotMode);
  }, []);

  const applyBootstrapSummariesOnly = useCallback((payload: BootstrapState) => {
    if (Array.isArray(payload.sessions)) {
      setSessions(sortWorkspaceSummaries(payload.sessions.map(normalizeSessionSummary)));
      return;
    }

    if (payload.mode === "plot" && payload.plot_mode) {
      setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(payload.plot_mode!)));
      return;
    }

    if (payload.mode === "annotation" && payload.session) {
      setSessions((previous) => upsertWorkspaceSummary(previous, toSessionSummary(payload.session!)));
    }
  }, []);

  const beginWorkspaceNavigationRequest = useCallback(() => {
    const requestId = workspaceNavigationRequestIdRef.current + 1;
    workspaceNavigationRequestIdRef.current = requestId;
    return requestId;
  }, []);

  const isCurrentWorkspaceNavigationRequest = useCallback(
    (requestId: number) => workspaceNavigationRequestIdRef.current === requestId,
    [],
  );

  const refresh = useCallback(async () => {
    const requestId = workspaceNavigationRequestIdRef.current;
    try {
      const payload = await fetchJSON<BootstrapState>("/api/bootstrap");
      if (workspaceNavigationRequestIdRef.current === requestId) {
        applyBootstrapPayload(payload);
      } else {
        applyBootstrapSummariesOnly(payload);
      }
      setError(null);
    } catch (err: unknown) {
      if (workspaceNavigationRequestIdRef.current === requestId) {
        setError(asErrorMessage(err, "Failed to fetch bootstrap state"));
      }
    } finally {
      setLoading(false);
    }
  }, [applyBootstrapPayload, applyBootstrapSummariesOnly]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    plotModeRef.current = plotMode;
  }, [plotMode]);

  useEffect(() => {
    activeWorkspaceIdRef.current = activeWorkspaceId;
  }, [activeWorkspaceId]);

  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);

  useEffect(() => {
    sessionsRef.current = sessions;
  }, [sessions]);

  useEffect(() => {
    availableRunnersRef.current = availableRunners;
  }, [availableRunners]);

  const refreshRunnerAvailability = useCallback(async () => {
    try {
      const payload = await fetchJSON<RunnerAvailabilityState>("/api/runners");
      const available = Array.isArray(payload.available_runners)
        ? payload.available_runners.filter(
            (runner): runner is FixRunner =>
              runner === "opencode" || runner === "codex" || runner === "claude",
          )
        : [];
      setAvailableRunners(available);
      if (available.length === 0) {
        setBackendFatalError(
          "At least one backend CLI must exist: codex, claude code, opencode.",
        );
        setOpencodeModelsLoading(false);
      } else {
        setBackendFatalError(null);
      }
    } catch (err: unknown) {
      setAvailableRunners([]);
      setBackendFatalError(
        asErrorMessage(err, "Failed to detect available backend CLIs"),
      );
      setOpencodeModelsLoading(false);
    }
  }, []);

  const refreshRunnerModels = useCallback(async (runner: FixRunner) => {
    const requestId = runnerModelsRequestIdRef.current + 1;
    runnerModelsRequestIdRef.current = requestId;

    setOpencodeModelsLoading(true);
    try {
      const payload = await fetchJSON<{
        runner: FixRunner;
        models: OpencodeModelOption[];
        default_model: string;
        default_variant: string;
      }>(`/api/runners/models?runner=${runner}`);

      if (runnerModelsRequestIdRef.current !== requestId) {
        return;
      }

      setOpencodeModels(payload.models || []);
      setDefaultOpencodeModel(payload.default_model || "");
      setDefaultOpencodeVariant(payload.default_variant || "");
      setOpencodeModelsError(null);
    } catch (err: unknown) {
      if (runnerModelsRequestIdRef.current !== requestId) {
        return;
      }

      setOpencodeModels([]);
      setDefaultOpencodeModel("");
      setDefaultOpencodeVariant("");
      setOpencodeModelsError(
        asErrorMessage(err, `Failed to load models from ${runner}`),
      );
    } finally {
      if (runnerModelsRequestIdRef.current === requestId) {
        setOpencodeModelsLoading(false);
      }
    }
  }, []);

  const refreshFixPreferences = useCallback(async () => {
    try {
      const payload = await fetchJSON<{
        fix_runner?: FixRunner;
      }>("/api/preferences");
      const runner = normalizeRunner(payload.fix_runner);
      setSelectedRunner((current) => {
        // If the current runner is already in the available list, prefer it
        // over the preference to avoid reverting an auto-correction.
        if (availableRunnersRef.current.length > 0 && availableRunnersRef.current.includes(current)) {
          return current;
        }
        return runner;
      });
    } catch {
      // Keep the current runner rather than forcing "opencode".
    }
  }, []);

  const refreshFixJob = useCallback(async () => {
    const targetSessionId = activeSessionId?.trim();
    if (!targetSessionId) {
      setFixJob(null);
      return;
    }

    try {
      const payload = await fetchJSON<{ job: FixJob | null }>(
        `/api/fix-jobs/current?session_id=${encodeURIComponent(targetSessionId)}`,
      );

      if (payload.job && payload.job.session_id !== targetSessionId) {
        setFixJob(null);
        return;
      }

      setFixJob((current) => mergeFixJobSnapshot(current, payload.job));
    } catch {
      // Ignore errors so existing annotation workflow remains unaffected.
    }
  }, [activeSessionId]);

  const refreshPythonInterpreter = useCallback(async () => {
    setPythonInterpreterLoading(true);
    try {
      const payload = await fetchJSON<PythonInterpreterState>("/api/python/interpreter");
      setPythonInterpreter(payload);
      setPythonInterpreterError(null);
    } catch (err: unknown) {
      setPythonInterpreter(null);
      setPythonInterpreterError(
        asErrorMessage(err, "Failed to load Python interpreter configuration"),
      );
    } finally {
      setPythonInterpreterLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshRunnerAvailability();
    void refreshFixPreferences();
    void refreshFixJob();
    void refreshPythonInterpreter();
  }, [
    refreshFixJob,
    refreshFixPreferences,
    refreshPythonInterpreter,
    refreshRunnerAvailability,
  ]);

  useEffect(() => {
    setOpencodeModels([]);
    setDefaultOpencodeModel("");
    setDefaultOpencodeVariant("");
  }, [selectedRunner]);

  useEffect(() => {
    if (!availableRunners.includes(selectedRunner)) {
      setOpencodeModelsLoading(false);
      return;
    }
    void refreshRunnerModels(selectedRunner);
  }, [availableRunners, refreshRunnerModels, selectedRunner]);

  useEffect(() => {
    setFixJob((current) => {
      if (!current) {
        return null;
      }
      if (!activeSessionId || current.session_id !== activeSessionId) {
        return null;
      }
      return current;
    });
  }, [activeSessionId]);

  useEffect(() => {
    if (!fixJob || (fixJob.status !== "queued" && fixJob.status !== "running")) {
      return;
    }
    if (!activeSessionId || fixJob.session_id !== activeSessionId) {
      return;
    }

    const intervalHandle = window.setInterval(() => {
      void refreshFixJob();
    }, 1000);

    return () => {
      window.clearInterval(intervalHandle);
    };
  }, [activeSessionId, fixJob, refreshFixJob]);

  // --- Annotation CRUD ---

  const addAnnotation = useCallback(async (annotation: Partial<Annotation>) => {
    const result = await fetchJSON<{ status: string; id: string }>(
      "/api/annotations",
      { method: "POST", body: JSON.stringify(annotation) },
    );
    await refresh();
    return result;
  }, [refresh]);

  const deleteAnnotation = useCallback(async (id: string) => {
    await fetchJSON(`/api/annotations/${id}`, { method: "DELETE" });
    await refresh();
  }, [refresh]);

  const updateAnnotation = useCallback(async (id: string, updates: Partial<Annotation>) => {
    await fetchJSON(`/api/annotations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
    await refresh();
  }, [refresh]);

  const checkoutVersion = useCallback(async (versionId: string, branchId?: string) => {
    await fetchJSON("/api/checkout", {
      method: "POST",
      body: JSON.stringify({
        version_id: versionId,
        branch_id: branchId,
      }),
    });
    await refresh();
    setPlotVersion((v) => v + 1);
  }, [refresh]);

  const switchBranch = useCallback(async (branchId: string) => {
    await fetchJSON(`/api/branches/${branchId}/checkout`, {
      method: "POST",
    });
    await refresh();
    setPlotVersion((v) => v + 1);
  }, [refresh]);

  const renameBranch = useCallback(async (branchId: string, name: string) => {
    const normalizedBranchId = branchId.trim();
    const normalizedName = name.trim();
    if (!normalizedBranchId) {
      throw new Error("Missing branch id");
    }
    if (!normalizedName) {
      throw new Error("Branch name cannot be empty");
    }

    const payload = await fetchJSON<{
      status: string;
      branch: Branch;
      active_branch_id: string | null;
    }>(`/api/branches/${encodeURIComponent(normalizedBranchId)}`, {
      method: "PATCH",
      body: JSON.stringify({ name: normalizedName }),
    });

    setFixJob((current) => {
      if (!current || current.branch_id !== payload.branch.id) {
        return current;
      }
      return {
        ...current,
        branch_name: payload.branch.name,
      };
    });

    await refresh();
    return payload.branch;
  }, [refresh]);

  const downloadAnnotationPlot = useCallback(async (annotationId: string) => {
    const res = await fetch(`${API_BASE}/api/annotations/${annotationId}/export`);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status}: ${text}`);
    }

    const blob = await res.blob();
    const contentDisposition = res.headers.get("Content-Disposition");
    const inferred = extractFileNameFromDisposition(contentDisposition);
    const fileName = inferred || `annotation-${annotationId}.zip`;

    return { blob, fileName };
  }, []);

  const downloadPlotModeWorkspace = useCallback(async () => {
    const workspaceId = plotModeRef.current?.id?.trim();
    const params = new URLSearchParams();
    if (workspaceId) {
      params.set("workspace_id", workspaceId);
    }
    const suffix = params.size > 0 ? `?${params.toString()}` : "";
    const res = await fetch(`${API_BASE}/api/plot-mode/export${suffix}`);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status}: ${text}`);
    }

    const blob = await res.blob();
    const contentDisposition = res.headers.get("Content-Disposition");
    const inferred = extractFileNameFromDisposition(contentDisposition);
    const fileName = inferred || "openplot_plot_workspace.zip";

    return { blob, fileName };
  }, []);

  const startFixJob = useCallback(async (
    runner: FixRunner,
    model: string,
    variant?: string,
  ) => {
    const targetSessionId = activeSessionId?.trim();
    const payload = await fetchJSON<{ status: string; job: FixJob }>("/api/fix-jobs", {
      method: "POST",
      body: JSON.stringify({
        runner,
        model,
        variant: variant || null,
        session_id: targetSessionId || null,
      }),
    });
    setFixJob((current) => mergeFixJobSnapshot(current, payload.job));
    return payload.job;
  }, [activeSessionId]);

  const cancelFixJob = useCallback(async (jobId: string) => {
    const payload = await fetchJSON<{ status: string; job: FixJob }>(
      `/api/fix-jobs/${jobId}/cancel`,
      {
        method: "POST",
      },
    );
    setFixJob((current) => mergeFixJobSnapshot(current, payload.job));
    return payload.job;
  }, []);

  const updateFixPreferences = useCallback(async (
    runner: FixRunner,
    model?: string | null,
    variant?: string | null,
  ) => {
    const body: Record<string, string | null> = {
      fix_runner: runner,
    };
    if (model !== undefined) {
      body.fix_model = model || null;
    }
    if (variant !== undefined) {
      body.fix_variant = variant || null;
    }

    await fetchJSON<{
      status: string;
      fix_runner: FixRunner;
      fix_model: string | null;
      fix_variant: string | null;
    }>(
      "/api/preferences",
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    );
  }, []);

  useEffect(() => {
    if (availableRunners.length === 0) {
      return;
    }
    if (!availableRunners.includes(selectedRunner)) {
      const corrected = availableRunners[0];
      setSelectedRunner(corrected);
      // Persist so future loads / preference refreshes don't revert.
      void updateFixPreferences(corrected, null, null).catch(() => {});
    }
  }, [availableRunners, selectedRunner, updateFixPreferences]);

  const setPythonInterpreterPreference = useCallback(
    async (mode: PythonInterpreterMode, path?: string) => {
      const body: Record<string, string> = { mode };
      if (mode === "manual") {
        body.path = path?.trim() || "";
      }

      const payload = await fetchJSON<PythonInterpreterState>("/api/python/interpreter", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setPythonInterpreter(payload);
      setPythonInterpreterError(null);
      return payload;
    },
    [],
  );

  const fetchPlotModePathSuggestions = useCallback(
    async (
      workspaceId: string | null,
      query: string,
      selectionType: PlotModePathSelectionType,
    ) => {
      return await fetchJSON<PlotModePathSuggestionResponse>(
        "/api/plot-mode/path-suggestions",
        {
          method: "POST",
          body: JSON.stringify({
            query,
            selection_type: selectionType,
            workspace_id: workspaceId,
          }),
        },
      );
    },
    [],
  );

  const selectPlotModePaths = useCallback(
    async (
      workspaceId: string | null,
      selectionType: PlotModePathSelectionType,
      paths: string[],
    ) => {
      const normalizedPaths = paths.map((path) => path.trim()).filter(Boolean);
      if (normalizedPaths.length === 0) {
        return;
      }

      const requestWorkspaceId = workspaceId;
      const previousPlotPath = plotModeRef.current?.current_plot ?? null;
      const payload = await fetchJSON<BootstrapState>("/api/plot-mode/select-paths", {
        method: "POST",
        body: JSON.stringify({
          selection_type: selectionType,
          paths: normalizedPaths,
          workspace_id: requestWorkspaceId,
        }),
      });

      const shouldApplyPlotResponse =
        payload.mode === "plot" &&
        payload.plot_mode != null &&
        shouldApplyPlotModeWorkspaceResponse({
          activeWorkspaceId: activeWorkspaceIdRef.current,
          requestWorkspaceId,
          responseWorkspaceId: payload.plot_mode.id,
          mode: modeRef.current,
          visiblePlotModeId: plotModeRef.current?.id ?? null,
        });
      const shouldApplyCompletionResponse =
        requestWorkspaceId != null &&
        payload.mode === "annotation" &&
        modeRef.current === "plot" &&
        activeWorkspaceIdRef.current === requestWorkspaceId &&
        plotModeRef.current?.id === requestWorkspaceId;

      if (shouldApplyPlotResponse || shouldApplyCompletionResponse) {
        applyBootstrapPayload(payload);
      } else if (Array.isArray(payload.sessions)) {
        setSessions(sortWorkspaceSummaries(payload.sessions.map(normalizeSessionSummary)));
      } else {
        const nextPlotMode = payload.plot_mode;
        if (nextPlotMode) {
          setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(nextPlotMode)));
        }
      }
      setError(null);
      if (
        shouldApplyPlotResponse &&
        payload.plot_mode?.current_plot &&
        previousPlotPath !== payload.plot_mode.current_plot
      ) {
        setPlotVersion((value) => value + 1);
      }
    },
    [applyBootstrapPayload],
  );

  const sendPlotModeMessage = useCallback(
    async (
      workspaceId: string | null,
      message: string,
      runner?: FixRunner,
      model?: string,
      variant?: string,
    ) => {
      const trimmedMessage = message.trim();
      if (!trimmedMessage) {
        throw new Error("Message cannot be empty");
      }

      const requestWorkspaceId = workspaceId;
      const previousPlotPath = plotModeRef.current?.current_plot ?? null;
      const body: Record<string, string> = {
        message: trimmedMessage,
        workspace_id: requestWorkspaceId || "",
      };
      if (runner) {
        body.runner = runner;
      }
      const normalizedModel = model?.trim();
      const normalizedVariant = variant?.trim();
      if (normalizedModel) {
        body.model = normalizedModel;
      }
      if (variant !== undefined) {
        body.variant = normalizedVariant ?? "";
      }

      const payload = await fetchJSON<{
        status: "ok" | "error";
        plot_mode: PlotModeState;
        error?: string;
      }>("/api/plot-mode/chat", {
        method: "POST",
        body: JSON.stringify(body),
      });

      const shouldApplyResponse = shouldApplyPlotModeWorkspaceResponse({
        activeWorkspaceId: activeWorkspaceIdRef.current,
        requestWorkspaceId,
        responseWorkspaceId: payload.plot_mode.id,
        mode: modeRef.current,
        visiblePlotModeId: plotModeRef.current?.id ?? null,
      });

      if (shouldApplyResponse) {
        setMode("plot");
        setSession(null);
        setActiveSessionId(null);
        setActiveWorkspaceId(payload.plot_mode.id);
        setPlotMode(payload.plot_mode);
      }
      setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(payload.plot_mode)));
      setError(null);
      if (
        shouldApplyResponse &&
        payload.plot_mode.current_plot &&
        previousPlotPath !== payload.plot_mode.current_plot
      ) {
        setPlotVersion((value) => value + 1);
      }

      if (payload.status === "error") {
        throw new Error(payload.error || "Plot generation failed");
      }

      return payload;
    },
    [],
  );

  const submitPlotModeTabularHint = useCallback(
    async (
      workspaceId: string | null,
      selectorId: string,
      regions: Array<{
        sheet_id: string;
        row_start: number;
        row_end: number;
        col_start: number;
        col_end: number;
      }>,
      note: string,
      runner?: FixRunner,
      model?: string,
      variant?: string,
    ) => {
      const requestWorkspaceId = workspaceId;
      const body: Record<string, unknown> = {
        workspace_id: requestWorkspaceId,
        selector_id: selectorId,
        regions,
        note: note.trim() || null,
      };
      if (runner) {
        body.runner = runner;
      }
      const normalizedModel = model?.trim();
      const normalizedVariant = variant?.trim();
      if (normalizedModel) {
        body.model = normalizedModel;
      }
      if (variant !== undefined) {
        body.variant = normalizedVariant ?? "";
      }

      const payload = await fetchJSON<{
        status: "ok";
        plot_mode: PlotModeState;
      }>("/api/plot-mode/tabular-hint", {
        method: "POST",
        body: JSON.stringify(body),
      });

      const shouldApplyResponse = shouldApplyPlotModeWorkspaceResponse({
        activeWorkspaceId: activeWorkspaceIdRef.current,
        requestWorkspaceId,
        responseWorkspaceId: payload.plot_mode.id,
        mode: modeRef.current,
        visiblePlotModeId: plotModeRef.current?.id ?? null,
      });

      if (shouldApplyResponse) {
        setMode("plot");
        setSession(null);
        setActiveSessionId(null);
        setActiveWorkspaceId(payload.plot_mode.id);
        setPlotMode(payload.plot_mode);
      }
      setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(payload.plot_mode)));
      setError(null);
      return payload;
    },
    [],
  );

  const updatePlotModeExecutionMode = useCallback(async (
    workspaceId: string | null,
    executionMode: PlotModeExecutionMode,
  ) => {
    const requestWorkspaceId = workspaceId;
    const payload = await fetchJSON<{
      status: "ok";
      plot_mode: PlotModeState;
    }>("/api/plot-mode/settings", {
      method: "PATCH",
      body: JSON.stringify({ execution_mode: executionMode, workspace_id: requestWorkspaceId }),
    });

    const shouldApplyResponse = shouldApplyPlotModeWorkspaceResponse({
      activeWorkspaceId: activeWorkspaceIdRef.current,
      requestWorkspaceId,
      responseWorkspaceId: payload.plot_mode.id,
      mode: modeRef.current,
      visiblePlotModeId: plotModeRef.current?.id ?? null,
    });

    if (shouldApplyResponse) {
      setMode("plot");
      setSession(null);
      setActiveSessionId(null);
      setActiveWorkspaceId(payload.plot_mode.id);
      setPlotMode(payload.plot_mode);
    }
    setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(payload.plot_mode)));
    setError(null);
    return payload;
  }, []);

  const answerPlotModeQuestion = useCallback(
    async (
      workspaceId: string | null,
      questionSetId: string,
      answers: Array<{
        question_id: string;
        option_ids: string[];
        text?: string | null;
      }>,
      runner?: FixRunner,
      model?: string,
      variant?: string,
    ) => {
      const requestWorkspaceId = workspaceId;
      const body: Record<string, unknown> = {
        workspace_id: requestWorkspaceId,
        question_set_id: questionSetId,
        answers: answers.map((entry) => ({
          question_id: entry.question_id,
          option_ids: entry.option_ids,
          text: entry.text ?? null,
        })),
      };
      if (runner) {
        body.runner = runner;
      }
      const normalizedModel = model?.trim();
      const normalizedVariant = variant?.trim();
      if (normalizedModel) {
        body.model = normalizedModel;
      }
      if (variant !== undefined) {
        body.variant = normalizedVariant ?? "";
      }

      const payload = await fetchJSON<{
        status: "ok";
        plot_mode: PlotModeState;
      }>("/api/plot-mode/answer", {
        method: "POST",
        body: JSON.stringify(body),
      });

      const shouldApplyResponse = shouldApplyPlotModeWorkspaceResponse({
        activeWorkspaceId: activeWorkspaceIdRef.current,
        requestWorkspaceId,
        responseWorkspaceId: payload.plot_mode.id,
        mode: modeRef.current,
        visiblePlotModeId: plotModeRef.current?.id ?? null,
      });

      if (shouldApplyResponse) {
        setMode("plot");
        setSession(null);
        setActiveSessionId(null);
        setActiveWorkspaceId(payload.plot_mode.id);
        setPlotMode(payload.plot_mode);
      }
      setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(payload.plot_mode)));
      setError(null);
      return payload;
    },
    [],
  );

  const finalizePlotMode = useCallback(
    async (
      workspaceId: string | null,
      metadata?: Record<string, string | null>,
    ) => {
      const requestWorkspaceId = workspaceId;
      const payload = await fetchJSON<BootstrapState>("/api/plot-mode/finalize", {
        method: "POST",
        body: JSON.stringify({ ...(metadata ?? {}), workspace_id: requestWorkspaceId }),
      });

      const shouldApplyResponse =
        requestWorkspaceId != null &&
        modeRef.current === "plot" &&
        activeWorkspaceIdRef.current === requestWorkspaceId &&
        plotModeRef.current?.id === requestWorkspaceId;

      if (shouldApplyResponse) {
        applyBootstrapPayload(payload);
        setPlotVersion((value) => value + 1);
      } else if (Array.isArray(payload.sessions)) {
        setSessions(sortWorkspaceSummaries(payload.sessions.map(normalizeSessionSummary)));
      }
      setError(null);
      return payload;
    },
    [applyBootstrapPayload],
  );

  const createNewSession = useCallback(async () => {
    const requestId = beginWorkspaceNavigationRequest();
    const payload = await fetchJSON<BootstrapState>("/api/sessions/new", {
      method: "POST",
      body: JSON.stringify({}),
    });

    if (isCurrentWorkspaceNavigationRequest(requestId)) {
      applyBootstrapPayload(payload);
      setPlotVersion((value) => value + 1);
    } else {
      applyBootstrapSummariesOnly(payload);
    }
    setError(null);
    return payload;
  }, [
    applyBootstrapPayload,
    applyBootstrapSummariesOnly,
    beginWorkspaceNavigationRequest,
    isCurrentWorkspaceNavigationRequest,
  ]);

  const activateSession = useCallback(
    async (sessionId: string) => {
      const normalizedSessionId = sessionId.trim();
      if (!normalizedSessionId) {
        throw new Error("Missing session id");
      }
      const workspace = sessionsRef.current.find((entry) => entry.id === normalizedSessionId);
      const requestId = beginWorkspaceNavigationRequest();
      if (workspace?.workspace_mode === "plot") {
        try {
          const payload = await fetchJSON<BootstrapState>("/api/plot-mode/activate", {
            method: "POST",
            body: JSON.stringify({ id: normalizedSessionId }),
          });

          if (isCurrentWorkspaceNavigationRequest(requestId)) {
            applyBootstrapPayload(payload);
            if (payload.plot_mode?.current_plot) {
              setPlotVersion((value) => value + 1);
            }
          } else {
            applyBootstrapSummariesOnly(payload);
          }
          setError(null);
          return payload;
        } catch (err: unknown) {
          if (err instanceof Error && err.message.includes("404")) {
            return null;
          }
          throw err;
        }
      }

      const payload = await fetchJSON<BootstrapState>(
        `/api/sessions/${encodeURIComponent(workspace?.session_id || normalizedSessionId)}/activate`,
        {
          method: "POST",
          body: JSON.stringify({}),
        },
      );

      if (isCurrentWorkspaceNavigationRequest(requestId)) {
        applyBootstrapPayload(payload);
        setPlotVersion((value) => value + 1);
      } else {
        applyBootstrapSummariesOnly(payload);
      }
      setError(null);
      return payload;
    },
    [
      applyBootstrapPayload,
      applyBootstrapSummariesOnly,
      beginWorkspaceNavigationRequest,
      isCurrentWorkspaceNavigationRequest,
    ],
  );

  const renameWorkspace = useCallback(
    async (sessionId: string, workspaceName: string) => {
      const normalizedSessionId = sessionId.trim();
      const normalizedWorkspaceName = workspaceName.trim();
      if (!normalizedSessionId) {
        throw new Error("Missing session id");
      }
      if (!normalizedWorkspaceName) {
        throw new Error("Workspace name cannot be empty");
      }
      const workspace = sessionsRef.current.find((entry) => entry.id === normalizedSessionId);
      if (workspace?.workspace_mode === "plot") {
        const payload = await fetchJSON<{
          status: string;
          plot_mode: PlotModeState;
        }>("/api/plot-mode/workspace", {
          method: "PATCH",
          body: JSON.stringify({ id: normalizedSessionId, workspace_name: normalizedWorkspaceName }),
        });

        setPlotMode((current) =>
          current && current.id === payload.plot_mode.id ? payload.plot_mode : current,
        );
        const summary = toPlotModeWorkspaceSummary(payload.plot_mode);
        setSessions((previous) => upsertWorkspaceSummary(previous, summary));
        return summary;
      }

      const payload = await fetchJSON<{
        status: string;
        workspace: SessionSummary;
        active_session_id: string | null;
      }>(`/api/sessions/${encodeURIComponent(workspace?.session_id || normalizedSessionId)}`, {
        method: "PATCH",
        body: JSON.stringify({ workspace_name: normalizedWorkspaceName }),
      });

      const normalizedWorkspace = normalizeSessionSummary(payload.workspace);
      setSessions((previous) => {
        return upsertWorkspaceSummary(previous, normalizedWorkspace);
      });

      if (activeSessionId === normalizedWorkspace.session_id) {
        setSession((current) => {
          if (!current || current.id !== normalizedWorkspace.session_id) {
            return current;
          }
          return {
            ...current,
            workspace_name: normalizedWorkspace.workspace_name,
            updated_at: normalizedWorkspace.updated_at,
          };
        });
      }

      if (payload.active_session_id !== undefined) {
        setActiveSessionId(payload.active_session_id);
      }

      return normalizedWorkspace;
    },
    [activeSessionId],
  );

  const deleteWorkspace = useCallback(
    async (sessionId: string) => {
      const normalizedSessionId = sessionId.trim();
      if (!normalizedSessionId) {
        throw new Error("Missing session id");
      }
      const workspace = sessionsRef.current.find((entry) => entry.id === normalizedSessionId);
      const requestId = beginWorkspaceNavigationRequest();
      if (workspace?.workspace_mode === "plot") {
        const payload = await fetchJSON<BootstrapState>("/api/plot-mode", {
          method: "DELETE",
          body: JSON.stringify({ id: normalizedSessionId }),
        });

        if (isCurrentWorkspaceNavigationRequest(requestId)) {
          applyBootstrapPayload(payload);
          setPlotVersion((value) => value + 1);
        } else {
          applyBootstrapSummariesOnly(payload);
        }
        setError(null);
        return payload;
      }

      const payload = await fetchJSON<BootstrapState>(
        `/api/sessions/${encodeURIComponent(workspace?.session_id || normalizedSessionId)}`,
        {
          method: "DELETE",
        },
      );

      if (isCurrentWorkspaceNavigationRequest(requestId)) {
        applyBootstrapPayload(payload);
        setPlotVersion((value) => value + 1);
      } else {
        applyBootstrapSummariesOnly(payload);
      }
      setError(null);
      return payload;
    },
    [
      applyBootstrapPayload,
      applyBootstrapSummariesOnly,
      beginWorkspaceNavigationRequest,
      isCurrentWorkspaceNavigationRequest,
    ],
  );

  // --- Handle WebSocket events ---

  const handleWsEvent = useCallback((event: WsEvent) => {
    const eventSessionId = "session_id" in event ? event.session_id?.trim() || null : null;
    const isCurrentSessionEvent =
      eventSessionId === null || !activeSessionId || eventSessionId === activeSessionId;

    switch (event.type) {
      case "plot_updated":
        if (mode !== "annotation" || !isCurrentSessionEvent) {
          break;
        }
        setPlotVersion((v) => v + 1);
        refresh();
        break;
      case "annotation_added":
      case "annotation_deleted":
      case "annotation_updated":
        if (mode !== "annotation" || !isCurrentSessionEvent) {
          break;
        }
        refresh();
        break;
      case "fix_job_updated":
        if (!activeSessionId || event.job.session_id !== activeSessionId) {
          break;
        }
        setFixJob((current) => mergeFixJobSnapshot(current, event.job));
        break;
      case "fix_job_log": {
        if (!shouldStoreFixLogEvent(event)) {
          break;
        }

        const stepKey = `${event.job_id}:${event.step_index}`;
        setFixStepLogsByKey((previous) => {
          const existing = previous[stepKey] || [];
          const nextEntries =
            existing.length + 1 > MAX_FIX_STEP_LOG_EVENTS
              ? [...existing.slice(-(MAX_FIX_STEP_LOG_EVENTS - 1)), event]
              : [...existing, event];
          return {
            ...previous,
            [stepKey]: nextEntries,
          };
        });
        break;
      }
      case "plot_mode_updated":
        if (
          shouldApplyPlotModeWorkspaceUpdate({
            activeWorkspaceId,
            incomingWorkspaceId: event.plot_mode.id,
            mode,
            visiblePlotModeId: plotModeRef.current?.id ?? null,
          })
        ) {
          if (
            event.plot_mode.current_plot &&
            plotModeRef.current?.current_plot !== event.plot_mode.current_plot
          ) {
            setPlotVersion((value) => value + 1);
          }
          setMode("plot");
          setSession(null);
          setActiveSessionId(null);
          setActiveWorkspaceId(event.plot_mode.id);
          setPlotMode(event.plot_mode);
        }
        setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(event.plot_mode)));
        break;
      case "plot_mode_message_updated": {
        const shouldApplyUpdate = shouldApplyPlotModeWorkspaceUpdate({
          activeWorkspaceId,
          incomingWorkspaceId: event.plot_mode_id,
          mode,
          visiblePlotModeId: plotModeRef.current?.id ?? null,
        });
        if (shouldApplyUpdate) {
          const nextPlotMode = upsertPlotModeMessage(
            plotModeRef.current,
            event.plot_mode_id,
            event.updated_at,
            event.message,
          );
          if (!nextPlotMode) {
            break;
          }
          setMode("plot");
          setSession(null);
          setActiveSessionId(null);
          setActiveWorkspaceId(nextPlotMode.id);
          setPlotMode(nextPlotMode);
          setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(nextPlotMode)));
          break;
        }
        setSessions((previous) => touchWorkspaceSummary(previous, event.plot_mode_id, event.updated_at));
        break;
      }
      case "plot_mode_completed": {
        const completedWorkspaceId = event.session.workspace_id || event.session.id;
        const shouldActivateCompletedWorkspace = shouldActivateCompletedPlotWorkspace({
          activeWorkspaceId,
          completedWorkspaceId,
          mode,
          visiblePlotModeId: plotModeRef.current?.id ?? null,
        });

        if (shouldActivateCompletedWorkspace) {
          setMode("annotation");
          setSession(event.session);
          setActiveSessionId(event.session.id);
          setActiveWorkspaceId(completedWorkspaceId);
          setPlotMode(null);
          setPlotVersion((value) => value + 1);
        }
        setSessions((previous) => {
          const summary = toSessionSummary(event.session);
          return upsertWorkspaceSummary(removeWorkspaceSummary(previous, completedWorkspaceId), summary);
        });
        break;
      }
    }
  }, [activeSessionId, activeWorkspaceId, mode, refresh]);

  return {
    mode,
    session,
    sessions,
    activeSessionId,
    activeWorkspaceId,
    plotMode,
    loading,
    error,
    selectedRunner,
    setSelectedRunner,
    availableRunners,
    backendFatalError,
    opencodeModels,
    defaultOpencodeModel,
    defaultOpencodeVariant,
    opencodeModelsLoading,
    opencodeModelsError,
    pythonInterpreter,
    pythonInterpreterLoading,
    pythonInterpreterError,
    fixJob,
    fixStepLogsByKey,
    plotVersion,
    refresh,
    refreshRunnerAvailability,
    refreshRunnerModels,
    refreshFixJob,
    refreshPythonInterpreter,
    addAnnotation,
    deleteAnnotation,
    updateAnnotation,
    checkoutVersion,
    switchBranch,
    renameBranch,
    downloadAnnotationPlot,
    downloadPlotModeWorkspace,
    startFixJob,
    cancelFixJob,
    updateFixPreferences,
    setPythonInterpreterPreference,
    fetchPlotModePathSuggestions,
    selectPlotModePaths,
    submitPlotModeTabularHint,
    sendPlotModeMessage,
    updatePlotModeExecutionMode,
    answerPlotModeQuestion,
    finalizePlotMode,
    createNewSession,
    activateSession,
    renameWorkspace,
    deleteWorkspace,
    handleWsEvent,
  };
}
