"""Compact HTML/CSS template for scored resume PDF generation."""

from dataclasses import dataclass

from applypilot.scoring.pdf_render_model import ResumeRenderModel


@dataclass
class CompactTemplateView:
    """Prepared compact-template view.

    This template-specific wrapper is where compact layout planning decisions
    can be added later without changing the shared ResumeRenderModel.
    """

    model: ResumeRenderModel


def prepare(model: ResumeRenderModel) -> CompactTemplateView:
    """Prepare a render model for the compact template.

    This initial seam preserves content behavior and wraps the shared model in
    a compact-template-specific prepared view.
    """

    return CompactTemplateView(model=model)


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
    if resume.experience:
        items = ""
        for entry in resume.experience:
            bullets = "".join(f"<li>{bullet}</li>" for bullet in entry.bullets)
            subtitle = f'<div class="entry-subtitle">{entry.subtitle}</div>' if entry.subtitle else ""
            items += f'<div class="entry"><div class="entry-title">{entry.title}</div>{subtitle}<ul>{bullets}</ul></div>'
        exp_html = f'<div class="section"><div class="section-title">Experience</div>{items}</div>'

    # Projects
    proj_html = ""
    if resume.projects:
        items = ""
        for entry in resume.projects:
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
{proj_html}
{edu_html}
</body>
</html>"""
