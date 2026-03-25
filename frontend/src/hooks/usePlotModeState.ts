import { useCallback } from "react";
import type { MutableRefObject } from "react";

import { downloadPlotModeArtifact } from "../api/artifacts";
import {
  answerPlotModeQuestion as answerPlotModeQuestionRequest,
  fetchPlotModePathSuggestions as fetchPlotModePathSuggestionsRequest,
  finalizePlotMode as finalizePlotModeRequest,
  selectPlotModePaths as selectPlotModePathsRequest,
  sendPlotModeMessage as sendPlotModeMessageRequest,
  submitPlotModeTabularHint as submitPlotModeTabularHintRequest,
  updatePlotModeSettings,
} from "../api/plotMode";
import type {
  FixRunner,
  PlotModeExecutionMode,
  PlotModePathSelectionType,
  PlotModeState,
} from "../types";

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

interface UsePlotModeStateOptions {
  plotModeRef: MutableRefObject<PlotModeState | null>;
}

export function usePlotModeState({ plotModeRef }: UsePlotModeStateOptions) {
  const fetchPlotModePathSuggestions = useCallback(
    async (
      workspaceId: string | null,
      query: string,
      selectionType: PlotModePathSelectionType,
    ) => {
      return await fetchPlotModePathSuggestionsRequest(workspaceId, query, selectionType);
    },
    [],
  );

  const selectPlotModePaths = useCallback(
    async (
      workspaceId: string | null,
      selectionType: PlotModePathSelectionType,
      paths: string[],
    ) => {
      const normalizedPaths = paths.map((path) => path.trim()).filter(Boolean);
      if (normalizedPaths.length === 0) {
        return null;
      }

      return await selectPlotModePathsRequest(workspaceId, selectionType, normalizedPaths);
    },
    [],
  );

  const sendPlotModeMessage = useCallback(
    async (
      workspaceId: string | null,
      message: string,
      runner?: FixRunner,
      model?: string,
      variant?: string,
    ) => {
      const trimmedMessage = message.trim();
      if (!trimmedMessage) {
        throw new Error("Message cannot be empty");
      }

      const body: Record<string, string> = {
        message: trimmedMessage,
        workspace_id: workspaceId || "",
      };
      if (runner) {
        body.runner = runner;
      }
      const normalizedModel = model?.trim();
      const normalizedVariant = variant?.trim();
      if (normalizedModel) {
        body.model = normalizedModel;
      }
      if (variant !== undefined) {
        body.variant = normalizedVariant ?? "";
      }

      return await sendPlotModeMessageRequest(body);
    },
    [],
  );

  const submitPlotModeTabularHint = useCallback(
    async (
      workspaceId: string | null,
      selectorId: string,
      regions: Array<{
        sheet_id: string;
        row_start: number;
        row_end: number;
        col_start: number;
        col_end: number;
      }>,
      note: string,
      runner?: FixRunner,
      model?: string,
      variant?: string,
    ) => {
      const body: Record<string, unknown> = {
        workspace_id: workspaceId,
        selector_id: selectorId,
        regions,
        note: note.trim() || null,
      };
      if (runner) {
        body.runner = runner;
      }
      const normalizedModel = model?.trim();
      const normalizedVariant = variant?.trim();
      if (normalizedModel) {
        body.model = normalizedModel;
      }
      if (variant !== undefined) {
        body.variant = normalizedVariant ?? "";
      }

      return await submitPlotModeTabularHintRequest(body);
    },
    [],
  );

  const updatePlotModeExecutionMode = useCallback(
    async (workspaceId: string | null, executionMode: PlotModeExecutionMode) => {
      return await updatePlotModeSettings(workspaceId, executionMode);
    },
    [],
  );

  const answerPlotModeQuestion = useCallback(
    async (
      workspaceId: string | null,
      questionSetId: string,
      answers: Array<{
        question_id: string;
        option_ids: string[];
        text?: string | null;
      }>,
      runner?: FixRunner,
      model?: string,
      variant?: string,
    ) => {
      const body: Record<string, unknown> = {
        workspace_id: workspaceId,
        question_set_id: questionSetId,
        answers: answers.map((entry) => ({
          question_id: entry.question_id,
          option_ids: entry.option_ids,
          text: entry.text ?? null,
        })),
      };
      if (runner) {
        body.runner = runner;
      }
      const normalizedModel = model?.trim();
      const normalizedVariant = variant?.trim();
      if (normalizedModel) {
        body.model = normalizedModel;
      }
      if (variant !== undefined) {
        body.variant = normalizedVariant ?? "";
      }

      return await answerPlotModeQuestionRequest(body);
    },
    [],
  );

  const finalizePlotMode = useCallback(
    async (workspaceId: string | null, metadata?: Record<string, string | null>) => {
      return await finalizePlotModeRequest(workspaceId, metadata);
    },
    [],
  );

  const downloadPlotModeWorkspace = useCallback(async () => {
    const workspaceId = plotModeRef.current?.id?.trim() || null;
    const res = await downloadPlotModeArtifact(workspaceId);
    const blob = await res.blob();
    const contentDisposition = res.headers.get("Content-Disposition");
    const inferred = extractFileNameFromDisposition(contentDisposition);
    const fileName = inferred || "openplot_plot_workspace.zip";

    return { blob, fileName };
  }, [plotModeRef]);

  return {
    fetchPlotModePathSuggestions,
    selectPlotModePaths,
    sendPlotModeMessage,
    submitPlotModeTabularHint,
    updatePlotModeExecutionMode,
    answerPlotModeQuestion,
    finalizePlotMode,
    downloadPlotModeWorkspace,
  };
}
