from __future__ import annotations

from applypilot.scoring.pdf_render_model import ResumeEntry, ResumeRenderModel
from applypilot.scoring.pdf_templates import professional_compact


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
        render_options={"page_target": 4},
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
    assert len(prepared.planning_attempts) == 4
    assert prepared.planning_attempts[-1]["fit"] is True


def test_prepare_with_measurement_returns_tightest_candidate_with_one_detailed_when_none_fit(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer", experience=_experience_entries(3))
    monkeypatch.setattr(professional_compact, "build_html", lambda _view: "10")

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1"]
    assert [entry.title for entry in prepared.compact_experience] == ["Role 2", "Role 3"]


def test_prepare_with_measurement_hard_cap_skips_measurement_loop(monkeypatch) -> None:
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
        return 99

    prepared = professional_compact.prepare_with_measurement(model, _measure)

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1", "Role 2"]
    assert [entry.title for entry in prepared.compact_experience] == ["Role 3", "Role 4", "Role 5"]
    assert calls["measure"] == 0


def test_prepare_with_measurement_honors_page_target_option(monkeypatch) -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        title="Senior Engineer",
        experience=_experience_entries(5),
        render_options={"page_target": 3},
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
        render_options={"page_target": 1},
    )
    monkeypatch.setattr(professional_compact, "build_html", lambda _view: "10")

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert len(prepared.detailed_experience) == 1
    assert [entry.title for entry in prepared.compact_experience] == ["Role 2", "Role 3"]


def test_prepare_with_measurement_page_target_two_allows_two_physical_pages(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer", experience=_experience_entries(4), render_options={"page_target": 2})
    monkeypatch.setattr(professional_compact, "build_html", lambda view: str(len(view.detailed_experience)))

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert len(prepared.detailed_experience) == 2


def test_prepare_with_measurement_page_target_2_001_allows_three_physical_pages(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer", experience=_experience_entries(4), render_options={"page_target": 2.001})
    monkeypatch.setattr(professional_compact, "build_html", lambda view: str(len(view.detailed_experience)))

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert len(prepared.detailed_experience) == 3


def test_prepare_with_measurement_page_target_2_5_allows_three_physical_pages(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer", experience=_experience_entries(4), render_options={"page_target": 2.5})
    monkeypatch.setattr(professional_compact, "build_html", lambda view: str(len(view.detailed_experience)))

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert len(prepared.detailed_experience) == 3


def test_prepare_with_measurement_page_target_three_allows_three_physical_pages(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer", experience=_experience_entries(4), render_options={"page_target": 3})
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
    assert '<div class="title">' not in html


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
