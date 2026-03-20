import { Loader2 } from "lucide-react";

import MarkdownMessage from "@/components/MarkdownMessage";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { runnerLabel } from "@/lib/runners";
import type { RunnerStatusEntry } from "@/types";

interface RunnerAuthDialogProps {
  open: boolean;
  entry: RunnerStatusEntry | null;
  launching: boolean;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => Promise<void> | void;
}

function authStepsMarkdown(entry: RunnerStatusEntry): string {
  const label = runnerLabel(entry.runner);
  const command = entry.auth_command ? `\`${entry.auth_command}\`` : `the ${label} sign-in command`;

  if (entry.runner === "codex") {
    return [
      `1. OpenPlot will open Terminal and run ${command}.`,
      "2. Codex will start in that Terminal window. Follow the prompts to sign in. If Codex asks you to finish first-run setup or initialize models, keep going until it says it is ready.",
      "3. When Codex shows that sign-in is complete, you can close Terminal or stop Codex with `Ctrl+C`.",
      "4. Return to OpenPlot and click **Refresh**.",
    ].join("\n\n");
  }

  if (entry.runner === "claude") {
    return [
      `1. OpenPlot will open Terminal and run ${command}.`,
      "2. Claude Code will start in that Terminal window. Follow the sign-in prompts until Claude Code says you are signed in.",
      "3. When sign-in is complete, you can close Terminal.",
      "4. Return to OpenPlot and click **Refresh**.",
    ].join("\n\n");
  }

  return [
    `1. OpenPlot will open Terminal and run ${command}.`,
    "2. OpenCode will start in that Terminal window. Follow the provider sign-in prompts. If it asks you to finish first-run setup or choose a provider or model, complete that there.",
    "3. When OpenCode says sign-in is complete, you can close Terminal or stop OpenCode with `Ctrl+C`.",
    "4. Return to OpenPlot and click **Refresh**.",
  ].join("\n\n");
}

export default function RunnerAuthDialog({
  open,
  entry,
  launching,
  error,
  onOpenChange,
  onConfirm,
}: RunnerAuthDialogProps) {
  if (!entry) {
    return null;
  }

  const label = runnerLabel(entry.runner);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl p-0" showCloseButton={!launching}>
        <DialogHeader className="border-b border-border/70 px-6 py-5">
          <DialogTitle>Authenticate {label}</DialogTitle>
          <DialogDescription>
            OpenPlot will open Terminal for you. Follow the steps there, then come back here.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 px-6 py-5">
          <div className="rounded-2xl border border-border/70 bg-muted/20 p-4">
            <MarkdownMessage
              content={authStepsMarkdown(entry)}
              className="text-sm leading-6 text-foreground"
            />
          </div>

          {error ? (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          ) : null}
        </div>

        <DialogFooter className="items-center gap-3 px-6 py-4 sm:justify-between">
          <div className="text-xs text-muted-foreground">
            After sign-in finishes in Terminal, return to OpenPlot and click Refresh.
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={launching}
            >
              Cancel
            </Button>
            <Button type="button" onClick={() => void onConfirm()} disabled={launching}>
              {launching ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Opening Terminal...
                </>
              ) : (
                "Open Terminal"
              )}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
