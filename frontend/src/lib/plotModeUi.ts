import type { AppMode } from "@/types";

export interface WalkthroughPromptState {
  annotation: boolean;
  plot: boolean;
}

export interface PlotModeWorkspaceUpdateParams {
  activeWorkspaceId: string | null;
  incomingWorkspaceId: string;
  mode: AppMode;
  visiblePlotModeId: string | null;
}

export interface PlotComposerRevealParams {
  desktopViewport: boolean;
  forceVisible?: boolean;
  hasHistory: boolean;
  hasMessage: boolean;
  isFocused: boolean;
  isHovered: boolean;
  isNearRevealZone: boolean;
  isSending: boolean;
  touchInput: boolean;
}

export interface CompletedPlotWorkspaceParams {
  activeWorkspaceId: string | null;
  completedWorkspaceId: string;
  mode: AppMode;
  visiblePlotModeId: string | null;
}

export interface PlotModeWorkspaceResponseParams {
  activeWorkspaceId: string | null;
  requestWorkspaceId: string | null;
  responseWorkspaceId: string;
  mode: AppMode;
  visiblePlotModeId: string | null;
}

export interface PlotPreviewViewportParams {
  containerHeight: number;
  containerWidth: number;
  framePadding: number;
  naturalHeight: number;
  naturalWidth: number;
  zoom: number;
}

export interface PlotChatScrollIntentMessage {
  id: string;
  role: string;
  content?: string;
}

export interface PlotChatScrollIntentParams {
  previousWorkspaceId: string | null;
  nextWorkspaceId: string | null;
  pendingRestoreWorkspaceId?: string | null;
  previousMessages: PlotChatScrollIntentMessage[];
  nextMessages: PlotChatScrollIntentMessage[];
  userNearBottom: boolean;
}

export type PlotChatScrollIntent =
  | "restore-bottom"
  | "follow-bottom"
  | "preserve-position";

export function createInitialWalkthroughPromptState(
  suppressed: boolean,
): WalkthroughPromptState {
  if (suppressed) {
    return { annotation: false, plot: false };
  }
  return { annotation: true, plot: true };
}

export function dismissWalkthroughPromptForMode(
  state: WalkthroughPromptState,
  mode: AppMode,
): WalkthroughPromptState {
  if (mode === "plot") {
    return { ...state, plot: false };
  }
  return { ...state, annotation: false };
}

export function shouldApplyPlotModeWorkspaceUpdate({
  activeWorkspaceId,
  incomingWorkspaceId,
  mode,
  visiblePlotModeId,
}: PlotModeWorkspaceUpdateParams): boolean {
  if (mode !== "plot") {
    return false;
  }
  if (!activeWorkspaceId) {
    return visiblePlotModeId === null || visiblePlotModeId === incomingWorkspaceId;
  }
  return activeWorkspaceId === incomingWorkspaceId && visiblePlotModeId === incomingWorkspaceId;
}

export function shouldRevealPlotComposer({
  desktopViewport,
  forceVisible = false,
  hasHistory,
  hasMessage,
  isFocused,
  isHovered,
  isNearRevealZone,
  isSending,
  touchInput,
}: PlotComposerRevealParams): boolean {
  if (forceVisible) {
    return true;
  }
  if (!desktopViewport || touchInput) {
    return true;
  }
  if (!hasHistory) {
    return true;
  }
  return isNearRevealZone || isHovered || isFocused || hasMessage || isSending;
}

export function shouldApplyPlotModeWorkspaceResponse({
  activeWorkspaceId,
  requestWorkspaceId,
  responseWorkspaceId,
  mode,
  visiblePlotModeId,
}: PlotModeWorkspaceResponseParams): boolean {
  if (!requestWorkspaceId || requestWorkspaceId !== responseWorkspaceId) {
    return false;
  }

  return shouldApplyPlotModeWorkspaceUpdate({
    activeWorkspaceId,
    incomingWorkspaceId: responseWorkspaceId,
    mode,
    visiblePlotModeId,
  });
}

export function isPlotWorkspacePhaseBusy(phase?: string | null): boolean {
  return (
    phase === "profiling_data" ||
    phase === "planning" ||
    phase === "drafting" ||
    phase === "self_review"
  );
}

export function shouldActivateCompletedPlotWorkspace({
  activeWorkspaceId,
  completedWorkspaceId,
  mode,
  visiblePlotModeId,
}: CompletedPlotWorkspaceParams): boolean {
  return (
    mode === "plot" &&
    activeWorkspaceId === completedWorkspaceId &&
    visiblePlotModeId === completedWorkspaceId
  );
}

export function computePlotPreviewViewport({
  containerHeight,
  containerWidth,
  framePadding,
  naturalHeight,
  naturalWidth,
  zoom,
}: PlotPreviewViewportParams): { displayHeight: number; displayWidth: number } {
  const safeNaturalWidth = Math.max(1, naturalWidth);
  const safeNaturalHeight = Math.max(1, naturalHeight);
  const availableWidth = Math.max(1, containerWidth - framePadding);
  const availableHeight = Math.max(1, containerHeight - framePadding);
  const baseScale = Math.min(
    availableWidth / safeNaturalWidth,
    availableHeight / safeNaturalHeight,
  );
  const scaledWidth = Math.max(1, Math.floor(safeNaturalWidth * baseScale * zoom));
  const scaledHeight = Math.max(1, Math.floor(safeNaturalHeight * baseScale * zoom));
  return {
    displayHeight: scaledHeight,
    displayWidth: scaledWidth,
  };
}

export function getPlotChatScrollIntent({
  previousWorkspaceId,
  nextWorkspaceId,
  pendingRestoreWorkspaceId,
  previousMessages,
  nextMessages,
  userNearBottom,
}: PlotChatScrollIntentParams): PlotChatScrollIntent {
  if (pendingRestoreWorkspaceId && pendingRestoreWorkspaceId === nextWorkspaceId) {
    return nextMessages.length > 0 ? "restore-bottom" : "preserve-position";
  }

  if (previousWorkspaceId !== nextWorkspaceId) {
    return nextMessages.length > 0 ? "restore-bottom" : "preserve-position";
  }

  if (previousMessages.length === 0) {
    return "preserve-position";
  }

  const previousAssistantMessagesById = new Map(
    previousMessages
      .filter((entry) => entry.role === "assistant")
      .map((entry) => [entry.id, entry]),
  );

  const hasNewAssistantMessage = nextMessages.some((entry) => {
    if (entry.role !== "assistant") {
      return false;
    }

    const previousEntry = previousAssistantMessagesById.get(entry.id);
    return !previousEntry || previousEntry.content !== entry.content;
  });

  if (hasNewAssistantMessage && userNearBottom) {
    return "follow-bottom";
  }

  return "preserve-position";
}
