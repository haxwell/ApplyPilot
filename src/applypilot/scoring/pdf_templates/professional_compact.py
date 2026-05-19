"""Measurement-aware professional compact resume template."""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace
import math
import re
from typing import Callable, Literal
from urllib.parse import urlparse

from applypilot.scoring.pdf_render_model import ResumeEntry, ResumeRenderModel

_DEFAULT_PAGE_TARGET = 2.5
# Template-local override hook. Keep None to inherit user/global page budget.
_TEMPLATE_PAGE_TARGET_OVERRIDE: float | None = None
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
    "max_resume_pages": {"type": "float", "default": 2.5},
    "compact_max_detailed_experience": {"type": "int", "min": 1},
}

SummaryMode = Literal["full", "compact", "micro"]
SkillsMode = Literal["full", "selected", "minimal"]
ProjectsMode = Literal["full", "compact", "selected", "hidden"]
ExperienceMode = Literal["detailed", "medium", "compact", "earlier_one_line", "grouped", "hidden"]
EducationMode = Literal["full", "compact", "hidden"]
CertificationsMode = Literal["full", "selected", "hidden"]
EarlierExperienceMode = Literal["compact", "earlier_one_line", "grouped"]


@dataclass
class ProfessionalCompactTemplateView:
    """Prepared professional-compact template view."""

    model: ResumeRenderModel
    detailed_experience: list[ResumeEntry]
    compact_experience: list[ResumeEntry]
    projects_to_render: list[ResumeEntry]
    page_target: float = _DEFAULT_PAGE_TARGET
    allowed_physical_pages: int | None = None
    measured_pages_final: int | None = None
    planning_attempts: list[dict[str, int | bool | str | None]] = field(default_factory=list)
    summary_mode: SummaryMode = "full"
    skills_mode: SkillsMode = "full"
    projects_mode: ProjectsMode = "full"
    experience_mode: ExperienceMode = "detailed"
    earlier_experience_mode: EarlierExperienceMode = "compact"
    education_mode: EducationMode = "full"
    certifications_mode: CertificationsMode = "full"
    detailed_bullet_cap: int | None = None
    planning_operations: list[dict[str, int | bool | str | float | None]] = field(default_factory=list)
    selected_skills_max_lines: int = 2
    min_protected_detailed_roles: int | None = None


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
    raw = _TEMPLATE_PAGE_TARGET_OVERRIDE
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


def _build_candidate_view(
    model: ResumeRenderModel,
    detailed_count: int,
    page_target: float,
    *,
    allowed_physical_pages: int | None = None,
    min_protected_detailed_roles: int | None = None,
    measured_pages_final: int | None = None,
    planning_attempts: list[dict[str, int | bool | str | None]] | None = None,
) -> ProfessionalCompactTemplateView:
    detailed = list(model.experience[:detailed_count])
    compact = list(model.experience[detailed_count:])
    return ProfessionalCompactTemplateView(
        model=model,
        detailed_experience=detailed,
        compact_experience=compact,
        projects_to_render=list(model.projects),
        page_target=page_target,
        allowed_physical_pages=allowed_physical_pages,
        min_protected_detailed_roles=min_protected_detailed_roles,
        measured_pages_final=measured_pages_final,
        planning_attempts=list(planning_attempts or []),
    )


def _min_protected_detailed_roles_for_target(allowed_pages: int, total_experience_entries: int) -> int | None:
    if allowed_pages <= 0:
        return None
    if allowed_pages <= 2:
        return min(5, total_experience_entries)
    if allowed_pages == 3:
        return min(7, total_experience_entries)
    return None


def _measure_view(
    view: ProfessionalCompactTemplateView,
    measure_html_page_count: Callable[[str], int],
    allowed_pages: int,
) -> tuple[int, bool]:
    html = build_html(view)
    page_count = measure_html_page_count(html)
    return page_count, page_count <= allowed_pages


def _record_operation(
    view: ProfessionalCompactTemplateView,
    *,
    step: str,
    from_value: object,
    to_value: object,
    measured_pages: int,
    fit: bool,
    kept: bool | None = None,
    reason: str | None = None,
) -> ProfessionalCompactTemplateView:
    operations = list(view.planning_operations)
    operation: dict[str, int | bool | str | float | None] = {
        "step": step,
        "from": from_value,
        "to": to_value,
        "measured_pages": measured_pages,
        "fit": fit,
    }
    if kept is not None:
        operation["kept"] = kept
    if reason:
        operation["reason"] = reason
    operations.append(operation)
    return replace(view, planning_operations=operations, measured_pages_final=measured_pages)


