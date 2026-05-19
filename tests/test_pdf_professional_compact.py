from __future__ import annotations

import json
from pathlib import Path
import re

from applypilot.scoring.pdf_render_model import ResumeEntry, ResumeRenderModel, SkillSection
from applypilot.scoring.pdf_templates import professional_compact


def _load_scale_ai_case() -> ResumeRenderModel:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "scale_ai_professional_compact_case.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    experience = [
        ResumeEntry(
            company=item["company"],
            role=item["role"],
            title=f"{item['company']} - {item['role']}",
            subtitle=item["subtitle"],
            bullets=[f"Impact bullet {index + 1}" for index in range(4)],
        )
        for index, item in enumerate(payload["experience"])
    ]
    projects = [
        ResumeEntry(
            title=item["name"],
            subtitle=item["subtitle"],
            bullets=item["bullets"],
        )
        for item in payload["projects"]
    ]
    return ResumeRenderModel(
        name=payload["name"],
        title=payload["title"],
        summary=payload["summary"],
        experience=experience,
        projects=projects,
    )


def _experience_entries(count: int) -> list[ResumeEntry]:
    return [
        ResumeEntry(
            title=f"Role {idx + 1}",
            subtitle=f"Company {idx + 1} | 20{10 + idx}-20{11 + idx}",
            bullets=[f"Bullet {idx + 1}"],
        )
        for idx in range(count)
    ]


def test_prepare_with_measurement_keeps_all_detailed_when_fit(monkeypatch) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=_experience_entries(4),
        render_options={"max_resume_pages": 4},
    )
    monkeypatch.setattr(professional_compact, "build_html", lambda view: str(len(view.detailed_experience)))

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1", "Role 2", "Role 3", "Role 4"]
    assert prepared.compact_experience == []


def test_prepare_with_measurement_moves_later_entries_until_fit(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer", experience=_experience_entries(6))
    monkeypatch.setattr(professional_compact, "build_html", lambda view: str(len(view.detailed_experience)))

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1", "Role 2", "Role 3"]
    assert [entry.title for entry in prepared.compact_experience] == ["Role 4", "Role 5", "Role 6"]
    assert prepared.allowed_physical_pages == 3
    assert prepared.measured_pages_final == 3
    assert len(prepared.planning_attempts) >= 3
    assert prepared.planning_attempts[-1]["fit"] is True


def test_prepare_with_measurement_returns_tightest_candidate_with_one_detailed_when_none_fit(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer", experience=_experience_entries(3))
    monkeypatch.setattr(professional_compact, "build_html", lambda _view: "10")

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1"]
    assert [entry.title for entry in prepared.compact_experience] == ["Role 2", "Role 3"]


def test_prepare_with_measurement_hard_cap_applies_as_initial_detailed_count(monkeypatch) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=_experience_entries(5),
        render_options={"compact_max_detailed_experience": 2},
    )
    calls = {"measure": 0}
    monkeypatch.setattr(professional_compact, "build_html", lambda _view: "unused")

    def _measure(_html: str) -> int:
        calls["measure"] += 1
        return 2

    prepared = professional_compact.prepare_with_measurement(model, _measure)

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1", "Role 2"]
    assert [entry.title for entry in prepared.compact_experience] == ["Role 3", "Role 4", "Role 5"]
    assert calls["measure"] == 1


def test_prepare_with_measurement_honors_max_resume_pages_option(monkeypatch) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=_experience_entries(5),
        render_options={"max_resume_pages": 3},
    )
    monkeypatch.setattr(professional_compact, "build_html", lambda view: str(len(view.detailed_experience)))

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1", "Role 2", "Role 3"]
    assert [entry.title for entry in prepared.compact_experience] == ["Role 4", "Role 5"]
    assert prepared.page_target == 3.0


