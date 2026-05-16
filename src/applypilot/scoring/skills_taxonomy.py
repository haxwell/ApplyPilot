"""Skills taxonomy catalog and default relevance policy."""

from __future__ import annotations

from typing import Any

# Catalog IDs are stable references that policies use.
DEFAULT_SKILLS_CATALOG: dict[str, dict[str, Any]] = {
    "synonyms.api": {
        "kind": "synonym_group",
        "terms": ["rest api", "rest apis", "restful api", "api"],
    },
    "synonyms.spring": {
        "kind": "synonym_group",
        "terms": ["spring", "spring boot"],
    },
    "synonyms.cicd": {
        "kind": "synonym_group",
        "terms": [
            "ci/cd",
            "ci cd",
            "continuous integration",
            "continuous delivery",
            "github actions",
            "gitlab ci",
            "jenkins",
        ],
    },
    "synonyms.kubernetes": {
        "kind": "synonym_group",
        "terms": ["kubernetes", "k8s"],
    },
    "synonyms.eventing": {
        "kind": "synonym_group",
        "terms": ["event-driven architecture", "event driven architecture", "event-driven", "event driven", "kafka", "messaging"],
    },
    "synonyms.sql": {
        "kind": "synonym_group",
        "terms": ["sql", "postgresql", "mysql", "rdbms"],
    },
    "synonyms.aws": {
        "kind": "synonym_group",
        "terms": ["aws", "ec2", "s3", "lambda", "ecs", "eks", "cloudformation"],
    },
    "domain.backend.cues": {
        "kind": "cue_set",
        "terms": ["backend", "platform", "distributed", "microservice", "api", "services", "reliability", "performance"],
    },
    "domain.backend.skills": {
        "kind": "skill_set",
        "terms": [
            "java",
            "spring",
            "spring boot",
            "rest api",
            "microservices",
            "distributed systems",
            "kafka",
            "event-driven architecture",
            "sql",
            "postgresql",
            "mysql",
            "docker",
            "kubernetes",
            "aws",
            "ci/cd",
        ],
    },
    "domain.frontend.cues": {
        "kind": "cue_set",
        "terms": ["frontend", "front-end", "ui", "react", "angular", "ionic", "javascript", "typescript"],
    },
    "domain.frontend.skills": {
        "kind": "skill_set",
        "terms": ["react", "angular", "ionic", "html", "css", "javascript", "typescript"],
    },
    "domain.ml.cues": {
        "kind": "cue_set",
        "terms": ["ml", "machine learning", "llm", "ai", "model", "neural", "tensorflow", "keras", "pandas"],
    },
    "domain.ml.skills": {
        "kind": "skill_set",
        "terms": ["tensorflow", "keras", "pandas", "scikit-learn", "pytorch"],
    },
    "domain.delivery.cues": {
        "kind": "cue_set",
        "terms": [
            "ci/cd",
            "continuous integration",
            "continuous delivery",
            "deployment",
            "delivery",
            "release",
            "pipeline",
            "reliability",
            "operational excellence",
        ],
    },
    "domain.delivery.skills": {
        "kind": "skill_set",
        "terms": [
            "ci/cd",
            "github actions",
            "gitlab ci",
            "jenkins",
            "integration testing",
            "test-driven development",
            "tdd",
        ],
    },
}

# Generic policy: references taxonomy IDs, no engine hardcoding.
DEFAULT_SKILLS_RELEVANCE_POLICY: dict[str, Any] = {
    "synonym_group_refs": [
        "synonyms.api",
        "synonyms.spring",
        "synonyms.cicd",
        "synonyms.kubernetes",
        "synonyms.eventing",
        "synonyms.sql",
        "synonyms.aws",
    ],
    "rules": [
        {
            "name": "backend_support",
            "when": "cue_present",
            "cue_set_ref": "domain.backend.cues",
            "skill_set_ref": "domain.backend.skills",
            "weight_key": "responsibility_support",
        },
        {
            "name": "frontend_penalty",
            "when": "cue_absent",
            "cue_set_ref": "domain.frontend.cues",
            "skill_set_ref": "domain.frontend.skills",
            "weight_key": "weak_frontend_penalty",
        },
        {
            "name": "ml_penalty",
            "when": "cue_absent",
            "cue_set_ref": "domain.ml.cues",
            "skill_set_ref": "domain.ml.skills",
            "weight_key": "weak_ml_penalty",
        },
        {
            "name": "delivery_support",
            "when": "cue_present",
            "cue_set_ref": "domain.delivery.cues",
            "skill_set_ref": "domain.delivery.skills",
            "weight_key": "delivery_support",
        },
    ],
}
