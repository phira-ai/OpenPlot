import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChartNoAxesColumn, Download, Loader2, Minus, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { computePlotPreviewViewport } from "@/lib/plotModeUi";
import { cn } from "@/lib/utils";

interface PlotModePreviewProps {
  hasPlot: boolean;
  imageUrl: string;
  workspaceId: string;
  plotVersion: number;
  downloadingExport?: boolean;
  onDownload?: () => Promise<void> | void;
  onGraphHoverChange?: (hovered: boolean) => void;
}

const MIN_GRAPH_ZOOM = 0.5;
const MAX_GRAPH_ZOOM = 2.5;
const GRAPH_ZOOM_STEP = 0.1;
const GRAPH_ZOOM_STORAGE_KEY_PREFIX = "openplot:plot-mode-graph-zoom";
const PREVIEW_FRAME_PADDING = 48;

function clampZoom(value: number): number {
  const clamped = Math.min(MAX_GRAPH_ZOOM, Math.max(MIN_GRAPH_ZOOM, value));
  return Math.round(clamped * 100) / 100;
}

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
    // Ignore storage read failures and use the default zoom.
  }
  return 1;
}

export default function PlotModePreview({
  hasPlot,
  imageUrl,
  workspaceId,
  plotVersion,
  downloadingExport = false,
  onDownload,
  onGraphHoverChange,
}: PlotModePreviewProps) {
  const [failedVersion, setFailedVersion] = useState<number | null>(null);
  const [graphZoom, setGraphZoom] = useState(() => loadGraphZoom(workspaceId));
  const [isGraphHovered, setIsGraphHovered] = useState(false);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [naturalSize, setNaturalSize] = useState({ height: 0, width: 0 });
  const [displayViewport, setDisplayViewport] = useState({ displayHeight: 0, displayWidth: 0 });
  const loadError = failedVersion === plotVersion;
  const zoomLabel = useMemo(() => `${Math.round(graphZoom * 100)}%`, [graphZoom]);

  const changeGraphZoom = useCallback((delta: number) => {
    setGraphZoom((current) => clampZoom(current + delta));
  }, []);

  const resetGraphZoom = useCallback(() => {
    setGraphZoom(1);
  }, []);

  useEffect(() => {
    setGraphZoom(loadGraphZoom(workspaceId));
  }, [workspaceId]);

  useEffect(() => {
    setIsGraphHovered(false);
    setFailedVersion(null);
    setNaturalSize({ height: 0, width: 0 });
    setDisplayViewport({ displayHeight: 0, displayWidth: 0 });
  }, [imageUrl, plotVersion, workspaceId]);

  const syncPreviewViewport = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport || !naturalSize.width || !naturalSize.height) {
      return;
    }
    const rect = viewport.getBoundingClientRect();
    setDisplayViewport(
      computePlotPreviewViewport({
        containerHeight: Math.round(rect.height),
        containerWidth: Math.round(rect.width),
        framePadding: PREVIEW_FRAME_PADDING,
        naturalHeight: naturalSize.height,
        naturalWidth: naturalSize.width,
        zoom: graphZoom,
      }),
    );
  }, [graphZoom, naturalSize.height, naturalSize.width]);

  useEffect(() => {
    syncPreviewViewport();
  }, [plotVersion, syncPreviewViewport]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    const resizeObserver = new ResizeObserver(() => {
      syncPreviewViewport();
    });
    resizeObserver.observe(viewport);

    return () => {
      resizeObserver.disconnect();
    };
  }, [syncPreviewViewport]);

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
    const handleZoomHotkey = (event: KeyboardEvent) => {
      if (!isGraphHovered) {
        return;
      }

      const hasZoomModifier = event.ctrlKey || event.metaKey;
      if (!hasZoomModifier) {
        return;
      }

      const isZoomInKey = event.key === "+" || event.key === "=" || event.code === "NumpadAdd";
      const isZoomOutKey = event.key === "-" || event.key === "_" || event.code === "NumpadSubtract";
      const isResetKey = event.key === "0" || event.code === "Numpad0";

      if (!isZoomInKey && !isZoomOutKey && !isResetKey) {
        return;
      }

      event.preventDefault();

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
  }, [changeGraphZoom, isGraphHovered, resetGraphZoom]);

  useEffect(() => {
    onGraphHoverChange?.(isGraphHovered);
  }, [isGraphHovered, onGraphHoverChange]);

  useEffect(
    () => () => {
      onGraphHoverChange?.(false);
    },
    [onGraphHoverChange],
  );

  return (
    <section
      data-walkthrough="plot-mode-preview"
      className="relative flex h-full min-h-0 flex-col overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(255,255,255,0.95),_rgba(246,247,249,0.75)_40%,_rgba(235,238,242,0.85)_100%)]"
      onMouseEnter={() => setIsGraphHovered(true)}
      onMouseLeave={() => setIsGraphHovered(false)}
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_82%_14%,_rgba(17,24,39,0.07),_transparent_24%),radial-gradient(circle_at_18%_82%,_rgba(15,23,42,0.08),_transparent_30%)]" />

      <div className="relative min-h-0 flex-1 overflow-auto p-4 sm:p-6">
        {!hasPlot || loadError ? (
          <div className="flex h-full min-h-[24rem] items-center justify-center">
            <Card className="w-full max-w-md border border-border/70 bg-background/82 shadow-xl shadow-black/5 backdrop-blur-xl">
              <CardContent className="px-6 py-8 text-center">
                {loadError ? (
                  <p className="text-lg font-medium text-foreground">Preview unavailable</p>
                ) : (
                  <div className="flex items-center justify-center">
                    <div className="flex size-20 items-center justify-center rounded-[1.75rem] border border-border/70 bg-muted/35 text-muted-foreground">
                      <ChartNoAxesColumn className="size-9" />
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        ) : (
          <div
            ref={viewportRef}
            data-plot-preview-viewport
            className="flex min-h-full items-center justify-center"
          >
            <div
              data-plot-preview-frame
              className="relative flex min-h-[24rem] w-full max-w-6xl items-center justify-center overflow-hidden rounded-[2rem] border border-white/80 bg-white/90 p-3 shadow-2xl shadow-slate-900/8 ring-1 ring-black/4 backdrop-blur-xl sm:p-5"
            >
              <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-slate-100/90 via-white/10 to-transparent" />
              <div className="absolute right-4 top-4 z-10">
                <div className="inline-flex items-center gap-1 rounded-lg border border-border/90 bg-background/92 p-1 shadow-sm backdrop-blur">
                  {onDownload ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      onClick={() => {
                        void onDownload();
                      }}
                      disabled={!hasPlot || downloadingExport}
                      title="Download plot and script"
                      aria-label="Download plot and script"
                      className={cn(
                        "transition-opacity duration-150",
                        isGraphHovered || downloadingExport ? "opacity-100" : "opacity-100 sm:opacity-0",
                      )}
                    >
                      {downloadingExport ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Download className="h-3.5 w-3.5" />
                      )}
                    </Button>
                  ) : null}

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

              <img
                src={imageUrl}
                alt="Generated plot preview"
                onLoad={(event) => {
                  setFailedVersion(null);
                  setNaturalSize({
                    height: event.currentTarget.naturalHeight,
                    width: event.currentTarget.naturalWidth,
                  });
                }}
                onError={() => setFailedVersion(plotVersion)}
                className="relative rounded-[1.4rem] border border-black/6 bg-white object-contain shadow-lg shadow-slate-900/6"
                style={{
                  height: displayViewport.displayHeight || undefined,
                  maxWidth: "none",
                  width: displayViewport.displayWidth || undefined,
                }}
              />

            </div>
          </div>
        )}
      </div>
    </section>
  );
}