def test_prepare_with_measurement_defaults_to_two_point_five_pages(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer", experience=_experience_entries(2))
    monkeypatch.setattr(professional_compact, "build_html", lambda view: str(len(view.detailed_experience)))

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert prepared.page_target == 2.5


def test_prepare_with_measurement_keeps_at_least_one_detailed_experience_entry(monkeypatch) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=_experience_entries(3),
        render_options={"max_resume_pages": 1},
    )
    monkeypatch.setattr(professional_compact, "build_html", lambda _view: "10")

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert len(prepared.detailed_experience) == 1
    assert [entry.title for entry in prepared.compact_experience] == ["Role 2", "Role 3"]


def test_prepare_with_measurement_max_resume_pages_two_allows_two_physical_pages(monkeypatch) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=_experience_entries(4),
        render_options={"max_resume_pages": 2},
    )
    monkeypatch.setattr(professional_compact, "build_html", lambda view: str(len(view.detailed_experience)))

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert len(prepared.detailed_experience) == 2


def test_prepare_with_measurement_max_resume_pages_2_001_allows_three_physical_pages(monkeypatch) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=_experience_entries(4),
        render_options={"max_resume_pages": 2.001},
    )
    monkeypatch.setattr(professional_compact, "build_html", lambda view: str(len(view.detailed_experience)))

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert len(prepared.detailed_experience) == 3


def test_prepare_with_measurement_max_resume_pages_2_5_allows_three_physical_pages(monkeypatch) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=_experience_entries(4),
        render_options={"max_resume_pages": 2.5},
    )
    monkeypatch.setattr(professional_compact, "build_html", lambda view: str(len(view.detailed_experience)))

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert len(prepared.detailed_experience) == 3


def test_prepare_with_measurement_max_resume_pages_three_allows_three_physical_pages(monkeypatch) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=_experience_entries(4),
        render_options={"max_resume_pages": 3},
    )
    monkeypatch.setattr(professional_compact, "build_html", lambda view: str(len(view.detailed_experience)))

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert len(prepared.detailed_experience) == 3


def test_professional_compact_build_html_renders_selected_experience() -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[
            ResumeEntry(
                title="Engineer at Example Co",
                subtitle="2017 - 2019",
                bullets=["Built API gateway", "Reduced incident MTTR"],
                compact_summary="Built and stabilized backend APIs.",
            )
        ],
        projects_to_render=[],
        page_target=2.0,
    )

    html = professional_compact.build_html(view)

    assert "Earlier Experience (Selected)" in html
    assert "Engineer at Example Co" in html
    assert "Built and stabilized backend APIs." in html


def test_professional_compact_build_html_renders_polished_header_and_sections() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        location="Denver, CO",
        contact="alex@example.com | 555-111-2222 | github.com/alex",
        summary="Built and shipped reliable systems.",
        education="State University | BS Computer Science | 2018",
        certifications="AWS Certified Developer | Amazon | 2023",
    )
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
    )

    html = professional_compact.build_html(view)

    assert '<h1 class="name">Alex Example</h1>' in html
    assert "Denver, CO • 555-111-2222 • alex@example.com" in html
    assert "github.com/alex" in html
    assert '<h2 class="section-title">Summary</h2>' in html
    assert '<h2 class="section-title">Education</h2>' in html
    assert '<h2 class="section-title">Certifications</h2>' in html
    assert '<div class="title">' not in html


def test_professional_compact_build_html_preserves_parenthetical_skill_groups() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[
            SkillSection(category="Cloud", value="AWS (EC2, S3, Lambda), PostgreSQL (RDS), Java"),
        ],
    )
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
    )

    html = professional_compact.build_html(view)

    assert "AWS (EC2, S3, Lambda)" in html
    assert "PostgreSQL (RDS)" in html


def test_professional_compact_header_omits_country_suffix_by_default() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        location="Aurora, CO, US",
        contact="alex@example.com | 303-521-3115 | https://github.com/haxwell",
    )
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
    )

    html = professional_compact.build_html(view)

    assert "Aurora, CO • 303-521-3115 • alex@example.com" in html
    assert "Aurora, CO, US" not in html
    assert "github.com/haxwell" in html


