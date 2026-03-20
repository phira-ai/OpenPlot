import type { FixRunner } from "../types";

export function runnerLabel(runner: FixRunner): string {
  if (runner === "codex") {
    return "Codex";
  }
  if (runner === "claude") {
    return "Claude Code";
  }
  return "OpenCode";
}
