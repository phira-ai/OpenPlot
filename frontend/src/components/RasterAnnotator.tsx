import { useEffect, useRef, useState, useCallback } from "react";
import type { Annotation, RegionInfo } from "../types";

interface RasterAnnotatorProps {
  imageUrl: string;
  annotations: Annotation[];
  focusedAnnotationId?: string | null;
  onRegionDrawn: (region: RegionInfo, anchorRect: DOMRect) => void;
  onSelectionPreview?: (anchorRect: DOMRect | null) => void;
  onDrawingChange?: (isDrawing: boolean) => void;
  zoom?: number;
  clearSelection?: boolean;
}

const MIN_DISPLAY_WIDTH = 1;
const CONTAINER_FRAME_MARGIN = 40;

export default function RasterAnnotator({
  imageUrl,
  annotations,
  focusedAnnotationId,
  onRegionDrawn,
  onSelectionPreview,
  onDrawingChange,
  zoom = 1,
  clearSelection = false,
}: RasterAnnotatorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const resizeFrameRef = useRef<number | null>(null);

  const [displaySize, setDisplaySize] = useState({ width: 1, height: 1 });
  const [isDrawing, setIsDrawing] = useState(false);
  const [startPos, setStartPos] = useState<{ x: number; y: number } | null>(null);
  const [currentPos, setCurrentPos] = useState<{ x: number; y: number } | null>(null);
  const [finalRectNorm, setFinalRectNorm] = useState<{
    x0: number;
    y0: number;
    x1: number;
    y1: number;
  } | null>(null);

  const syncCanvasSize = useCallback(() => {
    const img = imageRef.current;
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!img || !canvas || !container) {
      return;
    }

    if (!img.naturalWidth || !img.naturalHeight) {
      return;
    }

    const containerWidth = Math.max(1, Math.round(container.getBoundingClientRect().width));
    const viewportWidth =
      typeof window !== "undefined"
        ? Math.max(1, Math.round(window.innerWidth))
        : containerWidth;
    const availableWidth = Math.max(containerWidth - CONTAINER_FRAME_MARGIN, MIN_DISPLAY_WIDTH);
    const maxSafeAvailableWidth = Math.max(
      MIN_DISPLAY_WIDTH,
      viewportWidth - CONTAINER_FRAME_MARGIN,
    );
    const fittedWidth = Math.min(img.naturalWidth, availableWidth, maxSafeAvailableWidth);
    const width = Math.max(1, Math.round(fittedWidth * zoom));
    const height = Math.max(1, Math.round((width * img.naturalHeight) / img.naturalWidth));

    if (canvas.width !== width) {
      canvas.width = width;
    }
    if (canvas.height !== height) {
      canvas.height = height;
    }

    setDisplaySize((prev) => {
      if (prev.width === width && prev.height === height) {
        return prev;
      }
      return { width, height };
    });
  }, [zoom]);

  const scheduleSyncCanvasSize = useCallback(() => {
    if (resizeFrameRef.current !== null) {
      cancelAnimationFrame(resizeFrameRef.current);
    }
    resizeFrameRef.current = requestAnimationFrame(() => {
      resizeFrameRef.current = null;
      syncCanvasSize();
    });
  }, [syncCanvasSize]);

  useEffect(() => {
    scheduleSyncCanvasSize();
    return () => {
      if (resizeFrameRef.current !== null) {
        cancelAnimationFrame(resizeFrameRef.current);
        resizeFrameRef.current = null;
      }
    };
  }, [scheduleSyncCanvasSize]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const resizeObserver = new ResizeObserver(() => {
      scheduleSyncCanvasSize();
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      if (resizeFrameRef.current !== null) {
        cancelAnimationFrame(resizeFrameRef.current);
        resizeFrameRef.current = null;
      }
    };
  }, [scheduleSyncCanvasSize]);

  useEffect(() => {
    if (!isDrawing) {
      return;
    }

    const previousCursor = document.body.style.cursor;
    document.body.style.cursor = "none";

    return () => {
      document.body.style.cursor = previousCursor;
    };
  }, [isDrawing]);

  useEffect(() => {
    onDrawingChange?.(isDrawing);
  }, [isDrawing, onDrawingChange]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) {
      return;
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const drawSelectionOutline = (
      x: number,
      y: number,
      w: number,
      h: number,
      isFinal: boolean,
    ) => {
      const drawRoundedRectPath = (
        rx: number,
        ry: number,
        rw: number,
        rh: number,
        radius: number,
      ) => {
        const r = Math.max(0, Math.min(radius, rw / 2, rh / 2));
        ctx.beginPath();
        ctx.moveTo(rx + r, ry);
        ctx.lineTo(rx + rw - r, ry);
        ctx.arcTo(rx + rw, ry, rx + rw, ry + r, r);
        ctx.lineTo(rx + rw, ry + rh - r);
        ctx.arcTo(rx + rw, ry + rh, rx + rw - r, ry + rh, r);
        ctx.lineTo(rx + r, ry + rh);
        ctx.arcTo(rx, ry + rh, rx, ry + rh - r, r);
        ctx.lineTo(rx, ry + r);
        ctx.arcTo(rx, ry, rx + r, ry, r);
        ctx.closePath();
      };

      ctx.save();
      ctx.strokeStyle = isFinal
        ? "rgba(20, 20, 20, 0.95)"
        : "rgba(20, 20, 20, 0.85)";
      ctx.lineWidth = 2;
      if (!isFinal) {
        ctx.setLineDash([7, 4]);
      }

      const drawX = x + 1;
      const drawY = y + 1;
      const drawW = Math.max(w - 2, 1);
      const drawH = Math.max(h - 2, 1);
      const radius = Math.min(10, drawW / 6, drawH / 6);

      drawRoundedRectPath(drawX, drawY, drawW, drawH, radius);
      ctx.stroke();
      ctx.restore();
    };

    if (isDrawing && startPos && currentPos) {
      const x = Math.min(startPos.x, currentPos.x);
      const y = Math.min(startPos.y, currentPos.y);
      const w = Math.abs(currentPos.x - startPos.x);
      const h = Math.abs(currentPos.y - startPos.y);
      drawSelectionOutline(x, y, w, h, false);
      return;
    }

    if (finalRectNorm && !clearSelection) {
      const x = finalRectNorm.x0 * canvas.width;
      const y = finalRectNorm.y0 * canvas.height;
      const w = (finalRectNorm.x1 - finalRectNorm.x0) * canvas.width;
      const h = (finalRectNorm.y1 - finalRectNorm.y0) * canvas.height;
      drawSelectionOutline(x, y, w, h, true);
    }
  }, [isDrawing, startPos, currentPos, finalRectNorm, clearSelection]);

  useEffect(() => {
    draw();
  }, [draw, displaySize]);

  const getCanvasPoint = useCallback((clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return null;
    }

    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) {
      return null;
    }

    const x = ((clientX - rect.left) * canvas.width) / rect.width;
    const y = ((clientY - rect.top) * canvas.height) / rect.height;

    return {
      x: Math.max(0, Math.min(x, canvas.width)),
      y: Math.max(0, Math.min(y, canvas.height)),
    };
  }, []);

  useEffect(() => {
    if (!onSelectionPreview) {
      return;
    }

    const canvas = canvasRef.current;
    if (!canvas) {
      onSelectionPreview(null);
      return;
    }

    if (isDrawing && startPos && currentPos) {
      const x = Math.min(startPos.x, currentPos.x);
      const y = Math.min(startPos.y, currentPos.y);
      const w = Math.abs(currentPos.x - startPos.x);
      const h = Math.abs(currentPos.y - startPos.y);
      const rect = canvas.getBoundingClientRect();
      const scaleX = rect.width / canvas.width;
      const scaleY = rect.height / canvas.height;

      onSelectionPreview(
        new DOMRect(
          rect.left + x * scaleX,
          rect.top + y * scaleY,
          Math.max(w * scaleX, 1),
          Math.max(h * scaleY, 1),
        ),
      );
      return;
    }

    onSelectionPreview(null);
  }, [isDrawing, startPos, currentPos, onSelectionPreview]);

  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (e.button !== 0) {
      return;
    }

    const point = getCanvasPoint(e.clientX, e.clientY);
    if (!point) {
      return;
    }

    setIsDrawing(true);
    setStartPos(point);
    setCurrentPos(point);
    setFinalRectNorm(null);
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isDrawing) {
      return;
    }

    const point = getCanvasPoint(e.clientX, e.clientY);
    if (!point) {
      return;
    }

    setCurrentPos(point);
  };

  const handleMouseUp = () => {
    if (!isDrawing || !startPos || !currentPos) {
      return;
    }

    setIsDrawing(false);

    const x = Math.min(startPos.x, currentPos.x);
    const y = Math.min(startPos.y, currentPos.y);
    const w = Math.abs(currentPos.x - startPos.x);
    const h = Math.abs(currentPos.y - startPos.y);

    if (w < 5 || h < 5) {
      setStartPos(null);
      setCurrentPos(null);
      return;
    }

    const canvas = canvasRef.current;
    const img = imageRef.current;
    if (!canvas || !img) {
      return;
    }

    setFinalRectNorm({
      x0: x / canvas.width,
      y0: y / canvas.height,
      x1: (x + w) / canvas.width,
      y1: (y + h) / canvas.height,
    });

    setStartPos(null);
    setCurrentPos(null);

    const cropCanvas = document.createElement("canvas");
    cropCanvas.width = Math.max(Math.round(w), 1);
    cropCanvas.height = Math.max(Math.round(h), 1);
    const cropCtx = cropCanvas.getContext("2d");

    if (cropCtx) {
      const sourceScaleX = img.naturalWidth / canvas.width;
      const sourceScaleY = img.naturalHeight / canvas.height;
      cropCtx.drawImage(
        img,
        x * sourceScaleX,
        y * sourceScaleY,
        w * sourceScaleX,
        h * sourceScaleY,
        0,
        0,
        cropCanvas.width,
        cropCanvas.height,
      );
    }
    const crop_base64 = cropCanvas.toDataURL("image/png");

    const regionInfo: RegionInfo = {
      type: "rect",
      points: [
        { x: x / canvas.width, y: y / canvas.height },
        { x: (x + w) / canvas.width, y: (y + h) / canvas.height },
      ],
      crop_base64,
    };

    const rect = canvas.getBoundingClientRect();
    const scaleX = rect.width / canvas.width;
    const scaleY = rect.height / canvas.height;
    const anchorRect = new DOMRect(
      rect.left + x * scaleX,
      rect.top + y * scaleY,
      w * scaleX,
      h * scaleY,
    );

    onRegionDrawn(regionInfo, anchorRect);
  };

  const handleImageLoad = () => {
    scheduleSyncCanvasSize();
  };

  return (
    <div
      ref={containerRef}
      className="relative flex h-full w-full min-w-0 items-center justify-center overflow-auto bg-gradient-to-b from-background to-muted/30 p-4 select-none"
      style={{ scrollbarGutter: "stable both-edges" }}
    >
      <div
        data-walkthrough="plot-annotator"
        className="inline-block rounded-xl border border-border/80 bg-background p-2 shadow-sm"
      >
        <div
          className="relative"
          style={{
            width: `${displaySize.width}px`,
            height: `${displaySize.height}px`,
          }}
        >
          <img
            ref={imageRef}
            src={imageUrl}
            alt="Plot"
            onLoad={handleImageLoad}
            className="block h-full w-full rounded-md pointer-events-none"
            crossOrigin="anonymous"
            draggable={false}
          />

          <canvas
            ref={canvasRef}
            className={`absolute left-0 top-0 h-full w-full touch-none ${
              isDrawing ? "cursor-none" : "cursor-crosshair"
            }`}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          />

          {annotations.map((ann, index) => {
            if (!ann.region || ann.region.points.length < 2) {
              return null;
            }

            const isFocused = focusedAnnotationId === ann.id;

            const p0 = ann.region.points[0];
            const p1 = ann.region.points[ann.region.points.length - 1];
            const cx = ((p0.x + p1.x) / 2) * 100;
            const cy = ((p0.y + p1.y) / 2) * 100;

            return (
              <div
                key={ann.id}
                className={`absolute h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border text-[10px] font-semibold flex items-center justify-center pointer-events-none shadow-sm transition ${
                  ann.status === "pending"
                    ? "bg-amber-200 text-amber-950 border-amber-400"
                    : "bg-foreground text-background border-foreground/30"
                } ${isFocused ? "ring-2 ring-foreground/75 ring-offset-1 ring-offset-background" : ""}`}
                style={{ left: `${cx}%`, top: `${cy}%` }}
                title={`Annotation ${index + 1} (${ann.status})`}
              >
                {index + 1}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
