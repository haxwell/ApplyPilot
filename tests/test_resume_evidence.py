from __future__ import annotations

import re
from types import SimpleNamespace

from applypilot.resume.evidence import (
    SkillAliasProvider,
    TokenOverlapSimilarityProvider,
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
