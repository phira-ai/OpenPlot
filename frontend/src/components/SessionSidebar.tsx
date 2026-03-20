import { Check, Clock3, FileCode2, Loader2, Pencil, Pin, Plus, Trash2, X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

import type { SessionSummary } from "../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { isPlotWorkspacePhaseBusy } from "@/lib/plotModeUi";
import { compactPathDisplay } from "@/lib/paths";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

interface SessionSidebarProps {
  open: boolean;
  sessions: SessionSummary[];
  activeWorkspaceId: string | null;
  plotWorkspaceBusyById: Record<string, boolean>;
  pinned: boolean;
  actionPending: boolean;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
  onRenameWorkspace: (sessionId: string, workspaceName: string) => void;
  onDeleteWorkspace: (sessionId: string) => void;
  onTogglePinned: () => void;
  onPanelMouseEnter: () => void;
  onPanelMouseLeave: () => void;
  onClose: () => void;
}

function formatRelativeDate(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return "";
  }

  const deltaMs = Date.now() - timestamp;
  const deltaMinutes = Math.floor(deltaMs / 60_000);
  if (deltaMinutes < 1) {
    return "just now";
  }
  if (deltaMinutes < 60) {
    return `${deltaMinutes}m ago`;
  }

  const deltaHours = Math.floor(deltaMinutes / 60);
  if (deltaHours < 24) {
    return `${deltaHours}h ago`;
  }

  const deltaDays = Math.floor(deltaHours / 24);
  if (deltaDays < 7) {
    return `${deltaDays}d ago`;
  }

  return new Date(timestamp).toLocaleDateString();
}

