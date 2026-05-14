"""Tests for bullet normalization to prevent JSON metadata leaks.

@file test_bullet_normalization.py
@description Tests that bullets with embedded JSON are properly cleaned.
"""

import pytest
from applypilot.scoring.tailor import (
    _get_tailored_max_lines,
    _missing_profile_companies_in_generated_experience,
    _normalize_bullet,
    _strip_disallowed_watchlist_skills,
    assemble_resume_text,
)


class TestNormalizeBullet:
    """Test the _normalize_bullet function handles various input types."""

    def test_plain_string_bullet(self):
        """Plain string bullets should pass through unchanged."""
        bullet = "Built API handling 1M requests/day"
        result = _normalize_bullet(bullet)
        assert result == "Built API handling 1M requests/day"

    def test_bullet_with_trailing_json(self):
        """Bullets with trailing JSON metadata should have JSON stripped."""
        bullet = 'Built API handling 1M requests/day {"variants": {"car": "Test", "who": "Test"}, "tags": ["test"], "skills": ["python"]}'
        result = _normalize_bullet(bullet)
        assert result == "Built API handling 1M requests/day"
        assert "variants" not in result
        assert "tags" not in result

    def test_dict_bullet_with_text_field(self):
        """Dict bullets should extract the text field."""
        bullet = {"text": "Built API handling 1M requests/day", "variants": {"car": "Test"}, "tags": ["test"]}
        result = _normalize_bullet(bullet)
        assert result == "Built API handling 1M requests/day"

    def test_pure_json_bullet(self):
        """Bullets that are pure JSON should extract text if present."""
        bullet = '{"text": "Built API handling 1M requests/day", "variants": {}}'
        result = _normalize_bullet(bullet)
        assert result == "Built API handling 1M requests/day"

    def test_bullet_with_variants_keyword(self):
        """Bullets containing 'variants' in JSON should be cleaned."""
        bullet = 'Led team of 5 engineers {"variants": {"technical": "Test"}, "role_families": ["ai_engineer"]}'
        result = _normalize_bullet(bullet)
        assert result == "Led team of 5 engineers"
        assert "variants" not in result

    def test_bullet_with_tags_keyword(self):
        """Bullets containing 'tags' in JSON should be cleaned."""
        bullet = 'Designed system architecture {"tags": ["python", "aws"], "domains": ["ai"]}'
        result = _normalize_bullet(bullet)
        assert result == "Designed system architecture"
        assert "tags" not in result

    def test_numeric_bullet(self):
        """Numeric bullets should be converted to string."""
        bullet = 12345
        result = _normalize_bullet(bullet)
        assert result == "12345"

    def test_empty_bullet(self):
        """Empty bullets should be handled gracefully."""
        bullet = ""
        result = _normalize_bullet(bullet)
        assert result == ""


