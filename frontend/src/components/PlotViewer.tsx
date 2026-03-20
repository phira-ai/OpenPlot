import { useEffect, useMemo, useState, useCallback } from "react";
import { ArrowUpRight, Loader2, Minus, Plus } from "lucide-react";
import type { RegionInfo, Annotation } from "../types";
import RasterAnnotator from "./RasterAnnotator";
import FeedbackPrompt from "./FeedbackPrompt";
import { Button } from "@/components/ui/button";

interface FixStatusBubble {
  instruction: string;
  onOpen: () => void;
  running?: boolean;
}

interface PlotViewerProps {
  imageUrl: string;
  workspaceId: string;
  annotations: Annotation[];
  focusedAnnotationId?: string | null;
  onAddAnnotation: (annotation: Partial<Annotation>) => Promise<unknown>;
  fixStatusBubble?: FixStatusBubble | null;
  onSelectionActivityChange?: (active: boolean) => void;
  onGraphHoverChange?: (hovered: boolean) => void;
}

const MIN_GRAPH_ZOOM = 0.5;
const MAX_GRAPH_ZOOM = 2.5;
const GRAPH_ZOOM_STEP = 0.1;
const GRAPH_ZOOM_STORAGE_KEY_PREFIX = "openplot:graph-zoom";

function graphZoomStorageKey(workspaceId: string): string {
  return `${GRAPH_ZOOM_STORAGE_KEY_PREFIX}:${workspaceId}`;
}

function loadGraphZoom(workspaceId: string): number {
  if (typeof window === "undefined") {
    return 1;
  }
  try {
    const raw = window.localStorage.getItem(graphZoomStorageKey(workspaceId));
    if (!raw) {
      return 1;
    }
    const parsed = Number(raw);
    if (Number.isFinite(parsed)) {
      return clampZoom(parsed);
    }
  } catch {
    // Ignore storage read failures and use default zoom.
  }
  return 1;
}

function clampZoom(value: number): number {
  const clamped = Math.min(MAX_GRAPH_ZOOM, Math.max(MIN_GRAPH_ZOOM, value));
  return Math.round(clamped * 100) / 100;
}

/**
 * Renders the current plot with a unified region-draw annotation flow.
 * Both SVG and raster plots use the same raster-style rectangular selection.
 */