def _apply_mode_transition(view: ProfessionalCompactTemplateView, *, field_name: str, from_value: str, to_value: str) -> ProfessionalCompactTemplateView | None:
    current = getattr(view, field_name)
    if current != from_value:
        return None
    return replace(view, **{field_name: to_value})


def _apply_bullet_cap_transition(view: ProfessionalCompactTemplateView, *, from_value: int, to_value: int) -> ProfessionalCompactTemplateView | None:
    current = view.detailed_bullet_cap
    effective = 5 if current is None else current
    if effective != from_value:
        return None
    return replace(view, detailed_bullet_cap=to_value)


def _maybe_reduce_detailed_count(view: ProfessionalCompactTemplateView) -> ProfessionalCompactTemplateView | None:
    current = len(view.detailed_experience)
    if current <= 1:
        return None
    new_detailed_count = current - 1
    all_entries = list(view.detailed_experience) + list(view.compact_experience)
    return replace(
        view,
        detailed_experience=list(all_entries[:new_detailed_count]),
        compact_experience=list(all_entries[new_detailed_count:]),
    )


def prepare(model: ResumeRenderModel) -> ProfessionalCompactTemplateView:
    """Prepare template view without measurement-aware planning."""

    page_target = _resolve_page_target(model)
    hard_cap = _coerce_positive_int(model.render_options.get("compact_max_detailed_experience"))
    if hard_cap is None:
        detailed_count = len(model.experience)
    else:
        detailed_count = min(hard_cap, len(model.experience))
    return _build_candidate_view(
        model,
        detailed_count=detailed_count,
        page_target=page_target,
        allowed_physical_pages=_allowed_physical_pages(page_target),
    )


