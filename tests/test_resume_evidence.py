from __future__ import annotations

import re
from types import SimpleNamespace

from applypilot.resume.evidence import (
    SkillAliasProvider,
    TokenOverlapSimilarityProvider,
    _canonicalize_theme_label,
    build_evidence_mapping_report,
    claim_variants,
    clean_job_description_text,
    derive_job_themes,
    detect_metric_signals,
    detect_outcome_signals,
    detect_scale_signals,
    extract_evidence_items,
)
from applypilot.scoring.pdf_render_model import ResumeEntry, ResumeRenderModel, SkillSection


_WEAK_THEME_BOUNDARY_TERMS = {
    "a",
    "an",
    "and",
    "all",
    "any",
    "about",
    "around",
    "through",
    "this",
    "that",
    "these",
    "those",
    "the",
    "to",
    "for",
    "of",
    "in",
    "on",
    "by",
    "with",
    "from",
    "role",
    "team",
    "based",
    "definition",
    "passionate",
}

_THEME_BOILERPLATE_NOISE = {
    "benefits",
    "compensation",
    "salary",
    "equity",
    "location",
    "remote",
    "hybrid",
    "onsite",
    "privacy",
    "policy",
    "equal",
    "employment",
    "opportunity",
    "eeo",
    "accommodation",
    "accommodations",
}

_THEME_MEANINGFUL_TOKENS = {
    "cloud",
    "infrastructure",
    "distributed",
    "backend",
    "deployment",
    "automation",
    "ci/cd",
    "pipeline",
    "pipelines",
    "on-call",
    "reliability",
    "compute",
    "platform",
    "scalability",
    "tooling",
    "ownership",
    "operational",
    "resilience",
    "month-end",
    "close",
    "reconciliation",
    "financial",
    "reporting",
    "audit",
    "accounts",
    "payable",
    "compliance",
    "case",
    "management",
    "client",
    "advocacy",
    "crisis",
    "intervention",
    "community",
    "resources",
    "care",
    "coordination",
}


def _theme_labels(themes: list) -> list[str]:
    return [str(theme.label).strip().lower() for theme in themes]


def _assert_theme_shape_invariants(labels: list[str]) -> None:
    assert labels
    for label in labels:
        assert label
        tokens = [tok for tok in re.findall(r"[a-z0-9][a-z0-9\-/\+]*", label) if tok]
        assert tokens
        assert tokens[0] not in _WEAK_THEME_BOUNDARY_TERMS
        assert tokens[-1] not in _WEAK_THEME_BOUNDARY_TERMS
        weak_ratio = sum(1 for token in tokens if token in _WEAK_THEME_BOUNDARY_TERMS) / max(1, len(tokens))
        boilerplate_ratio = sum(1 for token in tokens if token in _THEME_BOILERPLATE_NOISE) / max(1, len(tokens))
        assert weak_ratio < 0.67
        assert boilerplate_ratio < 0.5
        assert any(token in _THEME_MEANINGFUL_TOKENS for token in tokens)


def _sample_model() -> ResumeRenderModel:
    return ResumeRenderModel(
        name="Alex Example",
        summary="Led cross-functional operations and improved cycle time by 20%.",
        skills=[
            SkillSection(category="Core", value="Workflow Design, Team Leadership, Reporting, Inventory Control, Customer Escalation, Training"),
            SkillSection(category="Ops", value="Scheduling, Vendor Coordination, Audits, Process Improvement, Safety, Compliance"),
        ],
        experience=[
            ResumeEntry(
                company="Acme Health",
                title="Operations Lead",
                compact_summary="Improved patient throughput and reduced wait times.",
                bullets=[
                    "Reduced onboarding time by 30% across three facilities.",
                    "Managed a team of 14 across multi-site operations.",
                ],
            ),
            ResumeEntry(
                company="City Care",
                title="Coordinator",
                compact_summary="Standardized service handoffs.",
                bullets=["Improved documentation quality for regulated workflows."],
            ),
        ],
        projects=[
            ResumeEntry(
                title="Coverage Redesign",
                compact_summary="Automated shift balancing across service lines.",
                bullets=["Saved $120,000 annually and cut overtime by 12 hours/week."],
            )
        ],
    )


def test_dynamic_job_themes_non_technical_are_derived_from_job_text() -> None:
    jd = """
    We are hiring a patient care coordinator to improve appointment flow,
    coordinate with nursing teams, and ensure compliance documentation quality.
    Must communicate with families and reduce scheduling delays.
    """
    themes = derive_job_themes(jd)

    assert themes
    joined = " ".join(theme.label for theme in themes).lower()
    assert "patient" in joined or "appointment" in joined or "scheduling" in joined


