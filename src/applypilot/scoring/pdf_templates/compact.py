"""Compact HTML/CSS template for scored resume PDF generation."""

from dataclasses import dataclass

from applypilot.scoring.pdf_render_model import ResumeEntry, ResumeRenderModel

_DEFAULT_MAX_DETAILED_EXPERIENCE = 4
TEMPLATE_INFO = {
    "name": "compact",
    "display_name": "Compact",
    "description": "Heuristic compact template that keeps first N experience entries detailed.",
}
TEMPLATE_CAPABILITIES = [
    "heuristic_prepare",
    "selected_experience_rendering",
]
TEMPLATE_INPUT_PREFERENCES = {
    "expects": "ResumeRenderModel",
}
TEMPLATE_REQUIREMENTS = {
    "hooks": ["build_html", "prepare"],
}
TEMPLATE_OPTIONS = {
    "compact_max_detailed_experience": {"type": "int", "default": 4, "min": 1},
}


@dataclass
class CompactTemplateView:
    """Prepared compact-template view.

    This template-specific wrapper is where compact layout planning decisions
    can be added later without changing the shared ResumeRenderModel.
    """

    model: ResumeRenderModel
    detailed_experience: list[ResumeEntry]
    compact_experience: list[ResumeEntry]
    projects_to_render: list[ResumeEntry]
    page_target: int | None = None


def _resolve_max_detailed_experience(model: ResumeRenderModel) -> int:
    raw = model.render_options.get("compact_max_detailed_experience")
    if isinstance(raw, bool):
        return _DEFAULT_MAX_DETAILED_EXPERIENCE
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_DETAILED_EXPERIENCE
    if parsed < 1:
        return _DEFAULT_MAX_DETAILED_EXPERIENCE
    return parsed


def prepare(model: ResumeRenderModel) -> CompactTemplateView:
    """Prepare a render model for the compact template.

    This initial seam preserves content behavior and wraps the shared model in
    a compact-template-specific prepared view.
    """

    max_detailed = _resolve_max_detailed_experience(model)
    detailed_experience = list(model.experience[:max_detailed])
    compact_experience = list(model.experience[max_detailed:])

    return CompactTemplateView(
        model=model,
        detailed_experience=detailed_experience,
        compact_experience=compact_experience,
        projects_to_render=model.projects,
        page_target=None,
    )


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


def build_html(view: CompactTemplateView) -> str:
    """Build compact resume HTML from a prepared compact template view."""
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

    # Certifications
    cert_html = ""
    if resume.certifications:
        certifications_html = "<br>".join(
            line.strip() for line in str(resume.certifications).splitlines() if line.strip()
        )
        cert_html = (
            '<div class="section"><div class="section-title">Certifications</div>'
            f'<div class="edu">{certifications_html}</div></div>'
        )

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
{cert_html}
</body>
</html>"""
