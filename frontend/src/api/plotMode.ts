import type {
  BootstrapState,
  PlotModeExecutionMode,
  PlotModePathSelectionType,
  PlotModePathSuggestionResponse,
  PlotModeState,
} from "../types";
import { fetchJSON } from "./client";

export function activatePlotWorkspace(id: string) {
  return fetchJSON<BootstrapState>("/api/plot-mode/activate", {
    method: "POST",
    body: JSON.stringify({ id }),
  });
}

export function fetchPlotModePathSuggestions(
  workspaceId: string | null,
  query: string,
  selectionType: PlotModePathSelectionType,
) {
  return fetchJSON<PlotModePathSuggestionResponse>("/api/plot-mode/path-suggestions", {
    method: "POST",
    body: JSON.stringify({
      query,
      selection_type: selectionType,
      workspace_id: workspaceId,
    }),
  });
}

export function selectPlotModePaths(
  workspaceId: string | null,
  selectionType: PlotModePathSelectionType,
  paths: string[],
) {
  return fetchJSON<BootstrapState>("/api/plot-mode/select-paths", {
    method: "POST",
    body: JSON.stringify({
      selection_type: selectionType,
      paths,
      workspace_id: workspaceId,
    }),
  });
}

export function sendPlotModeMessage(body: Record<string, string>) {
  return fetchJSON<{
    status: "ok" | "error";
    plot_mode: PlotModeState;
    error?: string;
  }>("/api/plot-mode/chat", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function submitPlotModeTabularHint(body: Record<string, unknown>) {
  return fetchJSON<{
    status: "ok";
    plot_mode: PlotModeState;
  }>("/api/plot-mode/tabular-hint", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updatePlotModeSettings(
  workspaceId: string | null,
  executionMode: PlotModeExecutionMode,
) {
  return fetchJSON<{
    status: "ok";
    plot_mode: PlotModeState;
  }>("/api/plot-mode/settings", {
    method: "PATCH",
    body: JSON.stringify({ execution_mode: executionMode, workspace_id: workspaceId }),
  });
}

export function answerPlotModeQuestion(body: Record<string, unknown>) {
  return fetchJSON<{
    status: "ok";
    plot_mode: PlotModeState;
  }>("/api/plot-mode/answer", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function finalizePlotMode(
  workspaceId: string | null,
  metadata?: Record<string, string | null>,
) {
  return fetchJSON<BootstrapState>("/api/plot-mode/finalize", {
    method: "POST",
    body: JSON.stringify({ ...(metadata ?? {}), workspace_id: workspaceId }),
  });
}

export function updatePlotWorkspace(id: string, workspaceName: string) {
  return fetchJSON<{
    status: string;
    plot_mode: PlotModeState;
  }>("/api/plot-mode/workspace", {
    method: "PATCH",
    body: JSON.stringify({ id, workspace_name: workspaceName }),
  });
}

export function deletePlotWorkspace(id: string) {
  return fetchJSON<BootstrapState>("/api/plot-mode", {
    method: "DELETE",
    body: JSON.stringify({ id }),
  });
}
