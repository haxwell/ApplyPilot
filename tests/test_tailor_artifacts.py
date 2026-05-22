from __future__ import annotations

import json
from pathlib import Path

from applypilot.scoring import tailor


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.committed = False

    def execute(self, query: str, params: tuple = ()) -> "_FakeConnection":
        self.calls.append((query, params))
        return self

    def commit(self) -> None:
        self.committed = True


def _make_job(url: str = "https://example.com/job/1") -> dict:
    return {
        "url": url,
        "title": "Staff Software Engineer - AI II",
        "site": "Thomson Reuters",
        "location": "Remote",
        "fit_score": 9,
        "full_description": "Build production AI systems.",
    }


def _approved_report() -> dict:
    return {
        "attempts": 1,
        "validator": {"passed": True, "errors": [], "warnings": []},
        "judge": {"passed": True, "verdict": "PASS", "issues": "none"},
        "status": "approved",
    }


def test_build_tailored_prefix_is_deterministic_and_unique_per_url() -> None:
    base = _make_job("https://example.com/job/1")
    same = _make_job("https://example.com/job/1")
    other = _make_job("https://example.com/job/2")

    first = tailor._build_tailored_prefix(base)
    second = tailor._build_tailored_prefix(same)
    third = tailor._build_tailored_prefix(other)

    assert first == second
    assert first != third
    assert first.startswith("Thomson_Reuters_Staff_Software_Engineer_-_AI_II_")


def test_run_tailoring_requires_pdf_for_submission(monkeypatch, tmp_path: Path) -> None:
    conn = _FakeConnection()
    job = _make_job()

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", _approved_report()))

    def _fake_convert_to_pdf(text_path: Path, output_path: Path | None = None, **_kwargs) -> Path:
        out = output_path or Path(text_path).with_suffix(".pdf")
        out = Path(out)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out

    monkeypatch.setattr("applypilot.scoring.pdf.convert_to_pdf", _fake_convert_to_pdf)

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")

    assert result["approved"] == 1
    assert result["errors"] == 0
    txts = list(tmp_path.glob("*.txt"))
    pdfs = list(tmp_path.glob("*.pdf"))
    assert any(not p.name.endswith("_JOB.txt") for p in txts)
    assert len(pdfs) == 1
    assert any("tailored_resume_path" in query for query, _ in conn.calls)
    assert conn.committed


def test_run_tailoring_uses_custom_output_name_for_single_job(monkeypatch, tmp_path: Path) -> None:
    conn = _FakeConnection()
    job = _make_job()

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", _approved_report()))

    def _fake_convert_to_pdf(text_path: Path, output_path: Path | None = None, **_kwargs) -> Path:
        out = output_path or Path(text_path).with_suffix(".pdf")
        out = Path(out)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out

    monkeypatch.setattr("applypilot.scoring.pdf.convert_to_pdf", _fake_convert_to_pdf)

    result = tailor.run_tailoring(
        min_score=7,
        limit=1,
        validation_mode="normal",
        output_name="OUTPUT",
    )

    assert result["approved"] == 1
    assert (tmp_path / "OUTPUT.txt").exists()
    assert (tmp_path / "OUTPUT.pdf").exists()
    assert (tmp_path / "OUTPUT_REPORT.json").exists()
    assert (tmp_path / "OUTPUT_JOB.txt").exists()


def test_run_tailoring_does_not_persist_when_pdf_generation_fails(monkeypatch, tmp_path: Path) -> None:
    conn = _FakeConnection()
    job = _make_job()

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", _approved_report()))
    monkeypatch.setattr(
        "applypilot.scoring.pdf.convert_to_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")

    assert result["approved"] == 0
    assert result["errors"] == 1
    assert any(not p.name.endswith("_JOB.txt") for p in tmp_path.glob("*.txt"))
    assert not any("tailored_resume_path" in query for query, _ in conn.calls)
    assert any("tailor_attempts=COALESCE(tailor_attempts,0)+1" in query for query, _ in conn.calls)
    assert conn.committed


def test_run_tailoring_prefers_structured_pdf_render_when_tailored_json_available(monkeypatch, tmp_path: Path) -> None:
    conn = _FakeConnection()
    job = _make_job()
    structured_called = {"value": False}

    report = _approved_report()
    report["tailored_json"] = {
        "title": "Staff Software Engineer - AI II",
        "summary": "Summary",
        "skills": {"Languages": "Python"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, template_name, html_only
        structured_called["value"] = True
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {
            "template_used": "professional_compact",
            "page_target_config": 2.5,
            "allowed_physical_pages": 3,
            "measured_pages_final": 2,
            "planning_attempts": [{"detailed_experience_count": 4, "measured_page_count": 2, "fit": True}],
            "detailed_roles": ["Example"],
            "earlier_selected_roles": [],
        }

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )
    monkeypatch.setattr(
        "applypilot.scoring.pdf.convert_to_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fallback should not be used")),
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")

    assert result["approved"] == 1
    assert structured_called["value"] is True
    assert any("tailored_resume_path" in query for query, _ in conn.calls)
    report_paths = list(tmp_path.glob("*_REPORT.json"))
    assert len(report_paths) == 1
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    assert report_data["pdf_render_planning"]["template_used"] == "professional_compact"
    assert report_data["pdf_render_planning"]["allowed_physical_pages"] == 3
    assert report_data["pdf_render_planning"]["measured_pages_final"] == 2
    assert report_data["skills_selection"]["before_count"] >= report_data["skills_selection"]["after_count"]
    assert isinstance(report_data["skills_selection"]["dropped_skills"], list)


