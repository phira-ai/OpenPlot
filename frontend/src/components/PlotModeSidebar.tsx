import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { ArrowRight, Loader2 } from "lucide-react";

import type {
  PlotModePathSelectionType,
  PlotModePathSuggestion,
} from "../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import TabularRangeSelectorDialog from "@/components/TabularRangeSelectorDialog";
import { shouldRevealPlotComposer } from "@/lib/plotModeUi";
import { directoryPrefix } from "@/lib/paths";
import PlotModeComposer from "./plot-mode/PlotModeComposer";
import PlotModeMessageList from "./plot-mode/PlotModeMessageList";
import PlotModePathPicker from "./plot-mode/PlotModePathPicker";
import { summarizeSelectedFiles } from "./plot-mode/plotModePathUtils";
import type {
  PlotModeQuestionAnswerDraft,
  PlotModeQuestionAnswerDraftMap,
  PlotModeSidebarProps,
} from "./plot-mode/types";
import { usePlotModeScrollState } from "./plot-mode/usePlotModeScrollState";

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
  walkthroughFocusedTarget,
  plotModeExecutionMode,
  onChangePlotModeExecutionMode,
  onAnswerQuestion,
  onNext,
}: PlotModeSidebarProps) {
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
  const [questionAnswers, setQuestionAnswers] = useState<PlotModeQuestionAnswerDraftMap>({});

  const messages = useMemo(() => state?.messages ?? [], [state?.messages]);
  const { messagesRef } = usePlotModeScrollState({
    workspaceId: state?.id ?? null,
    messages,
  });

  const hasAttachedInputs =
    (state?.files.length ?? 0) > 0 ||
    Boolean(state?.current_script_path?.trim()) ||
    Boolean(state?.current_script?.trim());
  const requiresInitialFiles = !state || state.phase === "awaiting_files" || !hasAttachedInputs;
  const shouldForceInitialFiles =
    forceInitialFileSelection && requiresInitialFiles && !dismissedForcedFileSelection;
  const pathSheetOpen = pathSelectionOpen || shouldForceInitialFiles;
  const requiresTabularHint = Boolean(state?.tabular_selector?.requires_user_hint);
  const hasGeneratedScript = Boolean(state?.current_script?.trim());
  const hasLiveRefiningStatus = messages.some(
    (entry) => entry.role === "assistant" && entry.metadata?.kind === "status",
  );
  const selectedFiles = state?.files ?? [];
  const hasChatHistory = messages.length > 0 || Boolean(pendingUserMessage);
  const sourcesLocked = selectedFiles.length > 0;
  const sourcesButtonLabel = sourcesLocked ? "Sources locked for this workspace" : "Manage sources";
  const selectedFilePaths = selectedFiles.map((entry) => entry.stored_path);
  const selectedFilesSummary = summarizeSelectedFiles(selectedFilePaths);
  const readOnlySourceDetails = sourcesLocked && pathSheetOpen && selectionType === "data";
  const composerDisabled =
    sendingMessage || selectingFiles || finalizing || requiresTabularHint || Boolean(state?.pending_question_set);
  const canSubmitMessage = Boolean(message.trim()) && !requiresInitialFiles && !composerDisabled;
  const walkthroughNeedsComposer =
    walkthroughFocusedTarget === "plot-mode-mode-switch" ||
    walkthroughFocusedTarget === "plot-mode-composer" ||
    walkthroughFocusedTarget === "plot-mode-sources";
  const showComposer = shouldRevealPlotComposer({
    desktopViewport,
    forceVisible: walkthroughNeedsComposer,
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
    if (!pendingUserMessage) {
      return;
    }

    const committed = messages.some(
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
  }, [messages, pendingUserMessage]);

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
    (questionId: string, next: PlotModeQuestionAnswerDraft) => {
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

  const applySuggestion = useCallback(
    (suggestion: PlotModePathSuggestion) => {
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
    },
    [selectionType],
  );

  const addCurrentPath = useCallback(() => {
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
  }, [pathInput, selectionType]);

  const handlePathInputKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
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
    },
    [addCurrentPath, applySuggestion, highlightedIndex, suggestions],
  );

  const submitPrompt = useCallback(
    async (nextMessage: string) => {
      setPendingUserMessage(nextMessage);
      setMessage("");
      try {
        await onSendMessage(nextMessage);
      } catch (error) {
        setPendingUserMessage(null);
        setMessage(nextMessage);
        throw error;
      }
    },
    [onSendMessage],
  );

  const handleComposerKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        const nextMessage = message.trim();
        if (!nextMessage || !canSubmitMessage) {
          return;
        }
        void submitPrompt(nextMessage);
      }
    },
    [canSubmitMessage, message, submitPrompt],
  );

  const handleSelectMode = useCallback(
    (nextType: PlotModePathSelectionType) => {
      setSelectionType(nextType);
      if (nextType === "data") {
        setPathInput(lastDataDirectory || "");
      } else {
        setPathInput(selectedScriptPath || pathInput || "");
      }
    },
    [lastDataDirectory, pathInput, selectedScriptPath],
  );

  const handleConfirmPathSelection = useCallback(async () => {
    if (selectionType === "script") {
      const scriptPath = selectedScriptPath.trim() || pathInput.trim();
      if (!scriptPath) {
        return;
      }
      await onSelectPaths("script", [scriptPath]);
      return;
    }

    const candidatePaths =
      selectedDataPaths.length > 0 ? selectedDataPaths : pathInput.trim() ? [pathInput.trim()] : [];
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
  }, [onSelectPaths, onShowError, pathInput, selectedDataPaths, selectedScriptPath, selectionType, sourcesLocked]);

  const handleSend = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const nextMessage = message.trim();
      if (!nextMessage || !canSubmitMessage) {
        return;
      }

      await submitPrompt(nextMessage);
    },
    [canSubmitMessage, message, submitPrompt],
  );

  const handleOpenSources = useCallback(() => {
    if (sourcesLocked) {
      onShowError("No more files can be added to this workspace. Use New workspace to start over.");
      return;
    }
    setPathSelectionOpen(true);
    setSelectionType("data");
    setPathInput(lastDataDirectory || "");
    setSelectedDataPaths(selectedFilePaths);
  }, [lastDataDirectory, onShowError, selectedFilePaths, sourcesLocked]);

  const handleOpenAttachedFileDetails = useCallback(() => {
    if (!sourcesLocked) {
      return;
    }
    setSelectionType("data");
    setSelectedDataPaths(selectedFilePaths);
    setPathSelectionOpen(true);
  }, [selectedFilePaths, sourcesLocked]);

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
          <PlotModeMessageList
            messagesRef={messagesRef}
            messages={messages}
            desktopViewport={desktopViewport}
            touchInput={touchInput}
            showComposer={showComposer}
            sendingMessage={sendingMessage}
            hasLiveRefiningStatus={hasLiveRefiningStatus}
            currentPendingQuestionSetId={state?.pending_question_set?.id ?? null}
            activeQuestionId={activeQuestionId}
            onActiveQuestionIdChange={setActiveQuestionId}
            questionAnswers={questionAnswers}
            onQuestionAnswerChange={handleQuestionAnswerChange}
            onAnswerQuestion={onAnswerQuestion}
            pendingUserMessage={pendingUserMessage}
          />
        </div>

        <Separator />

        <PlotModeComposer
          desktopViewport={desktopViewport}
          touchInput={touchInput}
          showComposer={showComposer}
          message={message}
          onMessageChange={setMessage}
          onComposerKeyDown={handleComposerKeyDown}
          onSubmit={handleSend}
          onToggleExecutionMode={() => {
            void onChangePlotModeExecutionMode(plotModeExecutionMode === "autonomous" ? "quick" : "autonomous");
          }}
          plotModeExecutionMode={plotModeExecutionMode}
          selectingFiles={selectingFiles}
          sendingMessage={sendingMessage}
          finalizing={finalizing}
          requiresTabularHint={requiresTabularHint}
          pendingQuestionSet={state?.pending_question_set ?? null}
          composerDisabled={composerDisabled}
          canSubmitMessage={canSubmitMessage}
          sourcesLocked={sourcesLocked}
          sourcesButtonLabel={sourcesButtonLabel}
          selectedFiles={selectedFiles}
          selectedFilesSummary={selectedFilesSummary}
          selectedFilePaths={selectedFilePaths}
          onOpenSources={handleOpenSources}
          onOpenAttachedFileDetails={handleOpenAttachedFileDetails}
          onRevealZoneEnter={() => setComposerNearRevealZone(true)}
          onRevealZoneLeave={() => setComposerNearRevealZone(false)}
          onComposerMouseEnter={() => setComposerHovered(true)}
          onComposerMouseLeave={() => setComposerHovered(false)}
          onComposerFocusCapture={() => setComposerFocused(true)}
          onComposerBlurCapture={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
              setComposerFocused(false);
            }
          }}
        />

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
            {finalizing ? <Loader2 className="animate-spin" data-icon="inline-start" /> : <ArrowRight data-icon="inline-start" />}
            Annotate
          </Button>
        </div>
      </aside>

      <PlotModePathPicker
        open={pathSheetOpen}
        onOpenChange={(open) => {
          if (open) {
            setDismissedForcedFileSelection(false);
          } else if (forceInitialFileSelection && requiresInitialFiles) {
            setDismissedForcedFileSelection(true);
          }
          setPathSelectionOpen(open);
        }}
        forceInitialFileSelection={forceInitialFileSelection}
        requiresInitialFiles={requiresInitialFiles}
        readOnlySourceDetails={readOnlySourceDetails}
        selectionType={selectionType}
        selectingFiles={selectingFiles}
        loadingSuggestions={loadingSuggestions}
        pathInput={pathInput}
        suggestions={suggestions}
        highlightedIndex={highlightedIndex}
        selectedDataPaths={selectedDataPaths}
        selectedScriptPath={selectedScriptPath}
        onSelectMode={handleSelectMode}
        onPathInputChange={setPathInput}
        onPathInputKeyDown={handlePathInputKeyDown}
        onAddCurrentPath={addCurrentPath}
        onApplySuggestion={applySuggestion}
        onRemoveDataPath={(path) => {
          setSelectedDataPaths((previous) => previous.filter((entry) => entry !== path));
        }}
        onConfirm={handleConfirmPathSelection}
      />

      <TabularRangeSelectorDialog
        selector={state?.tabular_selector ?? null}
        open={requiresTabularHint}
        submitting={sendingMessage}
        onSubmit={onSubmitTabularHint}
      />
    </>
  );
}
