from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from applypilot.scoring import pdf as pdf_module
from applypilot.scoring.evidence_aware_pdf_planner import (
    EvidenceAwarePdfPlanner,
    PdfPlanningContext,
    PdfPlanningResult,
)
from applypilot.scoring.pdf_render_model import ResumeEntry, ResumeRenderModel
from applypilot.scoring.skill_repair_planner import SkillRepairPlanner


def test_evidence_aware_pdf_planner_plan_returns_result() -> None:
    calls: list[str] = []

    def _preserve(**kwargs):
        calls.append("preserve")
        planning = dict(kwargs["planning"])
        planning["phase"] = "preserved"
        return kwargs["model"], kwargs["html"] + "p", kwargs["prepared"], planning

    def _replace(**kwargs):
        calls.append("replace")
        planning = dict(kwargs["planning"])
        planning["phase"] = "replaced"
        return kwargs["model"], kwargs["html"] + "r", kwargs["prepared"], planning

    planner = EvidenceAwarePdfPlanner(
        apply_evidence_preservation=_preserve,
        skill_repair_planner=SkillRepairPlanner(apply_skill_repair=_replace),
    )
    model = ResumeRenderModel(name="Alex")
    result = planner.plan(
        model=model,
        html="<html>",
        prepared=SimpleNamespace(),
        planning={"a": 1},
        context=PdfPlanningContext(template_name="professional_compact", job_description="jd", skills_selection={"x": 1}),
    )

    assert isinstance(result, PdfPlanningResult)
    assert result.model is model
    assert result.html == "<html>pr"
    assert result.planning["phase"] == "replaced"
    assert calls == ["preserve", "replace"]


def test_render_model_to_pdf_with_planning_uses_orchestrator(monkeypatch, tmp_path: Path) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        experience=[ResumeEntry(title="Role 1", subtitle="Company 1 | 2022", bullets=["Bullet 1"])],
    )

    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html>base</html>", object()))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "template_used": "professional_compact",
            "allowed_physical_pages": 2,
            "planning_attempts": [],
            "planning_operations": [],
            "render_modes_final": {"skills_mode": "selected"},
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
        },
    )

    class _StubPlanner:
        called = False

        def __init__(self, **_kwargs):
            pass

        def plan(self, **kwargs):
            _StubPlanner.called = True
            planning = dict(kwargs["planning"])
            planning["orchestrator_used"] = True
            return PdfPlanningResult(
                model=kwargs["model"],
                html="<html>planned</html>",
                prepared=kwargs["prepared"],
                planning=planning,
            )

    monkeypatch.setattr(pdf_module, "EvidenceAwarePdfPlanner", _StubPlanner)

    html_path, planning = pdf_module.render_model_to_pdf_with_planning(
        model,
        output_path=tmp_path / "planned.html",
        html_only=True,
    )

    assert _StubPlanner.called is True
    assert html_path.read_text(encoding="utf-8") == "<html>planned</html>"
    assert planning["orchestrator_used"] is True


def test_evidence_aware_pdf_planner_delegates_repair_to_skill_repair_planner() -> None:
    calls: list[str] = []

    def _preserve(**kwargs):
        calls.append("preserve")
        planning = dict(kwargs["planning"])
        return kwargs["model"], kwargs["html"], kwargs["prepared"], planning

    class _StubSkillRepairPlanner:
        def repair(self, **kwargs):
            calls.append("repair")
            planning = dict(kwargs["planning"])
            planning["repaired"] = True
            return SimpleNamespace(
                model=kwargs["model"],
                html=kwargs["html"] + "r",
                prepared=kwargs["prepared"],
                planning=planning,
            )

    planner = EvidenceAwarePdfPlanner(
        apply_evidence_preservation=_preserve,
        skill_repair_planner=_StubSkillRepairPlanner(),
    )

    result = planner.plan(
        model=ResumeRenderModel(name="Alex"),
        html="<html>",
        prepared=SimpleNamespace(),
        planning={"a": 1},
        context=PdfPlanningContext(template_name="professional_compact"),
    )

    assert calls == ["preserve", "repair"]
    assert result.html == "<html>r"
    assert result.planning["repaired"] is True
