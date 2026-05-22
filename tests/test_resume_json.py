from __future__ import annotations

import json

import pytest

from applypilot.resume_json import (
    ResumeJsonError,
    build_resume_text_from_json,
    get_profile_verified_metrics,
    load_resume_json_from_path,
    normalize_profile_from_resume_json,
    resolve_jsonresume_theme,
    resolve_render_theme,
    validate_resume_json,
)


def sample_resume_json() -> dict:
    return {
        "basics": {
            "name": "Spencer Thayer",
            "label": "Systems Architect",
            "email": "me@example.com",
            "phone": "555-123-4567",
            "url": "https://example.com",
            "summary": "Built production systems across design and engineering roles.",
            "location": {
                "city": "Portland",
                "region": "OR",
                "countryCode": "US",
                "postalCode": "97203",
            },
            "profiles": [
                {"network": "LinkedIn", "url": "https://linkedin.com/in/example"},
                {"network": "GitHub", "url": "https://github.com/example"},
            ],
        },
        "work": [
            {
                "name": "Watson Creative",
                "position": "Principal Developer",
                "location": "Portland, OR",
                "startDate": "2022-09-19",
                "summary": "Led platform strategy.",
                "highlights": ["Built client platforms", "Automated AI workflows"],
                "x-applypilot": {
                    "key_metrics": ["99.9% uptime", "50% faster delivery"],
                    "is_contract": True,
                },
            }
        ],
        "education": [
            {
                "institution": "Lincoln Land Community College",
                "studyType": "Associate",
                "area": "Liberal Arts",
                "endDate": "2000",
            }
        ],
        "skills": [
            {"name": "Programming Languages", "keywords": ["Python", "JavaScript"]},
            {"name": "Frameworks & Libraries", "keywords": ["FastAPI", "React"]},
            {"name": "Tools & Platforms", "keywords": ["Docker", "AWS"]},
        ],
        "projects": [
            {
                "name": "capstack.ai",
                "description": "Digital loan marketplace platform.",
                "highlights": ["Shipped platform MVP"],
                "url": "https://capstack.ai",
            }
        ],
        "meta": {
            "theme": "jsonresume-theme-even",
            "applypilot": {
                "target_role": "Staff Software Engineer",
                "years_of_experience_total": "20",
                "work_authorization": {
                    "legally_authorized_to_work": "Yes",
                    "require_sponsorship": "No",
                },
                "compensation": {
                    "salary_expectation": "180000",
                    "salary_currency": "USD",
                    "salary_range_min": "170000",
                    "salary_range_max": "210000",
                },
                "availability": {"earliest_start_date": "Immediately"},
                "render": {"theme": "jsonresume-theme-even"},
            },
        },
    }


def test_normalize_profile_from_resume_json_maps_internal_contract() -> None:
    profile = normalize_profile_from_resume_json(sample_resume_json())

    assert profile["personal"]["full_name"] == "Spencer Thayer"
    assert profile["personal"]["linkedin_url"] == "https://linkedin.com/in/example"
    assert profile["experience"]["current_title"] == "Principal Developer"
    assert profile["experience"]["target_role"] == "Staff Software Engineer"
    assert profile["work"][0]["company"] == "Watson Creative"
    assert profile["work"][0]["is_contract"] is True
    assert profile["render"]["jsonresume_theme"] == "jsonresume-theme-even"
    assert get_profile_verified_metrics(profile) == [
        "99.9% uptime",
        "50% faster delivery",
    ]


def test_normalize_profile_preserves_education_coursework_metadata() -> None:
    data = sample_resume_json()
    data["education"][0] = {
        "institution": "Metropolitan State College of Denver",
        "studyType": "Coursework",
        "area": "Computer Science",
        "startDate": "1994",
        "endDate": "1996",
        "x-applypilot": {
            "degree_completed": False,
            "education_display": "Computer Science coursework",
        },
    }

    profile = normalize_profile_from_resume_json(data)

    assert profile["education"][0]["degree_completed"] is False
    assert profile["education"][0]["education_display"] == "Computer Science coursework"
    assert profile["education"][0]["startDate"] == "1994"
    assert profile["education"][0]["endDate"] == "1996"


def test_build_resume_text_from_json_is_deterministic() -> None:
    data = sample_resume_json()

    first = build_resume_text_from_json(data)
    second = build_resume_text_from_json(data)

    assert first == second
    assert "SUMMARY" in first
    assert "TECHNICAL SKILLS" in first
    assert "EXPERIENCE" in first
    assert "PROJECTS" in first
    assert "EDUCATION" in first
    assert "Spencer Thayer" in first


def test_build_resume_text_from_json_education_uses_coursework_display_when_provided() -> None:
    data = sample_resume_json()
    data["education"][0] = {
        "institution": "Metropolitan State College of Denver",
        "studyType": "Coursework",
        "area": "Computer Science",
        "startDate": "1994",
        "endDate": "1996",
        "x-applypilot": {
            "degree_completed": False,
            "education_display": "Computer Science coursework",
        },
    }

    rendered = build_resume_text_from_json(data)

    assert "Metropolitan State College of Denver | Computer Science coursework | 1994 - 1996" in rendered
    assert "Major" not in rendered


def test_build_resume_text_from_json_education_without_metadata_preserves_existing_format() -> None:
    rendered = build_resume_text_from_json(sample_resume_json())

    assert "Lincoln Land Community College | Associate Liberal Arts | 2000" in rendered


def test_resolve_render_theme_backfills_from_resume_meta_for_compatibility() -> None:
    data = sample_resume_json()
    assert resolve_render_theme(data) == "jsonresume-theme-even"
    assert resolve_render_theme(data, explicit_theme="jsonresume-theme-professional") == "jsonresume-theme-professional"


def test_resolve_jsonresume_theme_prefers_profile_render_settings() -> None:
    profile = {"render": {"jsonresume_theme": "jsonresume-theme-even"}}
    assert resolve_jsonresume_theme(profile) == "jsonresume-theme-even"
    assert resolve_jsonresume_theme(profile, explicit_theme="jsonresume-theme-stackoverflow") == "jsonresume-theme-stackoverflow"


def test_resolve_jsonresume_theme_maps_legacy_render_theme_key() -> None:
    profile = {"render": {"theme": "jsonresume-theme-even"}}
    assert resolve_jsonresume_theme(profile) == "jsonresume-theme-even"


def test_normalize_profile_uses_first_role_from_multi_role_label_when_target_role_missing() -> None:
    data = sample_resume_json()
    data["meta"]["applypilot"].pop("target_role", None)
    data["basics"]["label"] = "Systems Architect, Senior Full Stack Developer, UI/UX"

    profile = normalize_profile_from_resume_json(data)

    assert profile["experience"]["target_role"] == "Systems Architect"


def test_validate_resume_json_rejects_secret_keys() -> None:
    pytest.importorskip("jsonschema")
    data = sample_resume_json()
    data["meta"]["applypilot"]["personal"] = {"password": "secret"}

    with pytest.raises(ResumeJsonError, match="secrets must stay in .env"):
        validate_resume_json(data)


def test_load_resume_json_from_path_fails_on_invalid_canonical(tmp_path) -> None:
    pytest.importorskip("jsonschema")
    path = tmp_path / "resume.json"
    path.write_text(json.dumps({"basics": [], "meta": {"applypilot": {}}}), encoding="utf-8")

    with pytest.raises(ResumeJsonError, match="Invalid resume.json"):
        load_resume_json_from_path(path)
