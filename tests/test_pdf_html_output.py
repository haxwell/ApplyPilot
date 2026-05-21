from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from applypilot.resume.evidence import ClaimCoverage, extract_all_skill_claims
from applypilot.scoring import pdf as pdf_module
from applypilot.scoring.pdf import (
    _apply_evidence_preservation,
    _apply_evidence_aware_skill_replacements,
    build_html_for_resume,
    convert_to_pdf,
    render_model_to_pdf,
    render_model_to_pdf_with_planning,
)
from applypilot.scoring.pdf_render_model import (
    ResumeEntry,
    ResumeRenderModel,
    SkillSection,
    build_render_model_from_tailored_json,
)
from applypilot.scoring.render_planning_service import RenderPlanningContext, RenderPlanningState
from applypilot.scoring.skill_repair_planner import SkillRepairPlanner
from applypilot.scoring.pdf_templates import compact as compact_template


def test_convert_to_pdf_html_only_contains_expected_sections(tmp_path: Path) -> None:
    source = tmp_path / "resume.txt"
    source.write_text(
        "\n".join(
            [
                "Alex Example",
                "Senior Engineer",
                "alex@example.com | 555-111-2222",
                "",
                "SUMMARY",
                "Built and shipped reliable systems.",
                "",
                "TECHNICAL SKILLS",
                "Languages: Python, Java",
                "Backend: APIs, Microservices",
                "",
                "EXPERIENCE",
                "Senior Engineer",
                "Example Corp | 2022-01 - Present",
                "- Built APIs",
                "",
                "EDUCATION",
                "State University | BS Computer Science | 2018",
            ]
        ),
        encoding="utf-8",
    )

    html_path = convert_to_pdf(source, html_only=True, template_name="classic")
    html = html_path.read_text(encoding="utf-8")

    assert "Summary" in html
    assert "Technical Skills" in html
    assert "Experience" in html
    assert "Education" in html


def test_convert_to_pdf_html_only_uses_production_default_template_when_not_specified(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "resume_default_template.txt"
    source.write_text(
        "\n".join(
            [
                "Alex Example",
                "Senior Engineer",
                "alex@example.com | 555-111-2222",
                "",
                "SUMMARY",
                "Built and shipped reliable systems.",
                "",
                "TECHNICAL SKILLS",
                "Languages: Python, Java",
                "",
                "EXPERIENCE",
                "Role 1",
                "Company 1 | 2022-01 - Present",
                "- Bullet 1",
                "",
                "Role 2",
                "Company 2 | 2020-01 - 2021-12",
                "- Bullet 2",
                "",
                "Role 3",
                "Company 3 | 2018-01 - 2019-12",
                "- Bullet 3",
                "",
                "EDUCATION",
                "State University | BS Computer Science | 2018",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("applypilot.scoring.pdf.measure_html_page_count", lambda _html: 99)
    html_path = convert_to_pdf(source, html_only=True)
    html = html_path.read_text(encoding="utf-8")

    # professional_compact is measurement-aware and may render earlier selected experience.
    assert "Earlier Experience (Selected)" in html


def test_convert_to_pdf_html_only_compact_contains_expected_sections(tmp_path: Path) -> None:
    source = tmp_path / "resume_compact.txt"
    source.write_text(
        "\n".join(
            [
                "Alex Example",
                "Senior Engineer",
                "alex@example.com | 555-111-2222",
                "",
                "SUMMARY",
                "Built and shipped reliable systems.",
                "",
                "TECHNICAL SKILLS",
                "Languages: Python, Java",
                "Backend: APIs, Microservices",
                "",
                "EXPERIENCE",
                "Senior Engineer",
                "Example Corp | 2022-01 - Present",
                "- Built APIs",
                "",
                "EDUCATION",
                "State University | BS Computer Science | 2018",
            ]
        ),
        encoding="utf-8",
    )

    compact_html_path = convert_to_pdf(source, html_only=True, template_name="compact")
    compact_html = compact_html_path.read_text(encoding="utf-8")

    assert "Summary" in compact_html
    assert "Technical Skills" in compact_html
    assert "Experience" in compact_html
    assert "Education" in compact_html


def test_render_model_html_outputs_certifications_section_when_present() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        summary="Built and shipped reliable systems.",
        certifications="AWS Certified Developer | Amazon | 2023",
    )

    html = build_html_for_resume(model, template_name="classic")

    assert "Certifications" in html
    assert "AWS Certified Developer | Amazon | 2023" in html


def test_compact_html_differs_from_classic_html(tmp_path: Path) -> None:
    source = tmp_path / "resume_compare.txt"
    source.write_text(
        "\n".join(
            [
                "Alex Example",
                "Senior Engineer",
                "alex@example.com | 555-111-2222",
                "",
                "SUMMARY",
                "Built and shipped reliable systems.",
                "",
                "TECHNICAL SKILLS",
                "Languages: Python, Java",
                "Backend: APIs, Microservices",
                "",
                "EXPERIENCE",
                "Senior Engineer",
                "Example Corp | 2022-01 - Present",
                "- Built APIs",
                "",
                "EDUCATION",
                "State University | BS Computer Science | 2018",
            ]
        ),
        encoding="utf-8",
    )

    default_html_path = convert_to_pdf(source, html_only=True, output_path=tmp_path / "default.html", template_name="classic")
    compact_html_path = convert_to_pdf(source, html_only=True, output_path=tmp_path / "compact.html", template_name="compact")

    default_html = default_html_path.read_text(encoding="utf-8")
    compact_html = compact_html_path.read_text(encoding="utf-8")

    assert default_html != compact_html


def test_render_model_to_pdf_html_only_contains_model_content(tmp_path: Path) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        summary="Built and shipped reliable systems.",
        contact="alex@example.com | 555-111-2222",
        skills=[SkillSection(category="Languages", value="Python, Java")],
        experience=[
            ResumeEntry(
                title="Senior Engineer",
                subtitle="Example Corp | 2022-01 - Present",
                bullets=["Built APIs"],
                compact_summary="Led backend reliability improvements.",
            )
        ],
        education="State University | BS Computer Science | 2018",
    )

    html_path = render_model_to_pdf(
        model,
        output_path=tmp_path / "model.html",
        template_name="classic",
        html_only=True,
    )
    html = html_path.read_text(encoding="utf-8")

    assert "Alex Example" in html
    assert "Built and shipped reliable systems." in html
    assert "Built APIs" in html
    assert "Led backend reliability improvements." not in html


def test_render_model_to_pdf_html_only_uses_production_default_template_when_not_specified(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        summary="Built and shipped reliable systems.",
        contact="alex@example.com | 555-111-2222",
        experience=[
            ResumeEntry(title="Role 1", subtitle="Company 1 | 2022", bullets=["Bullet 1"]),
            ResumeEntry(title="Role 2", subtitle="Company 2 | 2021", bullets=["Bullet 2"]),
            ResumeEntry(title="Role 3", subtitle="Company 3 | 2020", bullets=["Bullet 3"]),
        ],
    )

    monkeypatch.setattr("applypilot.scoring.pdf.measure_html_page_count", lambda _html: 99)
    html_path = render_model_to_pdf(model, output_path=tmp_path / "model_default.html", html_only=True)
    html = html_path.read_text(encoding="utf-8")

    assert "Earlier Experience (Selected)" in html


def test_render_model_to_pdf_html_only_from_tailored_json_model(tmp_path: Path) -> None:
    profile = {
        "personal": {
            "full_name": "Alex Example",
            "email": "alex@example.com",
            "phone": "555-111-2222",
            "city": "Denver",
            "province_state": "CO",
        }
    }
    tailored_json = {
        "title": "Senior Engineer",
        "summary": "Built and shipped reliable systems.",
        "skills": {"Languages": "Python, Java"},
        "experience": [
            {
                "header": "Senior Engineer",
                "subtitle": "Example Corp | 2022-01 - Present",
                "bullets": ["Built APIs"],
            }
        ],
        "projects": [],
        "education": "State University | BS Computer Science | 2018",
    }
    model = build_render_model_from_tailored_json(tailored_json, profile)

    html_path = render_model_to_pdf(
        model,
        output_path=tmp_path / "from_json_model.html",
        template_name="classic",
        html_only=True,
    )
    html = html_path.read_text(encoding="utf-8")

    assert "Alex Example" in html
    assert "Built and shipped reliable systems." in html
    assert "Built APIs" in html


def test_render_model_to_pdf_with_planning_returns_planning_report(monkeypatch, tmp_path: Path) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        summary="Built and shipped reliable systems.",
        contact="alex@example.com | 555-111-2222",
        experience=[
            ResumeEntry(title="Role 1", subtitle="Company 1 | 2022", bullets=["Bullet 1"]),
            ResumeEntry(title="Role 2", subtitle="Company 2 | 2021", bullets=["Bullet 2"]),
            ResumeEntry(title="Role 3", subtitle="Company 3 | 2020", bullets=["Bullet 3"]),
        ],
    )

    monkeypatch.setattr("applypilot.scoring.pdf.measure_html_page_count", lambda _html: 99)
    html_path, planning = render_model_to_pdf_with_planning(
        model,
        output_path=tmp_path / "model_with_planning.html",
        html_only=True,
    )
    html = html_path.read_text(encoding="utf-8")

    assert "Alex Example" in html
    assert planning["template_used"] == "professional_compact"
    assert planning["allowed_physical_pages"] == 3
    assert isinstance(planning.get("planning_attempts"), list)
    assert isinstance(planning.get("planning_operations"), list)
    assert isinstance(planning.get("render_modes_final"), dict)
    assert "projects_mode" in planning["render_modes_final"]
    if "detailed_bullet_cap_final" in planning:
        assert isinstance(planning["detailed_bullet_cap_final"], int)
    assert "selected_skills_max_lines_final" in planning
    assert "min_protected_detailed_roles" in planning
    assert "job_themes" in planning
    assert "claim_coverage" in planning
    assert "theme_evidence_matches" in planning
    assert "unsupported_visible_claims" in planning
    assert "weak_visible_claims" in planning
    assert "unsupported_visible_claims_final" in planning
    assert "weak_visible_claims_final" in planning
    assert "evidence_aware_skill_adjustments" in planning
    assert "unsupported_skill_removals" in planning
    assert "evidence_available_but_not_rendered" in planning
    assert "strong_unused_evidence" in planning


def test_render_model_to_pdf_with_planning_does_not_call_legacy_skill_repair_wrapper(
    monkeypatch, tmp_path: Path
) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        summary="Built and shipped reliable systems.",
        contact="alex@example.com | 555-111-2222",
        skills=[SkillSection(category="Core", value="Java, Spring Boot, SQL")],
        experience=[ResumeEntry(title="Role 1", subtitle="Company 1 | 2022", bullets=["Bullet 1"])],
    )

    def _fail_if_called(**_kwargs):
        raise AssertionError("legacy skill repair wrapper should not be used by production path")

    monkeypatch.setattr(pdf_module, "_apply_evidence_aware_skill_replacements", _fail_if_called)
    monkeypatch.setattr("applypilot.scoring.pdf.measure_html_page_count", lambda _html: 1)

    html_path, planning = render_model_to_pdf_with_planning(
        model,
        output_path=tmp_path / "model_direct_repair_path.html",
        template_name="professional_compact",
        html_only=True,
        job_description="Java Spring Boot SQL backend role",
        skills_selection={"min_count": 1},
    )

    assert html_path.exists()
    assert "evidence_aware_skill_adjustments" in planning
    assert "unsupported_skill_removals" in planning
    assert "final_weak_or_unsupported_claim_dispositions" in planning
    assert "unsupported_visible_claims_final" in planning
    assert "weak_visible_claims_final" in planning


