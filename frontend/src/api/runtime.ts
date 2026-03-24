import type { PythonInterpreterMode, PythonInterpreterState, UpdateStatusState } from "../types";
import { fetchJSON } from "./client";

export function openExternalUrl(url: string) {
  return fetchJSON<{ status: string }>("/api/open-external-url", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

export function refreshUpdateStatus() {
  return fetchJSON<UpdateStatusState>("/api/update-status/refresh", {
    method: "POST",
  });
}

export function fetchPythonInterpreter() {
  return fetchJSON<PythonInterpreterState>("/api/python/interpreter");
}

export function updatePythonInterpreter(mode: PythonInterpreterMode, path?: string) {
  const body: Record<string, string> = { mode };
  if (mode === "manual") {
    body.path = path?.trim() || "";
  }
  return fetchJSON<PythonInterpreterState>("/api/python/interpreter", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