def test_clean_job_description_text_removes_html_artifacts() -> None:
    raw = "&lt;strong&gt;Patient Care&lt;/strong&gt; &lt;li&gt;Scheduling&lt;/li&gt; gt lt /li gt"
    cleaned = clean_job_description_text(raw)
    low = cleaned.lower()
    assert "lt" not in low
    assert "gt" not in low
    assert "/li" not in low
    assert "patient care" in low
    assert "scheduling" in low


def test_clean_job_description_text_plain_text_still_works() -> None:
    raw = "Coordinate onboarding and reduce scheduling delays."
    cleaned = clean_job_description_text(raw)
    assert cleaned == raw


def test_dynamic_job_themes_technical_follow_jd_language() -> None:
    jd = """
    Build and maintain distributed services for payments, improve API reliability,
    and automate deployment workflows across cloud infrastructure.
    """
    themes = derive_job_themes(jd)

    assert themes
    joined = " ".join(theme.label for theme in themes).lower()
    assert "distributed" in joined or "api" in joined or "deployment" in joined


def test_dynamic_job_themes_do_not_include_markup_garbage() -> None:
    jd = "&lt;li&gt;Build quality workflows&lt;/li&gt; &lt;li&gt;Ensure compliance&lt;/li&gt;"
    themes = derive_job_themes(jd)
    joined = " ".join(theme.label for theme in themes).lower()
    assert "lt" not in joined
    assert "gt" not in joined
    assert "/li" not in joined


def test_derive_job_themes_filters_affirm_like_boilerplate_and_keeps_planning_signals() -> None:
    jd = """
    This role on the Compute Platform team owns cloud infrastructure reliability for distributed backend systems.
    You will lead deployment automation, CI/CD pipeline improvements, and on-call rotation ownership.
    Build developer tooling to improve service scalability and operational resilience.
    Work cross-functionally with product and security teams to deliver platform engineering outcomes.

    Through definition of team values, all Affirm teammates are expected to be passionate about mission alignment.
    Team through collaboration, based Spain hiring entities, and this role follows local labor guidelines.
    Benefits include base pay, equity, flexible spending wallets, medical, dental, and vision.
    Equal employment opportunity, privacy policy, and accommodations statements apply.
    """
    themes = derive_job_themes(jd, max_themes=10)
    labels = _theme_labels(themes)
    joined = " ".join(labels)

    for bad in [
        "this role",
        "through definition",
        "all affirm",
        "based spain",
        "passionate about",
        "team through",
        "ownership team",
    ]:
        assert bad not in labels
        assert bad not in joined

    signal_words = {
        "cloud",
        "infrastructure",
        "distributed",
        "backend",
        "deployment",
        "automation",
        "ci/cd",
        "pipeline",
        "on-call",
        "reliability",
        "compute",
        "platform",
        "scalability",
        "tooling",
        "ownership",
    }
    assert sum(1 for token in signal_words if token in joined) >= 6
    _assert_theme_shape_invariants(labels)


def test_derive_job_themes_accountant_role_keeps_finance_signals_not_boilerplate() -> None:
    jd = """
    Own month-end close and account reconciliation for multiple entities.
    Prepare financial reporting packages and support audit preparation and compliance controls.
    Partner with accounts payable and procurement to resolve invoice discrepancies.
    This role requires cross-functional communication with finance and operations.

    We are passionate about our mission and team culture.
    Compensation includes base pay, bonus, healthcare, and retirement benefits.
    Equal employment opportunity and privacy policy statements apply.
    """
    themes = derive_job_themes(jd, max_themes=10)
    labels = _theme_labels(themes)
    joined = " ".join(labels)

    assert any("month-end close" in label or ("month-end" in label and "close" in label) for label in labels)
    assert "reconciliation" in joined
    assert "financial" in joined
    assert "reporting" in joined
    assert "audit" in joined
    assert any("accounts payable" in label or ("accounts" in label and "payable" in label) for label in labels)
    assert "compliance" in joined
    assert "passionate about" not in joined
    assert "base pay" not in joined
    assert "equal employment" not in joined
    _assert_theme_shape_invariants(labels)