def prepare_with_measurement(
    model: ResumeRenderModel,
    measure_html_page_count: Callable[[str], int],
) -> ProfessionalCompactTemplateView:
    """Prepare template view using page-aware compaction planning."""

    page_target = _resolve_page_target(model)
    hard_cap = _coerce_positive_int(model.render_options.get("compact_max_detailed_experience"))
    allowed_pages = _allowed_physical_pages(page_target)
    total_entries = len(model.experience)
    min_protected_detailed_roles = _min_protected_detailed_roles_for_target(allowed_pages, total_entries)
    detailed_count = total_entries
    if hard_cap is not None:
        detailed_count = min(hard_cap, total_entries)
    if total_entries > 0:
        detailed_count = max(1, detailed_count)

    view = _build_candidate_view(
        model,
        detailed_count=detailed_count,
        page_target=page_target,
        allowed_physical_pages=allowed_pages,
        min_protected_detailed_roles=min_protected_detailed_roles,
        planning_attempts=(
            [
                {
                    "detailed_experience_count": detailed_count,
                    "measured_page_count": None,
                    "fit": None,
                    "reason": "hard_cap_override",
                }
            ]
            if hard_cap is not None
            else None
        ),
    )

    page_count, fits = _measure_view(view, measure_html_page_count, allowed_pages)
    view = replace(view, measured_pages_final=page_count)

    def _attempt_post_fit_expansion() -> None:
        nonlocal view
        if view.skills_mode != "selected" or view.selected_skills_max_lines != 2:
            return

        expanded = replace(view, selected_skills_max_lines=3)
        measured, fit = _measure_view(expanded, measure_html_page_count, allowed_pages)
        if fit:
            view = _record_operation(
                expanded,
                step="selected_skills_max_lines",
                from_value=2,
                to_value=3,
                measured_pages=measured,
                fit=True,
                kept=True,
            )
            return

        view = _record_operation(
            view,
            step="selected_skills_max_lines",
            from_value=2,
            to_value=3,
            measured_pages=measured,
            fit=False,
            kept=False,
        )

        floor = view.min_protected_detailed_roles
        if floor is None or len(view.detailed_experience) <= floor:
            return

        reduced = _maybe_reduce_detailed_count(view)
        if reduced is None:
            return
        measured_reduced, fit_reduced = _measure_view(reduced, measure_html_page_count, allowed_pages)
        if not fit_reduced:
            view = _record_operation(
                view,
                step="detailed_experience_count",
                from_value=len(view.detailed_experience),
                to_value=len(reduced.detailed_experience),
                measured_pages=measured_reduced,
                fit=False,
                kept=False,
                reason="post_fit_reallocation_for_selected_skills_expansion",
            )
            return

        expanded_reduced = replace(reduced, selected_skills_max_lines=3)
        measured_expanded, fit_expanded = _measure_view(expanded_reduced, measure_html_page_count, allowed_pages)
        if fit_expanded:
            reduced_with_op = _record_operation(
                reduced,
                step="detailed_experience_count",
                from_value=len(view.detailed_experience),
                to_value=len(reduced.detailed_experience),
                measured_pages=measured_reduced,
                fit=True,
                kept=True,
                reason="post_fit_reallocation_for_selected_skills_expansion",
            )
            view = _record_operation(
                replace(
                    expanded_reduced,
                    planning_operations=reduced_with_op.planning_operations,
                ),
                step="selected_skills_max_lines",
                from_value=2,
                to_value=3,
                measured_pages=measured_expanded,
                fit=True,
                kept=True,
                reason="after_post_fit_reallocation",
            )
            return

        view = _record_operation(
            view,
            step="detailed_experience_count",
            from_value=len(view.detailed_experience),
            to_value=len(reduced.detailed_experience),
            measured_pages=measured_reduced,
            fit=True,
            kept=False,
            reason="post_fit_reallocation_for_selected_skills_expansion",
        )
        view = _record_operation(
            view,
            step="selected_skills_max_lines",
            from_value=2,
            to_value=3,
            measured_pages=measured_expanded,
            fit=False,
            kept=False,
            reason="after_post_fit_reallocation",
        )

    if fits:
        _attempt_post_fit_expansion()
        return view

    def _apply_step(
        step: str,
        apply_fn: Callable[[ProfessionalCompactTemplateView], ProfessionalCompactTemplateView | None],
        from_value: object,
        to_value: object,
    ) -> bool:
        nonlocal view
        updated = apply_fn(view)
        if updated is None:
            return False
        measured, fit = _measure_view(updated, measure_html_page_count, allowed_pages)
        updated = _record_operation(
            updated,
            step=step,
            from_value=from_value,
            to_value=to_value,
            measured_pages=measured,
            fit=fit,
        )
        view = updated
        return fit

    initial_ladder = [
        ("projects_mode", lambda v: _apply_mode_transition(v, field_name="projects_mode", from_value="full", to_value="compact"), "full", "compact"),
        ("projects_mode", lambda v: _apply_mode_transition(v, field_name="projects_mode", from_value="compact", to_value="selected"), "compact", "selected"),
        ("projects_mode", lambda v: _apply_mode_transition(v, field_name="projects_mode", from_value="selected", to_value="hidden"), "selected", "hidden"),
        ("certifications_mode", lambda v: _apply_mode_transition(v, field_name="certifications_mode", from_value="full", to_value="selected"), "full", "selected"),
        ("education_mode", lambda v: _apply_mode_transition(v, field_name="education_mode", from_value="full", to_value="compact"), "full", "compact"),
        (
            "earlier_experience_mode",
            lambda v: _apply_mode_transition(v, field_name="earlier_experience_mode", from_value="compact", to_value="earlier_one_line"),
            "compact",
            "earlier_one_line",
        ),
        (
            "earlier_experience_mode",
            lambda v: _apply_mode_transition(v, field_name="earlier_experience_mode", from_value="earlier_one_line", to_value="grouped"),
            "earlier_one_line",
            "grouped",
        ),
        ("detailed_bullet_cap", lambda v: _apply_bullet_cap_transition(v, from_value=5, to_value=4), 5, 4),
        ("detailed_bullet_cap", lambda v: _apply_bullet_cap_transition(v, from_value=4, to_value=3), 4, 3),
        ("summary_mode", lambda v: _apply_mode_transition(v, field_name="summary_mode", from_value="full", to_value="compact"), "full", "compact"),
        ("skills_mode", lambda v: _apply_mode_transition(v, field_name="skills_mode", from_value="full", to_value="selected"), "full", "selected"),
    ]
    for step, apply_fn, from_value, to_value in initial_ladder:
        if _apply_step(step, apply_fn, from_value, to_value):
            _attempt_post_fit_expansion()
            return view

    def _reduce_detailed_until_floor(floor: int) -> bool:
        nonlocal view
        while len(view.detailed_experience) > floor:
            next_view = _maybe_reduce_detailed_count(view)
            if next_view is None:
                return False
            measured, fit = _measure_view(next_view, measure_html_page_count, allowed_pages)
            attempts = list(view.planning_attempts)
            attempts.append(
                {
                    "detailed_experience_count": len(next_view.detailed_experience),
                    "measured_page_count": measured,
                    "fit": fit,
                }
            )
            next_view = replace(next_view, planning_attempts=attempts)
            next_view = _record_operation(
                next_view,
                step="detailed_experience_count",
                from_value=len(view.detailed_experience),
                to_value=len(next_view.detailed_experience),
                measured_pages=measured,
                fit=fit,
            )
            view = next_view
            if fit:
                return True
        return False

    floor_for_two_pages = 6 if allowed_pages <= 2 else 1
    if _reduce_detailed_until_floor(floor_for_two_pages):
        _attempt_post_fit_expansion()
        return view

    if _apply_step(
        "skills_mode",
        lambda v: _apply_mode_transition(v, field_name="skills_mode", from_value="selected", to_value="minimal"),
        "selected",
        "minimal",
    ):
        _attempt_post_fit_expansion()
        return view

    if _apply_step(
        "certifications_mode",
        lambda v: _apply_mode_transition(v, field_name="certifications_mode", from_value="selected", to_value="hidden"),
        "selected",
        "hidden",
    ):
        _attempt_post_fit_expansion()
        return view

    if _reduce_detailed_until_floor(1):
        _attempt_post_fit_expansion()
        return view
    _attempt_post_fit_expansion()
    return view