def test_evidence_aware_skill_replacement_kept_when_pdf_still_fits(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="PostgreSQL, Java, Spring Boot, Docker, Kubernetes, Messaging, Kafka")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Kafka event pipelines."])],
    )
    prepared = SimpleNamespace()
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "PostgreSQL", "coverage_status": "unsupported"}],
        "unsupported_visible_claims": ["PostgreSQL"],
        "weak_visible_claims": [],
    }

    monkeypatch.setattr(
        pdf_module,
        "build_claim_coverage_for_claims",
        lambda **_kwargs: [
            ClaimCoverage(
                claim="Kafka",
                claim_type="skill",
                is_visible=False,
                supporting_evidence_count=1,
                retained_supporting_evidence_count=1,
                primary_supporting_evidence_count=1,
                retained_primary_supporting_evidence_count=1,
                secondary_supporting_evidence_count=0,
                coverage_status="supported",
                top_supporting_evidence=["Acme: Built Kafka event pipelines."],
            )
        ],
    )
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", SimpleNamespace()))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Kafka", "coverage_status": "supported"}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
        },
    )

    new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=prepared,
        planning=planning,
        template_name="professional_compact",
        job_description="Build event-driven systems.",
        skills_selection={
            "retained_skills": [
                {"skill": "PostgreSQL", "score": 90.0},
                {"skill": "Kafka", "score": 88.0},
            ]
        },
    )

    assert extract_all_skill_claims(new_model)[0] == "Kafka"
    assert updated["unsupported_visible_claims_final"] == []
    assert updated["evidence_aware_skill_adjustments"][0]["kept"] is True
    assert updated.get("unsupported_skill_removals", []) == []
    assert any(
        item.get("claim") == "PostgreSQL" and item.get("final_action") == "replaced"
        for item in updated["final_weak_or_unsupported_claim_dispositions"]
    )


def test_evidence_aware_skill_replacement_uses_render_planning_service_when_supplied(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="PostgreSQL, Java, Kafka")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Kafka event pipelines."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "PostgreSQL", "coverage_status": "unsupported"}],
        "unsupported_visible_claims": ["PostgreSQL"],
        "weak_visible_claims": [],
    }
    monkeypatch.setattr(
        pdf_module,
        "build_claim_coverage_for_claims",
        lambda **_kwargs: [
            ClaimCoverage(
                claim="Kafka",
                claim_type="skill",
                is_visible=False,
                supporting_evidence_count=1,
                retained_supporting_evidence_count=1,
                primary_supporting_evidence_count=1,
                retained_primary_supporting_evidence_count=1,
                secondary_supporting_evidence_count=0,
                coverage_status="supported",
                top_supporting_evidence=["Acme: Built Kafka event pipelines."],
            )
        ],
    )

    class _FakeRenderService:
        def __init__(self) -> None:
            self.calls = 0

        def rebuild_state(self, *, model: ResumeRenderModel, context: RenderPlanningContext) -> RenderPlanningState:
            self.calls += 1
            assert context.template_name == "professional_compact"
            return RenderPlanningState(
                model=model,
                html="<html/>",
                prepared=SimpleNamespace(),
                planning={
                    "allowed_physical_pages": 2,
                    "measured_pages_final": 2,
                    "claim_coverage": [{"claim": "Kafka", "coverage_status": "supported"}],
                    "unsupported_visible_claims": [],
                    "weak_visible_claims": [],
                },
            )

        def measured_fit(self, state: RenderPlanningState) -> tuple[int | None, bool]:
            return state.measured_pages, True

    service = _FakeRenderService()
    new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(),
        planning=planning,
        template_name="professional_compact",
        job_description="Build event-driven systems.",
        skills_selection={"retained_skills": [{"skill": "PostgreSQL", "score": 90.0}, {"skill": "Kafka", "score": 88.0}]},
        render_planning_service=service,
    )

    assert service.calls >= 1
    assert extract_all_skill_claims(new_model)[0] == "Kafka"
    assert updated["evidence_aware_skill_adjustments"][0]["kept"] is True


def test_legacy_wrapper_delegates_without_recursing_on_callback_only_helper(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="PostgreSQL, Java, Kafka")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Kafka event pipelines."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "PostgreSQL", "coverage_status": "unsupported"}],
        "unsupported_visible_claims": ["PostgreSQL"],
        "weak_visible_claims": [],
    }

    monkeypatch.setattr(
        pdf_module,
        "build_claim_coverage_for_claims",
        lambda **_kwargs: [
            ClaimCoverage(
                claim="Kafka",
                claim_type="skill",
                is_visible=False,
                supporting_evidence_count=1,
                retained_supporting_evidence_count=1,
                primary_supporting_evidence_count=1,
                retained_primary_supporting_evidence_count=1,
                secondary_supporting_evidence_count=0,
                coverage_status="supported",
                top_supporting_evidence=["Acme: Built Kafka event pipelines."],
            )
        ],
    )
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", SimpleNamespace()))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Kafka", "coverage_status": "supported"}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
        },
    )
    callback_only_helper = SkillRepairPlanner(
        apply_skill_repair=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("callback-only helper should not be used by legacy wrapper")
        ),
    )
    new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(),
        planning=planning,
        template_name="professional_compact",
        job_description="Build event-driven systems.",
        skills_selection={"retained_skills": [{"skill": "PostgreSQL", "score": 90.0}, {"skill": "Kafka", "score": 88.0}]},
        skill_repair_helpers=callback_only_helper,
    )

    assert extract_all_skill_claims(new_model)[0] == "Kafka"
    assert updated["unsupported_visible_claims_final"] == []