def test_derive_job_themes_social_worker_role_keeps_casework_signals_not_boilerplate() -> None:
    jd = """
    Provide case management and client advocacy for families in crisis.
    Deliver crisis intervention, care coordination, and referrals to community resources.
    Collaborate with schools, healthcare providers, and housing partners on service plans.
    Maintain documentation standards and compliance with agency policies.

    Our team is passionate about purpose and values.
    Benefits include PTO, healthcare, and flexible spending accounts.
    Equal employment opportunity and accommodations statements apply.
    """
    themes = derive_job_themes(jd, max_themes=10)
    labels = _theme_labels(themes)
    joined = " ".join(labels)

    assert any("case management" in label for label in labels)
    assert "client" in joined
    assert "advocacy" in joined
    assert any("crisis intervention" in label or ("crisis" in label and "intervention" in label) for label in labels)
    assert any("community resources" in label or ("community" in label and "resources" in label) for label in labels)
    assert any("care coordination" in label or ("care" in label and "coordination" in label) for label in labels)
    assert "passionate about" not in joined
    assert "equal employment" not in joined
    _assert_theme_shape_invariants(labels)


def test_derive_job_themes_prefers_compact_labels_and_avoids_sliding_windows() -> None:
    affirm_like_jd = """
    This role on the Compute Platform team owns cloud infrastructure reliability for distributed backend systems.
    You will lead deployment automation, CI/CD pipeline improvements, and on-call rotation ownership.
    Build developer tooling to improve service scalability and operational resilience.
    Work cross-functionally with product and security teams to deliver platform engineering outcomes.

    Through definition of team values, all Affirm teammates are expected to be passionate about mission alignment.
    Team through collaboration, based Spain hiring entities, and this role follows local labor guidelines.
    Benefits include base pay, equity, flexible spending wallets, medical, dental, and vision.
    Equal employment opportunity, privacy policy, and accommodations statements apply.
    """
    themes = derive_job_themes(affirm_like_jd, max_themes=10)
    labels = _theme_labels(themes)
    assert labels

    tokenized = [re.findall(r"[a-z0-9][a-z0-9\-/\+]*", label) for label in labels]
    token_counts = [len(tokens) for tokens in tokenized]
    assert all(2 <= count <= 4 for count in token_counts)
    assert sum(1 for count in token_counts if count <= 3) >= max(4, len(token_counts) // 2)

    # Avoid adjacent-concept window artifacts.
    joined = " ".join(labels)
    forbidden = {
        "infrastructure reliability distributed",
        "automation ci/cd pipeline",
        "ci/cd pipeline improvements",
        "pipeline improvements on-call",
        "improvements on-call rotation",
    }
    assert all(bad not in labels for bad in forbidden)
    assert all(bad not in joined for bad in forbidden)

    # Avoid excessive overlap among selected labels.
    high_overlap_pairs = 0
    for idx in range(len(tokenized)):
        left = set(tokenized[idx])
        for jdx in range(idx + 1, len(tokenized)):
            right = set(tokenized[jdx])
            overlap = len(left & right) / max(1, len(left | right))
            if overlap > 0.6:
                high_overlap_pairs += 1
    assert high_overlap_pairs <= 2

    preferred_compact = {
        "cloud infrastructure reliability",
        "distributed backend systems",
        "deployment automation",
        "ci/cd pipelines",
        "on-call rotation",
        "compute platform engineering",
        "service scalability",
        "developer tooling",
    }
    compact_hits = sum(
        1 for phrase in preferred_compact if any(phrase in label or label in phrase for label in labels)
    )
    assert compact_hits >= 4
    _assert_theme_shape_invariants(labels)


def test_derive_job_themes_compact_labels_for_accounting_and_social_work() -> None:
    accountant_jd = """
    Own month-end close and account reconciliation for multiple entities.
    Prepare financial reporting packages and support audit preparation and compliance controls.
    Partner with accounts payable and procurement to resolve invoice discrepancies.
    """
    social_work_jd = """
    Provide case management and client advocacy for families in crisis.
    Deliver crisis intervention, care coordination, and referrals to community resources.
    Collaborate with schools, healthcare providers, and housing partners on service plans.
    """

    accountant_labels = _theme_labels(derive_job_themes(accountant_jd, max_themes=10))
    social_labels = _theme_labels(derive_job_themes(social_work_jd, max_themes=10))

    for labels in (accountant_labels, social_labels):
        assert labels
        counts = [len(re.findall(r"[a-z0-9][a-z0-9\-/\+]*", label)) for label in labels]
        assert all(2 <= count <= 4 for count in counts)
        assert sum(1 for count in counts if count <= 3) >= max(3, len(counts) // 2)
        _assert_theme_shape_invariants(labels)

    accountant_expected = {
        "month-end close",
        "account reconciliation",
        "financial reporting",
        "audit preparation",
        "accounts payable",
        "regulatory compliance",
    }
    social_expected = {
        "case management",
        "client advocacy",
        "crisis intervention",
        "community resources",
        "care coordination",
    }
    accountant_hits = sum(
        1 for phrase in accountant_expected if any(phrase in label or label in phrase for label in accountant_labels)
    )
    social_hits = sum(
        1 for phrase in social_expected if any(phrase in label or label in phrase for label in social_labels)
    )
    accountant_forbidden = {
        "month-end close account",
        "reporting packages support",
        "packages support audit",
        "support audit preparation",
    }
    social_forbidden = {
        "case management client",
        "management client advocacy",
        "advocacy families crisis",
        "coordination referrals community",
    }
    assert all(bad not in accountant_labels for bad in accountant_forbidden)
    assert all(bad not in social_labels for bad in social_forbidden)
    assert accountant_hits >= 4
    assert social_hits >= 4


def test_theme_label_canonicalization_flips_automation_ci_cd() -> None:
    jd = "Own CI/CD automation and deployment automation for services."
    assert _canonicalize_theme_label("automation ci/cd", jd) == "ci/cd automation"


def test_theme_label_canonicalization_keeps_good_labels_unchanged() -> None:
    jd = (
        "case management financial reporting cloud infrastructure audit preparation "
        "care coordination account reconciliation deployment automation service scalability compute platform"
    )
    labels = [
        "case management",
        "financial reporting",
        "cloud infrastructure",
        "audit preparation",
        "care coordination",
        "account reconciliation",
        "deployment automation",
        "service scalability",
        "compute platform",
    ]
    assert [_canonicalize_theme_label(label, jd) for label in labels] == labels


def test_theme_label_canonicalization_preserves_original_when_jd_has_original_order() -> None:
    jd = "This role emphasizes automation ci/cd for release quality."
    assert _canonicalize_theme_label("automation ci/cd", jd) == "automation ci/cd"


def test_theme_label_canonicalization_prefers_flipped_when_jd_has_flipped_order() -> None:
    jd = "This role emphasizes ci/cd automation for release quality."
    assert _canonicalize_theme_label("automation ci/cd", jd) == "ci/cd automation"


def test_theme_label_canonicalization_is_deterministic() -> None:
    jd = "Own ci/cd automation and cloud infrastructure reliability."
    first = _canonicalize_theme_label("automation ci/cd", jd)
    second = _canonicalize_theme_label("automation ci/cd", jd)
    assert first == second


def test_extract_evidence_items_includes_bullets_and_compact_summary_with_retention() -> None:
    model = _sample_model()
    prepared = SimpleNamespace(
        detailed_experience=[model.experience[0]],
        compact_experience=[model.experience[1]],
        projects_to_render=model.projects,
        projects_mode="selected",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="compact",
    )

    items = extract_evidence_items(model, prepared)
    paths = {item.source_path for item in items}
    retained = {item.source_path for item in items if item.is_retained_in_rendered_resume}

    assert "experience[0].bullets[0]" in paths
    assert "experience[0].compact_summary" in paths
    assert "projects[0].bullets[0]" in paths
    assert "projects[0].compact_summary" in paths
    assert "experience[0].bullets[0]" in retained


def test_similarity_provider_prefers_related_text() -> None:
    provider = TokenOverlapSimilarityProvider()
    related = provider.similarity("patient throughput improvement", "improved patient throughput by 20 percent")
    unrelated = provider.similarity("patient throughput improvement", "warehouse forklift maintenance")
    assert related > unrelated


def test_claim_coverage_uses_similarity_provider_interface() -> None:
    class ConstantProvider:
        def __init__(self) -> None:
            self.calls = 0

        def similarity(self, a: str, b: str) -> float:
            del a, b
            self.calls += 1
            return 0.2

    provider = ConstantProvider()
    model = _sample_model()
    model.skills = [SkillSection(category="Core", value="Throughput")]
    prepared = SimpleNamespace(
        detailed_experience=[model.experience[0]],
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="compact",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Improve throughput in operations.",
        model=model,
        prepared=prepared,
        similarity_provider=provider,
    )
    assert provider.calls > 0
    assert report["claim_coverage"]


def test_claim_coverage_supported_weak_and_unsupported() -> None:
    model = _sample_model()
    model.skills = [SkillSection(category="Core", value="Throughput, Kubernetes")]
    prepared = SimpleNamespace(
        detailed_experience=[model.experience[0]],
        compact_experience=[model.experience[1]],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="compact",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Improve throughput and compliance in regulated environments.",
        model=model,
        prepared=prepared,
    )
    by_claim = {item["claim"]: item for item in report["claim_coverage"]}

    assert by_claim["Throughput"]["coverage_status"] in {"weak", "weak_summary_only"}
    assert by_claim["Throughput"]["retained_primary_supporting_evidence_count"] == 0
    assert by_claim["Kubernetes"]["coverage_status"] == "unsupported"
    assert "Kubernetes" in report["unsupported_visible_claims"]


def test_claim_coverage_marks_weak_when_only_non_retained_evidence_exists() -> None:
    model = _sample_model()
    model.skills = [SkillSection(category="Core", value="Throughput")]
    prepared = SimpleNamespace(
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="hidden",
        earlier_experience_mode="grouped",
        summary_mode="compact",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Improve throughput in operations.",
        model=model,
        prepared=prepared,
    )
    by_claim = {item["claim"]: item for item in report["claim_coverage"]}
    assert by_claim["Throughput"]["coverage_status"] == "weak"
    assert "Throughput" in report["weak_visible_claims"]
    assert any(
        item["claim"] == "Throughput"
        and item["recommendation"] == "preserve_supporting_evidence_in_future_planner"
        for item in report["evidence_available_but_not_rendered"]
    )


def test_evidence_available_but_not_rendered_includes_trimmed_bullet_candidates() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Core", value="Docker")],
        experience=[
            ResumeEntry(
                company="Acme",
                title="Engineer",
                bullets=["Built Java APIs.", "Improved test reliability."],
            ),
            ResumeEntry(
                company="Beta",
                title="Engineer II",
                bullets=[
                    "Built CI pipelines.",
                    "Improved deployment checks.",
                    "Containerized services with Docker for deployment consistency.",
                ],
            ),
        ],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
        detailed_bullet_cap=2,
    )

    report = build_evidence_mapping_report(
        job_description="Containerized services and deployment reliability.",
        model=model,
        prepared=prepared,
    )
    evidence_by_claim = {item["claim"]: item for item in report["evidence_available_but_not_rendered"]}
    docker = evidence_by_claim.get("Docker")
    assert docker is not None
    assert docker["source_primary_evidence_count"] >= 1
    assert docker["retained_primary_evidence_count"] == 0
    assert docker["candidate_evidence_items"]
    assert any(
        item["source_path"] == "experience[1].bullets[2]" and item["reason_not_rendered"] == "bullet_trimmed"
        for item in docker["candidate_evidence_items"]
    )


def test_claim_coverage_summary_only_is_not_supported() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        summary="Hands-on with Kubernetes and operations reliability.",
        skills=[SkillSection(category="Core", value="Kubernetes")],
        experience=[],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="hidden",
        earlier_experience_mode="grouped",
        summary_mode="compact",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Kubernetes platform operations.",
        model=model,
        prepared=prepared,
    )
    by_claim = {item["claim"]: item for item in report["claim_coverage"]}
    assert by_claim["Kubernetes"]["coverage_status"] == "weak_summary_only"
    assert by_claim["Kubernetes"]["retained_primary_supporting_evidence_count"] == 0


