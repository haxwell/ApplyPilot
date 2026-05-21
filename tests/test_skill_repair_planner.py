from __future__ import annotations

from types import SimpleNamespace

from applypilot.scoring.pdf_render_model import SkillSection
from applypilot.scoring.pdf_render_model import ResumeRenderModel
from applypilot.scoring.render_planning_service import RenderPlanningService
from applypilot.scoring.skill_repair_planner import (
    SkillRepairContext,
    SkillRepairPlanner,
    SkillRepairResult,
)


def test_skill_repair_planner_calls_injected_repair_fn() -> None:
    calls: list[dict] = []

    def _repair(**kwargs):
        calls.append(kwargs)
        planning = dict(kwargs["planning"])
        planning["phase"] = "repaired"
        return kwargs["model"], kwargs["html"] + "r", kwargs["prepared"], planning

    planner = SkillRepairPlanner(apply_skill_repair=_repair)
    model = ResumeRenderModel(name="Alex")
    result = planner.repair(
        model=model,
        html="<html>",
        prepared=SimpleNamespace(),
        planning={"a": 1},
        context=SkillRepairContext(
            template_name="professional_compact",
            job_description="job desc",
            skills_selection={"retained_skills": []},
        ),
    )

    assert isinstance(result, SkillRepairResult)
    assert result.model is model
    assert result.html == "<html>r"
    assert result.planning["phase"] == "repaired"
    assert len(calls) == 1
    call = calls[0]
    assert call["template_name"] == "professional_compact"
    assert call["job_description"] == "job desc"
    assert call["skills_selection"] == {"retained_skills": []}


def test_skill_repair_planner_passes_render_planning_service() -> None:
    calls: list[dict] = []

    def _repair(**kwargs):
        calls.append(kwargs)
        return kwargs["model"], kwargs["html"], kwargs["prepared"], kwargs["planning"]

    service = RenderPlanningService(
        build_html_and_prepared=lambda *_args, **_kwargs: ("<html/>", object()),
        build_planning_with_evidence=lambda **_kwargs: {},
        measured_fit=lambda _planning: (None, True),
    )
    planner = SkillRepairPlanner(apply_skill_repair=_repair, render_planning_service=service)
    planner.repair(
        model=ResumeRenderModel(name="Alex"),
        html="<html>",
        prepared=SimpleNamespace(),
        planning={},
        context=SkillRepairContext(template_name="professional_compact"),
    )
    assert calls[0]["render_planning_service"] is service
    assert calls[0]["skill_repair_helpers"] is planner


def test_alias_conflict_detects_visible_alias_and_ignores_replaced_claim() -> None:
    planner = SkillRepairPlanner(apply_skill_repair=lambda **kwargs: (kwargs["model"], kwargs["html"], kwargs["prepared"], kwargs["planning"]))

    assert (
        planner.alias_conflict(
            candidate="Test-Driven Development",
            visible_claims=["TDD", "Kafka"],
            claim_being_replaced="Jenkins CI",
        )
        is True
    )
    assert (
        planner.alias_conflict(
            candidate="Jenkins CI",
            visible_claims=["Jenkins CI", "Kafka"],
            claim_being_replaced="Jenkins CI",
        )
        is False
    )
    assert (
        planner.alias_conflict(
            candidate="PostgreSQL",
            visible_claims=["Kafka", "Docker"],
            claim_being_replaced="Jenkins CI",
        )
        is False
    )
    variants = planner.claim_variants_set("Jenkins CI")
    assert "jenkins ci" in variants
    assert "jenkins" in variants


def test_visible_skill_count_and_names_dedupes_and_falls_back_to_claim_coverage() -> None:
    planner = SkillRepairPlanner(
        apply_skill_repair=lambda **kwargs: (kwargs["model"], kwargs["html"], kwargs["prepared"], kwargs["planning"]),
        extract_visible_skill_claims_fn=lambda _model, _prepared: ["Kafka", "kafka", " Spring Boot "],
    )
    count, names = planner.visible_skill_count_and_names(
        model=ResumeRenderModel(name="Alex", skills=[SkillSection(category="Core", value="Kafka, Spring Boot")]),
        prepared=object(),
        planning={},
    )
    assert count == 2
    assert names == ["Kafka", "Spring Boot"]

    def _raise(_model, _prepared):
        raise RuntimeError("boom")

    planner_fallback = SkillRepairPlanner(
        apply_skill_repair=lambda **kwargs: (kwargs["model"], kwargs["html"], kwargs["prepared"], kwargs["planning"]),
        extract_visible_skill_claims_fn=_raise,
    )
    fallback_count, fallback_names = planner_fallback.visible_skill_count_and_names(
        model=ResumeRenderModel(name="Alex"),
        prepared=object(),
        planning={"claim_coverage": [{"claim": "Docker"}, {"claim": "Kubernetes"}, {"x": 1}]},
    )
    assert fallback_count == 2
    assert fallback_names == ["Docker", "Kubernetes"]


def test_build_disposition_metadata_and_removed_serialization() -> None:
    planner = SkillRepairPlanner(apply_skill_repair=lambda **kwargs: (kwargs["model"], kwargs["html"], kwargs["prepared"], kwargs["planning"]))
    replaced = planner.build_disposition(
        claim="PostgreSQL",
        coverage_status="unsupported",
        final_action="replaced",
        reason="replaced_by_supported_retained_skill",
        replacement="CI/CD",
    )
    assert replaced.replacement == "CI/CD"
    replaced.mark_removed("unsupported_no_replacement_no_source_evidence")
    payload = replaced.to_report_dict()
    assert payload["final_action"] == "removed"
    assert "replacement" not in payload

    kept = planner.build_disposition(
        claim="Docker",
        coverage_status="weak_summary_only",
        final_action="kept",
        reason="no_supported_retained_replacement_available",
    )
    kept_payload = kept.to_report_dict()
    assert "user_action" in kept_payload
