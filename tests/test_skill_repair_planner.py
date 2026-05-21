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


def test_apply_replacements_replaces_unsupported_claim() -> None:
    planner = SkillRepairPlanner(
        apply_skill_repair=lambda **kwargs: (kwargs["model"], kwargs["html"], kwargs["prepared"], kwargs["planning"]),
    )
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="PostgreSQL, Kafka")],
    )
    result = planner.apply_replacements(
        model=model,
        html="<html/>",
        prepared=object(),
        planning={"claim_coverage": [{"claim": "PostgreSQL", "coverage_status": "unsupported"}]},
        context=SkillRepairContext(template_name="professional_compact"),
        score_map={"postgresql": 90.0, "kafka": 88.0},
        build_claim_coverage_for_claims_fn=lambda **_kwargs: [
            SimpleNamespace(claim="Kafka", coverage_status="supported")
        ],
        extract_all_skill_claims_fn=lambda _model: ["PostgreSQL", "Kafka"],
        clone_model_with_swapped_skills_fn=lambda _model, _from, _to: ResumeRenderModel(
            skills=[SkillSection(category="Core", value="Kafka, PostgreSQL")]
        ),
        measured_fit_fn=lambda _planning: (2, True),
        build_html_and_prepared_fn=lambda *_args, **_kwargs: ("<html-swapped/>", object()),
        build_planning_with_evidence_fn=lambda **_kwargs: {
            "claim_coverage": [{"claim": "Kafka", "coverage_status": "supported"}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
            "measured_pages_final": 2,
            "allowed_physical_pages": 2,
        },
    )

    assert any(item.get("claim") == "PostgreSQL" and item.get("final_action") == "replaced" for item in [d.to_report_dict() for d in result.dispositions])
    assert result.adjustments and result.adjustments[0]["step"] == "evidence_aware_skill_replacement"


def test_remove_unsupported_claims_until_stable_removes_to_fixed_point() -> None:
    planner = SkillRepairPlanner(
        apply_skill_repair=lambda **kwargs: (kwargs["model"], kwargs["html"], kwargs["prepared"], kwargs["planning"]),
    )
    d1 = planner.build_disposition(
        claim="PostgreSQL",
        coverage_status="unsupported",
        final_action="replaced",
        reason="replaced_by_supported_retained_skill",
        replacement="CI/CD",
    )
    d2 = planner.build_disposition(
        claim="AWS S3",
        coverage_status="unsupported",
        final_action="kept",
        reason="no_supported_retained_replacement_available",
    )
    planning_seq = [
        {
            "unsupported_visible_claims": ["AWS S3"],
            "claim_coverage": [{"claim": "AWS S3", "coverage_status": "unsupported", "primary_supporting_evidence_count": 0}],
            "measured_pages_final": 2,
            "allowed_physical_pages": 2,
        },
        {
            "unsupported_visible_claims": ["PostgreSQL"],
            "claim_coverage": [{"claim": "PostgreSQL", "coverage_status": "unsupported", "primary_supporting_evidence_count": 0}],
            "measured_pages_final": 2,
            "allowed_physical_pages": 2,
        },
        {
            "unsupported_visible_claims": [],
            "claim_coverage": [],
            "measured_pages_final": 2,
            "allowed_physical_pages": 2,
        },
    ]
    idx = {"n": 0}

    def _build_planning(**_kwargs):
        i = idx["n"]
        idx["n"] += 1
        return planning_seq[min(i, len(planning_seq) - 1)]

    result = planner.remove_unsupported_claims_until_stable(
        model=ResumeRenderModel(skills=[SkillSection(category="Core", value="A")]),
        html="<html/>",
        prepared=object(),
        planning=planning_seq[0],
        context=SkillRepairContext(template_name="professional_compact"),
        min_visible_skill_count=0,
        dispositions=[d1, d2],
        candidate_search_lookup={},
        used_candidates=set(),
        replaced_claim_keys=set(),
        planning_step_ops=[],
        unsupported_skill_removals=[],
        find_usable_supported_replacements_for_claim_fn=lambda **_kwargs: ([], []),
        clone_model_without_skill_fn=lambda model, _claim: model,
        measured_fit_fn=lambda _planning: (2, True),
        build_html_and_prepared_fn=lambda *_args, **_kwargs: ("<html/>", object()),
        build_planning_with_evidence_fn=_build_planning,
    )

    claims = [item["claim"] for item in result.unsupported_skill_removals if item.get("kept")]
    assert "AWS S3" in claims
    assert "PostgreSQL" in claims
    disp_lookup = {d.claim: d for d in result.dispositions}
    post_payload = disp_lookup["PostgreSQL"].to_report_dict()
    assert post_payload["final_action"] == "removed"
    assert [a["action"] for a in post_payload["action_history"]] == ["replaced", "removed"]
