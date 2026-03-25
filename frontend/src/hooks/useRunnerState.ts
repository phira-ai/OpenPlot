import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchRunnerModels as fetchRunnerModelsRequest,
  fetchRunnerStatus,
  installRunner as installRunnerRequest,
  launchRunnerAuth as launchRunnerAuthRequest,
} from "../api/runners";
import {
  fetchPythonInterpreter,
  openExternalUrl as openExternalUrlRequest,
  refreshUpdateStatus as refreshUpdateStatusRequest,
  updatePythonInterpreter,
} from "../api/runtime";
import { asErrorMessage } from "../lib/errors";
import type {
  FixRunner,
  OpencodeModelOption,
  PythonInterpreterMode,
  PythonInterpreterState,
  RunnerStatusState,
  UpdateStatusState,
} from "../types";

interface UseRunnerStateOptions {
  selectedRunner: FixRunner;
}

export function useRunnerState({ selectedRunner }: UseRunnerStateOptions) {
  const [availableRunners, setAvailableRunners] = useState<FixRunner[]>([]);
  const [runnerStatus, setRunnerStatus] = useState<RunnerStatusState | null>(null);
  const [runnerStatusLoading, setRunnerStatusLoading] = useState(true);
  const [runnerStatusError, setRunnerStatusError] = useState<string | null>(null);
  const [backendFatalError, setBackendFatalError] = useState<string | null>(null);
  const [opencodeModels, setOpencodeModels] = useState<OpencodeModelOption[]>([]);
  const [defaultOpencodeModel, setDefaultOpencodeModel] = useState("");
  const [defaultOpencodeVariant, setDefaultOpencodeVariant] = useState("");
  const [opencodeModelsLoading, setOpencodeModelsLoading] = useState(true);
  const [opencodeModelsError, setOpencodeModelsError] = useState<string | null>(null);
  const [pythonInterpreter, setPythonInterpreter] = useState<PythonInterpreterState | null>(null);
  const [pythonInterpreterLoading, setPythonInterpreterLoading] = useState(true);
  const [pythonInterpreterError, setPythonInterpreterError] = useState<string | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatusState | null>(null);
  const [updateStatusLoading, setUpdateStatusLoading] = useState(false);
  const runnerStatusRequestIdRef = useRef(0);
  const runnerModelsRequestIdRef = useRef(0);
  const runnerStatusRef = useRef<RunnerStatusState | null>(null);

  const refreshRunnerAvailability = useCallback(async () => {
    const requestId = runnerStatusRequestIdRef.current + 1;
    runnerStatusRequestIdRef.current = requestId;

    setRunnerStatusLoading(true);
    try {
      const payload = await fetchRunnerStatus();
      if (runnerStatusRequestIdRef.current !== requestId) {
        return;
      }

      const available = Array.isArray(payload.available_runners)
        ? payload.available_runners.filter(
            (runner): runner is FixRunner =>
              runner === "opencode" || runner === "codex" || runner === "claude",
          )
        : [];
      setRunnerStatus(payload);
      setAvailableRunners(available);
      setRunnerStatusError(null);
      setBackendFatalError(null);
      if (available.length === 0) {
        setBackendFatalError(
          "At least one backend CLI must exist: codex, claude code, opencode.",
        );
        setOpencodeModelsLoading(false);
      }
    } catch (err: unknown) {
      if (runnerStatusRequestIdRef.current !== requestId) {
        return;
      }

      const message = asErrorMessage(err, "Failed to detect available backend CLIs");
      setRunnerStatusError(message);
      if (!runnerStatusRef.current) {
        setRunnerStatus(null);
        setAvailableRunners([]);
        setBackendFatalError(message);
      } else {
        setBackendFatalError(null);
      }
      setOpencodeModelsLoading(false);
    } finally {
      if (runnerStatusRequestIdRef.current === requestId) {
        setRunnerStatusLoading(false);
      }
    }
  }, []);

  const installRunner = useCallback(async (runner: FixRunner) => {
    await installRunnerRequest(runner);
    await refreshRunnerAvailability();
  }, [refreshRunnerAvailability]);

  const launchRunnerAuth = useCallback(async (runner: FixRunner) => {
    await launchRunnerAuthRequest(runner);
  }, []);

  const openExternalUrl = useCallback(async (url: string) => {
    await openExternalUrlRequest(url);
  }, []);

  const refreshUpdateStatus = useCallback(async () => {
    setUpdateStatusLoading(true);
    try {
      const payload = await refreshUpdateStatusRequest();
      setUpdateStatus(payload);
      return payload;
    } catch (err: unknown) {
      const message = asErrorMessage(err, "Failed to check for updates");
      setUpdateStatus((current) => ({
        current_version: current?.current_version ?? "",
        latest_version: current?.latest_version ?? null,
        latest_release_url:
          current?.latest_release_url ?? "https://github.com/phira-ai/OpenPlot/releases/latest",
        update_available: current?.update_available ?? false,
        checked_at: current?.checked_at ?? null,
        error: message,
      }));
      throw err;
    } finally {
      setUpdateStatusLoading(false);
    }
  }, []);

  const refreshRunnerModels = useCallback(async (runner: FixRunner) => {
    const requestId = runnerModelsRequestIdRef.current + 1;
    runnerModelsRequestIdRef.current = requestId;

    setOpencodeModelsLoading(true);
    try {
      const payload = await fetchRunnerModelsRequest(runner);

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
      setOpencodeModelsError(asErrorMessage(err, `Failed to load models from ${runner}`));
    } finally {
      if (runnerModelsRequestIdRef.current === requestId) {
        setOpencodeModelsLoading(false);
      }
    }
  }, []);

  const refreshPythonInterpreter = useCallback(async () => {
    setPythonInterpreterLoading(true);
    try {
      const payload = await fetchPythonInterpreter();
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

  const setPythonInterpreterPreference = useCallback(
    async (mode: PythonInterpreterMode, path?: string) => {
      const payload = await updatePythonInterpreter(mode, path);
      setPythonInterpreter(payload);
      setPythonInterpreterError(null);
      return payload;
    },
    [],
  );

  useEffect(() => {
    runnerStatusRef.current = runnerStatus;
  }, [runnerStatus]);

  useEffect(() => {
    void refreshRunnerAvailability();
    void refreshPythonInterpreter();
  }, [refreshPythonInterpreter, refreshRunnerAvailability]);

  useEffect(() => {
    if (!runnerStatus?.active_install_job_id) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void refreshRunnerAvailability();
    }, 2000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [refreshRunnerAvailability, runnerStatus?.active_install_job_id]);

  useEffect(() => {
    runnerModelsRequestIdRef.current += 1;
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

  return {
    availableRunners,
    runnerStatus,
    runnerStatusLoading,
    runnerStatusError,
    backendFatalError,
    opencodeModels,
    defaultOpencodeModel,
    defaultOpencodeVariant,
    opencodeModelsLoading,
    opencodeModelsError,
    pythonInterpreter,
    pythonInterpreterLoading,
    pythonInterpreterError,
    updateStatus,
    setUpdateStatus,
    updateStatusLoading,
    refreshRunnerAvailability,
    installRunner,
    launchRunnerAuth,
    openExternalUrl,
    refreshUpdateStatus,
    refreshRunnerModels,
    refreshPythonInterpreter,
    setPythonInterpreterPreference,
  };
}
