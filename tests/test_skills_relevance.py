from __future__ import annotations

from applypilot.scoring.skills_relevance import build_relevant_skills


def test_build_relevant_skills_caps_to_max_count() -> None:
    raw_skills = {
        "Core": (
            "Java, Spring Boot, REST APIs, Microservices, Distributed Systems, Kafka, "
            "Event-Driven Architecture, SQL, PostgreSQL, MySQL, AWS, Docker, Kubernetes, "
            "CI/CD, GitHub Actions, GitLab CI, Jenkins, Linux, React, Angular, TensorFlow, "
            "Keras, Pandas, Helm, CloudFoundry, Redis, OAuth2, OpenAPI"
        )
    }
    job = {
        "title": "Senior Backend Engineer",
        "full_description": (
            "Build backend microservices using Java and Spring Boot. Design REST APIs, "
            "distributed systems, Kafka event-driven services, and AWS infrastructure."
        ),
    }

    selected, meta = build_relevant_skills(raw_skills, job=job, profile={})

    assert len(selected) <= 24
    assert meta["before_count"] > meta["after_count"]
    assert meta["after_count"] <= 24


def test_build_relevant_skills_prefers_backend_over_irrelevant_frontend_ml() -> None:
    raw_skills = {
        "Mixed": "Java, Spring Boot, Kafka, AWS, Docker, Kubernetes, React, Angular, TensorFlow, Keras",
    }
    job = {
        "title": "Senior Backend Platform Engineer",
        "full_description": "Backend platform role focused on Java microservices, Kafka, AWS, and Kubernetes.",
    }

    selected, meta = build_relevant_skills(raw_skills, job=job, profile={})
    tokens = [token for _category, token in selected]

    assert "Java" in tokens
    assert "Spring Boot" in tokens
    assert "Kafka" in tokens
    assert "AWS" in tokens
    assert "Kubernetes" in tokens
    assert meta["before_count"] == 10


def test_build_relevant_skills_uses_policy_and_catalog_refs_not_hardcoded_groups() -> None:
    raw_skills = {"Mixed": "Rust, Terraform, Chef"}
    job = {
        "title": "Platform Engineer",
        "full_description": "Own infrastructure operations and automation for production services.",
    }
    render_options = {
        "skills_target_count": 2,
        "skills_max_count": 2,
        "skills_min_count": 1,
        "skills_taxonomy_overrides": {
            "custom.ops.cues": {"kind": "cue_set", "terms": ["operations", "infrastructure", "automation"]},
            "custom.ops.skills": {"kind": "skill_set", "terms": ["terraform", "chef"]},
            "custom.lang.cues": {"kind": "cue_set", "terms": ["compiler", "systems programming"]},
            "custom.lang.skills": {"kind": "skill_set", "terms": ["rust"]},
        },
        "skills_relevance_policy": {
            "synonym_group_refs": [],
            "rules": [
                {
                    "name": "ops_bonus",
                    "when": "cue_present",
                    "cue_set_ref": "custom.ops.cues",
                    "skill_set_ref": "custom.ops.skills",
                    "weight": 25,
                },
                {
                    "name": "lang_penalty",
                    "when": "cue_absent",
                    "cue_set_ref": "custom.lang.cues",
                    "skill_set_ref": "custom.lang.skills",
                    "weight": -25,
                },
            ],
        },
    }

    selected, meta = build_relevant_skills(raw_skills, job=job, profile={}, render_options=render_options)
    tokens = [token for _category, token in selected]

    assert tokens == ["Terraform", "Chef"]
    assert "Rust" in meta["dropped_skills"]