def test_professional_compact_header_keeps_country_when_explicitly_enabled() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        location="Aurora, CO, US",
        contact="alex@example.com | 303-521-3115",
        render_options={"include_country_in_location": True},
    )
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
    )

    html = professional_compact.build_html(view)

    assert "Aurora, CO, US • 303-521-3115 • alex@example.com" in html


def test_professional_compact_build_html_renders_detailed_and_compact_experience_content() -> None:
    model = ResumeRenderModel(name="Alex Example", contact="alex@example.com")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[
            ResumeEntry(
                title="Senior Software Engineer",
                subtitle="Scale AI | Nov 2024 - Present | Remote",
                bullets=["Led backend architecture improvements."],
            )
        ],
        compact_experience=[
            ResumeEntry(
                title="Software Engineer",
                subtitle="Example Corp | 2021 - 2023",
                bullets=["Built APIs", "Reduced MTTR"],
                compact_summary="Built API services and improved production reliability.",
            )
        ],
        projects_to_render=[],
    )

    html = professional_compact.build_html(view)

    assert "Scale AI - Senior Software Engineer" in html
    assert "Nov 2024 - Present | Remote" in html
    assert "Led backend architecture improvements." in html
    assert "Earlier Experience (Selected)" in html
    assert "Example Corp - Software Engineer" in html
    assert "2021 - 2023" in html
    assert "Built API services and improved production reliability." in html


def test_professional_compact_formats_experience_dates_as_month_year() -> None:
    model = ResumeRenderModel(name="Alex Example", contact="alex@example.com")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[
            ResumeEntry(
                title="Senior Software Engineer",
                subtitle="Scale AI | 2025-08 - 2026-03 | Remote",
                bullets=["Led backend architecture improvements."],
            )
        ],
        compact_experience=[],
        projects_to_render=[],
    )

    html = professional_compact.build_html(view)

    assert "Aug 2025 - Mar 2026 | Remote" in html
    assert "2025-08 - 2026-03" not in html


def test_professional_compact_build_html_renders_projects_in_experience_style() -> None:
    model = ResumeRenderModel(name="Alex Example", contact="alex@example.com")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[
            ResumeEntry(
                title="TribeApp Platform",
                subtitle="Personal Project | 2023 - 2024",
                bullets=["Designed backend service APIs."],
            )
        ],
    )

    html = professional_compact.build_html(view)

    assert '<h2 class="section-title">Projects</h2>' in html
    assert "TribeApp Platform" in html
    assert 'class="project-title-row"' in html
    assert "2023 - 2024" in html
    assert "Designed backend service APIs." in html


def test_scale_ai_three_page_planning_matches_current_behavior(monkeypatch) -> None:
    model = _load_scale_ai_case()
    model.render_options = {"max_resume_pages": 3}

    def _fake_build_html(view: professional_compact.ProfessionalCompactTemplateView) -> str:
        return str(len(view.detailed_experience))

    def _fake_measure(html: str) -> int:
        detailed_count = int(html)
        if detailed_count >= 8:
            return 4
        if detailed_count >= 7:
            return 3
        return 2

    monkeypatch.setattr(professional_compact, "build_html", _fake_build_html)
    prepared = professional_compact.prepare_with_measurement(model, _fake_measure)

    assert prepared.allowed_physical_pages == 3
    assert prepared.measured_pages_final == 3
    assert len(prepared.detailed_experience) == 7
    assert len(prepared.compact_experience) == 4
    assert isinstance(prepared.planning_attempts, list)
    assert prepared.planning_attempts[-1] == {
        "detailed_experience_count": 7,
        "measured_page_count": 3,
        "fit": True,
    }


