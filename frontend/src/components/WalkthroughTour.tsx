import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { ArrowLeft, ArrowRight, CircleHelp, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface WalkthroughTourProps {
  onClose: () => void;
  onStepTargetChange?: (target: string | null) => void;
}

interface WalkthroughStep {
  target: string;
  title: string;
  description: string;
  tip: string;
  panelSide?: "auto" | "left" | "right" | "top" | "bottom";
}

const WALKTHROUGH_STEPS: WalkthroughStep[] = [
  {
    target: "sessions-sidebar",
    title: "Workspace sessions",
    description:
      "Use the Workspace panel to reopen previous sessions, create new ones, and jump between active plots.",
    tip: "Pin the panel if you switch sessions often during review cycles.",
    panelSide: "right",
  },
  {
    target: "toolbar",
    title: "Model + runtime controls",
    description:
      "Select runner, model, and variant here before running fixes. You can also check Live Sync and configure Python execution.",
    tip: "If the plot looks stale, verify the Live Sync badge first.",
    panelSide: "bottom",
  },
  {
    target: "plot-canvas",
    title: "Inspect the plot",
    description:
      "Use the main canvas to review the current figure. Zoom controls stay in the top-right corner of the plot area.",
    tip: "Use + / - to zoom and Ctrl/Cmd+0 to reset while your cursor is over the plot.",
  },
  {
    target: "plot-annotator",
    title: "Draw feedback regions",
    description:
      "Drag directly on the plot to select a region. A quick feedback prompt appears so you can submit an annotation.",
    tip: "Keep feedback specific to the highlighted region for cleaner fix iterations.",
    panelSide: "left",
  },
  {
    target: "annotations-list",
    title: "Review annotations",
    description:
      "Use this list to inspect pending vs addressed feedback. Click an annotation card to check out its version and continue from that point.",
    tip: "Annotating from a non-head version automatically creates a branch so history stays intact.",
    panelSide: "left",
  },
  {
    target: "fix-panel",
    title: "Run fix queues",
    description:
      "Run Fix to process pending annotations on the active branch. The button changes to Stop while the queue is running.",
    tip: "Use the \"Fixing\" status pill over the plot to open live step output.",
    panelSide: "left",
  },
  {
    target: "session-footer",
    title: "Session context",
    description:
      "The footer shows source script path, active branch, revision count, and checked-out version id for quick verification.",
    tip: "Check this after each fix run to confirm you are still on the intended branch/version.",
    panelSide: "top",
  },
];

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(value, max));
}

