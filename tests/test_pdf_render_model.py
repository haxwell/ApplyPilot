from __future__ import annotations

from applypilot.scoring.pdf import build_render_model, parse_resume
from applypilot.scoring.pdf_render_model import ResumeEntry, build_render_model_from_tailored_json
from applypilot.scoring.pdf_templates import classic as classic_template
from applypilot.scoring.pdf_templates import compact as compact_template
from applypilot.scoring.pdf_templates import default as default_template
from applypilot.scoring.pdf_templates import professional_compact as professional_compact_template


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


def test_classic_prepare_is_noop_equivalent() -> None:
    parsed = parse_resume(_sample_resume_text())
    model = build_render_model(parsed)

    prepared = classic_template.prepare(model)

    assert prepared == model


def test_default_alias_points_to_production_template() -> None:
    parsed = parse_resume(_sample_resume_text())
    model = build_render_model(parsed)

    default_prepared = default_template.prepare(model)
    prod_prepared = professional_compact_template.prepare(model)

    assert default_template.build_html(default_prepared) == professional_compact_template.build_html(prod_prepared)


def test_build_render_model_from_tailored_json_maps_profile_and_sections() -> None:
    profile = {
        "personal": {
            "full_name": "Alex Example",
            "email": "alex@example.com",
            "phone": "555-111-2222",
            "city": "Denver",
            "province_state": "CO",
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


def test_resume_entry_supports_compact_summary() -> None:
    entry = ResumeEntry(
        title="Senior Engineer",
        subtitle="Example Corp | 2022-01 - Present",
        bullets=["Built APIs"],
        compact_summary="Led backend reliability improvements.",
    )

    assert entry.compact_summary == "Led backend reliability improvements."


def test_build_render_model_from_tailored_json_location_omits_country_by_default() -> None:
    profile = {
        "personal": {
            "full_name": "Alex Example",
            "city": "Aurora",
            "province_state": "CO",
            "country": "US",
        }
    }
    data = {"title": "Engineer", "summary": "Summary", "skills": {}, "experience": [], "projects": [], "education": ""}

    model = build_render_model_from_tailored_json(data, profile)

    assert model.location == "Aurora, CO"


def test_build_render_model_from_tailored_json_location_includes_country_when_enabled() -> None:
    profile = {
        "personal": {
            "full_name": "Alex Example",
            "city": "Aurora",
            "province_state": "CO",
            "country": "US",
        },
        "tailoring_config": {
            "pdf_render_options": {
                "include_country_in_location": True,
            }
        },
    }
    data = {"title": "Engineer", "summary": "Summary", "skills": {}, "experience": [], "projects": [], "education": ""}

    model = build_render_model_from_tailored_json(data, profile)

    assert model.location == "Aurora, CO, US"


def test_build_render_model_from_tailored_json_maps_compact_summary() -> None:
    profile = {"personal": {"full_name": "Alex Example"}}
    data = {
        "title": "Engineer",
        "summary": "Summary",
        "skills": {},
        "experience": [
            {
                "header": "Engineer",
                "subtitle": "Example | 2020-2024",
                "bullets": ["Built APIs"],
                "compact_summary": "Improved API reliability.",
            }
        ],
        "projects": [
            {
                "header": "Side Project",
                "subtitle": "Python | 2024",
                "bullets": ["Built a tool"],
                "short_summary": "Created automation tooling.",
            }
        ],
        "education": "",
    }

    model = build_render_model_from_tailored_json(data, profile)

    assert model.experience[0].compact_summary == "Improved API reliability."
    assert model.projects[0].compact_summary == "Created automation tooling."


def test_build_render_model_from_tailored_json_maps_render_options_from_pdf_render_options() -> None:
    profile = {
        "personal": {"full_name": "Alex Example"},
        "tailoring_config": {"pdf_render_options": {"compact_max_detailed_experience": 3}},
    }
    data = {"title": "Engineer", "summary": "Summary", "skills": {}, "experience": [], "projects": [], "education": ""}

    model = build_render_model_from_tailored_json(data, profile)

    assert model.render_options["compact_max_detailed_experience"] == 3


def test_build_render_model_from_tailored_json_render_options_priority_prefers_render_options() -> None:
    profile = {
        "personal": {"full_name": "Alex Example"},
        "tailoring_config": {
            "render_options": {"compact_max_detailed_experience": 2, "tailoring_only": "x"},
            "pdf_render_options": {"compact_max_detailed_experience": 3, "pdf_only": "y"},
        },
        "render": {"options": {"compact_max_detailed_experience": 5, "render_only": "z"}},
    }
    data = {"title": "Engineer", "summary": "Summary", "skills": {}, "experience": [], "projects": [], "education": ""}

    model = build_render_model_from_tailored_json(data, profile)

    assert model.render_options["compact_max_detailed_experience"] == 5
    assert model.render_options["tailoring_only"] == "x"
    assert model.render_options["pdf_only"] == "y"
    assert model.render_options["render_only"] == "z"


def test_build_render_model_from_tailored_json_maps_max_resume_pages_from_global_rules() -> None:
    profile = {
        "personal": {"full_name": "Alex Example"},
        "tailoring_config": {
            "global_rules": {"max_resume_pages": 2.5},
        },
    }
    data = {"title": "Engineer", "summary": "Summary", "skills": {}, "experience": [], "projects": [], "education": ""}

    model = build_render_model_from_tailored_json(data, profile)

    assert model.render_options["max_resume_pages"] == 2.5


def test_build_render_model_from_tailored_json_ignores_non_dict_render_options() -> None:
    profile = {
        "personal": {"full_name": "Alex Example"},
        "tailoring_config": {"render_options": "invalid", "pdf_render_options": 7},
        "render": {"options": ["not", "a", "dict"]},
    }
    data = {"title": "Engineer", "summary": "Summary", "skills": {}, "experience": [], "projects": [], "education": ""}

    model = build_render_model_from_tailored_json(data, profile)

    assert model.render_options == {}


def test_compact_prepare_honors_render_options_from_profile_model() -> None:
    profile = {
        "personal": {"full_name": "Alex Example"},
        "tailoring_config": {"pdf_render_options": {"compact_max_detailed_experience": 2}},
    }
    data = {
        "title": "Engineer",
        "summary": "Summary",
        "skills": {},
        "experience": [
            {"header": "Role 1", "bullets": ["b1"]},
            {"header": "Role 2", "bullets": ["b2"]},
            {"header": "Role 3", "bullets": ["b3"]},
            {"header": "Role 4", "bullets": ["b4"]},
        ],
        "projects": [],
        "education": "",
    }

    model = build_render_model_from_tailored_json(data, profile)
    prepared = compact_template.prepare(model)

    assert [entry.title for entry in prepared.detailed_experience] == ["Role 1", "Role 2"]
    assert [entry.title for entry in prepared.compact_experience] == ["Role 3", "Role 4"]
