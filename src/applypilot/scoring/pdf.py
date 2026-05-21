"""Text-to-PDF conversion for tailored resumes and cover letters.

Parses the structured text resume format, renders via an HTML/CSS template,
and exports to PDF using headless Chromium via Playwright.
"""

import logging
import math
import re
import tempfile
from pathlib import Path
from typing import Any

from applypilot.config import TAILORED_DIR
from applypilot.resume.evidence import (
    build_claim_coverage_for_claims,
    build_evidence_mapping_report,
    claim_distinctive_tokens,
    claim_supports_distinctive_tokens,
    extract_all_skill_claims,
    extract_visible_skill_claims,
)
from applypilot.scoring.evidence_aware_pdf_planner import (
    EvidenceAwarePdfPlanner,
    PdfPlanningContext,
)
from applypilot.scoring.pdf_planning_types import (
    PlanningOperation,
    SkillDisposition,
)
from applypilot.scoring.pdf_render_model import (
    ResumeEntry,
    ResumeRenderModel,
    SkillSection,
)
from applypilot.scoring.render_planning_service import (
    RenderPlanningContext,
    RenderPlanningService,
)
from applypilot.scoring.skill_repair_planner import SkillRepairContext, SkillRepairDependencies, SkillRepairPlanner
from applypilot.scoring.pdf_templates.registry import get_template

log = logging.getLogger(__name__)
DEFAULT_PDF_TEMPLATE = "professional_compact"


# ── Resume Parser ────────────────────────────────────────────────────────


def parse_resume(text: str) -> dict:
    """Parse a structured text resume into sections.

    Expects a format with header lines (name, title, location, contact)
    followed by ALL-CAPS section headers (SUMMARY, TECHNICAL SKILLS, etc.).

    Args:
        text: Full resume text.

    Returns:
        {"name": str, "title": str, "location": str, "contact": str, "sections": dict}
    """
    lines = [line.rstrip() for line in text.strip().split("\n")]

    # Header: first few lines before SUMMARY
    header_lines: list[str] = []
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip().upper() == "SUMMARY":
            body_start = i
            break
        if line.strip():
            header_lines.append(line.strip())

    name = header_lines[0] if len(header_lines) > 0 else ""
    title = header_lines[1] if len(header_lines) > 1 else ""
    # The header may have 3 or 4 lines depending on whether location is included
    location = ""
    contact = ""
    if len(header_lines) > 3:
        location = header_lines[2]
        contact = header_lines[3]
    elif len(header_lines) > 2:
        # Could be location or contact -- check for email/phone indicators
        if "@" in header_lines[2] or "|" in header_lines[2]:
            contact = header_lines[2]
        else:
            location = header_lines[2]

    # Split body into sections by ALL-CAPS headers
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for line in lines[body_start:]:
        stripped = line.strip()
        # Detect section headers (all caps, no leading dash/bullet, longer than 3 chars)
        if (
            stripped
            and stripped == stripped.upper()
            and not stripped.startswith("-")
            and len(stripped) > 3
            and not stripped.startswith("\u2022")
        ):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = stripped
            current_lines = []
        else:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    return {
        "name": name,
        "title": title,
        "location": location,
        "contact": contact,
        "sections": sections,
    }


def parse_skills(text: str) -> list[tuple[str, str]]:
    """Parse skills section into (category, value) pairs.

    Args:
        text: The TECHNICAL SKILLS section text.

    Returns:
        List of (category_name, skills_string) tuples.
    """
    skills: list[tuple[str, str]] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if ":" in line:
            cat, val = line.split(":", 1)
            skills.append((cat.strip(), val.strip()))
    return skills


def parse_entries(text: str) -> list[dict]:
    """Parse experience/project entries from section text.

    Args:
        text: The EXPERIENCE or PROJECTS section text.

    Returns:
        List of {"title": str, "subtitle": str, "bullets": list[str]} dicts.
    """
    entries: list[dict] = []
    lines = text.strip().split("\n")
    current: dict | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") or stripped.startswith("\u2022 "):
            if current:
                current["bullets"].append(stripped[2:].strip())
        elif current is None or (
            not stripped.startswith("-") and not stripped.startswith("\u2022") and len(current.get("bullets", [])) > 0
        ):
            # New entry
            if current:
                entries.append(current)
            current = {"title": stripped, "subtitle": "", "bullets": []}
        elif current and not current["subtitle"]:
            current["subtitle"] = stripped
        else:
            if current:
                current["bullets"].append(stripped)

    if current:
        entries.append(current)

    return entries


def build_render_model(parsed: dict) -> ResumeRenderModel:
    """Build a typed render model from parsed resume text output."""

    sections = parsed.get("sections", {})
    model = ResumeRenderModel(
        name=str(parsed.get("name", "")),
        title=str(parsed.get("title", "")),
        location=str(parsed.get("location", "")),
        contact=str(parsed.get("contact", "")),
    )

    summary_text = str(sections.get("SUMMARY", "")).strip()
    if summary_text:
        model.summary = summary_text

    skills_text = sections.get("TECHNICAL SKILLS", "")
    if isinstance(skills_text, str) and skills_text.strip():
        model.skills = [SkillSection(category=cat, value=val) for cat, val in parse_skills(skills_text)]

    exp_text = sections.get("EXPERIENCE", "")
    if isinstance(exp_text, str) and exp_text.strip():
        model.experience = [
            ResumeEntry(
                title=str(entry.get("title", "")),
                subtitle=str(entry.get("subtitle", "")),
                bullets=list(entry.get("bullets", [])),
            )
            for entry in parse_entries(exp_text)
        ]

    projects_text = sections.get("PROJECTS", "")
    if isinstance(projects_text, str) and projects_text.strip():
        model.projects = [
            ResumeEntry(
                title=str(entry.get("title", "")),
                subtitle=str(entry.get("subtitle", "")),
                bullets=list(entry.get("bullets", [])),
            )
            for entry in parse_entries(projects_text)
        ]

    education_text = str(sections.get("EDUCATION", "")).strip()
    if education_text:
        model.education = education_text

    certifications_text = str(sections.get("CERTIFICATIONS", "") or sections.get("CERTIFICATES", "")).strip()
    if certifications_text:
        model.certifications = certifications_text

    return model


