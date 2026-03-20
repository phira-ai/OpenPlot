"""Compile annotations into a structured feedback prompt for LLM agents."""

from __future__ import annotations

from .domain.regions import region_bounds_from_points, region_zone_hint_from_points
from .models import Annotation, AnnotationStatus, PlotSession, RegionInfo


def _region_bounds(region: RegionInfo) -> tuple[float, float, float, float] | None:
    return region_bounds_from_points(region.points)


def _region_zone_hint(region: RegionInfo) -> str:
    return region_zone_hint_from_points(region.points)


def _describe_element(ann: Annotation) -> str:
    """Human-readable description of the annotated element or region."""
    if ann.element_info is not None:
        ei = ann.element_info
        attrs_str = ", ".join(f"{k}: {v}" for k, v in ei.attributes.items())
        text_part = f' "{ei.text_content}"' if ei.text_content else ""
        attrs_part = f" ({attrs_str})" if attrs_str else ""
        return f"<{ei.tag}>{text_part}{attrs_part}"

    if ann.region is not None:
        ri = ann.region
        bounds = _region_bounds(ri)
        if bounds is not None:
            x0, y0, x1, y1 = bounds
            coords = f"({x0:.2f}, {y0:.2f}) -> ({x1:.2f}, {y1:.2f})"
        else:
            coords = "unknown region"
        has_crop = " [cropped image attached]" if ri.crop_base64 else ""
        return f"{ri.type.value.capitalize()} region at {coords}{has_crop}"

    return "Unknown element"


def compile_feedback(session: PlotSession, *, include_addressed: bool = False) -> str:
    """Build a Markdown prompt containing all pending annotations.

    Parameters
    ----------
    session:
        The current plot session with annotations.
    include_addressed:
        If True, also include annotations already marked as addressed.

    Returns
    -------
    str
        A Markdown-formatted feedback prompt ready to send to an LLM.
    """
    annotations = [
        a
        for a in session.annotations
        if include_addressed or a.status == AnnotationStatus.pending
    ]

    if not annotations:
        return "No pending feedback annotations."

    lines: list[str] = []
    lines.append(
        f"## Plot Feedback ({len(annotations)} annotation{'s' if len(annotations) != 1 else ''})\n"
    )

    has_region_annotations = any(a.region is not None for a in annotations)
    has_element_annotations = any(a.element_info is not None for a in annotations)

    lines.append("### Scope Rules (must follow)\n")

    if has_region_annotations:
        lines.append(
            "- For **raster-region** annotations, scope is **LOCAL_REGION**. "
            "Treat the attached crop image as authoritative grounding."
        )
        lines.append(
            '- Ambiguous references ("this", "these", "each line", '
            '"the lines") apply only to elements visible inside the selected '
            "region/crop."
        )

    if has_element_annotations:
        lines.append(
            "- For **svg-element** annotations, scope is **LOCAL_ELEMENT** by default."
        )

    lines.append(
        "- Do not modify outside local scope unless feedback explicitly asks for "
        'global edits (for example: "all charts", "entire figure", '
        '"across all subplots").'
    )
    lines.append(
        "- Prefer the minimal set of localized changes that satisfies each annotation.\n"
    )

    # Include the script source if available.
    if session.source_script:
        lines.append("### Current Script\n")
        lines.append("```python")
        lines.append(session.source_script.rstrip())
        lines.append("```\n")

    lines.append("### Annotations\n")
    for i, ann in enumerate(annotations, 1):
        desc = _describe_element(ann)
        lines.append(f"{i}. **Element**: {desc}")
        if ann.region is not None:
            lines.append("   **Mode**: raster-region")
            lines.append("   **Scope**: LOCAL_REGION")
            bounds = _region_bounds(ann.region)
            if bounds is not None:
                x0, y0, x1, y1 = bounds
                lines.append(
                    "   **Region (normalized)**: "
                    f"({x0:.3f}, {y0:.3f}) -> ({x1:.3f}, {y1:.3f})"
                )
            lines.append(f"   **Zone hint**: {_region_zone_hint(ann.region)}")
            lines.append(
                "   **Disambiguation**: Ambiguous references resolve only to "
                "elements visible in this region crop."
            )
        elif ann.element_info is not None:
            lines.append("   **Mode**: svg-element")
            lines.append("   **Scope**: LOCAL_ELEMENT")
            lines.append(
                "   **Disambiguation**: Ambiguous references resolve to the "
                "selected SVG element."
            )
        lines.append(f'   **Feedback**: "{ann.feedback}"\n')

    lines.append("---")
    lines.append(
        "Please update the script to address all the feedback above. "
        "Return the complete updated script. Apply scope rules first when "
        "feedback wording is ambiguous."
    )

    return "\n".join(lines)