def test_evidence_aware_skill_replacement_reverted_when_pdf_exceeds_limit(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="PostgreSQL, Java, Kafka")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Kafka event pipelines."])],
    )
    prepared = SimpleNamespace()
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "PostgreSQL", "coverage_status": "unsupported"}],
        "unsupported_visible_claims": ["PostgreSQL"],
        "weak_visible_claims": [],
    }

    monkeypatch.setattr(
        pdf_module,
        "build_claim_coverage_for_claims",
        lambda **_kwargs: [
            ClaimCoverage(
                claim="Kafka",
                claim_type="skill",
                is_visible=False,
                supporting_evidence_count=1,
                retained_supporting_evidence_count=1,
                primary_supporting_evidence_count=1,
                retained_primary_supporting_evidence_count=1,
                secondary_supporting_evidence_count=0,
                coverage_status="supported",
                top_supporting_evidence=["Acme: Built Kafka event pipelines."],
            )
        ],
    )
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", SimpleNamespace()))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 3,
            "claim_coverage": [{"claim": "PostgreSQL", "coverage_status": "unsupported"}],
            "unsupported_visible_claims": ["PostgreSQL"],
            "weak_visible_claims": [],
        },
    )

    new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=prepared,
        planning=planning,
        template_name="professional_compact",
        job_description="Build event-driven systems.",
        skills_selection={"retained_skills": [{"skill": "PostgreSQL", "score": 90.0}, {"skill": "Kafka", "score": 88.0}]},
    )

    assert extract_all_skill_claims(new_model)[0] == "PostgreSQL"
    assert updated["evidence_aware_skill_adjustments"][0]["kept"] is False
    assert "PostgreSQL" in updated["unsupported_visible_claims_final"]
    assert any(
        item.get("claim") == "PostgreSQL"
        and item.get("reason") in {"replacement_would_overflow_page_target", "min_visible_skill_count_guard"}
        for item in updated["final_weak_or_unsupported_claim_dispositions"]
    )


def test_weak_summary_only_claim_is_replaced_when_supported_candidate_exists(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Docker, Java, Kafka")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Kafka event pipelines."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "Docker", "coverage_status": "weak_summary_only"}],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Docker"],
    }
    monkeypatch.setattr(
        pdf_module,
        "build_claim_coverage_for_claims",
        lambda **_kwargs: [
            ClaimCoverage(
                claim="Kafka",
                claim_type="skill",
                is_visible=False,
                supporting_evidence_count=1,
                retained_supporting_evidence_count=1,
                primary_supporting_evidence_count=1,
                retained_primary_supporting_evidence_count=1,
                secondary_supporting_evidence_count=0,
                coverage_status="supported",
                top_supporting_evidence=["Acme: Built Kafka event pipelines."],
            )
        ],
    )
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", SimpleNamespace()))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Kafka", "coverage_status": "supported"}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
        },
    )

    new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(),
        planning=planning,
        template_name="professional_compact",
        job_description="Build event-driven systems.",
        skills_selection={"retained_skills": [{"skill": "Docker", "score": 92.0}, {"skill": "Kafka", "score": 90.0}]},
    )
    assert extract_all_skill_claims(new_model)[0] == "Kafka"
    assert updated["evidence_aware_skill_adjustments"][0]["kept"] is True


def test_weak_claim_replaced_when_supported_candidate_exists(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Distributed Systems, Java, Kafka")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Kafka event pipelines."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "Distributed Systems", "coverage_status": "weak"}],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Distributed Systems"],
    }
    monkeypatch.setattr(
        pdf_module,
        "build_claim_coverage_for_claims",
        lambda **_kwargs: [
            ClaimCoverage(
                claim="Kafka",
                claim_type="skill",
                is_visible=False,
                supporting_evidence_count=1,
                retained_supporting_evidence_count=1,
                primary_supporting_evidence_count=1,
                retained_primary_supporting_evidence_count=1,
                secondary_supporting_evidence_count=0,
                coverage_status="supported",
                top_supporting_evidence=["Acme: Built Kafka event pipelines."],
            )
        ],
    )
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", SimpleNamespace()))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Kafka", "coverage_status": "supported"}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
        },
    )

    new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(),
        planning=planning,
        template_name="professional_compact",
        job_description="Build event-driven systems.",
        skills_selection={"retained_skills": [{"skill": "Distributed Systems", "score": 95.0}, {"skill": "Kafka", "score": 90.0}]},
    )
    assert extract_all_skill_claims(new_model)[0] == "Kafka"
    assert updated["evidence_aware_skill_adjustments"][0]["kept"] is True


def test_evidence_aware_skill_adjustment_removes_weak_summary_only_but_keeps_weak_claims(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Docker, Messaging, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {"claim": "Docker", "coverage_status": "weak_summary_only", "primary_supporting_evidence_count": 0},
            {"claim": "Messaging", "coverage_status": "weak", "primary_supporting_evidence_count": 1},
            {"claim": "Java", "coverage_status": "supported", "primary_supporting_evidence_count": 1},
        ],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Docker", "Messaging"],
    }

    original = pdf_module.build_claim_coverage_for_claims
    pdf_module.build_claim_coverage_for_claims = lambda **_kwargs: []
    monkeypatch.setattr("applypilot.scoring.pdf.measure_html_page_count", lambda _html: 1)
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", SimpleNamespace()))

    def _build_dynamic_planning(**kwargs):
        claims = extract_all_skill_claims(kwargs["model"])
        claim_coverage = []
        weak = []
        for claim in claims:
            key = claim.lower().strip()
            if key == "java":
                status = "supported"
                primary = 1
            elif key == "messaging":
                status = "weak"
                primary = 1
                weak.append(claim)
            elif key == "docker":
                status = "weak_summary_only"
                primary = 0
                weak.append(claim)
            else:
                status = "unsupported"
                primary = 0
            claim_coverage.append(
                {
                    "claim": claim,
                    "coverage_status": status,
                    "primary_supporting_evidence_count": primary,
                    "retained_primary_supporting_evidence_count": 1 if status in {"supported", "weak"} else 0,
                }
            )
        return {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": claim_coverage,
            "unsupported_visible_claims": [item["claim"] for item in claim_coverage if item["coverage_status"] == "unsupported"],
            "weak_visible_claims": weak,
        }

    monkeypatch.setattr(pdf_module, "_build_planning_with_evidence", _build_dynamic_planning)
    try:
        new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
            model=model,
            html="<html/>",
            prepared=SimpleNamespace(),
            planning=planning,
            template_name="professional_compact",
            job_description="Build backend systems.",
            skills_selection={
                "retained_skills": [
                    {"skill": "Docker", "score": 92.0},
                    {"skill": "Messaging", "score": 90.0},
                    {"skill": "Java", "score": 89.0},
                ],
                "min_count": 1,
            },
        )
    finally:
        pdf_module.build_claim_coverage_for_claims = original

    claims = extract_all_skill_claims(new_model)
    assert "Docker" not in claims
    assert "Messaging" in claims
    assert updated["evidence_aware_skill_adjustments"] == []
    assert "Docker" not in updated["weak_visible_claims_final"]
    assert "Messaging" in updated["weak_visible_claims_final"]
    assert any(
        item.get("claim") == "Docker" and item.get("final_action") == "removed"
        for item in updated["final_weak_or_unsupported_claim_dispositions"]
    )
    assert any(
        item.get("claim") == "Docker" and item.get("result") == "no_supported_retained_replacement_available"
        for item in updated.get("supported_replacement_candidate_searches", [])
    )
    assert any(
        item.get("claim") == "Docker"
        and item.get("coverage_status") == "weak_summary_only"
        and item.get("kept") is True
        for item in updated.get("unsupported_skill_removals", [])
    )


def test_unsupported_claim_without_source_evidence_is_reported() -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Kubernetes, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services"])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {
                "claim": "Kubernetes",
                "coverage_status": "unsupported",
                "primary_supporting_evidence_count": 0,
                "retained_primary_supporting_evidence_count": 0,
            }
        ],
        "unsupported_visible_claims": ["Kubernetes"],
        "weak_visible_claims": [],
    }
    original = pdf_module.build_claim_coverage_for_claims
    pdf_module.build_claim_coverage_for_claims = lambda **_kwargs: []
    try:
        _model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
            model=model,
            html="<html/>",
            prepared=SimpleNamespace(),
            planning=planning,
            template_name="professional_compact",
            job_description="Build backend systems.",
            skills_selection={"retained_skills": [{"skill": "Kubernetes", "score": 90.0}]},
        )
    finally:
        pdf_module.build_claim_coverage_for_claims = original
    assert updated["unsupported_visible_claims_without_source_evidence"] == [
        {"claim": "Kubernetes", "reason": "no_primary_source_evidence_found"}
    ]


