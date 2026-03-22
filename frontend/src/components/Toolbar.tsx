import { useState } from "react";
import { Settings2 } from "lucide-react";

import type {
  Branch,
  FixRunner,
  OpencodeModelOption,
  PythonInterpreterMode,
  PythonInterpreterState,
  RunnerStatusEntry,
  RunnerStatusState,
  UpdateStatusState,
} from "../types";
import SettingsDialog from "./SettingsDialog";
import { Button } from "@/components/ui/button";
import { runnerLabel } from "@/lib/runners";
import openplotLogo from "../../openplot.png";
import codexLogo from "../../codex.svg";
import claudeCodeLogo from "../../claude-code.svg";
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
  runnerStatus: RunnerStatusState | null;
  runnerStatusLoading: boolean;
  runnerStatusError: string | null;
  onInstallRunner: (runner: RunnerStatusEntry["runner"]) => Promise<void> | void;
  onAuthenticateRunner: (entry: RunnerStatusEntry) => Promise<void> | void;
  onOpenRunnerGuide: (url: string) => Promise<void> | void;
  onRefreshRunners: () => Promise<void> | void;
  updateStatus: UpdateStatusState | null;
  updateStatusLoading: boolean;
  onRefreshUpdateStatus: () => Promise<UpdateStatusState | void> | void;
  onOpenReleasePage: (url: string) => Promise<void> | void;
}

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
  runnerStatus,
  runnerStatusLoading,
  runnerStatusError,
  onInstallRunner,
  onAuthenticateRunner,
  onOpenRunnerGuide,
  onRefreshRunners,
  updateStatus,
  updateStatusLoading,
  onRefreshUpdateStatus,
  onOpenReleasePage,
}: ToolbarProps) {
  const [showSettings, setShowSettings] = useState(false);
  const availableVariants = opencodeModels.find((option) => option.id === selectedModel)?.variants ?? [];
  const updateAvailable = updateStatus?.update_available === true;

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
            onClick={() => setShowSettings(true)}
            className="relative h-9 w-9 border-foreground/20 bg-foreground/[0.03] p-0 text-foreground"
            aria-label="Settings"
            title="Settings"
          >
            <Settings2 className="h-3.5 w-3.5" />
            {updateAvailable ? (
              <span
                data-testid="settings-update-dot"
                aria-hidden="true"
                className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-sky-500"
              />
            ) : null}
          </Button>

          {opencodeModelsError ? (
            <span className="basis-full text-right text-[11px] text-destructive">
              {opencodeModelsError}
            </span>
          ) : null}
        </div>
      </header>

      <SettingsDialog
        open={showSettings}
        onOpenChange={setShowSettings}
        mode={mode}
        branches={branches}
        activeBranchId={activeBranchId}
        checkedOutVersionId={checkedOutVersionId}
        connected={connected}
        wsUrl={wsUrl}
        reconnectAttempts={reconnectAttempts}
        lastConnectedAt={lastConnectedAt}
        lastDisconnectedAt={lastDisconnectedAt}
        runnerStatus={runnerStatus}
        runnerStatusLoading={runnerStatusLoading}
        runnerStatusError={runnerStatusError}
        onInstallRunner={onInstallRunner}
        onAuthenticateRunner={onAuthenticateRunner}
        onOpenRunnerGuide={onOpenRunnerGuide}
        onRefreshRunners={onRefreshRunners}
        pythonInterpreterState={pythonInterpreterState}
        pythonInterpreterLoading={pythonInterpreterLoading}
        pythonInterpreterError={pythonInterpreterError}
        onRefreshPythonInterpreter={onRefreshPythonInterpreter}
        onSavePythonInterpreter={onSavePythonInterpreter}
        updateStatus={updateStatus}
        updateStatusLoading={updateStatusLoading}
        onRefreshUpdateStatus={onRefreshUpdateStatus}
        onOpenReleasePage={onOpenReleasePage}
      />
    </>
  );
}
