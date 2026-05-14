from __future__ import annotations

from pathlib import Path

from applypilot.scoring.pdf import convert_to_pdf


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

    html_path = convert_to_pdf(source, html_only=True)
    html = html_path.read_text(encoding="utf-8")

    assert "Summary" in html
    assert "Technical Skills" in html
    assert "Experience" in html
    assert "Education" in html