function WorkspaceList({
  sessions,
  activeWorkspaceId,
  plotWorkspaceBusyById,
  actionPending,
  onSelectSession,
  onNewSession,
  onRenameWorkspace,
  onDeleteWorkspace,
}: Pick<
  SessionSidebarProps,
  | "sessions"
  | "activeWorkspaceId"
  | "plotWorkspaceBusyById"
  | "actionPending"
  | "onSelectSession"
  | "onNewSession"
  | "onRenameWorkspace"
  | "onDeleteWorkspace"
>) {
  const [editingWorkspaceId, setEditingWorkspaceId] = useState<string | null>(null);
  const [workspaceNameDraft, setWorkspaceNameDraft] = useState("");

  const selectWorkspace = (sessionId: string) => {
    cancelEdit();
    onSelectSession(sessionId);
  };

  const beginEdit = (entry: SessionSummary) => {
    setEditingWorkspaceId(entry.id);
    setWorkspaceNameDraft(entry.workspace_name);
  };

  const cancelEdit = () => {
    setEditingWorkspaceId(null);
    setWorkspaceNameDraft("");
  };

  const saveEdit = (entry: SessionSummary) => {
    const nextName = workspaceNameDraft.trim();
    if (!nextName || nextName === entry.workspace_name) {
      cancelEdit();
      return;
    }
    onRenameWorkspace(entry.id, nextName);
    cancelEdit();
  };

  const onNameKeyDown = (event: KeyboardEvent<HTMLInputElement>, entry: SessionSummary) => {
    if (event.key === "Escape") {
      cancelEdit();
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      saveEdit(entry);
    }
  };

  return (
    <>
      <div className="space-y-3 px-3 py-3">
        <Button
          type="button"
          size="sm"
          className="w-full justify-start gap-1.5"
          onClick={() => {
            cancelEdit();
            onNewSession();
          }}
          disabled={actionPending}
        >
          <Plus className="h-3.5 w-3.5" />
          New Workspace
        </Button>
      </div>

      <Separator />

      <ScrollArea className="min-h-0 flex-1">
        <ul className="space-y-2 p-3">
          {sessions.length === 0 ? (
            <li className="rounded-md border border-dashed border-border/80 bg-background/60 px-3 py-2 text-xs text-muted-foreground">
              No workspaces yet. Start a new workspace to generate a plot script.
            </li>
          ) : null}

          {sessions.map((entry) => {
            const isActive =
              !!activeWorkspaceId && entry.id === activeWorkspaceId;
            const subtitle = entry.source_script_path
              ? compactPathDisplay(entry.source_script_path)
              : (entry.workspace_mode === "plot"
                  ? "Plot workspace in progress"
                  : entry.plot_type.toUpperCase());
            const isWorking =
              entry.workspace_mode === "plot" &&
              (Boolean(plotWorkspaceBusyById[entry.id]) || isPlotWorkspacePhaseBusy(entry.plot_phase));
            const whenLabel = formatRelativeDate(entry.updated_at);
            const editing = editingWorkspaceId === entry.id;
            const canDelete = true;

            return (
              <li key={entry.id}>
                <div
                  className={cn(
                    "rounded-lg border px-3 py-2 transition",
                    isActive
                      ? "border-foreground/40 bg-foreground/[0.06]"
                      : "border-border/80 bg-background/70 hover:border-foreground/25 hover:bg-muted/35",
                  )}
                >
                  <div className="flex items-center gap-1.5">
                    {editing ? (
                      <Input
                        value={workspaceNameDraft}
                        onChange={(event) => setWorkspaceNameDraft(event.target.value)}
                        onKeyDown={(event) => onNameKeyDown(event, entry)}
                        onBlur={() => saveEdit(entry)}
                        maxLength={120}
                        className="h-7 min-w-0 flex-1 text-sm"
                        disabled={actionPending}
                      />
                    ) : (
                      <button
                        type="button"
                        onClick={() => selectWorkspace(entry.id)}
                        disabled={actionPending}
                        className="min-w-0 flex-1 text-left"
                        title={entry.workspace_name}
                      >
                        <p className="truncate text-sm font-medium text-foreground">
                          {entry.workspace_name}
                        </p>
                      </button>
                    )}

                    {editing ? (
                      <div className="flex items-center gap-1">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-xs"
                          onClick={() => saveEdit(entry)}
                          disabled={actionPending || !workspaceNameDraft.trim()}
                          aria-label="Save workspace name"
                        >
                          <Check className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-xs"
                          onClick={cancelEdit}
                          disabled={actionPending}
                          aria-label="Cancel workspace rename"
                        >
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-0.5">
                        {entry.workspace_mode === "plot" ? (
                          <Badge
                            variant="secondary"
                            className="h-5 rounded-full px-1.5 text-[10px]"
                          >
                            plot
                          </Badge>
                        ) : null}

                        {isWorking ? (
                          <Badge variant="outline" className="h-5 gap-1 rounded-full px-1.5 text-[10px]">
                            <Loader2 className="h-3 w-3 animate-spin" />
                            working
                          </Badge>
                        ) : null}

                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-xs"
                          onClick={() => beginEdit(entry)}
                          disabled={actionPending}
                          aria-label="Rename workspace"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>

                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-xs"
                          onClick={() => {
                            if (!canDelete || actionPending) {
                              return;
                            }
                            const confirmed = window.confirm(
                              "Delete this workspace and all of its artifacts? This cannot be undone.",
                            );
                            if (!confirmed) {
                              return;
                            }
                            cancelEdit();
                            onDeleteWorkspace(entry.id);
                          }}
                          disabled={!canDelete || actionPending}
                          aria-label="Delete workspace"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => selectWorkspace(entry.id)}
                    disabled={actionPending}
                    className="mt-1.5 w-full text-left"
                    title={entry.source_script_path || entry.plot_type.toUpperCase()}
                  >
                    <p className="truncate text-[11px] text-muted-foreground">{subtitle}</p>
                    <div className="mt-2 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                      <span className="inline-flex items-center gap-1">
                        <FileCode2 className="h-3 w-3" />
                        {entry.annotation_count} ann
                      </span>
                      <div className="flex items-center gap-1.5">
                        {entry.pending_annotation_count > 0 ? (
                          <Badge variant="secondary" className="h-5 rounded-full px-1.5 text-[10px]">
                            {entry.pending_annotation_count} pending
                          </Badge>
                        ) : null}
                        {whenLabel ? (
                          <span className="inline-flex items-center gap-1">
                            <Clock3 className="h-3 w-3" />
                            {whenLabel}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </ScrollArea>
    </>
  );
}

export default function SessionSidebar({
  open,
  sessions,
  activeWorkspaceId,
  plotWorkspaceBusyById,
  pinned,
  actionPending,
  onSelectSession,
  onNewSession,
  onRenameWorkspace,
  onDeleteWorkspace,
  onTogglePinned,
  onPanelMouseEnter,
  onPanelMouseLeave,
  onClose,
}: SessionSidebarProps) {
  return (
    <>
      <aside
        data-walkthrough="sessions-sidebar"
        className={cn(
          "hidden min-h-0 overflow-hidden bg-card/45 transition-[width,border-color] duration-300 ease-out lg:flex lg:flex-col",
          open
            ? "border-r border-border/80 lg:w-72"
            : "pointer-events-none border-r border-transparent lg:w-0",
        )}
        onMouseEnter={onPanelMouseEnter}
        onMouseLeave={onPanelMouseLeave}
      >
        <div
          className={cn(
            "flex min-h-0 flex-1 flex-col transition-all duration-250 ease-out",
            open ? "translate-x-0 opacity-100" : "-translate-x-2 opacity-0",
          )}
        >
          <div className="px-3 py-3">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              Workspace
            </p>
          </div>

          <WorkspaceList
            sessions={sessions}
            activeWorkspaceId={activeWorkspaceId}
            plotWorkspaceBusyById={plotWorkspaceBusyById}
            actionPending={actionPending}
            onSelectSession={onSelectSession}
            onNewSession={onNewSession}
            onRenameWorkspace={onRenameWorkspace}
            onDeleteWorkspace={onDeleteWorkspace}
          />

          <div className="border-t border-border/80 px-3 py-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className={cn(
                  "w-full justify-center gap-1.5",
                  pinned
                    ? "border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200"
                    : "text-muted-foreground",
                )}
                onClick={onTogglePinned}
                aria-label={pinned ? "Unpin workspace sidebar" : "Pin workspace sidebar"}
              >
                <Pin className={cn("h-3.5 w-3.5", pinned ? "text-slate-600" : "text-muted-foreground")} />
                {pinned ? "Pinned" : "Pin panel"}
              </Button>
          </div>
        </div>
      </aside>

      {open ? (
        <div className="fixed inset-0 z-[70] lg:hidden">
          <button
            type="button"
            onClick={onClose}
            className="absolute inset-0 bg-black/40"
            aria-label="Close workspace sidebar"
          />

          <aside
            className="absolute left-0 top-0 flex h-full w-72 flex-col border-r border-border/80 bg-card shadow-2xl"
            onMouseEnter={onPanelMouseEnter}
            onMouseLeave={onPanelMouseLeave}
          >
            <div className="flex items-center justify-between px-3 py-3">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Workspace
              </p>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                onClick={onClose}
                aria-label="Close workspace sidebar"
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>

            <WorkspaceList
              sessions={sessions}
              activeWorkspaceId={activeWorkspaceId}
              plotWorkspaceBusyById={plotWorkspaceBusyById}
              actionPending={actionPending}
              onSelectSession={(sessionId) => {
                onSelectSession(sessionId);
                onClose();
              }}
              onNewSession={() => {
                onNewSession();
                onClose();
              }}
              onRenameWorkspace={(sessionId, workspaceName) => {
                onRenameWorkspace(sessionId, workspaceName);
              }}
              onDeleteWorkspace={(sessionId) => {
                onDeleteWorkspace(sessionId);
              }}
            />

            <div className="border-t border-border/80 px-3 py-3">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className={cn(
                  "w-full justify-center gap-1.5",
                  pinned
                    ? "border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200"
                    : "text-muted-foreground",
                )}
                onClick={onTogglePinned}
                aria-label={pinned ? "Unpin workspace sidebar" : "Pin workspace sidebar"}
              >
                <Pin className={cn("h-3.5 w-3.5", pinned ? "text-slate-600" : "text-muted-foreground")} />
                {pinned ? "Pinned" : "Pin panel"}
              </Button>
            </div>
          </aside>
        </div>
      ) : null}
    </>
  );
}
