"""Measurement-aware professional compact resume template."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Callable
from urllib.parse import urlparse

from applypilot.scoring.pdf_render_model import ResumeEntry, ResumeRenderModel

_DEFAULT_PAGE_TARGET = 2.5
_MONTH_ABBR = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}
TEMPLATE_INFO = {
    "name": "professional_compact",
    "display_name": "Professional Compact",
    "description": "Measurement-aware production template that compacts later experience entries when needed.",
}
TEMPLATE_CAPABILITIES = [
    "measurement_aware_prepare",
    "selected_experience_rendering",
]
TEMPLATE_INPUT_PREFERENCES = {
    "expects": "ResumeRenderModel",
    "preferred_path": "structured_json_to_render_model",
    "requested_entry_fields": ["compact_summary"],
    "prefers_compact_summary": True,
}
TEMPLATE_REQUIREMENTS = {
    "hooks": ["build_html", "prepare", "prepare_with_measurement"],
}
TEMPLATE_OPTIONS = {
    "page_target": {"type": "float", "default": 2.5},
    "max_resume_pages": {"type": "float", "default": 2.5},
    "compact_max_detailed_experience": {"type": "int", "min": 1},
}


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


def _allowed_physical_pages(page_target: float) -> int:
    return max(1, int(math.ceil(page_target)))


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
        detailed_count = min(hard_cap, len(model.experience))
        if model.experience:
            detailed_count = max(1, detailed_count)
        return _build_candidate_view(model, detailed_count=detailed_count, page_target=page_target)

    total_entries = len(model.experience)
    min_detailed = 1 if total_entries > 0 else 0
    allowed_pages = _allowed_physical_pages(page_target)
    tightest_candidate = _build_candidate_view(model, detailed_count=min_detailed, page_target=page_target)

    for detailed_count in range(total_entries, min_detailed - 1, -1):
        candidate = _build_candidate_view(model, detailed_count=detailed_count, page_target=page_target)
        html = build_html(candidate)
        page_count = measure_html_page_count(html)
        tightest_candidate = candidate
        if page_count <= allowed_pages:
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
        return _format_date_text(subtitle), True

    return "", False


def _split_subtitle(subtitle: str) -> tuple[str, str]:
    parts = [part.strip() for part in subtitle.split("|") if part.strip()]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", _format_date_text(parts[0])
    return parts[0], _format_date_text(" | ".join(parts[1:]))


def _extract_project_context_and_dates(subtitle: str) -> tuple[str, str]:
    parts = [part.strip() for part in subtitle.split("|") if part.strip()]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", _format_date_text(parts[0])
    return _format_date_text(" | ".join(parts[:-1])), _format_date_text(parts[-1])


def _build_skill_lines(skills: list) -> list[str]:
    seen: set[str] = set()
    flattened: list[str] = []
    for skill in skills:
        for raw in str(skill.value).split(","):
            token = raw.strip()
            key = token.lower()
            if not token or key in seen:
                continue
            seen.add(key)
            flattened.append(token)

    if not flattened:
        return []

    lines: list[str] = []
    chunk_size = 6
    for idx in range(0, len(flattened), chunk_size):
        lines.append(" • ".join(flattened[idx:idx + chunk_size]))
    return lines


def _format_date_text(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        year = int(match.group(1))
        month = int(match.group(2))
        month_text = _MONTH_ABBR.get(month)
        if not month_text:
            return match.group(0)
        return f"{month_text} {year}"

    return re.sub(r"\b(\d{4})-(\d{2})(?:-(\d{2}))?\b", _replace, text)


def _is_email(value: str) -> bool:
    return "@" in value and "." in value.split("@")[-1]


def _is_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return len(digits) >= 10 and bool(re.fullmatch(r"[0-9\-\+\(\)\.\s]+", value))


def _normalize_display_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


def _is_url_like(value: str) -> bool:
    low = value.lower().strip()
    if low.startswith(("http://", "https://")):
        return True
    return any(domain in low for domain in ("github.com", "linkedin.com", "gitlab.com", "bitbucket.org"))


def _build_contact_lines(location: str, contact: str, *, include_country_in_location: bool = False) -> tuple[str, str]:
    parts = [part.strip() for part in contact.split("|")] if contact else []
    phones: list[str] = []
    emails: list[str] = []
    urls: list[str] = []
    others: list[str] = []

    for part in parts:
        if not part:
            continue
        if _is_phone(part):
            phones.append(part)
            continue
        if _is_email(part):
            emails.append(part)
            continue
        if _is_url_like(part):
            normalized = _normalize_display_url(part)
            if normalized:
                urls.append(normalized)
            continue
        others.append(part)

    primary_parts: list[str] = []
    location_text = location.strip()
    if not include_country_in_location:
        location_text = re.sub(r",\s*(US|USA|United States)$", "", location_text, flags=re.IGNORECASE).strip()
    if location_text:
        primary_parts.append(location_text)
    primary_parts.extend(phones)
    primary_parts.extend(emails)
    primary_parts.extend(others)

    primary_line = " • ".join(primary_parts)
    url_line = " • ".join(urls)
    return primary_line, url_line


def build_html(view: ProfessionalCompactTemplateView) -> str:
    """Build professional compact resume HTML from a prepared view."""
    resume = view.model

    # Skills
    skills_html = ""
    if resume.skills:
        rows = "".join(f'<div class="skill-line">{line}</div>' for line in _build_skill_lines(resume.skills))
        skills_html = f'<section class="section"><h2 class="section-title">Technical Skills</h2>{rows}</section>'

    # Experience
    exp_html = ""
    if view.detailed_experience:
        items = ""
        for entry in view.detailed_experience:
            company, detail_line = _split_subtitle(entry.subtitle)
            heading = f"{company} - {entry.title}" if company else entry.title
            subtitle = f'<div class="entry-subtitle">{detail_line}</div>' if detail_line else ""
            bullets = "".join(f"<li>{bullet}</li>" for bullet in entry.bullets)
            bullet_list = f'<ul class="entry-bullets">{bullets}</ul>' if bullets else ""
            items += f'<article class="entry"><h3 class="entry-title">{heading}</h3>{subtitle}{bullet_list}</article>'
        exp_html = f'<section class="section"><h2 class="section-title">Experience</h2>{items}</section>'

    # Selected Experience (compact entries)
    selected_exp_html = ""
    if view.compact_experience:
        items = ""
        for entry in view.compact_experience:
            summary, used_subtitle_as_summary = _build_compact_entry_summary(entry)
            company, detail_line = _split_subtitle(entry.subtitle)
            company_text = company if company else entry.title
            role_text = entry.title if company else ""
            role_suffix = f" - {role_text}" if role_text else ""
            detail_suffix = f" | {detail_line}" if detail_line and not used_subtitle_as_summary else ""
            summary_html = f'<p class="compact-summary">{summary}</p>' if summary else ""
            items += (
                '<article class="compact-entry">'
                f'<div class="compact-meta"><strong class="compact-company">{company_text}{role_suffix}</strong>'
                f'<span class="compact-date">{detail_suffix}</span></div>'
                f"{summary_html}"
                "</article>"
            )
        selected_exp_html = f'<section class="section"><h2 class="section-title">Selected Experience</h2>{items}</section>'

    # Projects
    proj_html = ""
    if view.projects_to_render:
        items = ""
        for entry in view.projects_to_render:
            context_line, date_line = _extract_project_context_and_dates(entry.subtitle)
            title_row = (
                '<div class="project-title-row">'
                f'<h3 class="entry-title">{entry.title}</h3>'
                f'<span class="project-dates">{date_line}</span>'
                "</div>"
            )
            subtitle = f'<div class="entry-subtitle">{context_line}</div>' if context_line else ""
            bullets = "".join(f"<li>{bullet}</li>" for bullet in entry.bullets)
            bullet_list = f'<ul class="entry-bullets">{bullets}</ul>' if bullets else ""
            items += f'<article class="entry">{title_row}{subtitle}{bullet_list}</article>'
        proj_html = f'<section class="section"><h2 class="section-title">Projects</h2>{items}</section>'

    # Education
    edu_html = ""
    if resume.education:
        edu_html = f'<section class="section"><h2 class="section-title">Education</h2><p class="edu">{resume.education}</p></section>'

    # Summary
    summary_html = ""
    if resume.summary:
        summary_html = f'<section class="section"><h2 class="section-title">Summary</h2><p class="summary">{resume.summary}</p></section>'

    # Contact line parsing
    include_country = bool(resume.render_options.get("include_country_in_location", False))
    primary_contact_line, url_contact_line = _build_contact_lines(
        resume.location,
        resume.contact,
        include_country_in_location=include_country,
    )
    header_contact_html = ""
    if primary_contact_line:
        header_contact_html += f'<div class="contact primary-contact">{primary_contact_line}</div>'
    if url_contact_line:
        header_contact_html += f'<div class="contact links-contact">{url_contact_line}</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{
    size: letter;
    margin: 0.68in 0.7in;
}}
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}
body {{
    font-family: Arial, Helvetica, sans-serif;
    font-size: 11pt;
    line-height: 1.42;
    color: #111111;
}}
.page {{
    max-width: 6.8in;
    margin: 0 auto;
}}
.header {{
    margin-bottom: 18px;
    padding-bottom: 11px;
    border-bottom: 1px solid #222222;
}}
.name {{
    font-size: 24pt;
    font-weight: 700;
    letter-spacing: 0.2px;
}}
.contact {{
    margin-top: 4px;
    font-size: 10.4pt;
    color: #303030;
}}
.primary-contact {{
    margin-top: 7px;
}}
.links-contact {{
    margin-top: 2px;
}}
.section {{
    margin-top: 16px;
}}
.section-title {{
    font-size: 14.5pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.1px;
    margin-bottom: 8px;
}}
.summary {{
    font-size: 11pt;
    line-height: 1.45;
    color: #222222;
}}
.skill-line {{
    font-size: 10.8pt;
    line-height: 1.38;
    color: #1c1c1c;
    margin-bottom: 2px;
}}
.entry {{
    margin-bottom: 14px;
    break-inside: avoid;
}}
.entry-title {{
    font-weight: 700;
    font-size: 11.4pt;
    line-height: 1.3;
}}
.entry-subtitle {{
    margin-top: 2px;
    font-size: 10.2pt;
    font-style: italic;
    color: #444444;
}}
.project-title-row {{
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: baseline;
}}
.project-dates {{
    font-size: 10.2pt;
    font-style: italic;
    color: #444444;
    white-space: nowrap;
}}
.entry-bullets {{
    margin: 6px 0 0 24px;
    padding: 0;
}}
.entry-bullets li {{
    margin-bottom: 4px;
    font-size: 10.9pt;
    line-height: 1.42;
}}
.compact-entry {{
    margin-bottom: 10px;
}}
.compact-meta {{
    font-size: 10.7pt;
    line-height: 1.36;
}}
.compact-company {{
    font-weight: 700;
}}
.compact-date {{
    color: #454545;
}}
.compact-summary {{
    margin-top: 2px;
    font-size: 10.8pt;
    line-height: 1.4;
    color: #222222;
}}
.edu {{
    font-size: 10.8pt;
    line-height: 1.38;
    color: #1f1f1f;
}}
</style>
</head>
<body>
<div class="page">
<header class="header">
    <h1 class="name">{resume.name}</h1>
    {header_contact_html}
</header>
{summary_html}
{skills_html}
{exp_html}
{selected_exp_html}
{proj_html}
{edu_html}
</div>
</body>
</html>"""
