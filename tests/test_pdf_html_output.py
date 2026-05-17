from __future__ import annotations

from pathlib import Path

from applypilot.scoring.pdf import build_html_for_resume, convert_to_pdf, render_model_to_pdf, render_model_to_pdf_with_planning
from applypilot.scoring.pdf_render_model import (
    ResumeEntry,
    ResumeRenderModel,
    SkillSection,
    build_render_model_from_tailored_json,
)
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