def test_run_tailoring_reports_skills_count_diagnostics_with_validator_scope(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = _FakeConnection()
    job = _make_job()
    report = _approved_report()
    report["validator"]["skills_item_count"] = 28
    report["validator"]["warnings"] = [
        "Skills section may be too broad: 28 skills; prefer 12-20 and max 24 unless the job requires a broad stack."
    ]
    report["tailored_json"] = {
        "title": "Staff Software Engineer - AI II",
        "summary": "Summary",
        "skills": {"Core": "A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P, Q, R, S, T, U, V, W, X, Y, Z, AA, AB"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, template_name, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {
            "template_used": "professional_compact",
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [
                {"claim": "Java"},
                {"claim": "Spring Boot"},
                {"claim": "Kafka"},
            ],
        }

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")
    assert result["approved"] == 1

    report_paths = list(tmp_path.glob("*_REPORT.json"))
    assert len(report_paths) == 1
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    diagnostics = report_data["skills_count_diagnostics"]
    assert diagnostics["tailored_json_skill_count"] == 28
    assert diagnostics["rendered_visible_skill_count"] == 3
    assert diagnostics["validator_skills_item_count"] == 28
    assert diagnostics["validator_count_scope"] == "tailored_json_skills"
    assert diagnostics["rendered_visible_skill_names"] == ["Java", "Spring Boot", "Kafka"]
    assert "skills_warning_context" in report_data
    assert report_data["validator_warning_scope"] == "tailored_json"
    assert report_data["validator_warnings_tailored_json"]
    assert report_data["validator_warnings_rendered_resume"] == []


def test_run_tailoring_marks_needs_review_when_final_weak_claims_lack_retained_primary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = _FakeConnection()
    job = _make_job()
    report = _approved_report()
    report["tailored_json"] = {
        "title": "Staff Software Engineer - AI II",
        "summary": "Summary",
        "skills": {"Core": "Docker, Kubernetes, Java"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, template_name, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {
            "template_used": "professional_compact",
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [
                {
                    "claim": "Kubernetes",
                    "coverage_status": "weak",
                    "retained_primary_supporting_evidence_count": 0,
                }
            ],
            "unsupported_visible_claims_final": [],
            "weak_visible_claims_final": ["Kubernetes"],
        }

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")
    assert result["approved"] == 0
    assert result["failed"] == 1

    report_paths = list(tmp_path.glob("*_REPORT.json"))
    assert len(report_paths) == 1
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    assert report_data["status"] == "needs_review"
    assert "Kubernetes" in report_data["unresolved_weak_claims_without_retained_primary"]


def test_run_tailoring_marks_needs_review_when_final_unsupported_claims_remain(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = _FakeConnection()
    job = _make_job()
    report = _approved_report()
    report["tailored_json"] = {
        "title": "Staff Software Engineer - AI II",
        "summary": "Summary",
        "skills": {"Core": "AWS S3, Java"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, template_name, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {
            "template_used": "professional_compact",
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [
                {
                    "claim": "AWS S3",
                    "coverage_status": "unsupported",
                    "retained_primary_supporting_evidence_count": 0,
                }
            ],
            "unsupported_visible_claims_final": ["AWS S3"],
            "weak_visible_claims_final": [],
        }

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")
    assert result["approved"] == 0
    assert result["failed"] == 1

    report_paths = list(tmp_path.glob("*_REPORT.json"))
    assert len(report_paths) == 1
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    assert report_data["status"] == "needs_review"
    assert report_data["unsupported_visible_claims_final"] == ["AWS S3"]


def test_run_tailoring_flags_high_specificity_claim_provenance_risk(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = _FakeConnection()
    job = _make_job()
    report = _approved_report()
    report["tailored_json"] = {
        "title": "Senior Engineer",
        "summary": "Summary",
        "skills": {"Core": "Kubernetes, Java"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume with Java services only")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, template_name, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {
            "template_used": "professional_compact",
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [
                {
                    "claim": "Kubernetes",
                    "coverage_status": "supported",
                    "retained_primary_supporting_evidence_count": 1,
                    "supporting_evidence_match_reasons": [
                        {
                            "source_label": "Example Corp",
                            "source_path": "experience[0].bullets[0]",
                            "reason": "direct_phrase_match",
                            "text": "Built automation with Kubernetes and GitHub Actions for releases.",
                        }
                    ],
                },
                {
                    "claim": "Java",
                    "coverage_status": "supported",
                    "retained_primary_supporting_evidence_count": 1,
                    "supporting_evidence_match_reasons": [
                        {
                            "source_label": "Example Corp",
                            "source_path": "experience[0].bullets[1]",
                            "reason": "direct_phrase_match",
                            "text": "Built Java services.",
                        }
                    ],
                },
            ],
            "unsupported_visible_claims_final": [],
            "weak_visible_claims_final": [],
        }

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")
    assert result["approved"] == 1

    report_paths = list(tmp_path.glob("*_REPORT.json"))
    assert len(report_paths) == 1
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    assert report_data["status"] == "approved_with_warnings"
    planning = report_data["pdf_render_planning"]
    risks = planning.get("high_specificity_claim_provenance_risks", [])
    assert any(item.get("claim") == "Kubernetes" for item in risks)


def test_run_tailoring_marks_docker_as_source_keyword_and_rendered(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = _FakeConnection()
    job = _make_job()
    report = _approved_report()
    report["tailored_json"] = {
        "title": "Senior Engineer",
        "summary": "Summary",
        "skills": {"Core": "Docker, Java"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }

    source_resume = (
        "Alex Example\n"
        "Senior Engineer\n"
        "SUMMARY\n"
        "Built reliable backend services.\n"
        "TECHNICAL SKILLS\n"
        "Core: Docker, Java\n"
        "EXPERIENCE\n"
        "Engineer\n"
        "Example | 2020-2024\n"
        "- Built Java services.\n"
    )

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: source_resume)
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, template_name, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {
            "template_used": "professional_compact",
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [
                {
                    "claim": "Docker",
                    "coverage_status": "supported",
                    "primary_supporting_evidence_count": 1,
                    "retained_primary_supporting_evidence_count": 1,
                    "supporting_evidence_match_reasons": [
                        {
                            "source_label": "Savvato",
                            "source_path": "experience[0].bullets[0]",
                            "reason": "direct_phrase_match",
                            "text": "Implemented deployment automation with Docker and AWS tooling.",
                        }
                    ],
                }
            ],
            "unsupported_visible_claims_final": [],
            "weak_visible_claims_final": [],
        }

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")
    assert result["approved"] == 1

    report_paths = list(tmp_path.glob("*_REPORT.json"))
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    planning = report_data["pdf_render_planning"]
    docker = next(item for item in planning["claim_coverage"] if item["claim"] == "Docker")
    assert docker["support_provenance_status"] == "source_keyword_and_rendered"
    assert docker["source_resume_keyword_support_count"] >= 1
    assert docker["rendered_primary_support_count"] >= 1


def test_run_tailoring_marks_aws_subclaim_as_source_primary_and_rendered(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = _FakeConnection()
    job = _make_job()
    report = _approved_report()
    report["tailored_json"] = {
        "title": "Senior Engineer",
        "summary": "Summary",
        "skills": {"Core": "AWS EC2, AWS Lambda, Route53"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }

    source_resume = (
        "Alex Example\n"
        "Senior Engineer\n"
        "SUMMARY\n"
        "Built reliable backend services.\n"
        "TECHNICAL SKILLS\n"
        "Core: AWS EC2, AWS Lambda, Route53\n"
        "EXPERIENCE\n"
        "Engineer\n"
        "Savvato | 2020-2024\n"
        "- Built automated deployment workflows using AWS EC2, Lambda, Route53, and DNS automation.\n"
    )

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: source_resume)
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, template_name, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {
            "template_used": "professional_compact",
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [
                {
                    "claim": "AWS Route53",
                    "coverage_status": "supported",
                    "primary_supporting_evidence_count": 1,
                    "retained_primary_supporting_evidence_count": 1,
                    "supporting_evidence_match_reasons": [
                        {
                            "source_label": "Savvato",
                            "source_path": "experience[0].bullets[0]",
                            "reason": "direct_phrase_match",
                            "text": "Built automated deployment workflows using AWS EC2, Lambda, Route53, and DNS automation.",
                        }
                    ],
                }
            ],
            "unsupported_visible_claims_final": [],
            "weak_visible_claims_final": [],
        }

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")
    assert result["approved"] == 1

    report_paths = list(tmp_path.glob("*_REPORT.json"))
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    planning = report_data["pdf_render_planning"]
    claim = next(item for item in planning["claim_coverage"] if item["claim"] == "AWS Route53")
    assert claim["support_provenance_status"] == "source_primary_and_rendered"
    assert claim["source_resume_primary_support_count"] >= 1
    assert claim["rendered_primary_support_count"] >= 1


def test_run_tailoring_relabels_removed_claim_reason_when_source_keyword_exists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = _FakeConnection()
    job = _make_job()
    report = _approved_report()
    report["tailored_json"] = {
        "title": "Senior Engineer",
        "summary": "Summary",
        "skills": {"Core": "Java"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }
    source_resume = (
        "Alex Example\n"
        "Senior Engineer\n"
        "SUMMARY\n"
        "Built backend systems.\n"
        "TECHNICAL SKILLS\n"
        "Core: Docker, Java\n"
        "EXPERIENCE\n"
        "Engineer\n"
        "Example | 2020-2024\n"
        "- Built Java services.\n"
    )

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: source_resume)
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, template_name, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {
            "template_used": "professional_compact",
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Java", "coverage_status": "supported", "retained_primary_supporting_evidence_count": 1}],
            "unsupported_visible_claims_final": [],
            "weak_visible_claims_final": [],
            "final_weak_or_unsupported_claim_dispositions": [
                {
                    "claim": "Docker",
                    "coverage_status": "unsupported",
                    "final_action": "removed",
                    "reason": "unsupported_no_replacement_no_source_evidence",
                }
            ],
        }

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")
    assert result["approved"] == 1
    report_paths = list(tmp_path.glob("*_REPORT.json"))
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    dispositions = report_data["pdf_render_planning"]["final_weak_or_unsupported_claim_dispositions"]
    docker = next(item for item in dispositions if item.get("claim") == "Docker")
    assert docker["reason"] == "source_keyword_only_no_rendered_primary_evidence"


def test_run_tailoring_updates_unsupported_skill_removal_reason_and_provenance(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = _FakeConnection()
    job = _make_job()
    report = _approved_report()
    report["tailored_json"] = {
        "title": "Senior Engineer",
        "summary": "Summary",
        "skills": {"Core": "Java"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }
    source_resume = (
        "Alex Example\n"
        "Senior Engineer\n"
        "SUMMARY\n"
        "Built backend systems.\n"
        "TECHNICAL SKILLS\n"
        "Core: AWS S3, Java\n"
        "EXPERIENCE\n"
        "Engineer\n"
        "Example | 2020-2024\n"
        "- Built Java services.\n"
    )

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: source_resume)
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, template_name, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {
            "template_used": "professional_compact",
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Java", "coverage_status": "supported", "retained_primary_supporting_evidence_count": 1}],
            "unsupported_visible_claims_final": [],
            "weak_visible_claims_final": [],
            "unsupported_skill_removals": [
                {
                    "claim": "AWS S3",
                    "coverage_status": "unsupported",
                    "kept": True,
                    "reason": "unsupported_visible_claim_no_supported_replacement_no_source_evidence",
                }
            ],
        }

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")
    assert result["approved"] == 1
    report_paths = list(tmp_path.glob("*_REPORT.json"))
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    removals = report_data["pdf_render_planning"]["unsupported_skill_removals"]
    aws_s3 = next(item for item in removals if item.get("claim") == "AWS S3")
    assert aws_s3["reason"] == "source_keyword_only_no_rendered_primary_evidence"
    assert aws_s3["source_keyword_support_count"] >= 1
    assert aws_s3["source_primary_support_count"] == 0
    assert aws_s3["rendered_primary_support_count"] == 0
    assert aws_s3["support_provenance_status"] == "unsupported"


def test_removed_source_keyword_claim_uses_provenance_reason_in_planning_operations(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = _FakeConnection()
    job = _make_job()
    report = _approved_report()
    report["tailored_json"] = {
        "title": "Senior Engineer",
        "summary": "Summary",
        "skills": {"Core": "Java"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }
    source_resume = (
        "Alex Example\n"
        "Senior Engineer\n"
        "TECHNICAL SKILLS\n"
        "Core: Docker, Java\n"
        "EXPERIENCE\n"
        "Engineer\n"
        "Example | 2020-2024\n"
        "- Built Java services.\n"
    )

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: source_resume)
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, template_name, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {
            "template_used": "professional_compact",
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [{"claim": "Java", "coverage_status": "supported", "retained_primary_supporting_evidence_count": 1}],
            "unsupported_visible_claims_final": [],
            "weak_visible_claims_final": [],
            "planning_operations": [
                {
                    "step": "unsupported_skill_removal",
                    "claim": "Docker",
                    "reason": "unsupported_visible_claim_no_supported_replacement_no_source_evidence",
                }
            ],
            "unsupported_skill_removals": [
                {
                    "claim": "Docker",
                    "coverage_status": "unsupported",
                    "kept": True,
                    "reason": "unsupported_visible_claim_no_supported_replacement_no_source_evidence",
                }
            ],
            "final_weak_or_unsupported_claim_dispositions": [
                {
                    "claim": "Docker",
                    "coverage_status": "unsupported",
                    "final_action": "removed",
                    "reason": "unsupported_no_replacement_no_source_evidence",
                }
            ],
        }

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")
    assert result["approved"] == 1
    report_paths = list(tmp_path.glob("*_REPORT.json"))
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    planning = report_data["pdf_render_planning"]

    op = next(
        item
        for item in planning.get("planning_operations", [])
        if item.get("step") == "unsupported_skill_removal" and item.get("claim") == "Docker"
    )
    removal = next(item for item in planning.get("unsupported_skill_removals", []) if item.get("claim") == "Docker")
    disposition = next(
        item
        for item in planning.get("final_weak_or_unsupported_claim_dispositions", [])
        if item.get("claim") == "Docker"
    )

    expected = "source_keyword_only_no_rendered_primary_evidence"
    assert op.get("reason") == expected
    assert removal.get("reason") == expected
    assert disposition.get("reason") == expected
    assert "no_source_evidence" not in str(op.get("reason", ""))


def test_run_tailoring_marks_approved_with_warnings_when_rendered_validator_warnings_exist(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = _FakeConnection()
    job = _make_job()
    report = _approved_report()
    report["validator"]["warnings"] = ["Rendered layout warning: possible overlap in skills row"]
    report["tailored_json"] = {
        "title": "Senior Engineer",
        "summary": "Summary",
        "skills": {"Core": "Java, Spring Boot, Kafka, Redis, Docker, AWS, GCP, Azure, Linux, Terraform, Ansible, RabbitMQ, PostgreSQL, MySQL, MongoDB, Cassandra, Elasticsearch, Kubernetes, Helm, Prometheus, Grafana, Jenkins, GitLab CI, CircleCI, ArgoCD, Nginx, HAProxy, OpenAPI, REST, gRPC"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume with Java services")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, template_name, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {
            "template_used": "professional_compact",
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [
                {"claim": "Java", "coverage_status": "supported", "retained_primary_supporting_evidence_count": 1},
                {"claim": "Spring Boot", "coverage_status": "supported", "retained_primary_supporting_evidence_count": 1},
            ],
            "unsupported_visible_claims_final": [],
            "weak_visible_claims_final": [],
        }

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )

    tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")
    report_paths = list(tmp_path.glob("*_REPORT.json"))
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    assert report_data["validator_warnings_rendered_resume"]
    assert report_data["status"] == "approved_with_warnings"


def test_run_tailoring_scopes_banned_phrase_warning_to_tailored_json_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = _FakeConnection()
    job = _make_job()
    report = _approved_report()
    report["validator"]["warnings"] = ["Banned words: adept at"]
    report["tailored_json"] = {
        "title": "Staff Software Engineer - AI II",
        "summary": "Summary text",
        "skills": {"Core": "Java, AWS, Kafka"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, template_name, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {
            "template_used": "professional_compact",
            "allowed_physical_pages": 2,
            "measured_pages_final": 2,
            "claim_coverage": [
                {"claim": "Java"},
                {"claim": "AWS"},
            ],
        }

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")
    assert result["approved"] == 1

    report_paths = list(tmp_path.glob("*_REPORT.json"))
    assert len(report_paths) == 1
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    assert report_data["validator_warnings_tailored_json"] == ["Banned words: adept at"]
    assert report_data["validator_warnings_rendered_resume"] == []
    assert report_data["status"] == "approved_with_warnings"


def test_run_tailoring_falls_back_to_text_pdf_when_structured_render_fails(monkeypatch, tmp_path: Path) -> None:
    conn = _FakeConnection()
    job = _make_job()
    fallback_called = {"value": False}

    report = _approved_report()
    report["tailored_json"] = {
        "title": "Staff Software Engineer - AI II",
        "summary": "Summary",
        "skills": {"Languages": "Python"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(tailor, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("structured boom")),
    )

    def _fake_convert_to_pdf(text_path: Path, output_path: Path | None = None, **_kwargs) -> Path:
        fallback_called["value"] = True
        out = output_path or Path(text_path).with_suffix(".pdf")
        out = Path(out)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out

    monkeypatch.setattr("applypilot.scoring.pdf.convert_to_pdf", _fake_convert_to_pdf)

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")

    assert result["approved"] == 1
    assert fallback_called["value"] is True
    assert any("tailored_resume_path" in query for query, _ in conn.calls)
    report_paths = list(tmp_path.glob("*_REPORT.json"))
    assert len(report_paths) == 1
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    assert report_data["pdf_render_planning"]["render_path"] == "text_fallback"


def test_run_tailoring_invalid_configured_template_falls_back_to_default(
    monkeypatch,
    tmp_path: Path,
    caplog,
) -> None:
    conn = _FakeConnection()
    job = _make_job()
    captured_template = {"value": None}

    report = _approved_report()
    report["tailored_json"] = {
        "title": "Staff Software Engineer - AI II",
        "summary": "Summary",
        "skills": {"Languages": "Python"},
        "experience": [{"header": "Engineer", "subtitle": "Example | 2020-2024", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": "BS",
    }

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(
        tailor,
        "load_profile",
        lambda: {
            "personal": {"full_name": "Alex Example"},
            "tailoring_config": {"pdf_template": "missing-template"},
        },
    )
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", report))

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, html_only
        captured_template["value"] = template_name
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out, {"template_used": template_name}

    monkeypatch.setattr(
        "applypilot.scoring.pdf.render_model_to_pdf_with_planning",
        _fake_render_model_to_pdf_with_planning,
    )
    monkeypatch.setattr(
        "applypilot.scoring.pdf.convert_to_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fallback text renderer should not run")),
    )

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")

    assert result["approved"] == 1
    assert captured_template["value"] == "professional_compact"
    assert "Falling back to 'professional_compact'" in caplog.text


def test_tailor_resume_includes_tailored_json_on_success(monkeypatch) -> None:
    class _FakeClient:
        def chat(self, _messages, max_output_tokens: int = 16000):  # noqa: ARG002
            return (
                "{"
                '"title":"Senior Software Engineer",'
                '"summary":"Built production backend services.",'
                '"skills":{"Languages":"Python, Java"},'
                '"experience":[{"header":"Engineer","subtitle":"Acme | 2020-2024","bullets":["Built APIs"]}],'
                '"projects":[],'
                '"education":"State University | BS Computer Science"'
                "}"
            )

    monkeypatch.setattr(tailor, "get_client", lambda: _FakeClient())

    profile = {"personal": {}}
    job = {
        "title": "Senior Software Engineer",
        "site": "Example",
        "location": "Remote",
        "full_description": "Build APIs",
    }
    base_resume = "Base resume text"

    _, report = tailor.tailor_resume(
        base_resume,
        job,
        profile,
        max_retries=0,
        validation_mode="lenient",
    )

    assert report["status"] == "approved"
    assert isinstance(report.get("tailored_json"), dict)


def test_tailor_resume_applies_banned_phrase_cleanup_once(monkeypatch) -> None:
    class _FakeClient:
        def chat(self, _messages, max_output_tokens: int = 16000):  # noqa: ARG002
            return (
                "{"
                '"title":"Senior Software Engineer",'
                '"summary":"Senior backend engineer with extensive experience and demonstrated ability to lead delivery.",'
                '"skills":{"Languages":"Python, Java"},'
                '"experience":[{"header":"Engineer","subtitle":"Acme | 2020-2024","bullets":["Built APIs"]}],'
                '"projects":[],'
                '"education":"State University | BS Computer Science"'
                "}"
            )

    validate_calls = {"count": 0}

    def _fake_validate_json_fields(data, _profile, mode="normal"):  # noqa: ARG001
        validate_calls["count"] += 1
        summary = str(data.get("summary", "")).lower()
        warnings = []
        if "extensive experience" in summary:
            warnings.append("Banned words: extensive experience")
        if "demonstrated ability to" in summary:
            warnings.append("Banned words: demonstrated ability")
        return {"passed": True, "errors": [], "warnings": warnings}

    monkeypatch.setattr(tailor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(tailor, "validate_json_fields", _fake_validate_json_fields)
    monkeypatch.setattr(
        tailor,
        "judge_tailored_resume",
        lambda *_args, **_kwargs: {"passed": True, "verdict": "PASS", "issues": "none"},
    )

    profile = {"personal": {}}
    job = {
        "title": "Senior Software Engineer",
        "site": "Example",
        "location": "Remote",
        "full_description": "Build APIs",
    }

    _, report = tailor.tailor_resume(
        "Base resume text",
        job,
        profile,
        max_retries=0,
        validation_mode="normal",
    )

    assert report["status"] == "approved"
    assert report["banned_phrase_cleanup_applied"] is True
    assert report["banned_phrase_replacements"]
    assert report["validation_resolution_source"] == "deterministic_cleanup"
    assert isinstance(report["validation_attempts"], list)
    assert report["validation_attempts"][0]["banned_phrase_cleanup_attempted"] is True
    assert report["validation_attempts"][0]["banned_phrase_cleanup_applied"] is True
    assert report["validation_attempts"][0]["validator_warnings_before_cleanup"]
    assert report["validation_attempts"][0]["validator_warnings_after_cleanup"] == []
    assert validate_calls["count"] == 2
    cleaned_summary = str(report["tailored_json"]["summary"]).lower()
    assert "extensive experience" not in cleaned_summary
    assert "demonstrated ability to" not in cleaned_summary


def test_tailor_resume_skips_cleanup_when_no_banned_phrase_warning(monkeypatch) -> None:
    class _FakeClient:
        def chat(self, _messages, max_output_tokens: int = 16000):  # noqa: ARG002
            return (
                "{"
                '"title":"Senior Software Engineer",'
                '"summary":"Senior backend engineer designing reliable APIs.",'
                '"skills":{"Languages":"Python, Java"},'
                '"experience":[{"header":"Engineer","subtitle":"Acme | 2020-2024","bullets":["Built APIs"]}],'
                '"projects":[],'
                '"education":"State University | BS Computer Science"'
                "}"
            )

    validate_calls = {"count": 0}

    def _fake_validate_json_fields(_data, _profile, mode="normal"):  # noqa: ARG001
        validate_calls["count"] += 1
        return {"passed": True, "errors": [], "warnings": []}

    monkeypatch.setattr(tailor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(tailor, "validate_json_fields", _fake_validate_json_fields)
    monkeypatch.setattr(
        tailor,
        "judge_tailored_resume",
        lambda *_args, **_kwargs: {"passed": True, "verdict": "PASS", "issues": "none"},
    )

    _, report = tailor.tailor_resume(
        "Base resume text",
        {"title": "Senior Software Engineer", "site": "Example", "location": "Remote", "full_description": "Build APIs"},
        {"personal": {}},
        max_retries=0,
        validation_mode="normal",
    )

    assert report["status"] == "approved"
    assert report["banned_phrase_cleanup_applied"] is False
    assert report["banned_phrase_replacements"] == []
    assert report["validation_resolution_source"] == "initial_pass"
    assert report["validator_warnings_before_cleanup"] == []
    assert report["validator_warnings_after_cleanup"] is None
    assert report["validation_attempts"][0]["banned_phrase_cleanup_attempted"] is False
    assert report["validation_attempts"][0]["validator_warnings_after_cleanup"] is None
    assert validate_calls["count"] == 1
    assert report["tailored_json"]["title"] == "Senior Software Engineer"


def test_tailor_resume_later_generation_attempt_telemetry(monkeypatch) -> None:
    class _FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, _messages, max_output_tokens: int = 16000):  # noqa: ARG002
            self.calls += 1
            if self.calls == 1:
                return (
                    "{"
                    '"title":"Senior Software Engineer",'
                    '"summary":"Senior backend engineer adept at delivery.",'
                    '"skills":{"Languages":"Python, Java"},'
                    '"experience":[{"header":"Engineer","subtitle":"Acme | 2020-2024","bullets":["Built APIs"]}],'
                    '"projects":[],'
                    '"education":"State University | BS Computer Science"'
                    "}"
                )
            return (
                "{"
                '"title":"Senior Software Engineer",'
                '"summary":"Senior backend engineer delivering reliable APIs.",'
                '"skills":{"Languages":"Python, Java"},'
                '"experience":[{"header":"Engineer","subtitle":"Acme | 2020-2024","bullets":["Built APIs"]}],'
                '"projects":[],'
                '"education":"State University | BS Computer Science"'
                "}"
            )

    validate_calls = {"count": 0}

    def _fake_validate_json_fields(data, _profile, mode="normal"):  # noqa: ARG001
        validate_calls["count"] += 1
        summary = str(data.get("summary", "")).lower()
        if validate_calls["count"] <= 2:
            warnings = ["Banned words: adept at"] if "adept at" in summary else ["Banned words: adept at"]
            return {"passed": False, "errors": ["Banned words: adept at"], "warnings": warnings}
        return {"passed": True, "errors": [], "warnings": []}

    monkeypatch.setattr(tailor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(tailor, "validate_json_fields", _fake_validate_json_fields)
    monkeypatch.setattr(
        tailor,
        "judge_tailored_resume",
        lambda *_args, **_kwargs: {"passed": True, "verdict": "PASS", "issues": "none"},
    )

    _, report = tailor.tailor_resume(
        "Base resume text",
        {"title": "Senior Software Engineer", "site": "Example", "location": "Remote", "full_description": "Build APIs"},
        {"personal": {}},
        max_retries=1,
        validation_mode="normal",
    )

    assert report["status"] == "approved"
    assert report["validation_resolution_source"] == "later_generation_attempt"
    assert report["attempts"] == 2
    assert report["banned_phrase_cleanup_applied"] is False
    assert report["banned_phrase_replacements"] == []
    assert report["validator_warnings_before_cleanup"] == []
    assert len(report["validation_attempts"]) == 2
    assert "Banned words: adept at" in report["validation_attempts"][0]["validator_warnings_before_cleanup"]
    assert report["validation_attempts"][1]["validator_warnings_before_cleanup"] == []


def test_tailor_resume_cleanup_attempted_but_not_applied(monkeypatch) -> None:
    class _FakeClient:
        def chat(self, _messages, max_output_tokens: int = 16000):  # noqa: ARG002
            return (
                "{"
                '"title":"Senior Software Engineer",'
                '"summary":"Senior backend engineer delivering reliable APIs.",'
                '"skills":{"Languages":"Python, Java"},'
                '"experience":[{"header":"Engineer","subtitle":"Acme | 2020-2024","bullets":["Built APIs"]}],'
                '"projects":[],'
                '"education":"State University | BS Computer Science"'
                "}"
            )

    def _fake_validate_json_fields(_data, _profile, mode="normal"):  # noqa: ARG001
        return {"passed": True, "errors": [], "warnings": ["Banned words: adept at"]}

    monkeypatch.setattr(tailor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(tailor, "validate_json_fields", _fake_validate_json_fields)
    monkeypatch.setattr(
        tailor,
        "judge_tailored_resume",
        lambda *_args, **_kwargs: {"passed": True, "verdict": "PASS", "issues": "none"},
    )

    _, report = tailor.tailor_resume(
        "Base resume text",
        {"title": "Senior Software Engineer", "site": "Example", "location": "Remote", "full_description": "Build APIs"},
        {"personal": {}},
        max_retries=0,
        validation_mode="normal",
    )

    assert report["status"] == "approved"
    assert report["validation_attempts"][0]["banned_phrase_cleanup_attempted"] is True
    assert report["validation_attempts"][0]["banned_phrase_cleanup_applied"] is False
    assert report["banned_phrase_cleanup_applied"] is False
    assert report["banned_phrase_replacements"] == []


def test_tailor_resume_includes_content_preparation_context(monkeypatch) -> None:
    class _FakeClient:
        def chat(self, _messages, max_output_tokens: int = 16000):  # noqa: ARG002
            return (
                "{"
                '"title":"Senior Software Engineer",'
                '"summary":"Built production backend services.",'
                '"skills":{"Languages":"Python, Java"},'
                '"experience":[{"header":"Engineer","subtitle":"Acme | 2020-2024","bullets":["Built APIs"]}],'
                '"projects":[],'
                '"education":"State University | BS Computer Science"'
                "}"
            )

    monkeypatch.setattr(tailor, "get_client", lambda: _FakeClient())

    profile = {"personal": {}}
    job = {
        "title": "Senior Software Engineer",
        "site": "Example",
        "location": "Remote",
        "full_description": "Build APIs",
    }
    context = {
        "pdf_template": "professional_compact",
        "pdf_template_input_preferences": {"prefers_compact_summary": True},
    }

    _, report = tailor.tailor_resume(
        "Base resume text",
        job,
        profile,
        max_retries=0,
        validation_mode="lenient",
        content_preparation_context=context,
    )

    assert report["content_preparation_context"] == context


def test_build_tailor_prompt_includes_informational_template_context() -> None:
    prompt = tailor._build_tailor_prompt(
        profile={"personal": {}},
        content_preparation_context={
            "pdf_template": "professional_compact",
            "pdf_template_input_preferences": {"prefers_compact_summary": True},
        },
    )

    assert "## TEMPLATE INPUT PREFERENCES (INFORMATIONAL)" in prompt
    assert '"pdf_template": "professional_compact"' in prompt
    assert '"prefers_compact_summary": true' in prompt
    assert "It does NOT change the required output schema." in prompt
    assert "## COMPACT SUMMARY (OPTIONAL WHEN USEFUL)" in prompt
    assert '"compact_summary": "Optional concise sentence for compact layouts."' in prompt
    assert '"start_date": "2025-08"' in prompt
    assert '"end_date": null' in prompt
    assert '"is_contract": false' in prompt


def test_build_tailor_prompt_omits_compact_summary_guidance_when_not_requested() -> None:
    prompt = tailor._build_tailor_prompt(
        profile={"personal": {}},
        content_preparation_context={
            "pdf_template": "classic",
            "pdf_template_input_preferences": {},
        },
    )

    assert "## COMPACT SUMMARY (OPTIONAL WHEN USEFUL)" not in prompt
    assert '"compact_summary": "Optional concise sentence for compact layouts."' not in prompt


def test_tailor_resume_applies_profile_contract_authority_to_experience() -> None:
    class _FakeClient:
        def chat(self, _messages, max_output_tokens: int = 16000):  # noqa: ARG002
            return (
                "{"
                '"title":"Senior Software Engineer",'
                '"summary":"Built production backend services.",'
                '"skills":{"Languages":"Python, Java"},'
                '"experience":[{"company":"Charles Schwab","role":"Software Engineer","is_contract":false,'
                '"start_date":"2025-08","end_date":"2026-03","bullets":["Built APIs"]}],'
                '"projects":[],'
                '"education":"State University | BS Computer Science"'
                "}"
            )

    original_get_client = tailor.get_client
    try:
        tailor.get_client = lambda: _FakeClient()
        profile = {
            "personal": {"full_name": "Alex Example"},
            "work": [
                {
                    "company": "Charles Schwab",
                    "position": "Software Engineer",
                    "is_contract": True,
                    "start_date": "2025-08",
                    "end_date": "2026-03",
                }
            ],
            "education": [{"institution": "State University"}],
        }
        job = {
            "title": "Senior Software Engineer",
            "site": "Example",
            "location": "Remote",
            "full_description": "Build APIs",
        }

        _, report = tailor.tailor_resume(
            "Base resume text",
            job,
            profile,
            max_retries=0,
            validation_mode="lenient",
        )
    finally:
        tailor.get_client = original_get_client

    assert report["status"] == "approved"
    assert report["tailored_json"]["experience"][0]["is_contract"] is True
    assert report["profile_work_authority_overrides"] == ["Charles Schwab: is_contract=true"]


def test_build_tailor_prompt_centralizes_global_voice_and_evidence_standard() -> None:
    prompt = tailor._build_tailor_prompt(
        profile={"personal": {}},
        content_preparation_context={
            "pdf_template": "professional_compact",
            "pdf_template_input_preferences": {},
        },
    )

    assert "## OUTPUT VOICE AND EVIDENCE STANDARD" in prompt
    assert "Validator banned/generic phrase list:" in prompt
    assert "robust" in prompt
    assert "proven track record" in prompt
    assert "extensive experience" in prompt
    assert "rewrite the sentence using more concrete evidence before returning JSON" in prompt
    assert "## SUMMARY" in prompt
    assert "Use the global voice and evidence standard." in prompt
    assert "## FINAL QUALITY CHECK BEFORE OUTPUT" in prompt
    assert "Did I apply the global voice and evidence standard?" in prompt
    assert "Education is injected from trusted profile data" in prompt
    assert 'The "education" field in output is legacy/compatibility only' in prompt


def test_build_tailor_prompt_strengthens_skills_selection_guidance() -> None:
    prompt = tailor._build_tailor_prompt(
        profile={"personal": {}},
        content_preparation_context={
            "pdf_template": "professional_compact",
            "pdf_template_input_preferences": {},
        },
    )

    assert "The skills section is not a complete inventory of source-resume skills." in prompt
    assert "Include only skills that appear in the job description" in prompt
    assert "Strongly prefer 12-20 total skill items across all categories." in prompt
    assert "Absolute maximum: 24 skill items unless the job description explicitly requires a broad stack." in prompt
    assert "Use only categories that help this job." in prompt
    assert "Omit empty or weak categories." in prompt
    assert '"Backend / Platform": "..."' in prompt
    assert '"Cloud / Infrastructure": "..."' in prompt
    assert '"Data / Messaging": "..."' in prompt
    assert '"Testing / Delivery": "..."' in prompt


def test_run_tailoring_report_includes_pdf_template_preferences(monkeypatch, tmp_path: Path) -> None:
    conn = _FakeConnection()
    job = _make_job()

    monkeypatch.setattr(tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(
        tailor,
        "load_profile",
        lambda: {
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
        },
    )
    monkeypatch.setattr(tailor, "load_resume_text", lambda: "base resume")
    monkeypatch.setattr(tailor, "get_connection", lambda: conn)
    monkeypatch.setattr(tailor, "get_jobs_by_stage", lambda **_: [job])
    monkeypatch.setattr(tailor, "tailor_resume", lambda *args, **kwargs: ("tailored resume", _approved_report()))

    def _fake_convert_to_pdf(text_path: Path, output_path: Path | None = None, **_kwargs) -> Path:
        out = output_path or Path(text_path).with_suffix(".pdf")
        out = Path(out)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return out

    monkeypatch.setattr("applypilot.scoring.pdf.convert_to_pdf", _fake_convert_to_pdf)

    result = tailor.run_tailoring(min_score=7, limit=1, validation_mode="normal")

    assert result["approved"] == 1
    report_paths = list(tmp_path.glob("*_REPORT.json"))
    assert len(report_paths) == 1
    report_data = json.loads(report_paths[0].read_text(encoding="utf-8"))
    assert report_data["pdf_template"] == "professional_compact"
    assert isinstance(report_data["pdf_template_input_preferences"], dict)
    assert report_data["content_preparation_context"]["pdf_template"] == "professional_compact"
    assert isinstance(report_data["content_preparation_context"]["pdf_template_input_preferences"], dict)
    assert report_data["profile_education_rendered"] == (
        "Metropolitan State College of Denver | Computer Science coursework | 1994 - 1996"
    )
