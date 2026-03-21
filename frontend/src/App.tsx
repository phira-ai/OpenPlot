import "./App.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CircleHelp } from "lucide-react";
import { useWebSocket } from "./hooks/useWebSocket";
import { useSessionState } from "./hooks/useSessionState";
import { useWorkspaceActions } from "./hooks/useWorkspaceActions";
import PlotViewer from "./components/PlotViewer";
import PlotModePreview from "./components/PlotModePreview";
import PlotModeSidebar from "./components/PlotModeSidebar";
import SessionSidebar from "./components/SessionSidebar";
import Toolbar from "./components/Toolbar";
import FeedbackSidebar from "./components/FeedbackSidebar";
import FixStepLiveModal from "./components/FixStepLiveModal";
import RunnerAuthDialog from "./components/RunnerAuthDialog";
import RunnerManager from "./components/RunnerManager";
import NotificationBubbleStack, {
  type NotificationBubble,
} from "./components/NotificationBubbleStack";
import WalkthroughPromptModal from "./components/WalkthroughPromptModal";
import WalkthroughTour from "./components/WalkthroughTour";
import PlotModeWalkthroughTour from "./components/PlotModeWalkthroughTour";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { TooltipProvider } from "@/components/ui/tooltip";
import { asErrorMessage } from "@/lib/errors";
import {
  createInitialWalkthroughPromptState,
  dismissWalkthroughPromptForMode,
} from "@/lib/plotModeUi";
import {
  getPlotWorkspaceActionState,
  isPlotWorkspaceBusy,
  updatePlotWorkspaceActionState,
} from "@/lib/plotWorkspaceUi";
import type {
  Annotation,
  FixRunner,
  PlotModeExecutionMode,
  PlotModePathSelectionType,
} from "./types";

const WALKTHROUGH_PROMPT_STORAGE_KEY = "openplot:walkthrough-prompt";
const WALKTHROUGH_PROMPT_SUPPRESSED_VALUE = "never";
const WORKSPACE_PANEL_PINNED_STORAGE_KEY = "openplot:workspace-panel-pinned";
const DESKTOP_VIEWPORT_QUERY = "(min-width: 1024px)";
const UI_ZOOM_STORAGE_KEY = "openplot:ui-zoom";
const MIN_UI_ZOOM = 0.7;
const MAX_UI_ZOOM = 2;
const UI_ZOOM_STEP = 0.1;
const NOTIFICATION_LIFETIME_MS = 4200;

function isWalkthroughPromptSuppressed(): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  try {
    return (
      window.localStorage.getItem(WALKTHROUGH_PROMPT_STORAGE_KEY) ===
      WALKTHROUGH_PROMPT_SUPPRESSED_VALUE
    );
  } catch {
    return false;
  }
}

function persistWalkthroughPromptSuppression(suppress: boolean): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    if (suppress) {
      window.localStorage.setItem(
        WALKTHROUGH_PROMPT_STORAGE_KEY,
        WALKTHROUGH_PROMPT_SUPPRESSED_VALUE,
      );
    } else {
      window.localStorage.removeItem(WALKTHROUGH_PROMPT_STORAGE_KEY);
    }
  } catch {
    // Ignore storage write failures.
  }
}

function isWorkspacePanelPinned(): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  try {
    return window.localStorage.getItem(WORKSPACE_PANEL_PINNED_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function persistWorkspacePanelPinned(pinned: boolean): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    if (pinned) {
      window.localStorage.setItem(WORKSPACE_PANEL_PINNED_STORAGE_KEY, "1");
    } else {
      window.localStorage.removeItem(WORKSPACE_PANEL_PINNED_STORAGE_KEY);
    }
  } catch {
    // Ignore storage write failures.
  }
}

function isDesktopViewport(): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  return window.matchMedia(DESKTOP_VIEWPORT_QUERY).matches;
}

function isPyWebviewRuntime(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return Boolean((window as Window & { pywebview?: unknown }).pywebview);
}

function clampUiZoom(value: number): number {
  const clamped = Math.min(MAX_UI_ZOOM, Math.max(MIN_UI_ZOOM, value));
  return Math.round(clamped * 100) / 100;
}

function loadUiZoom(): number {
  if (typeof window === "undefined") {
    return 1;
  }

  try {
    const raw = window.localStorage.getItem(UI_ZOOM_STORAGE_KEY);
    if (!raw) {
      return 1;
    }
    const parsed = Number(raw);
    if (Number.isFinite(parsed)) {
      return clampUiZoom(parsed);
    }
  } catch {
    // Ignore storage read failures and use default zoom.
  }

  return 1;
}

