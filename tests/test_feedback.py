from openplot.feedback import compile_feedback
from openplot.models import Annotation, ElementInfo, PlotSession, RegionInfo, RegionType


def test_compile_feedback_adds_local_scope_rules_for_raster_regions() -> None:
    session = PlotSession(source_script="print('demo')")
    session.annotations.append(
        Annotation(
            feedback="add an EMA to each of the lines",
            region=RegionInfo(
                type=RegionType.rect,
                points=[{"x": 0.074, "y": 0.130}, {"x": 0.922, "y": 0.458}],
                crop_base64="data:image/png;base64,AAAA",
            ),
        )
    )

    prompt = compile_feedback(session)

    assert "### Scope Rules (must follow)" in prompt
    assert "Treat the attached crop image as authoritative grounding." in prompt
    assert "**Scope**: LOCAL_REGION" in prompt
    assert "**Zone hint**: upper figure zone" in prompt
    assert (
        "Ambiguous references resolve only to elements visible in this region crop."
        in prompt
    )


def test_compile_feedback_keeps_svg_annotations_local_by_default() -> None:
    session = PlotSession(source_script="print('demo')")
    session.annotations.append(
        Annotation(
            feedback="make this label bolder",
            element_info=ElementInfo(
                tag="text",
                text_content="Active Users",
                attributes={"font-size": "12"},
                xpath="/svg/g/text[1]",
            ),
        )
    )

    prompt = compile_feedback(session)

    assert "**Scope**: LOCAL_ELEMENT" in prompt
    assert "Ambiguous references resolve to the selected SVG element." in prompt