def _build_compact_entry_summary(entry: ResumeEntry) -> tuple[str, bool]:
    compact_summary = entry.compact_summary.strip()
    if compact_summary:
        return compact_summary, False

    fallback_parts = [bullet.strip() for bullet in entry.bullets[:2] if bullet.strip()]
    if fallback_parts:
        return " ".join(fallback_parts), False

    date_text = _format_entry_date_range(entry, default_present=True)
    if date_text:
        return date_text, True

    subtitle = entry.subtitle.strip()
    if subtitle:
        return _format_date_text(subtitle), True

    return "", False


def _compact_entry_signal_summary(entry: ResumeEntry) -> str:
    compact_summary = entry.compact_summary.strip()
    if compact_summary:
        return compact_summary
    for bullet in entry.bullets:
        cleaned = bullet.strip()
        if cleaned:
            return cleaned
    return ""


def _compact_entry_company_label(entry: ResumeEntry) -> str:
    company = entry.company.strip()
    if company:
        return company
    company_legacy, _detail_legacy = _split_subtitle(entry.subtitle)
    if company_legacy:
        return company_legacy
    title = entry.title.strip()
    if " - " in title:
        return title.split(" - ", 1)[0].strip()
    return title


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


def _is_present_value(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"present", "current", "now"}


def _format_entry_date_range(entry: ResumeEntry, *, default_present: bool) -> str:
    start = str(entry.start_date or "").strip()
    end = str(entry.end_date or "").strip()
    if not start and not end and entry.dates.strip():
        start_legacy, end_legacy = _parse_legacy_date_range(entry.dates)
        start = start or start_legacy
        end = end or end_legacy
    if not start and not end:
        return ""

    if _is_present_value(end):
        end_display = "Present"
    elif end:
        end_display = end
    else:
        end_display = "Present" if default_present and start else ""

    if start and end_display:
        return _format_date_text(f"{start} - {end_display}")
    if start:
        return _format_date_text(start)
    return _format_date_text(end_display)


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
    return match.group("start").strip(), match.group("end").strip()


def _experience_heading(entry: ResumeEntry) -> str:
    def _strip_contract_suffix(text: str) -> str:
        value = text.strip()
        if not value:
            return ""
        # Normalize display by removing trailing contract markers from role/title.
        value = re.sub(r"\s*[\(\[]?\bcontract(or)?\b[\)\]]?\s*$", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"\s*[-|,]\s*$", "", value).strip()
        return value

    company = entry.company.strip()
    role = _strip_contract_suffix(entry.role.strip() or entry.title.strip())
    if company and role:
        return f"{company} - {role}"
    company_legacy, _detail_legacy = _split_subtitle(entry.subtitle)
    if company_legacy:
        title = role or _strip_contract_suffix(entry.title.strip())
        return f"{company_legacy} - {title}" if title else company_legacy
    return role or _strip_contract_suffix(entry.title.strip())