def test_compound_claim_not_supported_when_distinctive_subclaim_missing() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Core", value="AWS (EC2, S3, Lambda, Route53)")],
        experience=[
            ResumeEntry(
                company="Acme",
                title="Engineer",
                bullets=["Built AWS EC2 and Lambda services with Route53 traffic management."],
            )
        ],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="AWS platform engineering.",
        model=model,
        prepared=prepared,
    )
    by_claim = {item["claim"]: item for item in report["claim_coverage"]}
    aws_group = by_claim["AWS (EC2, S3, Lambda, Route53)"]
    assert aws_group["coverage_status"] != "supported"
    assert sorted(aws_group["distinctive_tokens_required"]) == ["ec2", "lambda", "route53", "s3"]
    assert sorted(aws_group["distinctive_tokens_matched"]) == ["ec2", "lambda", "route53"]


def test_distributed_systems_supported_by_concept_context_match() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Core", value="Distributed Systems")],
        experience=[
            ResumeEntry(
                company="Acme",
                title="Engineer",
                bullets=["Developed distributed services that produced and consumed events to orchestrate transactional workflows."],
            )
        ],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Distributed backend architecture ownership.",
        model=model,
        prepared=prepared,
    )
    by_claim = {item["claim"]: item for item in report["claim_coverage"]}
    assert by_claim["Distributed Systems"]["coverage_status"] == "supported"
    assert "concept_support" in by_claim["Distributed Systems"]["support_match_methods"]