def test_no_duplicate_replacement_candidate_used_twice(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="PostgreSQL, Docker, Java, Kafka")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Kafka event pipelines."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {"claim": "PostgreSQL", "coverage_status": "unsupported"},
            {"claim": "Docker", "coverage_status": "weak_summary_only"},
        ],
        "unsupported_visible_claims": ["PostgreSQL"],
        "weak_visible_claims": ["Docker"],
    }
    monkeypatch.setattr(
        pdf_module,
        "build_claim_coverage_for_claims",
        lambda **_kwargs: [
            ClaimCoverage(
                claim="Kafka",
                claim_type="skill",
                is_visible=False,
                supporting_evidence_count=1,
                retained_supporting_evidence_count=1,
                primary_supporting_evidence_count=1,
                retained_primary_supporting_evidence_count=1,
                secondary_supporting_evidence_count=0,
                coverage_status="supported",
                top_supporting_evidence=["Acme: Built Kafka event pipelines."],
            )
        ],
    )
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", SimpleNamespace()))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Kafka", "coverage_status": "supported"}, {"claim": "Docker", "coverage_status": "weak_summary_only"}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": ["Docker"],
        },
    )
    _model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(),
        planning=planning,
        template_name="professional_compact",
        job_description="Build event-driven systems.",
        skills_selection={"retained_skills": [{"skill": "PostgreSQL", "score": 95.0}, {"skill": "Docker", "score": 94.0}, {"skill": "Kafka", "score": 90.0}]},
    )
    assert len(updated["evidence_aware_skill_adjustments"]) == 1


def test_alias_conflict_prevents_duplicate_visible_alias(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Jenkins CI, GitLab CI, Java, Jenkins")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Maintained Jenkins CI pipelines."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "GitLab CI", "coverage_status": "unsupported"}, {"claim": "Jenkins CI", "coverage_status": "supported"}],
        "unsupported_visible_claims": ["GitLab CI"],
        "weak_visible_claims": [],
    }
    monkeypatch.setattr(
        pdf_module,
        "build_claim_coverage_for_claims",
        lambda **_kwargs: [
            ClaimCoverage(
                claim="Jenkins",
                claim_type="skill",
                is_visible=False,
                supporting_evidence_count=1,
                retained_supporting_evidence_count=1,
                primary_supporting_evidence_count=1,
                retained_primary_supporting_evidence_count=1,
                secondary_supporting_evidence_count=0,
                coverage_status="supported",
                top_supporting_evidence=["Acme: Maintained Jenkins CI pipelines."],
            )
        ],
    )
    _model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(),
        planning=planning,
        template_name="professional_compact",
        job_description="CI platform reliability.",
        skills_selection={"retained_skills": [{"skill": "GitLab CI", "score": 95.0}, {"skill": "Jenkins", "score": 90.0}]},
    )
    assert updated["evidence_aware_skill_adjustments"] == []
    disposition = next(
        item for item in updated["final_weak_or_unsupported_claim_dispositions"] if item.get("claim") == "GitLab CI"
    )
    assert disposition.get("final_action") == "kept"
    assert any(
        disposition.get("reason") == reason
        for reason in {
            "replacement_duplicate_or_alias_conflict",
            "min_visible_skill_count_guard",
            "no_supported_retained_replacement_available",
        }
    )
    assert any(item.get("decision") == "rejected_alias_conflict" for item in updated["supported_replacement_candidates_considered"])


def test_replacement_candidate_diagnostics_include_visible_rejection_reason(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="PostgreSQL, Java, Kafka")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Kafka event pipelines."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {"claim": "PostgreSQL", "coverage_status": "unsupported"},
            {"claim": "Java", "coverage_status": "supported"},
        ],
        "unsupported_visible_claims": ["PostgreSQL"],
        "weak_visible_claims": [],
    }
    monkeypatch.setattr(pdf_module, "build_claim_coverage_for_claims", lambda **_kwargs: [])
    _model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(),
        planning=planning,
        template_name="professional_compact",
        job_description="Backend systems.",
        skills_selection={"retained_skills": [{"skill": "PostgreSQL", "score": 99.0}, {"skill": "Java", "score": 98.0}]},
    )
    assert any(item.get("decision") == "rejected_already_visible" for item in updated["supported_replacement_candidates_considered"])


def test_unsupported_skill_removed_when_no_supported_replacement_exists_and_above_minimum(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Jenkins CI, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {"claim": "Jenkins CI", "coverage_status": "unsupported", "primary_supporting_evidence_count": 0},
            {"claim": "Java", "coverage_status": "supported", "primary_supporting_evidence_count": 1},
        ],
        "unsupported_visible_claims": ["Jenkins CI"],
        "weak_visible_claims": [],
    }
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", SimpleNamespace()))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Java", "coverage_status": "supported", "primary_supporting_evidence_count": 1}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
        },
    )

    new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(),
        planning=planning,
        template_name="professional_compact",
        job_description="Build backend systems.",
        skills_selection={"retained_skills": [{"skill": "Jenkins CI", "score": 95.0}, {"skill": "Java", "score": 94.0}], "min_count": 1},
    )

    assert "Jenkins CI" not in extract_all_skill_claims(new_model)
    assert updated["unsupported_visible_claims_final"] == []
    assert all(item.get("claim") != "Jenkins CI" for item in updated.get("claim_coverage", []))
    assert updated["unsupported_skill_removals"][0]["kept"] is True
    assert any(op.get("step") == "unsupported_skill_removal" and op.get("kept") is True for op in updated["planning_operations"])
    assert any(
        item.get("claim") == "Jenkins CI" and item.get("final_action") == "removed"
        for item in updated["final_weak_or_unsupported_claim_dispositions"]
    )


def test_unsupported_skill_not_removed_when_minimum_visible_skill_guard_hits(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Jenkins CI, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {"claim": "Jenkins CI", "coverage_status": "unsupported", "primary_supporting_evidence_count": 0},
            {"claim": "Java", "coverage_status": "supported", "primary_supporting_evidence_count": 1},
        ],
        "unsupported_visible_claims": ["Jenkins CI"],
        "weak_visible_claims": [],
    }
    new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(),
        planning=planning,
        template_name="professional_compact",
        job_description="Build backend systems.",
        skills_selection={"retained_skills": [{"skill": "Jenkins CI", "score": 95.0}, {"skill": "Java", "score": 94.0}], "min_count": 2},
    )
    assert "Jenkins CI" in extract_all_skill_claims(new_model)
    assert updated["unsupported_skill_removals"][0]["kept"] is False
    assert updated["unsupported_skill_removals"][0]["revert_reason"] == "visible_skill_count_below_minimum"
    assert any(
        item.get("claim") == "Jenkins CI" and item.get("reason") == "min_visible_skill_count_guard"
        for item in updated["final_weak_or_unsupported_claim_dispositions"]
    )


def test_weak_summary_only_skill_not_removed_when_minimum_visible_skill_guard_hits() -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Docker, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {"claim": "Docker", "coverage_status": "weak_summary_only", "primary_supporting_evidence_count": 0},
            {"claim": "Java", "coverage_status": "supported", "primary_supporting_evidence_count": 1},
        ],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Docker"],
    }
    new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(),
        planning=planning,
        template_name="professional_compact",
        job_description="Build backend systems.",
        skills_selection={
            "retained_skills": [{"skill": "Docker", "score": 92.0}, {"skill": "Java", "score": 91.0}],
            "min_count": 2,
        },
    )
    assert "Docker" in extract_all_skill_claims(new_model)
    assert any(
        item.get("claim") == "Docker"
        and item.get("coverage_status") == "weak_summary_only"
        and item.get("kept") is False
        and item.get("revert_reason") == "visible_skill_count_below_minimum"
        for item in updated.get("unsupported_skill_removals", [])
    )
    assert "Docker" in updated.get("weak_visible_claims_final", [])
    assert any(
        item.get("claim") == "Docker" and item.get("reason") == "min_visible_skill_count_guard"
        for item in updated.get("final_weak_or_unsupported_claim_dispositions", [])
    )


def test_weak_claim_removed_when_no_retained_primary_evidence_and_above_minimum(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Kubernetes, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {
                "claim": "Kubernetes",
                "coverage_status": "weak",
                "primary_supporting_evidence_count": 1,
                "retained_primary_supporting_evidence_count": 0,
            },
            {
                "claim": "Java",
                "coverage_status": "supported",
                "primary_supporting_evidence_count": 1,
                "retained_primary_supporting_evidence_count": 1,
            },
        ],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Kubernetes"],
    }
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", SimpleNamespace()))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Java", "coverage_status": "supported", "retained_primary_supporting_evidence_count": 1}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
        },
    )
    new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(),
        planning=planning,
        template_name="professional_compact",
        job_description="Kubernetes platform reliability.",
        skills_selection={"retained_skills": [{"skill": "Kubernetes", "score": 90.0}, {"skill": "Java", "score": 89.0}], "min_count": 1},
    )
    assert "Kubernetes" not in extract_all_skill_claims(new_model)
    assert "Kubernetes" not in updated.get("weak_visible_claims_final", [])
    assert any(
        item.get("claim") == "Kubernetes"
        and item.get("coverage_status") == "weak"
        and item.get("kept") is True
        and item.get("removal_applied") is True
        for item in updated.get("unsupported_skill_removals", [])
    )