def _experience_detail_line(entry: ResumeEntry) -> str:
    parts: list[str] = []
    date_text = _format_entry_date_range(entry, default_present=True)
    location = entry.location.strip()
    if date_text:
        parts.append(date_text)
    if location:
        parts.append(location)
    if entry.is_contract:
        parts.append("Contract")
    if parts:
        return " | ".join(parts)
    _company_legacy, detail_legacy = _split_subtitle(entry.subtitle)
    return detail_legacy


def _project_context_and_dates(entry: ResumeEntry) -> tuple[str, str]:
    context_parts: list[str] = []
    description = str(entry.metadata.get("description", "")).strip()
    if description:
        context_parts.append(description)
    if entry.technologies:
        context_parts.append(", ".join(entry.technologies))
    date_text = _format_entry_date_range(entry, default_present=True)
    if date_text:
        return " | ".join(context_parts), date_text
    context_legacy, date_legacy = _extract_project_context_and_dates(entry.subtitle)
    if not context_parts:
        return context_legacy, date_legacy
    return " | ".join(context_parts), date_legacy


def _build_skill_lines(skills: list) -> list[str]:
    def _split_preserving_parentheses(text: str) -> list[str]:
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

    seen: set[str] = set()
    flattened: list[str] = []
    for skill in skills:
        for raw in _split_preserving_parentheses(str(skill.value)):
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


def _render_summary(resume: ResumeRenderModel, mode: SummaryMode) -> str:
    text = resume.summary.strip()
    if not text or mode == "hidden":  # hidden not exposed, but keep helper defensive.
        return ""
    if mode == "compact":
        parts = re.split(r"(?<=[.!?])\s+", text)
        text = " ".join(parts[:2]).strip()
    elif mode == "micro":
        parts = re.split(r"(?<=[.!?])\s+", text)
        text = parts[0].strip()
    if not text:
        return ""
    return f'<section class="section"><h2 class="section-title">Summary</h2><p class="summary">{text}</p></section>'


def _render_skills(resume: ResumeRenderModel, mode: SkillsMode, *, selected_skills_max_lines: int = 2) -> str:
    if not resume.skills:
        return ""
    lines = _build_skill_lines(resume.skills)
    if mode == "selected":
        lines = lines[: max(1, selected_skills_max_lines)]
    elif mode == "minimal":
        lines = lines[:1]
    if not lines:
        return ""
    rows = "".join(f'<div class="skill-line">{line}</div>' for line in lines)
    return f'<section class="section"><h2 class="section-title">Technical Skills</h2>{rows}</section>'


def _render_experience_entry(entry: ResumeEntry, *, bullet_limit: int | None = None) -> str:
    heading = _experience_heading(entry)
    detail_line = _experience_detail_line(entry)
    subtitle = f'<div class="entry-subtitle">{detail_line}</div>' if detail_line else ""
    bullets_src = entry.bullets if bullet_limit is None else entry.bullets[:bullet_limit]
    bullets = "".join(f"<li>{bullet}</li>" for bullet in bullets_src)
    bullet_list = f'<ul class="entry-bullets">{bullets}</ul>' if bullets else ""
    return f'<article class="entry"><h3 class="entry-title">{heading}</h3>{subtitle}{bullet_list}</article>'


def _render_compact_entry(entry: ResumeEntry, *, one_line: bool = False) -> str:
    summary, used_subtitle_as_summary = _build_compact_entry_summary(entry)
    heading = _experience_heading(entry)
    detail_line = _experience_detail_line(entry)
    detail_suffix = f" | {detail_line}" if detail_line and not used_subtitle_as_summary else ""
    if one_line:
        one_line_text = f"{heading}{detail_suffix}"
        return f'<article class="compact-entry"><div class="compact-meta">{one_line_text}</div></article>'
    summary_html = f'<p class="compact-summary">{summary}</p>' if summary else ""
    return (
        '<article class="compact-entry">'
        f'<div class="compact-meta"><strong class="compact-company">{heading}</strong>'
        f'<span class="compact-date">{detail_suffix}</span></div>'
        f"{summary_html}"
        "</article>"
    )