def test_scale_ai_two_page_planning_exposes_current_over_collapse_and_large_projects(monkeypatch) -> None:
    model = _load_scale_ai_case()
    model.render_options = {"max_resume_pages": 2}

    def _fake_build_html(view: professional_compact.ProfessionalCompactTemplateView) -> str:
        return str(len(view.detailed_experience))

    def _fake_measure(html: str) -> int:
        detailed_count = int(html)
        if detailed_count >= 3:
            return 3
        return 2

    monkeypatch.setattr(professional_compact, "build_html", _fake_build_html)
    prepared = professional_compact.prepare_with_measurement(model, _fake_measure)

    assert prepared.allowed_physical_pages == 2
    assert prepared.measured_pages_final == 2
    assert len(prepared.detailed_experience) == 2
    assert len(prepared.compact_experience) == 9
    # Current planner only compacts experience; projects remain unchanged.
    assert len(prepared.projects_to_render) == 2
    assert len(prepared.projects_to_render[0].bullets) == 5
    assert len(prepared.projects_to_render[1].bullets) == 5


def test_professional_compact_supports_summary_modes() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        summary="First sentence. Second sentence. Third sentence.",
    )
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
        summary_mode="micro",
    )
    html = professional_compact.build_html(view)
    assert "First sentence." in html
    assert "Second sentence." not in html


def test_professional_compact_supports_skills_modes() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[
            SkillSection(category="Backend", value="Java, Spring Boot, REST, Kafka, PostgreSQL, MySQL"),
            SkillSection(category="Cloud", value="AWS, Docker, Kubernetes, Terraform, Linux, GitHub Actions"),
        ],
    )
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
        skills_mode="minimal",
    )
    html = professional_compact.build_html(view)
    assert html.count('class="skill-line"') == 1


def test_professional_compact_selected_skills_default_max_lines_is_two() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[
            SkillSection(category="Backend", value="Java, Spring Boot, REST, Kafka, PostgreSQL, MySQL"),
            SkillSection(category="Cloud", value="AWS, Docker, Kubernetes, Terraform, Linux, GitHub Actions"),
            SkillSection(category="Delivery", value="CI/CD, Git, Monitoring, SRE, Incident Response, Testing"),
        ],
    )
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
        skills_mode="selected",
    )

    html = professional_compact.build_html(view)
    assert html.count('class="skill-line"') == 2


def test_professional_compact_selected_skills_expansion_uses_next_retained_skill_lines() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[
            SkillSection(category="Core", value="Skill1, Skill2, Skill3, Skill4, Skill5, Skill6"),
            SkillSection(category="Next", value="Skill7, Skill8, Skill9, Skill10, Skill11, Skill12"),
            SkillSection(category="Later", value="Skill13, Skill14, Skill15, Skill16, Skill17, Skill18"),
        ],
    )
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
        skills_mode="selected",
        selected_skills_max_lines=3,
    )

    html = professional_compact.build_html(view)
    assert "Skill1 • Skill2 • Skill3 • Skill4 • Skill5 • Skill6" in html
    assert "Skill7 • Skill8 • Skill9 • Skill10 • Skill11 • Skill12" in html
    assert "Skill13 • Skill14 • Skill15 • Skill16 • Skill17 • Skill18" in html


def test_professional_compact_supports_experience_modes() -> None:
    model = ResumeRenderModel(name="Alex Example")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[
            ResumeEntry(title="Staff Engineer", subtitle="Scale AI | 2024 - Present", bullets=["Built services", "Reduced MTTR"])
        ],
        compact_experience=[],
        projects_to_render=[],
        experience_mode="compact",
    )
    html = professional_compact.build_html(view)
    assert "Earlier Experience (Selected)" not in html
    assert "Built services Reduced MTTR" in html
    assert '<ul class="entry-bullets">' not in html


def test_professional_compact_grouped_earlier_experience_uses_compact_summaries() -> None:
    model = ResumeRenderModel(name="Alex Example")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[
            ResumeEntry(company="Alpha Corp", title="Engineer", compact_summary="Built event-driven APIs."),
            ResumeEntry(company="Beta Labs", title="Engineer", compact_summary="Reduced production incidents."),
            ResumeEntry(company="Gamma Co", title="Engineer", compact_summary="Improved deployment reliability."),
        ],
        projects_to_render=[],
        earlier_experience_mode="grouped",
    )

    html = professional_compact.build_html(view)
    assert "Alpha Corp / Beta Labs - Built event-driven APIs; Reduced production incidents." in html
    assert "Gamma Co - Improved deployment reliability." in html
    assert ".;" not in html
    assert "202" not in html