def build_html_for_resume(model: ResumeRenderModel, template_name: str = DEFAULT_PDF_TEMPLATE) -> str:
    """Run template preparation + HTML generation for a render model.

    `prepare()` may return a template-specific prepared view type; `build_html()`
    consumes that prepared value. Templates may also provide
    `prepare_with_measurement(model, measure_html_page_count)`.
    """

    html, _prepared = _build_html_and_prepared_for_resume(model, template_name=template_name)
    return html


def _build_html_and_prepared_for_resume(
    model: ResumeRenderModel,
    template_name: str = DEFAULT_PDF_TEMPLATE,
) -> tuple[str, Any]:
    template = get_template(template_name)
    prepare_with_measurement = getattr(template, "prepare_with_measurement", None)
    if callable(prepare_with_measurement):
        prepared = prepare_with_measurement(model, measure_html_page_count)
    else:
        prepare = getattr(template, "prepare", None)
        if not callable(prepare):
            raise ValueError(
                f"Template '{template_name}' must define prepare(model) or "
                "prepare_with_measurement(model, measure_html_page_count)."
            )
        prepared = prepare(model)
    return template.build_html(prepared), prepared


def _extract_company_label(entry: ResumeEntry) -> str:
    subtitle = str(entry.subtitle).strip()
    if subtitle:
        first = subtitle.split("|", 1)[0].strip()
        if first:
            return first
    return str(entry.title).strip()


def extract_render_planning_report(
    model: ResumeRenderModel,
    prepared: Any,
    template_name: str,
) -> dict[str, Any]:
    """Extract template planning telemetry for report artifacts."""

    report: dict[str, Any] = {
        "template_used": template_name,
    }
    page_target_raw = getattr(prepared, "page_target", None)
    try:
        page_target = float(page_target_raw) if page_target_raw is not None else None
    except (TypeError, ValueError):
        page_target = None
    if page_target is not None and page_target > 0:
        report["page_target_config"] = page_target
        report["allowed_physical_pages"] = max(1, int(math.ceil(page_target)))

    allowed_physical_pages = getattr(prepared, "allowed_physical_pages", None)
    if isinstance(allowed_physical_pages, int) and allowed_physical_pages > 0:
        report["allowed_physical_pages"] = allowed_physical_pages

    measured_pages_final = getattr(prepared, "measured_pages_final", None)
    if isinstance(measured_pages_final, int) and measured_pages_final > 0:
        report["measured_pages_final"] = measured_pages_final

    planning_attempts = getattr(prepared, "planning_attempts", None)
    if isinstance(planning_attempts, list):
        normalized_attempts: list[dict[str, Any]] = []
        for attempt in planning_attempts:
            if isinstance(attempt, dict):
                normalized_attempts.append(dict(attempt))
        report["planning_attempts"] = normalized_attempts

    planning_operations = getattr(prepared, "planning_operations", None)
    if isinstance(planning_operations, list):
        normalized_operations: list[dict[str, Any]] = []
        for operation in planning_operations:
            if isinstance(operation, dict):
                normalized_operations.append(dict(operation))
        report["planning_operations"] = normalized_operations

    render_modes_final = {
        "summary_mode": getattr(prepared, "summary_mode", None),
        "skills_mode": getattr(prepared, "skills_mode", None),
        "projects_mode": getattr(prepared, "projects_mode", None),
        "experience_mode": getattr(prepared, "experience_mode", None),
        "earlier_experience_mode": getattr(prepared, "earlier_experience_mode", None),
        "education_mode": getattr(prepared, "education_mode", None),
        "certifications_mode": getattr(prepared, "certifications_mode", None),
    }
    render_modes_final = {k: v for k, v in render_modes_final.items() if isinstance(v, str) and v}
    if render_modes_final:
        report["render_modes_final"] = render_modes_final

    detailed_bullet_cap_final = getattr(prepared, "detailed_bullet_cap", None)
    if isinstance(detailed_bullet_cap_final, int) and detailed_bullet_cap_final > 0:
        report["detailed_bullet_cap_final"] = detailed_bullet_cap_final

    selected_skills_max_lines_final = getattr(prepared, "selected_skills_max_lines", None)
    if isinstance(selected_skills_max_lines_final, int) and selected_skills_max_lines_final > 0:
        report["selected_skills_max_lines_final"] = selected_skills_max_lines_final

    min_protected_detailed_roles = getattr(prepared, "min_protected_detailed_roles", None)
    if isinstance(min_protected_detailed_roles, int) and min_protected_detailed_roles > 0:
        report["min_protected_detailed_roles"] = min_protected_detailed_roles

    detailed_entries = getattr(prepared, "detailed_experience", model.experience)
    compact_entries = getattr(prepared, "compact_experience", [])
    if isinstance(detailed_entries, list):
        report["detailed_roles"] = [_extract_company_label(entry) for entry in detailed_entries if isinstance(entry, ResumeEntry)]
    if isinstance(compact_entries, list):
        report["earlier_selected_roles"] = [
            _extract_company_label(entry) for entry in compact_entries if isinstance(entry, ResumeEntry)
        ]

    return report