function App() {
  const {
    mode,
    session,
    sessions,
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
    fixJob,
    fixStepLogsByKey,
    plotVersion,
    addAnnotation,
    deleteAnnotation,
    updateAnnotation,
    checkoutVersion,
    switchBranch,
    renameBranch,
    downloadAnnotationPlot,
    downloadPlotModeWorkspace,
    startFixJob,
    cancelFixJob,
    updateFixPreferences,
    installRunner,
    launchRunnerAuth,
    openExternalUrl,
    refreshPythonInterpreter,
    refreshRunnerAvailability,
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
  } = useSessionState();

  const [focusedAnnotationId, setFocusedAnnotationId] = useState<string | null>(null);
  const [walkthroughPromptState, setWalkthroughPromptState] = useState(() =>
    createInitialWalkthroughPromptState(isWalkthroughPromptSuppressed()),
  );
  const [showWalkthroughTour, setShowWalkthroughTour] = useState(false);
  const [showPlotModeWalkthroughTour, setShowPlotModeWalkthroughTour] = useState(false);
  const [notifications, setNotifications] = useState<NotificationBubble[]>([]);
  const [walkthroughFocusedTarget, setWalkthroughFocusedTarget] = useState<string | null>(null);
  const [plotWorkspaceActionsById, setPlotWorkspaceActionsById] = useState<Record<string, {
    selectingFiles: boolean;
    sendingMessage: boolean;
    finalizing: boolean;
  }>>({});
  const [downloadingPlotExport, setDownloadingPlotExport] = useState(false);
  const [plotModeActionError, setPlotModeActionError] = useState<string | null>(null);
  const [workspacePanelPinned, setWorkspacePanelPinned] = useState(isWorkspacePanelPinned);
  const [workspacePanelPeek, setWorkspacePanelPeek] = useState(isWorkspacePanelPinned);
  const [workspacePanelHovered, setWorkspacePanelHovered] = useState(false);
  const workspacePeekHideTimerRef = useRef<number | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedVariant, setSelectedVariant] = useState("");
  const [annotationLiveOutputOpen, setAnnotationLiveOutputOpen] = useState(false);
  const [forcePlotFileSelection, setForcePlotFileSelection] = useState(false);
  const [annotationSelectionActive, setAnnotationSelectionActive] = useState(false);
  const [desktopViewport, setDesktopViewport] = useState(isDesktopViewport);
  const [isPlotRegionHovered, setIsPlotRegionHovered] = useState(false);
  const [uiZoom, setUiZoom] = useState(() => loadUiZoom());
  const notificationTimersRef = useRef<Map<string, number>>(new Map());
  const [showRunnerManager, setShowRunnerManager] = useState(false);
  const [runnerManagerError, setRunnerManagerError] = useState<string | null>(null);
  const [runnerAuthEntry, setRunnerAuthEntry] = useState<
    NonNullable<typeof runnerStatus> extends { runners: infer R }
      ? R extends Array<infer T>
        ? T | null
        : null
      : null
  >(null);
  const [runnerAuthLaunching, setRunnerAuthLaunching] = useState(false);
  const [runnerAuthError, setRunnerAuthError] = useState<string | null>(null);

  const activePlotWorkspaceId = plotMode?.id ?? null;
  const activePlotWorkspaceActions = useMemo(
    () => getPlotWorkspaceActionState(plotWorkspaceActionsById, activePlotWorkspaceId),
    [activePlotWorkspaceId, plotWorkspaceActionsById],
  );
  const plotWorkspaceBusyById = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(plotWorkspaceActionsById)
          .filter(([, state]) => isPlotWorkspaceBusy(state))
          .map(([workspaceId]) => [workspaceId, true]),
      ) as Record<string, boolean>,
    [plotWorkspaceActionsById],
  );
  const updatePlotWorkspaceActions = useCallback(
    (
      workspaceId: string | null | undefined,
      patch: Partial<{
        selectingFiles: boolean;
        sendingMessage: boolean;
        finalizing: boolean;
      }>,
    ) => {
      setPlotWorkspaceActionsById((current) => updatePlotWorkspaceActionState(current, workspaceId, patch));
    },
    [],
  );

  const {
    connected,
    wsUrl,
    reconnectAttempts,
    lastConnectedAt,
    lastDisconnectedAt,
  } = useWebSocket(handleWsEvent);

  const activeBranch = useMemo(() => {
    if (!session) {
      return null;
    }
    return (
      session.branches.find((branch) => branch.id === session.active_branch_id) ?? null
    );
  }, [session]);

  const activeBranchAnnotations = useMemo(() => {
    if (!session) {
      return [];
    }
    return session.annotations.filter(
      (annotation) =>
        !session.active_branch_id ||
        !annotation.branch_id ||
        annotation.branch_id === session.active_branch_id,
    );
  }, [session]);

  const hasSavedWorkspaces = useMemo(
    () => sessions.length > 0,
    [sessions],
  );

  const currentFixStep = useMemo(() => {
    if (!fixJob || !session || fixJob.branch_id !== session.active_branch_id) {
      return null;
    }
    return fixJob.steps[fixJob.steps.length - 1] ?? null;
  }, [fixJob, session]);

  const currentFixLogs = useMemo(() => {
    if (!fixJob || !currentFixStep) {
      return [];
    }
    return fixStepLogsByKey[`${fixJob.id}:${currentFixStep.index}`] || [];
  }, [currentFixStep, fixJob, fixStepLogsByKey]);

  const currentFixInstruction = useMemo(() => {
    if (!currentFixStep) {
      return "";
    }
    const annotation = activeBranchAnnotations.find((entry) => entry.id === currentFixStep.annotation_id);
    return annotation?.feedback?.trim() || currentFixStep.annotation_id;
  }, [activeBranchAnnotations, currentFixStep]);

  const fixStatusBubble = useMemo(() => {
    if (!fixJob || !currentFixStep || !currentFixInstruction) {
      return null;
    }
    if (fixJob.status !== "queued" && fixJob.status !== "running") {
      return null;
    }
    return {
      instruction: currentFixInstruction,
      running: currentFixStep.status === "running" || fixJob.status === "queued",
      onOpen: () => setAnnotationLiveOutputOpen(true),
    };
  }, [currentFixInstruction, currentFixStep, fixJob]);

  useEffect(() => {
    if (!annotationLiveOutputOpen) {
      return;
    }
    if (!fixJob || !currentFixStep) {
      setAnnotationLiveOutputOpen(false);
    }
  }, [annotationLiveOutputOpen, currentFixStep, fixJob]);

  useEffect(() => {
    if (mode !== "plot" || workspacePanelPinned) {
      return;
    }
    setWorkspacePanelPeek(hasSavedWorkspaces);
  }, [hasSavedWorkspaces, mode, workspacePanelPinned]);

  useEffect(() => {
    if (mode !== "plot") {
      setForcePlotFileSelection(false);
      setAnnotationSelectionActive(false);
      return;
    }
    if (plotMode?.phase === "drafting") {
      setForcePlotFileSelection(false);
    }
  }, [mode, plotMode?.phase]);

  useEffect(() => {
    if (mode !== "plot" || workspacePanelPinned) {
      return;
    }
    if ((plotMode?.files.length ?? 0) <= 0) {
      return;
    }
    setWorkspacePanelHovered(false);
    setWorkspacePanelPeek(false);
  }, [mode, plotMode?.files.length, workspacePanelPinned]);

  useEffect(() => {
    if (mode !== "annotation" || workspacePanelPinned || !annotationSelectionActive) {
      return;
    }
    setWorkspacePanelHovered(false);
    setWorkspacePanelPeek(false);
  }, [annotationSelectionActive, mode, workspacePanelPinned]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const mediaQuery = window.matchMedia(DESKTOP_VIEWPORT_QUERY);
    const handleViewportChange = (event: MediaQueryListEvent) => {
      setDesktopViewport(event.matches);
    };

    setDesktopViewport(mediaQuery.matches);
    mediaQuery.addEventListener("change", handleViewportChange);
    return () => {
      mediaQuery.removeEventListener("change", handleViewportChange);
    };
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }

    const root = document.documentElement;
    if (Math.abs(uiZoom - 1) < 0.001) {
      root.style.removeProperty("zoom");
    } else {
      root.style.zoom = String(uiZoom);
    }

    return () => {
      root.style.removeProperty("zoom");
    };
  }, [uiZoom]);

  const dismissNotification = useCallback((id: string) => {
    const timerId = notificationTimersRef.current.get(id);
    if (timerId !== undefined) {
      window.clearTimeout(timerId);
      notificationTimersRef.current.delete(id);
    }
    setNotifications((current) => current.filter((entry) => entry.id !== id));
  }, []);

  const enqueueErrorNotification = useCallback(
    (message: string) => {
      const trimmed = message.trim();
      if (!trimmed) {
        return;
      }

      const id =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(36).slice(2)}`;

      setNotifications((current) => {
        if (current.some((entry) => entry.message === trimmed)) {
          return current;
        }
        return [...current, { id, message: trimmed, tone: "error" as const }].slice(-4);
      });
    },
    [],
  );

  useEffect(() => {
    const activeIds = new Set(notifications.map((entry) => entry.id));
    for (const [id, timerId] of notificationTimersRef.current.entries()) {
      if (activeIds.has(id)) {
        continue;
      }
      window.clearTimeout(timerId);
      notificationTimersRef.current.delete(id);
    }

    for (const notification of notifications) {
      if (notificationTimersRef.current.has(notification.id)) {
        continue;
      }
      const timerId = window.setTimeout(() => {
        dismissNotification(notification.id);
      }, NOTIFICATION_LIFETIME_MS);
      notificationTimersRef.current.set(notification.id, timerId);
    }
  }, [dismissNotification, notifications]);

  useEffect(() => {
    if (!plotModeActionError) {
      return;
    }
    enqueueErrorNotification(plotModeActionError);
  }, [enqueueErrorNotification, plotModeActionError]);

  useEffect(() => {
    if (mode !== "plot" || !plotMode?.last_error) {
      return;
    }
    enqueueErrorNotification(plotMode.last_error);
  }, [enqueueErrorNotification, mode, plotMode?.last_error]);

  useEffect(() => {
    if (mode !== "plot" || !error) {
      return;
    }
    enqueueErrorNotification(error);
  }, [enqueueErrorNotification, error, mode]);

  useEffect(() => {
    const timers = notificationTimersRef.current;
    return () => {
      for (const timerId of timers.values()) {
        window.clearTimeout(timerId);
      }
      timers.clear();
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    try {
      if (Math.abs(uiZoom - 1) < 0.001) {
        window.localStorage.removeItem(UI_ZOOM_STORAGE_KEY);
      } else {
        window.localStorage.setItem(UI_ZOOM_STORAGE_KEY, String(uiZoom));
      }
    } catch {
      // Ignore storage write failures.
    }
  }, [uiZoom]);

  useEffect(() => {
    const handleUiZoomHotkey = (event: KeyboardEvent) => {
      if (isPlotRegionHovered) {
        return;
      }

      if (!isPyWebviewRuntime()) {
        return;
      }

      const hasZoomModifier = event.ctrlKey || event.metaKey;
      if (!hasZoomModifier) {
        return;
      }

      const isZoomInKey = event.key === "+" || event.key === "=" || event.code === "NumpadAdd";
      const isZoomOutKey = event.key === "-" || event.key === "_" || event.code === "NumpadSubtract";
      const isResetKey = event.key === "0" || event.code === "Numpad0";

      if (!isZoomInKey && !isZoomOutKey && !isResetKey) {
        return;
      }

      event.preventDefault();

      if (isZoomInKey) {
        setUiZoom((current) => clampUiZoom(current + UI_ZOOM_STEP));
        return;
      }

      if (isZoomOutKey) {
        setUiZoom((current) => clampUiZoom(current - UI_ZOOM_STEP));
        return;
      }

      setUiZoom(1);
    };

    window.addEventListener("keydown", handleUiZoomHotkey, true);
    return () => window.removeEventListener("keydown", handleUiZoomHotkey, true);
  }, [isPlotRegionHovered]);

  const activePlotUrl = useMemo(() => {
    if (!session) {
      return "";
    }

    const params = new URLSearchParams({
      session_id: session.id,
      v: String(plotVersion),
    });
    if (session.checked_out_version_id) {
      params.set("version_id", session.checked_out_version_id);
    }
    return `/api/plot?${params.toString()}`;
  }, [plotVersion, session]);

  const plotModePreviewUrl = useMemo(() => {
    const params = new URLSearchParams({
      plot_mode: "1",
      v: String(plotVersion),
    });
    if (plotMode?.id) {
      params.set("workspace_id", plotMode.id);
    }
    return `/api/plot?${params.toString()}`;
  }, [plotMode?.id, plotVersion]);

  const rootVersionId = session?.root_version_id ?? "";
  const focusedAnnotationIdForBranch = useMemo(() => {
    if (!focusedAnnotationId) {
      return null;
    }
    const exists = activeBranchAnnotations.some((ann) => ann.id === focusedAnnotationId);
    return exists ? focusedAnnotationId : null;
  }, [activeBranchAnnotations, focusedAnnotationId]);

  const modelIds = useMemo(
    () => opencodeModels.map((option) => option.id),
    [opencodeModels],
  );

  const effectiveSelectedModel = useMemo(() => {
    if (selectedModel && (modelIds.length === 0 || modelIds.includes(selectedModel))) {
      return selectedModel;
    }

    if (
      plotMode?.selected_runner === selectedRunner &&
      plotMode?.selected_model &&
      (modelIds.length === 0 || modelIds.includes(plotMode.selected_model))
    ) {
      return plotMode.selected_model;
    }

    if (defaultOpencodeModel && (modelIds.length === 0 || modelIds.includes(defaultOpencodeModel))) {
      return defaultOpencodeModel;
    }

    return modelIds[0] ?? "";
  }, [
    defaultOpencodeModel,
    modelIds,
    plotMode?.selected_model,
    plotMode?.selected_runner,
    selectedModel,
    selectedRunner,
  ]);

  const selectedModelOption = useMemo(
    () => opencodeModels.find((option) => option.id === effectiveSelectedModel) ?? null,
    [effectiveSelectedModel, opencodeModels],
  );

  const availableVariants = useMemo(
    () => selectedModelOption?.variants ?? [],
    [selectedModelOption],
  );

  const effectiveSelectedVariant = useMemo(() => {
    if (!effectiveSelectedModel || availableVariants.length === 0) {
      return "";
    }

    const fallbackPlotModeVariant =
      selectedModel || plotMode?.selected_runner !== selectedRunner
        ? ""
        : (plotMode?.selected_variant ?? "");
    const fallbackDefaultVariant = selectedModel ? "" : defaultOpencodeVariant;
    const candidates = [selectedVariant, fallbackPlotModeVariant, fallbackDefaultVariant];
    const candidate = candidates.find((value) => value.trim()) || "";
    if (!candidate) {
      return "";
    }
    if (availableVariants.includes(candidate)) {
      return candidate;
    }
    return "";
  }, [
    availableVariants,
    defaultOpencodeVariant,
    effectiveSelectedModel,
    plotMode?.selected_runner,
    plotMode?.selected_variant,
    selectedModel,
    selectedRunner,
    selectedVariant,
  ]);

  const handleSelectAnnotation = useCallback(
    async (annotation: Annotation) => {
      const versionId = annotation.addressed_in_version_id ?? annotation.base_version_id;
      if (!versionId) {
        return;
      }
      setFocusedAnnotationId(annotation.id);
      await checkoutVersion(versionId, annotation.branch_id || undefined);
    },
    [checkoutVersion],
  );

  const handleSelectInitialState = useCallback(async () => {
    if (!rootVersionId) {
      return;
    }
    setFocusedAnnotationId(null);
    await checkoutVersion(rootVersionId);
  }, [checkoutVersion, rootVersionId]);

  const saveBlobWithPicker = useCallback(async (blob: Blob, fileName: string) => {
    const filePickerWindow = window as Window & {
      showSaveFilePicker?: (options: {
        suggestedName?: string;
        types?: Array<{ description: string; accept: Record<string, string[]> }>;
      }) => Promise<{
        createWritable: () => Promise<{
          write: (data: Blob) => Promise<void>;
          close: () => Promise<void>;
        }>;
      }>;
    };

    if (filePickerWindow.showSaveFilePicker) {
      const extension = fileName.includes(".")
        ? fileName.slice(fileName.lastIndexOf("."))
        : ".png";
      const mimeType = blob.type || "application/octet-stream";
      const description = extension === ".zip" ? "OpenPlot export" : "Plot image";
      const handle = await filePickerWindow.showSaveFilePicker({
        suggestedName: fileName,
        types: [
          {
            description,
            accept: { [mimeType]: [extension] },
          },
        ],
      });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      return;
    }

    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }, []);

  const handleDownloadAnnotation = useCallback(
    async (annotation: Annotation) => {
      if (annotation.status !== "addressed") {
        return;
      }

      try {
        const { blob, fileName } = await downloadAnnotationPlot(annotation.id);
        await saveBlobWithPicker(blob, fileName);
      } catch (err) {
        const name = err instanceof DOMException ? err.name : "";
        if (name === "AbortError") {
          return;
        }
        console.error("Failed to download annotation plot", err);
      }
    },
    [downloadAnnotationPlot, saveBlobWithPicker],
  );

  const handleDownloadPlotModeExport = useCallback(async () => {
    if (!plotMode?.current_plot || !plotMode.current_script) {
      return;
    }

    setDownloadingPlotExport(true);
    try {
      const { blob, fileName } = await downloadPlotModeWorkspace();
      await saveBlobWithPicker(blob, fileName);
    } catch (err) {
      const name = err instanceof DOMException ? err.name : "";
      if (name !== "AbortError") {
        console.error("Failed to download plot-mode export", err);
      }
    } finally {
      setDownloadingPlotExport(false);
    }
  }, [downloadPlotModeWorkspace, plotMode?.current_plot, plotMode?.current_script, saveBlobWithPicker]);

  const handleDismissWalkthroughPrompt = useCallback(() => {
    setWalkthroughPromptState((current) => dismissWalkthroughPromptForMode(current, mode));
    setWalkthroughFocusedTarget(null);
  }, [mode]);

  const handleStartWalkthrough = useCallback(() => {
    setWalkthroughPromptState((current) => dismissWalkthroughPromptForMode(current, mode));
    if (mode === "plot") {
      setShowWalkthroughTour(false);
      setShowPlotModeWalkthroughTour(true);
      return;
    }
    setShowPlotModeWalkthroughTour(false);
    setShowWalkthroughTour(true);
  }, [mode]);

  const handleDontShowWalkthroughAgain = useCallback(() => {
    persistWalkthroughPromptSuppression(true);
    setWalkthroughPromptState({ annotation: false, plot: false });
    setShowWalkthroughTour(false);
    setShowPlotModeWalkthroughTour(false);
    setWalkthroughFocusedTarget(null);
  }, []);

  const handleCloseWalkthroughTour = useCallback(() => {
    setShowWalkthroughTour(false);
    setWalkthroughFocusedTarget(null);
  }, []);

  const handleClosePlotModeWalkthroughTour = useCallback(() => {
    setShowPlotModeWalkthroughTour(false);
    setWalkthroughFocusedTarget(null);
  }, []);

  const handleWorkspaceHotzoneEnter = useCallback(() => {
    if (mode === "annotation" && annotationSelectionActive) {
      return;
    }
    if (workspacePeekHideTimerRef.current !== null) {
      window.clearTimeout(workspacePeekHideTimerRef.current);
      workspacePeekHideTimerRef.current = null;
    }
    if (!workspacePanelPinned) {
      setWorkspacePanelPeek(true);
    }
  }, [annotationSelectionActive, mode, workspacePanelPinned]);

  const handleWorkspaceHotzoneLeave = useCallback(() => {
    if (workspacePanelPinned) {
      return;
    }
    if (workspacePeekHideTimerRef.current !== null) {
      window.clearTimeout(workspacePeekHideTimerRef.current);
    }
    workspacePeekHideTimerRef.current = window.setTimeout(() => {
      setWorkspacePanelPeek(false);
      workspacePeekHideTimerRef.current = null;
    }, 110);
  }, [workspacePanelPinned]);

  const handleWorkspacePanelMouseEnter = useCallback(() => {
    if (mode === "annotation" && annotationSelectionActive) {
      return;
    }
    if (workspacePeekHideTimerRef.current !== null) {
      window.clearTimeout(workspacePeekHideTimerRef.current);
      workspacePeekHideTimerRef.current = null;
    }
    setWorkspacePanelHovered(true);
    setWorkspacePanelPeek(true);
  }, [annotationSelectionActive, mode]);

  const handleWorkspacePanelMouseLeave = useCallback(() => {
    if (workspacePeekHideTimerRef.current !== null) {
      window.clearTimeout(workspacePeekHideTimerRef.current);
      workspacePeekHideTimerRef.current = null;
    }
    setWorkspacePanelHovered(false);
    if (!workspacePanelPinned) {
      setWorkspacePanelPeek(false);
    }
  }, [workspacePanelPinned]);

  const handleWorkspacePanelClose = useCallback(() => {
    if (workspacePeekHideTimerRef.current !== null) {
      window.clearTimeout(workspacePeekHideTimerRef.current);
      workspacePeekHideTimerRef.current = null;
    }
    setWorkspacePanelHovered(false);
    if (!workspacePanelPinned) {
      setWorkspacePanelPeek(false);
    }
  }, [workspacePanelPinned]);

  const handleToggleWorkspacePanelPinned = useCallback(() => {
    setWorkspacePanelPinned((current) => {
      const next = !current;
      persistWorkspacePanelPinned(next);
      if (workspacePeekHideTimerRef.current !== null) {
        window.clearTimeout(workspacePeekHideTimerRef.current);
        workspacePeekHideTimerRef.current = null;
      }
      if (next) {
        setWorkspacePanelPeek(true);
      } else {
        setWorkspacePanelPeek(false);
      }
      return next;
    });
  }, []);

  const handleDeleteWorkspaceRequest = useCallback(
    async (sessionId: string) => {
      await deleteWorkspace(sessionId);
      setForcePlotFileSelection(false);
    },
    [deleteWorkspace],
  );

  const {
    sessionActionPending,
    handleCreateSession,
    handleActivateSession,
    handleRenameWorkspace,
    handleDeleteWorkspace,
  } = useWorkspaceActions({
    activeWorkspaceId,
    createNewSession,
    activateSession,
    renameWorkspace,
    deleteWorkspace: handleDeleteWorkspaceRequest,
    clearFocusedAnnotation: () => setFocusedAnnotationId(null),
    onError: enqueueErrorNotification,
  });

  const handleSidebarSelectSession = useCallback(
    async (sessionId: string) => {
      const selectedWorkspace = sessions.find((entry) => entry.id === sessionId) ?? null;
      setForcePlotFileSelection(selectedWorkspace?.workspace_mode === "plot");
      await handleActivateSession(sessionId);
    },
    [handleActivateSession, sessions],
  );

  const handleSidebarCreateSession = useCallback(async () => {
    setForcePlotFileSelection(true);
    await handleCreateSession();
  }, [handleCreateSession]);

  const forceWorkspaceSidebarForWalkthrough = walkthroughFocusedTarget === "sessions-sidebar";
  const allowWorkspaceSidebar = mode !== "plot" || hasSavedWorkspaces || forceWorkspaceSidebarForWalkthrough;
  const showWorkspaceSidebar =
    allowWorkspaceSidebar &&
    (forceWorkspaceSidebarForWalkthrough || workspacePanelPinned || workspacePanelPeek || workspacePanelHovered);

  const persistModelPreference = useCallback(
    (runner: FixRunner, model?: string | null, variant?: string | null) => {
      void Promise.resolve(updateFixPreferences(runner, model, variant)).catch(() => {
        // Keep UI responsive even if persistence fails.
      });
    },
    [updateFixPreferences],
  );

  const handleToolbarRunnerChange = useCallback(
    (runner: FixRunner) => {
      setSelectedRunner(runner);
      setSelectedModel("");
      setSelectedVariant("");
      persistModelPreference(runner, null, null);
    },
    [persistModelPreference, setSelectedRunner],
  );

  const handleToolbarModelChange = useCallback(
    (model: string) => {
      setSelectedModel(model);
      setSelectedVariant("");
      persistModelPreference(selectedRunner, model, null);
    },
    [persistModelPreference, selectedRunner],
  );

  const handleToolbarVariantChange = useCallback(
    (variant: string) => {
      setSelectedVariant(variant);
      persistModelPreference(
        selectedRunner,
        effectiveSelectedModel,
        variant || null,
      );
    },
    [effectiveSelectedModel, persistModelPreference, selectedRunner],
  );

  const handleSavePythonInterpreter = useCallback(
    async (modeValue: "builtin" | "manual", path?: string) => {
      await setPythonInterpreterPreference(modeValue, path);
    },
    [setPythonInterpreterPreference],
  );

  const handleInstallRunner = useCallback(
    async (runner: FixRunner) => {
      setRunnerManagerError(null);
      try {
        await installRunner(runner);
      } catch (err: unknown) {
        setRunnerManagerError(asErrorMessage(err, `Failed to install ${runner}`));
      }
    },
    [installRunner],
  );

  const handleAuthenticateRunner = useCallback((entry: NonNullable<typeof runnerAuthEntry>) => {
    setRunnerManagerError(null);
    setRunnerAuthError(null);
    setRunnerAuthEntry(entry);
  }, []);

  const handleConfirmRunnerAuth = useCallback(async () => {
    if (!runnerAuthEntry) {
      return;
    }
    setRunnerAuthLaunching(true);
    setRunnerAuthError(null);
    try {
      await launchRunnerAuth(runnerAuthEntry.runner);
      setRunnerAuthEntry(null);
    } catch (err: unknown) {
      setRunnerAuthError(
        asErrorMessage(err, `Failed to start ${runnerAuthEntry.runner} authentication`),
      );
    } finally {
      setRunnerAuthLaunching(false);
    }
  }, [launchRunnerAuth, runnerAuthEntry]);

  const handleOpenRunnerGuide = useCallback(
    async (url: string) => {
      setRunnerManagerError(null);
      try {
        await openExternalUrl(url);
      } catch (err: unknown) {
        setRunnerManagerError(asErrorMessage(err, "Failed to open runner guide"));
      }
    },
    [openExternalUrl],
  );

  const handleRefreshRunners = useCallback(async () => {
    setRunnerManagerError(null);
    setRunnerAuthError(null);
    await refreshRunnerAvailability();
  }, [refreshRunnerAvailability]);

  const handleFetchPlotModePathSuggestions = useCallback(
    async (query: string, selectionType: PlotModePathSelectionType) => {
      return await fetchPlotModePathSuggestions(plotMode?.id ?? null, query, selectionType);
    },
    [fetchPlotModePathSuggestions, plotMode?.id],
  );

  const handleSelectPlotModePaths = useCallback(
    async (selectionType: PlotModePathSelectionType, paths: string[]) => {
      const workspaceId = plotMode?.id ?? null;
      updatePlotWorkspaceActions(workspaceId, { selectingFiles: true });
      setPlotModeActionError(null);
      try {
        await selectPlotModePaths(workspaceId, selectionType, paths);
      } catch (err: unknown) {
        setPlotModeActionError(
          asErrorMessage(
            err,
            selectionType === "script"
              ? "Failed to select script path"
              : "Failed to select data file paths",
          ),
        );
      } finally {
        updatePlotWorkspaceActions(workspaceId, { selectingFiles: false });
      }
    },
    [plotMode?.id, selectPlotModePaths, updatePlotWorkspaceActions],
  );

  const handleSendPlotMessage = useCallback(
    async (message: string) => {
      const workspaceId = plotMode?.id ?? null;
      updatePlotWorkspaceActions(workspaceId, { sendingMessage: true });
      setPlotModeActionError(null);
      try {
        await sendPlotModeMessage(
          workspaceId,
          message,
          selectedRunner,
          effectiveSelectedModel || undefined,
          effectiveSelectedVariant || undefined,
        );
      } catch (err: unknown) {
        setPlotModeActionError(asErrorMessage(err, "Failed to generate plot draft"));
      } finally {
        updatePlotWorkspaceActions(workspaceId, { sendingMessage: false });
      }
    },
    [
      plotMode?.id,
      effectiveSelectedModel,
      effectiveSelectedVariant,
      selectedRunner,
      sendPlotModeMessage,
      updatePlotWorkspaceActions,
    ],
  );

  const handleSetPlotExecutionMode = useCallback(
    async (executionMode: PlotModeExecutionMode) => {
      setPlotModeActionError(null);
      try {
        await updatePlotModeExecutionMode(plotMode?.id ?? null, executionMode);
      } catch (err: unknown) {
        setPlotModeActionError(asErrorMessage(err, "Failed to update plot mode"));
      }
    },
    [plotMode?.id, updatePlotModeExecutionMode],
  );

  const handleAnswerPlotQuestion = useCallback(
    async (
      questionSetId: string,
      answers: Array<{
        question_id: string;
        option_ids: string[];
        text?: string | null;
      }>,
    ) => {
      const workspaceId = plotMode?.id ?? null;
      updatePlotWorkspaceActions(workspaceId, { sendingMessage: true });
      setPlotModeActionError(null);
      try {
        await answerPlotModeQuestion(
          workspaceId,
          questionSetId,
          answers,
          selectedRunner,
          effectiveSelectedModel || undefined,
          effectiveSelectedVariant || undefined,
        );
      } catch (err: unknown) {
        setPlotModeActionError(asErrorMessage(err, "Failed to answer plot-mode question"));
      } finally {
        updatePlotWorkspaceActions(workspaceId, { sendingMessage: false });
      }
    },
    [
      answerPlotModeQuestion,
      plotMode?.id,
      selectedRunner,
      effectiveSelectedModel,
      effectiveSelectedVariant,
      updatePlotWorkspaceActions,
    ],
  );

  const handleSubmitTabularHint = useCallback(
    async (
      selectorId: string,
      regions: Array<{
        sheet_id: string;
        row_start: number;
        row_end: number;
        col_start: number;
        col_end: number;
      }>,
      note: string,
    ) => {
      const workspaceId = plotMode?.id ?? null;
      updatePlotWorkspaceActions(workspaceId, { sendingMessage: true });
      setPlotModeActionError(null);
      try {
        await submitPlotModeTabularHint(
          workspaceId,
          selectorId,
          regions,
          note,
          selectedRunner,
          effectiveSelectedModel || undefined,
          effectiveSelectedVariant || undefined,
        );
      } catch (err: unknown) {
        setPlotModeActionError(asErrorMessage(err, "Failed to apply tabular selection"));
      } finally {
        updatePlotWorkspaceActions(workspaceId, { sendingMessage: false });
      }
    },
    [
      submitPlotModeTabularHint,
      plotMode?.id,
      selectedRunner,
      effectiveSelectedModel,
      effectiveSelectedVariant,
      updatePlotWorkspaceActions,
    ],
  );

  const handleFinalizePlotMode = useCallback(async () => {
    const script = plotMode?.current_script;
    if (!script) {
      return;
    }

    const workspaceId = plotMode?.id ?? null;
    updatePlotWorkspaceActions(workspaceId, { finalizing: true });
    setPlotModeActionError(null);

    try {
      await finalizePlotMode(workspaceId, {});
    } catch (err: unknown) {
      setPlotModeActionError(asErrorMessage(err, "Failed to finalize plot mode"));
    } finally {
      updatePlotWorkspaceActions(workspaceId, { finalizing: false });
    }
  }, [finalizePlotMode, plotMode?.current_script, plotMode?.id, updatePlotWorkspaceActions]);

  const runnerManagerDialog = runnerStatus ? (
    <Dialog open={showRunnerManager} onOpenChange={setShowRunnerManager}>
      <DialogContent className="max-h-[85vh] max-w-6xl overflow-y-auto p-0" showCloseButton>
        <DialogHeader className="border-b border-border/70 px-6 py-5">
          <DialogTitle>Manage runners</DialogTitle>
          <DialogDescription>
            Add or review the runners OpenPlot can use on this machine.
          </DialogDescription>
        </DialogHeader>
        <div className="p-6">
          <RunnerManager
            runners={runnerStatus.runners}
            loading={runnerStatusLoading}
            error={runnerManagerError ?? runnerStatusError}
            onInstall={handleInstallRunner}
            onAuthenticate={handleAuthenticateRunner}
            onOpenGuide={handleOpenRunnerGuide}
            onRefresh={handleRefreshRunners}
          />
        </div>
      </DialogContent>
    </Dialog>
  ) : null;

  const runnerAuthDialog = (
    <RunnerAuthDialog
      open={runnerAuthEntry !== null}
      entry={runnerAuthEntry}
      launching={runnerAuthLaunching}
      error={runnerAuthError}
      onOpenChange={(open) => {
        if (!open) {
          setRunnerAuthEntry(null);
          setRunnerAuthLaunching(false);
          setRunnerAuthError(null);
        }
      }}
      onConfirm={handleConfirmRunnerAuth}
    />
  );

  if (loading) {
    return (
      <div className="flex h-dvh items-center justify-center bg-background p-4">
        <Card className="w-full max-w-md border border-border/80 bg-card shadow-sm">
          <CardContent className="pt-6">
            <CardTitle>Connecting to OpenPlot</CardTitle>
            <CardDescription className="mt-1">
              Establishing session with the local server.
            </CardDescription>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (runnerStatusLoading && !runnerStatus) {
    return (
      <div className="flex h-dvh items-center justify-center bg-background p-4">
        <Card className="w-full max-w-md border border-border/80 bg-card shadow-sm">
          <CardContent className="pt-6">
            <CardTitle>Checking runners</CardTitle>
            <CardDescription className="mt-1">
              Looking for installed runners before opening the workspace.
            </CardDescription>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (runnerStatus && availableRunners.length === 0) {
    return (
      <>
        <RunnerManager
          runners={runnerStatus.runners}
          loading={runnerStatusLoading}
          error={runnerManagerError ?? runnerStatusError}
          blocking
          onInstall={handleInstallRunner}
          onAuthenticate={handleAuthenticateRunner}
          onOpenGuide={handleOpenRunnerGuide}
          onRefresh={handleRefreshRunners}
        />
        {runnerAuthDialog}
      </>
    );
  }

  if (backendFatalError && !runnerStatus) {
    return (
      <div className="flex h-dvh items-center justify-center bg-background p-4">
        <Card className="w-full max-w-2xl border border-border/80 bg-card shadow-sm">
          <CardContent className="space-y-3 pt-6">
            <CardTitle className="text-destructive">No Supported Backend Found</CardTitle>
            <CardDescription className="text-sm leading-6 text-foreground">
              At least one of the following CLIs must exist on this machine: codex,
              claude code, opencode.
            </CardDescription>
            <CardDescription className="text-xs text-muted-foreground">
              {backendFatalError}
            </CardDescription>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (mode === "plot") {
    const selectedFileCount = plotMode?.files.length ?? 0;

    return (
      <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
        <NotificationBubbleStack
          notifications={notifications}
          onDismiss={dismissNotification}
        />
        <Toolbar
          mode="plot"
          connected={connected}
          wsUrl={wsUrl}
          reconnectAttempts={reconnectAttempts}
          lastConnectedAt={lastConnectedAt}
          lastDisconnectedAt={lastDisconnectedAt}
          opencodeModels={opencodeModels}
          opencodeModelsLoading={opencodeModelsLoading}
          opencodeModelsError={opencodeModelsError}
          availableRunners={availableRunners}
          selectedRunner={selectedRunner}
          onChangeRunner={handleToolbarRunnerChange}
          selectedModel={effectiveSelectedModel}
          selectedVariant={effectiveSelectedVariant}
          onChangeModel={handleToolbarModelChange}
          onChangeVariant={handleToolbarVariantChange}
          pythonInterpreterState={pythonInterpreter}
          pythonInterpreterLoading={pythonInterpreterLoading}
          pythonInterpreterError={pythonInterpreterError}
          onRefreshPythonInterpreter={refreshPythonInterpreter}
          onSavePythonInterpreter={handleSavePythonInterpreter}
          onOpenRunnerManager={runnerStatus ? () => setShowRunnerManager(true) : undefined}
        />

        {allowWorkspaceSidebar ? (
          <div
            aria-hidden
            className="fixed inset-y-0 left-0 z-30 hidden w-8 lg:block"
            onMouseEnter={handleWorkspaceHotzoneEnter}
            onMouseLeave={handleWorkspaceHotzoneLeave}
          />
        ) : null}

        <div className="flex min-h-0 flex-1 overflow-hidden">
          <SessionSidebar
            open={showWorkspaceSidebar}
            sessions={sessions}
            activeWorkspaceId={activeWorkspaceId}
            plotWorkspaceBusyById={plotWorkspaceBusyById}
            actionPending={sessionActionPending}
            onSelectSession={(sessionId) => {
              void handleSidebarSelectSession(sessionId);
            }}
            onNewSession={() => {
              void handleSidebarCreateSession();
            }}
            onRenameWorkspace={(sessionId, workspaceName) => {
              void handleRenameWorkspace(sessionId, workspaceName);
            }}
            onDeleteWorkspace={(sessionId) => {
              void handleDeleteWorkspace(sessionId);
            }}
            pinned={workspacePanelPinned}
            onTogglePinned={handleToggleWorkspacePanelPinned}
            onPanelMouseEnter={handleWorkspacePanelMouseEnter}
            onPanelMouseLeave={handleWorkspacePanelMouseLeave}
            onClose={handleWorkspacePanelClose}
          />

          {desktopViewport ? (
            <div className="min-h-0 flex-1 overflow-hidden">
              <ResizablePanelGroup orientation="horizontal" className="h-full w-full">
                <ResizablePanel defaultSize="67%" minSize="44%">
                  <main className="h-full min-h-0 min-w-0 overflow-hidden">
                    <PlotModePreview
                      hasPlot={Boolean(plotMode?.current_plot)}
                      imageUrl={plotModePreviewUrl}
                      workspaceId={plotMode?.id ?? "plot-mode"}
                      plotVersion={plotVersion}
                      downloadingExport={downloadingPlotExport}
                      onDownload={handleDownloadPlotModeExport}
                      onGraphHoverChange={setIsPlotRegionHovered}
                    />
                  </main>
                </ResizablePanel>

                <ResizableHandle
                  withHandle
                  className="bg-transparent text-muted-foreground/70 transition-colors hover:text-foreground"
                />

                <ResizablePanel defaultSize="33%" minSize="33%">
                  <div className="h-full min-h-0 overflow-hidden">
                    <PlotModeSidebar
                      state={plotMode}
                      desktopViewport={desktopViewport}
                      forceInitialFileSelection={forcePlotFileSelection}
                      selectingFiles={activePlotWorkspaceActions.selectingFiles}
                      sendingMessage={activePlotWorkspaceActions.sendingMessage}
                      finalizing={activePlotWorkspaceActions.finalizing}
                      onFetchPathSuggestions={handleFetchPlotModePathSuggestions}
                      onSelectPaths={handleSelectPlotModePaths}
                      onSubmitTabularHint={handleSubmitTabularHint}
                      onSendMessage={handleSendPlotMessage}
                      onShowError={enqueueErrorNotification}
                      plotModeExecutionMode={plotMode?.execution_mode ?? "quick"}
                      onChangePlotModeExecutionMode={handleSetPlotExecutionMode}
                      onAnswerQuestion={handleAnswerPlotQuestion}
                      onNext={handleFinalizePlotMode}
                    />
                  </div>
                </ResizablePanel>
              </ResizablePanelGroup>
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              <main className="min-h-0 min-w-0 flex-1 overflow-hidden">
                <PlotModePreview
                  hasPlot={Boolean(plotMode?.current_plot)}
                  imageUrl={plotModePreviewUrl}
                  workspaceId={plotMode?.id ?? "plot-mode"}
                  plotVersion={plotVersion}
                  downloadingExport={downloadingPlotExport}
                  onDownload={handleDownloadPlotModeExport}
                  onGraphHoverChange={setIsPlotRegionHovered}
                />
              </main>

              <PlotModeSidebar
                state={plotMode}
                desktopViewport={desktopViewport}
                forceInitialFileSelection={forcePlotFileSelection}
                selectingFiles={activePlotWorkspaceActions.selectingFiles}
                sendingMessage={activePlotWorkspaceActions.sendingMessage}
                finalizing={activePlotWorkspaceActions.finalizing}
                onFetchPathSuggestions={handleFetchPlotModePathSuggestions}
                onSelectPaths={handleSelectPlotModePaths}
                onSubmitTabularHint={handleSubmitTabularHint}
                onSendMessage={handleSendPlotMessage}
                onShowError={enqueueErrorNotification}
                plotModeExecutionMode={plotMode?.execution_mode ?? "quick"}
                onChangePlotModeExecutionMode={handleSetPlotExecutionMode}
                onAnswerQuestion={handleAnswerPlotQuestion}
                onNext={handleFinalizePlotMode}
              />
            </div>
          )}
        </div>

        <footer
          data-walkthrough="plot-mode-footer"
          className="flex items-center justify-between border-t border-border/80 bg-muted/35 px-4 py-1.5 text-xs text-muted-foreground"
        >
          <span>
            {selectedFileCount} selected file{selectedFileCount === 1 ? "" : "s"}
          </span>
          <div className="flex shrink-0 items-center gap-1.5">
            <span>Refine the draft here, then move to annotation when it is ready</span>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              onClick={handleStartWalkthrough}
              aria-label="Restart walkthrough"
              title="Restart walkthrough"
            >
              <CircleHelp className="h-3.5 w-3.5" />
            </Button>
          </div>
        </footer>

        <WalkthroughPromptModal
          open={walkthroughPromptState.plot}
          mode="plot"
          onStart={handleStartWalkthrough}
          onDismiss={handleDismissWalkthroughPrompt}
          onDontShowAgain={handleDontShowWalkthroughAgain}
        />

        {showPlotModeWalkthroughTour ? (
          <PlotModeWalkthroughTour
            onClose={handleClosePlotModeWalkthroughTour}
            onStepTargetChange={setWalkthroughFocusedTarget}
          />
        ) : null}

        {runnerManagerDialog}
        {runnerAuthDialog}
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="flex h-dvh items-center justify-center bg-background p-4">
        <Card className="w-full max-w-md border border-border/80 bg-card shadow-sm">
          <CardContent className="space-y-3 pt-6">
            <CardTitle className="text-destructive">
              {error ?? "No active session."}
            </CardTitle>
            <CardDescription>
              Start a session with{" "}
              <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[12px] text-foreground">
                openplot serve &lt;file&gt;
              </code>
            </CardDescription>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
        <NotificationBubbleStack
          notifications={notifications}
          onDismiss={dismissNotification}
        />
        <Toolbar
          mode="annotation"
          connected={connected}
          branches={session.branches}
          activeBranchId={session.active_branch_id}
          checkedOutVersionId={session.checked_out_version_id}
          wsUrl={wsUrl}
          reconnectAttempts={reconnectAttempts}
          lastConnectedAt={lastConnectedAt}
          lastDisconnectedAt={lastDisconnectedAt}
          opencodeModels={opencodeModels}
          opencodeModelsLoading={opencodeModelsLoading}
          opencodeModelsError={opencodeModelsError}
          availableRunners={availableRunners}
          selectedRunner={selectedRunner}
          onChangeRunner={handleToolbarRunnerChange}
          selectedModel={effectiveSelectedModel}
          selectedVariant={effectiveSelectedVariant}
          onChangeModel={handleToolbarModelChange}
          onChangeVariant={handleToolbarVariantChange}
          pythonInterpreterState={pythonInterpreter}
          pythonInterpreterLoading={pythonInterpreterLoading}
          pythonInterpreterError={pythonInterpreterError}
          onRefreshPythonInterpreter={refreshPythonInterpreter}
          onSavePythonInterpreter={handleSavePythonInterpreter}
          onOpenRunnerManager={runnerStatus ? () => setShowRunnerManager(true) : undefined}
        />

        <div
          aria-hidden
          className="fixed inset-y-0 left-0 z-30 hidden w-8 lg:block"
          onMouseEnter={handleWorkspaceHotzoneEnter}
          onMouseLeave={handleWorkspaceHotzoneLeave}
        />

        <div className="flex min-h-0 flex-1 overflow-hidden">
          <SessionSidebar
            open={showWorkspaceSidebar}
            sessions={sessions}
            activeWorkspaceId={activeWorkspaceId}
            plotWorkspaceBusyById={plotWorkspaceBusyById}
            actionPending={sessionActionPending}
            onSelectSession={(sessionId) => {
              void handleSidebarSelectSession(sessionId);
            }}
            onNewSession={() => {
              void handleSidebarCreateSession();
            }}
            onRenameWorkspace={(sessionId, workspaceName) => {
              void handleRenameWorkspace(sessionId, workspaceName);
            }}
            onDeleteWorkspace={(sessionId) => {
              void handleDeleteWorkspace(sessionId);
            }}
            pinned={workspacePanelPinned}
            onTogglePinned={handleToggleWorkspacePanelPinned}
            onPanelMouseEnter={handleWorkspacePanelMouseEnter}
            onPanelMouseLeave={handleWorkspacePanelMouseLeave}
            onClose={handleWorkspacePanelClose}
          />

          <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
            <main className="min-h-0 min-w-0 flex-1 overflow-hidden">
              <PlotViewer
                key={`${session.id}:${session.checked_out_version_id || "none"}:${plotVersion}`}
                imageUrl={activePlotUrl}
                workspaceId={session.id}
                annotations={activeBranchAnnotations}
                focusedAnnotationId={focusedAnnotationIdForBranch}
                onAddAnnotation={addAnnotation}
                fixStatusBubble={fixStatusBubble}
                onSelectionActivityChange={setAnnotationSelectionActive}
                onGraphHoverChange={setIsPlotRegionHovered}
              />
            </main>

            <FeedbackSidebar
              annotations={session.annotations}
              versions={session.versions}
              branches={session.branches}
              rootVersionId={session.root_version_id}
              activeBranchId={session.active_branch_id}
              checkedOutVersionId={session.checked_out_version_id}
              onSwitchBranch={async (branchId) => {
                await switchBranch(branchId);
                setFocusedAnnotationId(null);
              }}
              onRenameBranch={renameBranch}
              focusedAnnotationId={focusedAnnotationIdForBranch}
              onSelectInitialState={handleSelectInitialState}
              onSelectAnnotation={handleSelectAnnotation}
              onDownload={handleDownloadAnnotation}
              onDelete={deleteAnnotation}
              onUpdate={updateAnnotation}
              selectedRunner={selectedRunner}
              selectedModel={effectiveSelectedModel}
              selectedVariant={effectiveSelectedVariant}
              opencodeModelsLoading={opencodeModelsLoading}
              opencodeModelsError={opencodeModelsError}
              fixJob={fixJob}
              onStartFixJob={startFixJob}
              onCancelFixJob={cancelFixJob}
            />
          </div>
        </div>

        <footer
          data-walkthrough="session-footer"
          className="flex items-center justify-between border-t border-border/80 bg-muted/35 px-4 py-1.5 text-xs text-muted-foreground"
        >
          <span className="truncate pr-4">
            {session.source_script_path ?? "Static file"} &mdash; {session.plot_type.toUpperCase()} &mdash; {activeBranch?.name ?? "main"}
          </span>
          <div className="flex shrink-0 items-center gap-1.5">
            <span>Rev {session.revision_history.length} · {session.checked_out_version_id || "<none>"}</span>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              onClick={handleStartWalkthrough}
              aria-label="Restart walkthrough"
              title="Restart walkthrough"
            >
              <CircleHelp className="h-3.5 w-3.5" />
            </Button>
          </div>
        </footer>

        <WalkthroughPromptModal
          open={walkthroughPromptState.annotation}
          mode="annotation"
          onStart={handleStartWalkthrough}
          onDismiss={handleDismissWalkthroughPrompt}
          onDontShowAgain={handleDontShowWalkthroughAgain}
        />

        {showWalkthroughTour ? (
          <WalkthroughTour
            onClose={handleCloseWalkthroughTour}
            onStepTargetChange={setWalkthroughFocusedTarget}
          />
        ) : null}

        {fixJob && currentFixStep && annotationLiveOutputOpen ? (
          <FixStepLiveModal
            open
            job={fixJob}
            step={currentFixStep}
            logs={currentFixLogs}
            onClose={() => setAnnotationLiveOutputOpen(false)}
          />
        ) : null}

        {runnerManagerDialog}
        {runnerAuthDialog}
      </div>
    </TooltipProvider>
  );
}

export default App;