def test_professional_compact_supports_projects_modes() -> None:
    model = ResumeRenderModel(name="Alex Example")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[
            ResumeEntry(title="Project 1", subtitle="Backend | 2024", bullets=["Bullet 1"], compact_summary="Summary 1"),
            ResumeEntry(title="Project 2", subtitle="Backend | 2023", bullets=["Bullet 2"], compact_summary="Summary 2"),
            ResumeEntry(title="Project 3", subtitle="Backend | 2022", bullets=["Bullet 3"], compact_summary="Summary 3"),
        ],
        projects_mode="selected",
    )
    html = professional_compact.build_html(view)
    assert "Project 1" in html
    assert "Project 2" in html
    assert "Project 3" not in html


def test_professional_compact_supports_education_and_certification_modes() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        education="School | CS | 2010",
        certifications="Cert One\nCert Two\nCert Three\nCert Four",
    )
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
        education_mode="compact",
        certifications_mode="selected",
    )
    html = professional_compact.build_html(view)
    assert "School • CS • 2010" in html
    assert "Cert One" in html
    assert "Cert Three" in html
    assert "Cert Four" not in html


def _fake_state_html(view: professional_compact.ProfessionalCompactTemplateView) -> str:
    return (
        f"projects={view.projects_mode};skills={view.skills_mode};summary={view.summary_mode};"
        f"earlier={view.earlier_experience_mode};cap={view.detailed_bullet_cap if view.detailed_bullet_cap is not None else 5};"
        f"certs={view.certifications_mode};selected_lines={view.selected_skills_max_lines};"
        f"min_protected={view.min_protected_detailed_roles if view.min_protected_detailed_roles is not None else 0};"
        f"detailed={len(view.detailed_experience)}"
    )


def _parse_state_html(html: str) -> dict[str, str]:
    pairs = [token.split("=", 1) for token in html.split(";") if "=" in token]
    return {k: v for k, v in pairs}


