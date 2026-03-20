import { useEffect, useMemo, useState } from "react";
import { Loader2, X } from "lucide-react";

import type {
  PlotModeSheetBounds,
  PlotModeTabularSelectionRegion,
  PlotModeTabularSelector,
} from "../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

interface TabularRangeSelectorDialogProps {
  selector: PlotModeTabularSelector | null;
  open: boolean;
  submitting: boolean;
  onSubmit: (
    selectorId: string,
    regions: Array<{
      sheet_id: string;
      row_start: number;
      row_end: number;
      col_start: number;
      col_end: number;
    }>,
    note: string,
  ) => Promise<void>;
}

function columnLabel(index: number): string {
  let label = "";
  let value = index + 1;
  while (value > 0) {
    const remainder = (value - 1) % 26;
    label = String.fromCharCode(65 + remainder) + label;
    value = Math.floor((value - 1) / 26);
  }
  return label || "A";
}

function normalizeBounds(
  start: { row: number; col: number } | null,
  end: { row: number; col: number } | null,
): PlotModeSheetBounds | null {
  if (!start || !end) {
    return null;
  }
  return {
    row_start: Math.min(start.row, end.row),
    row_end: Math.max(start.row, end.row),
    col_start: Math.min(start.col, end.col),
    col_end: Math.max(start.col, end.col),
  };
}

function formatBounds(bounds: PlotModeSheetBounds): string {
  return `${columnLabel(bounds.col_start)}${bounds.row_start + 1}:${columnLabel(bounds.col_end)}${bounds.row_end + 1}`;
}

function boundsEqual(left: PlotModeSheetBounds, right: PlotModeSheetBounds): boolean {
  return (
    left.row_start === right.row_start &&
    left.row_end === right.row_end &&
    left.col_start === right.col_start &&
    left.col_end === right.col_end
  );
}

function cellIsSelected(bounds: PlotModeSheetBounds, row: number, col: number): boolean {
  return (
    row >= bounds.row_start &&
    row <= bounds.row_end &&
    col >= bounds.col_start &&
    col <= bounds.col_end
  );
}

function regionMatches(
  region: PlotModeTabularSelectionRegion,
  sheetId: string,
  bounds: PlotModeSheetBounds,
): boolean {
  return region.sheet_id === sheetId && boundsEqual(region.bounds, bounds);
}

function localRegionId(sheetId: string, bounds: PlotModeSheetBounds): string {
  return `${sheetId}:${bounds.row_start}:${bounds.row_end}:${bounds.col_start}:${bounds.col_end}`;
}

