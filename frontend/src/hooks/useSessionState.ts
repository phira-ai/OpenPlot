import { useCallback, useEffect, useRef } from "react";

import {
  createAnnotation,
  deleteAnnotation as deleteAnnotationRequest,
  updateAnnotation as updateAnnotationRequest,
} from "../api/annotations";
import { downloadAnnotationArtifact } from "../api/artifacts";
import {
  activatePlotWorkspace,
  deletePlotWorkspace,
  updatePlotWorkspace,
} from "../api/plotMode";
import {
  activateAnnotationSession,
  createSession,
  deleteAnnotationWorkspace,
  fetchBootstrap,
  updateAnnotationWorkspace,
} from "../api/sessions";
import {
  checkoutBranch,
  checkoutVersion as checkoutVersionRequest,
  renameBranch as renameBranchRequest,
} from "../api/versioning";
import { asErrorMessage } from "../lib/errors";
import {
  shouldActivateCompletedPlotWorkspace,
  shouldApplyPlotModeWorkspaceResponse,
  shouldApplyPlotModeWorkspaceUpdate,
} from "../lib/plotModeUi";
import type {
  Annotation,
  BootstrapState,
  FixRunner,
  PlotModeQuestionAnswerInput,
  PlotModeExecutionMode,
  PlotModePathSelectionType,
  PlotModeState,
  PlotModeTabularHintRegionInput,
  WsEvent,
} from "../types";
import { useFixJobState } from "./useFixJobState";
import { usePlotModeState } from "./usePlotModeState";
import { usePreferencesState } from "./usePreferencesState";
import { useRunnerState } from "./useRunnerState";
import {
  normalizeSessionSummary,
  removeWorkspaceSummary,
  toPlotModeWorkspaceSummary,
  toSessionSummary,
  touchWorkspaceSummary,
  upsertPlotModeMessage,
  upsertWorkspaceSummary,
  useWorkspaceSessions,
} from "./useWorkspaceSessions";

function extractFileNameFromDisposition(disposition: string | null): string | null {
  if (!disposition) {
    return null;
  }

  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1]);
  }

  const quotedMatch = disposition.match(/filename="([^"]+)"/i);
  if (quotedMatch?.[1]) {
    return quotedMatch[1];
  }

  const bareMatch = disposition.match(/filename=([^;]+)/i);
  if (bareMatch?.[1]) {
    return bareMatch[1].trim();
  }

  return null;
}

