import type { FixRunner, OpencodeModelOption, RunnerStatusState } from "../types";
import { fetchJSON } from "./client";

export function fetchRunnerStatus() {
  return fetchJSON<RunnerStatusState>("/api/runners/status");
}

export function installRunner(runner: FixRunner) {
  return fetchJSON<{ job: { id: string } }>("/api/runners/install", {
    method: "POST",
    body: JSON.stringify({ runner }),
  });
}

export function launchRunnerAuth(runner: FixRunner) {
  return fetchJSON<{ status: string }>("/api/runners/auth/launch", {
    method: "POST",
    body: JSON.stringify({ runner }),
  });
}

export function fetchRunnerModels(runner: FixRunner) {
  return fetchJSON<{
    runner: FixRunner;
    models: OpencodeModelOption[];
    default_model: string;
    default_variant: string;
  }>(`/api/runners/models?runner=${runner}`);
}
