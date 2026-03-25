import type { PlotModeChatMessage, PlotModeQuestionItem } from "../../types";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

function questionTabLabel(question: PlotModeQuestionItem, index: number): string {
  if (question.title?.trim()) {
    return question.title.trim();
  }
  return `Question ${index + 1}`;
}

export default function PlotModeQuestionCard({
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
    if (!completed || !isPendingQuestionSet) {
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
                            <span className="text-xs text-muted-foreground whitespace-normal break-words">
                              {option.description}
                            </span>
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
