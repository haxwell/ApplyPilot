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
    assert isinstance(meta["retained_skills"], list)


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


def test_build_relevant_skills_fills_toward_target_when_strong_skills_are_few() -> None:
    raw_skills = {
        "Core": "Java, Spring Boot, Kafka, AWS, Docker, Kubernetes, SQL, MySQL, PostgreSQL, Linux, Helm, GitHub Actions",
        "Extra": "OpenAPI, OAuth2, Bash, Git, Nginx, RabbitMQ, Redis, Terraform",
    }
    job = {
        "title": "Senior Backend Engineer",
        "full_description": "Build Java services using Spring Boot, Kafka, AWS, and Kubernetes.",
    }
    render_options = {"skills_target_count": 16, "skills_max_count": 24, "skills_min_count": 12}

    selected, meta = build_relevant_skills(raw_skills, job=job, profile={}, render_options=render_options)

    assert len(selected) >= 12
    assert len(selected) <= 16
    assert meta["after_count"] == len(selected)


def test_build_relevant_skills_does_not_include_zero_score_fillers_when_min_reached() -> None:
    raw_skills = {"Core": "Java (17-21), Spring Boot 3.x, Kubernetes, Helm, JPA/Hibernate"}
    job = {
        "title": "Backend Engineer",
        "full_description": "Build backend distributed systems with Kubernetes and Java services.",
    }
    render_options = {"skills_target_count": 20, "skills_max_count": 24, "skills_min_count": 2}

    _selected, meta = build_relevant_skills(raw_skills, job=job, profile={}, render_options=render_options)

    assert meta["after_count"] >= 2
    retained = meta.get("retained_skills", [])
    assert all(float(entry.get("score", 0)) > 0 for entry in retained)


def test_build_relevant_skills_handles_vendor_prefixed_skill_variants() -> None:
    raw_skills = {"Core": "Apache Kafka, AWS EC2, AWS S3"}
    job = {
        "title": "Backend Engineer",
        "full_description": "Own Kafka event pipelines on AWS for backend systems.",
    }

    selected, _meta = build_relevant_skills(raw_skills, job=job, profile={})
    tokens = [token for _category, token in selected]

    assert "Apache Kafka" in tokens
    assert ("AWS EC2" in tokens) or ("AWS S3" in tokens)


def test_build_relevant_skills_handles_versioned_skill_variants() -> None:
    raw_skills = {"Core": "Java (17-21), Spring Boot 3.x"}
    job = {
        "title": "Senior Backend Engineer",
        "full_description": "Deep Java and Spring Boot experience for backend systems.",
    }

    _selected, meta = build_relevant_skills(raw_skills, job=job, profile={})
    retained = {entry["skill"]: entry["score"] for entry in meta["retained_skills"]}

    assert retained["Java (17-21)"] > 0
    assert retained["Spring Boot 3.x"] > 0


def test_build_relevant_skills_preserves_parenthetical_comma_groups() -> None:
    raw_skills = {"Core": "AWS (EC2, S3, Lambda), PostgreSQL (RDS), Java"}
    job = {
        "title": "Backend Engineer",
        "full_description": "Build backend services on AWS and PostgreSQL.",
    }

    selected, _meta = build_relevant_skills(raw_skills, job=job, profile={})
    tokens = [token for _category, token in selected]

    assert "AWS (EC2, S3, Lambda)" in tokens
    assert "PostgreSQL (RDS)" in tokens


def test_build_relevant_skills_boosts_delivery_tooling_when_delivery_cues_present() -> None:
    raw_skills = {"Core": "GitHub Actions, GitLab CI, Jenkins CI, Java"}
    job = {
        "title": "Backend Engineer",
        "full_description": "Own CI/CD pipelines, deployment automation, release reliability, and delivery workflows.",
    }

    _selected, meta = build_relevant_skills(raw_skills, job=job, profile={})
    retained = {entry["skill"]: entry for entry in meta["retained_skills"]}

    assert retained["GitHub Actions"]["score"] > 0
    assert "delivery_support" in retained["GitHub Actions"]["reasons"]


def test_build_relevant_skills_applies_default_aws_family_cap() -> None:
    raw_skills = {"Cloud": "AWS EC2, AWS S3, AWS Lambda, Docker, Kubernetes, CI/CD"}
    job = {
        "title": "Platform Engineer",
        "full_description": "Build distributed systems on cloud-native infrastructure with strong reliability.",
    }
    render_options = {"skills_target_count": 6, "skills_max_count": 6, "skills_min_count": 6}

    selected, meta = build_relevant_skills(raw_skills, job=job, profile={}, render_options=render_options)
    tokens = [token for _category, token in selected]
    aws_count = sum(1 for token in tokens if token.startswith("AWS "))

    assert aws_count <= 2
    assert meta["family_caps_applied"]["aws"] == 2
