import type { KeyboardEventHandler } from "react";
import { ArrowRight, Loader2 } from "lucide-react";
import { Icon } from "@iconify/react";
import defaultFolderIcon from "@iconify-icons/vscode-icons/default-folder";

import type { PlotModePathSelectionType, PlotModePathSuggestion } from "../../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { compactPathDisplay } from "@/lib/paths";
import { iconForPath } from "./plotModePathUtils";

const SUGGESTION_PATH_MAX_LENGTH = 56;

function Hotkey({ children }: { children: string }) {
  return (
    <span className="inline-flex h-6 items-center rounded-md border border-border/70 bg-background px-2 font-mono text-[11px] font-medium text-foreground shadow-sm">
      {children}
    </span>
  );
}

export function PathTypeIcon({
  pathLike,
  isDirectory = false,
}: {
  pathLike: string;
  isDirectory?: boolean;
}) {
  if (isDirectory) {
    return <Icon icon={defaultFolderIcon} className="h-4 w-4 shrink-0" />;
  }

  return <Icon icon={iconForPath(pathLike)} className="h-4 w-4 shrink-0" />;
}

export function PathLabel({
  pathLike,
  maxLength = 56,
  className,
}: {
  pathLike: string;
  maxLength?: number;
  className?: string;
}) {
  return (
    <span className={cn("block min-w-0 flex-1 truncate", className)} title={pathLike}>
      {compactPathDisplay(pathLike, maxLength)}
    </span>
  );
}

