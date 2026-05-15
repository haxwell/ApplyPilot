"""Typed render model for scored resume PDF templates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


def _normalize_entry(entry: Any) -> ResumeEntry | None:
    if not isinstance(entry, dict):
        return None

    title = str(entry.get("header", "")).strip()
    subtitle = str(entry.get("subtitle", "")).strip()
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

    if not title and not subtitle and not bullets:
        return None

    return ResumeEntry(
        title=title,
        subtitle=subtitle,
        bullets=bullets,
        compact_summary=compact_summary,
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


def build_render_model_from_tailored_json(data: dict, profile: dict) -> ResumeRenderModel:
    """Build a render model directly from LLM-tailored JSON + profile context."""

    personal = profile.get("personal", {}) if isinstance(profile, dict) else {}
    model = ResumeRenderModel()
    model.render_options = _extract_render_options(profile)
    include_country = bool(model.render_options.get("include_country_in_location", False))

    model.name = str(personal.get("full_name", "")).strip()
    model.location = _build_location(personal, include_country=include_country)
    model.title = str(data.get("title", "")).strip()
    model.summary = str(data.get("summary", "")).strip()
    model.education = str(data.get("education", "")).strip()

    contact_parts: list[str] = []
    for key in ("email", "phone", "github_url", "linkedin_url"):
        value = str(personal.get(key, "")).strip()
        if value:
            contact_parts.append(value)
    model.contact = " | ".join(contact_parts)

    raw_skills = data.get("skills", {})
    if isinstance(raw_skills, dict):
        for category, value in raw_skills.items():
            category_text = str(category).strip()
            value_text = str(value).strip()
            if category_text and value_text:
                model.skills.append(SkillSection(category=category_text, value=value_text))
    elif isinstance(raw_skills, list):
        for idx, value in enumerate(raw_skills):
            value_text = str(value).strip()
            if value_text:
                model.skills.append(SkillSection(category=f"Skill {idx + 1}", value=value_text))

    raw_experience = data.get("experience", [])
    if isinstance(raw_experience, list):
        for entry in raw_experience:
            normalized = _normalize_entry(entry)
            if normalized is not None:
                model.experience.append(normalized)

    raw_projects = data.get("projects", [])
    if isinstance(raw_projects, list):
        for entry in raw_projects:
            normalized = _normalize_entry(entry)
            if normalized is not None:
                model.projects.append(normalized)

    return model
