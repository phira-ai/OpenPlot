import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  Check,
  CheckCheck,
  Download,
  GitBranch,
  Loader2,
  Pause,
  Pencil,
  Play,
  Trash2,
  X,
} from "lucide-react";
import type {
  Annotation,
  Branch,
  FixJob,
  FixRunner,
  VersionNode,
} from "../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";

interface FeedbackSidebarProps {
  annotations: Annotation[];
  versions: VersionNode[];
  branches: Branch[];
  rootVersionId: string;
  activeBranchId: string;
  checkedOutVersionId: string;
  onSwitchBranch: (branchId: string) => Promise<void> | void;
  onRenameBranch: (branchId: string, name: string) => Promise<unknown> | void;
  focusedAnnotationId?: string | null;
  onSelectInitialState: () => Promise<void> | void;
  onSelectAnnotation: (annotation: Annotation) => Promise<void> | void;
  onDownload: (annotation: Annotation) => Promise<void> | void;
  onDelete: (id: string) => Promise<void> | void;
  onUpdate: (id: string, updates: Partial<Annotation>) => Promise<void> | void;
  selectedRunner: FixRunner;
  selectedModel: string;
  selectedVariant: string;
  opencodeModelsLoading: boolean;
  opencodeModelsError: string | null;
  fixJob: FixJob | null;
  onStartFixJob: (
    runner: FixRunner,
    model: string,
    variant?: string,
  ) => Promise<FixJob> | Promise<void>;
  onCancelFixJob: (jobId: string) => Promise<FixJob> | Promise<void>;
}