def test_unsupported_skill_removal_keeps_weak_claims_and_can_remove_weak_summary_only(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Docker, Messaging, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {"claim": "Docker", "coverage_status": "weak_summary_only", "primary_supporting_evidence_count": 0},
            {"claim": "Messaging", "coverage_status": "weak", "primary_supporting_evidence_count": 1},
            {"claim": "Java", "coverage_status": "supported", "primary_supporting_evidence_count": 1},
        ],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Docker", "Messaging"],
    }
    monkeypatch.setattr("applypilot.scoring.pdf.measure_html_page_count", lambda _html: 1)
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", SimpleNamespace()))

    def _build_dynamic_planning(**kwargs):
        claims = extract_all_skill_claims(kwargs["model"])
        claim_coverage = []
        weak = []
        for claim in claims:
            key = claim.lower().strip()
            if key == "java":
                status = "supported"
                primary = 1
            elif key == "messaging":
                status = "weak"
                primary = 1
                weak.append(claim)
            elif key == "docker":
                status = "weak_summary_only"
                primary = 0
                weak.append(claim)
            else:
                status = "unsupported"
                primary = 0
            claim_coverage.append(
                {
                    "claim": claim,
                    "coverage_status": status,
                    "primary_supporting_evidence_count": primary,
                    "retained_primary_supporting_evidence_count": 1 if status in {"supported", "weak"} else 0,
                }
            )
        return {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": claim_coverage,
            "unsupported_visible_claims": [item["claim"] for item in claim_coverage if item["coverage_status"] == "unsupported"],
            "weak_visible_claims": weak,
        }

    monkeypatch.setattr(pdf_module, "_build_planning_with_evidence", _build_dynamic_planning)
    new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(),
        planning=planning,
        template_name="professional_compact",
        job_description="Build backend systems.",
        skills_selection={
            "retained_skills": [
                {"skill": "Docker", "score": 92.0},
                {"skill": "Messaging", "score": 90.0},
                {"skill": "Java", "score": 89.0},
            ],
            "min_count": 1,
        },
    )
    claims = extract_all_skill_claims(new_model)
    assert "Docker" not in claims
    assert "Messaging" in claims
    assert any(
        item.get("claim") == "Docker"
        and item.get("coverage_status") == "weak_summary_only"
        and item.get("kept") is True
        for item in updated.get("unsupported_skill_removals", [])
    )


def test_second_unsupported_skill_removed_when_only_supported_candidate_was_already_used(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="PostgreSQL, Kubernetes, Jenkins CI, Docker, TDD")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {"claim": "PostgreSQL", "coverage_status": "unsupported", "primary_supporting_evidence_count": 0},
            {"claim": "Kubernetes", "coverage_status": "unsupported", "primary_supporting_evidence_count": 0},
            {"claim": "Jenkins CI", "coverage_status": "unsupported", "primary_supporting_evidence_count": 0},
            {"claim": "Docker", "coverage_status": "weak_summary_only", "primary_supporting_evidence_count": 0},
        ],
        "unsupported_visible_claims": ["PostgreSQL", "Kubernetes", "Jenkins CI"],
        "weak_visible_claims": ["Docker"],
    }

    def _status_for_claim(claim: str) -> tuple[str, int]:
        key = claim.lower().strip()
        if key == "tdd":
            return "supported", 1
        if key in {"postgresql", "kubernetes", "jenkins ci"}:
            return "unsupported", 0
        if key == "docker":
            return "weak_summary_only", 0
        return "unsupported", 0

    def _build_dynamic_planning(**kwargs):
        model_arg = kwargs["model"]
        claims = extract_all_skill_claims(model_arg)[:4]
        claim_coverage = []
        unsupported = []
        weak = []
        for claim in claims:
            status, primary_count = _status_for_claim(claim)
            claim_coverage.append(
                {
                    "claim": claim,
                    "coverage_status": status,
                    "primary_supporting_evidence_count": primary_count,
                    "retained_primary_supporting_evidence_count": 0 if status != "supported" else 1,
                }
            )
            if status == "unsupported":
                unsupported.append(claim)
            elif status in {"weak", "weak_summary_only"}:
                weak.append(claim)
        return {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": claim_coverage,
            "unsupported_visible_claims": unsupported,
            "weak_visible_claims": weak,
        }

    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", SimpleNamespace(skills_mode="selected", selected_skills_max_lines=1)))
    monkeypatch.setattr(pdf_module, "_build_planning_with_evidence", _build_dynamic_planning)
    monkeypatch.setattr(
        pdf_module,
        "extract_visible_skill_claims",
        lambda model_arg, _prepared: extract_all_skill_claims(model_arg)[:4],
    )

    def _hidden_claim_coverage(*, claims, **_kwargs):
        out: list[ClaimCoverage] = []
        for claim in claims:
            key = claim.lower().strip()
            if key == "tdd":
                out.append(
                    ClaimCoverage(
                        claim=claim,
                        claim_type="skill",
                        is_visible=False,
                        supporting_evidence_count=1,
                        retained_supporting_evidence_count=1,
                        primary_supporting_evidence_count=1,
                        retained_primary_supporting_evidence_count=1,
                        secondary_supporting_evidence_count=0,
                        coverage_status="supported",
                        top_supporting_evidence=["Acme: Test-driven delivery improvements."],
                    )
                )
        return out

    monkeypatch.setattr(pdf_module, "build_claim_coverage_for_claims", _hidden_claim_coverage)

    new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(skills_mode="selected", selected_skills_max_lines=1),
        planning=planning,
        template_name="professional_compact",
        job_description="Backend systems.",
        skills_selection={
            "retained_skills": [
                {"skill": "PostgreSQL", "score": 99.0},
                {"skill": "Kubernetes", "score": 98.0},
                {"skill": "Jenkins CI", "score": 97.0},
                {"skill": "Docker", "score": 96.0},
                {"skill": "TDD", "score": 95.0},
            ],
            "min_count": 2,
        },
    )

    claims = extract_all_skill_claims(new_model)
    assert "TDD" in claims
    assert "Jenkins CI" not in updated["unsupported_visible_claims_final"]
    assert "Kubernetes" not in updated["unsupported_visible_claims_final"]
    assert "PostgreSQL" not in updated["unsupported_visible_claims_final"]
    assert any(item.get("step") == "evidence_aware_skill_replacement" and item.get("from") == "PostgreSQL" and item.get("kept") is True for item in updated["planning_operations"])
    kept_removals = [item for item in updated["unsupported_skill_removals"] if item.get("kept")]
    assert any(item.get("claim") == "Kubernetes" for item in kept_removals)
    assert any(item.get("claim") == "Jenkins CI" for item in kept_removals)
    assert any(item.get("claim") == "PostgreSQL" for item in kept_removals)
    assert all(item.get("claim") not in {"Kubernetes", "Jenkins CI", "PostgreSQL"} for item in updated.get("claim_coverage", []))
    postgres_disp = next(
        item for item in updated["final_weak_or_unsupported_claim_dispositions"] if item.get("claim") == "PostgreSQL"
    )
    assert postgres_disp.get("final_action") == "removed"
    assert postgres_disp.get("reason") == "unsupported_no_replacement_no_source_evidence"
    assert "replacement" not in postgres_disp
    assert postgres_disp.get("action_history") == [
        {"action": "replaced", "replacement": "TDD", "reason": "replaced_by_supported_retained_skill"},
        {"action": "removed", "reason": "unsupported_no_replacement_no_source_evidence"},
    ]
    assert "user_action" in postgres_disp


