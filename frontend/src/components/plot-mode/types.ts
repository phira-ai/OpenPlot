import type {
  PlotModeExecutionMode,
  PlotModeQuestionAnswerInput,
  PlotModePathSelectionType,
  PlotModePathSuggestionResponse,
  PlotModeState,
  PlotModeTabularHintRegionInput,
} from "../../types";

export interface PlotModeQuestionAnswerDraft {
  optionIds: string[];
  text: string;
}

export type PlotModeQuestionAnswerDraftMap = Record<string, PlotModeQuestionAnswerDraft>;

export interface PlotModeSidebarProps {
  state: PlotModeState | null;
  desktopViewport: boolean;
  forceInitialFileSelection: boolean;
  selectingFiles: boolean;
  sendingMessage: boolean;
  finalizing: boolean;
  onFetchPathSuggestions: (
    query: string,
    selectionType: PlotModePathSelectionType,
  ) => Promise<PlotModePathSuggestionResponse>;
  onSelectPaths: (
    selectionType: PlotModePathSelectionType,
    paths: string[],
  ) => Promise<void>;
  onSubmitTabularHint: (
    selectorId: string,
    regions: PlotModeTabularHintRegionInput[],
    note: string,
  ) => Promise<void>;
  onSendMessage: (message: string) => Promise<void>;
  onShowError: (message: string) => void;
  walkthroughFocusedTarget?: string | null;
  plotModeExecutionMode: PlotModeExecutionMode;
  onChangePlotModeExecutionMode: (mode: PlotModeExecutionMode) => Promise<void> | void;
  onAnswerQuestion: (
    questionSetId: string,
    answers: PlotModeQuestionAnswerInput[],
  ) => Promise<void>;
  onNext: () => Promise<void>;
}
