import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  CircleOff,
  Download,
  Link as LinkIcon,
  RefreshCw,
  RotateCcw,
  Save,
  X,
} from "lucide-react";
import type {
  Branch,
  FixRunner,
  OpencodeModelOption,
  PythonInterpreterMode,
  PythonInterpreterState,
} from "../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { runnerLabel } from "@/lib/runners";
import openplotLogo from "../../openplot.png";
import codexLogo from "../../codex.svg";
import claudeCodeLogo from "../../claude-code.svg";
import opencodeLogo from "../../opencode.svg";
import pythonLogo from "../../python.svg";

function runnerLogo(runner: FixRunner): string {
  if (runner === "codex") {
    return codexLogo;
  }
  if (runner === "claude") {
    return claudeCodeLogo;
  }
  return opencodeLogo;
}

interface ToolbarProps {
  mode: "annotation" | "plot";
  connected: boolean;
  branches?: Branch[];
  activeBranchId?: string;
  checkedOutVersionId?: string;
  wsUrl: string;
  reconnectAttempts: number;
  lastConnectedAt: string | null;
  lastDisconnectedAt: string | null;
  opencodeModels: OpencodeModelOption[];
  opencodeModelsLoading: boolean;
  opencodeModelsError: string | null;
  availableRunners: FixRunner[];
  selectedRunner: FixRunner;
  onChangeRunner: (runner: FixRunner) => void;
  selectedModel: string;
  selectedVariant: string;
  onChangeModel: (model: string) => void;
  onChangeVariant: (variant: string) => void;
  pythonInterpreterState: PythonInterpreterState | null;
  pythonInterpreterLoading: boolean;
  pythonInterpreterError: string | null;
  onRefreshPythonInterpreter: () => Promise<void> | void;
  onSavePythonInterpreter: (
    mode: PythonInterpreterMode,
    path?: string,
  ) => Promise<void> | void;
  onOpenRunnerManager?: () => void;
}

/**
 * Top toolbar — shows connection status and action buttons.
 * Annotations are created via region drawing for all plot types.
 */
