"""Classic baseline HTML/CSS template for scored resume PDF generation."""

from applypilot.scoring.pdf_render_model import ResumeRenderModel

TEMPLATE_INFO = {
    "name": "classic",
    "display_name": "Classic",
    "description": "Baseline renderer with no measurement-aware or heuristic compaction planning.",
}
TEMPLATE_CAPABILITIES = [
    "baseline_rendering",
]
TEMPLATE_INPUT_PREFERENCES = {
    "expects": "ResumeRenderModel",
}
TEMPLATE_REQUIREMENTS = {
    "hooks": ["build_html", "prepare"],
}
TEMPLATE_OPTIONS = {}


def prepare(model: ResumeRenderModel) -> ResumeRenderModel:
    """Prepare a render model for the classic template (no-op)."""

    return model


def build_html(resume: ResumeRenderModel) -> str:
    """Build baseline resume HTML from parsed data."""

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
    contact_html = " &nbsp;|&nbsp; ".join(contact_parts)

    # Location line (may be empty)
    location_html = f'<div class="location">{resume.location}</div>' if resume.location else ""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{
    size: letter;
    margin: 0.35in 0.5in;
}}
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}
body {{
    font-family: 'Calibri', 'Segoe UI', Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.35;
    color: #1a1a1a;
}}
.header {{
    text-align: center;
    margin-bottom: 4px;
    padding-bottom: 4px;
    border-bottom: 1.5px solid #2a7ab5;
}}
.name {{
    font-size: 18pt;
    font-weight: 700;
    color: #1a3a5c;
    letter-spacing: 0.5px;
}}
.title {{
    font-size: 10.5pt;
    color: #3a6b8c;
    margin: 1px 0;
}}
.location {{
    font-size: 9pt;
    color: #555;
}}
.contact {{
    font-size: 9pt;
    color: #444;
    margin-top: 1px;
}}
.contact a {{
    color: #2c3e50;
    text-decoration: none;
}}
.section {{
    margin-top: 5px;
}}
.section-title {{
    font-size: 10pt;
    font-weight: 700;
    color: #1a3a5c;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    border-bottom: 1.5px solid #2a7ab5;
    padding-bottom: 1px;
    margin-bottom: 3px;
}}
.summary {{
    font-size: 9.5pt;
    color: #333;
    line-height: 1.4;
}}
.skill-row {{
    font-size: 9.5pt;
    margin: 0;
    line-height: 1.35;
}}
.skill-cat {{
    font-weight: 600;
    color: #1a3a5c;
}}
.entry {{
    margin-bottom: 4px;
    break-inside: avoid;
}}
.entry-title {{
    font-weight: 600;
    font-size: 10pt;
    color: #1a3a5c;
}}
.entry-subtitle {{
    font-size: 9pt;
    color: #4a7a9b;
    font-style: italic;
    margin-bottom: 1px;
}}
ul {{
    margin-left: 14px;
    padding: 0;
}}
li {{
    font-size: 9.5pt;
    margin-bottom: 1px;
    line-height: 1.35;
}}
.edu {{
    font-size: 10pt;
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