def test_distributed_systems_not_supported_by_irrelevant_distributed_phrase() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Core", value="Distributed Systems")],
        experience=[
            ResumeEntry(
                company="Acme",
                title="Coordinator",
                bullets=["Distributed weekly reports to stakeholders and coordinated team responsibilities."],
            )
        ],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Distributed backend architecture ownership.",
        model=model,
        prepared=prepared,
    )
    by_claim = {item["claim"]: item for item in report["claim_coverage"]}
    assert by_claim["Distributed Systems"]["coverage_status"] != "supported"


def test_claim_variants_handle_versions_and_parentheses() -> None:
    assert "Java" in claim_variants("Java 17-21")
    assert "Spring Boot" in claim_variants("Spring Boot 3.x")
    vars_aws = claim_variants("AWS (EC2, S3, Lambda, Route53)")
    assert "AWS" in vars_aws
    assert "EC2" in vars_aws
    assert "S3" in vars_aws
    assert "Lambda" in vars_aws
    assert "Route53" in vars_aws
    assert "AWS (EC2" not in vars_aws
    assert "Route53)" not in vars_aws


def test_claim_variants_hyphenated_forms_generate_space_variants() -> None:
    assert "event driven architecture" in claim_variants("Event-Driven Architecture")
    assert "patient centered care" in claim_variants("Patient-Centered Care")
    assert "cross functional coordination" in claim_variants("Cross-Functional Coordination")
    assert "data driven reporting" in claim_variants("Data-Driven Reporting")


