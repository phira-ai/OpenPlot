import { useEffect } from "react";
import { BookOpen, PlayCircle, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface WalkthroughPromptModalProps {
  open: boolean;
  mode: "annotation" | "plot";
  onStart: () => void;
  onDismiss: () => void;
  onDontShowAgain: () => void;
}

export default function WalkthroughPromptModal({
  open,
  mode,
  onStart,
  onDismiss,
  onDontShowAgain,
}: WalkthroughPromptModalProps) {
  const content =
    mode === "plot"
      ? {
          description:
            "We can guide you through source setup, draft refinement, and the handoff to annotation mode.",
          bullets: [
            "Attach source files and script context quickly.",
            "Draft and refine plot outputs in the conversation timeline.",
            "Move to annotation mode when the draft is ready.",
          ],
        }
      : {
          description:
            "We can guide you through the full OpenPlot workflow in about a minute.",
          bullets: [
            "See how workspace sessions, branches, and versions connect.",
            "Learn where to inspect and annotate the plot quickly.",
            "Run and monitor fix queues from start to finish.",
          ],
        };

  useEffect(() => {
    if (!open) {
      return;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onDismiss();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [onDismiss, open]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-[75] flex items-center justify-center bg-black/45 p-4"
      onClick={onDismiss}
    >
      <Card
        className="w-full max-w-xl border border-border/85 bg-popover shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <CardHeader className="space-y-2 pb-3">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2 text-base">
                <BookOpen className="h-4 w-4" />
                Take a quick walkthrough?
              </CardTitle>
              <CardDescription>{content.description}</CardDescription>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              onClick={onDismiss}
              aria-label="Close walkthrough prompt"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <ul className="space-y-1.5 text-sm text-muted-foreground">
            {content.bullets.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" onClick={onStart} className="gap-1.5">
              <PlayCircle className="h-3.5 w-3.5" />
              Start walkthrough
            </Button>
            <Button type="button" variant="outline" onClick={onDismiss}>
              Not now
            </Button>
            <Button type="button" variant="ghost" onClick={onDontShowAgain}>
              Don&apos;t show again
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