class TestAssembleResumeTextWithJsonBullets:
    """Test that assemble_resume_text properly handles JSON in bullets."""

    @pytest.fixture
    def sample_profile(self):
        return {"personal": {"full_name": "Test User", "email": "test@example.com"}}

    @pytest.fixture
    def profile_with_work(self):
        return {
            "personal": {"full_name": "Test User", "email": "test@example.com"},
            "work": [
                {
                    "company": "Alpha Corp",
                    "position": "Senior Backend Engineer",
                    "start_date": "2025-01",
                    "end_date": "2026-01",
                    "summary": "Built backend APIs.",
                    "highlights": [
                        "Built Spring Boot APIs for payment workflows.",
                        "Integrated Kafka event streams for billing events.",
                        "Improved CI/CD reliability across service deployments.",
                    ],
                },
                {
                    "company": "Beta Systems",
                    "position": "Software Engineer",
                    "start_date": "2023-01",
                    "end_date": "2024-12",
                    "summary": "Backend and integrations.",
                    "highlights": [
                        "Implemented REST integrations with external systems.",
                        "Reduced release preparation from days to hours.",
                    ],
                },
            ],
        }

    def test_experience_with_json_bullets(self, sample_profile):
        """Experience bullets with JSON should be cleaned in final output."""
        data = {
            "title": "Software Engineer",
            "summary": "Test summary",
            "skills": {"Languages": "Python"},
            "experience": [
                {
                    "header": "Engineer | TestCorp | 2020-2023",
                    "subtitle": "Backend | 2020-2023",
                    "bullets": [
                        "Built API handling 1M requests/day",
                        'Led team {"variants": {"car": "Test"}, "tags": ["test"]}',
                        'Designed system {"variants": {}, "skills": ["python"]}',
                    ],
                }
            ],
            "projects": [],
            "education": "BS Computer Science",
        }

        result = assemble_resume_text(data, sample_profile)

        # Check that JSON is not in output
        assert "variants" not in result
        assert '"car"' not in result
        assert '"tags"' not in result

        # Check that bullet text IS in output
        assert "Built API handling 1M requests/day" in result
        assert "Led team" in result
        assert "Designed system" in result

    def test_projects_with_json_bullets(self, sample_profile):
        """Project bullets with JSON should be cleaned in final output."""
        data = {
            "title": "Software Engineer",
            "summary": "Test summary",
            "skills": {"Languages": "Python"},
            "experience": [],
            "projects": [
                {
                    "header": "Project X - AI Platform",
                    "subtitle": "Python, AI | 2023",
                    "bullets": ['Built ML pipeline {"variants": {"technical": "Test"}, "role_families": ["ai"]}'],
                }
            ],
            "education": "BS Computer Science",
        }

        result = assemble_resume_text(data, sample_profile)

        # Check that JSON is not in output
        assert "variants" not in result
        assert "role_families" not in result

        # Check that bullet text IS in output
        assert "Built ML pipeline" in result

    def test_no_regression_with_clean_bullets(self, sample_profile):
        """Clean bullets should still work normally."""
        data = {
            "title": "Software Engineer",
            "summary": "Test summary",
            "skills": {"Languages": "Python"},
            "experience": [
                {
                    "header": "Engineer | TestCorp | 2020-2023",
                    "subtitle": "Backend | 2020-2023",
                    "bullets": [
                        "Built API handling 1M requests/day",
                        "Led team of 5 engineers",
                        "Reduced costs by 40%",
                    ],
                }
            ],
            "projects": [],
            "education": "BS Computer Science",
        }

        result = assemble_resume_text(data, sample_profile)

        # All bullets should appear
        assert "Built API handling 1M requests/day" in result
        assert "Led team of 5 engineers" in result
        assert "Reduced costs by 40%" in result

        # Should have proper formatting
        assert "- Built API" in result
        assert "- Led team" in result
        assert "- Reduced costs" in result

    def test_omits_projects_section_when_empty(self, sample_profile):
        """PROJECTS header should not render when there are no project entries."""
        data = {
            "title": "Software Engineer",
            "summary": "Test summary",
            "skills": {"Languages": "Python"},
            "experience": [],
            "projects": [],
            "education": "BS Computer Science",
        }

        result = assemble_resume_text(data, sample_profile)

        assert "\nPROJECTS\n" not in result
        assert "\nEDUCATION\n" in result

    def test_keeps_projects_section_when_project_content_exists(self, sample_profile):
        """PROJECTS header should render when at least one project has content."""
        data = {
            "title": "Software Engineer",
            "summary": "Test summary",
            "skills": {"Languages": "Python"},
            "experience": [],
            "projects": [{"header": "Project X", "subtitle": "", "bullets": []}],
            "education": "BS Computer Science",
        }

        result = assemble_resume_text(data, sample_profile)

        assert "\nPROJECTS\n" in result
        assert "Project X" in result

    def test_does_not_reinsert_profile_jobs_omitted_by_llm(self, profile_with_work):
        """Assembler should not reinsert roles omitted by the model."""
        data = {
            "title": "Senior Backend Engineer",
            "summary": "Test summary",
            "skills": {"Languages": "Python, Java"},
            "experience": [
                {
                    "header": "Senior Backend Engineer",
                    "subtitle": "Alpha Corp | 2025-01 - 2026-01",
                    "bullets": ["Built payment APIs"],
                }
            ],
            "projects": [],
            "education": "BS Computer Science",
        }

        result = assemble_resume_text(data, profile_with_work, job={"title": "Backend Engineer"})

        assert "Alpha Corp" in result
        assert "Beta Systems" not in result
        assert "\nEXPERIENCE\n" in result

    def test_prefers_model_content_when_role_present(self, profile_with_work):
        """Assembler should preserve model-tailored bullets for matched roles."""
        data = {
            "title": "Senior Backend Engineer",
            "summary": "Test summary",
            "skills": {"Languages": "Python, Java"},
            "experience": [
                {
                    "header": "Senior Backend Engineer",
                    "subtitle": "Alpha Corp | 2025-01 - 2026-01",
                    "bullets": ["Built GraphQL APIs for partner integrations."],
                },
                {
                    "header": "Software Engineer",
                    "subtitle": "Beta Systems | 2023-01 - 2024-12",
                    "bullets": ["Implemented event-driven billing workflows with Kafka."],
                },
            ],
            "projects": [],
            "education": "BS Computer Science",
        }

        result = assemble_resume_text(data, profile_with_work, job={"title": "Backend Engineer"})

        assert "Built GraphQL APIs for partner integrations." in result
        assert "Implemented event-driven billing workflows with Kafka." in result
        assert "Built Spring Boot APIs for payment workflows." not in result

    def test_adds_selected_experience_when_length_over_budget(self, sample_profile):
        """Oldest roles should be compressed into SELECTED EXPERIENCE when over budget."""
        generated_experience = []
        for idx in range(26):
            year = 2033 - idx
            generated_experience.append(
                {
                    "header": "Software Engineer",
                    "subtitle": f"Company {idx} | {year}-01 - {year}-12",
                    "bullets": [
                        f"Built backend service {idx} using Java and Spring Boot.",
                        f"Integrated event workflow {idx} with Kafka and SQL.",
                        f"Automated CI/CD pipeline {idx} and improved reliability.",
                    ],
                }
            )

        profile = {
            "personal": {"full_name": "Test User", "email": "test@example.com"},
            "work": [],
        }
        data = {
            "title": "Senior Software Engineer",
            "summary": "Test summary",
            "skills": {"Languages": "Python, Java", "Backend": "Spring Boot, APIs"},
            "experience": generated_experience,
            "projects": [],
            "education": "BS Computer Science",
        }

        result = assemble_resume_text(data, profile, job={"title": "Senior Backend Engineer"})

        assert "\nSELECTED EXPERIENCE\n" in result
        for idx in range(26):
            assert f"Company {idx}" in result

    def test_moves_oldest_roles_to_selected_experience_first(self):
        roles = []
        for idx in range(12):
            year = 2025 - idx
            roles.append(
                {
                    "company": f"Company {idx}",
                    "position": "Engineer",
                    "start_date": f"{year}-01",
                    "end_date": f"{year}-12" if idx else "",
                }
            )
        profile = {
            "personal": {"full_name": "Test User", "email": "test@example.com"},
            "tailoring_config": {"global_rules": {"max_resume_pages": 1.2, "formatting": {"lines_per_page": 50}}},
            "work": roles,
        }
        generated_experience = []
        for idx in range(12):
            year = 2025 - idx
            generated_experience.append(
                {
                    "header": "Engineer",
                    "subtitle": f"Company {idx} | {year}-01 - {year}-12" if idx else f"Company {idx} | {year}-01 - Present",
                    "bullets": [f"Built service {idx}.", f"Improved workflow {idx}."],
                }
            )
        data = {
            "title": "Senior Software Engineer",
            "summary": "Test summary",
            "skills": {"Languages": "Python, Java", "Backend": "Spring Boot, APIs"},
            "experience": generated_experience,
            "projects": [],
            "education": "BS Computer Science",
        }

        result = assemble_resume_text(data, profile, job={"title": "Senior Backend Engineer"})

        assert "\nSELECTED EXPERIENCE\n" in result
        assert "Company 11" in result


