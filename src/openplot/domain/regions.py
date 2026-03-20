"""Shared helpers for raster-region normalization and descriptions."""

from __future__ import annotations

from typing import Any


def clamp_01(value: float) -> float:
    return max(0.0, min(1.0, value))


def region_bounds_from_points(
    points: Any,
) -> tuple[float, float, float, float] | None:
    """Return normalized region bounds as (x0, y0, x1, y1)."""
    if not isinstance(points, list) or not points:
        return None

    xs: list[float] = []
    ys: list[float] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        raw_x = point.get("x")
        raw_y = point.get("y")
        if not isinstance(raw_x, (int, float)) or not isinstance(raw_y, (int, float)):
            continue
        xs.append(clamp_01(float(raw_x)))
        ys.append(clamp_01(float(raw_y)))

    if not xs or not ys:
        return None

    return min(xs), min(ys), max(xs), max(ys)


def region_zone_hint_from_bounds(bounds: tuple[float, float, float, float]) -> str:
    """A simple vertical zone hint to reduce subplot-scope ambiguity."""
    _x0, y0, _x1, y1 = bounds
    y_mid = (y0 + y1) / 2.0
    if y_mid < 1 / 3:
        return "upper figure zone"
    if y_mid < 2 / 3:
        return "middle figure zone"
    return "lower figure zone"


def region_zone_hint_from_points(points: Any) -> str:
    bounds = region_bounds_from_points(points)
    if bounds is None:
        return "unknown figure zone"
    return region_zone_hint_from_bounds(bounds)
