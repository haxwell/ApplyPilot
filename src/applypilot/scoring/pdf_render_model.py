"""Typed render model for scored resume PDF templates."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from applypilot.resume_json import format_education_entry
from applypilot.scoring.skills_relevance import build_relevant_skills

@dataclass
class SkillSection:
    category: str
    value: str


@dataclass
class ResumeEntry:
    title: str
    subtitle: str = ""
    bullets: list[str] = field(default_factory=list)
    compact_summary: str = ""
    company: str = ""
    role: str = ""
    location: str = ""
    technologies: list[str] = field(default_factory=list)
    is_contract: bool = False
    start_date: str = ""
    end_date: str = ""
    dates: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResumeRenderModel:
    name: str = ""
    title: str = ""
    location: str = ""
    contact: str = ""
    summary: str = ""
    skills: list[SkillSection] = field(default_factory=list)
    experience: list[ResumeEntry] = field(default_factory=list)
    projects: list[ResumeEntry] = field(default_factory=list)
    education: str = ""
    render_options: dict[str, Any] = field(default_factory=dict)


def _normalize_bullet_text(bullet: Any) -> str:
    if bullet is None:
        return ""
    if isinstance(bullet, str):
        return bullet.strip()
    if isinstance(bullet, dict):
        for key in ("text", "bullet", "value", "content"):
            value = bullet.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if value is not None and not isinstance(value, (dict, list)):
                as_text = str(value).strip()
                if as_text:
                    return as_text
        return ""
    return str(bullet).strip()


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return default


def _normalize_date_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.lower() in {"none", "null"}:
        return ""
    return text


def _parse_legacy_date_range(text: str) -> tuple[str, str]:
    cleaned = text.strip()
    if not cleaned:
        return "", ""
    match = re.search(
        r"(?P<start>\d{4}(?:-\d{2})?(?:-\d{2})?)\s*-\s*(?P<end>\d{4}(?:-\d{2})?(?:-\d{2})?|Present)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not match:
        return "", ""
    start = _normalize_date_value(match.group("start"))
    end = _normalize_date_value(match.group("end"))
    return start, end


def _normalize_technologies(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _normalize_company_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _infer_company_from_legacy_fields(entry: ResumeEntry) -> str:
    if entry.company.strip():
        return entry.company.strip()
    subtitle = entry.subtitle.strip()
    if subtitle:
        first = subtitle.split("|", 1)[0].strip()
        if first:
            return first
    return ""


def _reconcile_entry_with_profile_work(entry: ResumeEntry, profile_work: list[dict[str, Any]]) -> ResumeEntry:
    company_key = _normalize_company_key(_infer_company_from_legacy_fields(entry))
    if not company_key:
        return entry

    matched: dict[str, Any] | None = None
    for role in profile_work:
        if not isinstance(role, dict):
            continue
        role_key = _normalize_company_key(str(role.get("company", "")))
        if role_key and role_key == company_key:
            matched = role
            break

    if matched is None:
        return entry

    if not entry.company.strip():
        entry.company = str(matched.get("company", "")).strip()
    if not entry.role.strip():
        entry.role = str(matched.get("position", "")).strip() or entry.title
    if not entry.location.strip():
        entry.location = str(matched.get("location", "")).strip()
    if not entry.start_date.strip():
        entry.start_date = _normalize_date_value(matched.get("start_date"))
    if not entry.end_date.strip():
        entry.end_date = _normalize_date_value(matched.get("end_date"))
    if not entry.technologies:
        entry.technologies = _normalize_technologies(matched.get("technologies", []))
    # Profile work metadata is authoritative for contract status.
    entry.is_contract = _coerce_bool(matched.get("is_contract"), default=False)
    return entry


def _normalize_entry(entry: Any, *, is_project: bool = False) -> ResumeEntry | None:
    if not isinstance(entry, dict):
        return None

    company = str(entry.get("company", "")).strip()
    role = str(entry.get("role", "")).strip()
    location = str(entry.get("location", "")).strip()
    header = str(entry.get("header", "")).strip()
    title = str(entry.get("name", "")).strip() if is_project else role
    if not title:
        title = header
    subtitle = str(entry.get("subtitle", "")).strip()
    description = str(entry.get("description", "")).strip()
    dates = str(entry.get("dates", "")).strip()
    start_date = _normalize_date_value(entry.get("start_date"))
    end_date = _normalize_date_value(entry.get("end_date"))
    technologies = _normalize_technologies(entry.get("technologies", []))
    is_contract = _coerce_bool(entry.get("is_contract"), default=False)

    if not start_date and not end_date:
        start_from_dates, end_from_dates = _parse_legacy_date_range(dates)
        start_date = start_date or start_from_dates
        end_date = end_date or end_from_dates
    if not start_date and not end_date:
        start_from_subtitle, end_from_subtitle = _parse_legacy_date_range(subtitle)
        start_date = start_date or start_from_subtitle
        end_date = end_date or end_from_subtitle

    compact_summary = ""
    for key in ("compact_summary", "summary", "short_summary"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            compact_summary = value.strip()
            break

    raw_bullets = entry.get("bullets", [])
    bullets: list[str] = []
    if isinstance(raw_bullets, list):
        for raw in raw_bullets:
            text = _normalize_bullet_text(raw)
            if text:
                bullets.append(text)

    if not title and not subtitle and not bullets and not company and not description:
        return None

    metadata: dict[str, Any] = {}
    if description:
        metadata["description"] = description

    return ResumeEntry(
        title=title,
        subtitle=subtitle,
        bullets=bullets,
        compact_summary=compact_summary,
        company=company,
        role=role,
        location=location,
        technologies=technologies,
        is_contract=is_contract,
        start_date=start_date,
        end_date=end_date,
        dates=dates,
        metadata=metadata,
    )


def _build_location(personal: dict, *, include_country: bool = False) -> str:
    city = str(personal.get("city", "")).strip()
    state = str(personal.get("province_state", "")).strip()
    country = str(personal.get("country", "")).strip()
    postal_code = str(personal.get("postal_code", "")).strip()

    city_state = ", ".join(part for part in (city, state) if part)
    if city_state and country and include_country:
        return f"{city_state}, {country}"
    if city_state:
        return city_state
    if country and postal_code and include_country:
        return f"{postal_code}, {country}"
    if country and include_country:
        return country
    if postal_code:
        return postal_code

    return str(personal.get("location", "")).strip()


def _extract_render_options(profile: dict) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if not isinstance(profile, dict):
        return options

    tailoring_config = profile.get("tailoring_config", {})
    if isinstance(tailoring_config, dict):
        global_rules = tailoring_config.get("global_rules")
        if isinstance(global_rules, dict):
            # Keep page-target semantics available to templates without requiring
            # duplicate config under render_options/pdf_render_options.
            max_pages = global_rules.get("max_resume_pages")
            if max_pages is not None:
                options["max_resume_pages"] = max_pages

        raw_tailoring_render_options = tailoring_config.get("render_options")
        if isinstance(raw_tailoring_render_options, dict):
            options.update(raw_tailoring_render_options)

        raw_pdf_render_options = tailoring_config.get("pdf_render_options")
        if isinstance(raw_pdf_render_options, dict):
            options.update(raw_pdf_render_options)

    render = profile.get("render", {})
    if isinstance(render, dict):
        raw_render_options = render.get("options")
        if isinstance(raw_render_options, dict):
            options.update(raw_render_options)

    return options


def build_render_model_from_tailored_json(
    data: dict,
    profile: dict,
    job: dict | None = None,
) -> ResumeRenderModel:
    """Build a render model directly from LLM-tailored JSON + profile context."""

    personal = profile.get("personal", {}) if isinstance(profile, dict) else {}
    model = ResumeRenderModel()
    model.render_options = _extract_render_options(profile)
    include_country = bool(model.render_options.get("include_country_in_location", False))

    model.name = str(personal.get("full_name", "")).strip()
    model.location = _build_location(personal, include_country=include_country)
    model.title = str(data.get("title", "")).strip()
    model.summary = str(data.get("summary", "")).strip()
    profile_education = profile.get("education", []) if isinstance(profile, dict) else []
    if isinstance(profile_education, list):
        rendered_education = []
        for entry in profile_education:
            if not isinstance(entry, dict):
                continue
            rendered = format_education_entry(entry)
            if rendered:
                rendered_education.append(rendered)
    else:
        rendered_education = []

    if rendered_education:
        model.education = "\n".join(rendered_education)
    else:
        model.education = str(data.get("education", "")).strip()

    contact_parts: list[str] = []
    for key in ("email", "phone", "github_url", "linkedin_url"):
        value = str(personal.get(key, "")).strip()
        if value:
            contact_parts.append(value)
    model.contact = " | ".join(contact_parts)

    raw_skills = data.get("skills", {})
    selected_skills, _ = build_relevant_skills(
        raw_skills,
        job=job,
        profile=profile,
        render_options=model.render_options,
    )

    grouped_skills: dict[str, list[str]] = {}
    ordered_categories: list[str] = []
    for category, token in selected_skills:
        category_text = str(category).strip()
        token_text = str(token).strip()
        if not category_text or not token_text:
            continue
        if category_text not in grouped_skills:
            grouped_skills[category_text] = []
            ordered_categories.append(category_text)
        grouped_skills[category_text].append(token_text)

    for category in ordered_categories:
        values = grouped_skills.get(category, [])
        if values:
            model.skills.append(SkillSection(category=category, value=", ".join(values)))

    raw_experience = data.get("experience", [])
    profile_work = profile.get("work", []) if isinstance(profile, dict) and isinstance(profile.get("work"), list) else []
    if isinstance(raw_experience, list):
        for entry in raw_experience:
            normalized = _normalize_entry(entry, is_project=False)
            if normalized is not None:
                normalized = _reconcile_entry_with_profile_work(normalized, profile_work)
                model.experience.append(normalized)

    raw_projects = data.get("projects", [])
    if isinstance(raw_projects, list):
        for entry in raw_projects:
            normalized = _normalize_entry(entry, is_project=True)
            if normalized is not None:
                model.projects.append(normalized)

    return model