export default function PlotViewer({
  imageUrl,
  workspaceId,
  annotations,
  focusedAnnotationId,
  onAddAnnotation,
  fixStatusBubble = null,
  onSelectionActivityChange,
  onGraphHoverChange,
}: PlotViewerProps) {
  const [selectionPreviewRect, setSelectionPreviewRect] = useState<DOMRect | null>(null);
  const [selectedRegion, setSelectedRegion] = useState<{
    info: RegionInfo;
    anchorRect: DOMRect;
  } | null>(null);
  const [graphZoom, setGraphZoom] = useState(() => loadGraphZoom(workspaceId));
  const [isGraphHovered, setIsGraphHovered] = useState(false);
  const [isSelectionDrawing, setIsSelectionDrawing] = useState(false);

  const clearSelectionState = useCallback(() => {
    setSelectionPreviewRect(null);
    setSelectedRegion(null);
  }, []);

  const changeGraphZoom = useCallback((delta: number) => {
    setGraphZoom((z) => clampZoom(z + delta));
  }, []);

  const resetGraphZoom = useCallback(() => {
    setGraphZoom(1);
  }, []);

  const zoomLabel = useMemo(() => `${Math.round(graphZoom * 100)}%`, [graphZoom]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      window.localStorage.setItem(graphZoomStorageKey(workspaceId), String(graphZoom));
    } catch {
      // Ignore storage write failures.
    }
  }, [graphZoom, workspaceId]);

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key !== "Escape") {
        return;
      }
      if (!selectedRegion && !selectionPreviewRect) {
        return;
      }
      clearSelectionState();
    };

    window.addEventListener("keydown", handleEscape, true);
    return () => window.removeEventListener("keydown", handleEscape, true);
  }, [selectedRegion, selectionPreviewRect, clearSelectionState]);

  useEffect(() => {
    onSelectionActivityChange?.(
      Boolean(isSelectionDrawing || selectionPreviewRect || selectedRegion),
    );
  }, [isSelectionDrawing, onSelectionActivityChange, selectedRegion, selectionPreviewRect]);

  useEffect(() => {
    onGraphHoverChange?.(isGraphHovered);
  }, [isGraphHovered, onGraphHoverChange]);

  useEffect(
    () => () => {
      onGraphHoverChange?.(false);
    },
    [onGraphHoverChange],
  );

  useEffect(() => {
    const handleZoomHotkey = (e: KeyboardEvent) => {
      if (!isGraphHovered) {
        return;
      }

      const hasZoomModifier = e.ctrlKey || e.metaKey;
      if (!hasZoomModifier) {
        return;
      }

      const isZoomInKey = e.key === "+" || e.key === "=" || e.code === "NumpadAdd";
      const isZoomOutKey = e.key === "-" || e.key === "_" || e.code === "NumpadSubtract";
      const isResetKey = e.key === "0" || e.code === "Numpad0";

      if (!isZoomInKey && !isZoomOutKey && !isResetKey) {
        return;
      }

      e.preventDefault();

      if (isZoomInKey) {
        changeGraphZoom(GRAPH_ZOOM_STEP);
        return;
      }
      if (isZoomOutKey) {
        changeGraphZoom(-GRAPH_ZOOM_STEP);
        return;
      }
      resetGraphZoom();
    };

    window.addEventListener("keydown", handleZoomHotkey, true);
    return () => window.removeEventListener("keydown", handleZoomHotkey, true);
  }, [isGraphHovered, changeGraphZoom, resetGraphZoom]);

  const handleRegionDrawn = useCallback(
    (info: RegionInfo, anchorRect: DOMRect) => {
      setSelectionPreviewRect(null);
      setSelectedRegion({ info, anchorRect });
    },
    [],
  );

  const handleSelectionPreview = useCallback((anchorRect: DOMRect | null) => {
    setSelectionPreviewRect(anchorRect);
  }, []);

  const handleFeedbackSubmit = useCallback(
    async (feedback: string) => {
      if (selectedRegion) {
        await onAddAnnotation({
          region: selectedRegion.info,
          feedback,
        });
        clearSelectionState();
      }
    },
    [selectedRegion, onAddAnnotation, clearSelectionState],
  );

  const handleFeedbackCancel = useCallback(() => {
    clearSelectionState();
  }, [clearSelectionState]);

  const spotlightRect = selectedRegion?.anchorRect ?? selectionPreviewRect;

  const spotlightStyle = spotlightRect
    ? {
        left: spotlightRect.left,
        top: spotlightRect.top,
        width: Math.max(spotlightRect.width, 1),
        height: Math.max(spotlightRect.height, 1),
        borderRadius: `${Math.min(
          10,
          Math.max(spotlightRect.width - 2, 1) / 6,
          Math.max(spotlightRect.height - 2, 1) / 6,
        )}px`,
        boxShadow: "0 0 0 9999px rgba(12, 12, 12, 0.36)",
      }
    : undefined;

  return (
    <>
      <div
        data-walkthrough="plot-canvas"
        className="relative h-full min-w-0 w-full overflow-hidden"
        onMouseEnter={() => setIsGraphHovered(true)}
        onMouseLeave={() => setIsGraphHovered(false)}
      >
        <RasterAnnotator
          imageUrl={imageUrl}
          annotations={annotations}
          focusedAnnotationId={focusedAnnotationId}
          onRegionDrawn={handleRegionDrawn}
          onSelectionPreview={handleSelectionPreview}
          onDrawingChange={setIsSelectionDrawing}
          clearSelection={!selectedRegion}
          zoom={graphZoom}
        />

        <div className="pointer-events-none absolute right-4 top-4 z-30">
          <div className="pointer-events-auto inline-flex items-center gap-1 rounded-lg border border-border/90 bg-background/92 p-1 shadow-sm backdrop-blur">
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              onClick={() => changeGraphZoom(-GRAPH_ZOOM_STEP)}
              disabled={graphZoom <= MIN_GRAPH_ZOOM}
              title="Zoom out graph"
              aria-label="Zoom out graph"
            >
              <Minus className="h-3.5 w-3.5" />
            </Button>

            <button
              type="button"
              onClick={resetGraphZoom}
              className="min-w-14 rounded-md px-2 py-1 text-xs font-semibold text-foreground hover:bg-muted"
              title="Reset graph zoom"
            >
              {zoomLabel}
            </button>

            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              onClick={() => changeGraphZoom(GRAPH_ZOOM_STEP)}
              disabled={graphZoom >= MAX_GRAPH_ZOOM}
              title="Zoom in graph"
              aria-label="Zoom in graph"
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {fixStatusBubble ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-4 z-30 flex justify-center px-4">
            <button
              type="button"
              onClick={fixStatusBubble.onOpen}
              className="pointer-events-auto flex items-center gap-3 rounded-full border border-white/10 bg-[#171b22]/94 px-4 py-2 text-sm text-white shadow-2xl shadow-black/18 backdrop-blur-xl transition-all"
              aria-label={`Fixing: ${fixStatusBubble.instruction}`}
            >
              {fixStatusBubble.running ? (
                <Loader2 className="size-4 animate-spin text-white/70" />
              ) : (
                <ArrowUpRight className="size-4 text-white/70" />
              )}
              <span className="max-w-[28rem] truncate">
                <span className="font-semibold">Fixing:</span> {fixStatusBubble.instruction}
              </span>
            </button>
          </div>
        ) : null}
      </div>

      {spotlightRect && (
        <div aria-hidden className="pointer-events-none fixed inset-0 z-40">
          <div
            className="absolute"
            style={spotlightStyle}
          />
        </div>
      )}
      {selectedRegion && (
        <FeedbackPrompt
          regionInfo={selectedRegion.info}
          anchorRect={selectedRegion.anchorRect}
          onSubmit={handleFeedbackSubmit}
          onCancel={handleFeedbackCancel}
        />
      )}
    </>
  );
}