export default function TabularRangeSelectorDialog({
  selector,
  open,
  submitting,
  onSubmit,
}: TabularRangeSelectorDialogProps) {
  const [selectedSheetId, setSelectedSheetId] = useState<string>("");
  const [dragStart, setDragStart] = useState<{ row: number; col: number } | null>(null);
  const [dragEnd, setDragEnd] = useState<{ row: number; col: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [selectionNote, setSelectionNote] = useState("");
  const [selectedRegions, setSelectedRegions] = useState<PlotModeTabularSelectionRegion[]>([]);

  const selectedSheet = useMemo(
    () => selector?.sheets.find((sheet) => sheet.id === selectedSheetId) ?? selector?.sheets[0] ?? null,
    [selectedSheetId, selector],
  );

  const draftBounds = useMemo(() => normalizeBounds(dragStart, dragEnd), [dragStart, dragEnd]);

  const draftRegion = useMemo(() => {
    if (!selectedSheet || !draftBounds) {
      return null;
    }
    return {
      id: localRegionId(selectedSheet.id, draftBounds),
      sheet_id: selectedSheet.id,
      sheet_name: selectedSheet.name,
      bounds: draftBounds,
    } satisfies PlotModeTabularSelectionRegion;
  }, [draftBounds, selectedSheet]);

  const regionsForSelectedSheet = useMemo(
    () => selectedRegions.filter((region) => region.sheet_id === selectedSheet?.id),
    [selectedRegions, selectedSheet],
  );

  const draftAlreadyAdded = useMemo(() => {
    if (!draftRegion) {
      return false;
    }
    return selectedRegions.some((region) => regionMatches(region, draftRegion.sheet_id, draftRegion.bounds));
  }, [draftRegion, selectedRegions]);

  const regionsToSubmit = useMemo(() => {
    if (!draftRegion || draftAlreadyAdded) {
      return selectedRegions;
    }
    return [...selectedRegions, draftRegion];
  }, [draftAlreadyAdded, draftRegion, selectedRegions]);

  useEffect(() => {
    if (!selector) {
      setSelectedSheetId("");
      setDragStart(null);
      setDragEnd(null);
      setSelectionNote("");
      setSelectedRegions([]);
      return;
    }
    setSelectedSheetId(selector.selected_sheet_id || selector.sheets[0]?.id || "");
    setDragStart(null);
    setDragEnd(null);
    setSelectionNote("");
    setSelectedRegions(selector.selected_regions ?? []);
  }, [selector]);

  useEffect(() => {
    const handleMouseUp = () => setDragging(false);
    window.addEventListener("mouseup", handleMouseUp);
    return () => window.removeEventListener("mouseup", handleMouseUp);
  }, []);

  if (!selector || !open || !selectedSheet) {
    return null;
  }

  const addDraftRegion = () => {
    if (!draftRegion || draftAlreadyAdded) {
      return;
    }
    setSelectedRegions((current) => [...current, draftRegion]);
    setDragStart(null);
    setDragEnd(null);
  };

  return (
    <Dialog open={open} onOpenChange={() => undefined}>
      <DialogContent
        showCloseButton={false}
        className="flex max-h-[90vh] max-w-[min(96vw,1180px)] flex-col gap-0 overflow-hidden p-0"
      >
        <DialogHeader className="gap-2 border-b border-border/70 px-6 py-5">
          <div className="flex flex-col gap-2">
            <DialogTitle>Select one or more spreadsheet regions</DialogTitle>
            <DialogDescription>
              {selector.status_text} Drag across the spreadsheet grid, add each region, then submit the full set. OpenPlot will infer the actual tables from those hints and show a grouped preview before plotting.
            </DialogDescription>
          </div>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-6 py-5">
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden" role="tablist" aria-label="Workbook sheets">
            <div className="flex h-14 max-w-full shrink-0 items-stretch gap-1 overflow-x-auto overflow-y-hidden rounded-2xl bg-muted/40 p-1">
              {selector.sheets.map((sheet) => {
                const sheetSelectionCount = selectedRegions.filter((region) => region.sheet_id === sheet.id).length;
                return (
                  <button
                    type="button"
                    key={sheet.id}
                    role="tab"
                    aria-selected={selectedSheetId === sheet.id}
                    title={sheet.name}
                    className={`flex h-12 w-44 shrink-0 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm leading-5 transition-colors ${
                      selectedSheetId === sheet.id
                        ? "bg-background text-foreground shadow-sm"
                        : "text-foreground/60 hover:text-foreground"
                    }`}
                    onClick={() => setSelectedSheetId(sheet.id)}
                  >
                    <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap pb-px">
                      {sheet.name}
                    </span>
                    {sheetSelectionCount > 0 ? (
                      <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-[11px] font-medium text-zinc-900">
                        {sheetSelectionCount}
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>

            <div className="grid min-h-0 flex-1 gap-4 overflow-hidden lg:grid-cols-[minmax(0,1fr)_320px]">
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden" role="tabpanel">
                <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
                  {selectedSheet.candidate_tables.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {selectedSheet.candidate_tables.map((candidate) => (
                        <Badge key={candidate.id} variant="outline" className="rounded-full px-2.5">
                          {candidate.label}
                        </Badge>
                      ))}
                    </div>
                  ) : null}

                  <div className="min-h-0 flex-1 overflow-auto rounded-2xl border border-border/70 bg-background/90 shadow-sm">
                    <table className="min-w-full select-none border-collapse text-xs text-foreground">
                      <thead>
                        <tr>
                          <th className="sticky left-0 top-0 z-20 min-w-12 border-b border-r border-border bg-muted/70 px-2 py-2 text-right font-medium text-muted-foreground">
                            #
                          </th>
                          {Array.from({ length: selectedSheet.preview_rows[0]?.length ?? 0 }).map((_, columnIndex) => (
                            <th
                              key={`${selectedSheet.id}:col:${columnIndex}`}
                              className="sticky top-0 z-10 min-w-24 border-b border-border bg-muted/70 px-3 py-2 text-center font-medium text-muted-foreground"
                            >
                              {columnLabel(columnIndex)}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {selectedSheet.preview_rows.map((row, rowIndex) => (
                          <tr key={`${selectedSheet.id}:row:${rowIndex}`}>
                            <th className="sticky left-0 z-10 min-w-12 border-r border-border bg-muted/50 px-2 py-2 text-right font-medium text-muted-foreground">
                              {rowIndex + 1}
                            </th>
                            {row.map((cell, columnIndex) => {
                              const inSavedRegion = regionsForSelectedSheet.some((region) =>
                                cellIsSelected(region.bounds, rowIndex, columnIndex),
                              );
                              const inDraftRegion = Boolean(
                                draftBounds && cellIsSelected(draftBounds, rowIndex, columnIndex),
                              );
                              return (
                                <td
                                  key={`${selectedSheet.id}:row:${rowIndex}:col:${columnIndex}`}
                                  className="border border-border/60 p-0"
                                >
                                  <button
                                    type="button"
                                    className={`flex h-10 w-full min-w-24 items-center px-3 py-2 text-left align-top transition ${
                                      inDraftRegion
                                        ? "bg-zinc-200/80 text-foreground ring-1 ring-inset ring-zinc-500/45"
                                        : inSavedRegion
                                          ? "bg-zinc-100 text-foreground"
                                          : "bg-background text-muted-foreground hover:bg-muted/35"
                                    }`}
                                    onMouseDown={(event) => {
                                      event.preventDefault();
                                      setSelectedSheetId(selectedSheet.id);
                                      setDragStart({ row: rowIndex, col: columnIndex });
                                      setDragEnd({ row: rowIndex, col: columnIndex });
                                      setDragging(true);
                                    }}
                                    onMouseEnter={() => {
                                      if (!dragging) {
                                        return;
                                      }
                                      setDragEnd({ row: rowIndex, col: columnIndex });
                                    }}
                                  >
                                    <span className="truncate">{cell || " "}</span>
                                  </button>
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <div className="flex min-h-0 flex-col gap-3 overflow-hidden rounded-2xl border border-border/70 bg-muted/20 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-foreground">Current draft</div>
                    <div className="text-xs text-muted-foreground">
                      {draftBounds
                        ? `${selectedSheet.name}!${formatBounds(draftBounds)}`
                        : "Drag across cells to draft the next region."}
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="rounded-full"
                    disabled={!draftBounds || draftAlreadyAdded || submitting}
                    onClick={addDraftRegion}
                  >
                    Add region
                  </Button>
                </div>

                <div className="min-h-0 flex-1 overflow-auto rounded-2xl border border-border/70 bg-background/80 p-3">
                  <div className="mb-2 text-sm font-medium text-foreground">
                    Selected regions ({regionsToSubmit.length})
                  </div>
                  <div className="flex flex-col gap-2">
                    {regionsToSubmit.length > 0 ? (
                      regionsToSubmit.map((region) => {
                        const isDraft = Boolean(draftRegion && region.id === draftRegion.id);
                        return (
                          <div
                            key={`${region.id}:${region.sheet_id}:${formatBounds(region.bounds)}`}
                            className={`flex items-start justify-between gap-3 rounded-2xl border px-3 py-2 ${
                              isDraft ? "border-zinc-300 bg-zinc-50" : "border-zinc-300 bg-zinc-100/80"
                            }`}
                          >
                            <div className="min-w-0">
                              <div className="text-sm font-medium text-foreground">
                                {region.sheet_name || "Sheet"}
                              </div>
                              <div className="text-xs text-muted-foreground">{formatBounds(region.bounds)}</div>
                            </div>
                            {isDraft ? (
                              <Badge variant="outline" className="rounded-full text-[11px]">
                                Draft
                              </Badge>
                            ) : (
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="size-7 rounded-full"
                                disabled={submitting}
                                onClick={() => {
                                  setSelectedRegions((current) =>
                                    current.filter((item) => item.id !== region.id),
                                  );
                                }}
                              >
                                <X className="size-4" />
                              </Button>
                            )}
                          </div>
                        );
                      })
                    ) : (
                      <div className="text-xs text-muted-foreground">
                        No regions added yet. Mark one or more ranges across any sheets in this workbook.
                      </div>
                    )}
                  </div>
                </div>

                <div className="rounded-2xl border border-border/70 bg-background/80 p-3">
                  <div className="mb-2 text-xs font-medium text-foreground">Optional note</div>
                  <Textarea
                    value={selectionNote}
                    onChange={(event) => setSelectionNote(event.target.value)}
                    placeholder="Example: combine the metadata block on Sheet1 with the values table on Sheet2"
                    disabled={submitting}
                    className="min-h-[96px] resize-none border-0 bg-transparent px-0 py-0 text-sm leading-6 shadow-none focus-visible:border-transparent focus-visible:ring-0"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <DialogFooter className="flex-col items-stretch gap-3 px-6 pt-4 pb-6 sm:justify-between">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-xs text-muted-foreground">
              {regionsToSubmit.length > 0
                ? `${regionsToSubmit.length} region${regionsToSubmit.length === 1 ? "" : "s"} ready for inference.`
                : "Add at least one region before continuing."}
            </div>
            {submitting ? (
              <div className="text-xs font-medium text-muted-foreground">
                Turning your hints into table proposals...
              </div>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              className="rounded-full"
              disabled={submitting}
              onClick={() => {
                setSelectedRegions([]);
                setDragStart(null);
                setDragEnd(null);
              }}
            >
              Reset all
            </Button>
            <Button
              type="button"
              className={`rounded-full transition-colors ${
                submitting ? "bg-slate-700 text-white hover:bg-slate-700" : "bg-black text-white hover:bg-black/88"
              }`}
              disabled={submitting || regionsToSubmit.length === 0}
              onClick={() => {
                void onSubmit(
                  selector.id,
                  regionsToSubmit.map((region) => ({
                    sheet_id: region.sheet_id,
                    row_start: region.bounds.row_start,
                    row_end: region.bounds.row_end,
                    col_start: region.bounds.col_start,
                    col_end: region.bounds.col_end,
                  })),
                  selectionNote,
                );
              }}
            >
              {submitting ? (
                <>
                  <Loader2 className="animate-spin" data-icon="inline-start" />
                  Inferring regions...
                </>
              ) : (
                "Use Selection Hints"
              )}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