export function useSessionState() {
  const workspaceState = useWorkspaceSessions();
  const preferencesState = usePreferencesState();
  const runnerState = useRunnerState({ selectedRunner: preferencesState.selectedRunner });
  const {
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
    applyBootstrapPayload: applyWorkspaceBootstrapPayload,
    applyBootstrapSummariesOnly: applyWorkspaceBootstrapSummariesOnly,
  } = workspaceState;
  const {
    selectedRunner,
    setSelectedRunner,
    refreshFixPreferences,
    updateFixPreferences,
    reconcileSelectedRunner,
  } = preferencesState;
  const {
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
  } = runnerState;
  const fixJobState = useFixJobState({ activeSessionId });
  const {
    fixJob,
    fixStepLogsByKey,
    refreshFixJob,
    startFixJob,
    cancelFixJob,
    applyFixJobUpdate,
    appendFixJobLog,
    setFixJob,
  } = fixJobState;
  const workspaceNavigationRequestIdRef = useRef(0);

  const applyBootstrapPayload = useCallback((payload: BootstrapState) => {
    applyWorkspaceBootstrapPayload(payload);
    if ("update_status" in payload) {
      setUpdateStatus(payload.update_status ?? null);
    }
  }, [applyWorkspaceBootstrapPayload, setUpdateStatus]);

  const applyBootstrapSummariesOnly = useCallback((payload: BootstrapState) => {
    applyWorkspaceBootstrapSummariesOnly(payload);
    if ("update_status" in payload) {
      setUpdateStatus(payload.update_status ?? null);
    }
  }, [applyWorkspaceBootstrapSummariesOnly, setUpdateStatus]);

  const beginWorkspaceNavigationRequest = useCallback(() => {
    const requestId = workspaceNavigationRequestIdRef.current + 1;
    workspaceNavigationRequestIdRef.current = requestId;
    return requestId;
  }, []);

  const isCurrentWorkspaceNavigationRequest = useCallback(
    (requestId: number) => workspaceNavigationRequestIdRef.current === requestId,
    [],
  );

  const refresh = useCallback(async () => {
    const requestId = workspaceNavigationRequestIdRef.current;
    try {
      const payload = await fetchBootstrap();
      if (workspaceNavigationRequestIdRef.current === requestId) {
        applyBootstrapPayload(payload);
      } else {
        applyBootstrapSummariesOnly(payload);
      }
      setError(null);
    } catch (err: unknown) {
      if (workspaceNavigationRequestIdRef.current === requestId) {
        setError(asErrorMessage(err, "Failed to fetch bootstrap state"));
      }
    } finally {
      setLoading(false);
    }
  }, [applyBootstrapPayload, applyBootstrapSummariesOnly, setError, setLoading]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    void refreshFixPreferences();
  }, [refreshFixPreferences]);

  useEffect(() => {
    reconcileSelectedRunner(availableRunners);
  }, [availableRunners, reconcileSelectedRunner]);

  const addAnnotation = useCallback(async (annotation: Partial<Annotation>) => {
    const result = await createAnnotation(annotation);
    await refresh();
    return result;
  }, [refresh]);

  const deleteAnnotation = useCallback(async (id: string) => {
    await deleteAnnotationRequest(id);
    await refresh();
  }, [refresh]);

  const updateAnnotation = useCallback(async (id: string, updates: Partial<Annotation>) => {
    await updateAnnotationRequest(id, updates);
    await refresh();
  }, [refresh]);

  const checkoutVersion = useCallback(async (versionId: string, branchId?: string) => {
    await checkoutVersionRequest(versionId, branchId);
    await refresh();
    setPlotVersion((value) => value + 1);
  }, [refresh, setPlotVersion]);

  const switchBranch = useCallback(async (branchId: string) => {
    await checkoutBranch(branchId);
    await refresh();
    setPlotVersion((value) => value + 1);
  }, [refresh, setPlotVersion]);

  const renameBranch = useCallback(async (branchId: string, name: string) => {
    const normalizedBranchId = branchId.trim();
    const normalizedName = name.trim();
    if (!normalizedBranchId) {
      throw new Error("Missing branch id");
    }
    if (!normalizedName) {
      throw new Error("Branch name cannot be empty");
    }

    const payload = await renameBranchRequest(normalizedBranchId, normalizedName);

    setFixJob((current) => {
      if (!current || current.branch_id !== payload.branch.id) {
        return current;
      }
      return {
        ...current,
        branch_name: payload.branch.name,
      };
    });

    await refresh();
    return payload.branch;
  }, [refresh, setFixJob]);

  const downloadAnnotationPlot = useCallback(async (annotationId: string) => {
    const res = await downloadAnnotationArtifact(annotationId);
    const blob = await res.blob();
    const contentDisposition = res.headers.get("Content-Disposition");
    const inferred = extractFileNameFromDisposition(contentDisposition);
    const fileName = inferred || `annotation-${annotationId}.zip`;

    return { blob, fileName };
  }, []);

  const shouldApplyPlotResponse = useCallback(
    (requestWorkspaceId: string | null, responseWorkspaceId: string) =>
      shouldApplyPlotModeWorkspaceResponse({
        activeWorkspaceId: activeWorkspaceIdRef.current,
        requestWorkspaceId,
        responseWorkspaceId,
        mode: modeRef.current,
        visiblePlotModeId: plotModeRef.current?.id ?? null,
      }),
    [activeWorkspaceIdRef, modeRef, plotModeRef],
  );

  const shouldApplyCompletedPlotResponse = useCallback(
    (requestWorkspaceId: string | null) =>
      requestWorkspaceId != null &&
      modeRef.current === "plot" &&
      activeWorkspaceIdRef.current === requestWorkspaceId &&
      plotModeRef.current?.id === requestWorkspaceId,
    [activeWorkspaceIdRef, modeRef, plotModeRef],
  );

  const plotModeState = usePlotModeState({
    plotModeRef,
  });

  const applyVisiblePlotModeResponse = useCallback((plotModePayload: PlotModeState) => {
    setMode("plot");
    setSession(null);
    setActiveSessionId(null);
    setActiveWorkspaceId(plotModePayload.id);
    setPlotMode(plotModePayload);
  }, [setActiveSessionId, setActiveWorkspaceId, setMode, setPlotMode, setSession]);

  const reconcilePlotModePayload = useCallback(
    (requestWorkspaceId: string | null, payload: BootstrapState) => {
      const shouldApplyResponse =
        payload.mode === "plot" &&
        payload.plot_mode != null &&
        shouldApplyPlotResponse(requestWorkspaceId, payload.plot_mode.id);
      const shouldApplyCompletionResponse =
        requestWorkspaceId != null &&
        payload.mode === "annotation" &&
        shouldApplyCompletedPlotResponse(requestWorkspaceId);

      if (shouldApplyResponse || shouldApplyCompletionResponse) {
        applyBootstrapPayload(payload);
      } else if (Array.isArray(payload.sessions)) {
        applyBootstrapSummariesOnly(payload);
      } else if (payload.mode === "plot" && payload.plot_mode) {
        setSessions((previous) =>
          upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(payload.plot_mode!)),
        );
      }

      return { shouldApplyResponse };
    },
    [
      applyBootstrapPayload,
      applyBootstrapSummariesOnly,
      setSessions,
      shouldApplyCompletedPlotResponse,
      shouldApplyPlotResponse,
    ],
  );

  const fetchPlotModePathSuggestions = useCallback(
    async (workspaceId: string | null, query: string, selectionType: PlotModePathSelectionType) => {
      return await plotModeState.fetchPlotModePathSuggestions(workspaceId, query, selectionType);
    },
    [plotModeState],
  );

  const selectPlotModePaths = useCallback(
    async (
      workspaceId: string | null,
      selectionType: PlotModePathSelectionType,
      paths: string[],
    ) => {
      const previousPlotPath = plotModeRef.current?.current_plot ?? null;
      const payload = await plotModeState.selectPlotModePaths(workspaceId, selectionType, paths);
      if (!payload) {
        return;
      }

      const { shouldApplyResponse } = reconcilePlotModePayload(workspaceId, payload);
      setError(null);
      if (
        shouldApplyResponse &&
        payload.mode === "plot" &&
        payload.plot_mode?.current_plot &&
        previousPlotPath !== payload.plot_mode.current_plot
      ) {
        setPlotVersion((value) => value + 1);
      }
    },
    [plotModeRef, plotModeState, reconcilePlotModePayload, setError, setPlotVersion],
  );

  const sendPlotModeMessage = useCallback(
    async (
      workspaceId: string | null,
      message: string,
      runner?: FixRunner,
      model?: string,
      variant?: string,
    ) => {
      const previousPlotPath = plotModeRef.current?.current_plot ?? null;
      const payload = await plotModeState.sendPlotModeMessage(
        workspaceId,
        message,
        runner,
        model,
        variant,
      );

      const shouldApplyResponse = shouldApplyPlotResponse(workspaceId, payload.plot_mode.id);
      if (shouldApplyResponse) {
        applyVisiblePlotModeResponse(payload.plot_mode);
      }
      setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(payload.plot_mode)));
      setError(null);
      if (
        shouldApplyResponse &&
        payload.plot_mode.current_plot &&
        previousPlotPath !== payload.plot_mode.current_plot
      ) {
        setPlotVersion((value) => value + 1);
      }

      if (payload.status === "error") {
        throw new Error(payload.error || "Plot generation failed");
      }

      return payload;
    },
    [
      applyVisiblePlotModeResponse,
      plotModeRef,
      plotModeState,
      setError,
      setPlotVersion,
      setSessions,
      shouldApplyPlotResponse,
    ],
  );

  const submitPlotModeTabularHint = useCallback(
    async (
      workspaceId: string | null,
      selectorId: string,
      regions: PlotModeTabularHintRegionInput[],
      note: string,
      runner?: FixRunner,
      model?: string,
      variant?: string,
    ) => {
      const payload = await plotModeState.submitPlotModeTabularHint(
        workspaceId,
        selectorId,
        regions,
        note,
        runner,
        model,
        variant,
      );

      if (shouldApplyPlotResponse(workspaceId, payload.plot_mode.id)) {
        applyVisiblePlotModeResponse(payload.plot_mode);
      }
      setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(payload.plot_mode)));
      setError(null);
      return payload;
    },
    [applyVisiblePlotModeResponse, plotModeState, setError, setSessions, shouldApplyPlotResponse],
  );

  const updatePlotModeExecutionMode = useCallback(
    async (workspaceId: string | null, executionMode: PlotModeExecutionMode) => {
      const payload = await plotModeState.updatePlotModeExecutionMode(workspaceId, executionMode);

      if (shouldApplyPlotResponse(workspaceId, payload.plot_mode.id)) {
        applyVisiblePlotModeResponse(payload.plot_mode);
      }
      setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(payload.plot_mode)));
      setError(null);
      return payload;
    },
    [applyVisiblePlotModeResponse, plotModeState, setError, setSessions, shouldApplyPlotResponse],
  );

  const answerPlotModeQuestion = useCallback(
    async (
      workspaceId: string | null,
      questionSetId: string,
      answers: PlotModeQuestionAnswerInput[],
      runner?: FixRunner,
      model?: string,
      variant?: string,
    ) => {
      const payload = await plotModeState.answerPlotModeQuestion(
        workspaceId,
        questionSetId,
        answers,
        runner,
        model,
        variant,
      );

      if (shouldApplyPlotResponse(workspaceId, payload.plot_mode.id)) {
        applyVisiblePlotModeResponse(payload.plot_mode);
      }
      setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(payload.plot_mode)));
      setError(null);
      return payload;
    },
    [applyVisiblePlotModeResponse, plotModeState, setError, setSessions, shouldApplyPlotResponse],
  );

  const finalizePlotMode = useCallback(
    async (workspaceId: string | null, metadata?: Record<string, string | null>) => {
      const payload = await plotModeState.finalizePlotMode(workspaceId, metadata);

      if (workspaceId != null && payload.mode === "annotation" && shouldApplyCompletedPlotResponse(workspaceId)) {
        applyBootstrapPayload(payload);
        setPlotVersion((value) => value + 1);
      } else if (Array.isArray(payload.sessions)) {
        applyBootstrapSummariesOnly(payload);
      }
      setError(null);
      return payload;
    },
    [
      applyBootstrapPayload,
      applyBootstrapSummariesOnly,
      plotModeState,
      setError,
      setPlotVersion,
      shouldApplyCompletedPlotResponse,
    ],
  );

  const createNewSession = useCallback(async () => {
    const requestId = beginWorkspaceNavigationRequest();
    const payload = await createSession();

    if (isCurrentWorkspaceNavigationRequest(requestId)) {
      applyBootstrapPayload(payload);
      setPlotVersion((value) => value + 1);
    } else {
      applyBootstrapSummariesOnly(payload);
    }
    setError(null);
    return payload;
  }, [
    applyBootstrapPayload,
    applyBootstrapSummariesOnly,
    beginWorkspaceNavigationRequest,
    isCurrentWorkspaceNavigationRequest,
    setError,
    setPlotVersion,
  ]);

  const activateSession = useCallback(
    async (sessionId: string) => {
      const normalizedSessionId = sessionId.trim();
      if (!normalizedSessionId) {
        throw new Error("Missing session id");
      }
      const workspace = sessionsRef.current.find(
        (entry) => entry.id === normalizedSessionId,
      );
      const requestId = beginWorkspaceNavigationRequest();
      if (workspace?.workspace_mode === "plot") {
        try {
          const payload = await activatePlotWorkspace(normalizedSessionId);

          if (isCurrentWorkspaceNavigationRequest(requestId)) {
            applyBootstrapPayload(payload);
            if (payload.plot_mode?.current_plot) {
              setPlotVersion((value) => value + 1);
            }
          } else {
            applyBootstrapSummariesOnly(payload);
          }
          setError(null);
          return payload;
        } catch (err: unknown) {
          if (err instanceof Error && err.message.includes("404")) {
            return null;
          }
          throw err;
        }
      }

      const payload = await activateAnnotationSession(workspace?.session_id || normalizedSessionId);

      if (isCurrentWorkspaceNavigationRequest(requestId)) {
        applyBootstrapPayload(payload);
        setPlotVersion((value) => value + 1);
      } else {
        applyBootstrapSummariesOnly(payload);
      }
      setError(null);
      return payload;
    },
    [
      applyBootstrapPayload,
      applyBootstrapSummariesOnly,
      beginWorkspaceNavigationRequest,
      isCurrentWorkspaceNavigationRequest,
      sessionsRef,
      setError,
      setPlotVersion,
    ],
  );

  const renameWorkspace = useCallback(
    async (sessionId: string, workspaceName: string) => {
      const normalizedSessionId = sessionId.trim();
      const normalizedWorkspaceName = workspaceName.trim();
      if (!normalizedSessionId) {
        throw new Error("Missing session id");
      }
      if (!normalizedWorkspaceName) {
        throw new Error("Workspace name cannot be empty");
      }
      const workspace = sessionsRef.current.find(
        (entry) => entry.id === normalizedSessionId,
      );
      if (workspace?.workspace_mode === "plot") {
        const payload = await updatePlotWorkspace(normalizedSessionId, normalizedWorkspaceName);

        setPlotMode((current) =>
          current && current.id === payload.plot_mode.id ? payload.plot_mode : current,
        );
        const summary = toPlotModeWorkspaceSummary(payload.plot_mode);
        setSessions((previous) => upsertWorkspaceSummary(previous, summary));
        return summary;
      }

      const payload = await updateAnnotationWorkspace(
        workspace?.session_id || normalizedSessionId,
        normalizedWorkspaceName,
      );

      const normalizedWorkspace = normalizeSessionSummary(payload.workspace);
      setSessions((previous) => upsertWorkspaceSummary(previous, normalizedWorkspace));

      if (activeSessionId === normalizedWorkspace.session_id) {
        setSession((current) => {
          if (!current || current.id !== normalizedWorkspace.session_id) {
            return current;
          }
          return {
            ...current,
            workspace_name: normalizedWorkspace.workspace_name,
            updated_at: normalizedWorkspace.updated_at,
          };
        });
      }

      if (payload.active_session_id !== undefined) {
        setActiveSessionId(payload.active_session_id);
      }

      return normalizedWorkspace;
    },
    [activeSessionId, sessionsRef, setActiveSessionId, setPlotMode, setSession, setSessions],
  );

  const deleteWorkspace = useCallback(
    async (sessionId: string) => {
      const normalizedSessionId = sessionId.trim();
      if (!normalizedSessionId) {
        throw new Error("Missing session id");
      }
      const workspace = sessionsRef.current.find(
        (entry) => entry.id === normalizedSessionId,
      );
      const requestId = beginWorkspaceNavigationRequest();
      if (workspace?.workspace_mode === "plot") {
        const payload = await deletePlotWorkspace(normalizedSessionId);

        if (isCurrentWorkspaceNavigationRequest(requestId)) {
          applyBootstrapPayload(payload);
          setPlotVersion((value) => value + 1);
        } else {
          applyBootstrapSummariesOnly(payload);
        }
        setError(null);
        return payload;
      }

      const payload = await deleteAnnotationWorkspace(workspace?.session_id || normalizedSessionId);

      if (isCurrentWorkspaceNavigationRequest(requestId)) {
        applyBootstrapPayload(payload);
        setPlotVersion((value) => value + 1);
      } else {
        applyBootstrapSummariesOnly(payload);
      }
      setError(null);
      return payload;
    },
    [
      applyBootstrapPayload,
      applyBootstrapSummariesOnly,
      beginWorkspaceNavigationRequest,
      isCurrentWorkspaceNavigationRequest,
      sessionsRef,
      setError,
      setPlotVersion,
    ],
  );

  const handleWsEvent = useCallback((event: WsEvent) => {
    const eventSessionId = "session_id" in event ? event.session_id?.trim() || null : null;
    const isCurrentSessionEvent =
      eventSessionId === null || !activeSessionId || eventSessionId === activeSessionId;

    switch (event.type) {
      case "plot_updated":
        if (mode !== "annotation" || !isCurrentSessionEvent) {
          break;
        }
        setPlotVersion((value) => value + 1);
        void refresh();
        break;
      case "annotation_added":
      case "annotation_deleted":
      case "annotation_updated":
        if (mode !== "annotation" || !isCurrentSessionEvent) {
          break;
        }
        void refresh();
        break;
      case "fix_job_updated":
        if (!activeSessionId || event.job.session_id !== activeSessionId) {
          break;
        }
        applyFixJobUpdate(event.job);
        break;
      case "fix_job_log":
        appendFixJobLog(event);
        break;
      case "plot_mode_updated":
        if (
          shouldApplyPlotModeWorkspaceUpdate({
            activeWorkspaceId: activeWorkspaceIdRef.current,
            incomingWorkspaceId: event.plot_mode.id,
            mode: modeRef.current,
            visiblePlotModeId: plotModeRef.current?.id ?? null,
          })
        ) {
          if (
            event.plot_mode.current_plot &&
            plotModeRef.current?.current_plot !== event.plot_mode.current_plot
          ) {
            setPlotVersion((value) => value + 1);
          }
          setMode("plot");
          setSession(null);
          setActiveSessionId(null);
          setActiveWorkspaceId(event.plot_mode.id);
          setPlotMode(event.plot_mode);
        }
        setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(event.plot_mode)));
        break;
      case "plot_mode_message_updated": {
        const shouldApplyUpdate = shouldApplyPlotModeWorkspaceUpdate({
          activeWorkspaceId: activeWorkspaceIdRef.current,
          incomingWorkspaceId: event.plot_mode_id,
          mode: modeRef.current,
          visiblePlotModeId: plotModeRef.current?.id ?? null,
        });
        if (shouldApplyUpdate) {
          const nextPlotMode = upsertPlotModeMessage(
            plotModeRef.current,
            event.plot_mode_id,
            event.updated_at,
            event.message,
          );
          if (!nextPlotMode) {
            break;
          }
          setMode("plot");
          setSession(null);
          setActiveSessionId(null);
          setActiveWorkspaceId(nextPlotMode.id);
          setPlotMode(nextPlotMode);
          setSessions((previous) => upsertWorkspaceSummary(previous, toPlotModeWorkspaceSummary(nextPlotMode)));
          break;
        }
        setSessions((previous) => touchWorkspaceSummary(previous, event.plot_mode_id, event.updated_at));
        break;
      }
      case "plot_mode_completed": {
        const completedWorkspaceId = event.session.workspace_id || event.session.id;
        const shouldActivateCompletedWorkspace = shouldActivateCompletedPlotWorkspace({
          activeWorkspaceId: activeWorkspaceIdRef.current,
          completedWorkspaceId,
          mode: modeRef.current,
          visiblePlotModeId: plotModeRef.current?.id ?? null,
        });

        if (shouldActivateCompletedWorkspace) {
          setMode("annotation");
          setSession(event.session);
          setActiveSessionId(event.session.id);
          setActiveWorkspaceId(completedWorkspaceId);
          setPlotMode(null);
          setPlotVersion((value) => value + 1);
        }
        setSessions((previous) => {
          const summary = toSessionSummary(event.session);
          return upsertWorkspaceSummary(removeWorkspaceSummary(previous, completedWorkspaceId), summary);
        });
        break;
      }
    }
  }, [
    activeSessionId,
    activeWorkspaceIdRef,
    appendFixJobLog,
    applyFixJobUpdate,
    mode,
    modeRef,
    plotModeRef,
    refresh,
    setActiveSessionId,
    setActiveWorkspaceId,
    setMode,
    setPlotMode,
    setPlotVersion,
    setSession,
    setSessions,
  ]);

  return {
    mode,
    session,
    sessions,
    activeSessionId,
    activeWorkspaceId,
    plotMode,
    loading,
    error,
    selectedRunner,
    setSelectedRunner,
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
    updateStatusLoading,
    fixJob,
    fixStepLogsByKey,
    plotVersion,
    refresh,
    refreshRunnerAvailability,
    installRunner,
    launchRunnerAuth,
    openExternalUrl,
    refreshUpdateStatus,
    refreshRunnerModels,
    refreshFixJob,
    refreshPythonInterpreter,
    addAnnotation,
    deleteAnnotation,
    updateAnnotation,
    checkoutVersion,
    switchBranch,
    renameBranch,
    downloadAnnotationPlot,
    downloadPlotModeWorkspace: plotModeState.downloadPlotModeWorkspace,
    startFixJob,
    cancelFixJob,
    updateFixPreferences,
    setPythonInterpreterPreference,
    fetchPlotModePathSuggestions,
    selectPlotModePaths,
    submitPlotModeTabularHint,
    sendPlotModeMessage,
    updatePlotModeExecutionMode,
    answerPlotModeQuestion,
    finalizePlotMode,
    createNewSession,
    activateSession,
    renameWorkspace,
    deleteWorkspace,
    handleWsEvent,
  };
}
