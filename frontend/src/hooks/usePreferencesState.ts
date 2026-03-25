import { useCallback, useState } from "react";

import { fetchPreferences, updateFixPreferences as updateFixPreferencesRequest } from "../api/preferences";
import type { FixRunner } from "../types";

function normalizeRunner(value: unknown): FixRunner {
  if (value === "codex") {
    return "codex";
  }
  if (value === "claude") {
    return "claude";
  }
  return "opencode";
}

export function usePreferencesState() {
  const [selectedRunner, setSelectedRunner] = useState<FixRunner>("opencode");

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

    await updateFixPreferencesRequest(body as {
      fix_runner: FixRunner;
      fix_model?: string | null;
      fix_variant?: string | null;
    });
  }, []);

  const refreshFixPreferences = useCallback(async () => {
    try {
      const payload = await fetchPreferences();
      setSelectedRunner(normalizeRunner(payload.fix_runner));
    } catch {
      // Keep the current runner rather than forcing "opencode".
    }
  }, []);

  const reconcileSelectedRunner = useCallback((availableRunners: FixRunner[]) => {
    if (availableRunners.length === 0 || availableRunners.includes(selectedRunner)) {
      return;
    }
    const corrected = availableRunners[0];
    setSelectedRunner(corrected);
    void updateFixPreferences(corrected, null, null).catch(() => {});
  }, [selectedRunner, updateFixPreferences]);

  return {
    selectedRunner,
    setSelectedRunner,
    refreshFixPreferences,
    updateFixPreferences,
    reconcileSelectedRunner,
  };
}