def test_prepare_with_measurement_no_compaction_when_initial_render_fits(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", experience=_experience_entries(4))
    model.render_options = {"max_resume_pages": 3}
    monkeypatch.setattr(professional_compact, "build_html", _fake_state_html)

    prepared = professional_compact.prepare_with_measurement(model, lambda _html: 2)

    assert prepared.measured_pages_final == 2
    assert prepared.planning_operations == []
    assert prepared.selected_skills_max_lines == 2


def test_prepare_with_measurement_expanded_selected_skills_reverts_when_not_fit(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", experience=_experience_entries(4))
    model.render_options = {"max_resume_pages": 2}
    monkeypatch.setattr(professional_compact, "build_html", _fake_state_html)

    def _measure(html: str) -> int:
        state = _parse_state_html(html)
        if state["skills"] == "full":
            return 3
        if int(state["selected_lines"]) == 3:
            return 3
        return 2

    prepared = professional_compact.prepare_with_measurement(model, _measure)
    expansion_ops = [op for op in prepared.planning_operations if op["step"] == "selected_skills_max_lines"]
    assert expansion_ops
    assert expansion_ops[-1]["kept"] is False
    assert prepared.selected_skills_max_lines == 2


def test_prepare_with_measurement_applies_projects_before_skills_and_detailed_count(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", experience=_experience_entries(5))
    model.render_options = {"max_resume_pages": 2}
    monkeypatch.setattr(professional_compact, "build_html", _fake_state_html)

    def _measure(html: str) -> int:
        state = _parse_state_html(html)
        if state["projects"] == "hidden" and state["skills"] == "minimal" and int(state["detailed"]) <= 2:
            return 2
        return 3

    prepared = professional_compact.prepare_with_measurement(model, _measure)
    steps = [op["step"] for op in prepared.planning_operations]

    assert steps[0:3] == ["projects_mode", "projects_mode", "projects_mode"]
    assert steps.index("skills_mode") > 2
    assert steps.index("detailed_experience_count") > steps.index("skills_mode")


def test_prepare_with_measurement_reduces_to_floor_before_skills_minimal_for_two_pages(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", experience=_experience_entries(10))
    model.render_options = {"max_resume_pages": 2}
    monkeypatch.setattr(professional_compact, "build_html", _fake_state_html)

    def _measure(html: str) -> int:
        state = _parse_state_html(html)
        detailed = int(state["detailed"])
        skills = state["skills"]
        if skills == "selected" and detailed <= 6:
            return 3
        if skills == "minimal" and detailed <= 6:
            return 2
        return 4

    prepared = professional_compact.prepare_with_measurement(model, _measure)
    ops = prepared.planning_operations
    steps = [op["step"] for op in ops]
    first_skills_minimal_idx = next(
        idx for idx, op in enumerate(ops) if op["step"] == "skills_mode" and op["from"] == "selected" and op["to"] == "minimal"
    )
    reduction_steps_before_minimal = [
        op for op in ops[:first_skills_minimal_idx] if op["step"] == "detailed_experience_count"
    ]

    assert "skills_mode" in steps
    assert reduction_steps_before_minimal
    assert reduction_steps_before_minimal[-1]["to"] == 6


def test_prepare_with_measurement_can_reallocate_detailed_role_for_skills_expansion_above_floor(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", experience=_experience_entries(7))
    model.render_options = {"max_resume_pages": 2}
    monkeypatch.setattr(professional_compact, "build_html", _fake_state_html)

    def _measure(html: str) -> int:
        state = _parse_state_html(html)
        detailed = int(state["detailed"])
        skills = state["skills"]
        selected_lines = int(state["selected_lines"])
        if skills == "full":
            return 3
        if selected_lines == 2 and detailed == 7:
            return 2
        if selected_lines == 3 and detailed == 7:
            return 3
        if selected_lines == 3 and detailed == 6:
            return 2
        return 2

    prepared = professional_compact.prepare_with_measurement(model, _measure)
    assert prepared.selected_skills_max_lines == 3
    assert len(prepared.detailed_experience) == 6
    reallocation_ops = [
        op
        for op in prepared.planning_operations
        if op["step"] == "detailed_experience_count"
        and op.get("reason") == "post_fit_reallocation_for_selected_skills_expansion"
    ]
    assert reallocation_ops
    assert reallocation_ops[-1]["kept"] is True


def test_prepare_with_measurement_post_fit_reallocation_respects_protected_floor(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", experience=_experience_entries(6))
    model.render_options = {"max_resume_pages": 2}
    monkeypatch.setattr(professional_compact, "build_html", _fake_state_html)

    def _measure(html: str) -> int:
        state = _parse_state_html(html)
        if int(state["selected_lines"]) == 3:
            return 3
        return 2

    prepared = professional_compact.prepare_with_measurement(model, _measure)
    assert prepared.min_protected_detailed_roles == 5
    # Starting at 6 detailed roles, post-fit reallocation can at most move to 5; it should not go below 5.
    assert len(prepared.detailed_experience) >= 5
    assert not any(
        op["step"] == "detailed_experience_count"
        and op.get("reason") == "post_fit_reallocation_for_selected_skills_expansion"
        and int(op["to"]) < 5
        for op in prepared.planning_operations
    )


def test_prepare_with_measurement_records_operation_measurement_and_stops_on_fit(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", experience=_experience_entries(5))
    model.render_options = {"max_resume_pages": 2}
    monkeypatch.setattr(professional_compact, "build_html", _fake_state_html)

    def _measure(html: str) -> int:
        state = _parse_state_html(html)
        if state["projects"] == "selected":
            return 2
        return 3

    prepared = professional_compact.prepare_with_measurement(model, _measure)
    ops = prepared.planning_operations

    assert len(ops) == 2
    assert [op["step"] for op in ops] == ["projects_mode", "projects_mode"]
    assert all("measured_pages" in op and "fit" in op for op in ops)
    assert ops[-1]["fit"] is True


def test_prepare_with_measurement_records_bullet_cap_transition(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", experience=_experience_entries(4))
    model.render_options = {"max_resume_pages": 2}
    monkeypatch.setattr(professional_compact, "build_html", _fake_state_html)

    def _measure(html: str) -> int:
        state = _parse_state_html(html)
        if int(state["cap"]) <= 4:
            return 2
        return 3

    prepared = professional_compact.prepare_with_measurement(model, _measure)

    bullet_ops = [op for op in prepared.planning_operations if op["step"] == "detailed_bullet_cap"]
    assert bullet_ops
    assert bullet_ops[0]["from"] == 5
    assert bullet_ops[0]["to"] == 4
    assert prepared.detailed_bullet_cap == 4


def test_prepare_with_measurement_records_certs_selected_to_hidden_when_required(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", experience=_experience_entries(10))
    model.render_options = {"max_resume_pages": 2}
    monkeypatch.setattr(professional_compact, "build_html", _fake_state_html)

    def _measure(html: str) -> int:
        state = _parse_state_html(html)
        if state["certs"] == "hidden" and state["skills"] == "minimal" and int(state["detailed"]) <= 6:
            return 2
        return 3

    prepared = professional_compact.prepare_with_measurement(model, _measure)
    cert_ops = [
        op
        for op in prepared.planning_operations
        if op["step"] == "certifications_mode" and op["from"] == "selected" and op["to"] == "hidden"
    ]
    assert cert_ops
    assert cert_ops[-1]["fit"] is True


def test_professional_compact_bullet_cap_drops_later_role_bullets_preserving_earlier_role() -> None:
    role_one = ResumeEntry(
        title="Role 1",
        subtitle="Company 1 | 2024",
        bullets=["R1-B1", "R1-B2", "R1-B3", "R1-B4", "R1-B5", "R1-B6"],
    )
    role_two = ResumeEntry(
        title="Role 2",
        subtitle="Company 2 | 2023",
        bullets=["R2-B1", "R2-B2", "R2-B3", "R2-B4", "R2-B5", "R2-B6"],
    )
    view = professional_compact.ProfessionalCompactTemplateView(
        model=ResumeRenderModel(name="Alex Example"),
        detailed_experience=[role_one, role_two],
        compact_experience=[],
        projects_to_render=[],
        detailed_bullet_cap=4,
    )

    html = professional_compact.build_html(view)
    role_one_match = re.search(r"Role 1.*?</article>", html, flags=re.DOTALL)
    role_two_match = re.search(r"Role 2.*?</article>", html, flags=re.DOTALL)

    assert role_one_match and "R1-B6" in role_one_match.group(0)
    assert role_two_match and "R2-B4" in role_two_match.group(0)
    assert role_two_match and "R2-B5" not in role_two_match.group(0)


def test_professional_compact_projects_use_summary_only_when_no_bullets() -> None:
    model = ResumeRenderModel(name="Alex Example", contact="alex@example.com")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[
            ResumeEntry(
                title="TribeApp Platform",
                start_date="2022-10",
                end_date="2024-02",
                bullets=[],
                metadata={"description": "Backend-driven mobile platform"},
            )
        ],
    )

    html = professional_compact.build_html(view)

    assert "Backend-driven mobile platform" in html
    assert "<ul class=\"entry-bullets\">" not in html


def test_professional_compact_certifications_selected_constrained_to_one_line() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        certifications="AWS Cloud Cert\nOracle Java SE 17 Cert\nSome Other Cert",
        skills=[SkillSection(category="Backend", value="Java, Spring Boot, AWS")],
    )
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
        certifications_mode="selected",
        skills_mode="selected",
        allowed_physical_pages=2,
    )

    html = professional_compact.build_html(view)

    assert "Oracle Java SE 17 Cert" in html
    assert "AWS Cloud Cert" not in html
    assert "Some Other Cert" not in html


def test_professional_compact_certifications_hidden_omits_section() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        certifications="AWS Cloud Cert\nOracle Java SE 17 Cert",
    )
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
        certifications_mode="hidden",
    )

    html = professional_compact.build_html(view)

    assert "Certifications" not in html


def test_professional_compact_projects_hide_summary_when_bullets_present() -> None:
    model = ResumeRenderModel(name="Alex Example", contact="alex@example.com")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[
            ResumeEntry(
                title="TribeApp Platform",
                start_date="2022-10",
                end_date="2024-02",
                bullets=["Designed backend service APIs."],
                metadata={"description": "Backend-driven mobile platform"},
            )
        ],
    )

    html = professional_compact.build_html(view)

    assert "Designed backend service APIs." in html
    assert "Backend-driven mobile platform" not in html


def test_professional_compact_earlier_experience_strips_contract_from_heading() -> None:
    model = ResumeRenderModel(name="Alex Example", contact="alex@example.com")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[
            ResumeEntry(
                title="Software Engineer (Contract)",
                company="Charles Schwab",
                role="Software Engineer (Contract)",
                is_contract=True,
                start_date="2025-08",
                end_date="2026-03",
                location="Denver, CO",
                bullets=["Built backend services."],
            )
        ],
        projects_to_render=[],
    )

    html = professional_compact.build_html(view)

    assert "Charles Schwab - Software Engineer" in html
    assert "Software Engineer (Contract)" not in html
    assert "Aug 2025 - Mar 2026 | Denver, CO | Contract" in html


def test_professional_compact_selected_experience_subtitle_fallback_formats_dates() -> None:
    model = ResumeRenderModel(name="Alex Example")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[
            ResumeEntry(
                title="Software Engineer",
                subtitle="Example Corp | 2025-08 - 2026-03 | Remote",
                bullets=[],
            )
        ],
        projects_to_render=[],
    )

    html = professional_compact.build_html(view)

    assert "Aug 2025 - Mar 2026" in html
    assert "2025-08 - 2026-03" not in html


def test_professional_compact_formats_structured_dates_and_present() -> None:
    model = ResumeRenderModel(name="Alex Example", contact="alex@example.com")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[
            ResumeEntry(
                title="Software Engineer",
                company="Charles Schwab",
                role="Software Engineer",
                start_date="2025-08",
                end_date=None or "",
                location="Denver, CO",
                bullets=["Built backend services."],
            )
        ],
        compact_experience=[],
        projects_to_render=[],
    )

    html = professional_compact.build_html(view)

    assert "Charles Schwab - Software Engineer" in html
    assert "Aug 2025 - Present | Denver, CO" in html


