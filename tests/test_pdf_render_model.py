from __future__ import annotations

from applypilot.scoring.pdf import build_render_model, parse_resume
from applypilot.scoring.pdf_render_model import (
    ResumeEntry,
    build_render_model_from_tailored_json,
    build_skills_selection_report_from_tailored_json,
)
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
        },
        "education": [
            {
                "institution": "State University",
                "studyType": "BS",
                "area": "Computer Science",
                "endDate": "2018",
            }
        ],
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


def test_build_render_model_from_tailored_json_maps_structured_date_fields() -> None:
    profile = {
        "personal": {"full_name": "Alex Example"},
        "work": [
            {
                "company": "Charles Schwab",
                "position": "Software Engineer",
                "is_contract": True,
                "start_date": "2025-08",
                "end_date": "2026-03",
                "location": "Denver, CO",
            }
        ],
    }
    data = {
        "title": "Engineer",
        "summary": "Summary",
        "skills": {},
        "experience": [
            {
                "company": "Charles Schwab",
                "role": "Software Engineer",
                "start_date": "2025-08",
                "end_date": "2026-03",
                "location": "Denver, CO",
                "technologies": ["Cucumber", "GitHub Actions", "CloudFoundry"],
                "bullets": ["Built APIs"],
            }
        ],
        "projects": [
            {
                "name": "TribeApp",
                "description": "Backend-driven mobile platform",
                "start_date": "2022-10",
                "end_date": None,
                "technologies": ["Spring Boot", "MySQL"],
                "bullets": ["Built product features"],
            }
        ],
        "education": "",
    }

    model = build_render_model_from_tailored_json(data, profile)

    assert model.experience[0].company == "Charles Schwab"
    assert model.experience[0].role == "Software Engineer"
    assert model.experience[0].start_date == "2025-08"
    assert model.experience[0].end_date == "2026-03"
    assert model.experience[0].location == "Denver, CO"
    assert model.experience[0].technologies == ["Cucumber", "GitHub Actions", "CloudFoundry"]
    assert model.experience[0].is_contract is True
    assert model.projects[0].title == "TribeApp"
    assert model.projects[0].start_date == "2022-10"
    assert model.projects[0].end_date == ""


def test_build_render_model_from_tailored_json_prefers_profile_education_over_llm_education() -> None:
    profile = {
        "personal": {"full_name": "Alex Example"},
        "education": [
            {
                "institution": "Metropolitan State College of Denver",
                "studyType": "Major",
                "area": "Computer Science",
                "startDate": "1994",
                "endDate": "1996",
                "degree_completed": False,
            }
        ],
    }
    data = {
        "title": "Engineer",
        "summary": "Summary",
        "skills": {},
        "experience": [],
        "projects": [],
        "education": "Metropolitan State College of Denver | Major Computer Science | 1994 - 1996",
    }

    model = build_render_model_from_tailored_json(data, profile)

    assert model.education == "Metropolitan State College of Denver | Computer Science coursework | 1994 - 1996"
    assert "Major Computer Science" not in model.education


def test_build_render_model_from_tailored_json_uses_llm_education_when_profile_missing() -> None:
    profile = {"personal": {"full_name": "Alex Example"}}
    data = {
        "title": "Engineer",
        "summary": "Summary",
        "skills": {},
        "experience": [],
        "projects": [],
        "education": "State University | BS Computer Science | 2018",
    }

    model = build_render_model_from_tailored_json(data, profile)

    assert model.education == "State University | BS Computer Science | 2018"


def test_build_render_model_from_tailored_json_parses_legacy_dates_fallback() -> None:
    profile = {"personal": {"full_name": "Alex Example"}}
    data = {
        "title": "Engineer",
        "summary": "Summary",
        "skills": {},
        "experience": [
            {
                "header": "Software Engineer",
                "subtitle": "Acme Corp | 2020-01 - 2021-02",
                "bullets": ["Built APIs"],
            }
        ],
        "projects": [],
        "education": "",
    }

    model = build_render_model_from_tailored_json(data, profile)

    assert model.experience[0].start_date == "2020-01"
    assert model.experience[0].end_date == "2021-02"


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


def test_build_skills_selection_report_from_tailored_json_returns_counts_and_drops() -> None:
    profile = {"personal": {"full_name": "Alex Example"}}
    data = {
        "title": "Engineer",
        "summary": "Summary",
        "skills": {
            "Core": (
                "Java, Spring Boot, REST APIs, Microservices, Distributed Systems, Kafka, "
                "Event-Driven Architecture, SQL, PostgreSQL, MySQL, AWS, Docker, Kubernetes, "
                "CI/CD, GitHub Actions, GitLab CI, Jenkins, Linux, React, Angular, TensorFlow, "
                "Keras, Pandas, Helm, CloudFoundry, Redis, OAuth2, OpenAPI"
            )
        },
        "experience": [],
        "projects": [],
        "education": "",
    }
    job = {
        "title": "Senior Backend Engineer",
        "full_description": (
            "Build backend microservices in Java and Spring Boot, design REST APIs, "
            "distributed systems, Kafka event-driven workflows, and AWS Kubernetes deployments."
        ),
    }

    report = build_skills_selection_report_from_tailored_json(data, profile, job=job)

    assert report["before_count"] > report["after_count"]
    assert report["after_count"] <= 24
    assert isinstance(report["dropped_skills"], list)


def test_build_render_model_from_tailored_json_applies_relevance_capped_skills_for_job() -> None:
    profile = {
        "personal": {"full_name": "Alex Example"},
    }
    data = {
        "title": "Engineer",
        "summary": "Summary",
        "skills": {
            "Core": (
                "Java, Spring Boot, REST APIs, Microservices, Distributed Systems, Kafka, "
                "Event-Driven Architecture, SQL, PostgreSQL, MySQL, AWS, Docker, Kubernetes, "
                "CI/CD, GitHub Actions, GitLab CI, Jenkins, Linux, React, Angular, TensorFlow, "
                "Keras, Pandas, Helm, CloudFoundry, Redis, OAuth2, OpenAPI"
            )
        },
        "experience": [],
        "projects": [],
        "education": "",
    }
    job = {
        "title": "Senior Backend Engineer",
        "full_description": (
            "Build backend microservices in Java and Spring Boot, design REST APIs, "
            "distributed systems, Kafka event-driven workflows, and AWS Kubernetes deployments."
        ),
    }

    model = build_render_model_from_tailored_json(data, profile, job=job)

    flattened = []
    for section in model.skills:
        flattened.extend([part.strip() for part in section.value.split(",") if part.strip()])

    assert len(flattened) <= 24
    assert "Java" in flattened
    assert "Spring Boot" in flattened


def test_build_render_model_from_tailored_json_prefers_richer_profile_skill_display_variants() -> None:
    profile = {
        "personal": {"full_name": "Alex Example"},
        "skills": [
            {"name": "Languages", "keywords": ["Java 17-21"]},
            {"name": "Backend", "keywords": ["Spring Boot 3.x"]},
        ],
    }
    data = {
        "title": "Engineer",
        "summary": "Summary",
        "skills": {"Core": "Java, Spring Boot, Kubernetes"},
        "experience": [],
        "projects": [],
        "education": "",
    }
    job = {
        "title": "Senior Backend Engineer",
        "full_description": "Build backend services with Java and Spring Boot on Kubernetes.",
    }

    model = build_render_model_from_tailored_json(data, profile, job=job)

    flattened = []
    for section in model.skills:
        flattened.extend([part.strip() for part in section.value.split(",") if part.strip()])

    assert "Java 17-21" in flattened
    assert "Spring Boot 3.x" in flattened