def test_removed_disposition_action_history_does_not_use_kept_for_intermediate_state(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="PostgreSQL, Kafka")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Kafka event pipelines."])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {"claim": "PostgreSQL", "coverage_status": "unsupported", "primary_supporting_evidence_count": 0},
        ],
        "unsupported_visible_claims": ["PostgreSQL"],
        "weak_visible_claims": [],
    }
    monkeypatch.setattr(
        pdf_module,
        "build_claim_coverage_for_claims",
        lambda **_kwargs: [
            ClaimCoverage(
                claim="Kafka",
                claim_type="skill",
                is_visible=False,
                supporting_evidence_count=1,
                retained_supporting_evidence_count=1,
                primary_supporting_evidence_count=1,
                retained_primary_supporting_evidence_count=1,
                secondary_supporting_evidence_count=0,
                coverage_status="supported",
                top_supporting_evidence=["Acme: Built Kafka event pipelines."],
            )
        ],
    )
    monkeypatch.setattr(
        pdf_module,
        "_build_html_and_prepared_for_resume",
        lambda *_args, **_kwargs: ("<html/>", SimpleNamespace(skills_mode="selected", selected_skills_max_lines=1)),
    )

    def _planning_for_model(**kwargs):
        model_arg = kwargs["model"]
        claims = extract_all_skill_claims(model_arg)
        if any(claim.lower() == "postgresql" for claim in claims):
            return {
                "allowed_physical_pages": 2,
                "measured_pages_final": 3,
                "claim_coverage": [
                    {"claim": "PostgreSQL", "coverage_status": "unsupported", "primary_supporting_evidence_count": 0},
                ],
                "unsupported_visible_claims": ["PostgreSQL"],
                "weak_visible_claims": [],
            }
        return {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Kafka", "coverage_status": "supported", "primary_supporting_evidence_count": 1}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
        }

    monkeypatch.setattr(pdf_module, "_build_planning_with_evidence", _planning_for_model)

    _new_model, _html, _prepared, updated = _apply_evidence_aware_skill_replacements(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(skills_mode="selected", selected_skills_max_lines=1),
        planning=planning,
        template_name="professional_compact",
        job_description="Build backend systems.",
        skills_selection={"retained_skills": [{"skill": "PostgreSQL", "score": 99.0}, {"skill": "Kafka", "score": 98.0}], "min_count": 1},
    )

    disp = next(item for item in updated["final_weak_or_unsupported_claim_dispositions"] if item.get("claim") == "PostgreSQL")
    assert disp.get("final_action") == "removed"
    assert disp.get("reason") == "unsupported_no_replacement_no_source_evidence"
    assert "replacement" not in disp
    history = disp.get("action_history")
    assert isinstance(history, list) and len(history) == 2
    assert history[0]["action"] == "replacement_not_kept"
    assert history[0]["reason"] == "replacement_would_overflow_page_target"
    assert history[1] == {"action": "removed", "reason": "unsupported_no_replacement_no_source_evidence"}
    assert "user_action" in disp