export default function Toolbar({
  mode,
  connected,
  branches,
  activeBranchId,
  checkedOutVersionId,
  wsUrl,
  reconnectAttempts,
  lastConnectedAt,
  lastDisconnectedAt,
  opencodeModels,
  opencodeModelsLoading,
  opencodeModelsError,
  availableRunners,
  selectedRunner,
  onChangeRunner,
  selectedModel,
  selectedVariant,
  onChangeModel,
  onChangeVariant,
  pythonInterpreterState,
  pythonInterpreterLoading,
  pythonInterpreterError,
  onRefreshPythonInterpreter,
  onSavePythonInterpreter,
  onOpenRunnerManager,
}: ToolbarProps) {
  const [showConnectionInfo, setShowConnectionInfo] = useState(false);
  const [showInterpreterConfig, setShowInterpreterConfig] = useState(false);
  const [interpreterModeDraft, setInterpreterModeDraft] = useState<PythonInterpreterMode>("builtin");
  const [manualPathDraft, setManualPathDraft] = useState("");
  const [isSavingInterpreter, setIsSavingInterpreter] = useState(false);
  const [interpreterActionError, setInterpreterActionError] = useState<string | null>(null);

  const branchList = useMemo(() => branches ?? [], [branches]);

  const formattedLastConnectedAt = useMemo(
    () =>
      lastConnectedAt
        ? new Date(lastConnectedAt).toLocaleString()
        : "No successful connection yet",
    [lastConnectedAt],
  );

  const formattedLastDisconnectedAt = useMemo(
    () =>
      lastDisconnectedAt
        ? new Date(lastDisconnectedAt).toLocaleString()
        : "No disconnections recorded",
    [lastDisconnectedAt],
  );

  const activeBranchName = useMemo(
    () => branchList.find((branch) => branch.id === activeBranchId)?.name ?? "Unknown",
    [activeBranchId, branchList],
  );

  const selectedModelOption = useMemo(
    () => opencodeModels.find((option) => option.id === selectedModel) ?? null,
    [opencodeModels, selectedModel],
  );

  const availableVariants = useMemo(
    () => selectedModelOption?.variants ?? [],
    [selectedModelOption],
  );

  const resolvedInterpreterSummary = useMemo(() => {
    if (!pythonInterpreterState) {
      return "Interpreter unavailable";
    }
    const version = pythonInterpreterState.resolved_version || "unknown";
    return `Python ${version}`;
  }, [pythonInterpreterState]);

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

  useEffect(() => {
    if (!showInterpreterConfig) {
      return;
    }
    setInterpreterModeDraft(pythonInterpreterState?.mode ?? "builtin");
    setManualPathDraft(pythonInterpreterState?.configured_path ?? "");
    setInterpreterActionError(null);
  }, [pythonInterpreterState, showInterpreterConfig]);

  const openInterpreterConfig = () => {
    setShowInterpreterConfig(true);
    setInterpreterActionError(null);
    void Promise.resolve(onRefreshPythonInterpreter()).catch(() => {
      // Errors are surfaced via pythonInterpreterError.
    });
  };

  const closeInterpreterConfig = () => {
    if (isSavingInterpreter) {
      return;
    }
    setShowInterpreterConfig(false);
    setInterpreterActionError(null);
  };

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
      setShowInterpreterConfig(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save interpreter setting";
      setInterpreterActionError(message);
    } finally {
      setIsSavingInterpreter(false);
    }
  };

  return (
    <>
      <header
        data-walkthrough="toolbar"
        className="flex flex-wrap items-center gap-3 border-b border-border/80 bg-background/90 px-4 py-2 backdrop-blur"
      >
        <div className="flex items-center">
          <img
            src={openplotLogo}
            alt="OpenPlot"
            className="pointer-events-none h-8 w-auto origin-left scale-[3] object-contain"
          />
        </div>

        <div className="ml-auto flex min-w-[20rem] flex-wrap items-center justify-end gap-2.5">
          <div className="flex items-center gap-2 rounded-md border border-border/80 bg-muted/45 px-2 py-1.5">
            <div
              className="relative flex h-7 w-9 items-center justify-center rounded-md border border-border/80 bg-background"
              title={runnerLabel(selectedRunner)}
            >
              <img
                src={runnerLogo(selectedRunner)}
                alt={runnerLabel(selectedRunner)}
                className="h-4 w-4 object-contain"
              />
              <select
                value={selectedRunner}
                onChange={(event) => {
                  onChangeRunner(event.target.value as FixRunner);
                }}
                aria-label="Backend"
                disabled={availableRunners.length <= 1}
                className="absolute inset-0 cursor-pointer opacity-0"
              >
                {availableRunners.map((runner) => (
                  <option key={runner} value={runner}>
                    {runnerLabel(runner)}
                  </option>
                ))}
              </select>
            </div>

            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              Model
            </span>
            <select
              value={selectedModel}
              onChange={(event) => {
                onChangeModel(event.target.value);
              }}
              disabled={opencodeModelsLoading || opencodeModels.length === 0}
              className="w-52 rounded-md border border-border/80 bg-background px-2 py-1 text-xs text-foreground disabled:cursor-not-allowed disabled:opacity-60"
            >
              {opencodeModels.length === 0 ? (
                <option value={selectedModel || ""}>
                  {selectedModel ? `${selectedModel} (default)` : "No model available"}
                </option>
              ) : null}
              {opencodeModels.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.id}
                </option>
              ))}
            </select>

            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              Variant
            </span>
            <select
              value={selectedVariant}
              onChange={(event) => {
                onChangeVariant(event.target.value);
              }}
              disabled={
                opencodeModelsLoading ||
                !selectedModel ||
                opencodeModels.length === 0 ||
                availableVariants.length === 0
              }
              className="w-32 rounded-md border border-border/80 bg-background px-2 py-1 text-xs text-foreground disabled:cursor-not-allowed disabled:opacity-60"
            >
              <option value="">Default</option>
              {availableVariants.map((variant) => (
                <option key={variant} value={variant}>
                  {variant}
                </option>
              ))}
            </select>
          </div>

            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onOpenRunnerManager}
              disabled={!onOpenRunnerManager}
              className="gap-1.5 border-foreground/20 bg-foreground/[0.03] text-foreground"
            >
            <Download className="h-3.5 w-3.5" />
            Runners
          </Button>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setShowConnectionInfo(true)}
            className={
              connected
                ? "gap-1.5 border-foreground/20 bg-foreground/[0.03] text-foreground"
                : "gap-1.5 border-destructive/35 bg-destructive/10 text-destructive"
            }
          >
            {connected ? (
              <CheckCircle2 className="h-3.5 w-3.5" />
            ) : (
              <CircleOff className="h-3.5 w-3.5" />
            )}
            Live Sync
          </Button>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={openInterpreterConfig}
            className="gap-1.5 border-foreground/20 bg-foreground/[0.03] text-foreground"
            title={resolvedInterpreterSummary}
            aria-label="Configure Python interpreter"
          >
            <img src={pythonLogo} alt="" className="h-3.5 w-3.5" aria-hidden="true" />
            Python
          </Button>

          {opencodeModelsError ? (
            <span className="basis-full text-right text-[11px] text-destructive">
              {opencodeModelsError}
            </span>
          ) : null}
        </div>
      </header>

      {showConnectionInfo && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          onClick={() => setShowConnectionInfo(false)}
        >
          <Card
            className="w-full max-w-md border border-border/90 bg-popover shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle className="text-base">Connection Information</CardTitle>
                  <CardDescription className="mt-1">
                    Live WebSocket status for OpenPlot sync.
                  </CardDescription>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => setShowConnectionInfo(false)}
                  aria-label="Close connection information"
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
            </CardHeader>

            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Status</span>
                <Badge
                  variant="secondary"
                  className={
                    connected
                      ? "bg-foreground/10 text-foreground"
                      : "bg-destructive/10 text-destructive"
                  }
                >
                  {connected ? "Connected" : "Disconnected"}
                </Badge>
              </div>

              <div className="space-y-1">
                <div className="flex items-center gap-1.5 text-muted-foreground">
                  <LinkIcon className="h-3.5 w-3.5" />
                  Endpoint
                </div>
                <code className="block rounded-md border border-border/80 bg-muted/40 px-2.5 py-2 font-mono text-xs text-foreground break-all">
                  {wsUrl || "Unavailable"}
                </code>
              </div>

              <div className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1.5 text-xs">
                <span className="text-muted-foreground">Mode</span>
                <span className="text-right text-foreground">{mode}</span>

                {mode === "annotation" ? (
                  <>
                    <span className="text-muted-foreground">Active branch</span>
                    <span className="text-right text-foreground">{activeBranchName}</span>

                    <span className="text-muted-foreground">Checked out</span>
                    <span className="truncate text-right font-mono text-foreground">{checkedOutVersionId || "<none>"}</span>
                  </>
                ) : null}

                <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                  <RotateCcw className="h-3.5 w-3.5" />
                  Reconnect attempts
                </span>
                <span className="text-right font-medium text-foreground">{reconnectAttempts}</span>

                <span className="text-muted-foreground">Last connected</span>
                <span className="text-right text-foreground">{formattedLastConnectedAt}</span>

                <span className="text-muted-foreground">Last disconnected</span>
                <span className="text-right text-foreground">{formattedLastDisconnectedAt}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {showInterpreterConfig && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          onClick={closeInterpreterConfig}
        >
          <Card
            className="w-full max-w-2xl border border-border/90 bg-popover shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle className="text-base">Python Runtime</CardTitle>
                  <CardDescription className="mt-1">
                    This runtime executes plotting scripts and annotation fixes.
                  </CardDescription>
                </div>
                <div className="flex items-center gap-1.5">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      void Promise.resolve(onRefreshPythonInterpreter()).catch(() => {
                        // Surface backend errors through the shared error state.
                      });
                    }}
                    disabled={pythonInterpreterLoading || isSavingInterpreter}
                    className="gap-1.5"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    Refresh
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    onClick={closeInterpreterConfig}
                    aria-label="Close Python interpreter configuration"
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            </CardHeader>

            <CardContent className="space-y-4 text-sm">
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
                <div className="space-y-1.5 rounded-md border border-border/80 bg-muted/20 px-3 py-2">
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

                <div className="space-y-1.5 rounded-md border border-border/80 bg-muted/20 px-3 py-2">
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

              <div className="space-y-2 rounded-md border border-border/80 bg-muted/10 px-3 py-2">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  Runtime package inventory
                </p>
                <div className="space-y-2 rounded-md border border-border/70 bg-background/60 px-2.5 py-2">
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
                  variant="outline"
                  size="sm"
                  onClick={closeInterpreterConfig}
                  disabled={isSavingInterpreter}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="gap-1.5"
                  onClick={() => {
                    void handleSaveInterpreter();
                  }}
                  disabled={
                    isSavingInterpreter ||
                    (interpreterModeDraft === "manual" && !manualPathDraft.trim())
                  }
                >
                  <Save className="h-3.5 w-3.5" />
                  {isSavingInterpreter ? "Saving" : "Save"}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
