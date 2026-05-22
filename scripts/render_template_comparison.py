#!/usr/bin/env python3
"""Render one tailored report through multiple PDF templates for side-by-side comparison."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from applypilot.config import load_profile
from applypilot.scoring.pdf import render_model_to_pdf_with_planning
from applypilot.scoring.pdf_render_model import build_render_model_from_tailored_json


DEFAULT_TEMPLATES = ("professional_compact", "editorial_timeline")
DEFAULT_OUT_DIR = Path("/tmp/applypilot-template-comparison")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_job_description(report: dict[str, Any], job_file: Path | None) -> str:
    if job_file is not None:
        return job_file.read_text(encoding="utf-8").strip()

    candidates = [
        report.get("job_description"),
        report.get("full_description"),
    ]
    job = report.get("job")
    if isinstance(job, dict):
        candidates.extend(
            [
                job.get("description"),
                job.get("full_description"),
            ]
        )
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _extract_job_metadata(report: dict[str, Any], job_description: str) -> dict[str, str]:
    job = report.get("job")
    title = str(report.get("title") or "").strip()
    company = str(report.get("site") or "").strip()
    if isinstance(job, dict):
        title = str(job.get("title") or title).strip()
        company = str(job.get("site") or job.get("company") or company).strip()
    return {
        "title": title,
        "company": company,
        "description": job_description,
    }


def _visible_skill_claims_from_planning(planning: dict[str, Any]) -> list[str]:
    rendered = planning.get("rendered_visible_skill_names")
    if isinstance(rendered, list):
        return [str(item).strip() for item in rendered if str(item).strip()]

    coverage = planning.get("claim_coverage")
    if not isinstance(coverage, list):
        return []
    claims: list[str] = []
    seen: set[str] = set()
    for item in coverage:
        if not isinstance(item, dict):
            continue
        if not bool(item.get("is_visible")):
            continue
        claim = str(item.get("claim", "")).strip()
        if not claim:
            continue
        key = claim.casefold()
        if key in seen:
            continue
        seen.add(key)
        claims.append(claim)
    return claims


def _job_theme_labels(planning: dict[str, Any]) -> list[str]:
    raw = planning.get("job_themes")
    if not isinstance(raw, list):
        return []
    labels: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            label = str(item.get("label", "")).strip()
            if label:
                labels.append(label)
        else:
            label = str(item).strip()
            if label:
                labels.append(label)
    return labels


def _summarize_planning(template: str, pdf_path: Path, planning: dict[str, Any]) -> dict[str, Any]:
    unsupported_final = planning.get("unsupported_visible_claims_final")
    weak_final = planning.get("weak_visible_claims_final")
    unsupported = unsupported_final if isinstance(unsupported_final, list) else planning.get("unsupported_visible_claims", [])
    weak = weak_final if isinstance(weak_final, list) else planning.get("weak_visible_claims", [])
    render_modes_final = planning.get("render_modes_final")
    if not isinstance(render_modes_final, dict):
        render_modes_final = {
            "summary_mode": planning.get("summary_mode_final"),
            "skills_mode": planning.get("skills_mode_final"),
            "projects_mode": planning.get("projects_mode_final"),
            "experience_mode": planning.get("experience_mode_final"),
            "earlier_experience_mode": planning.get("earlier_experience_mode_final"),
            "education_mode": planning.get("education_mode_final"),
            "certifications_mode": planning.get("certifications_mode_final"),
        }
    return {
        "template": template,
        "pdf_path": str(pdf_path),
        "measured_pages": planning.get("measured_pages_final"),
        "allowed_physical_pages": planning.get("allowed_physical_pages"),
        "render_modes_final": render_modes_final,
        "detailed_roles": list(planning.get("detailed_roles", []) or []),
        "earlier_selected_roles": list(planning.get("earlier_selected_roles", []) or []),
        "visible_skill_claims": _visible_skill_claims_from_planning(planning),
        "unsupported_visible_claims": list(unsupported) if isinstance(unsupported, list) else [],
        "weak_visible_claims": list(weak) if isinstance(weak, list) else [],
        "unsupported_visible_claims_final": list(unsupported_final) if isinstance(unsupported_final, list) else [],
        "weak_visible_claims_final": list(weak_final) if isinstance(weak_final, list) else [],
        "job_themes": _job_theme_labels(planning),
        "strong_unused_evidence_count": len(planning.get("strong_unused_evidence", []) or []),
        "evidence_available_but_not_rendered_count": len(planning.get("evidence_available_but_not_rendered", []) or []),
        "evidence_preservation_attempt_count": len(planning.get("evidence_preservation_attempts", []) or []),
        "evidence_aware_skill_adjustment_count": len(planning.get("evidence_aware_skill_adjustments", []) or []),
        "unsupported_skill_removal_count": len(planning.get("unsupported_skill_removals", []) or []),
        "compound_grouped_skill_repair_count": len(
            (planning.get("compound_skill_repairs", []) or [])
            + (planning.get("grouped_skill_repairs", []) or [])
        ),
        "planning_operation_count": len(planning.get("planning_operations", []) or []),
    }


def _skill_diff(baseline_claims: list[str], other_claims: list[str]) -> dict[str, list[str]]:
    baseline_map = {claim.casefold(): claim for claim in baseline_claims}
    other_map = {claim.casefold(): claim for claim in other_claims}
    removed = [baseline_map[key] for key in baseline_map.keys() - other_map.keys()]
    added = [other_map[key] for key in other_map.keys() - baseline_map.keys()]
    return {
        "removed_from_baseline": sorted(removed, key=str.casefold),
        "added_vs_baseline": sorted(added, key=str.casefold),
    }


def _print_template_summary(comparison: dict[str, Any]) -> None:
    templates = comparison.get("templates", [])
    if not isinstance(templates, list) or not templates:
        return
    print("\nTemplate comparison summary:")
    baseline = templates[0]
    baseline_name = str(baseline.get("template", "baseline"))
    for item in templates:
        name = str(item.get("template", "unknown"))
        print(
            f"- {name}: pages={item.get('measured_pages')}/{item.get('allowed_physical_pages')} "
            f"visible_skills={len(item.get('visible_skill_claims', []))} "
            f"unsupported_final={len(item.get('unsupported_visible_claims_final', []))} "
            f"weak_final={len(item.get('weak_visible_claims_final', []))} "
            f"ops={item.get('planning_operation_count')} "
            f"preservation={item.get('evidence_preservation_attempt_count')} "
            f"adjustments={item.get('evidence_aware_skill_adjustment_count')} "
            f"removals={item.get('unsupported_skill_removal_count')}"
        )
        if item is not baseline:
            diff = _skill_diff(
                list(baseline.get("visible_skill_claims", []) or []),
                list(item.get("visible_skill_claims", []) or []),
            )
            if diff["removed_from_baseline"] or diff["added_vs_baseline"]:
                print(
                    f"  compared to {baseline_name}: "
                    f"-{diff['removed_from_baseline']} +{diff['added_vs_baseline']}"
                )


def run_comparison(
    *,
    report_path: Path,
    job_path: Path | None,
    out_dir: Path,
    templates: list[str],
) -> dict[str, Any]:
    report = _load_json(report_path)
    original_report_snapshot = json.dumps(report, sort_keys=True)
    tailored_json = report.get("tailored_json")
    if not isinstance(tailored_json, dict):
        raise ValueError(f"Report does not contain object field 'tailored_json': {report_path}")

    profile = load_profile()
    job_description = _extract_job_description(report, job_path)
    job = _extract_job_metadata(report, job_description)

    base_model = build_render_model_from_tailored_json(tailored_json, profile, job=job)
    skills_selection = report.get("skills_selection")
    if not isinstance(skills_selection, dict):
        skills_selection = None

    out_dir.mkdir(parents=True, exist_ok=True)
    template_results: list[dict[str, Any]] = []
    planning_paths: list[Path] = []
    pdf_paths: list[Path] = []

    for template in templates:
        safe_name = template.replace("/", "_")
        pdf_path = out_dir / f"{safe_name}.pdf"
        model = copy.deepcopy(base_model)
        rendered_path, planning = render_model_to_pdf_with_planning(
            model=model,
            output_path=pdf_path,
            template_name=template,
            html_only=False,
            job_description=job_description,
            skills_selection=skills_selection,
        )
        planning_path = out_dir / f"{safe_name}_PLANNING.json"
        planning_path.write_text(json.dumps(planning, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        pdf_paths.append(rendered_path)
        planning_paths.append(planning_path)
        template_results.append(_summarize_planning(template, rendered_path, planning))

    comparison = {
        "report_path": str(report_path),
        "job_path": str(job_path) if job_path is not None else None,
        "templates": template_results,
    }
    if template_results:
        baseline_claims = template_results[0].get("visible_skill_claims", [])
        template_differences: list[dict[str, Any]] = []
        for item in template_results[1:]:
            diff = _skill_diff(
                list(baseline_claims) if isinstance(baseline_claims, list) else [],
                list(item.get("visible_skill_claims", []) or []),
            )
            diff["baseline_template"] = template_results[0].get("template")
            diff["template"] = item.get("template")
            template_differences.append(diff)
        comparison["template_differences"] = template_differences
    comparison["input_report_unchanged"] = (
        original_report_snapshot == json.dumps(_load_json(report_path), sort_keys=True)
    )
    comparison_path = out_dir / "comparison.json"
    comparison_path.write_text(json.dumps(comparison, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"comparison: {comparison_path}")
    for pdf_path in pdf_paths:
        print(f"pdf: {pdf_path}")
    for planning_path in planning_paths:
        print(f"planning: {planning_path}")
    _print_template_summary(comparison)

    return comparison


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path, help="Path to *_REPORT.json containing tailored_json.")
    parser.add_argument(
        "--job",
        dest="job_path",
        type=Path,
        default=None,
        help="Optional path to *_JOB.txt (job description override).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--templates",
        nargs="+",
        default=list(DEFAULT_TEMPLATES),
        help="Template names to render in order.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_comparison(
        report_path=args.report,
        job_path=args.job_path,
        out_dir=args.out_dir,
        templates=[str(item).strip() for item in args.templates if str(item).strip()],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
