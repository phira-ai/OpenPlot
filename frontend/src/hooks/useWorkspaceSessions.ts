import { useCallback, useEffect, useRef, useState } from "react";

import type { AppMode, BootstrapState, PlotModeChatMessage, PlotModeState, PlotSession, SessionSummary } from "../types";

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

export function toSessionSummary(session: PlotSession): SessionSummary {
  const name = session.workspace_name?.trim() || defaultWorkspaceName(session.created_at);
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

export function normalizeSessionSummary(summary: SessionSummary): SessionSummary {
  const name = summary.workspace_name?.trim() || defaultWorkspaceName(summary.created_at);
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

export function toPlotModeWorkspaceSummary(plotMode: PlotModeState): SessionSummary {
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

export function sortWorkspaceSummaries(items: SessionSummary[]): SessionSummary[] {
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

export function upsertWorkspaceSummary(
  current: SessionSummary[],
  summary: SessionSummary,
): SessionSummary[] {
  const normalized = normalizeSessionSummary(summary);
  const remaining = current.filter((entry) => entry.id !== normalized.id);
  return sortWorkspaceSummaries([normalized, ...remaining]);
}

export function removeWorkspaceSummary(current: SessionSummary[], workspaceId: string): SessionSummary[] {
  return current.filter((entry) => entry.id !== workspaceId);
}

export function touchWorkspaceSummary(
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

export function upsertPlotModeMessage(
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

export function useWorkspaceSessions() {
  const [mode, setMode] = useState<AppMode>("plot");
  const [session, setSession] = useState<PlotSession | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);
  const [plotMode, setPlotMode] = useState<PlotModeState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [plotVersion, setPlotVersion] = useState(0);
  const activeWorkspaceIdRef = useRef<string | null>(null);
  const modeRef = useRef<AppMode>("plot");
  const plotModeRef = useRef<PlotModeState | null>(null);
  const sessionsRef = useRef<SessionSummary[]>([]);

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
      setActiveWorkspaceId(payload.session?.workspace_id ?? payload.session?.id ?? null);
    } else {
      setActiveWorkspaceId(payload.plot_mode?.id ?? null);
    }

    if (payload.mode === "annotation") {
      setMode("annotation");
      setSession(payload.session ?? null);
      setPlotMode(null);
      return;
    }

    setMode("plot");
    setSession(null);
    setPlotMode(payload.plot_mode ?? null);
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

  return {
    mode,
    setMode,
    session,
    setSession,
    sessions,
    setSessions,
    activeSessionId,
    setActiveSessionId,
    activeWorkspaceId,
    setActiveWorkspaceId,
    plotMode,
    setPlotMode,
    loading,
    setLoading,
    error,
    setError,
    plotVersion,
    setPlotVersion,
    activeWorkspaceIdRef,
    modeRef,
    plotModeRef,
    sessionsRef,
    applyBootstrapPayload,
    applyBootstrapSummariesOnly,
  };
}