def test_professional_compact_project_structured_dates_render_month_year() -> None:
    model = ResumeRenderModel(name="Alex Example", contact="alex@example.com")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[
            ResumeEntry(
                title="TribeApp",
                start_date="2022-10",
                end_date="2024-02",
                technologies=["Spring Boot", "MySQL"],
                bullets=["Built product features."],
                metadata={"description": "Backend-driven mobile platform"},
            )
        ],
    )

    html = professional_compact.build_html(view)

    assert "Oct 2022 - Feb 2024" in html


def test_professional_compact_detailed_entries_can_flow_across_pages() -> None:
    model = ResumeRenderModel(name="Alex Example", contact="alex@example.com")
    view = professional_compact.ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=[ResumeEntry(title="Role", subtitle="Company | 2024 - Present", bullets=["Bullet"])],
        compact_experience=[ResumeEntry(title="Older Role", subtitle="Company | 2020 - 2024", bullets=["Bullet"])],
        projects_to_render=[],
    )

    html = professional_compact.build_html(view)

    assert ".entry {" in html
    assert "break-inside: avoid;" not in html.split(".entry {", 1)[1].split("}", 1)[0]
    assert ".compact-entry {" in html
    assert "break-inside: avoid;" in html.split(".compact-entry {", 1)[1].split("}", 1)[0]
