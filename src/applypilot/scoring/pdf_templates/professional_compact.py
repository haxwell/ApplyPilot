"""Measurement-aware professional compact resume template."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from applypilot.scoring.pdf_render_model import ResumeEntry, ResumeRenderModel

_DEFAULT_PAGE_TARGET = 2.0


@dataclass
class ProfessionalCompactTemplateView:
    """Prepared professional-compact template view."""

    model: ResumeRenderModel
    detailed_experience: list[ResumeEntry]
    compact_experience: list[ResumeEntry]
    projects_to_render: list[ResumeEntry]
    page_target: float = _DEFAULT_PAGE_TARGET


def _coerce_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 1:
        return None
    return parsed


def _resolve_page_target(model: ResumeRenderModel) -> float:
    raw = model.render_options.get("page_target")
    if raw is None:
        raw = model.render_options.get("max_resume_pages")
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_PAGE_TARGET
    if parsed <= 0:
        return _DEFAULT_PAGE_TARGET
    return parsed


def _build_candidate_view(model: ResumeRenderModel, detailed_count: int, page_target: float) -> ProfessionalCompactTemplateView:
    detailed = list(model.experience[:detailed_count])
    compact = list(model.experience[detailed_count:])
    return ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=detailed,
        compact_experience=compact,
        projects_to_render=list(model.projects),
        page_target=page_target,
    )


def prepare(model: ResumeRenderModel) -> ProfessionalCompactTemplateView:
    """Prepare template view without measurement-aware planning."""

    page_target = _resolve_page_target(model)
    hard_cap = _coerce_positive_int(model.render_options.get("compact_max_detailed_experience"))
    if hard_cap is None:
        detailed_count = len(model.experience)
    else:
        detailed_count = min(hard_cap, len(model.experience))
    return _build_candidate_view(model, detailed_count=detailed_count, page_target=page_target)


def prepare_with_measurement(
    model: ResumeRenderModel,
    measure_html_page_count: Callable[[str], int],
) -> ProfessionalCompactTemplateView:
    """Prepare template view using page-aware compaction planning."""

    page_target = _resolve_page_target(model)
    hard_cap = _coerce_positive_int(model.render_options.get("compact_max_detailed_experience"))
    if hard_cap is not None:
        return _build_candidate_view(model, detailed_count=min(hard_cap, len(model.experience)), page_target=page_target)

    total_entries = len(model.experience)
    tightest_candidate = _build_candidate_view(model, detailed_count=0, page_target=page_target)

    for detailed_count in range(total_entries, -1, -1):
        candidate = _build_candidate_view(model, detailed_count=detailed_count, page_target=page_target)
        html = build_html(candidate)
        page_count = measure_html_page_count(html)
        tightest_candidate = candidate
        if page_count <= page_target:
            return candidate

    return tightest_candidate


def _build_compact_entry_summary(entry: ResumeEntry) -> tuple[str, bool]:
    compact_summary = entry.compact_summary.strip()
    if compact_summary:
        return compact_summary, False

    fallback_parts = [bullet.strip() for bullet in entry.bullets[:2] if bullet.strip()]
    if fallback_parts:
        return " ".join(fallback_parts), False

    subtitle = entry.subtitle.strip()
    if subtitle:
        return subtitle, True

    return "", False


def build_html(view: ProfessionalCompactTemplateView) -> str:
    """Build professional compact resume HTML from a prepared view."""
    resume = view.model

    # Skills
    skills_html = ""
    if resume.skills:
        rows = ""
        for skill in resume.skills:
            rows += f'<div class="skill-row"><span class="skill-cat">{skill.category}:</span> {skill.value}</div>\n'
        skills_html = f'<div class="section"><div class="section-title">Technical Skills</div>{rows}</div>'

    # Experience
    exp_html = ""
    if view.detailed_experience:
        items = ""
        for entry in view.detailed_experience:
            bullets = "".join(f"<li>{bullet}</li>" for bullet in entry.bullets)
            subtitle = f'<div class="entry-subtitle">{entry.subtitle}</div>' if entry.subtitle else ""
            items += f'<div class="entry"><div class="entry-title">{entry.title}</div>{subtitle}<ul>{bullets}</ul></div>'
        exp_html = f'<div class="section"><div class="section-title">Experience</div>{items}</div>'

    # Selected Experience (compact entries)
    selected_exp_html = ""
    if view.compact_experience:
        items = ""
        for entry in view.compact_experience:
            summary, used_subtitle_as_summary = _build_compact_entry_summary(entry)
            subtitle = ""
            if entry.subtitle and not used_subtitle_as_summary:
                subtitle = f'<span class="compact-subtitle">{entry.subtitle}</span>'
            summary_html = f'<div class="compact-summary">{summary}</div>' if summary else ""
            items += (
                '<div class="compact-entry">'
                f'<div class="compact-title">{entry.title}{subtitle}</div>'
                f"{summary_html}"
                "</div>"
            )
        selected_exp_html = f'<div class="section"><div class="section-title">Selected Experience</div>{items}</div>'

    # Projects
    proj_html = ""
    if view.projects_to_render:
        items = ""
        for entry in view.projects_to_render:
            bullets = "".join(f"<li>{bullet}</li>" for bullet in entry.bullets)
            subtitle = f'<div class="entry-subtitle">{entry.subtitle}</div>' if entry.subtitle else ""
            items += f'<div class="entry"><div class="entry-title">{entry.title}</div>{subtitle}<ul>{bullets}</ul></div>'
        proj_html = f'<div class="section"><div class="section-title">Projects</div>{items}</div>'

    # Education
    edu_html = ""
    if resume.education:
        edu_html = f'<div class="section"><div class="section-title">Education</div><div class="edu">{resume.education}</div></div>'

    # Summary
    summary_html = ""
    if resume.summary:
        summary_html = f'<div class="section"><div class="section-title">Summary</div><div class="summary">{resume.summary}</div></div>'

    # Contact line parsing
    contact_parts = [p.strip() for p in resume.contact.split("|")] if resume.contact else []
    contact_html = " | ".join(contact_parts)

    # Location line (may be empty)
    location_html = f'<div class="location">{resume.location}</div>' if resume.location else ""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{
    size: letter;
    margin: 0.25in 0.35in;
}}
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}
body {{
    font-family: Arial, sans-serif;
    font-size: 9pt;
    line-height: 1.25;
    color: #111;
}}
.header {{
    margin-bottom: 3px;
    padding-bottom: 2px;
    border-bottom: 1px solid #333;
}}
.name {{
    font-size: 14pt;
    font-weight: 700;
}}
.title {{
    font-size: 9.5pt;
    margin-top: 1px;
}}
.location {{
    font-size: 8.5pt;
    color: #444;
}}
.contact {{
    font-size: 8.5pt;
    color: #333;
    margin-top: 1px;
}}
.section {{
    margin-top: 4px;
}}
.section-title {{
    font-size: 9pt;
    font-weight: 700;
    text-transform: uppercase;
    border-bottom: 1px solid #333;
    margin-bottom: 2px;
    padding-bottom: 1px;
}}
.summary {{
    font-size: 8.8pt;
    line-height: 1.3;
}}
.skill-row {{
    font-size: 8.8pt;
    line-height: 1.2;
}}
.skill-cat {{
    font-weight: 700;
}}
.entry {{
    margin-bottom: 3px;
    break-inside: avoid;
}}
.entry-title {{
    font-weight: 700;
    font-size: 9pt;
}}
.entry-subtitle {{
    font-size: 8.4pt;
    color: #444;
    margin-bottom: 1px;
}}
.compact-entry {{
    margin-bottom: 3px;
    line-height: 1.25;
}}
.compact-title {{
    font-size: 8.8pt;
    font-weight: 700;
}}
.compact-subtitle {{
    font-weight: 400;
    color: #444;
    margin-left: 4px;
}}
.compact-summary {{
    font-size: 8.6pt;
    color: #222;
}}
ul {{
    margin-left: 12px;
    padding: 0;
}}
li {{
    font-size: 8.8pt;
    margin-bottom: 1px;
    line-height: 1.25;
}}
.edu {{
    font-size: 8.8pt;
}}
</style>
</head>
<body>
<div class="header">
    <div class="name">{resume.name}</div>
    <div class="title">{resume.title}</div>
    {location_html}
    <div class="contact">{contact_html}</div>
</div>
{summary_html}
{skills_html}
{exp_html}
{selected_exp_html}
{proj_html}
{edu_html}
</body>
</html>"""
