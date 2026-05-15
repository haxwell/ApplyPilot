from __future__ import annotations

from applypilot.scoring.pdf import build_render_model, parse_resume
from applypilot.scoring.pdf_render_model import build_render_model_from_tailored_json
from applypilot.scoring.pdf_templates import default as default_template


def _sample_resume_text() -> str:
    return "\n".join(
        [
            "Alex Example",
            "Senior Engineer",
            "Denver, CO",
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
            "- Improved delivery reliability",
            "",
            "PROJECTS",
            "Side Project",
            "Python | 2024",
            "- Built a tool",
            "",
            "EDUCATION",
            "State University | BS Computer Science | 2018",
        ]
    )


def test_parse_resume_extracts_header_and_sections() -> None:
    parsed = parse_resume(_sample_resume_text())

    assert parsed["name"] == "Alex Example"
    assert parsed["title"] == "Senior Engineer"
    assert parsed["location"] == "Denver, CO"
    assert parsed["contact"] == "alex@example.com | 555-111-2222"
    assert "SUMMARY" in parsed["sections"]
    assert "TECHNICAL SKILLS" in parsed["sections"]
    assert "EXPERIENCE" in parsed["sections"]
    assert "PROJECTS" in parsed["sections"]
    assert "EDUCATION" in parsed["sections"]


def test_build_render_model_maps_expected_fields() -> None:
    parsed = parse_resume(_sample_resume_text())
    model = build_render_model(parsed)

    assert model.name == "Alex Example"
    assert model.title == "Senior Engineer"
    assert model.location == "Denver, CO"
    assert model.contact == "alex@example.com | 555-111-2222"
    assert model.summary == "Built and shipped reliable systems."
    assert len(model.skills) == 2
    assert model.skills[0].category == "Languages"
    assert model.skills[0].value == "Python, Java"
    assert len(model.experience) == 1
    assert model.experience[0].title == "Senior Engineer"
    assert model.experience[0].subtitle == "Example Corp | 2022-01 - Present"
    assert model.experience[0].bullets == ["Built APIs", "Improved delivery reliability"]
    assert len(model.projects) == 1
    assert model.projects[0].title == "Side Project"
    assert model.education == "State University | BS Computer Science | 2018"


def test_default_prepare_is_noop_equivalent() -> None:
    parsed = parse_resume(_sample_resume_text())
    model = build_render_model(parsed)

    prepared = default_template.prepare(model)

    assert prepared == model


def test_build_render_model_from_tailored_json_maps_profile_and_sections() -> None:
    profile = {
        "personal": {
            "full_name": "Alex Example",
            "email": "alex@example.com",
            "phone": "555-111-2222",
            "location": "Denver, CO",
        }
    }
    data = {
        "title": "Senior Engineer",
        "summary": "Built and shipped reliable systems.",
        "skills": {"Languages": "Python, Java", "Backend": "APIs"},
        "experience": [
            {
                "header": "Senior Engineer",
                "subtitle": "Example Corp | 2022-01 - Present",
                "bullets": ["Built APIs", {"text": "Improved delivery reliability"}],
            }
        ],
        "projects": [
            {
                "header": "Side Project",
                "subtitle": "Python | 2024",
                "bullets": [{"value": "Built a tool"}],
            }
        ],
        "education": "State University | BS Computer Science | 2018",
    }

    model = build_render_model_from_tailored_json(data, profile)

    assert model.name == "Alex Example"
    assert model.title == "Senior Engineer"
    assert model.location == "Denver, CO"
    assert model.contact == "alex@example.com | 555-111-2222"
    assert model.summary == "Built and shipped reliable systems."
    assert len(model.skills) == 2
    assert model.skills[0].category == "Languages"
    assert model.skills[0].value == "Python, Java"
    assert len(model.experience) == 1
    assert model.experience[0].title == "Senior Engineer"
    assert model.experience[0].bullets == ["Built APIs", "Improved delivery reliability"]
    assert len(model.projects) == 1
    assert model.projects[0].bullets == ["Built a tool"]
    assert model.education == "State University | BS Computer Science | 2018"
