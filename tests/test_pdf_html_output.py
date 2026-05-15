from __future__ import annotations

from pathlib import Path

from applypilot.scoring.pdf import convert_to_pdf, render_model_to_pdf
from applypilot.scoring.pdf_render_model import ResumeEntry, ResumeRenderModel, SkillSection


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

    html_path = convert_to_pdf(source, html_only=True, template_name="default")
    html = html_path.read_text(encoding="utf-8")

    assert "Summary" in html
    assert "Technical Skills" in html
    assert "Experience" in html
    assert "Education" in html


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


def test_compact_html_differs_from_default_html(tmp_path: Path) -> None:
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

    default_html_path = convert_to_pdf(source, html_only=True, output_path=tmp_path / "default.html", template_name="default")
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
            )
        ],
        education="State University | BS Computer Science | 2018",
    )

    html_path = render_model_to_pdf(
        model,
        output_path=tmp_path / "model.html",
        template_name="default",
        html_only=True,
    )
    html = html_path.read_text(encoding="utf-8")

    assert "Alex Example" in html
    assert "Built and shipped reliable systems." in html
    assert "Built APIs" in html
