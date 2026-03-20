import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import {
  ArrowRight,
  Bot,
  CircleAlert,
  FolderOpen,
  Lock,
  Loader2,
  Paperclip,
  SendHorizontal,
  Zap,
} from "lucide-react";
import { Icon } from "@iconify/react";
import type { IconifyIcon } from "@iconify/types";
import defaultFileIcon from "@iconify-icons/vscode-icons/default-file";
import defaultFolderIcon from "@iconify-icons/vscode-icons/default-folder";
import fileTypeBinaryIcon from "@iconify-icons/vscode-icons/file-type-binary";
import fileTypeConfigIcon from "@iconify-icons/vscode-icons/file-type-config";
import fileTypeDbIcon from "@iconify-icons/vscode-icons/file-type-db";
import fileTypeExcelIcon from "@iconify-icons/vscode-icons/file-type-excel";
import fileTypeImageIcon from "@iconify-icons/vscode-icons/file-type-image";
import fileTypeIniIcon from "@iconify-icons/vscode-icons/file-type-ini";
import fileTypeJsonIcon from "@iconify-icons/vscode-icons/file-type-json";
import fileTypeJupyterIcon from "@iconify-icons/vscode-icons/file-type-jupyter";
import fileTypeMarkdownIcon from "@iconify-icons/vscode-icons/file-type-markdown";
import fileTypePdfIcon from "@iconify-icons/vscode-icons/file-type-pdf2";
import fileTypePythonIcon from "@iconify-icons/vscode-icons/file-type-python";
import fileTypeShellIcon from "@iconify-icons/vscode-icons/file-type-shell";
import fileTypeSqlIcon from "@iconify-icons/vscode-icons/file-type-sql";
import fileTypeSvgIcon from "@iconify-icons/vscode-icons/file-type-svg";
import fileTypeTextIcon from "@iconify-icons/vscode-icons/file-type-text";
import fileTypeTomlIcon from "@iconify-icons/vscode-icons/file-type-toml";
import fileTypeXmlIcon from "@iconify-icons/vscode-icons/file-type-xml";
import fileTypeYamlIcon from "@iconify-icons/vscode-icons/file-type-yaml";
import fileTypeZipIcon from "@iconify-icons/vscode-icons/file-type-zip";

import type {
  PlotModeChatMessage,
  PlotModeExecutionMode,
  PlotModeQuestionItem,
  PlotModePathSelectionType,
  PlotModePathSuggestion,
  PlotModePathSuggestionResponse,
  PlotModeState,
} from "../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import MarkdownMessage from "@/components/MarkdownMessage";
import TabularRangeSelectorDialog from "@/components/TabularRangeSelectorDialog";
import { getPlotChatScrollIntent, shouldRevealPlotComposer } from "@/lib/plotModeUi";
import { cn } from "@/lib/utils";
import { compactPathDisplay, directoryPrefix } from "@/lib/paths";
import openplotIcon from "../../openplot-icon.png";

interface PlotModeSidebarProps {
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
    regions: Array<{
      sheet_id: string;
      row_start: number;
      row_end: number;
      col_start: number;
      col_end: number;
    }>,
    note: string,
  ) => Promise<void>;
  onSendMessage: (message: string) => Promise<void>;
  onShowError: (message: string) => void;
  plotModeExecutionMode: PlotModeExecutionMode;
  onChangePlotModeExecutionMode: (mode: PlotModeExecutionMode) => Promise<void> | void;
  onAnswerQuestion: (
    questionSetId: string,
    answers: Array<{
      question_id: string;
      option_ids: string[];
      text?: string | null;
    }>,
  ) => Promise<void>;
  onNext: () => Promise<void>;
}

const SUGGESTION_PATH_MAX_LENGTH = 56;
const PLOT_CHAT_BOTTOM_THRESHOLD_PX = 80;

const EXTENSION_ICON_MAP: Record<string, IconifyIcon> = {
  py: fileTypePythonIcon,
  ipynb: fileTypeJupyterIcon,
  csv: fileTypeExcelIcon,
  tsv: fileTypeExcelIcon,
  xls: fileTypeExcelIcon,
  xlsx: fileTypeExcelIcon,
  parquet: fileTypeDbIcon,
  feather: fileTypeDbIcon,
  arrow: fileTypeDbIcon,
  db: fileTypeDbIcon,
  sqlite: fileTypeDbIcon,
  sql: fileTypeSqlIcon,
  json: fileTypeJsonIcon,
  jsonl: fileTypeJsonIcon,
  json5: fileTypeJsonIcon,
  yaml: fileTypeYamlIcon,
  yml: fileTypeYamlIcon,
  toml: fileTypeTomlIcon,
  ini: fileTypeIniIcon,
  env: fileTypeConfigIcon,
  conf: fileTypeConfigIcon,
  cfg: fileTypeConfigIcon,
  txt: fileTypeTextIcon,
  md: fileTypeMarkdownIcon,
  markdown: fileTypeMarkdownIcon,
  xml: fileTypeXmlIcon,
  svg: fileTypeSvgIcon,
  png: fileTypeImageIcon,
  jpg: fileTypeImageIcon,
  jpeg: fileTypeImageIcon,
  gif: fileTypeImageIcon,
  webp: fileTypeImageIcon,
  bmp: fileTypeImageIcon,
  tif: fileTypeImageIcon,
  tiff: fileTypeImageIcon,
  pdf: fileTypePdfIcon,
  zip: fileTypeZipIcon,
  gz: fileTypeZipIcon,
  bz2: fileTypeZipIcon,
  xz: fileTypeZipIcon,
  tar: fileTypeZipIcon,
  sh: fileTypeShellIcon,
  bash: fileTypeShellIcon,
  zsh: fileTypeShellIcon,
  fish: fileTypeShellIcon,
  ps1: fileTypeShellIcon,
  npy: fileTypeBinaryIcon,
  npz: fileTypeBinaryIcon,
  h5: fileTypeBinaryIcon,
  hdf5: fileTypeBinaryIcon,
  pkl: fileTypeBinaryIcon,
  joblib: fileTypeBinaryIcon,
};

function fileExtension(pathLike: string): string {
  const normalized = pathLike.trim().replace(/\\/g, "/");
  const baseName = normalized.split("/").at(-1) ?? "";
  if (!baseName) {
    return "";
  }

  if (baseName.startsWith(".") && !baseName.slice(1).includes(".")) {
    return baseName.slice(1).toLowerCase();
  }

  const dotIndex = baseName.lastIndexOf(".");
  if (dotIndex <= 0 || dotIndex >= baseName.length - 1) {
    return "";
  }

  return baseName.slice(dotIndex + 1).toLowerCase();
}

function iconForPath(pathLike: string): IconifyIcon {
  const extension = fileExtension(pathLike);
  if (!extension) {
    return defaultFileIcon;
  }
  return EXTENSION_ICON_MAP[extension] ?? defaultFileIcon;
}

function formatMessageTime(value: string): string {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return "";
  }

  return new Date(parsed).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

function PathTypeIcon({
  pathLike,
  isDirectory = false,
}: {
  pathLike: string;
  isDirectory?: boolean;
}) {
  if (isDirectory) {
    return <Icon icon={defaultFolderIcon} className="h-4 w-4 shrink-0" />;
  }

  return <Icon icon={iconForPath(pathLike)} className="h-4 w-4 shrink-0" />;
}

function Hotkey({ children }: { children: string }) {
  return (
    <span className="inline-flex h-6 items-center rounded-md border border-border/70 bg-background px-2 font-mono text-[11px] font-medium text-foreground shadow-sm">
      {children}
    </span>
  );
}