def _normalize_skill_claim_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _split_skill_tokens_preserving_parentheses(text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
            buf.append(ch)
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
            continue
        if ch == "," and depth == 0:
            token = "".join(buf).strip()
            if token:
                parts.append(token)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _clone_model_with_swapped_skills(model: ResumeRenderModel, from_skill: str, to_skill: str) -> ResumeRenderModel | None:
    from_key = _normalize_skill_claim_key(from_skill)
    to_key = _normalize_skill_claim_key(to_skill)
    if not from_key or not to_key or from_key == to_key:
        return None

    sections: list[tuple[str, list[str]]] = []
    from_pos: tuple[int, int] | None = None
    to_pos: tuple[int, int] | None = None

    for sidx, section in enumerate(model.skills):
        tokens = _split_skill_tokens_preserving_parentheses(str(section.value))
        for tidx, token in enumerate(tokens):
            key = _normalize_skill_claim_key(token)
            if from_pos is None and key == from_key:
                from_pos = (sidx, tidx)
            if to_pos is None and key == to_key:
                to_pos = (sidx, tidx)
        sections.append((section.category, tokens))

    if from_pos is None or to_pos is None:
        return None

    (from_sidx, from_tidx), (to_sidx, to_tidx) = from_pos, to_pos
    sections[from_sidx][1][from_tidx], sections[to_sidx][1][to_tidx] = (
        sections[to_sidx][1][to_tidx],
        sections[from_sidx][1][from_tidx],
    )

    cloned = ResumeRenderModel(
        name=model.name,
        title=model.title,
        location=model.location,
        contact=model.contact,
        summary=model.summary,
        skills=[SkillSection(category=cat, value=", ".join(tokens)) for cat, tokens in sections],
        experience=list(model.experience),
        projects=list(model.projects),
        education=model.education,
        certifications=model.certifications,
        render_options=dict(model.render_options),
    )
    return cloned


def _clone_model_without_skill(model: ResumeRenderModel, skill: str) -> ResumeRenderModel | None:
    skill_key = _normalize_skill_claim_key(skill)
    if not skill_key:
        return None

    sections: list[SkillSection] = []
    removed = False
    for section in model.skills:
        tokens = _split_skill_tokens_preserving_parentheses(str(section.value))
        kept_tokens: list[str] = []
        for token in tokens:
            token_key = _normalize_skill_claim_key(token)
            if not removed and token_key == skill_key:
                removed = True
                continue
            kept_tokens.append(token)
        if kept_tokens:
            sections.append(SkillSection(category=section.category, value=", ".join(kept_tokens)))
    if not removed:
        return None

    return ResumeRenderModel(
        name=model.name,
        title=model.title,
        location=model.location,
        contact=model.contact,
        summary=model.summary,
        skills=sections,
        experience=list(model.experience),
        projects=list(model.projects),
        education=model.education,
        certifications=model.certifications,
        render_options=dict(model.render_options),
    )


def _skill_score_map_from_selection(skills_selection: dict[str, Any] | None) -> dict[str, float]:
    mapping: dict[str, float] = {}
    if not isinstance(skills_selection, dict):
        return mapping
    retained = skills_selection.get("retained_skills")
    if not isinstance(retained, list):
        return mapping
    for entry in retained:
        if not isinstance(entry, dict):
            continue
        skill = str(entry.get("skill", "")).strip()
        key = _normalize_skill_claim_key(skill)
        if not key:
            continue
        try:
            score = float(entry.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        mapping[key] = score
    return mapping


def _measured_fit(planning: dict[str, Any]) -> tuple[int | None, bool]:
    measured = planning.get("measured_pages_final")
    allowed = planning.get("allowed_physical_pages")
    measured_pages = measured if isinstance(measured, int) and measured > 0 else None
    allowed_pages = allowed if isinstance(allowed, int) and allowed > 0 else None
    if measured_pages is None or allowed_pages is None:
        return measured_pages, True
    return measured_pages, measured_pages <= allowed_pages


def _build_planning_with_evidence(
    *,
    model: ResumeRenderModel,
    prepared: Any,
    template_name: str,
    job_description: str,
) -> dict[str, Any]:
    planning = extract_render_planning_report(model, prepared, template_name)
    try:
        evidence_report = build_evidence_mapping_report(
            job_description=job_description,
            model=model,
            prepared=prepared,
        )
        planning.update(evidence_report)
    except Exception as exc:  # pragma: no cover - diagnostics should never break rendering
        planning["evidence_mapping_error"] = str(exc)
    return planning


def _parse_source_path(source_path: str) -> tuple[str, int, int | None] | None:
    match = re.match(r"^(experience|projects)\[(\d+)\]\.(compact_summary|bullets\[(\d+)\])$", source_path.strip())
    if not match:
        return None
    section = str(match.group(1))
    entry_idx = int(match.group(2))
    bullet_idx = int(match.group(4)) if match.group(4) is not None else None
    return section, entry_idx, bullet_idx


def _clone_model_with_restored_experience_bullet(
    model: ResumeRenderModel,
    entry_idx: int,
    bullet_idx: int,
    cap: int,
) -> ResumeRenderModel | None:
    if entry_idx < 0 or entry_idx >= len(model.experience):
        return None
    entry = model.experience[entry_idx]
    bullets = list(entry.bullets)
    if bullet_idx < 0 or bullet_idx >= len(bullets):
        return None
    if cap <= 0 or bullet_idx < cap:
        return None
    # Move supporting bullet into retained cap window and push the displaced bullet out.
    supporting = bullets.pop(bullet_idx)
    insert_at = min(max(cap - 1, 0), len(bullets))
    bullets.insert(insert_at, supporting)
    experience = list(model.experience)
    updated_entry = ResumeEntry(
        title=entry.title,
        subtitle=entry.subtitle,
        bullets=bullets,
        compact_summary=entry.compact_summary,
        company=entry.company,
        role=entry.role,
        location=entry.location,
        technologies=list(entry.technologies),
        is_contract=entry.is_contract,
        start_date=entry.start_date,
        end_date=entry.end_date,
        dates=entry.dates,
        metadata=dict(entry.metadata),
    )
    experience[entry_idx] = updated_entry
    return ResumeRenderModel(
        name=model.name,
        title=model.title,
        location=model.location,
        contact=model.contact,
        summary=model.summary,
        skills=list(model.skills),
        experience=experience,
        projects=list(model.projects),
        education=model.education,
        certifications=model.certifications,
        render_options=dict(model.render_options),
    )


def _clone_model_with_compact_summary_from_bullet(
    model: ResumeRenderModel,
    entry_idx: int,
    bullet_idx: int,
) -> ResumeRenderModel | None:
    if entry_idx < 0 or entry_idx >= len(model.experience):
        return None
    entry = model.experience[entry_idx]
    bullets = list(entry.bullets)
    if bullet_idx < 0 or bullet_idx >= len(bullets):
        return None
    summary = bullets[bullet_idx].strip()
    if not summary:
        return None
    experience = list(model.experience)
    updated_entry = ResumeEntry(
        title=entry.title,
        subtitle=entry.subtitle,
        bullets=bullets,
        compact_summary=summary,
        company=entry.company,
        role=entry.role,
        location=entry.location,
        technologies=list(entry.technologies),
        is_contract=entry.is_contract,
        start_date=entry.start_date,
        end_date=entry.end_date,
        dates=entry.dates,
        metadata=dict(entry.metadata),
    )
    experience[entry_idx] = updated_entry
    return ResumeRenderModel(
        name=model.name,
        title=model.title,
        location=model.location,
        contact=model.contact,
        summary=model.summary,
        skills=list(model.skills),
        experience=experience,
        projects=list(model.projects),
        education=model.education,
        certifications=model.certifications,
        render_options=dict(model.render_options),
    )


def _clone_model_with_preserved_project_line(
    model: ResumeRenderModel,
    project_idx: int,
    *,
    source_path: str,
    claim: str,
) -> ResumeRenderModel | None:
    if project_idx < 0 or project_idx >= len(model.projects):
        return None
    project = model.projects[project_idx]
    projects = list(model.projects)
    summary = ""
    compact = project.compact_summary.strip()
    if compact and claim_supports_distinctive_tokens(claim, compact):
        summary = compact
    if not summary:
        parsed = _parse_source_path(source_path)
        bullet_idx = parsed[2] if parsed and parsed[0] == "projects" and parsed[2] is not None else None
        if bullet_idx is not None and 0 <= bullet_idx < len(project.bullets):
            bullet_text = project.bullets[bullet_idx].strip()
            if bullet_text and claim_supports_distinctive_tokens(claim, bullet_text):
                summary = bullet_text
        if not summary:
            for bullet in project.bullets:
                bullet_text = bullet.strip()
                if bullet_text and claim_supports_distinctive_tokens(claim, bullet_text):
                    summary = bullet_text
                    break
    if not summary and compact:
        summary = compact
    if not summary:
        summary = str(project.metadata.get("description", "")).strip() or (project.bullets[0].strip() if project.bullets else "")
    if not summary:
        return None

    updated_project = ResumeEntry(
        title=project.title,
        subtitle=project.subtitle,
        bullets=list(project.bullets),
        compact_summary=summary,
        company=project.company,
        role=project.role,
        location=project.location,
        technologies=list(project.technologies),
        is_contract=project.is_contract,
        start_date=project.start_date,
        end_date=project.end_date,
        dates=project.dates,
        metadata=dict(project.metadata),
    )
    projects[project_idx] = updated_project
    render_options = dict(model.render_options)
    existing = render_options.get("preserve_selected_project_indices")
    indices: list[int] = []
    if isinstance(existing, list):
        for raw in existing:
            try:
                parsed = int(raw)
            except (TypeError, ValueError):
                continue
            if parsed >= 0:
                indices.append(parsed)
    if project_idx not in indices:
        indices.append(project_idx)
    render_options["preserve_selected_project_indices"] = indices[:1]
    return ResumeRenderModel(
        name=model.name,
        title=model.title,
        location=model.location,
        contact=model.contact,
        summary=model.summary,
        skills=list(model.skills),
        experience=list(model.experience),
        projects=projects,
        education=model.education,
        certifications=model.certifications,
        render_options=render_options,
    )


def _apply_evidence_preservation(
    *,
    model: ResumeRenderModel,
    html: str,
    prepared: Any,
    planning: dict[str, Any],
    template_name: str,
    job_description: str,
) -> tuple[ResumeRenderModel, str, Any, dict[str, Any]]:
    """Attempt to preserve hidden primary evidence for weak/unsupported visible claims."""

    def _coverage_rank(status: str) -> int:
        return {
            "unsupported": 0,
            "weak_summary_only": 1,
            "weak": 2,
            "supported": 3,
        }.get(status, -1)

    preservation_attempts: list[dict[str, Any]] = []
    preservation_decisions: list[dict[str, Any]] = []
    current_model = model
    current_html = html
    current_prepared = prepared
    current_planning = planning
    claim_coverage_lookup = {
        _normalize_skill_claim_key(str(item.get("claim", ""))): item
        for item in current_planning.get("claim_coverage", [])
        if isinstance(item, dict)
    }
    target_claims = list(dict.fromkeys([*current_planning.get("unsupported_visible_claims", []), *current_planning.get("weak_visible_claims", [])]))
    preserved_claims: set[str] = set()

    detailed_bullet_cap = getattr(current_prepared, "detailed_bullet_cap", None)
    effective_cap = int(detailed_bullet_cap) if isinstance(detailed_bullet_cap, int) and detailed_bullet_cap > 0 else None
    earlier_mode = str(getattr(current_prepared, "earlier_experience_mode", "compact"))

    for claim in target_claims:
        claim_key = _normalize_skill_claim_key(claim)
        coverage = claim_coverage_lookup.get(claim_key)
        if not isinstance(coverage, dict):
            continue
        source_primary = int(coverage.get("primary_supporting_evidence_count", 0) or 0)
        retained_primary = int(coverage.get("retained_primary_supporting_evidence_count", 0) or 0)
        if source_primary <= retained_primary:
            continue

        candidates = []
        for entry in current_planning.get("evidence_available_but_not_rendered", []):
            if not isinstance(entry, dict):
                continue
            if _normalize_skill_claim_key(str(entry.get("claim", ""))) != claim_key:
                continue
            for item in entry.get("candidate_evidence_items", []):
                if isinstance(item, dict):
                    candidates.append(item)

        decision: dict[str, Any] = {
            "claim": claim,
            "coverage_status": str(coverage.get("coverage_status", "")),
            "candidate_evidence_count": len(candidates),
        }
        if not candidates:
            decision["decision"] = "skipped_no_supported_operation"
            decision["reason"] = "no_supported_preservation_operation_for_candidate_evidence"
            decision["attempted_operations"] = []
            decision["candidate_sources"] = []
            preservation_decisions.append(decision)
            continue
        candidates = sorted(candidates, key=lambda item: float(item.get("evidence_score", 0.0)), reverse=True)

        kept = False
        attempted_ops: list[str] = []
        candidate_sources = [
            {
                "source_type": str(item.get("source_type", "")),
                "source_label": str(item.get("source_label", "")),
                "source_path": str(item.get("source_path", "")),
                "reason_not_rendered": str(item.get("reason_not_rendered", "unknown")),
            }
            for item in candidates
        ]
        for candidate in candidates:
            source_path = str(candidate.get("source_path", ""))
            reason_not_rendered = str(candidate.get("reason_not_rendered", "unknown"))
            evidence_score = float(candidate.get("evidence_score", 0.0) or 0.0)
            parsed = _parse_source_path(source_path)
            operation = "unknown"
            next_model: ResumeRenderModel | None = None
            if evidence_score < 0.25:
                continue
            if parsed and parsed[0] == "projects":
                project_idx = parsed[1]
                if reason_not_rendered == "hidden_project":
                    operation = "add_selected_project_line"
                    next_model = _clone_model_with_preserved_project_line(
                        current_model,
                        project_idx,
                        source_path=source_path,
                        claim=claim,
                    )
            elif parsed and parsed[0] == "experience" and parsed[2] is not None:
                entry_idx, bullet_idx = parsed[1], parsed[2]
                if reason_not_rendered in {"bullet_trimmed", "not_selected_by_bullet_cap"} and effective_cap is not None:
                    operation = "restore_trimmed_bullet"
                    next_model = _clone_model_with_restored_experience_bullet(current_model, entry_idx, bullet_idx, effective_cap)
                elif reason_not_rendered in {"bullet_trimmed", "not_selected_by_bullet_cap"} and effective_cap is None:
                    decision["decision"] = "not_attempted"
                    decision["reason"] = "cannot_identify_trimmed_bullet_retention_state"
                    decision["attempted_operations"] = []
                    decision["candidate_sources"] = candidate_sources
                    preservation_decisions.append(decision)
                    kept = False
                    break
                elif reason_not_rendered in {"earlier_grouped", "role_collapsed"} and earlier_mode == "grouped":
                    operation = "promote_grouped_support_signal"
                    next_model = _clone_model_with_compact_summary_from_bullet(current_model, entry_idx, bullet_idx)

            if next_model is None:
                continue
            attempted_ops.append(operation)

            next_html, next_prepared = _build_html_and_prepared_for_resume(next_model, template_name=template_name)
            next_planning = _build_planning_with_evidence(
                model=next_model,
                prepared=next_prepared,
                template_name=template_name,
                job_description=job_description,
            )
            measured_pages, fit = _measured_fit(next_planning)
            before_status = str(coverage.get("coverage_status", ""))
            before_retained = int(coverage.get("retained_primary_supporting_evidence_count", 0) or 0)
            before_rank = _coverage_rank(before_status)
            after_coverage_lookup = {
                _normalize_skill_claim_key(str(item.get("claim", ""))): item
                for item in next_planning.get("claim_coverage", [])
                if isinstance(item, dict)
            }
            after_item = after_coverage_lookup.get(claim_key, {})
            after_status = str(after_item.get("coverage_status", ""))
            after_retained = int(after_item.get("retained_primary_supporting_evidence_count", 0) or 0)
            after_rank = _coverage_rank(after_status)
            coverage_improved = after_rank > before_rank or (
                after_rank == before_rank and after_retained > before_retained
            )
            required_tokens = claim_distinctive_tokens(claim)
            matched_tokens = list(after_item.get("distinctive_tokens_matched", [])) if isinstance(after_item, dict) else []
            attempt = {
                "step": "evidence_preservation",
                "claim": claim,
                "operation": operation,
                "source_label": str(candidate.get("source_label", "")),
                "source_path": source_path,
                "snippet": str(candidate.get("text", ""))[:180],
                "reason": "visible_claim_weak_or_unsupported_with_source_primary_evidence",
                "measured_pages": measured_pages,
                "fit": fit,
                "kept": bool(fit and coverage_improved),
                "target_claim_status_before": before_status,
                "target_claim_status_after": after_status,
                "retained_primary_count_before": before_retained,
                "retained_primary_count_after": after_retained,
                "claim_coverage_improved": bool(coverage_improved),
                "distinctive_tokens_required": required_tokens,
                "distinctive_tokens_matched": matched_tokens,
            }
            if fit and not coverage_improved:
                attempt["reason"] = "no_claim_coverage_improvement_after_render"
            preservation_attempts.append(attempt)
            if fit and coverage_improved:
                current_model = next_model
                current_html = next_html
                current_prepared = next_prepared
                current_planning = next_planning
                preserved_claims.add(claim_key)
                kept = True
                break
        if any(
            isinstance(item, dict)
            and str(item.get("decision", "")) in {"not_attempted", "attempted"}
            and str(item.get("claim", "")) == claim
            for item in preservation_decisions
        ):
            continue
        if kept:
            decision["decision"] = "attempted"
            decision["reason"] = "source_primary_evidence_available_and_candidate_operation_supported"
            decision["attempted_operations"] = attempted_ops
            preservation_decisions.append(decision)
        else:
            overflow_attempted = any(not bool(attempt.get("fit", True)) for attempt in preservation_attempts if attempt.get("claim") == claim)
            no_improvement = any(
                attempt.get("claim") == claim
                and bool(attempt.get("fit", False))
                and not bool(attempt.get("claim_coverage_improved", False))
                for attempt in preservation_attempts
            )
            decision["decision"] = "skipped_would_exceed_page_target" if overflow_attempted else "not_attempted"
            decision["reason"] = (
                "all_candidate_operations_exceeded_page_target"
                if overflow_attempted
                else ("no_claim_coverage_improvement_after_render" if no_improvement else "no_supported_preservation_operation_for_candidate_evidence")
            )
            decision["attempted_operations"] = attempted_ops
            decision["candidate_sources"] = candidate_sources
            preservation_decisions.append(decision)
        if kept:
            # refresh lookup for subsequent claims
            claim_coverage_lookup = {
                _normalize_skill_claim_key(str(item.get("claim", ""))): item
                for item in current_planning.get("claim_coverage", [])
                if isinstance(item, dict)
            }

    existing_ops = current_planning.get("planning_operations")
    if not isinstance(existing_ops, list):
        existing_ops = []
    if preservation_attempts:
        current_planning["planning_operations"] = [*existing_ops, *preservation_attempts]
    current_planning["evidence_preservation_attempts"] = preservation_attempts
    current_planning["evidence_preservation_decisions"] = preservation_decisions
    current_planning["unsupported_visible_claims_without_source_evidence"] = [
        {"claim": item.get("claim"), "reason": "no_primary_source_evidence_found"}
        for item in current_planning.get("claim_coverage", [])
        if isinstance(item, dict)
        and str(item.get("coverage_status")) == "unsupported"
        and int(item.get("primary_supporting_evidence_count", 0) or 0) == 0
    ]
    return current_model, current_html, current_prepared, current_planning


def _apply_evidence_aware_skill_replacements(
    *,
    model: ResumeRenderModel,
    html: str,
    prepared: Any,
    planning: dict[str, Any],
    template_name: str,
    job_description: str,
    skills_selection: dict[str, Any] | None,
    render_planning_service: RenderPlanningService | None = None,
    skill_repair_helpers: SkillRepairPlanner | None = None,
) -> tuple[ResumeRenderModel, str, Any, dict[str, Any]]:
    """Prefer supported visible skills over weak/unsupported claims."""
    adjustments: list[dict[str, Any]] = []
    planning_step_ops: list[dict[str, Any]] = []
    unsupported_skill_removals: list[dict[str, Any]] = []
    dispositions: list[SkillDisposition] = []
    candidates_considered: list[dict[str, Any]] = []
    candidate_search_summaries: list[dict[str, Any]] = []
    candidate_search_lookup: dict[str, dict[str, Any]] = {}
    score_map = _skill_score_map_from_selection(skills_selection)
    current_model = model
    current_html = html
    current_prepared = prepared
    current_planning = planning
    preserved_attempts = list(planning.get("evidence_preservation_attempts", [])) if isinstance(
        planning.get("evidence_preservation_attempts"), list
    ) else []
    preserved_decisions = list(planning.get("evidence_preservation_decisions", [])) if isinstance(
        planning.get("evidence_preservation_decisions"), list
    ) else []
    unsupported_before = list(planning.get("unsupported_visible_claims_before_preservation", []))
    weak_before = list(planning.get("weak_visible_claims_before_preservation", []))
    used_candidates: set[str] = set()
    replaced_claim_keys: set[str] = set()
    min_visible_skill_count = 12
    if isinstance(skills_selection, dict):
        try:
            min_visible_skill_count = max(1, int(skills_selection.get("min_count", min_visible_skill_count)))
        except (TypeError, ValueError):
            min_visible_skill_count = 12
    helpers = skill_repair_helpers or SkillRepairPlanner(
        apply_skill_repair=lambda **kwargs: (
            kwargs["model"],
            kwargs["html"],
            kwargs["prepared"],
            kwargs["planning"],
        ),
        render_planning_service=render_planning_service,
    )

    replacement_result = helpers.apply_replacements(
        model=current_model,
        html=current_html,
        prepared=current_prepared,
        planning=current_planning,
        context=SkillRepairContext(
            template_name=template_name,
            job_description=job_description,
            skills_selection=skills_selection,
            render_planning_service=render_planning_service,
        ),
        score_map=score_map,
        used_candidates=used_candidates,
        replaced_claim_keys=replaced_claim_keys,
        adjustments=adjustments,
        planning_step_ops=planning_step_ops,
        dispositions=dispositions,
        candidates_considered=candidates_considered,
        candidate_search_summaries=candidate_search_summaries,
        candidate_search_lookup=candidate_search_lookup,
        build_claim_coverage_for_claims_fn=build_claim_coverage_for_claims,
        extract_all_skill_claims_fn=extract_all_skill_claims,
        clone_model_with_swapped_skills_fn=_clone_model_with_swapped_skills,
        measured_fit_fn=_measured_fit,
        build_html_and_prepared_fn=_build_html_and_prepared_for_resume,
        build_planning_with_evidence_fn=_build_planning_with_evidence,
    )
    current_model = replacement_result.model
    current_html = replacement_result.html
    current_prepared = replacement_result.prepared
    current_planning = replacement_result.planning
    adjustments = replacement_result.adjustments
    planning_step_ops = replacement_result.planning_step_ops
    dispositions = replacement_result.dispositions
    candidates_considered = replacement_result.candidates_considered
    candidate_search_summaries = replacement_result.candidate_search_summaries
    candidate_search_lookup = replacement_result.candidate_search_lookup
    used_candidates = replacement_result.used_candidates
    replaced_claim_keys = replacement_result.replaced_claim_keys

    removal_result = helpers.remove_unsupported_claims_until_stable(
        model=current_model,
        html=current_html,
        prepared=current_prepared,
        planning=current_planning,
        context=SkillRepairContext(
            template_name=template_name,
            job_description=job_description,
            skills_selection=skills_selection,
            render_planning_service=render_planning_service,
        ),
        min_visible_skill_count=min_visible_skill_count,
        dispositions=dispositions,
        candidate_search_lookup=candidate_search_lookup,
        used_candidates=used_candidates,
        replaced_claim_keys=replaced_claim_keys,
        planning_step_ops=planning_step_ops,
        unsupported_skill_removals=unsupported_skill_removals,
        score_map=score_map,
        adjustments=adjustments,
        build_claim_coverage_for_claims_fn=build_claim_coverage_for_claims,
        extract_all_skill_claims_fn=extract_all_skill_claims,
        clone_model_without_skill_fn=_clone_model_without_skill,
        measured_fit_fn=_measured_fit,
        build_html_and_prepared_fn=_build_html_and_prepared_for_resume,
        build_planning_with_evidence_fn=_build_planning_with_evidence,
    )
    current_model = removal_result.model
    current_html = removal_result.html
    current_prepared = removal_result.prepared
    current_planning = removal_result.planning
    unsupported_skill_removals = removal_result.unsupported_skill_removals
    planning_step_ops = removal_result.planning_step_ops
    dispositions = removal_result.dispositions
    removed_claim_keys = removal_result.removed_claim_keys
    current_planning = helpers.finalize_repair_report(
        planning=current_planning,
        planning_step_ops=planning_step_ops,
        preserved_attempts=preserved_attempts,
        preserved_decisions=preserved_decisions,
        unsupported_before=unsupported_before,
        weak_before=weak_before,
        adjustments=adjustments,
        unsupported_skill_removals=unsupported_skill_removals,
        candidates_considered=candidates_considered,
        candidate_search_summaries=candidate_search_summaries,
        candidate_search_lookup=candidate_search_lookup,
        dispositions=dispositions,
        replaced_claim_keys=replaced_claim_keys,
        removed_claim_keys=removed_claim_keys,
    )
    return current_model, current_html, current_prepared, current_planning


def resolve_pdf_template_name(profile: dict, explicit_template: str | None = None) -> str:
    """Resolve PDF template name from explicit value or profile config."""

    if explicit_template and str(explicit_template).strip():
        return str(explicit_template).strip()

    render = profile.get("render", {}) if isinstance(profile, dict) else {}
    if isinstance(render, dict):
        theme = render.get("theme", "")
        if str(theme).strip():
            return str(theme).strip()

    tailoring_config = profile.get("tailoring_config", {}) if isinstance(profile, dict) else {}
    if isinstance(tailoring_config, dict):
        template_name = tailoring_config.get("pdf_template", "")
        if str(template_name).strip():
            return str(template_name).strip()

    return DEFAULT_PDF_TEMPLATE


def render_model_to_pdf(
    model: ResumeRenderModel,
    output_path: Path,
    template_name: str = DEFAULT_PDF_TEMPLATE,
    html_only: bool = False,
) -> Path:
    """Render a resume model directly to HTML or PDF."""

    out = Path(output_path)
    html, _prepared = _build_html_and_prepared_for_resume(model, template_name=template_name)

    if html_only:
        out.write_text(html, encoding="utf-8")
        log.info("HTML generated: %s", out)
        return out

    render_pdf(html, str(out))
    log.info("PDF generated: %s", out)
    return out


def render_model_to_pdf_with_planning(
    model: ResumeRenderModel,
    output_path: Path,
    template_name: str = DEFAULT_PDF_TEMPLATE,
    html_only: bool = False,
    job_description: str = "",
    skills_selection: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Render a resume model and return template planning telemetry."""

    out = Path(output_path)
    render_service = RenderPlanningService(
        build_html_and_prepared=_build_html_and_prepared_for_resume,
        build_planning_with_evidence=_build_planning_with_evidence,
        measured_fit=_measured_fit,
    )
    state = render_service.build_state(
        model=model,
        context=RenderPlanningContext(
            template_name=template_name,
            job_description=job_description,
        ),
    )
    html = state.html
    prepared = state.prepared
    planning = state.planning
    planning["unsupported_visible_claims_before_preservation"] = list(planning.get("unsupported_visible_claims", []))
    planning["weak_visible_claims_before_preservation"] = list(planning.get("weak_visible_claims", []))
    planner = EvidenceAwarePdfPlanner(
        apply_evidence_preservation=_apply_evidence_preservation,
        skill_repair_planner=SkillRepairPlanner(
            apply_skill_repair=_apply_evidence_aware_skill_replacements,
            render_planning_service=render_service,
            dependencies=SkillRepairDependencies(
                skill_score_map_from_selection_fn=_skill_score_map_from_selection,
                build_claim_coverage_for_claims_fn=build_claim_coverage_for_claims,
                extract_all_skill_claims_fn=extract_all_skill_claims,
                clone_model_with_swapped_skills_fn=_clone_model_with_swapped_skills,
                clone_model_without_skill_fn=_clone_model_without_skill,
                measured_fit_fn=_measured_fit,
                build_html_and_prepared_fn=_build_html_and_prepared_for_resume,
                build_planning_with_evidence_fn=_build_planning_with_evidence,
            ),
        ),
    )
    planning_result = planner.plan(
        model=model,
        html=html,
        prepared=prepared,
        planning=planning,
        context=PdfPlanningContext(
            template_name=template_name,
            job_description=job_description,
            skills_selection=skills_selection,
            render_planning_service=render_service,
        ),
    )
    model = planning_result.model
    html = planning_result.html
    prepared = planning_result.prepared
    planning = planning_result.planning

    if html_only:
        out.write_text(html, encoding="utf-8")
        log.info("HTML generated: %s", out)
        return out, planning

    render_pdf(html, str(out))
    log.info("PDF generated: %s", out)
    return out, planning


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """Count pages in a PDF byte stream.

    This uses a lightweight token count that is reliable for Chromium-generated
    PDFs used by this module.
    """

    return len(re.findall(rb"/Type\s*/Page\b", pdf_bytes))


def measure_html_page_count(html: str) -> int:
    """Render HTML to a temporary PDF and return its page count."""

    with tempfile.TemporaryDirectory(prefix="applypilot_pdf_measure_") as tmp_dir:
        tmp_pdf = Path(tmp_dir) / "measure.pdf"
        render_pdf(html, str(tmp_pdf))
        pdf_bytes = tmp_pdf.read_bytes()

    page_count = _count_pdf_pages(pdf_bytes)
    if page_count < 1:
        raise RuntimeError("Unable to measure PDF page count from rendered HTML.")
    return page_count


def measure_model_page_count(
    model: ResumeRenderModel,
    template_name: str = DEFAULT_PDF_TEMPLATE,
) -> int:
    """Measure rendered page count for a resume model + template."""

    html = build_html_for_resume(model, template_name=template_name)
    return measure_html_page_count(html)


# ── PDF Renderer ─────────────────────────────────────────────────────────


def render_pdf(html: str, output_path: str) -> None:
    """Render HTML to PDF using Playwright's headless Chromium.

    Args:
        html: Complete HTML string.
        output_path: Path to write the PDF file.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=output_path,
            format="Letter",
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            print_background=True,
        )
        browser.close()


# ── Public API ───────────────────────────────────────────────────────────


def convert_to_pdf(
    text_path: Path,
    output_path: Path | None = None,
    html_only: bool = False,
    template_name: str = DEFAULT_PDF_TEMPLATE,
) -> Path:
    """Convert a text resume/cover letter to PDF.

    Args:
        text_path: Path to the .txt file to convert.
        output_path: Optional override for the output path. Defaults to same
            name with .pdf extension.
        html_only: If True, output HTML instead of PDF.
        template_name: Template identifier used for HTML generation.

    Returns:
        Path to the generated PDF (or HTML) file.
    """
    text_path = Path(text_path)
    text = text_path.read_text(encoding="utf-8")
    parsed = parse_resume(text)
    model = build_render_model(parsed)
    html = build_html_for_resume(model, template_name=template_name)

    if html_only:
        out = output_path or text_path.with_suffix(".html")
        out = Path(out)
        out.write_text(html, encoding="utf-8")
        log.info("HTML generated: %s", out)
        return out

    out = output_path or text_path.with_suffix(".pdf")
    out = Path(out)
    render_pdf(html, str(out))
    log.info("PDF generated: %s", out)
    return out


def batch_convert(limit: int = 0, template_name: str = DEFAULT_PDF_TEMPLATE) -> int:
    """Convert .txt files in TAILORED_DIR that don't have corresponding PDFs.

    Scans for .txt files (excluding _JOB.txt and _REPORT.json), checks if a
    .pdf with the same stem already exists, and converts any that are missing.

    Args:
        limit: Maximum number of files to convert (0 = all eligible files).
        template_name: Template identifier used for HTML generation.

    Returns:
        Number of PDFs generated.
    """
    if not TAILORED_DIR.exists():
        log.warning("Tailored directory does not exist: %s", TAILORED_DIR)
        return 0

    txt_files = sorted(TAILORED_DIR.glob("*.txt"))
    # Exclude _JOB.txt and _CL.txt files from resume conversion
    # (they get their own conversion calls)
    candidates = [f for f in txt_files if not f.name.endswith("_JOB.txt")]

    # Filter to those without a corresponding PDF
    to_convert: list[Path] = []
    for f in candidates:
        pdf_path = f.with_suffix(".pdf")
        if not pdf_path.exists():
            to_convert.append(f)
        if limit > 0 and len(to_convert) >= limit:
            break

    if not to_convert:
        log.debug("All text files already have PDFs.")
        return 0

    log.info("Converting %d files to PDF...", len(to_convert))
    converted = 0

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            for f in to_convert:
                try:
                    text = f.read_text(encoding="utf-8")
                    parsed = parse_resume(text)
                    model = build_render_model(parsed)
                    html = build_html_for_resume(model, template_name=template_name)
                    out = f.with_suffix(".pdf")
                    page.set_content(html, wait_until="networkidle")
                    page.pdf(
                        path=str(out),
                        format="Letter",
                        margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                        print_background=True,
                    )
                    log.info("PDF generated: %s", out)
                    converted += 1
                except Exception as e:
                    log.error("Failed to convert %s: %s", f.name, e)
        finally:
            browser.close()

    log.info("Done: %d/%d PDFs generated in %s", converted, len(to_convert), TAILORED_DIR)
    return converted