def test_evidence_preservation_restore_trimmed_bullet_kept_when_fit(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Docker, Java, Spring Boot")],
        experience=[
            ResumeEntry(
                title="Engineer",
                subtitle="Acme",
                bullets=["Built APIs", "Improved tests", "Containerized services with Docker"],
            ),
            ResumeEntry(title="Engineer II", subtitle="Beta", bullets=["Built APIs"]),
        ],
    )
    prepared = SimpleNamespace(detailed_bullet_cap=2, earlier_experience_mode="compact")
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {
                "claim": "Docker",
                "coverage_status": "weak",
                "primary_supporting_evidence_count": 1,
                "retained_primary_supporting_evidence_count": 0,
            }
        ],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Docker"],
        "evidence_available_but_not_rendered": [
            {
                "claim": "Docker",
                "candidate_evidence_items": [
                    {
                        "source_type": "experience_bullet",
                        "source_label": "Acme",
                        "source_path": "experience[0].bullets[2]",
                        "text": "Containerized services with Docker",
                        "evidence_score": 0.9,
                        "reason_not_rendered": "bullet_trimmed",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", prepared))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [
                {
                    "claim": "Docker",
                    "coverage_status": "supported",
                    "primary_supporting_evidence_count": 1,
                    "retained_primary_supporting_evidence_count": 1,
                }
            ],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
            "evidence_available_but_not_rendered": [],
        },
    )

    updated_model, _html, _prepared, updated = _apply_evidence_preservation(
        model=model,
        html="<html/>",
        prepared=prepared,
        planning=planning,
        template_name="professional_compact",
        job_description="Containerized systems.",
    )

    assert updated_model.experience[0].bullets[1] == "Containerized services with Docker"
    assert updated["evidence_preservation_attempts"][0]["operation"] == "restore_trimmed_bullet"
    assert updated["evidence_preservation_attempts"][0]["kept"] is True
    assert updated["evidence_preservation_decisions"][0]["decision"] == "attempted"


def test_evidence_preservation_reverts_when_overflow(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Docker, Java")],
        experience=[
            ResumeEntry(
                title="Engineer",
                subtitle="Acme",
                bullets=["Built APIs", "Improved tests", "Containerized services with Docker"],
            ),
            ResumeEntry(title="Engineer II", subtitle="Beta", bullets=["Built APIs"]),
        ],
    )
    prepared = SimpleNamespace(detailed_bullet_cap=2, earlier_experience_mode="compact")
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "Docker", "coverage_status": "weak", "primary_supporting_evidence_count": 1, "retained_primary_supporting_evidence_count": 0}],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Docker"],
        "evidence_available_but_not_rendered": [
            {
                "claim": "Docker",
                "candidate_evidence_items": [
                    {
                        "source_type": "experience_bullet",
                        "source_label": "Acme",
                        "source_path": "experience[0].bullets[2]",
                        "text": "Containerized services with Docker",
                        "evidence_score": 0.9,
                        "reason_not_rendered": "bullet_trimmed",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", prepared))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 3,
            "claim_coverage": [{"claim": "Docker", "coverage_status": "weak", "primary_supporting_evidence_count": 1, "retained_primary_supporting_evidence_count": 0}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": ["Docker"],
            "evidence_available_but_not_rendered": [],
        },
    )

    updated_model, _html, _prepared, updated = _apply_evidence_preservation(
        model=model,
        html="<html/>",
        prepared=prepared,
        planning=planning,
        template_name="professional_compact",
        job_description="Containerized systems.",
    )

    assert updated_model.experience[0].bullets[1] == "Improved tests"
    assert updated["evidence_preservation_attempts"][0]["kept"] is False
    assert updated["evidence_preservation_decisions"][0]["decision"] == "skipped_would_exceed_page_target"


def test_evidence_preservation_hidden_project_line_attempted_and_kept(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Jenkins, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services"])],
        projects=[ResumeEntry(title="CI Automation", subtitle="2024", bullets=["Built Jenkins CI pipelines"], compact_summary="Built Jenkins CI pipelines")],
    )
    prepared = SimpleNamespace(detailed_bullet_cap=2, earlier_experience_mode="compact")
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "Jenkins", "coverage_status": "weak", "primary_supporting_evidence_count": 1, "retained_primary_supporting_evidence_count": 0}],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Jenkins"],
        "evidence_available_but_not_rendered": [
            {
                "claim": "Jenkins",
                "candidate_evidence_items": [
                    {
                        "source_type": "project_bullet",
                        "source_label": "CI Automation",
                        "source_path": "projects[0].bullets[0]",
                        "text": "Built Jenkins CI pipelines",
                        "evidence_score": 0.8,
                        "reason_not_rendered": "hidden_project",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", prepared))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Jenkins", "coverage_status": "supported", "primary_supporting_evidence_count": 1, "retained_primary_supporting_evidence_count": 1}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
            "evidence_available_but_not_rendered": [],
        },
    )

    updated_model, _html, _prepared, updated = _apply_evidence_preservation(
        model=model,
        html="<html/>",
        prepared=prepared,
        planning=planning,
        template_name="professional_compact",
        job_description="CI platform reliability.",
    )
    assert updated_model.render_options["preserve_selected_project_indices"] == [0]
    assert updated["evidence_preservation_attempts"][0]["operation"] == "add_selected_project_line"
    assert updated["evidence_preservation_attempts"][0]["kept"] is True
    assert updated["evidence_preservation_decisions"][0]["decision"] == "attempted"
    assert updated["evidence_preservation_attempts"][0]["claim_coverage_improved"] is True


def test_evidence_preservation_hidden_project_line_reverted_when_overflow(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Jenkins, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services"])],
        projects=[ResumeEntry(title="CI Automation", subtitle="2024", bullets=["Built Jenkins CI pipelines"], compact_summary="Built Jenkins CI pipelines")],
    )
    prepared = SimpleNamespace(detailed_bullet_cap=2, earlier_experience_mode="compact")
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "Jenkins", "coverage_status": "weak", "primary_supporting_evidence_count": 1, "retained_primary_supporting_evidence_count": 0}],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Jenkins"],
        "evidence_available_but_not_rendered": [
            {
                "claim": "Jenkins",
                "candidate_evidence_items": [
                    {
                        "source_type": "project_bullet",
                        "source_label": "CI Automation",
                        "source_path": "projects[0].bullets[0]",
                        "text": "Built Jenkins CI pipelines",
                        "evidence_score": 0.8,
                        "reason_not_rendered": "hidden_project",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", prepared))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 3,
            "claim_coverage": [{"claim": "Jenkins", "coverage_status": "weak", "primary_supporting_evidence_count": 1, "retained_primary_supporting_evidence_count": 0}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": ["Jenkins"],
            "evidence_available_but_not_rendered": [],
        },
    )

    updated_model, _html, _prepared, updated = _apply_evidence_preservation(
        model=model,
        html="<html/>",
        prepared=prepared,
        planning=planning,
        template_name="professional_compact",
        job_description="CI platform reliability.",
    )
    assert "preserve_selected_project_indices" not in updated_model.render_options
    assert updated["evidence_preservation_attempts"][0]["kept"] is False
    assert updated["evidence_preservation_decisions"][0]["decision"] == "skipped_would_exceed_page_target"


def test_evidence_preservation_fit_without_coverage_improvement_reverts(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Jenkins CI, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services"])],
        projects=[ResumeEntry(title="Mock Job", subtitle="2024", bullets=["Established CI/test gates and demos."], compact_summary="Established CI/test gates.")],
    )
    prepared = SimpleNamespace(detailed_bullet_cap=2, earlier_experience_mode="compact")
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {
                "claim": "Jenkins CI",
                "coverage_status": "weak",
                "primary_supporting_evidence_count": 1,
                "retained_primary_supporting_evidence_count": 0,
                "distinctive_tokens_required": ["jenkins"],
                "distinctive_tokens_matched": [],
            }
        ],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Jenkins CI"],
        "evidence_available_but_not_rendered": [
            {
                "claim": "Jenkins CI",
                "candidate_evidence_items": [
                    {
                        "source_type": "project_bullet",
                        "source_label": "Mock Job",
                        "source_path": "projects[0].bullets[0]",
                        "text": "Established CI/test gates and demos.",
                        "evidence_score": 0.8,
                        "reason_not_rendered": "hidden_project",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", prepared))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [
                {
                    "claim": "Jenkins CI",
                    "coverage_status": "weak",
                    "primary_supporting_evidence_count": 1,
                    "retained_primary_supporting_evidence_count": 0,
                    "distinctive_tokens_required": ["jenkins"],
                    "distinctive_tokens_matched": [],
                }
            ],
            "unsupported_visible_claims": [],
            "weak_visible_claims": ["Jenkins CI"],
            "evidence_available_but_not_rendered": [],
        },
    )
    updated_model, _html, _prepared, updated = _apply_evidence_preservation(
        model=model,
        html="<html/>",
        prepared=prepared,
        planning=planning,
        template_name="professional_compact",
        job_description="Jenkins CI ownership.",
    )
    assert "preserve_selected_project_indices" not in updated_model.render_options
    assert updated["evidence_preservation_attempts"][0]["kept"] is False
    assert updated["evidence_preservation_attempts"][0]["claim_coverage_improved"] is False
    assert updated["evidence_preservation_attempts"][0]["reason"] == "no_claim_coverage_improvement_after_render"


def test_hidden_project_preservation_uses_supporting_bullet_when_compact_summary_not_supportive(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="GitLab CI, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services"])],
        projects=[
            ResumeEntry(
                title="Deployment Tooling",
                subtitle="2024",
                bullets=["Built GitLab CI/CD pipeline automation for release reliability."],
                compact_summary="Improved team demos and workflow discipline.",
            )
        ],
    )
    prepared = SimpleNamespace(detailed_bullet_cap=2, earlier_experience_mode="compact")
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [
            {
                "claim": "GitLab CI",
                "coverage_status": "weak",
                "primary_supporting_evidence_count": 1,
                "retained_primary_supporting_evidence_count": 0,
                "distinctive_tokens_required": ["gitlab"],
                "distinctive_tokens_matched": [],
            }
        ],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["GitLab CI"],
        "evidence_available_but_not_rendered": [
            {
                "claim": "GitLab CI",
                "candidate_evidence_items": [
                    {
                        "source_type": "project_bullet",
                        "source_label": "Deployment Tooling",
                        "source_path": "projects[0].bullets[0]",
                        "text": "Built GitLab CI/CD pipeline automation for release reliability.",
                        "evidence_score": 0.9,
                        "reason_not_rendered": "hidden_project",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", prepared))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [
                {
                    "claim": "GitLab CI",
                    "coverage_status": "supported",
                    "primary_supporting_evidence_count": 1,
                    "retained_primary_supporting_evidence_count": 1,
                    "distinctive_tokens_required": ["gitlab"],
                    "distinctive_tokens_matched": ["gitlab"],
                }
            ],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
            "evidence_available_but_not_rendered": [],
        },
    )
    updated_model, _html, _prepared, updated = _apply_evidence_preservation(
        model=model,
        html="<html/>",
        prepared=prepared,
        planning=planning,
        template_name="professional_compact",
        job_description="GitLab CI ownership.",
    )
    assert updated_model.projects[0].compact_summary == "Built GitLab CI/CD pipeline automation for release reliability."
    assert updated["evidence_preservation_attempts"][0]["kept"] is True


def test_evidence_preservation_decision_records_compact_summary_preservation_attempt(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Jenkins, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services"], compact_summary="Worked with Jenkins")],
        projects=[],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "Jenkins", "coverage_status": "weak", "primary_supporting_evidence_count": 1, "retained_primary_supporting_evidence_count": 0}],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Jenkins"],
        "evidence_available_but_not_rendered": [
            {
                "claim": "Jenkins",
                "candidate_evidence_items": [
                    {
                        "source_type": "experience_compact_summary",
                        "source_label": "Acme",
                        "source_path": "experience[0].compact_summary",
                        "text": "Worked with Jenkins",
                        "evidence_score": 0.7,
                        "reason_not_rendered": "unknown",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(pdf_module, "_build_html_and_prepared_for_resume", lambda *_args, **_kwargs: ("<html/>", SimpleNamespace()))
    monkeypatch.setattr(
        pdf_module,
        "_build_planning_with_evidence",
        lambda **_kwargs: {
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [
                {
                    "claim": "Jenkins",
                    "coverage_status": "supported",
                    "primary_supporting_evidence_count": 1,
                    "retained_primary_supporting_evidence_count": 1,
                }
            ],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
            "evidence_available_but_not_rendered": [],
        },
    )
    _model, _html, _prepared, updated = _apply_evidence_preservation(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(detailed_bullet_cap=2, earlier_experience_mode="compact"),
        planning=planning,
        template_name="professional_compact",
        job_description="CI platform reliability.",
    )
    assert updated["evidence_preservation_decisions"][0]["decision"] in {"attempted", "not_attempted"}
    assert any(
        item.get("operation") == "restore_experience_compact_summary"
        for item in updated.get("evidence_preservation_attempts", [])
    )


def test_evidence_preservation_reports_low_score_skip_reason_for_non_distinctive_candidate() -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="GitLab CI, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services"])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "GitLab CI", "coverage_status": "weak", "primary_supporting_evidence_count": 1, "retained_primary_supporting_evidence_count": 0}],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["GitLab CI"],
        "evidence_available_but_not_rendered": [
            {
                "claim": "GitLab CI",
                "candidate_evidence_items": [
                    {
                        "source_type": "project_bullet",
                        "source_label": "Acme",
                        "source_path": "projects[0].bullets[0]",
                        "text": "Improved release process quality.",
                        "evidence_score": 0.1,
                        "reason_not_rendered": "hidden_project",
                    }
                ],
            }
        ],
    }
    _model, _html, _prepared, updated = _apply_evidence_preservation(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(detailed_bullet_cap=2, earlier_experience_mode="compact"),
        planning=planning,
        template_name="professional_compact",
        job_description="CI platform reliability.",
    )
    assert updated["evidence_preservation_attempts"] == []
    assert updated["evidence_preservation_decisions"][0]["decision"] == "skipped_low_evidence_score"
    assert updated["evidence_preservation_decisions"][0]["reason"] == "evidence_score_below_preservation_threshold"


def test_evidence_preservation_reports_cannot_identify_trimmed_bullet_state() -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Docker, Java")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built Java services", "Containerized with Docker"])],
    )
    planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "Docker", "coverage_status": "weak", "primary_supporting_evidence_count": 1, "retained_primary_supporting_evidence_count": 0}],
        "unsupported_visible_claims": [],
        "weak_visible_claims": ["Docker"],
        "evidence_available_but_not_rendered": [
            {
                "claim": "Docker",
                "candidate_evidence_items": [
                    {
                        "source_type": "experience_bullet",
                        "source_label": "Acme",
                        "source_path": "experience[0].bullets[1]",
                        "text": "Containerized with Docker",
                        "evidence_score": 0.9,
                        "reason_not_rendered": "bullet_trimmed",
                    }
                ],
            }
        ],
    }
    _model, _html, _prepared, updated = _apply_evidence_preservation(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(detailed_bullet_cap=None, earlier_experience_mode="compact"),
        planning=planning,
        template_name="professional_compact",
        job_description="Containerized services.",
    )
    assert updated["evidence_preservation_decisions"][0]["reason"] == "cannot_identify_trimmed_bullet_retention_state"


