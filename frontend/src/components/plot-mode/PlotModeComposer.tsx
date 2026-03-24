import type { FocusEventHandler, FormEventHandler, KeyboardEventHandler, MouseEventHandler } from "react";
import { Bot, FolderOpen, Loader2, Lock, Paperclip, SendHorizontal, Zap } from "lucide-react";

import type { PlotModeExecutionMode, PlotModeState } from "../../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { PathTypeIcon } from "./PlotModePathPicker";

function ComposerShell({
  message,
  onMessageChange,
  onComposerKeyDown,
  onSubmit,
  onToggleExecutionMode,
  plotModeExecutionMode,
  selectingFiles,
  sendingMessage,
  finalizing,
  requiresTabularHint,
  pendingQuestionSet,
  composerDisabled,
  canSubmitMessage,
  sourcesLocked,
  sourcesButtonLabel,
  selectedFiles,
  selectedFilesSummary,
  selectedFilePaths,
  onOpenSources,
  onOpenAttachedFileDetails,
}: {
  message: string;
  onMessageChange: (value: string) => void;
  onComposerKeyDown: KeyboardEventHandler<HTMLTextAreaElement>;
  onSubmit: FormEventHandler<HTMLFormElement>;
  onToggleExecutionMode: () => void;
  plotModeExecutionMode: PlotModeExecutionMode;
  selectingFiles: boolean;
  sendingMessage: boolean;
  finalizing: boolean;
  requiresTabularHint: boolean;
  pendingQuestionSet: PlotModeState["pending_question_set"];
  composerDisabled: boolean;
  canSubmitMessage: boolean;
  sourcesLocked: boolean;
  sourcesButtonLabel: string;
  selectedFiles: PlotModeState["files"];
  selectedFilesSummary: string;
  selectedFilePaths: string[];
  onOpenSources: () => void;
  onOpenAttachedFileDetails: () => void;
}) {
  return (
    <form onSubmit={onSubmit}>
      <div className="rounded-[1.8rem] border border-white/45 bg-[linear-gradient(180deg,rgba(255,255,255,0.26),rgba(255,255,255,0.1))] p-3 shadow-[0_28px_80px_rgba(148,163,184,0.22),inset_0_1px_0_rgba(255,255,255,0.72),inset_0_-1px_0_rgba(255,255,255,0.12)] ring-1 ring-white/28 backdrop-blur-[28px] backdrop-saturate-[180%]">
        <div className="flex items-center gap-2">
          <Button
            type="button"
            data-walkthrough="plot-mode-mode-switch"
            variant="outline"
            size="icon-sm"
            className="rounded-full border-white/45 bg-[linear-gradient(180deg,rgba(255,255,255,0.44),rgba(255,255,255,0.24))] shadow-[inset_0_1px_0_rgba(255,255,255,0.84),0_8px_18px_rgba(148,163,184,0.14)]"
            onClick={onToggleExecutionMode}
            disabled={selectingFiles || sendingMessage || finalizing}
            title={plotModeExecutionMode === "autonomous" ? "Auto mode enabled" : "Quick mode enabled"}
            aria-label={
              plotModeExecutionMode === "autonomous"
                ? "Switch to quick plot drafting"
                : "Switch to auto plot drafting"
            }
          >
            {plotModeExecutionMode === "autonomous" ? <Bot className="size-4" /> : <Zap className="size-4" />}
          </Button>

          <div
            data-walkthrough="plot-mode-composer"
            className="flex min-w-0 flex-1 items-center gap-2 rounded-full border border-white/55 bg-[linear-gradient(135deg,rgba(255,255,255,0.62),rgba(255,255,255,0.22)_58%,rgba(255,255,255,0.34))] px-3 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.88),inset_0_-1px_0_rgba(255,255,255,0.16),0_14px_32px_rgba(148,163,184,0.16)] backdrop-blur-[24px]"
          >
            <Textarea
              value={message}
              onChange={(event) => onMessageChange(event.target.value)}
              onKeyDown={onComposerKeyDown}
              placeholder={
                requiresTabularHint
                  ? "Mark the relevant spreadsheet regions before sending a prompt"
                  : pendingQuestionSet
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
              {sendingMessage ? <Loader2 className="size-4 animate-spin" /> : <SendHorizontal className="size-4" />}
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
            onClick={onOpenSources}
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
              onClick={onOpenAttachedFileDetails}
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
  );
}

export default function PlotModeComposer({
  desktopViewport,
  touchInput,
  showComposer,
  onRevealZoneEnter,
  onRevealZoneLeave,
  onComposerMouseEnter,
  onComposerMouseLeave,
  onComposerFocusCapture,
  onComposerBlurCapture,
  ...shellProps
}: {
  desktopViewport: boolean;
  touchInput: boolean;
  showComposer: boolean;
  onRevealZoneEnter: MouseEventHandler<HTMLDivElement>;
  onRevealZoneLeave: MouseEventHandler<HTMLDivElement>;
  onComposerMouseEnter: MouseEventHandler<HTMLDivElement>;
  onComposerMouseLeave: MouseEventHandler<HTMLDivElement>;
  onComposerFocusCapture: FocusEventHandler<HTMLDivElement>;
  onComposerBlurCapture: FocusEventHandler<HTMLDivElement>;
} & Parameters<typeof ComposerShell>[0]) {
  if (desktopViewport && !touchInput) {
    return (
      <>
        <div
          aria-hidden
          className="absolute inset-x-0 bottom-[3.75rem] z-10 h-8"
          onMouseEnter={onRevealZoneEnter}
          onMouseLeave={onRevealZoneLeave}
        />

        <div className="pointer-events-none absolute inset-x-0 bottom-[4.5rem] z-20 px-4 pb-3 sm:px-5">
          <div
            className={cn(
              "transition-all duration-200 ease-out",
              showComposer
                ? "pointer-events-auto translate-y-0 opacity-100"
                : "pointer-events-none translate-y-5 opacity-0",
            )}
            onMouseEnter={onComposerMouseEnter}
            onMouseLeave={onComposerMouseLeave}
            onFocusCapture={onComposerFocusCapture}
            onBlurCapture={onComposerBlurCapture}
          >
            <ComposerShell {...shellProps} />
          </div>
        </div>
      </>
    );
  }

  return (
    <div className="space-y-3 px-4 py-4 sm:px-5">
      <ComposerShell {...shellProps} />
    </div>
  );
}