function formatAnnotationTimestamp(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return "";
  }

  const dt = new Date(timestamp);
  return dt.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function FeedbackSidebar({
  annotations,
  versions,
  branches,
  rootVersionId,
  activeBranchId,
  checkedOutVersionId,
  onSwitchBranch,
  onRenameBranch,
  focusedAnnotationId,
  onSelectInitialState,
  onSelectAnnotation,
  onDownload,
  onDelete,
  onUpdate,
  selectedRunner,
  selectedModel,
  selectedVariant,
  opencodeModelsLoading,
  opencodeModelsError,
  fixJob,
  onStartFixJob,
  onCancelFixJob,
}: FeedbackSidebarProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftFeedback, setDraftFeedback] = useState("");
  const [isStartingFix, setIsStartingFix] = useState(false);
  const [isCancellingFix, setIsCancellingFix] = useState(false);
  const [isEditingBranchName, setIsEditingBranchName] = useState(false);
  const [branchNameDraft, setBranchNameDraft] = useState("");
  const [isSavingBranchName, setIsSavingBranchName] = useState(false);
  const [branchActionError, setBranchActionError] = useState<string | null>(null);
  const annotationsScrollContainerRef = useRef<HTMLDivElement | null>(null);

  const activeBranch = useMemo(
    () => branches.find((branch) => branch.id === activeBranchId) ?? null,
    [branches, activeBranchId],
  );

  const versionOrder = useMemo(() => {
    if (!activeBranch) {
      return new Map<string, number>();
    }

    const byId = new Map(versions.map((version) => [version.id, version]));
    const chain: string[] = [];
    const seen = new Set<string>();
    let cursor: string | null = activeBranch.head_version_id;

    while (cursor && !seen.has(cursor)) {
      seen.add(cursor);
      const node = byId.get(cursor);
      if (!node) {
        break;
      }
      chain.push(node.id);
      cursor = node.parent_version_id;
    }

    chain.reverse();

    const order = new Map<string, number>();
    chain.forEach((id, index) => {
      order.set(id, index);
    });
    return order;
  }, [versions, activeBranch]);

  const checkedOutOrder = checkedOutVersionId
    ? versionOrder.get(checkedOutVersionId)
    : undefined;
  const isInitialFocused =
    !!rootVersionId && checkedOutVersionId === rootVersionId;

  const sorted = useMemo(
    () =>
      annotations
        .filter(
          (ann) =>
            !activeBranchId || !ann.branch_id || ann.branch_id === activeBranchId,
        )
        .sort((a, b) => {
          const byTime = a.created_at.localeCompare(b.created_at);
          return byTime !== 0 ? byTime : a.id.localeCompare(b.id);
        }),
    [annotations, activeBranchId],
  );

  const pendingCount = useMemo(
    () => sorted.filter((ann) => ann.status === "pending").length,
    [sorted],
  );

  const annotationListStateRef = useRef({
    branchId: activeBranchId,
    count: sorted.length,
  });

  useEffect(() => {
    const previous = annotationListStateRef.current;
    const sameBranch = previous.branchId === activeBranchId;
    const hasNewAnnotation = sameBranch && sorted.length > previous.count;

    annotationListStateRef.current = {
      branchId: activeBranchId,
      count: sorted.length,
    };

    if (!hasNewAnnotation) {
      return;
    }

    const rafId = window.requestAnimationFrame(() => {
      const viewport = annotationsScrollContainerRef.current?.querySelector<HTMLElement>(
        '[data-slot="scroll-area-viewport"]',
      );
      if (!viewport) {
        return;
      }
      viewport.scrollTop = viewport.scrollHeight;
    });

    return () => {
      window.cancelAnimationFrame(rafId);
    };
  }, [activeBranchId, sorted.length]);

  const canSwitchBranch = branches.length > 0;

  const isFixRunning = fixJob?.status === "queued" || fixJob?.status === "running";
  const isFixOnActiveBranch = !!fixJob && fixJob.branch_id === activeBranchId;

  useEffect(() => {
    setIsEditingBranchName(false);
    setBranchNameDraft("");
    setBranchActionError(null);
    setIsSavingBranchName(false);
  }, [activeBranchId]);

  const startFix = async () => {
    if (!selectedModel) {
      return;
    }

    setIsStartingFix(true);
    try {
      await onStartFixJob(
        selectedRunner,
        selectedModel,
        selectedVariant || undefined,
      );
    } catch (err: unknown) {
      console.error(err);
    } finally {
      setIsStartingFix(false);
    }
  };

  const cancelFix = async () => {
    if (!fixJob) {
      return;
    }

    setIsCancellingFix(true);
    try {
      await onCancelFixJob(fixJob.id);
    } catch (err: unknown) {
      console.error(err);
    } finally {
      setIsCancellingFix(false);
    }
  };

  const startEdit = (ann: Annotation) => {
    if (ann.status !== "pending") {
      return;
    }
    setEditingId(ann.id);
    setDraftFeedback(ann.feedback);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setDraftFeedback("");
  };

  const saveEdit = async (ann: Annotation) => {
    if (ann.status !== "pending") {
      cancelEdit();
      return;
    }

    const next = draftFeedback.trim();
    if (!next || next === ann.feedback) {
      cancelEdit();
      return;
    }
    await onUpdate(ann.id, { feedback: next });
    cancelEdit();
  };

  useEffect(() => {
    if (!editingId) {
      return;
    }
    const editingAnnotation = sorted.find((ann) => ann.id === editingId);
    if (!editingAnnotation || editingAnnotation.status !== "pending") {
      setEditingId(null);
      setDraftFeedback("");
    }
  }, [editingId, sorted]);

  const startBranchEdit = () => {
    if (!activeBranch) {
      return;
    }
    setBranchActionError(null);
    setBranchNameDraft(activeBranch.name);
    setIsEditingBranchName(true);
  };

  const cancelBranchEdit = () => {
    setIsEditingBranchName(false);
    setBranchNameDraft("");
    setBranchActionError(null);
  };

  const saveBranchName = async () => {
    if (!activeBranch) {
      cancelBranchEdit();
      return;
    }

    const nextName = branchNameDraft.trim();
    if (!nextName || nextName === activeBranch.name) {
      cancelBranchEdit();
      return;
    }

    setIsSavingBranchName(true);
    setBranchActionError(null);
    try {
      await onRenameBranch(activeBranch.id, nextName);
      cancelBranchEdit();
    } catch (err: unknown) {
      setBranchActionError(
        err instanceof Error && err.message ? err.message : "Failed to rename branch",
      );
    } finally {
      setIsSavingBranchName(false);
    }
  };

  const onBranchNameKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      cancelBranchEdit();
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      void saveBranchName();
    }
  };

  return (
    <>
      <aside className="flex w-full flex-col border-t border-border/80 bg-card/40 lg:w-80 lg:border-t-0 lg:border-l xl:w-[22rem]">
        <div className="flex items-center justify-between px-4 py-3">
          <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            Annotations
          </h2>
          <div className="flex items-center gap-2">
            {canSwitchBranch ? (
              isEditingBranchName && activeBranch ? (
                <div className="flex items-center gap-1">
                  <div className="flex h-6 items-center gap-1 rounded-md border border-border/80 bg-background px-1.5">
                    <GitBranch className="h-3.5 w-3.5 text-muted-foreground" />
                    <Input
                      value={branchNameDraft}
                      onChange={(event) => setBranchNameDraft(event.target.value)}
                      onKeyDown={onBranchNameKeyDown}
                      maxLength={120}
                      autoFocus
                      className="h-5 w-24 border-0 bg-transparent px-0 text-[11px] shadow-none focus-visible:ring-0"
                      disabled={isSavingBranchName}
                      aria-label="Edit branch name"
                    />
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => {
                      void saveBranchName();
                    }}
                    disabled={isSavingBranchName || !branchNameDraft.trim()}
                    aria-label="Save branch name"
                  >
                    <Check className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    onClick={cancelBranchEdit}
                    disabled={isSavingBranchName}
                    aria-label="Cancel branch rename"
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-1">
                  <div className="flex h-6 items-center gap-1 rounded-md border border-border/80 bg-background px-1.5">
                    <GitBranch className="h-3.5 w-3.5 text-muted-foreground" />
                    <select
                      value={activeBranchId}
                      onChange={(event) => {
                        cancelBranchEdit();
                        void onSwitchBranch(event.target.value);
                      }}
                      className="h-5 max-w-24 bg-transparent py-0 pr-1 text-[11px] text-foreground outline-none"
                      aria-label="Switch branch"
                    >
                      {branches.map((branch) => (
                        <option key={branch.id} value={branch.id}>
                          {branch.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  {activeBranch ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      onClick={startBranchEdit}
                      aria-label="Rename branch"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                  ) : null}
                </div>
              )
            ) : null}

            <Badge variant="secondary">{sorted.length}</Badge>
          </div>
        </div>

        {branchActionError ? (
          <div className="px-4 pb-2 text-[11px] text-destructive">{branchActionError}</div>
        ) : null}

        <Separator />

        <div ref={annotationsScrollContainerRef} className="h-72 lg:flex-1">
          <ScrollArea data-walkthrough="annotations-list" className="h-full">
            <ul className="space-y-3 p-4">
          <li onClick={() => onSelectInitialState()} className="cursor-pointer">
            <Card
              size="sm"
              className={`border bg-background/85 shadow-xs transition ${
                isInitialFocused
                  ? "border-foreground/65 ring-2 ring-foreground/25"
                  : "border-border/80"
              }`}
            >
              <CardContent className="space-y-2.5 pt-3">
                <div className="rounded-md border border-border/70 bg-muted/40 px-3.5 py-2.5">
                  <p className="text-base leading-7 font-semibold text-foreground">
                    Initial plot
                  </p>
                </div>

                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="h-6 rounded-full px-2.5">
                      #0
                    </Badge>

                    <Badge
                      variant="secondary"
                      className="bg-slate-200 text-slate-800"
                    >
                      root
                    </Badge>
                  </div>
                </div>
              </CardContent>
            </Card>
          </li>

          {sorted.length === 0 ? (
            <li>
              <Card
                size="sm"
                className="border border-dashed border-border/90 bg-background/80"
              >
                <CardHeader>
                  <CardTitle className="text-sm">
                    No annotations on this branch
                  </CardTitle>
                  <CardDescription>
                    Draw a region on the plot to add feedback.
                  </CardDescription>
                </CardHeader>
              </Card>
            </li>
          ) : null}

          {sorted.map((ann, idx) => {
            const anchorVersionId = ann.addressed_in_version_id ?? ann.base_version_id;
            const anchorOrder = anchorVersionId
              ? versionOrder.get(anchorVersionId)
              : undefined;
            const isDimmed =
              checkedOutOrder !== undefined &&
              anchorOrder !== undefined &&
              anchorOrder > checkedOutOrder;
            const isFocused =
              focusedAnnotationId === ann.id ||
              (!!ann.addressed_in_version_id &&
                ann.addressed_in_version_id === checkedOutVersionId);
            const isHeadAnnotation =
              ann.status === "addressed" &&
              !!ann.addressed_in_version_id &&
              !!activeBranch &&
              ann.addressed_in_version_id === activeBranch.head_version_id;
            const canEdit = ann.status === "pending";
            const canDelete = ann.status === "pending" || isHeadAnnotation;
            const annotationTime = formatAnnotationTimestamp(ann.created_at);

            return (
              <li
                key={ann.id}
                onClick={() => onSelectAnnotation(ann)}
                className="cursor-pointer"
              >
                <Card
                  size="sm"
                  className={`border bg-background/85 shadow-xs transition ${
                    isFocused
                      ? "border-foreground/65 ring-2 ring-foreground/25"
                      : "border-border/80"
                  } ${isDimmed ? "opacity-45" : "opacity-100"}`}
                >
                  <CardContent className="space-y-2.5 pt-3">
                    {editingId === ann.id ? (
                      <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
                        <Textarea
                          value={draftFeedback}
                          onChange={(e) => setDraftFeedback(e.target.value)}
                          className="min-h-24 resize-y"
                        />
                        <div className="flex gap-2">
                          <Button
                            onClick={() => saveEdit(ann)}
                            size="sm"
                            className="gap-1.5"
                          >
                            <CheckCheck className="h-3.5 w-3.5" />
                            Save
                          </Button>
                          <Button
                            onClick={cancelEdit}
                            size="sm"
                            variant="outline"
                          >
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="rounded-md border border-border/70 bg-muted/40 px-3.5 py-2.5">
                          <div className="flex items-start justify-between gap-2">
                            <p className="min-w-0 text-base leading-7 font-semibold text-foreground">
                              {ann.feedback}
                            </p>
                            <div className="mt-0.5 flex shrink-0 items-center gap-1">
                              {ann.status === "addressed" ? (
                                <Button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void onDownload(ann);
                                  }}
                                  size="icon-xs"
                                  variant="ghost"
                                  className="text-muted-foreground hover:text-foreground"
                                  title="Download plot + script"
                                  aria-label="Download plot + script"
                                >
                                  <Download className="h-3.5 w-3.5" />
                                </Button>
                              ) : null}

                              <Button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (!canEdit) {
                                    return;
                                  }
                                  startEdit(ann);
                                }}
                                size="icon-xs"
                                variant="ghost"
                                disabled={!canEdit}
                                className="text-muted-foreground hover:text-foreground"
                                title={canEdit ? "Edit annotation" : "Only pending annotations can be edited"}
                                aria-label="Edit annotation"
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </div>
                        </div>

                      </>
                    )}

                    {ann.element_info && (
                      <p className="text-xs text-muted-foreground">
                        &lt;{ann.element_info.tag}&gt;{" "}
                        {ann.element_info.text_content
                          ? `"${ann.element_info.text_content}"`
                          : ""}
                      </p>
                    )}

                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="h-6 rounded-full px-2.5">
                          #{idx + 1}
                        </Badge>

                        <Badge
                          variant="secondary"
                          className={
                            ann.status === "pending"
                              ? "bg-amber-100 text-amber-800"
                              : "bg-foreground/10 text-foreground"
                          }
                        >
                          {ann.status}
                        </Badge>
                      </div>

                      <div className="flex items-center gap-2">
                        {annotationTime ? (
                          <span className="text-[10px] text-muted-foreground">
                            {annotationTime}
                          </span>
                        ) : null}
                        <Button
                          onClick={(e) => {
                            e.stopPropagation();
                            if (canDelete) {
                              void onDelete(ann.id);
                            }
                          }}
                          disabled={!canDelete}
                          variant="ghost"
                          size="icon-xs"
                          className="text-muted-foreground hover:text-destructive disabled:opacity-35"
                          title={
                            canDelete
                              ? "Delete annotation"
                              : "Tip-only undo: switch to branch head to delete this addressed annotation"
                          }
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </li>
            );
          })}
            </ul>
          </ScrollArea>
        </div>

        <Separator />

        <div data-walkthrough="fix-panel" className="p-4">
          <Button
            type="button"
            onClick={() => {
              if (isFixRunning && isFixOnActiveBranch && fixJob) {
                void cancelFix();
                return;
              }
              void startFix();
            }}
            disabled={
              isFixRunning && isFixOnActiveBranch && fixJob
                ? isCancellingFix
                : !selectedModel ||
                  opencodeModelsLoading ||
                  !!opencodeModelsError ||
                  pendingCount === 0 ||
                  isFixRunning ||
                  isStartingFix
            }
            className={`w-full rounded-full px-4 ${
              isFixRunning && isFixOnActiveBranch && fixJob
                ? "bg-black/70 text-white hover:bg-black/65"
                : "bg-black text-white hover:bg-black/88"
            }`}
          >
            {isFixRunning && isFixOnActiveBranch && fixJob ? (
              isCancellingFix ? (
                <Loader2 className="animate-spin" data-icon="inline-start" />
              ) : (
                <Pause data-icon="inline-start" />
              )
            ) : isStartingFix ? (
              <Loader2 className="animate-spin" data-icon="inline-start" />
            ) : (
              <Play data-icon="inline-start" />
            )}
            {isFixRunning && isFixOnActiveBranch && fixJob ? "Stop" : "Fix"}
          </Button>
        </div>
      </aside>
    </>
  );
}
