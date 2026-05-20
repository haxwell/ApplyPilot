from __future__ import annotations

from types import SimpleNamespace

from applypilot.scoring.pdf_render_model import ResumeRenderModel
from applypilot.scoring.render_planning_service import (
    RenderPlanningContext,
    RenderPlanningService,
    RenderPlanningState,
)


def test_render_planning_service_build_state_uses_injected_builders() -> None:
    calls: list[str] = []

    def _build_html(model: ResumeRenderModel, *, template_name: str):
        calls.append(f"html:{template_name}:{model.name}")
        return "<html/>", SimpleNamespace(kind="prepared")

    def _build_planning(*, model: ResumeRenderModel, prepared: object, template_name: str, job_description: str):
        calls.append(f"planning:{template_name}:{job_description}:{model.name}:{getattr(prepared, 'kind', '')}")
        return {"measured_pages_final": 2, "allowed_physical_pages": 3}

    service = RenderPlanningService(
        build_html_and_prepared=_build_html,
        build_planning_with_evidence=_build_planning,
        measured_fit=lambda _planning: (2, True),
    )
    state = service.build_state(
        model=ResumeRenderModel(name="Alex"),
        context=RenderPlanningContext(template_name="professional_compact", job_description="JD"),
    )

    assert isinstance(state, RenderPlanningState)
    assert state.html == "<html/>"
    assert state.measured_pages == 2
    assert state.fits_page_target is True
    assert calls == [
        "html:professional_compact:Alex",
        "planning:professional_compact:JD:Alex:prepared",
    ]


def test_render_planning_state_fit_properties_follow_planning_values() -> None:
    state = RenderPlanningState(
        model=ResumeRenderModel(name="Alex"),
        html="<html/>",
        prepared=object(),
        planning={"measured_pages_final": 4, "allowed_physical_pages": 3},
    )
    assert state.measured_pages == 4
    assert state.fits_page_target is False

    state_unknown = RenderPlanningState(
        model=ResumeRenderModel(name="Alex"),
        html="<html/>",
        prepared=object(),
        planning={"measured_pages_final": None, "allowed_physical_pages": 3},
    )
    assert state_unknown.measured_pages is None
    assert state_unknown.fits_page_target is None


def test_visible_skill_names_dedupes_preserving_order() -> None:
    service = RenderPlanningService(
        build_html_and_prepared=lambda *_args, **_kwargs: ("<html/>", object()),
        build_planning_with_evidence=lambda **_kwargs: {},
        measured_fit=lambda _planning: (None, True),
        extract_visible_skill_claims_fn=lambda _model, _prepared: [
            "Kafka",
            "kafka",
            "  Spring Boot  ",
            "Kafka  ",
            "Spring Boot",
            "",
        ],
    )
    state = RenderPlanningState(
        model=ResumeRenderModel(name="Alex"),
        html="<html/>",
        prepared=object(),
        planning={},
    )

    assert service.visible_skill_names(state) == ["Kafka", "Spring Boot"]
    assert service.visible_skill_count(state) == 2
