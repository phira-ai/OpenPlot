import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  CircleOff,
  ExternalLink,
  Link as LinkIcon,
  RefreshCw,
  RotateCcw,
  Save,
} from "lucide-react";

import type {
  Branch,
  PythonInterpreterMode,
  PythonInterpreterState,
  RunnerStatusEntry,
  RunnerStatusState,
  UpdateStatusState,
} from "../types";
import RunnerManager from "./RunnerManager";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "annotation" | "plot";
  branches?: Branch[];
  activeBranchId?: string;
  checkedOutVersionId?: string;
  connected: boolean;
  wsUrl: string;
  reconnectAttempts: number;
  lastConnectedAt: string | null;
  lastDisconnectedAt: string | null;
  runnerStatus: RunnerStatusState | null;
  runnerStatusLoading: boolean;
  runnerStatusError: string | null;
  onInstallRunner: (runner: RunnerStatusEntry["runner"]) => Promise<void> | void;
  onAuthenticateRunner: (entry: RunnerStatusEntry) => Promise<void> | void;
  onOpenRunnerGuide: (url: string) => Promise<void> | void;
  onRefreshRunners: () => Promise<void> | void;
  pythonInterpreterState: PythonInterpreterState | null;
  pythonInterpreterLoading: boolean;
  pythonInterpreterError: string | null;
  onRefreshPythonInterpreter: () => Promise<void> | void;
  onSavePythonInterpreter: (
    mode: PythonInterpreterMode,
    path?: string,
  ) => Promise<void> | void;
  updateStatus: UpdateStatusState | null;
  updateStatusLoading: boolean;
  onRefreshUpdateStatus: () => Promise<UpdateStatusState | void> | void;
  onOpenReleasePage: (url: string) => Promise<void> | void;
}

