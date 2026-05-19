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
from applypilot.resume.evidence import build_evidence_mapping_report
from applypilot.scoring.pdf_render_model import (
    ResumeEntry,
    ResumeRenderModel,
    SkillSection,
)
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
) -> tuple[Path, dict[str, Any]]:
    """Render a resume model and return template planning telemetry."""

    out = Path(output_path)
    html, prepared = _build_html_and_prepared_for_resume(model, template_name=template_name)
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