def test_claim_variants_slash_forms_generate_useful_variants_without_noise() -> None:
    ci = claim_variants("CI/CD")
    assert "CI/CD" in ci
    assert any(item.lower() == "ci cd" for item in ci)
    assert "CI" in ci
    assert "CD" in ci
    ap_ar = claim_variants("AP/AR")
    assert "AP/AR" in ap_ar
    assert any(item.lower() == "ap ar" for item in ap_ar)
    assert "AP" in ap_ar
    assert "AR" in ap_ar
    assert "A" not in ap_ar
    assert "R" not in ap_ar


def test_extract_visible_skill_claims_preserves_slash_phrase_with_following_word() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Delivery", value="Java 17-21, CI/CD Automation, GitHub Actions")],
        experience=[ResumeEntry(company="Acme", title="Engineer", bullets=["Built CI/CD automation workflows."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(job_description="Build delivery automation.", model=model, prepared=prepared)
    claims = [item["claim"] for item in report["claim_coverage"]]
    assert "CI/CD Automation" in claims
    assert "Automation" not in claims
    assert "CI/CD" not in claims

    variants = claim_variants("CI/CD Automation")
    assert "CI/CD Automation" in variants
    assert "Automation" not in variants
    assert "CI" not in variants
    assert "CD Automation" not in variants


def test_claim_coverage_versioned_skill_matches_primary_evidence() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Core", value="Java 17-21")],
        experience=[ResumeEntry(company="Acme", title="Engineer", bullets=["Built Java services for high-volume operations."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Build Java services.",
        model=model,
        prepared=prepared,
    )
    by_claim = {item["claim"]: item for item in report["claim_coverage"]}
    assert by_claim["Java 17-21"]["coverage_status"] == "supported"


def test_alias_provider_is_isolated_and_expandable() -> None:
    aliases = SkillAliasProvider()
    expanded = aliases.expand("Apache Kafka")
    assert "kafka" in expanded


def test_alias_provider_supports_tdd_and_e2e_pairs() -> None:
    aliases = SkillAliasProvider()
    assert "test driven development" in aliases.expand("tdd")
    assert "tdd" in aliases.expand("test driven development")
    assert "end to end" in aliases.expand("e2e")
    assert "e2e" in aliases.expand("end to end")


def test_distinctive_token_vendor_claim_requires_vendor_not_generic_ci() -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Jenkins CI")],
        experience=[ResumeEntry(company="Acme", title="Engineer", bullets=["Established CI/test gates and peer review cadences."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(job_description="Own Jenkins CI pipelines.", model=model, prepared=prepared)
    claim = report["claim_coverage"][0]
    assert claim["coverage_status"] in {"weak", "unsupported"}
    assert "jenkins" in claim["distinctive_tokens_required"]
    assert "jenkins" not in claim["distinctive_tokens_matched"]


def test_distinctive_token_vendor_claim_supported_when_vendor_is_present() -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="Jenkins CI")],
        experience=[ResumeEntry(company="Acme", title="Engineer", bullets=["Built Jenkins pipeline jobs and release gates."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(job_description="Own Jenkins CI pipelines.", model=model, prepared=prepared)
    claim = report["claim_coverage"][0]
    assert claim["coverage_status"] == "supported"
    assert "jenkins" in claim["distinctive_tokens_matched"]


def test_gitlab_ci_requires_gitlab_not_generic_ci_only() -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="GitLab CI")],
        experience=[ResumeEntry(company="Acme", title="Engineer", bullets=["Improved CI/CD quality gates and test reliability."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(job_description="Own GitLab CI pipelines.", model=model, prepared=prepared)
    assert report["claim_coverage"][0]["coverage_status"] in {"weak", "unsupported"}


def test_aws_s3_requires_s3_not_generic_aws_only() -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="AWS S3")],
        experience=[ResumeEntry(company="Acme", title="Engineer", bullets=["Automated AWS deployment workflows."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(job_description="Manage S3 storage and lifecycle.", model=model, prepared=prepared)
    assert report["claim_coverage"][0]["coverage_status"] in {"weak", "unsupported"}


def test_postgresql_requires_postgresql_not_generic_sql() -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="PostgreSQL")],
        experience=[ResumeEntry(company="Acme", title="Engineer", bullets=["Designed SQL schemas and tuned query plans."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(job_description="Own PostgreSQL reliability and migrations.", model=model, prepared=prepared)
    assert report["claim_coverage"][0]["coverage_status"] in {"weak", "unsupported"}


def test_postgresql_supported_when_postgresql_is_present() -> None:
    model = ResumeRenderModel(
        skills=[SkillSection(category="Core", value="PostgreSQL")],
        experience=[ResumeEntry(company="Acme", title="Engineer", bullets=["Owned PostgreSQL schema migrations and performance tuning."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(job_description="Own PostgreSQL reliability and migrations.", model=model, prepared=prepared)
    assert report["claim_coverage"][0]["coverage_status"] == "supported"


def test_signal_detection_covers_metric_scale_and_outcome() -> None:
    text = "Improved turnaround by 17%, saved $25,000, and reduced time by 12 hours/week across multi-site enterprise operations."
    assert detect_metric_signals(text)
    assert detect_scale_signals(text)
    assert detect_outcome_signals(text)


def test_top_supporting_evidence_prefers_primary_over_summary() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        summary="Kubernetes operations lead.",
        skills=[SkillSection(category="Core", value="Kubernetes")],
        experience=[ResumeEntry(company="Acme", title="Engineer", bullets=["Delivered Kubernetes reliability improvements."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="compact",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Kubernetes operations.",
        model=model,
        prepared=prepared,
    )
    first = report["claim_coverage"][0]["top_supporting_evidence"][0]
    assert first.startswith("Acme:")


def test_top_supporting_evidence_prefers_retained_over_non_retained_primary() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Core", value="Compliance")],
        experience=[
            ResumeEntry(company="Retained Co", title="Lead", bullets=["Improved compliance workflows."]),
            ResumeEntry(company="Hidden Co", title="Lead", bullets=["Managed compliance processes."]),
        ],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=[model.experience[0]],
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Compliance ownership and process quality.",
        model=model,
        prepared=prepared,
    )
    first = report["claim_coverage"][0]["top_supporting_evidence"][0]
    assert first.startswith("Retained Co:")


def test_top_supporting_evidence_prefers_signal_rich_when_similarity_close() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Core", value="Automation")],
        experience=[
            ResumeEntry(company="Alpha", title="Lead", bullets=["Built automation workflows for service operations."]),
            ResumeEntry(company="Beta", title="Lead", bullets=["Automated workflows and reduced cycle time by 25%."]),
        ],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    class NearTieProvider:
        def similarity(self, a: str, b: str) -> float:
            del a
            return 0.4 if "workflows" in b.lower() else 0.0

    report = build_evidence_mapping_report(
        job_description="Workflow automation improvements.",
        model=model,
        prepared=prepared,
        similarity_provider=NearTieProvider(),
    )
    first = report["claim_coverage"][0]["top_supporting_evidence"][0]
    assert first.startswith("Beta:")


def test_alias_matching_supports_kafka_and_jenkins_ci_claims() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Core", value="Apache Kafka, Jenkins CI")],
        experience=[
            ResumeEntry(company="Acme", title="Engineer", bullets=["Built Kafka pipelines and maintained Jenkins jobs."]),
        ],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Operate data pipelines and CI systems.",
        model=model,
        prepared=prepared,
    )
    by_claim = {item["claim"]: item for item in report["claim_coverage"]}
    assert by_claim["Apache Kafka"]["coverage_status"] == "supported"
    assert by_claim["Jenkins CI"]["coverage_status"] == "supported"


def test_compound_phrase_claim_supported_by_retained_primary_evidence() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Core", value="Event-Driven Architecture")],
        experience=[ResumeEntry(company="Acme", title="Engineer", bullets=["Built event-driven microservices for payments workflows."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Design event-driven systems and architecture.",
        model=model,
        prepared=prepared,
    )
    by_claim = {item["claim"]: item for item in report["claim_coverage"]}
    assert by_claim["Event-Driven Architecture"]["coverage_status"] == "supported"


def test_compound_phrase_claim_not_supported_by_only_generic_word_overlap() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Core", value="Data-Driven Reporting")],
        experience=[ResumeEntry(company="Acme", title="Analyst", bullets=["Owned reporting cadences and stakeholder updates."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Data-driven reporting and measurement.",
        model=model,
        prepared=prepared,
    )
    by_claim = {item["claim"]: item for item in report["claim_coverage"]}
    assert by_claim["Data-Driven Reporting"]["coverage_status"] in {"weak", "unsupported"}


def test_compound_phrase_summary_only_is_not_supported() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        summary="Led event-driven architecture initiatives.",
        skills=[SkillSection(category="Core", value="Event-Driven Architecture")],
        experience=[],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="hidden",
        earlier_experience_mode="grouped",
        summary_mode="compact",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Event-driven workflows and architecture.",
        model=model,
        prepared=prepared,
    )
    by_claim = {item["claim"]: item for item in report["claim_coverage"]}
    assert by_claim["Event-Driven Architecture"]["coverage_status"] == "weak_summary_only"


def test_duplicate_visible_skills_generate_single_claim_coverage_entry() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Core", value="Java, Java, Spring Boot 3.x, Spring Boot 3.x")],
        experience=[ResumeEntry(company="Acme", title="Engineer", bullets=["Built Java Spring Boot services."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Build Java Spring services.",
        model=model,
        prepared=prepared,
    )
    claims = [item["claim"] for item in report["claim_coverage"]]
    assert claims.count("Java") == 1
    assert claims.count("Spring Boot 3.x") == 1


def test_report_quality_has_no_malformed_or_duplicate_claim_entries() -> None:
    model = ResumeRenderModel(
        name="Alex Example",
        skills=[SkillSection(category="Core", value="AWS (EC2, S3, Lambda, Route53), AWS (EC2, S3, Lambda, Route53)")],
        experience=[ResumeEntry(company="Acme", title="Engineer", bullets=["Used AWS EC2 and S3 in production."])],
        projects=[],
    )
    prepared = SimpleNamespace(
        detailed_experience=model.experience,
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="detailed",
        earlier_experience_mode="compact",
        summary_mode="hidden",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Cloud operations experience.",
        model=model,
        prepared=prepared,
    )
    claims = [item["claim"] for item in report["claim_coverage"]]
    assert len(claims) == len(set(claims))
    assert not any("(" in c and ")" not in c for c in claims)
    assert not any(")" in c and "(" not in c for c in claims)
    assert len(report["unsupported_visible_claims"]) == len(set(report["unsupported_visible_claims"]))
    assert len(report["weak_visible_claims"]) == len(set(report["weak_visible_claims"]))


def test_theme_labels_avoid_stemmed_truncated_artifacts() -> None:
    jd = """
    Preferred experience building operations processes.
    Build operations correctness checks and preferred experience in reporting.
    """
    themes = derive_job_themes(jd)
    labels = [theme.label.lower() for theme in themes]
    assert "experience build" not in labels
    assert "preferr experience" not in labels
    assert "build operat" not in labels
    assert not any(re.search(r"\bcorrectnes\b", label) for label in labels)


def test_theme_labels_filter_benefits_and_legal_boilerplate() -> None:
    jd = """
    Affirm offers excellent benefits, flexible time off, base pay transparency, and
    flexible spending wallets. We are an equal employment opportunity employer.
    You will design resilient backend services and improve API reliability.
    """
    themes = derive_job_themes(jd)
    labels = [theme.label.lower() for theme in themes]
    joined = " ".join(labels)
    assert "time off" not in joined
    assert "base pay" not in joined
    assert "flexible spending" not in joined
    assert "equal employment" not in joined
    assert "affirm s" not in joined
    assert "backend services" in joined or "api reliability" in joined or "resilient backend" in joined


def test_strong_unused_evidence_is_reported_when_not_retained() -> None:
    model = _sample_model()
    model.skills = [SkillSection(category="Core", value="Throughput, Compliance")]
    prepared = SimpleNamespace(
        detailed_experience=[],
        compact_experience=[],
        projects_to_render=[],
        projects_mode="hidden",
        experience_mode="hidden",
        earlier_experience_mode="grouped",
        summary_mode="compact",
        skills_mode="selected",
        selected_skills_max_lines=1,
    )
    report = build_evidence_mapping_report(
        job_description="Need measurable operational improvements in regulated multi-site workflows.",
        model=model,
        prepared=prepared,
    )
    assert report["strong_unused_evidence"]
    first = report["strong_unused_evidence"][0]
    assert first["matched_theme_ids"]
    assert first["signals"]["metric"] or first["signals"]["scale"] or first["signals"]["outcome"]
