import { ExternalLink, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { runnerLabel } from "@/lib/runners";
import type { FixRunner, RunnerStatusEntry } from "@/types";

import claudeCodeLogo from "../../claude-code.svg";
import codexLogo from "../../codex.svg";
import opencodeLogo from "../../opencode.svg";

function runnerLogo(runner: FixRunner): string {
  if (runner === "codex") {
    return codexLogo;
  }
  if (runner === "claude") {
    return claudeCodeLogo;
  }
  return opencodeLogo;
}

function runnerSummary(runner: FixRunner): string {
  if (runner === "claude") {
    return "Nice if you use Claude model families. It also optionally supports other providers.";
  }
  if (runner === "codex") {
    return "Nice if you use GPT model families.";
  }
  return "A flexible open-source runner with broad provider support.";
}

function panelClassName(extra?: string): string {
  return `rounded-md border border-border/70 bg-muted/20 px-3 py-2 ${extra ?? ""}`.trim();
}

interface RunnerManagerProps {
  runners: RunnerStatusEntry[];
  loading: boolean;
  error: string | null;
  blocking?: boolean;
  onInstall: (runner: FixRunner) => Promise<void> | void;
  onAuthenticate: (entry: RunnerStatusEntry) => Promise<void> | void;
  onOpenGuide: (url: string) => Promise<void> | void;
  onRefresh: () => Promise<void> | void;
}

export default function RunnerManager({
  runners,
  loading,
  error,
  blocking = false,
  onInstall,
  onAuthenticate,
  onOpenGuide,
  onRefresh,
}: RunnerManagerProps) {
  const authGateActive = blocking && runners.some((entry) => entry.status === "installed_needs_auth");
  const activeInstallRunner =
    runners.find((entry) => entry.install_job?.state === "queued" || entry.install_job?.state === "running")
      ?.runner ?? null;

  return (
    <div className={blocking ? "flex min-h-dvh items-center justify-center bg-background p-4" : "w-full"}>
      <Card
        className={
          blocking
            ? "w-full max-w-6xl border border-border/80 bg-card shadow-sm"
            : "border border-border/80 bg-card shadow-sm"
        }
      >
        <CardHeader className="gap-3 border-b border-border/70 pb-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle>
                {blocking
                  ? authGateActive
                    ? "Authenticate a runner"
                    : "No runners available"
                  : "Manage runners"}
              </CardTitle>
              <CardDescription className="max-w-4xl text-sm leading-6">
                {authGateActive
                  ? "OpenPlot can help you finish sign-in for one runner. Complete the terminal steps, come back here, and click Refresh when you are done."
                  : "Choose a runner for OpenPlot. Install one here if needed, or finish sign-in for an installed runner and then refresh this page."}
              </CardDescription>
            </div>

            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void onRefresh();
              }}
              disabled={loading}
              className="gap-1.5"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </Button>
          </div>

          {error ? (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          ) : null}
        </CardHeader>

        <CardContent className="p-5">
          <div className="grid gap-4 lg:grid-cols-3">
            {runners.map((entry) => {
              const installDisabled =
                entry.primary_action !== "install" ||
                loading ||
                (activeInstallRunner !== null && activeInstallRunner !== entry.runner);
              const logs = entry.install_job?.logs ?? [];
              const latestLog = logs.length > 0 ? logs[logs.length - 1] : null;

              return (
                <div
                  key={entry.runner}
                  className="flex h-full flex-col rounded-2xl border border-border/80 bg-background/70 p-5 shadow-sm"
                >
                  <div className="flex min-h-[6.5rem] flex-col gap-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <div className="flex h-11 w-14 shrink-0 items-center justify-center rounded-xl border border-border/80 bg-background px-2">
                          <img
                            src={runnerLogo(entry.runner)}
                            alt={runnerLabel(entry.runner)}
                            className="h-7 w-full object-contain"
                          />
                        </div>
                        <div className="min-w-0">
                          <h3 className="text-sm font-semibold text-foreground">
                            {runnerLabel(entry.runner)}
                          </h3>
                        </div>
                      </div>
                      <Badge variant="secondary" className="shrink-0 bg-muted text-foreground">
                        {entry.status_label}
                      </Badge>
                    </div>

                    <p className="max-w-none text-xs leading-5 text-muted-foreground">
                      {runnerSummary(entry.runner)}
                    </p>
                  </div>

                  <div className="mt-4 space-y-2 text-xs text-muted-foreground">
                    <div className={panelClassName()}>
                      <span className="font-semibold text-foreground">Primary action:</span>{" "}
                      {entry.primary_action_label}
                    </div>

                    {entry.executable_path ? (
                      <div className={panelClassName("min-h-[4.5rem]")}>
                        <div className="font-semibold text-foreground">Detected executable</div>
                        <div className="mt-1 break-all font-mono">{entry.executable_path}</div>
                      </div>
                    ) : null}

                    {entry.auth_instructions ? (
                      <div className={panelClassName()}>
                        <div className="font-semibold text-foreground">Authentication</div>
                        <div className="mt-1 whitespace-pre-wrap break-words">
                          {entry.auth_instructions}
                        </div>
                        {entry.auth_command ? (
                          <div className="mt-2 break-all font-mono text-foreground">
                            {entry.auth_command}
                          </div>
                        ) : null}
                      </div>
                    ) : null}

                    {latestLog ? (
                      <div className={panelClassName()}>
                        <div className="font-semibold text-foreground">Latest status</div>
                        <div className="mt-1 max-h-28 overflow-y-auto whitespace-pre-wrap break-words pr-1">
                          {latestLog}
                        </div>
                      </div>
                    ) : null}

                    {entry.install_job?.error ? (
                      <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-destructive">
                        <div className="max-h-28 overflow-y-auto whitespace-pre-wrap break-words pr-1">
                          {entry.install_job.error}
                        </div>
                      </div>
                    ) : null}
                  </div>

                  <div className="mt-auto flex flex-wrap gap-2 pt-4">
                    {entry.primary_action === "install" ? (
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => {
                          void onInstall(entry.runner);
                        }}
                        disabled={installDisabled}
                      >
                        {entry.primary_action_label}
                      </Button>
                    ) : entry.primary_action === "authenticate" ? (
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => {
                          void onAuthenticate(entry);
                        }}
                        disabled={loading}
                      >
                        {entry.primary_action_label}
                      </Button>
                    ) : entry.primary_action === "guide" ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          void onOpenGuide(entry.guide_url);
                        }}
                      >
                        {entry.primary_action_label}
                      </Button>
                    ) : (
                      <Button type="button" size="sm" variant="outline" disabled>
                        {entry.primary_action_label}
                      </Button>
                    )}

                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="gap-1.5"
                      onClick={() => {
                        void onOpenGuide(entry.guide_url);
                      }}
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                      Official docs
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