def _render_experience(view: ProfessionalCompactTemplateView, mode: ExperienceMode) -> tuple[str, str]:
    detailed_entries = list(view.detailed_experience)
    compact_entries = list(view.compact_experience)
    if mode == "hidden":
        return "", ""
    if mode == "earlier_one_line":
        compact_entries = detailed_entries + compact_entries
        detailed_entries = []
    elif mode == "grouped":
        lines: list[str] = []
        for entry in detailed_entries + compact_entries:
            heading = _experience_heading(entry)
            detail_line = _experience_detail_line(entry)
            lines.append(f"{heading} ({detail_line})" if detail_line else heading)
        if not lines:
            return "", ""
        grouped = " • ".join(line for line in lines if line)
        html = (
            '<section class="section"><h2 class="section-title">Experience</h2>'
            f'<p class="compact-summary">{grouped}</p></section>'
        )
        return html, ""

    exp_html = ""
    if detailed_entries:
        items = ""
        for idx, entry in enumerate(detailed_entries):
            entry_bullet_cap = None
            if idx > 0 and isinstance(view.detailed_bullet_cap, int) and view.detailed_bullet_cap > 0:
                entry_bullet_cap = view.detailed_bullet_cap
            if mode == "detailed":
                items += _render_experience_entry(entry, bullet_limit=entry_bullet_cap)
            elif mode == "medium":
                medium_limit = 2 if entry_bullet_cap is None else min(2, entry_bullet_cap)
                items += _render_experience_entry(entry, bullet_limit=medium_limit)
            elif mode == "compact":
                items += _render_compact_entry(entry)
        exp_html = f'<section class="section"><h2 class="section-title">Experience</h2>{items}</section>'

    selected_exp_html = ""
    if compact_entries:
        if view.earlier_experience_mode == "grouped":
            grouped_lines: list[str] = []
            for idx in range(0, len(compact_entries), 2):
                group = compact_entries[idx:idx + 2]
                companies = " / ".join(
                    label for label in (_compact_entry_company_label(entry) for entry in group) if label
                )
                summaries = [_compact_entry_signal_summary(entry) for entry in group]
                summaries = [summary.rstrip(" .;") for summary in summaries if summary and summary.rstrip(" .;")]
                if companies and summaries:
                    grouped_lines.append(f"{companies} - {'; '.join(summaries)}.")
                elif companies:
                    grouped_lines.append(f"{companies}.")
                elif summaries:
                    grouped_lines.append(f"{'; '.join(summaries)}.")
            items = "".join(f'<p class="compact-summary">{line}</p>' for line in grouped_lines)
        else:
            one_line = view.earlier_experience_mode == "earlier_one_line"
            items = "".join(_render_compact_entry(entry, one_line=one_line) for entry in compact_entries)
        selected_exp_html = (
            '<section class="section"><h2 class="section-title">Earlier Experience (Selected)</h2>'
            f"{items}</section>"
        )
    return exp_html, selected_exp_html


def _render_projects(view: ProfessionalCompactTemplateView, mode: ProjectsMode) -> str:
    if mode == "hidden":
        return ""
    entries = list(view.projects_to_render)
    if mode == "selected":
        entries = entries[:2]
    if not entries:
        return ""
    items = ""
    for entry in entries:
        context_line, date_line = _project_context_and_dates(entry)
        title_row = (
            '<div class="project-title-row">'
            f'<h3 class="entry-title">{entry.title}</h3>'
            f'<span class="project-dates">{date_line}</span>'
            "</div>"
        )
        if mode == "compact":
            summary = entry.compact_summary.strip() or context_line
            summary_html = f'<p class="project-summary">{summary}</p>' if summary else ""
            items += f'<article class="entry">{title_row}{summary_html}</article>'
            continue
        bullets = "".join(f"<li>{bullet}</li>" for bullet in entry.bullets)
        has_bullets = bool(bullets)
        summary_html = f'<p class="project-summary">{context_line}</p>' if context_line and not has_bullets else ""
        bullet_list = f'<ul class="entry-bullets">{bullets}</ul>' if has_bullets else ""
        items += f'<article class="entry">{title_row}{summary_html}{bullet_list}</article>'
    return f'<section class="section"><h2 class="section-title">Projects</h2>{items}</section>'


