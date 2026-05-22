from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "render_template_comparison.py"
    spec = importlib.util.spec_from_file_location("render_template_comparison_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_comparison_renders_each_template_without_llm(monkeypatch, tmp_path: Path) -> None:
    module = _load_script_module()

    report_path = tmp_path / "sample_REPORT.json"
    report_payload = {
        "title": "Senior Engineer",
        "site": "Example",
        "full_description": "Build resilient backend systems and deployment automation.",
        "skills_selection": {"before_count": 3, "after_count": 2},
        "tailored_json": {
            "title": "Senior Engineer",
            "summary": "Summary text",
            "skills": {"Core": "Java, AWS"},
            "experience": [
                {
                    "header": "Backend Engineer",
                    "subtitle": "Example Corp | 2020-2024",
                    "bullets": ["Built backend systems."],
                }
            ],
            "projects": [],
            "education": "BS Computer Science",
        },
    }
    report_path.write_text(json.dumps(report_payload), encoding="utf-8")
    report_before = report_path.read_text(encoding="utf-8")

    monkeypatch.setattr(module, "load_profile", lambda: {"personal": {"full_name": "Alex Example"}})

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        planning = {
            "measured_pages_final": 2,
            "allowed_physical_pages": 3,
            "summary_mode_final": "compact",
            "skills_mode_final": "selected",
            "projects_mode_final": "compact",
            "experience_mode_final": "detailed",
            "earlier_experience_mode_final": "compact",
            "education_mode_final": "full",
            "certifications_mode_final": "selected",
            "detailed_roles": ["Example Corp"],
            "earlier_selected_roles": ["Older Corp"],
            "rendered_visible_skill_names": ["Java", "AWS"],
            "unsupported_visible_claims_final": [],
            "weak_visible_claims_final": [],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
            "job_themes": [{"id": "theme_1", "label": "backend systems"}],
            "strong_unused_evidence": [{"id": "e1"}],
            "evidence_available_but_not_rendered": [{"id": "e2"}, {"id": "e3"}],
            "evidence_preservation_attempts": [{"kept": True}],
            "evidence_aware_skill_adjustments": [{"action": "kept"}],
            "unsupported_skill_removals": [],
            "compound_skill_repairs": [{"from": "AWS (EC2, S3)", "to": "AWS EC2"}],
            "grouped_skill_repairs": [{"rewritten_skill": "AWS (EC2, Lambda)"}],
            "planning_operations": [{"step": "compact"}],
            "template_used": template_name,
        }
        if template_name == "editorial_timeline":
            planning["rendered_visible_skill_names"] = ["Java", "AWS", "Route53"]
        return out, planning

    monkeypatch.setattr(module, "render_model_to_pdf_with_planning", _fake_render_model_to_pdf_with_planning)

    out_dir = tmp_path / "comparison"
    comparison = module.run_comparison(
        report_path=report_path,
        job_path=None,
        out_dir=out_dir,
        templates=["professional_compact", "editorial_timeline"],
    )

    assert (out_dir / "professional_compact.pdf").exists()
    assert (out_dir / "editorial_timeline.pdf").exists()
    assert (out_dir / "professional_compact_PLANNING.json").exists()
    assert (out_dir / "editorial_timeline_PLANNING.json").exists()
    assert (out_dir / "comparison.json").exists()

    templates = comparison["templates"]
    assert [item["template"] for item in templates] == ["professional_compact", "editorial_timeline"]
    assert templates[0]["visible_skill_claims"] == ["Java", "AWS"]
    assert templates[0]["allowed_physical_pages"] == 3
    assert templates[0]["render_modes_final"]["skills_mode"] == "selected"
    assert templates[0]["detailed_roles"] == ["Example Corp"]
    assert templates[0]["earlier_selected_roles"] == ["Older Corp"]
    assert templates[0]["unsupported_visible_claims_final"] == []
    assert templates[0]["weak_visible_claims_final"] == []
    assert templates[0]["strong_unused_evidence_count"] == 1
    assert templates[0]["evidence_available_but_not_rendered_count"] == 2
    assert templates[0]["evidence_preservation_attempt_count"] == 1
    assert templates[0]["evidence_aware_skill_adjustment_count"] == 1
    assert templates[0]["unsupported_skill_removal_count"] == 0
    assert templates[0]["compound_grouped_skill_repair_count"] == 2
    assert templates[0]["planning_operation_count"] == 1
    assert comparison["input_report_unchanged"] is True
    assert comparison["template_differences"][0]["template"] == "editorial_timeline"
    assert comparison["template_differences"][0]["added_vs_baseline"] == ["Route53"]
    assert report_path.read_text(encoding="utf-8") == report_before


def test_run_comparison_with_complex_fixture_emits_expected_comparison_fields(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    fixtures = Path(__file__).resolve().parent / "fixtures"
    report_path = fixtures / "template_comparison_backend_complex_REPORT.json"
    job_path = fixtures / "template_comparison_backend_complex_JOB.txt"
    report_before = report_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        module,
        "load_profile",
        lambda: {
            "personal": {
                "full_name": "Alex Example",
                "email": "alex@example.com",
                "phone": "555-0100",
                "github_url": "https://github.com/alex",
                "linkedin_url": "https://linkedin.com/in/alex",
            }
        },
    )

    def _fake_render_model_to_pdf_with_planning(
        model,
        output_path: Path,
        template_name: str = "professional_compact",
        html_only: bool = False,
        **_kwargs,
    ) -> tuple[Path, dict]:
        del model, html_only
        out = Path(output_path)
        out.write_bytes(b"%PDF-1.4 fake\n")
        planning = {
            "allowed_physical_pages": 3,
            "measured_pages_final": 2,
            "summary_mode_final": "compact",
            "skills_mode_final": "selected",
            "projects_mode_final": "compact",
            "experience_mode_final": "detailed",
            "earlier_experience_mode_final": "grouped",
            "education_mode_final": "compact",
            "certifications_mode_final": "selected",
            "detailed_roles": ["Charles Schwab", "Savvato Software", "Coinme", "SquareTrade"],
            "earlier_selected_roles": ["Charter Communications", "IHS Markit"],
            "rendered_visible_skill_names": ["Java 17-21", "Spring Boot 3.x", "AWS (EC2, Lambda, Route53)"],
            "unsupported_visible_claims": [],
            "weak_visible_claims": [],
            "unsupported_visible_claims_final": [],
            "weak_visible_claims_final": [],
            "job_themes": [{"id": "theme_1", "label": "distributed backend systems"}],
            "strong_unused_evidence": [],
            "evidence_available_but_not_rendered": [{"id": "e1"}],
            "evidence_preservation_attempts": [{"kept": True}],
            "evidence_aware_skill_adjustments": [{"claim": "AWS S3", "action": "removed"}],
            "unsupported_skill_removals": [{"claim": "AWS S3"}],
            "compound_skill_repairs": [{"from": "AWS (EC2, S3, Lambda, Route53)", "to": "AWS (EC2, Lambda, Route53)"}],
            "grouped_skill_repairs": [],
            "planning_operations": [{"step": "skills_mode"}],
            "template_used": template_name,
        }
        return out, planning

    monkeypatch.setattr(module, "render_model_to_pdf_with_planning", _fake_render_model_to_pdf_with_planning)

    comparison = module.run_comparison(
        report_path=report_path,
        job_path=job_path,
        out_dir=tmp_path / "comparison-complex",
        templates=["professional_compact", "editorial_timeline"],
    )

    assert comparison["input_report_unchanged"] is True
    assert comparison["template_differences"] == [
        {
            "baseline_template": "professional_compact",
            "template": "editorial_timeline",
            "removed_from_baseline": [],
            "added_vs_baseline": [],
        }
    ]
    for item in comparison["templates"]:
        assert "allowed_physical_pages" in item
        assert "render_modes_final" in item
        assert "detailed_roles" in item
        assert "earlier_selected_roles" in item
        assert "unsupported_visible_claims_final" in item
        assert "weak_visible_claims_final" in item
        assert "evidence_preservation_attempt_count" in item
        assert "evidence_aware_skill_adjustment_count" in item
        assert "unsupported_skill_removal_count" in item
        assert "compound_grouped_skill_repair_count" in item
        assert "planning_operation_count" in item
    assert report_path.read_text(encoding="utf-8") == report_before
