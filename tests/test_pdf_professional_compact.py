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

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1", "Role 2"]
    assert [entry.title for entry in prepared.compact_experience] == ["Role 3", "Role 4", "Role 5", "Role 6"]


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

    assert "Selected Experience" in html
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
    assert "Selected Experience" in html
    assert "Example Corp - Software Engineer" in html
    assert "2021 - 2023" in html
    assert "Built API services and improved production reliability." in html


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
    assert "Personal Project" in html
    assert "Designed backend service APIs." in html
