import type { BootstrapState, SessionSummary } from "../types";
import { fetchJSON } from "./client";

export function fetchBootstrap() {
  return fetchJSON<BootstrapState>("/api/bootstrap");
}

export function createSession() {
  return fetchJSON<BootstrapState>("/api/sessions/new", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function activateAnnotationSession(sessionId: string) {
  return fetchJSON<BootstrapState>(`/api/sessions/${encodeURIComponent(sessionId)}/activate`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function updateAnnotationWorkspace(sessionId: string, workspaceName: string) {
  return fetchJSON<{
    status: string;
    workspace: SessionSummary;
    active_session_id: string | null;
  }>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    body: JSON.stringify({ workspace_name: workspaceName }),
  });
}

export function deleteAnnotationWorkspace(sessionId: string) {
  return fetchJSON<BootstrapState>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}
