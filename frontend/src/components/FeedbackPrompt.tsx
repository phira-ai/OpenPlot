import { useState, useRef, useEffect, useCallback } from "react";
import { X } from "lucide-react";
import type { RegionInfo } from "../types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const SUGGESTIONS = [
  "Font too small",
  "Overlapping text",
  "Wrong color",
  "Move this",
  "Remove this",
  "Too crowded",
  "Hard to read",
];

interface FeedbackPromptProps {
  regionInfo?: RegionInfo;
  anchorRect: DOMRect;
  onSubmit: (feedback: string) => void;
  onCancel: () => void;
}

export default function FeedbackPrompt({
  anchorRect,
  onSubmit,
  onCancel,
}: FeedbackPromptProps) {
  const [text, setText] = useState("");
  const [cardHeight, setCardHeight] = useState(220);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = cardRef.current;
    if (!node || typeof ResizeObserver === "undefined") {
      return;
    }

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }
      const nextHeight = Math.round(entry.contentRect.height);
      if (nextHeight > 0) {
        setCardHeight((prev) => (prev === nextHeight ? prev : nextHeight));
      }
    });

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onCancel]);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (cardRef.current && !cardRef.current.contains(e.target as Node)) {
        onCancel();
      }
    };
    const timer = setTimeout(() => {
      window.addEventListener("mousedown", handleClick);
    }, 100);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("mousedown", handleClick);
    };
  }, [onCancel]);

  const handleSubmit = useCallback(
    (value?: string) => {
      const feedback = (value ?? text).trim();
      if (feedback) onSubmit(feedback);
    },
    [text, onSubmit],
  );

  const cardStyle = (() => {
    const gap = 10;
    const viewportPadding = 10;
    const viewportW = window.innerWidth;
    const viewportH = window.innerHeight;
    const cardWidth = Math.min(380, viewportW - viewportPadding * 2);

    const topBelow = anchorRect.bottom + gap;
    const topAbove = anchorRect.top - cardHeight - gap;
    const fitsBelow = topBelow + cardHeight <= viewportH - viewportPadding;
    const fitsAbove = topAbove >= viewportPadding;

    let top: number;
    if (fitsBelow) {
      top = topBelow;
    } else if (fitsAbove) {
      top = topAbove;
    } else {
      const overlappedTop = anchorRect.top + (anchorRect.height - cardHeight) / 2;
      top = Math.max(
        viewportPadding,
        Math.min(overlappedTop, viewportH - cardHeight - viewportPadding),
      );
    }

    let left = anchorRect.left + anchorRect.width / 2 - cardWidth / 2;
    left = Math.max(
      viewportPadding,
      Math.min(left, viewportW - cardWidth - viewportPadding),
    );

    return { top, left, width: cardWidth };
  })();

  return (
    <div
      ref={cardRef}
      className="fixed z-50"
      style={cardStyle}
    >
      <Card className="relative border border-border/90 bg-popover/96 shadow-lg backdrop-blur-sm">
        <Button
          type="button"
          onClick={onCancel}
          variant="ghost"
          size="icon-xs"
          className="absolute right-2 top-2 text-muted-foreground"
        >
          <X className="h-3.5 w-3.5" />
        </Button>

        <CardContent className="space-y-2.5 px-3 pb-3 pt-2">
          <div className="flex flex-wrap gap-1.5 pr-7">
            {SUGGESTIONS.map((s) => (
              <Button
                key={s}
                type="button"
                onClick={() => handleSubmit(s)}
                variant="outline"
                size="xs"
              >
                {s}
              </Button>
            ))}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSubmit();
            }}
            className="flex gap-2"
          >
            <Input
              autoFocus
              type="text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Describe the issue..."
            />
            <Button type="submit" disabled={!text.trim()}>
              Add
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
