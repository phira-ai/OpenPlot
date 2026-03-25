import type { FixJob, FixRunner } from "../types";
import { fetchJSON } from "./client";

export function fetchCurrentFixJob(sessionId: string) {
  return fetchJSON<{ job: FixJob | null }>(
    `/api/fix-jobs/current?session_id=${encodeURIComponent(sessionId)}`,
  );
}

export function startFixJob(
  runner: FixRunner,
  model: string,
  variant: string | null,
  sessionId: string | null,
) {
  return fetchJSON<{ status: string; job: FixJob }>("/api/fix-jobs", {
    method: "POST",
    body: JSON.stringify({
      runner,
      model,
      variant,
      session_id: sessionId,
    }),
  });
}

export function cancelFixJob(jobId: string) {
  return fetchJSON<{ status: string; job: FixJob }>(`/api/fix-jobs/${jobId}/cancel`, {
    method: "POST",
  });
}