export default function WalkthroughTour({ onClose, onStepTargetChange }: WalkthroughTourProps) {
  const [stepIndex, setStepIndex] = useState(0);
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);

  const currentStep = WALKTHROUGH_STEPS[stepIndex] ?? WALKTHROUGH_STEPS[0];
  const isLastStep = stepIndex >= WALKTHROUGH_STEPS.length - 1;

  useEffect(() => {
    onStepTargetChange?.(currentStep.target);
    return () => {
      onStepTargetChange?.(null);
    };
  }, [currentStep.target, onStepTargetChange]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key === "ArrowRight") {
        setStepIndex((index) => Math.min(index + 1, WALKTHROUGH_STEPS.length - 1));
        return;
      }
      if (event.key === "ArrowLeft") {
        setStepIndex((index) => Math.max(index - 1, 0));
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }

    const selector = `[data-walkthrough="${currentStep.target}"]`;
    const targetElement = document.querySelector<HTMLElement>(selector);
    if (!targetElement) {
      const frameId = window.requestAnimationFrame(() => {
        setTargetRect(null);
      });
      return () => {
        window.cancelAnimationFrame(frameId);
      };
    }

    let frameId = 0;
    let settleFrameId = 0;
    let settleTimeoutId: number | null = null;
    let resizeObserver: ResizeObserver | null = null;

    const syncRect = () => {
      window.cancelAnimationFrame(frameId);
      frameId = window.requestAnimationFrame(() => {
        setTargetRect(targetElement.getBoundingClientRect());
      });
    };

    const syncRectForTransition = (ticksRemaining: number) => {
      if (ticksRemaining <= 0) {
        return;
      }
      settleFrameId = window.requestAnimationFrame(() => {
        setTargetRect(targetElement.getBoundingClientRect());
        syncRectForTransition(ticksRemaining - 1);
      });
    };

    frameId = window.requestAnimationFrame(() => {
      targetElement.scrollIntoView({
        block: "center",
        inline: "nearest",
        behavior: "smooth",
      });
      setTargetRect(targetElement.getBoundingClientRect());
      syncRectForTransition(24);
    });

    settleTimeoutId = window.setTimeout(() => {
      syncRect();
    }, 320);

    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(() => {
        syncRect();
      });
      resizeObserver.observe(targetElement);
    }

    window.addEventListener("resize", syncRect);
    window.addEventListener("scroll", syncRect, true);
    targetElement.addEventListener("transitionend", syncRect);

    return () => {
      window.cancelAnimationFrame(frameId);
      window.cancelAnimationFrame(settleFrameId);
      if (settleTimeoutId !== null) {
        window.clearTimeout(settleTimeoutId);
      }
      resizeObserver?.disconnect();
      window.removeEventListener("resize", syncRect);
      window.removeEventListener("scroll", syncRect, true);
      targetElement.removeEventListener("transitionend", syncRect);
    };
  }, [currentStep.target, stepIndex]);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }

    const onVisibilityChange = () => {
      if (!document.hidden) {
        const selector = `[data-walkthrough="${currentStep.target}"]`;
        const targetElement = document.querySelector<HTMLElement>(selector);
        if (!targetElement) {
          return;
        }
        setTargetRect(targetElement.getBoundingClientRect());
      }
    };

    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [currentStep.target]);

  const { panelStyle, highlightStyle } = useMemo(() => {
    const viewportWidth = typeof window === "undefined" ? 1200 : window.innerWidth;
    const viewportHeight = typeof window === "undefined" ? 800 : window.innerHeight;
    const panelWidth = Math.min(420, viewportWidth - 24);
    const panelHeightEstimate = 310;
    const panelGap = 16;

    if (!targetRect) {
      return {
        panelStyle: {
          width: panelWidth,
          left: Math.round((viewportWidth - panelWidth) / 2),
          top: Math.round((viewportHeight - panelHeightEstimate) / 2),
        } satisfies CSSProperties,
        highlightStyle: undefined,
      };
    }

    const highlightPadding = 8;
    const highlightLeft = clamp(
      Math.round(targetRect.left - highlightPadding),
      4,
      Math.max(viewportWidth - 36, 4),
    );
    const highlightTop = clamp(
      Math.round(targetRect.top - highlightPadding),
      4,
      Math.max(viewportHeight - 36, 4),
    );
    const highlightWidth = Math.max(
      Math.round(targetRect.width + highlightPadding * 2),
      30,
    );
    const highlightHeight = Math.max(
      Math.round(targetRect.height + highlightPadding * 2),
      30,
    );

    const availableSpace = {
      left: targetRect.left - 12,
      right: viewportWidth - targetRect.right - 12,
      top: targetRect.top - 12,
      bottom: viewportHeight - targetRect.bottom - 12,
    };

    const canFit = (side: "left" | "right" | "top" | "bottom") => {
      if (side === "left" || side === "right") {
        return availableSpace[side] >= panelWidth + panelGap;
      }
      return availableSpace[side] >= panelHeightEstimate + panelGap;
    };

    const preferredSide = currentStep.panelSide && currentStep.panelSide !== "auto"
      ? currentStep.panelSide
      : null;

    const candidateSides: Array<"left" | "right" | "top" | "bottom"> = [
      "right",
      "left",
      "bottom",
      "top",
    ];

    const sortedByRoom = [...candidateSides].sort(
      (a, b) => availableSpace[b] - availableSpace[a],
    );

    const sideOrder = preferredSide
      ? [preferredSide, ...sortedByRoom.filter((side) => side !== preferredSide)]
      : sortedByRoom;

    const chosenSide = sideOrder.find((side) => canFit(side)) ?? sideOrder[0] ?? "bottom";

    const centeredLeft = clamp(
      targetRect.left + targetRect.width / 2 - panelWidth / 2,
      12,
      Math.max(viewportWidth - panelWidth - 12, 12),
    );
    const centeredTop = clamp(
      targetRect.top + targetRect.height / 2 - panelHeightEstimate / 2,
      12,
      Math.max(viewportHeight - panelHeightEstimate - 12, 12),
    );

    let panelLeft = centeredLeft;
    let panelTop = centeredTop;

    if (chosenSide === "left") {
      panelLeft = clamp(
        targetRect.left - panelWidth - panelGap,
        12,
        Math.max(viewportWidth - panelWidth - 12, 12),
      );
      panelTop = centeredTop;
    } else if (chosenSide === "right") {
      panelLeft = clamp(
        targetRect.right + panelGap,
        12,
        Math.max(viewportWidth - panelWidth - 12, 12),
      );
      panelTop = centeredTop;
    } else if (chosenSide === "top") {
      panelLeft = centeredLeft;
      panelTop = clamp(
        targetRect.top - panelHeightEstimate - panelGap,
        12,
        Math.max(viewportHeight - panelHeightEstimate - 12, 12),
      );
    } else {
      panelLeft = centeredLeft;
      panelTop = clamp(
        targetRect.bottom + panelGap,
        12,
        Math.max(viewportHeight - panelHeightEstimate - 12, 12),
      );
    }

    return {
      panelStyle: {
        width: panelWidth,
        left: Math.round(panelLeft),
        top: Math.round(panelTop),
      } satisfies CSSProperties,
      highlightStyle: {
        left: highlightLeft,
        top: highlightTop,
        width: highlightWidth,
        height: highlightHeight,
        borderRadius: Math.min(16, Math.max(8, Math.round(Math.min(highlightWidth, highlightHeight) / 8))),
        boxShadow: "0 0 0 9999px rgba(6, 10, 16, 0.55)",
      } satisfies CSSProperties,
    };
  }, [currentStep.panelSide, targetRect]);

  return (
    <div className="fixed inset-0 z-[80]">
      {highlightStyle ? (
        <div
          aria-hidden
          className="pointer-events-none absolute border-2 border-foreground/90 bg-transparent transition-all duration-200"
          style={highlightStyle}
        />
      ) : (
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-black/55" />
      )}

      <Card
        role="dialog"
        aria-modal="true"
        className="absolute border border-border/90 bg-popover shadow-2xl"
        style={panelStyle}
      >
        <CardHeader className="space-y-2 pb-3">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <CardDescription>
                Step {stepIndex + 1} of {WALKTHROUGH_STEPS.length}
              </CardDescription>
              <CardTitle className="text-base">{currentStep.title}</CardTitle>
            </div>

            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              onClick={onClose}
              aria-label="Close walkthrough"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <p className="text-sm leading-6 text-foreground">{currentStep.description}</p>

          <div className="rounded-md border border-border/80 bg-muted/35 px-2.5 py-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1 font-medium text-foreground">
              <CircleHelp className="h-3.5 w-3.5" />
              Tip
            </span>
            <p className="mt-1 leading-5">{currentStep.tip}</p>
          </div>

          {!targetRect ? (
            <p className="text-xs text-muted-foreground">
              This section is currently off-screen or unavailable. Continue to the next step.
            </p>
          ) : null}

          <div className="flex items-center justify-between gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={onClose}>
              Skip walkthrough
            </Button>

            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={stepIndex === 0}
                onClick={() => setStepIndex((index) => Math.max(index - 1, 0))}
                className="gap-1"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                Back
              </Button>

              <Button
                type="button"
                size="sm"
                onClick={() => {
                  if (isLastStep) {
                    onClose();
                    return;
                  }
                  setStepIndex((index) => Math.min(index + 1, WALKTHROUGH_STEPS.length - 1));
                }}
                className="gap-1"
              >
                {isLastStep ? "Finish" : "Next"}
                {!isLastStep ? <ArrowRight className="h-3.5 w-3.5" /> : null}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