export default function PlotModePathPicker({
  open,
  onOpenChange,
  forceInitialFileSelection,
  requiresInitialFiles,
  readOnlySourceDetails,
  selectionType,
  selectingFiles,
  loadingSuggestions,
  pathInput,
  suggestions,
  highlightedIndex,
  selectedDataPaths,
  selectedScriptPath,
  onSelectMode,
  onPathInputChange,
  onPathInputKeyDown,
  onAddCurrentPath,
  onApplySuggestion,
  onRemoveDataPath,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  forceInitialFileSelection: boolean;
  requiresInitialFiles: boolean;
  readOnlySourceDetails: boolean;
  selectionType: PlotModePathSelectionType;
  selectingFiles: boolean;
  loadingSuggestions: boolean;
  pathInput: string;
  suggestions: PlotModePathSuggestion[];
  highlightedIndex: number;
  selectedDataPaths: string[];
  selectedScriptPath: string;
  onSelectMode: (selectionType: PlotModePathSelectionType) => void;
  onPathInputChange: (value: string) => void;
  onPathInputKeyDown: KeyboardEventHandler<HTMLInputElement>;
  onAddCurrentPath: () => void;
  onApplySuggestion: (suggestion: PlotModePathSuggestion) => void;
  onRemoveDataPath: (path: string) => void;
  onConfirm: () => Promise<void>;
}) {
  return (
    <Sheet
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen) {
          onOpenChange(true);
          return;
        }
        if (forceInitialFileSelection && requiresInitialFiles) {
          onOpenChange(false);
          return;
        }
        onOpenChange(false);
      }}
    >
      <SheetContent side="right" showCloseButton className="w-full gap-0 sm:max-w-2xl">
        <SheetHeader className="gap-3 border-b border-border/70 pb-4 pr-14">
          <Badge variant="outline" className="w-fit rounded-full bg-background/90 px-2.5">
            {readOnlySourceDetails ? "Attached sources" : "Source selection"}
          </Badge>
          <div>
            <SheetTitle>
              {readOnlySourceDetails
                ? "Attached files for this workspace"
                : "Attach local data files or plotting script"}
            </SheetTitle>
          </div>
        </SheetHeader>

        <div className="flex min-h-0 flex-1 flex-col">
          <ScrollArea className="min-h-0 flex-1">
            <div className="flex flex-col gap-5 p-4 sm:p-5">
              {readOnlySourceDetails ? null : (
                <div className="grid grid-cols-2 gap-2 rounded-2xl border border-border/70 bg-muted/20 p-1">
                  <Button
                    type="button"
                    size="sm"
                    variant={selectionType === "data" ? "default" : "ghost"}
                    className="rounded-xl"
                    onClick={() => onSelectMode("data")}
                    disabled={selectingFiles}
                  >
                    Data files
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={selectionType === "script" ? "default" : "ghost"}
                    className="rounded-xl"
                    onClick={() => onSelectMode("script")}
                    disabled={selectingFiles}
                  >
                    Python script
                  </Button>
                </div>
              )}

              {readOnlySourceDetails ? null : (
                <Card className="border border-border/70 bg-background/92 shadow-sm">
                  <CardHeader>
                    <CardTitle className="text-base">Browse local paths</CardTitle>
                    <CardDescription className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Hotkey>Up</Hotkey>
                        <Hotkey>Down</Hotkey>
                        <span>Navigate</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Hotkey>Tab</Hotkey>
                        <span>Accept</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Hotkey>Enter</Hotkey>
                        <span>Add</span>
                      </div>
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex gap-2">
                      <Input
                        value={pathInput}
                        onChange={(event) => onPathInputChange(event.target.value)}
                        onKeyDown={onPathInputKeyDown}
                        placeholder={selectionType === "script" ? "~/path/to/script.py" : "~/path/to/data.csv"}
                        disabled={selectingFiles}
                        className="h-11 rounded-2xl bg-background"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        className="h-11 rounded-2xl px-4"
                        onClick={onAddCurrentPath}
                        disabled={selectingFiles}
                      >
                        Add
                      </Button>
                    </div>

                    <div className="rounded-2xl border border-border/70 bg-muted/20 p-2">
                      {loadingSuggestions ? (
                        <p className="px-2 py-2 text-sm text-muted-foreground">Loading paths...</p>
                      ) : suggestions.length === 0 ? (
                        <p className="px-2 py-2 text-sm text-muted-foreground">No matching paths</p>
                      ) : (
                        <ul className="max-h-60 space-y-1 overflow-y-auto">
                          {suggestions.map((suggestion, index) => {
                            const isHighlighted = index === highlightedIndex;
                            return (
                              <li key={`${suggestion.path}:${index}`}>
                                <button
                                  type="button"
                                  className={`flex w-full min-w-0 items-center gap-3 rounded-xl px-3 py-2 text-left text-sm transition ${
                                    isHighlighted
                                      ? "bg-background text-foreground shadow-sm"
                                      : "text-muted-foreground hover:bg-background/70 hover:text-foreground"
                                  }`}
                                  onClick={() => onApplySuggestion(suggestion)}
                                  title={suggestion.display_path}
                                >
                                  <PathTypeIcon pathLike={suggestion.path} isDirectory={suggestion.is_dir} />
                                  <PathLabel
                                    pathLike={suggestion.display_path}
                                    maxLength={SUGGESTION_PATH_MAX_LENGTH}
                                  />
                                </button>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>
                  </CardContent>
                </Card>
              )}

              {selectionType === "data" ? (
                <Card className="border border-border/70 bg-background/92 shadow-sm">
                  <CardContent className="space-y-3 pt-4">
                    <div className="flex items-center justify-between gap-3">
                      <Badge variant="outline" className="rounded-full px-2.5">
                        Attached files
                      </Badge>
                      <Badge variant="secondary" className="rounded-full px-2.5">
                        {selectedDataPaths.length}
                      </Badge>
                    </div>
                    {selectedDataPaths.length === 0 ? (
                      <div className="rounded-2xl border border-dashed border-border/70 bg-muted/20 px-4 py-6 text-sm text-muted-foreground">
                        Add paths above to start building your file set.
                      </div>
                    ) : (
                      <ul className="space-y-2">
                        {selectedDataPaths.map((path) => (
                          <li
                            key={path}
                            className="flex items-center gap-3 rounded-2xl border border-border/70 bg-muted/20 px-3 py-3"
                          >
                            <span className="flex min-w-0 flex-1 items-center gap-3 overflow-hidden" title={path}>
                              <PathTypeIcon pathLike={path} />
                              <PathLabel pathLike={path} className="text-sm text-foreground" />
                            </span>
                            {readOnlySourceDetails ? (
                              <Badge variant="outline" className="rounded-full px-2.5">
                                Locked
                              </Badge>
                            ) : (
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                className="rounded-full"
                                onClick={() => onRemoveDataPath(path)}
                              >
                                Remove
                              </Button>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {readOnlySourceDetails
                        ? "This workspace is locked after the initial file selection. Use New workspace to attach a different set of files."
                        : "Enter another path above to include more files."}
                    </p>
                  </CardContent>
                </Card>
              ) : (
                <Card className="border border-border/70 bg-background/92 shadow-sm">
                  <CardContent className="pt-4">
                    <div className="flex items-center gap-3 overflow-hidden rounded-2xl border border-border/70 bg-muted/20 px-3 py-3 text-sm text-foreground">
                      <Badge variant="outline" className="rounded-full px-2.5">
                        Script
                      </Badge>
                      {(selectedScriptPath || pathInput) && <PathTypeIcon pathLike={selectedScriptPath || pathInput} />}
                      <PathLabel pathLike={selectedScriptPath || pathInput || "(none)"} />
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          </ScrollArea>

          <SheetFooter className="border-t border-border/70 bg-background/96 sm:flex-row sm:justify-end">
            {readOnlySourceDetails ? null : (
              <Button
                type="button"
                size="icon-lg"
                className="rounded-full"
                aria-label={selectionType === "script" ? "Open script" : "Use selected sources"}
                onClick={() => {
                  void onConfirm();
                }}
                disabled={selectingFiles}
              >
                {selectingFiles ? <Loader2 className="animate-spin" /> : <ArrowRight />}
              </Button>
            )}
          </SheetFooter>
        </div>
      </SheetContent>
    </Sheet>
  );
}