class TestWatchlistSkillStripping:
    """Test stripping disallowed watchlist skills from generated payloads."""

    def test_strips_unapproved_watchlist_skills(self):
        profile = {"skills": [{"name": "Languages", "keywords": ["Python", "JavaScript"]}]}
        data = {
            "skills": {
                "Languages": "Python, Rust, JavaScript, Swift",
                "Frameworks": "React, Rails, FastAPI",
            }
        }

        removed = _strip_disallowed_watchlist_skills(data, profile)

        assert "Rust" in removed
        assert "Swift" in removed
        assert "Rails" in removed
        assert data["skills"]["Languages"] == "Python, JavaScript"
        assert data["skills"]["Frameworks"] == "React, FastAPI"

    def test_strips_watchlist_skill_even_if_profile_mentions_it(self):
        profile = {"skills": [{"name": "Languages", "keywords": ["Python", "Rust"]}]}
        data = {"skills": {"Languages": "Python, Rust"}}

        removed = _strip_disallowed_watchlist_skills(data, profile)

        assert removed == ["Rust"]
        assert data["skills"]["Languages"] == "Python"


class TestTailorLineBudget:
    def test_default_line_budget(self):
        profile = {"tailoring_config": {}}
        assert _get_tailored_max_lines(profile) == 130

    def test_configurable_max_pages_budget(self):
        profile = {
            "tailoring_config": {
                "global_rules": {
                    "max_resume_pages": 3.0,
                    "formatting": {"lines_per_page": 50},
                }
            }
        }
        assert _get_tailored_max_lines(profile) == 150


class TestMissingCompanyDetection:
    def test_reports_missing_profile_companies_in_generated_experience(self):
        profile = {
            "work": [
                {"company": "Alpha Corp"},
                {"company": "Beta Systems"},
            ]
        }
        data = {
            "experience": [
                {"header": "Senior Backend Engineer", "subtitle": "Alpha Corp | 2025-01 - 2026-01", "bullets": ["Built APIs."]},
            ]
        }

        missing = _missing_profile_companies_in_generated_experience(data, profile)

        assert missing == ["Beta Systems"]