export default function SettingsDialog({
  open,
  onOpenChange,
  mode,
  branches,
  activeBranchId,
  checkedOutVersionId,
  connected,
  wsUrl,
  reconnectAttempts,
  lastConnectedAt,
  lastDisconnectedAt,
  runnerStatus,
  runnerStatusLoading,
  runnerStatusError,
  onInstallRunner,
  onAuthenticateRunner,
  onOpenRunnerGuide,
  onRefreshRunners,
  pythonInterpreterState,
  pythonInterpreterLoading,
  pythonInterpreterError,
  onRefreshPythonInterpreter,
  onSavePythonInterpreter,
  updateStatus,
  updateStatusLoading,
  onRefreshUpdateStatus,
  onOpenReleasePage,
}: SettingsDialogProps) {
  const [interpreterModeDraft, setInterpreterModeDraft] = useState<PythonInterpreterMode>("builtin");
  const [manualPathDraft, setManualPathDraft] = useState("");
  const [isSavingInterpreter, setIsSavingInterpreter] = useState(false);
  const [interpreterActionError, setInterpreterActionError] = useState<string | null>(null);
  const [updateActionError, setUpdateActionError] = useState<string | null>(null);

  const branchList = useMemo(() => branches ?? [], [branches]);
  const activeBranchName = useMemo(
    () => branchList.find((branch) => branch.id === activeBranchId)?.name ?? "Unknown",
    [activeBranchId, branchList],
  );
  const availablePackages = useMemo(
    () => pythonInterpreterState?.available_packages ?? [],
    [pythonInterpreterState],
  );
  const runtimeSourceLabel = useMemo(() => {
    const source = pythonInterpreterState?.resolved_source || "";
    if (source === "manual") {
      return "manual path";
    }
    if (source === "built-in") {
      return "default runtime";
    }
    return source || "unknown source";
  }, [pythonInterpreterState]);
  const formattedLastConnectedAt = useMemo(
    () =>
      lastConnectedAt ? new Date(lastConnectedAt).toLocaleString() : "No successful connection yet",
    [lastConnectedAt],
  );
  const formattedLastDisconnectedAt = useMemo(
    () =>
      lastDisconnectedAt
        ? new Date(lastDisconnectedAt).toLocaleString()
        : "No disconnections recorded",
    [lastDisconnectedAt],
  );
  const formattedUpdateCheckedAt = useMemo(
    () =>
      updateStatus?.checked_at ? new Date(updateStatus.checked_at).toLocaleString() : "Not checked yet",
    [updateStatus?.checked_at],
  );

  useEffect(() => {
    if (!open) {
      return;
    }
    setInterpreterModeDraft(pythonInterpreterState?.mode ?? "builtin");
    setManualPathDraft(pythonInterpreterState?.configured_path ?? "");
    setInterpreterActionError(null);
    setUpdateActionError(null);
  }, [open, pythonInterpreterState]);

  const handleSaveInterpreter = async () => {
    if (interpreterModeDraft === "manual" && !manualPathDraft.trim()) {
      setInterpreterActionError("Please enter a Python executable path.");
      return;
    }

    setIsSavingInterpreter(true);
    setInterpreterActionError(null);

    try {
      await onSavePythonInterpreter(interpreterModeDraft, manualPathDraft);
      await onRefreshPythonInterpreter();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save interpreter setting";
      setInterpreterActionError(message);
    } finally {
      setIsSavingInterpreter(false);
    }
  };

  const handleOpenReleasePage = async () => {
    const latestReleaseUrl = updateStatus?.latest_release_url?.trim() || "";
    if (!latestReleaseUrl) {
      return;
    }
    setUpdateActionError(null);
    try {
      await onOpenReleasePage(latestReleaseUrl);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to open release page";
      setUpdateActionError(message);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] max-w-6xl overflow-hidden p-0" showCloseButton>
        <DialogHeader className="border-b border-border/70 px-6 py-5">
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>
            Manage runners, connectivity, Python execution, and update status in one place.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="runners" className="min-h-0 gap-0 px-6 pb-6 pt-5">
          <TabsList variant="line" className="w-full justify-start gap-2 border-b border-border/70 bg-transparent p-0 pb-2">
            <TabsTrigger value="runners">Runners</TabsTrigger>
            <TabsTrigger value="live-sync">Live Sync</TabsTrigger>
            <TabsTrigger value="python">Python</TabsTrigger>
            <TabsTrigger value="update">Update</TabsTrigger>
          </TabsList>

          <TabsContent value="runners" className="min-h-0 overflow-y-auto pt-4">
            <RunnerManager
              runners={runnerStatus?.runners ?? []}
              loading={runnerStatusLoading}
              error={runnerStatusError}
              onInstall={onInstallRunner}
              onAuthenticate={onAuthenticateRunner}
              onOpenGuide={onOpenRunnerGuide}
              onRefresh={onRefreshRunners}
            />
          </TabsContent>

          <TabsContent value="live-sync" className="space-y-4 overflow-y-auto pt-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-semibold text-foreground">Connection Information</h3>
                <p className="mt-1 text-sm text-muted-foreground">Live WebSocket status for OpenPlot sync.</p>
              </div>
              <Badge
                variant="secondary"
                className={connected ? "bg-foreground/10 text-foreground" : "bg-destructive/10 text-destructive"}
              >
                {connected ? (
                  <><CheckCircle2 className="h-3.5 w-3.5" /> Connected</>
                ) : (
                  <><CircleOff className="h-3.5 w-3.5" /> Disconnected</>
                )}
              </Badge>
            </div>

            <div className="space-y-2 rounded-xl border border-border/80 bg-muted/15 p-4">
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <LinkIcon className="h-3.5 w-3.5" />
                Endpoint
              </div>
              <code className="block rounded-md border border-border/80 bg-background px-3 py-2 font-mono text-xs text-foreground break-all">
                {wsUrl || "Unavailable"}
              </code>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-xl border border-border/80 bg-muted/15 p-4 text-sm">
                <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2">
                  <span className="text-muted-foreground">Mode</span>
                  <span className="text-right text-foreground">{mode}</span>

                  {mode === "annotation" ? (
                    <>
                      <span className="text-muted-foreground">Active branch</span>
                      <span className="text-right text-foreground">{activeBranchName}</span>

                      <span className="text-muted-foreground">Checked out</span>
                      <span className="truncate text-right font-mono text-foreground">
                        {checkedOutVersionId || "<none>"}
                      </span>
                    </>
                  ) : null}

                  <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                    <RotateCcw className="h-3.5 w-3.5" />
                    Reconnect attempts
                  </span>
                  <span className="text-right font-medium text-foreground">{reconnectAttempts}</span>
                </div>
              </div>

              <div className="rounded-xl border border-border/80 bg-muted/15 p-4 text-sm">
                <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2">
                  <span className="text-muted-foreground">Last connected</span>
                  <span className="text-right text-foreground">{formattedLastConnectedAt}</span>

                  <span className="text-muted-foreground">Last disconnected</span>
                  <span className="text-right text-foreground">{formattedLastDisconnectedAt}</span>
                </div>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="python" className="space-y-4 overflow-y-auto pt-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold text-foreground">Python Runtime</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  This runtime executes plotting scripts and annotation fixes.
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  void Promise.resolve(onRefreshPythonInterpreter()).catch(() => {
                    // Backend errors are surfaced through shared state.
                  });
                }}
                disabled={pythonInterpreterLoading || isSavingInterpreter}
                className="gap-1.5"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Refresh
              </Button>
            </div>

            {pythonInterpreterError ? (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {pythonInterpreterError}
              </div>
            ) : null}

            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                Runtime Selection
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant={interpreterModeDraft === "builtin" ? "default" : "outline"}
                  size="sm"
                  onClick={() => setInterpreterModeDraft("builtin")}
                  disabled={isSavingInterpreter}
                >
                  Default runtime
                </Button>
                <Button
                  type="button"
                  variant={interpreterModeDraft === "manual" ? "default" : "outline"}
                  size="sm"
                  onClick={() => setInterpreterModeDraft("manual")}
                  disabled={isSavingInterpreter}
                >
                  Manual path
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Default runtime path: {pythonInterpreterState?.default_path || "Unavailable"}
              </p>
            </div>

            {interpreterModeDraft === "manual" ? (
              <label className="block space-y-1.5">
                <span className="text-xs text-muted-foreground">Python executable path</span>
                <Input
                  value={manualPathDraft}
                  onChange={(event) => setManualPathDraft(event.target.value)}
                  placeholder="/usr/bin/python3"
                  disabled={isSavingInterpreter}
                />
              </label>
            ) : null}

            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1.5 rounded-xl border border-border/80 bg-muted/15 px-4 py-3">
                <p className="text-xs font-semibold text-foreground">Default runtime (built-in)</p>
                <p className="font-mono text-xs text-muted-foreground break-all">
                  {pythonInterpreterState?.default_path || "Unavailable"}
                </p>
                <p className="text-xs text-muted-foreground">
                  Python {pythonInterpreterState?.default_version || "unknown"}
                </p>
                {pythonInterpreterState?.default_package_probe_error ? (
                  <p className="text-xs text-destructive">
                    {pythonInterpreterState.default_package_probe_error}
                  </p>
                ) : null}
              </div>

              <div className="space-y-1.5 rounded-xl border border-border/80 bg-muted/15 px-4 py-3">
                <p className="text-xs font-semibold text-foreground">Runtime in use</p>
                <p className="font-mono text-xs text-muted-foreground break-all">
                  {pythonInterpreterState?.resolved_path || "Unavailable"}
                </p>
                <p className="text-xs text-muted-foreground">
                  Python {pythonInterpreterState?.resolved_version || "unknown"} · {runtimeSourceLabel}
                </p>
                {pythonInterpreterState?.configured_error ? (
                  <p className="text-xs text-destructive">{pythonInterpreterState.configured_error}</p>
                ) : null}
                {pythonInterpreterState?.package_probe_error ? (
                  <p className="text-xs text-destructive">{pythonInterpreterState.package_probe_error}</p>
                ) : null}
              </div>
            </div>

            <div className="space-y-2 rounded-xl border border-border/80 bg-muted/10 px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                Runtime package inventory
              </p>
              <div className="space-y-2 rounded-md border border-border/70 bg-background/60 px-3 py-3">
                <p className="text-[11px] font-semibold text-foreground">Runtime in use</p>
                <p className="text-xs text-muted-foreground">
                  {pythonInterpreterState?.available_package_count ?? availablePackages.length} third-party package
                  {(pythonInterpreterState?.available_package_count ?? availablePackages.length) === 1
                    ? ""
                    : "s"} detected.
                </p>
                {availablePackages.length > 0 ? (
                  <div className="grid max-h-28 gap-1.5 overflow-y-auto sm:grid-cols-2">
                    {availablePackages.map((pkg) => (
                      <div
                        key={`runtime-${pkg}`}
                        className="rounded-md border border-border/70 bg-background/70 px-2 py-1 text-xs"
                      >
                        <span className="font-mono text-foreground">{pkg}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    No third-party packages were detected for this runtime.
                  </p>
                )}
              </div>
            </div>

            {interpreterActionError ? (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {interpreterActionError}
              </div>
            ) : null}

            <div className="flex items-center justify-end gap-2">
              <Button
                type="button"
                size="sm"
                className="gap-1.5"
                onClick={() => {
                  void handleSaveInterpreter();
                }}
                disabled={isSavingInterpreter || (interpreterModeDraft === "manual" && !manualPathDraft.trim())}
              >
                <Save className="h-3.5 w-3.5" />
                {isSavingInterpreter ? "Saving" : "Save"}
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="update" className="space-y-4 overflow-y-auto pt-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold text-foreground">Update</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Compare your installed version against the latest GitHub release.
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-1.5"
                onClick={() => {
                  setUpdateActionError(null);
                  void Promise.resolve(onRefreshUpdateStatus()).catch((err: unknown) => {
                    const message = err instanceof Error ? err.message : "Failed to check for updates";
                    setUpdateActionError(message);
                  });
                }}
                disabled={updateStatusLoading}
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Check again
              </Button>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-xl border border-border/80 bg-muted/15 px-4 py-3">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  Current version
                </p>
                <p className="mt-2 font-mono text-sm text-foreground">
                  {updateStatus?.current_version || "unknown"}
                </p>
              </div>
              <div className="rounded-xl border border-border/80 bg-muted/15 px-4 py-3">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  Latest version
                </p>
                <p className="mt-2 font-mono text-sm text-foreground">
                  {updateStatus?.latest_version || "unknown"}
                </p>
              </div>
            </div>

            <div className="rounded-xl border border-border/80 bg-muted/10 px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge
                  variant="secondary"
                  className={
                    updateStatus?.update_available
                      ? "bg-emerald-500/12 text-emerald-700"
                      : "bg-muted text-foreground"
                  }
                >
                  {updateStatus?.update_available ? "Update available" : "Up to date"}
                </Badge>
                <span className="text-xs text-muted-foreground">Last checked: {formattedUpdateCheckedAt}</span>
              </div>
              {updateStatus?.error ? (
                <p className="mt-3 text-xs text-destructive">{updateStatus.error}</p>
              ) : null}
              {updateActionError ? (
                <p className="mt-3 text-xs text-destructive">{updateActionError}</p>
              ) : null}
            </div>

            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button
                type="button"
                size="sm"
                className="gap-1.5"
                onClick={() => {
                  void handleOpenReleasePage();
                }}
                disabled={!updateStatus?.latest_release_url}
              >
                <ExternalLink className="h-3.5 w-3.5" />
                View Latest Release
              </Button>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
