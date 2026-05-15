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


def test_prepare_with_measurement_returns_tightest_candidate_when_none_fit(monkeypatch) -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer", experience=_experience_entries(3))
    monkeypatch.setattr(professional_compact, "build_html", lambda _view: "10")

    prepared = professional_compact.prepare_with_measurement(model, lambda html: int(html))

    assert prepared.detailed_experience == []
    assert [entry.title for entry in prepared.compact_experience] == ["Role 1", "Role 2", "Role 3"]


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
