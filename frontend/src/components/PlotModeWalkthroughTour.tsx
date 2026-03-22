import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, Bot, CircleHelp, X, Zap } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface PlotModeWalkthroughTourProps {
  onClose: () => void;
  onStepTargetChange?: (target: string | null) => void;
}

interface WalkthroughStep {
  target: string;
  title: string;
  description: ReactNode;
  tip: ReactNode;
  panelSide?: "auto" | "left" | "right" | "top" | "bottom";
  panelOffsetY?: number;
}

const WALKTHROUGH_STEPS: WalkthroughStep[] = [
  {
    target: "sessions-sidebar",
    title: "Workspace sessions",
    description:
      "Use the Workspace panel to reopen previous sessions, create new ones, and switch between drafting contexts.",
    tip: "Pin the panel if you frequently compare multiple draft workspaces.",
    panelSide: "right",
  },
  {
    target: "toolbar",
    title: "Model + runtime controls",
    description:
      "Select runner, model, and variant before you generate or refine a draft. Live Sync and Python runtime controls are here too.",
    tip: "If updates seem delayed, verify the Live Sync badge first.",
    panelSide: "bottom",
  },
  {
    target: "plot-mode-preview",
    title: "Preview panel",
    description:
      "Inspect the latest generated plot preview in this canvas area before deciding what to change next.",
    tip: "Use zoom controls on the preview to inspect details and spot mistakes quickly.",
  },
  {
    target: "plot-mode-sources",
    title: "Attach sources",
    description:
      "Open Sources to add data files or a script path. These files provide context for each drafting round.",
    tip: "Attach the plotting script when you want edits grounded in existing code.",
    panelSide: "top",
  },
  {
    target: "plot-mode-sidebar",
    title: "Drafting timeline",
    description:
      "This panel shows the full drafting conversation, status updates, questions, and table previews from OpenPlot.",
    tip: "Answer pending questions directly in-line to unblock the next draft.",
    panelSide: "left",
  },
  {
    target: "plot-mode-mode-switch",
    title: "Quick vs auto mode",
    description: (
      <>
        <span className="inline-flex items-center gap-1">
          <Zap className="h-3.5 w-3.5" />
          Quick mode
        </span>{" "}
        for fast visualization. <span className="inline-flex items-center gap-1"><Bot className="h-3.5 w-3.5" />Auto mode</span>{" "}
        lets the agent self-iterate toward the final result.
      </>
    ),
    tip: "Use Quick when exploring. Use Auto when the goal is clear.",
    panelSide: "left",
    panelOffsetY: -88,
  },
  {
    target: "plot-mode-composer",
    title: "Prompt composer",
    description:
      "Describe the chart you want in the composer, then send to run another draft iteration.",
    tip: "Be specific about encodings, labels, ranges, and style to reduce back-and-forth.",
    panelSide: "left",
  },
  {
    target: "plot-mode-annotate",
    title: "Move to annotate",
    description:
      "When the draft is ready, click Annotate to switch into annotation mode for region-level feedback.",
    tip: "Use this after the main structure looks right, then refine with visual annotations.",
    panelSide: "top",
  },
  {
    target: "plot-mode-footer",
    title: "Drafting status",
    description:
      "The footer confirms how many files are attached and reminds you to finalize the draft before annotation.",
    tip: "Quickly verify attached file count before sending prompts that depend on specific sources.",
    panelSide: "top",
  },
];

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(value, max));
}

export default function PlotModeWalkthroughTour({
  onClose,
  onStepTargetChange,
}: PlotModeWalkthroughTourProps) {
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

    const offsetY = currentStep.panelOffsetY ?? 0;

    return {
      panelStyle: {
        width: panelWidth,
        left: Math.round(panelLeft),
        top: Math.round(
          clamp(panelTop + offsetY, 12, Math.max(viewportHeight - panelHeightEstimate - 12, 12)),
        ),
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
  }, [currentStep.panelOffsetY, currentStep.panelSide, targetRect]);

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
