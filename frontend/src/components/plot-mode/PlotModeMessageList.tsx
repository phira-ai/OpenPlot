import type { ReactNode, RefObject } from "react";
import { CircleAlert, Loader2 } from "lucide-react";

import type { PlotModeChatMessage, PlotModeQuestionAnswerInput } from "../../types";
import MarkdownMessage from "@/components/MarkdownMessage";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import openplotIcon from "../../../openplot-icon.png";
import PlotModeQuestionCard from "./PlotModeQuestionCard";

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
    align === "start" ? "left-0" : align === "end" ? "right-0" : "left-1/2 -translate-x-1/2";

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
      <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">You</div>
      <HoverTimestamp timestamp={timestamp} align="end">
        <div className="w-fit max-w-[92%] rounded-[2rem] rounded-br-[1.4rem] bg-[#171b22] px-4 py-2.5 text-white shadow-xl shadow-slate-900/14 sm:max-w-[44rem]">
          <p className="whitespace-pre-wrap break-words text-[14px] leading-6">{content}</p>
        </div>
      </HoverTimestamp>
    </article>
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
    answers: PlotModeQuestionAnswerInput[],
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
            {metadata.table_caption ? <p className="text-sm text-muted-foreground">{metadata.table_caption}</p> : null}
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
                    <td
                      key={`${entry.id}:row:${rowIndex}:cell:${cellIndex}`}
                      className="border-b border-border/60 px-3 py-2 align-top text-muted-foreground"
                    >
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
      <PlotModeQuestionCard
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

export default function PlotModeMessageList({
  messagesRef,
  messages,
  desktopViewport,
  touchInput,
  showComposer,
  sendingMessage,
  hasLiveRefiningStatus,
  currentPendingQuestionSetId,
  activeQuestionId,
  onActiveQuestionIdChange,
  questionAnswers,
  onQuestionAnswerChange,
  onAnswerQuestion,
  pendingUserMessage,
}: {
  messagesRef: RefObject<HTMLDivElement | null>;
  messages: PlotModeChatMessage[];
  desktopViewport: boolean;
  touchInput: boolean;
  showComposer: boolean;
  sendingMessage: boolean;
  hasLiveRefiningStatus: boolean;
  currentPendingQuestionSetId: string | null;
  activeQuestionId: string;
  onActiveQuestionIdChange: (value: string) => void;
  questionAnswers: Record<string, { optionIds: string[]; text: string }>;
  onQuestionAnswerChange: (questionId: string, next: { optionIds: string[]; text: string }) => void;
  onAnswerQuestion: (
    questionSetId: string,
    answers: PlotModeQuestionAnswerInput[],
  ) => Promise<void>;
  pendingUserMessage: string | null;
}) {
  return (
    <div
      ref={messagesRef}
      data-plot-messages
      className={cn(
        "flex h-full min-h-0 flex-col gap-6 overflow-y-auto px-4 py-5 sm:px-5",
        desktopViewport && !touchInput ? (showComposer ? "pb-[10rem]" : "pb-16") : "pb-6",
      )}
    >
      {messages.map((entry) => {
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
                    currentPendingQuestionSetId={currentPendingQuestionSetId}
                    activeQuestionId={activeQuestionId}
                    onActiveQuestionIdChange={onActiveQuestionIdChange}
                    questionAnswers={questionAnswers}
                    onQuestionAnswerChange={onQuestionAnswerChange}
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
                      currentPendingQuestionSetId={currentPendingQuestionSetId}
                      activeQuestionId={activeQuestionId}
                      onActiveQuestionIdChange={onActiveQuestionIdChange}
                      questionAnswers={questionAnswers}
                      onQuestionAnswerChange={onQuestionAnswerChange}
                      onAnswerQuestion={onAnswerQuestion}
                    />
                  </div>
                </HoverTimestamp>
              </div>
            </article>
          </div>
        );
      })}

      {pendingUserMessage ? <UserMessageBubble content={pendingUserMessage} /> : null}

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
  );
}