function PathLabel({
  pathLike,
  maxLength = 56,
  className,
}: {
  pathLike: string;
  maxLength?: number;
  className?: string;
}) {
  return (
    <span className={cn("block min-w-0 flex-1 truncate", className)} title={pathLike}>
      {compactPathDisplay(pathLike, maxLength)}
    </span>
  );
}

function summarizeSelectedFiles(paths: string[]): string {
  if (paths.length === 0) {
    return "No sources yet";
  }

  const names = paths.map((path) => path.split(/[\\/]/).at(-1) || path);
  if (names.length === 1) {
    return names[0];
  }
  if (names.length === 2) {
    return `${names[0]}, ${names[1]}`;
  }
  return `${names[0]}, ${names[1]} +${names.length - 2}`;
}

function isPlotChatNearBottom(container: HTMLDivElement): boolean {
  return (
    container.scrollHeight - container.scrollTop - container.clientHeight <=
    PLOT_CHAT_BOTTOM_THRESHOLD_PX
  );
}

function HoverTimestamp({
  timestamp,
  children,
  align = "center",
}: {
  timestamp?: string;
  children: ReactNode;
  align?: "center" | "start" | "end";
}) {
  const positionClass =
    align === "start"
      ? "left-0"
      : align === "end"
        ? "right-0"
        : "left-1/2 -translate-x-1/2";

  return (
    <div className="group relative w-fit max-w-full">
      {children}
      {timestamp ? (
        <div
          className={cn(
            "pointer-events-none absolute top-full z-10 mt-1 text-[10px] font-medium text-muted-foreground/80 opacity-0 transition group-hover:opacity-100 group-focus-within:opacity-100",
            positionClass,
          )}
        >
          {timestamp}
        </div>
      ) : null}
    </div>
  );
}

function UserMessageBubble({ content, timestamp }: { content: string; timestamp?: string }) {
  return (
    <article className="flex flex-col items-end gap-1.5">
      <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
        You
      </div>
      <HoverTimestamp timestamp={timestamp} align="end">
        <div className="w-fit max-w-[92%] rounded-[2rem] rounded-br-[1.4rem] bg-[#171b22] px-4 py-2.5 text-white shadow-xl shadow-slate-900/14 sm:max-w-[44rem]">
          <p className="whitespace-pre-wrap break-words text-[14px] leading-6">{content}</p>
        </div>
      </HoverTimestamp>
    </article>
  );
}

function questionTabLabel(question: PlotModeQuestionItem, index: number): string {
  if (question.title?.trim()) {
    return question.title.trim();
  }
  return `Question ${index + 1}`;
}

function PlotModeQuestionSetCard({
  entry,
  sending,
  currentPendingQuestionSetId,
  activeQuestionId,
  onActiveQuestionIdChange,
  questionAnswers,
  onQuestionAnswerChange,
  onSubmitQuestionSet,
}: {
  entry: PlotModeChatMessage;
  sending: boolean;
  currentPendingQuestionSetId: string | null;
  activeQuestionId: string;
  onActiveQuestionIdChange: (value: string) => void;
  questionAnswers: Record<string, { optionIds: string[]; text: string }>;
  onQuestionAnswerChange: (questionId: string, next: { optionIds: string[]; text: string }) => void;
  onSubmitQuestionSet: (
    questionSetId: string,
    questions: PlotModeQuestionItem[],
    answers: Record<string, { optionIds: string[]; text: string }>,
  ) => Promise<void>;
}) {
  const metadata = entry.metadata;
  if (!metadata?.question_set_id || metadata.questions.length === 0) {
    return null;
  }

  const questions = metadata.questions;
  const isPendingQuestionSet = metadata.question_set_id === currentPendingQuestionSetId;
  const selectedQuestionId =
    questions.some((question) => question.id === activeQuestionId) ? activeQuestionId : questions[0]?.id || "";
  const selectedQuestion = questions.find((question) => question.id === selectedQuestionId) ?? questions[0];
  if (!selectedQuestion) {
    return null;
  }

  const allAnswered = questions.every((question) => {
    const answer = questionAnswers[question.id] ?? {
      optionIds: question.selected_option_ids,
      text: question.answer_text ?? "",
    };
    return answer.optionIds.length > 0 || Boolean(answer.text.trim());
  });

  const submitIfComplete = async (nextAnswers: Record<string, { optionIds: string[]; text: string }>) => {
    const completed = questions.every((question) => {
      const answer = nextAnswers[question.id] ?? {
        optionIds: question.selected_option_ids,
        text: question.answer_text ?? "",
      };
      return answer.optionIds.length > 0 || Boolean(answer.text.trim());
    });
    if (!completed) {
      return;
    }
    if (!isPendingQuestionSet) {
      return;
    }
    await onSubmitQuestionSet(metadata.question_set_id!, questions, nextAnswers);
  };

  return (
    <div className="flex flex-col gap-3">
      <div>
        <p className="text-sm font-semibold text-foreground">{metadata.question_set_title || "Questions"}</p>
      </div>

      <Tabs
        value={selectedQuestion.id}
        onValueChange={(value) => {
          if (!isPendingQuestionSet) {
            return;
          }
          onActiveQuestionIdChange(value);
        }}
        className="flex flex-col gap-3"
      >
        <TabsList className="max-w-full overflow-x-auto rounded-2xl bg-muted/35 p-1">
          {questions.map((question, index) => (
            <TabsTrigger
              key={question.id}
              value={question.id}
              disabled={!isPendingQuestionSet}
              className="rounded-xl px-3 text-xs sm:text-sm"
            >
              {questionTabLabel(question, index)}
            </TabsTrigger>
          ))}
        </TabsList>

        {questions.map((question, index) => {
          const answer = questionAnswers[question.id] ?? {
            optionIds: question.selected_option_ids,
            text: question.answer_text ?? "",
          };
          const nextQuestion = questions[index + 1];
          const canSubmitQuestion = answer.optionIds.length > 0 || Boolean(answer.text.trim());

          return (
            <TabsContent key={question.id} value={question.id} className="mt-0 flex flex-col gap-3">
              <div className="rounded-2xl border border-border/70 bg-muted/20 p-4">
                <p className="text-sm font-semibold leading-6 text-foreground">{question.prompt}</p>
              </div>

              {question.options.length > 0 ? (
                <div className="flex flex-col gap-2">
                  {question.options.map((option) => {
                    const selected = answer.optionIds.includes(option.id);
                    return (
                      <Button
                        key={option.id}
                        type="button"
                        variant={selected ? "default" : "outline"}
                        className="h-auto items-start justify-start rounded-2xl px-4 py-3 text-left whitespace-normal"
                        disabled={sending || question.answered || !isPendingQuestionSet}
                        onClick={() => {
                          const nextOptionIds = question.multiple
                            ? selected
                              ? answer.optionIds.filter((id) => id !== option.id)
                              : [...answer.optionIds, option.id]
                            : [option.id];
                          const nextAnswers = {
                            ...questionAnswers,
                            [question.id]: { ...answer, optionIds: nextOptionIds },
                          };
                          onQuestionAnswerChange(question.id, { ...answer, optionIds: nextOptionIds });

                          if (!question.multiple) {
                            if (nextQuestion) {
                              onActiveQuestionIdChange(nextQuestion.id);
                            } else {
                              void submitIfComplete(nextAnswers);
                            }
                          }
                        }}
                      >
                        <span className="flex w-full flex-col gap-1 text-left whitespace-normal break-words">
                          <span className="whitespace-normal break-words">{option.label}</span>
                          {option.description ? (
                            <span className="text-xs text-muted-foreground whitespace-normal break-words">{option.description}</span>
                          ) : null}
                        </span>
                      </Button>
                    );
                  })}
                </div>
              ) : null}

              {question.allow_custom_answer ? (
                <div className="flex flex-col gap-2 rounded-2xl border border-border/70 bg-muted/20 p-3">
                    <Textarea
                      value={answer.text}
                    onChange={(event) => {
                      onQuestionAnswerChange(question.id, { ...answer, text: event.target.value });
                    }}
                      placeholder="Type your answer"
                      disabled={sending || question.answered || !isPendingQuestionSet}
                    className="min-h-[88px] resize-none border-0 bg-transparent px-0 py-0 text-sm leading-6 shadow-none focus-visible:border-transparent focus-visible:ring-0"
                  />
                </div>
              ) : null}

              {(question.multiple || question.allow_custom_answer) && !question.answered ? (
                <div className="flex justify-end gap-2">
                  {nextQuestion ? (
                    <Button
                      type="button"
                      size="sm"
                      className="rounded-full"
                      disabled={sending || !canSubmitQuestion || !isPendingQuestionSet}
                      onClick={() => {
                        onActiveQuestionIdChange(nextQuestion.id);
                      }}
                    >
                      Next
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      className="rounded-full"
                      disabled={sending || !allAnswered || !isPendingQuestionSet}
                      onClick={() => {
                        void onSubmitQuestionSet(metadata.question_set_id!, questions, questionAnswers);
                      }}
                    >
                      Submit answers
                    </Button>
                  )}
                </div>
              ) : null}
            </TabsContent>
          );
        })}
      </Tabs>
    </div>
  );
}

