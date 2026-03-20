import { useEffect, useMemo, useRef } from "react";
import { CircleAlert, Loader2, Sparkles, Wrench } from "lucide-react";

import type { FixJob, FixJobLogEvent, FixJobStep, FixRunner } from "../types";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import MarkdownMessage from "@/components/MarkdownMessage";
import { Progress } from "@/components/ui/progress";
import { buildChatRows, fallbackLogs, formatClock } from "@/features/fix-jobs/logParsing";
import { runnerLabel } from "@/lib/runners";
import codexLogo from "../../codex.svg";
import claudeCodeLogo from "../../claude-code.svg";
import opencodeLogo from "../../opencode.svg";

interface FixStepLiveModalProps {
  open: boolean;
  job: FixJob;
  step: FixJobStep;
  logs: FixJobLogEvent[];
  onClose: () => void;
}

function splitToolMessage(text: string): { headline: string; details: string | null } {
  const [headline, ...rest] = text.split("\n");
  return {
    headline: headline.replaceAll("`", "").trim() || "Tool",
    details: rest.join("\n").trim() || null,
  };
}

function runnerIcon(runner: FixRunner): string {
  if (runner === "codex") {
    return codexLogo;
  }
  if (runner === "claude") {
    return claudeCodeLogo;
  }
  return opencodeLogo;
}

export default function FixStepLiveModal({
  open,
  job,
  step,
  logs,
  onClose,
}: FixStepLiveModalProps) {
  const chatRef = useRef<HTMLDivElement | null>(null);

  const sourceLogs = useMemo(() => {
    if (logs.length > 0) {
      return logs;
    }
    return fallbackLogs(job, step);
  }, [job, logs, step]);

  const rows = useMemo(() => buildChatRows(job.runner, sourceLogs), [job.runner, sourceLogs]);
  const visibleRows = useMemo(() => rows.filter((row) => row.role !== "status"), [rows]);

  useEffect(() => {
    if (!open || !chatRef.current) {
      return;
    }
    chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [open, visibleRows.length]);

  const isRunning = step.status === "running";
  const resolvedRunnerLabel = runnerLabel(job.runner);
  const resolvedRunnerIcon = runnerIcon(job.runner);
  const statusClass =
    step.status === "running"
      ? "bg-blue-100 text-blue-800"
      : step.status === "completed"
        ? "bg-emerald-100 text-emerald-800"
        : step.status === "failed"
          ? "bg-destructive/15 text-destructive"
          : "bg-slate-200 text-slate-700";
  const progressValue =
    job.total_annotations > 0
      ? Math.min(100, (job.completed_annotations / job.total_annotations) * 100)
      : 0;

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onClose();
        }
      }}
    >
      <DialogContent
        showCloseButton
        className="flex h-[min(92vh,940px)] w-[calc(100vw-1rem)] md:w-[50vw] max-w-none flex-col gap-0 overflow-hidden rounded-[2rem] border border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(247,248,250,0.96))] p-0 shadow-2xl shadow-slate-900/12 sm:max-w-none"
      >
        <DialogHeader className="border-b border-border/70 bg-background/76 px-5 py-4 backdrop-blur-xl sm:px-6">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary" className={statusClass}>
                {step.status}
              </Badge>
              <Badge variant="outline" className="rounded-full px-2.5 font-mono text-[11px]">
                {job.model}
              </Badge>
              {job.variant ? (
                <Badge variant="outline" className="rounded-full px-2.5 font-mono text-[11px]">
                  {job.variant}
                </Badge>
              ) : null}
              {isRunning ? (
                <Badge variant="outline" className="rounded-full px-2.5">
                  <Loader2 className="animate-spin" />
                  Live
                </Badge>
              ) : null}
            </div>

            <DialogTitle className="text-lg tracking-tight">
              {resolvedRunnerLabel} · {step.annotation_id}
            </DialogTitle>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>{job.completed_annotations}/{job.total_annotations || 0} complete</span>
              <span>{job.branch_name}</span>
              <span>{formatClock(step.started_at || job.started_at || job.created_at)}</span>
            </div>

            <Progress value={progressValue} className="h-1.5 gap-0" />
          </div>
        </DialogHeader>

        <div
          ref={chatRef}
          className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6 sm:py-6"
        >
          {visibleRows.length === 0 ? (
            <div className="mx-auto flex max-w-2xl items-center gap-3 rounded-[1.6rem] border border-border/70 bg-background/85 px-5 py-4 shadow-sm">
              {isRunning ? <Loader2 className="size-4 animate-spin text-muted-foreground" /> : <Sparkles className="size-4 text-muted-foreground" />}
              <p className="text-sm leading-6 text-muted-foreground">
                {isRunning ? `Waiting for ${resolvedRunnerLabel}...` : "No visible output for this step."}
              </p>
            </div>
          ) : (
            <div className="mx-auto flex w-full max-w-[108rem] flex-col gap-6">
              {visibleRows.map((row) => {
                if (row.role === "tool") {
                  const { headline, details } = splitToolMessage(row.text);

                  return (
                    <article
                      key={row.id}
                      className="rounded-[1.35rem] border border-border/70 bg-background/88 px-4 py-3 shadow-sm"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                          <Wrench className="size-3.5" />
                          Tool
                        </div>
                        <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                          {formatClock(row.timestamp)}
                        </span>
                      </div>
                      <p className="mt-2 whitespace-pre-wrap break-words font-mono text-[13px] font-semibold leading-6 text-foreground">
                        {headline}
                      </p>
                      {details ? (
                        <MarkdownMessage
                          content={details}
                          className="mt-2 font-mono text-xs leading-6 text-muted-foreground"
                        />
                      ) : null}
                    </article>
                  );
                }

                if (row.role === "error") {
                  return (
                    <article
                      key={row.id}
                      className="rounded-[1.5rem] border border-destructive/25 bg-destructive/6 px-4 py-4 shadow-sm"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2 text-sm font-semibold text-destructive">
                          <CircleAlert className="size-4" />
                          Error
                        </div>
                        <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-destructive/70">
                          {formatClock(row.timestamp)}
                        </span>
                      </div>
                      <MarkdownMessage content={row.text} className="mt-3 text-sm leading-6 text-foreground" />
                    </article>
                  );
                }

                return (
                  <article key={row.id} className="flex gap-3">
                    <img
                      src={resolvedRunnerIcon}
                      alt={resolvedRunnerLabel}
                      className="mt-1 size-9 shrink-0 rounded-full border border-border/70 bg-background p-1 object-contain shadow-sm"
                    />
                    <div className="min-w-0 flex-1 pt-0.5">
                      <div className="mb-2 flex items-center justify-between gap-3">
                        <div className="text-sm font-semibold text-foreground">{resolvedRunnerLabel}</div>
                        <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                          {formatClock(row.timestamp)}
                        </span>
                      </div>
                      <MarkdownMessage content={row.text} className="text-[15px] leading-7 text-foreground" />
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