def _render_education(resume: ResumeRenderModel, mode: EducationMode) -> str:
    text = resume.education.strip()
    if not text or mode == "hidden":
        return ""
    if mode == "compact":
        text = text.replace(" | ", " • ")
    return f'<section class="section"><h2 class="section-title">Education</h2><p class="edu">{text}</p></section>'


def _selected_skill_tokens(
    resume: ResumeRenderModel,
    skills_mode: SkillsMode,
    *,
    selected_skills_max_lines: int,
) -> set[str]:
    lines = _build_skill_lines(resume.skills)
    if skills_mode == "selected":
        lines = lines[: max(1, selected_skills_max_lines)]
    elif skills_mode == "minimal":
        lines = lines[:1]
    text = " ".join(lines).lower()
    return set(re.findall(r"[a-z0-9\+\#\.\-/]{2,}", text))


def _pick_best_certification(lines: list[str], skill_tokens: set[str]) -> str:
    def _score(line: str) -> tuple[int, int]:
        low = line.lower()
        java_score = 1 if "java" in low else 0
        skill_score = 0
        for token in skill_tokens:
            if token and token in low:
                skill_score += 1
        return java_score, skill_score

    best = lines[0]
    best_score = _score(best)
    for line in lines[1:]:
        score = _score(line)
        if score > best_score:
            best = line
            best_score = score
    return best


def _render_certifications(view: ProfessionalCompactTemplateView, mode: CertificationsMode) -> str:
    resume = view.model
    lines = [line.strip() for line in str(resume.certifications).splitlines() if line.strip()]
    if not lines or mode == "hidden":
        return ""
    if mode == "selected":
        if view.allowed_physical_pages is not None and view.allowed_physical_pages <= 2:
            skill_tokens = _selected_skill_tokens(
                resume,
                view.skills_mode,
                selected_skills_max_lines=view.selected_skills_max_lines,
            )
            lines = [_pick_best_certification(lines, skill_tokens)]
        else:
            lines = lines[:3]
    certifications_html = "<br>".join(lines)
    return (
        f'<section class="section"><h2 class="section-title">Certifications</h2>'
        f'<p class="edu">{certifications_html}</p></section>'
    )


def build_html(view: ProfessionalCompactTemplateView) -> str:
    """Build professional compact resume HTML from a prepared view."""
    resume = view.model

    summary_html = _render_summary(resume, view.summary_mode)
    skills_html = _render_skills(
        resume,
        view.skills_mode,
        selected_skills_max_lines=view.selected_skills_max_lines,
    )
    exp_html, selected_exp_html = _render_experience(view, view.experience_mode)
    proj_html = _render_projects(view, view.projects_mode)
    edu_html = _render_education(resume, view.education_mode)
    cert_html = _render_certifications(view, view.certifications_mode)

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
    font-family: Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.17;
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
    line-height: 1.17;
}}
.contact {{
    margin-top: 4px;
    font-size: 10.4pt;
    color: #303030;
    line-height: 1.17;
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
    line-height: 1.17;
}}
.summary {{
    font-size: 11pt;
    line-height: 1.17;
    color: #222222;
}}
.skill-line {{
    font-size: 10.8pt;
    line-height: 1.17;
    color: #1c1c1c;
    margin-bottom: 2px;
}}
.entry {{
    margin-bottom: 14px;
}}
.entry-title {{
    font-weight: 700;
    font-size: 11.4pt;
    line-height: 1.17;
    break-after: avoid;
}}
.entry-subtitle {{
    margin-top: 2px;
    font-size: 10.2pt;
    font-style: italic;
    color: #444444;
    break-after: avoid;
    line-height: 1.17;
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
    line-height: 1.17;
}}
.project-summary {{
    margin-top: 2px;
    font-size: 10.8pt;
    line-height: 1.17;
    color: #222222;
}}
.entry-bullets {{
    margin: 6px 0 0 24px;
    padding: 0;
}}
.entry-bullets li {{
    margin-bottom: 4px;
    font-size: 10.9pt;
    line-height: 1.17;
}}
.compact-entry {{
    margin-bottom: 10px;
    break-inside: avoid;
}}
.compact-meta {{
    font-size: 10.7pt;
    line-height: 1.17;
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
    line-height: 1.17;
    color: #222222;
}}
.edu {{
    font-size: 10.8pt;
    line-height: 1.17;
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
{cert_html}
</div>
</body>
</html>"""
