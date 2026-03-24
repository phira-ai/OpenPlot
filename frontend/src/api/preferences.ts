import type { FixRunner } from "../types";
import { fetchJSON } from "./client";

export function fetchPreferences() {
  return fetchJSON<{
    fix_runner?: FixRunner;
  }>("/api/preferences");
}

export function updateFixPreferences(body: {
  fix_runner: FixRunner;
  fix_model?: string | null;
  fix_variant?: string | null;
}) {
  return fetchJSON<{
    status: string;
    fix_runner: FixRunner;
    fix_model: string | null;
    fix_variant: string | null;
  }>("/api/preferences", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