def test_skill_replacement_runs_after_preservation_and_skips_when_preserved(monkeypatch) -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Docker, Integration Testing")],
        experience=[ResumeEntry(title="Engineer", subtitle="Acme", bullets=["Built APIs", "Improved tests", "Containerized with Docker"])],
    )
    preserved_planning = {
        "allowed_physical_pages": 2,
        "measured_pages_final": 2,
        "claim_coverage": [{"claim": "Docker", "coverage_status": "supported", "primary_supporting_evidence_count": 1, "retained_primary_supporting_evidence_count": 1}],
        "unsupported_visible_claims": [],
        "weak_visible_claims": [],
        "evidence_available_but_not_rendered": [],
        "evidence_preservation_attempts": [{"step": "evidence_preservation", "kept": True}],
    }
    monkeypatch.setattr(
        pdf_module,
        "_build_html_and_prepared_for_resume",
        lambda *_args, **_kwargs: ("<html/>", SimpleNamespace(detailed_bullet_cap=2, earlier_experience_mode="compact")),
    )
    monkeypatch.setattr(pdf_module, "_build_planning_with_evidence", lambda **_kwargs: preserved_planning)

    preserved_model, html, prepared, planning = _apply_evidence_preservation(
        model=model,
        html="<html/>",
        prepared=SimpleNamespace(detailed_bullet_cap=2, earlier_experience_mode="compact"),
        planning={
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Docker", "coverage_status": "weak", "primary_supporting_evidence_count": 1, "retained_primary_supporting_evidence_count": 0}],
            "unsupported_visible_claims": [],
            "weak_visible_claims": ["Docker"],
            "evidence_available_but_not_rendered": [
                {"claim": "Docker", "candidate_evidence_items": [{"source_path": "experience[0].bullets[2]", "reason_not_rendered": "bullet_trimmed", "text": "Containerized with Docker", "source_label": "Acme", "evidence_score": 1.0}]}
            ],
        },
        template_name="professional_compact",
        job_description="Containerized systems.",
    )
    final_model, _html, _prepared, final_planning = _apply_evidence_aware_skill_replacements(
        model=preserved_model,
        html=html,
        prepared=prepared,
        planning=planning,
        template_name="professional_compact",
        job_description="Containerized systems.",
        skills_selection={"retained_skills": [{"skill": "Docker", "score": 95.0}, {"skill": "Integration Testing", "score": 93.0}]},
    )
    assert extract_all_skill_claims(final_model)[0] == "Docker"
    assert final_planning["evidence_aware_skill_adjustments"] == []


def test_compact_template_ignores_compact_summary_and_renders_bullets(tmp_path: Path) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        summary="Built and shipped reliable systems.",
        contact="alex@example.com | 555-111-2222",
        experience=[
            ResumeEntry(
                title="Senior Engineer",
                subtitle="Example Corp | 2022-01 - Present",
                bullets=["Built APIs"],
                compact_summary="Led backend reliability improvements.",
            )
        ],
        education="State University | BS Computer Science | 2018",
    )

    html_path = render_model_to_pdf(
        model,
        output_path=tmp_path / "compact_ignore_summary.html",
        template_name="compact",
        html_only=True,
    )
    html = html_path.read_text(encoding="utf-8")

    assert "Built APIs" in html
    assert "Led backend reliability improvements." not in html


def test_classic_template_renders_all_experience_detailed_without_selected_experience(tmp_path: Path) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        summary="Built and shipped reliable systems.",
        contact="alex@example.com | 555-111-2222",
        experience=[
            ResumeEntry(title="Role 1", subtitle="Company 1 | 2022", bullets=["Bullet 1"]),
            ResumeEntry(title="Role 2", subtitle="Company 2 | 2021", bullets=["Bullet 2"]),
            ResumeEntry(title="Role 3", subtitle="Company 3 | 2020", bullets=["Bullet 3"]),
        ],
        education="State University | BS Computer Science | 2018",
    )

    html_path = render_model_to_pdf(
        model,
        output_path=tmp_path / "classic.html",
        template_name="classic",
        html_only=True,
    )
    html = html_path.read_text(encoding="utf-8")

    assert "Experience" in html
    assert "Role 1" in html
    assert "Role 2" in html
    assert "Role 3" in html
    assert "Selected Experience" not in html


def test_compact_prepare_returns_template_view() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=[ResumeEntry(title="Senior Engineer", bullets=["Built APIs"])],
        projects=[ResumeEntry(title="TribeApp", bullets=["Built product features"])],
    )

    prepared = compact_template.prepare(model)

    assert isinstance(prepared, compact_template.CompactTemplateView)
    assert prepared.model == model
    assert prepared.detailed_experience == model.experience
    assert prepared.compact_experience == []
    assert prepared.projects_to_render == model.projects
    assert prepared.page_target is None


def _experience_entries(count: int) -> list[ResumeEntry]:
    return [
        ResumeEntry(
            title=f"Role {idx + 1}",
            subtitle=f"Company {idx + 1} | 20{10 + idx}-20{11 + idx}",
            bullets=[f"Bullet {idx + 1}"],
        )
        for idx in range(count)
    ]


def test_compact_prepare_with_three_entries_keeps_all_detailed() -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer", experience=_experience_entries(3))

    prepared = compact_template.prepare(model)

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1", "Role 2", "Role 3"]
    assert prepared.compact_experience == []


def test_compact_prepare_with_six_entries_keeps_first_four_detailed_and_moves_last_two() -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer", experience=_experience_entries(6))

    prepared = compact_template.prepare(model)

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1", "Role 2", "Role 3", "Role 4"]
    assert [entry.title for entry in prepared.compact_experience] == ["Role 5", "Role 6"]


def test_compact_prepare_invalid_render_option_falls_back_to_default() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=_experience_entries(6),
        render_options={"compact_max_detailed_experience": "bad-value"},
    )

    prepared = compact_template.prepare(model)

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1", "Role 2", "Role 3", "Role 4"]
    assert [entry.title for entry in prepared.compact_experience] == ["Role 5", "Role 6"]


def test_compact_prepare_render_option_two_keeps_first_two_detailed() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=_experience_entries(6),
        render_options={"compact_max_detailed_experience": 2},
    )

    prepared = compact_template.prepare(model)

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1", "Role 2"]
    assert [entry.title for entry in prepared.compact_experience] == ["Role 3", "Role 4", "Role 5", "Role 6"]


def test_compact_build_html_uses_prepared_view_and_preserves_content() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        summary="Built and shipped reliable systems.",
        contact="alex@example.com | 555-111-2222",
        experience=[
            ResumeEntry(
                title="Senior Engineer",
                subtitle="Example Corp | 2022-01 - Present",
                bullets=["Built APIs"],
            )
        ],
        education="State University | BS Computer Science | 2018",
    )

    html = compact_template.build_html(compact_template.prepare(model))

    assert "Alex Example" in html
    assert "Summary" in html
    assert "Experience" in html
    assert "Education" in html
    assert "Built APIs" in html
    assert "Selected Experience" not in html


def test_compact_build_html_with_prepare_on_six_entries_includes_selected_experience() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=_experience_entries(6),
    )

    html = compact_template.build_html(compact_template.prepare(model))

    assert "Experience" in html
    assert "Selected Experience" in html
    assert "Role 1" in html
    assert "Role 4" in html
    assert "Role 5" in html
    assert "Role 6" in html


def test_compact_build_html_renders_selected_experience_when_compact_entries_provided() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        summary="Built and shipped reliable systems.",
        contact="alex@example.com | 555-111-2222",
        experience=[ResumeEntry(title="Senior Engineer", bullets=["Built APIs"])],
        education="State University | BS Computer Science | 2018",
    )
    view = compact_template.CompactTemplateView(
        model=model,
        detailed_experience=model.experience,
        compact_experience=[
            ResumeEntry(
                title="Staff Engineer at Example Co",
                subtitle="2019 - 2021",
                bullets=["Led platform migration"],
                compact_summary="Led platform migration and reliability improvements.",
            )
        ],
        projects_to_render=[],
        page_target=None,
    )

    html = compact_template.build_html(view)

    assert "Selected Experience" in html
    assert "Staff Engineer at Example Co" in html
    assert "Led platform migration and reliability improvements." in html


def test_compact_build_html_selected_experience_falls_back_to_bullets_when_no_compact_summary() -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer")
    view = compact_template.CompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[
            ResumeEntry(
                title="Engineer at Example Co",
                subtitle="2017 - 2019",
                bullets=["Built API gateway", "Reduced incident MTTR"],
                compact_summary="",
            )
        ],
        projects_to_render=[],
        page_target=None,
    )

    html = compact_template.build_html(view)

    assert "Selected Experience" in html
    assert "Engineer at Example Co" in html
    assert "Built API gateway Reduced incident MTTR" in html