function PlotModeMessageBody({
  entry,
  sending,
  currentPendingQuestionSetId,
  activeQuestionId,
  onActiveQuestionIdChange,
  questionAnswers,
  onQuestionAnswerChange,
  onAnswerQuestion,
}: {
  entry: PlotModeChatMessage;
  sending: boolean;
  currentPendingQuestionSetId: string | null;
  activeQuestionId: string;
  onActiveQuestionIdChange: (value: string) => void;
  questionAnswers: Record<string, { optionIds: string[]; text: string }>;
  onQuestionAnswerChange: (questionId: string, next: { optionIds: string[]; text: string }) => void;
  onAnswerQuestion: (
    questionSetId: string,
    answers: Array<{ question_id: string; option_ids: string[]; text?: string | null }>,
  ) => Promise<void>;
}) {
  const metadata = entry.metadata;
  if (!metadata) {
    return <MarkdownMessage content={entry.content} className="text-[15px] leading-7 text-foreground" />;
  }

  if (metadata.kind === "status") {
    const focusLine = metadata.items[0] || entry.content;
    return (
      <div className="inline-flex max-w-full flex-col gap-2 rounded-[1.6rem] border border-border/70 bg-muted/20 px-4 py-3 text-sm text-foreground shadow-sm">
        <div className="inline-flex items-center gap-2 font-semibold text-foreground">
          <Loader2 className="size-4 animate-spin" />
          <span>{metadata.title || "Refining plot"}</span>
        </div>
        {focusLine ? <p className="text-sm leading-6 text-muted-foreground">{focusLine}</p> : null}
      </div>
    );
  }

  if (metadata.kind === "activity") {
    return (
      <div className="flex flex-col gap-3 text-sm text-foreground">
        {metadata.title ? <p className="font-semibold text-foreground">{metadata.title}</p> : null}
        <div className="flex flex-col gap-2">
          {metadata.items.map((item, index) => (
            <div
              key={`${entry.id}:activity:${index}`}
              className="rounded-2xl border border-border/70 bg-muted/25 px-3 py-2 text-sm text-foreground"
            >
              {item}
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (metadata.kind === "table_preview") {
    return (
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <p className="text-sm font-semibold text-foreground">
              {metadata.table_source_label || metadata.title || "Data preview"}
            </p>
            {metadata.table_caption ? (
              <p className="text-sm text-muted-foreground">{metadata.table_caption}</p>
            ) : null}
          </div>
          <Badge variant="outline" className="rounded-full bg-background/90 px-2.5">
            Preview
          </Badge>
        </div>
        <div className="overflow-x-auto rounded-2xl border border-border/70 bg-background/80">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr>
                {metadata.table_columns.map((column) => (
                  <th key={`${entry.id}:${column}`} className="border-b border-border px-3 py-2 font-medium text-foreground">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {metadata.table_rows.map((row, rowIndex) => (
                <tr key={`${entry.id}:row:${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${entry.id}:row:${rowIndex}:cell:${cellIndex}`} className="border-b border-border/60 px-3 py-2 align-top text-muted-foreground">
                      {cell || "-"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (metadata.kind === "question" && metadata.question_set_id && metadata.questions.length > 0) {
    return (
      <PlotModeQuestionSetCard
        entry={entry}
        sending={sending}
        currentPendingQuestionSetId={currentPendingQuestionSetId}
        activeQuestionId={activeQuestionId}
        onActiveQuestionIdChange={onActiveQuestionIdChange}
        questionAnswers={questionAnswers}
        onQuestionAnswerChange={onQuestionAnswerChange}
        onSubmitQuestionSet={async (questionSetId, questions, answersByQuestion) => {
          const answers = questions.map((question) => {
            const answer = answersByQuestion[question.id] ?? {
              optionIds: question.selected_option_ids,
              text: question.answer_text ?? "",
            };
            return {
              question_id: question.id,
              option_ids: answer.optionIds,
              text: answer.text || null,
            };
          });
          await onAnswerQuestion(questionSetId, answers);
        }}
      />
    );
  }

  return <MarkdownMessage content={entry.content} className="text-[15px] leading-7 text-foreground" />;
}

export default function PlotModeSidebar({
  state,
  desktopViewport,
  forceInitialFileSelection,
  selectingFiles,
  sendingMessage,
  finalizing,
  onFetchPathSuggestions,
  onSelectPaths,
  onSubmitTabularHint,
  onSendMessage,
  onShowError,
  plotModeExecutionMode,
  onChangePlotModeExecutionMode,
  onAnswerQuestion,
  onNext,
}: PlotModeSidebarProps) {
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const suggestionRequestRef = useRef(0);

  const [message, setMessage] = useState("");
  const [selectionType, setSelectionType] = useState<PlotModePathSelectionType>("data");
  const [pathInput, setPathInput] = useState("");
  const [selectedDataPaths, setSelectedDataPaths] = useState<string[]>([]);
  const [selectedScriptPath, setSelectedScriptPath] = useState("");
  const [lastDataDirectory, setLastDataDirectory] = useState("");
  const [suggestions, setSuggestions] = useState<PlotModePathSuggestion[]>([]);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [pathSelectionOpen, setPathSelectionOpen] = useState(false);
  const [dismissedForcedFileSelection, setDismissedForcedFileSelection] = useState(false);
  const [pendingUserMessage, setPendingUserMessage] = useState<string | null>(null);
  const [touchInput, setTouchInput] = useState(false);
  const [composerFocused, setComposerFocused] = useState(false);
  const [composerHovered, setComposerHovered] = useState(false);
  const [composerNearRevealZone, setComposerNearRevealZone] = useState(false);
  const [activeQuestionId, setActiveQuestionId] = useState("");
  const [questionAnswers, setQuestionAnswers] = useState<
    Record<string, { optionIds: string[]; text: string }>
  >({});
  const pendingInitialRestoreRef = useRef(true);
  const pendingWorkspaceRestoreRef = useRef<string | null>(null);
  const previousMessagesRef = useRef((state?.messages ?? []).map((entry) => ({
    id: entry.id,
    role: entry.role,
    content: entry.content,
  })));
  const previousWorkspaceIdRef = useRef<string | null>(state?.id ?? null);
  const userNearBottomRef = useRef(true);

  const hasAttachedInputs =
    (state?.files.length ?? 0) > 0 ||
    Boolean(state?.current_script_path?.trim()) ||
    Boolean(state?.current_script?.trim());
  const requiresInitialFiles =
    !state || state.phase === "awaiting_files" || !hasAttachedInputs;
  const shouldForceInitialFiles =
    forceInitialFileSelection && requiresInitialFiles && !dismissedForcedFileSelection;
  const pathSheetOpen = pathSelectionOpen || shouldForceInitialFiles;
  const requiresTabularHint = Boolean(state?.tabular_selector?.requires_user_hint);
  const hasGeneratedScript = Boolean(state?.current_script?.trim());
  const hasLiveRefiningStatus = (state?.messages ?? []).some(
    (entry) => entry.role === "assistant" && entry.metadata?.kind === "status",
  );
  const selectedFiles = state?.files ?? [];
  const hasChatHistory = (state?.messages.length ?? 0) > 0 || Boolean(pendingUserMessage);
  const sourcesLocked = selectedFiles.length > 0;
  const sourcesButtonLabel = sourcesLocked ? "Sources locked for this workspace" : "Manage sources";
  const selectedFilePaths = selectedFiles.map((entry) => entry.stored_path);
  const selectedFilesSummary = summarizeSelectedFiles(selectedFilePaths);
  const readOnlySourceDetails = sourcesLocked && pathSheetOpen && selectionType === "data";
  const composerDisabled =
    sendingMessage ||
    selectingFiles ||
    finalizing ||
    requiresTabularHint ||
    Boolean(state?.pending_question_set);
  const canSubmitMessage = Boolean(message.trim()) && !requiresInitialFiles && !composerDisabled;
  const showComposer = shouldRevealPlotComposer({
    desktopViewport,
    hasHistory: hasChatHistory,
    hasMessage: Boolean(message.trim()),
    isFocused: composerFocused,
    isHovered: composerHovered,
    isNearRevealZone: composerNearRevealZone,
    isSending: sendingMessage,
    touchInput,
  });
  const phaseLabel =
    state?.phase === "awaiting_files"
      ? "Awaiting Files"
      : state?.phase === "profiling_data"
        ? "Profiling Data"
      : state?.phase === "awaiting_data_choice"
        ? "Need Confirmation"
      : state?.phase === "planning"
        ? "Planning"
      : state?.phase === "awaiting_prompt"
        ? "Awaiting Prompt"
      : state?.phase === "awaiting_plan_approval"
        ? "Awaiting Approval"
      : state?.phase === "drafting"
        ? "Drafting"
        : state?.phase === "self_review"
          ? "Self Review"
          : state?.phase === "ready"
            ? "Ready"
        : "Awaiting Files";

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const mediaQuery = window.matchMedia("(hover: none), (pointer: coarse)");
    const updateTouchInput = () => {
      setTouchInput(mediaQuery.matches || navigator.maxTouchPoints > 0);
    };

    updateTouchInput();
    mediaQuery.addEventListener("change", updateTouchInput);
    return () => {
      mediaQuery.removeEventListener("change", updateTouchInput);
    };
  }, []);

  useEffect(() => {
    if (!messagesRef.current) {
      return;
    }

    const container = messagesRef.current;
    const updateUserNearBottom = () => {
      userNearBottomRef.current = isPlotChatNearBottom(container);
    };

    updateUserNearBottom();
    container.addEventListener("scroll", updateUserNearBottom, { passive: true });

    return () => {
      container.removeEventListener("scroll", updateUserNearBottom);
    };
  }, []);

  useEffect(() => {
    const nextWorkspaceId = state?.id ?? null;
    if (previousWorkspaceIdRef.current !== nextWorkspaceId) {
      pendingWorkspaceRestoreRef.current = nextWorkspaceId;
    }
  }, [state?.id]);

  useEffect(() => {
    if (!messagesRef.current) {
      return;
    }

    const nextMessages = state?.messages ?? [];
    const nextWorkspaceId = state?.id ?? null;
    const previousWorkspaceId = previousWorkspaceIdRef.current;
    const previousMessages = previousMessagesRef.current;

    if (pendingInitialRestoreRef.current) {
      previousWorkspaceIdRef.current = nextWorkspaceId;
      previousMessagesRef.current = nextMessages.map((entry) => ({
        id: entry.id,
        role: entry.role,
        content: entry.content,
      }));

      if (nextMessages.length === 0) {
        return;
      }

      const container = messagesRef.current;
      const scrollFrame = window.requestAnimationFrame(() => {
        container.scrollTo({ top: container.scrollHeight });
        pendingInitialRestoreRef.current = false;
        userNearBottomRef.current = true;
      });

      return () => {
        window.cancelAnimationFrame(scrollFrame);
      };
    }

    const scrollIntent = getPlotChatScrollIntent({
      previousWorkspaceId,
      nextWorkspaceId,
      pendingRestoreWorkspaceId: pendingWorkspaceRestoreRef.current,
      previousMessages,
      nextMessages,
      userNearBottom: userNearBottomRef.current,
    });

    previousWorkspaceIdRef.current = nextWorkspaceId;
    previousMessagesRef.current = nextMessages.map((entry) => ({
      id: entry.id,
      role: entry.role,
      content: entry.content,
    }));

    if (scrollIntent === "preserve-position") {
      return;
    }

    const container = messagesRef.current;
    const scrollFrame = window.requestAnimationFrame(() => {
      container.scrollTo({ top: container.scrollHeight });
      pendingWorkspaceRestoreRef.current = null;
      userNearBottomRef.current = true;
    });

    return () => {
      window.cancelAnimationFrame(scrollFrame);
    };
  }, [state?.id, state?.messages]);

  useEffect(() => {
    if (!pendingUserMessage) {
      return;
    }

    const committed = (state?.messages ?? []).some(
      (entry) => entry.role === "user" && entry.content === pendingUserMessage,
    );
    if (!committed) {
      return;
    }

    const clearPendingTimer = window.setTimeout(() => {
      setPendingUserMessage(null);
    }, 0);

    return () => {
      window.clearTimeout(clearPendingTimer);
    };
  }, [pendingUserMessage, state?.messages]);

  useEffect(() => {
    const nextSet = state?.pending_question_set;
    const frame = window.requestAnimationFrame(() => {
      if (!nextSet) {
        setActiveQuestionId("");
        setQuestionAnswers({});
        return;
      }

      setActiveQuestionId((current) => {
        if (nextSet.questions.some((question) => question.id === current)) {
          return current;
        }
        return nextSet.questions[0]?.id ?? "";
      });

      setQuestionAnswers((previous) => {
        const next: Record<string, { optionIds: string[]; text: string }> = {};
        for (const question of nextSet.questions) {
          next[question.id] = previous[question.id] ?? {
            optionIds: question.selected_option_ids,
            text: question.answer_text ?? "",
          };
        }
        return next;
      });
    });

    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [state?.pending_question_set]);

  const handleQuestionAnswerChange = useCallback(
    (questionId: string, next: { optionIds: string[]; text: string }) => {
      setQuestionAnswers((previous) => ({
        ...previous,
        [questionId]: next,
      }));
    },
    [],
  );

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setDismissedForcedFileSelection(false);
      setMessage("");
      setPendingUserMessage(null);
      setPathSelectionOpen(false);
      setSelectionType("data");
      setPathInput("");
      setSelectedDataPaths([]);
      setSelectedScriptPath("");
      setLastDataDirectory("");
      setSuggestions([]);
      setHighlightedIndex(0);
      setLoadingSuggestions(false);
      setComposerFocused(false);
      setComposerHovered(false);
      setComposerNearRevealZone(false);
      setActiveQuestionId("");
      setQuestionAnswers({});
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [state?.id]);

  useEffect(() => {
    if (!requiresInitialFiles) {
      const frame = window.requestAnimationFrame(() => {
        setDismissedForcedFileSelection(false);
      });
      return () => {
        window.cancelAnimationFrame(frame);
      };
    }
  }, [requiresInitialFiles]);

  useEffect(() => {
    if (!pathSheetOpen) {
      return;
    }

    const requestId = suggestionRequestRef.current + 1;
    suggestionRequestRef.current = requestId;
    const loadingTimer = window.setTimeout(() => {
      if (suggestionRequestRef.current === requestId) {
        setLoadingSuggestions(true);
      }
    }, 0);

    void onFetchPathSuggestions(pathInput, selectionType)
      .then((payload) => {
        if (suggestionRequestRef.current !== requestId) {
          return;
        }
        setSuggestions(payload.suggestions);
        setHighlightedIndex(payload.suggestions.length > 0 ? 0 : -1);
      })
      .catch(() => {
        if (suggestionRequestRef.current !== requestId) {
          return;
        }
        setSuggestions([]);
        setHighlightedIndex(-1);
      })
      .finally(() => {
        if (suggestionRequestRef.current === requestId) {
          window.clearTimeout(loadingTimer);
          setLoadingSuggestions(false);
        }
      });

    return () => {
      window.clearTimeout(loadingTimer);
    };
  }, [onFetchPathSuggestions, pathInput, pathSheetOpen, selectionType]);

  const applySuggestion = (suggestion: PlotModePathSuggestion) => {
    setPathInput(suggestion.display_path);

    if (suggestion.is_dir) {
      if (selectionType === "data") {
        setLastDataDirectory(suggestion.display_path);
      }
      return;
    }

    if (selectionType === "script") {
      setSelectedScriptPath(suggestion.path);
      return;
    }

    setSelectedDataPaths((previous) => {
      if (previous.includes(suggestion.path)) {
        return previous;
      }
      return [...previous, suggestion.path];
    });

    const nextDirectory = directoryPrefix(suggestion.display_path);
    if (nextDirectory) {
      setLastDataDirectory(nextDirectory);
      setPathInput(nextDirectory);
    }
  };

  const addCurrentPath = () => {
    const trimmed = pathInput.trim();
    if (!trimmed) {
      return;
    }

    if (selectionType === "script") {
      setSelectedScriptPath(trimmed);
      return;
    }

    setSelectedDataPaths((previous) => {
      if (previous.includes(trimmed)) {
        return previous;
      }
      return [...previous, trimmed];
    });

    const nextDirectory = directoryPrefix(trimmed);
    if (nextDirectory) {
      setLastDataDirectory(nextDirectory);
      setPathInput(nextDirectory);
    }
  };

  const handlePathInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (suggestions.length === 0) {
        return;
      }
      setHighlightedIndex((current) => {
        if (current < 0) {
          return 0;
        }
        return (current + 1) % suggestions.length;
      });
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (suggestions.length === 0) {
        return;
      }
      setHighlightedIndex((current) => {
        if (current <= 0) {
          return suggestions.length - 1;
        }
        return current - 1;
      });
      return;
    }

    if (event.key === "Tab") {
      if (suggestions.length === 0) {
        return;
      }
      event.preventDefault();
      const nextSuggestion = suggestions[Math.max(highlightedIndex, 0)];
      if (nextSuggestion) {
        applySuggestion(nextSuggestion);
      }
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      if (suggestions.length > 0 && highlightedIndex >= 0) {
        const nextSuggestion = suggestions[highlightedIndex];
        if (nextSuggestion) {
          applySuggestion(nextSuggestion);
          return;
        }
      }
      addCurrentPath();
    }
  };

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      const nextMessage = message.trim();
      if (!nextMessage || !canSubmitMessage) {
        return;
      }
      void submitPrompt(nextMessage);
    }
  };

  const submitPrompt = async (nextMessage: string) => {
    setPendingUserMessage(nextMessage);
    setMessage("");
    try {
      await onSendMessage(nextMessage);
    } catch (error) {
      setPendingUserMessage(null);
      setMessage(nextMessage);
      throw error;
    }
  };

  const handleSelectMode = (nextType: PlotModePathSelectionType) => {
    setSelectionType(nextType);
    if (nextType === "data") {
      setPathInput(lastDataDirectory || "");
    } else {
      setPathInput(selectedScriptPath || pathInput || "");
    }
  };

  const handleConfirmPathSelection = async () => {
    if (selectionType === "script") {
      const scriptPath = selectedScriptPath.trim() || pathInput.trim();
      if (!scriptPath) {
        return;
      }
      await onSelectPaths("script", [scriptPath]);
      return;
    }

    const candidatePaths =
      selectedDataPaths.length > 0
        ? selectedDataPaths
        : pathInput.trim()
          ? [pathInput.trim()]
          : [];
    if (candidatePaths.length === 0) {
      return;
    }
    if (sourcesLocked) {
      onShowError("No more files can be added to this workspace. Use New workspace to start over.");
      setPathSelectionOpen(false);
      return;
    }
    await onSelectPaths("data", candidatePaths);
    setPathSelectionOpen(false);
  };

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextMessage = message.trim();
    if (!nextMessage || !canSubmitMessage) {
      return;
    }

    await submitPrompt(nextMessage);
  };

  const handleOpenSources = () => {
    if (sourcesLocked) {
      onShowError("No more files can be added to this workspace. Use New workspace to start over.");
      return;
    }
    setPathSelectionOpen(true);
    setSelectionType("data");
    setPathInput(lastDataDirectory || "");
    setSelectedDataPaths(selectedFilePaths);
  };

  const handleOpenAttachedFileDetails = () => {
    if (!sourcesLocked) {
      return;
    }
    setSelectionType("data");
    setSelectedDataPaths(selectedFilePaths);
    setPathSelectionOpen(true);
  };

  return (
    <>
      <aside
        data-walkthrough="plot-mode-sidebar"
        className="relative flex h-full w-full min-h-0 flex-col border-t border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.9),rgba(248,249,251,0.92))] backdrop-blur-xl lg:border-l lg:border-t-0"
      >
        <div className="border-b border-border/70 px-4 py-4 sm:px-5">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="rounded-full bg-background/85 px-2.5">
              Plot mode
            </Badge>
            <Badge variant="secondary" className="rounded-full px-2.5">
              {phaseLabel}
            </Badge>
          </div>

          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            Keep refining the draft here, then move to annotation when it is ready.
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden">
          <div
            ref={messagesRef}
            data-plot-messages
            className={cn(
              "flex h-full min-h-0 flex-col gap-6 overflow-y-auto px-4 py-5 sm:px-5",
              desktopViewport && !touchInput
                ? showComposer
                  ? "pb-[10rem]"
                  : "pb-16"
                : "pb-6",
            )}
          >
            {state?.messages.map((entry) => {
              const timestamp = formatMessageTime(entry.created_at);

                if (entry.role === "user") {
                  return (
                    <div key={entry.id} data-plot-message-id={entry.id}>
                      <UserMessageBubble content={entry.content} timestamp={timestamp} />
                    </div>
                  );
                }

                if (entry.role === "error") {
                  return (
                    <div key={entry.id} data-plot-message-id={entry.id}>
                      <article className="rounded-[1.5rem] border border-destructive/30 bg-destructive/7 px-4 py-3 shadow-sm">
                        <div className="mb-2 flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2 text-sm font-semibold text-destructive">
                            <CircleAlert className="size-4" />
                            Error
                          </div>
                          {timestamp ? (
                            <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-destructive/70">
                              {timestamp}
                            </span>
                          ) : null}
                        </div>
                        <div className="text-sm leading-6 text-foreground">
                          <PlotModeMessageBody
                            entry={entry}
                            sending={sendingMessage}
                            currentPendingQuestionSetId={state?.pending_question_set?.id ?? null}
                            activeQuestionId={activeQuestionId}
                            onActiveQuestionIdChange={setActiveQuestionId}
                            questionAnswers={questionAnswers}
                            onQuestionAnswerChange={handleQuestionAnswerChange}
                            onAnswerQuestion={onAnswerQuestion}
                          />
                        </div>
                      </article>
                    </div>
                  );
                }

                return (
                  <div key={entry.id} data-plot-message-id={entry.id}>
                    <article className="flex gap-3">
                      <img
                        src={openplotIcon}
                        alt="OpenPlot"
                        className="mt-1 size-8 shrink-0 rounded-full border border-border/70 bg-background object-cover shadow-sm"
                      />
                      <div className="min-w-0 flex-1 pt-0.5">
                        <div className="mb-2 text-sm font-semibold text-foreground">OpenPlot</div>
                        <HoverTimestamp timestamp={timestamp} align="start">
                          <div className="rounded-[1.85rem] rounded-tl-[1.3rem] border border-border/70 bg-background/88 px-4 py-3 shadow-sm">
                            <PlotModeMessageBody
                              entry={entry}
                              sending={sendingMessage}
                              currentPendingQuestionSetId={state?.pending_question_set?.id ?? null}
                              activeQuestionId={activeQuestionId}
                              onActiveQuestionIdChange={setActiveQuestionId}
                              questionAnswers={questionAnswers}
                              onQuestionAnswerChange={handleQuestionAnswerChange}
                              onAnswerQuestion={onAnswerQuestion}
                            />
                          </div>
                        </HoverTimestamp>
                      </div>
                    </article>
                  </div>
                );
            })}

            {pendingUserMessage ? (
              <UserMessageBubble content={pendingUserMessage} />
            ) : null}

            {sendingMessage && !hasLiveRefiningStatus ? (
              <article className="flex gap-3">
                <img
                  src={openplotIcon}
                  alt="OpenPlot"
                  className="mt-1 size-8 shrink-0 rounded-full border border-border/70 bg-background object-cover shadow-sm"
                />
                <div className="min-w-0 flex-1 pt-0.5">
                  <div className="mb-2 text-sm font-semibold text-foreground">OpenPlot</div>
                  <div className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-background/85 px-3 py-2 text-sm text-muted-foreground shadow-sm">
                    <Loader2 className="size-4 animate-spin" />
                    Working on the next draft
                  </div>
                </div>
              </article>
            ) : null}
          </div>
        </div>

        <Separator />

        {desktopViewport && !touchInput ? (
          <>
            <div
              aria-hidden
              className="absolute inset-x-0 bottom-[3.75rem] z-10 h-8"
              onMouseEnter={() => setComposerNearRevealZone(true)}
              onMouseLeave={() => setComposerNearRevealZone(false)}
            />

            <div className="pointer-events-none absolute inset-x-0 bottom-[4.5rem] z-20 px-4 pb-3 sm:px-5">
              <div
                className={cn(
                  "transition-all duration-200 ease-out",
                  showComposer
                    ? "pointer-events-auto translate-y-0 opacity-100"
                    : "pointer-events-none translate-y-5 opacity-0",
                )}
                onMouseEnter={() => setComposerHovered(true)}
                onMouseLeave={() => setComposerHovered(false)}
                onFocusCapture={() => setComposerFocused(true)}
                onBlurCapture={(event) => {
                  if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                    setComposerFocused(false);
                  }
                }}
              >
                <form onSubmit={handleSend}>
                  <div className="rounded-[1.8rem] border border-white/45 bg-[linear-gradient(180deg,rgba(255,255,255,0.26),rgba(255,255,255,0.1))] p-3 shadow-[0_28px_80px_rgba(148,163,184,0.22),inset_0_1px_0_rgba(255,255,255,0.72),inset_0_-1px_0_rgba(255,255,255,0.12)] ring-1 ring-white/28 backdrop-blur-[28px] backdrop-saturate-[180%]">
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="icon-sm"
                        className="rounded-full border-white/45 bg-[linear-gradient(180deg,rgba(255,255,255,0.44),rgba(255,255,255,0.24))] shadow-[inset_0_1px_0_rgba(255,255,255,0.84),0_8px_18px_rgba(148,163,184,0.14)]"
                        onClick={() => {
                          void onChangePlotModeExecutionMode(
                            plotModeExecutionMode === "autonomous" ? "quick" : "autonomous",
                          );
                        }}
                        disabled={selectingFiles || sendingMessage || finalizing}
                        title={
                          plotModeExecutionMode === "autonomous"
                            ? "Auto mode enabled"
                            : "Quick mode enabled"
                        }
                        aria-label={
                          plotModeExecutionMode === "autonomous"
                            ? "Switch to quick plot drafting"
                            : "Switch to auto plot drafting"
                        }
                      >
                        {plotModeExecutionMode === "autonomous" ? (
                          <Bot className="size-4" />
                        ) : (
                          <Zap className="size-4" />
                        )}
                      </Button>

                      <div
                        data-walkthrough="plot-mode-composer"
                        className="flex min-w-0 flex-1 items-center gap-2 rounded-full border border-white/55 bg-[linear-gradient(135deg,rgba(255,255,255,0.62),rgba(255,255,255,0.22)_58%,rgba(255,255,255,0.34))] px-3 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.88),inset_0_-1px_0_rgba(255,255,255,0.16),0_14px_32px_rgba(148,163,184,0.16)] backdrop-blur-[24px]"
                      >
                        <Textarea
                          value={message}
                          onChange={(event) => setMessage(event.target.value)}
                          onKeyDown={handleComposerKeyDown}
                          placeholder={
                            requiresTabularHint
                              ? "Mark the relevant spreadsheet regions before sending a prompt"
                              : state?.pending_question_set
                              ? "Answer the pending confirmation before sending a new prompt"
                              : "Describe the next change to the draft"
                          }
                          disabled={composerDisabled}
                          rows={1}
                          className="min-h-0 flex-1 resize-none border-0 bg-transparent px-1.5 py-1 text-sm leading-5 shadow-none focus-visible:border-transparent focus-visible:ring-0"
                        />

                        <Button
                          type="submit"
                          size="icon-sm"
                          className="rounded-full"
                          disabled={!canSubmitMessage}
                          aria-label="Send prompt"
                        >
                          {sendingMessage ? (
                            <Loader2 className="size-4 animate-spin" />
                          ) : (
                            <SendHorizontal className="size-4" />
                          )}
                        </Button>
                      </div>
                    </div>

                    <div className="mt-2 flex min-h-6 flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                      <Button
                        type="button"
                        data-walkthrough="plot-mode-sources"
                        variant="ghost"
                        size="icon-xs"
                        className={cn(
                          "rounded-full transition-all",
                          sourcesLocked
                            ? "border border-amber-300/45 bg-[linear-gradient(180deg,rgba(255,248,235,0.68),rgba(255,237,213,0.38))] text-amber-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_8px_18px_rgba(245,158,11,0.12)] hover:bg-[linear-gradient(180deg,rgba(255,248,235,0.78),rgba(255,237,213,0.5))]"
                            : undefined,
                        )}
                        onClick={handleOpenSources}
                        disabled={selectingFiles || sendingMessage || finalizing}
                        aria-label={sourcesButtonLabel}
                        title={sourcesButtonLabel}
                      >
                        <span className="relative inline-flex items-center justify-center">
                          <FolderOpen className="size-3.5" />
                          {sourcesLocked ? (
                            <Lock className="absolute -right-1.5 -top-1 size-2.5 rounded-full bg-background/80 p-[1px]" />
                          ) : null}
                        </span>
                      </Button>

                      {selectedFiles.length > 0 ? (
                        <button
                          type="button"
                          className="inline-flex min-w-0 max-w-full items-center gap-2 rounded-full border border-white/34 bg-[linear-gradient(180deg,rgba(255,255,255,0.28),rgba(255,255,255,0.14))] px-2 py-1 text-[11px] text-muted-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.62)] backdrop-blur-[18px] transition hover:bg-[linear-gradient(180deg,rgba(255,255,255,0.34),rgba(255,255,255,0.18))]"
                          onClick={handleOpenAttachedFileDetails}
                          title={selectedFilePaths.join("\n")}
                          aria-label="View attached file details"
                        >
                          <span className="flex shrink-0 items-center -space-x-1">
                            {selectedFiles.slice(0, 3).map((file) => (
                              <span
                                key={file.id}
                                className="rounded-full border border-white/60 bg-white/70 p-0.5 shadow-sm"
                              >
                                <PathTypeIcon pathLike={file.stored_path} />
                              </span>
                            ))}
                          </span>
                          <span className="min-w-0 truncate">{selectedFilesSummary}</span>
                          <Badge variant="secondary" className="rounded-full px-1.5 py-0 text-[10px]">
                            {selectedFiles.length}
                          </Badge>
                        </button>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full border border-dashed border-white/30 bg-[linear-gradient(180deg,rgba(255,255,255,0.22),rgba(255,255,255,0.1))] px-2 py-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.5)] backdrop-blur-[16px]">
                          <Paperclip className="size-3" />
                          No sources yet
                        </span>
                      )}
                    </div>
                  </div>
                </form>
              </div>
            </div>
          </>
        ) : (
          <div className="space-y-3 px-4 py-4 sm:px-5">
            <form onSubmit={handleSend}>
              <div className="rounded-[1.8rem] border border-white/45 bg-[linear-gradient(180deg,rgba(255,255,255,0.26),rgba(255,255,255,0.1))] p-3 shadow-[0_28px_80px_rgba(148,163,184,0.22),inset_0_1px_0_rgba(255,255,255,0.72),inset_0_-1px_0_rgba(255,255,255,0.12)] ring-1 ring-white/28 backdrop-blur-[28px] backdrop-saturate-[180%]">
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="icon-sm"
                    className="rounded-full border-white/45 bg-[linear-gradient(180deg,rgba(255,255,255,0.44),rgba(255,255,255,0.24))] shadow-[inset_0_1px_0_rgba(255,255,255,0.84),0_8px_18px_rgba(148,163,184,0.14)]"
                    onClick={() => {
                      void onChangePlotModeExecutionMode(
                        plotModeExecutionMode === "autonomous" ? "quick" : "autonomous",
                      );
                    }}
                    disabled={selectingFiles || sendingMessage || finalizing}
                    title={
                      plotModeExecutionMode === "autonomous"
                        ? "Auto mode enabled"
                        : "Quick mode enabled"
                    }
                    aria-label={
                      plotModeExecutionMode === "autonomous"
                        ? "Switch to quick plot drafting"
                        : "Switch to auto plot drafting"
                    }
                  >
                    {plotModeExecutionMode === "autonomous" ? (
                      <Bot className="size-4" />
                    ) : (
                      <Zap className="size-4" />
                    )}
                  </Button>

                  <div
                    data-walkthrough="plot-mode-composer"
                    className="flex min-w-0 flex-1 items-center gap-2 rounded-full border border-white/55 bg-[linear-gradient(135deg,rgba(255,255,255,0.62),rgba(255,255,255,0.22)_58%,rgba(255,255,255,0.34))] px-3 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.88),inset_0_-1px_0_rgba(255,255,255,0.16),0_14px_32px_rgba(148,163,184,0.16)] backdrop-blur-[24px]"
                  >
                    <Textarea
                      value={message}
                      onChange={(event) => setMessage(event.target.value)}
                      onKeyDown={handleComposerKeyDown}
                      placeholder={
                        requiresTabularHint
                          ? "Mark the relevant spreadsheet regions before sending a prompt"
                          : state?.pending_question_set
                          ? "Answer the pending confirmation before sending a new prompt"
                          : "Describe the next change to the draft"
                      }
                      disabled={composerDisabled}
                      rows={1}
                      className="min-h-0 flex-1 resize-none border-0 bg-transparent px-1.5 py-1 text-sm leading-5 shadow-none focus-visible:border-transparent focus-visible:ring-0"
                    />

                    <Button
                      type="submit"
                      size="icon-sm"
                      className="rounded-full"
                      disabled={!canSubmitMessage}
                      aria-label="Send prompt"
                    >
                      {sendingMessage ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <SendHorizontal className="size-4" />
                      )}
                    </Button>
                  </div>
                </div>

                <div className="mt-2 flex min-h-6 flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                  <Button
                    type="button"
                    data-walkthrough="plot-mode-sources"
                    variant="ghost"
                    size="icon-xs"
                    className={cn(
                      "rounded-full transition-all",
                      sourcesLocked
                        ? "border border-amber-300/45 bg-[linear-gradient(180deg,rgba(255,248,235,0.68),rgba(255,237,213,0.38))] text-amber-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_8px_18px_rgba(245,158,11,0.12)] hover:bg-[linear-gradient(180deg,rgba(255,248,235,0.78),rgba(255,237,213,0.5))]"
                        : undefined,
                    )}
                    onClick={handleOpenSources}
                    disabled={selectingFiles || sendingMessage || finalizing}
                    aria-label={sourcesButtonLabel}
                    title={sourcesButtonLabel}
                  >
                    <span className="relative inline-flex items-center justify-center">
                      <FolderOpen className="size-3.5" />
                      {sourcesLocked ? (
                        <Lock className="absolute -right-1.5 -top-1 size-2.5 rounded-full bg-background/80 p-[1px]" />
                      ) : null}
                    </span>
                  </Button>

                  {selectedFiles.length > 0 ? (
                    <button
                      type="button"
                      className="inline-flex min-w-0 max-w-full items-center gap-2 rounded-full border border-white/34 bg-[linear-gradient(180deg,rgba(255,255,255,0.28),rgba(255,255,255,0.14))] px-2 py-1 text-[11px] text-muted-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.62)] backdrop-blur-[18px] transition hover:bg-[linear-gradient(180deg,rgba(255,255,255,0.34),rgba(255,255,255,0.18))]"
                      onClick={handleOpenAttachedFileDetails}
                      title={selectedFilePaths.join("\n")}
                      aria-label="View attached file details"
                    >
                      <span className="flex shrink-0 items-center -space-x-1">
                        {selectedFiles.slice(0, 3).map((file) => (
                          <span
                            key={file.id}
                            className="rounded-full border border-white/60 bg-white/70 p-0.5 shadow-sm"
                          >
                            <PathTypeIcon pathLike={file.stored_path} />
                          </span>
                        ))}
                      </span>
                      <span className="min-w-0 truncate">{selectedFilesSummary}</span>
                      <Badge variant="secondary" className="rounded-full px-1.5 py-0 text-[10px]">
                        {selectedFiles.length}
                      </Badge>
                    </button>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full border border-dashed border-white/30 bg-[linear-gradient(180deg,rgba(255,255,255,0.22),rgba(255,255,255,0.1))] px-2 py-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.5)] backdrop-blur-[16px]">
                      <Paperclip className="size-3" />
                      No sources yet
                    </span>
                  )}
                </div>
              </div>
            </form>
          </div>
        )}

        <div className="border-t border-border/70 px-4 py-3 sm:px-5">
          <Button
            type="button"
            data-walkthrough="plot-mode-annotate"
            className="w-full rounded-full"
            onClick={() => {
              void onNext();
            }}
            disabled={finalizing || sendingMessage || !hasGeneratedScript}
          >
            {finalizing ? (
              <Loader2 className="animate-spin" data-icon="inline-start" />
            ) : (
              <ArrowRight data-icon="inline-start" />
            )}
            Annotate
          </Button>
        </div>
      </aside>

      <Sheet
        open={pathSheetOpen}
        onOpenChange={(open) => {
          if (open) {
            setDismissedForcedFileSelection(false);
          } else if (forceInitialFileSelection && requiresInitialFiles) {
            setDismissedForcedFileSelection(true);
          }
          setPathSelectionOpen(open);
        }}
      >
        <SheetContent
          side="right"
          showCloseButton
          className="w-full gap-0 sm:max-w-2xl"
        >
          <SheetHeader className="gap-3 border-b border-border/70 pb-4 pr-14">
            <Badge variant="outline" className="w-fit rounded-full bg-background/90 px-2.5">
              {readOnlySourceDetails ? "Attached sources" : "Source selection"}
            </Badge>
            <div>
              <SheetTitle>
                {readOnlySourceDetails
                  ? "Attached files for this workspace"
                  : "Attach local data files or plotting script"}
              </SheetTitle>
            </div>
          </SheetHeader>

          <div className="flex min-h-0 flex-1 flex-col">
            <ScrollArea className="min-h-0 flex-1">
              <div className="flex flex-col gap-5 p-4 sm:p-5">
                {readOnlySourceDetails ? null : (
                  <div className="grid grid-cols-2 gap-2 rounded-2xl border border-border/70 bg-muted/20 p-1">
                  <Button
                    type="button"
                    size="sm"
                    variant={selectionType === "data" ? "default" : "ghost"}
                    className="rounded-xl"
                    onClick={() => handleSelectMode("data")}
                    disabled={selectingFiles}
                  >
                    Data files
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={selectionType === "script" ? "default" : "ghost"}
                    className="rounded-xl"
                    onClick={() => handleSelectMode("script")}
                    disabled={selectingFiles}
                  >
                    Python script
                  </Button>
                  </div>
                )}

                {readOnlySourceDetails ? null : (
                  <Card className="border border-border/70 bg-background/92 shadow-sm">
                  <CardHeader>
                    <CardTitle className="text-base">Browse local paths</CardTitle>
                    <CardDescription className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Hotkey>Up</Hotkey>
                        <Hotkey>Down</Hotkey>
                        <span>Navigate</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Hotkey>Tab</Hotkey>
                        <span>Accept</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Hotkey>Enter</Hotkey>
                        <span>Add</span>
                      </div>
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex gap-2">
                      <Input
                        value={pathInput}
                        onChange={(event) => setPathInput(event.target.value)}
                        onKeyDown={handlePathInputKeyDown}
                        placeholder={
                          selectionType === "script"
                            ? "~/path/to/script.py"
                            : "~/path/to/data.csv"
                        }
                        disabled={selectingFiles}
                        className="h-11 rounded-2xl bg-background"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        className="h-11 rounded-2xl px-4"
                        onClick={addCurrentPath}
                        disabled={selectingFiles}
                      >
                        Add
                      </Button>
                    </div>

                    <div className="rounded-2xl border border-border/70 bg-muted/20 p-2">
                      {loadingSuggestions ? (
                        <p className="px-2 py-2 text-sm text-muted-foreground">Loading paths...</p>
                      ) : suggestions.length === 0 ? (
                        <p className="px-2 py-2 text-sm text-muted-foreground">No matching paths</p>
                      ) : (
                        <ul className="max-h-60 space-y-1 overflow-y-auto">
                          {suggestions.map((suggestion, index) => {
                            const isHighlighted = index === highlightedIndex;
                            return (
                              <li key={`${suggestion.path}:${index}`}>
                                <button
                                  type="button"
                                  className={`flex w-full min-w-0 items-center gap-3 rounded-xl px-3 py-2 text-left text-sm transition ${
                                    isHighlighted
                                      ? "bg-background text-foreground shadow-sm"
                                      : "text-muted-foreground hover:bg-background/70 hover:text-foreground"
                                  }`}
                                  onMouseEnter={() => setHighlightedIndex(index)}
                                  onClick={() => applySuggestion(suggestion)}
                                  title={suggestion.display_path}
                                >
                                  <PathTypeIcon
                                    pathLike={suggestion.path}
                                    isDirectory={suggestion.is_dir}
                                  />
                                  <PathLabel
                                    pathLike={suggestion.display_path}
                                    maxLength={SUGGESTION_PATH_MAX_LENGTH}
                                  />
                                </button>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>
                  </CardContent>
                  </Card>
                )}

                {selectionType === "data" ? (
                  <Card className="border border-border/70 bg-background/92 shadow-sm">
                    <CardContent className="space-y-3 pt-4">
                      <div className="flex items-center justify-between gap-3">
                        <Badge variant="outline" className="rounded-full px-2.5">
                          Attached files
                        </Badge>
                        <Badge variant="secondary" className="rounded-full px-2.5">
                          {selectedDataPaths.length}
                        </Badge>
                      </div>
                      {selectedDataPaths.length === 0 ? (
                        <div className="rounded-2xl border border-dashed border-border/70 bg-muted/20 px-4 py-6 text-sm text-muted-foreground">
                          Add paths above to start building your file set.
                        </div>
                      ) : (
                        <ul className="space-y-2">
                          {selectedDataPaths.map((path) => (
                            <li
                              key={path}
                              className="flex items-center gap-3 rounded-2xl border border-border/70 bg-muted/20 px-3 py-3"
                            >
                              <span
                                className="flex min-w-0 flex-1 items-center gap-3 overflow-hidden"
                                title={path}
                              >
                                <PathTypeIcon pathLike={path} />
                                <PathLabel pathLike={path} className="text-sm text-foreground" />
                              </span>
                              {readOnlySourceDetails ? (
                                <Badge variant="outline" className="rounded-full px-2.5">
                                  Locked
                                </Badge>
                              ) : (
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="ghost"
                                  className="rounded-full"
                                  onClick={() => {
                                    setSelectedDataPaths((previous) =>
                                      previous.filter((entry) => entry !== path),
                                    );
                                  }}
                                >
                                  Remove
                                </Button>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                      <p className="text-xs text-muted-foreground">
                        {readOnlySourceDetails
                          ? "This workspace is locked after the initial file selection. Use New workspace to attach a different set of files."
                          : "Enter another path above to include more files."}
                      </p>
                    </CardContent>
                  </Card>
                ) : (
                  <Card className="border border-border/70 bg-background/92 shadow-sm">
                    <CardContent className="pt-4">
                      <div className="flex items-center gap-3 overflow-hidden rounded-2xl border border-border/70 bg-muted/20 px-3 py-3 text-sm text-foreground">
                        <Badge variant="outline" className="rounded-full px-2.5">
                          Script
                        </Badge>
                        {(selectedScriptPath || pathInput) && (
                          <PathTypeIcon pathLike={selectedScriptPath || pathInput} />
                        )}
                        <PathLabel pathLike={selectedScriptPath || pathInput || "(none)"} />
                      </div>
                    </CardContent>
                  </Card>
                )}

              </div>
            </ScrollArea>

            <SheetFooter className="border-t border-border/70 bg-background/96 sm:flex-row sm:justify-end">
              {readOnlySourceDetails ? null : (
                <Button
                  type="button"
                  size="icon-lg"
                  className="rounded-full"
                  aria-label={selectionType === "script" ? "Open script" : "Use selected sources"}
                  onClick={() => {
                    void handleConfirmPathSelection();
                  }}
                  disabled={selectingFiles}
                >
                  {selectingFiles ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <ArrowRight />
                  )}
                </Button>
              )}
            </SheetFooter>
          </div>
        </SheetContent>
      </Sheet>

      <TabularRangeSelectorDialog
        selector={state?.tabular_selector ?? null}
        open={requiresTabularHint}
        submitting={sendingMessage}
        onSubmit={onSubmitTabularHint}
      />
    </>
  );
}
