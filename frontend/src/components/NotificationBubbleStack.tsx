import { AlertCircle, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface NotificationBubble {
  id: string;
  message: string;
  tone?: "error";
}

interface NotificationBubbleStackProps {
  notifications: NotificationBubble[];
  onDismiss: (id: string) => void;
}

export default function NotificationBubbleStack({
  notifications,
  onDismiss,
}: NotificationBubbleStackProps) {
  if (notifications.length === 0) {
    return null;
  }

  return (
    <div className="pointer-events-none fixed right-4 top-4 z-[120] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
      {notifications.map((notification) => (
        <div
          key={notification.id}
          className={cn(
            "pointer-events-auto flex items-start gap-3 rounded-[1.35rem] border px-4 py-3 shadow-2xl backdrop-blur-xl",
            notification.tone === "error"
              ? "border-destructive/20 bg-[linear-gradient(180deg,rgba(255,247,247,0.96),rgba(255,240,240,0.94))] text-destructive shadow-rose-950/10"
              : "border-border/80 bg-background/95 text-foreground",
          )}
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <p className="min-w-0 flex-1 text-sm leading-5">{notification.message}</p>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            className="-mr-1 -mt-1 rounded-full text-current hover:bg-black/5"
            onClick={() => onDismiss(notification.id)}
            aria-label="Dismiss notification"
          >
            <X className="size-3.5" />
          </Button>
        </div>
      ))}
    </div>
  );
}
