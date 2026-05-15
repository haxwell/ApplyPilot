"""Resume tailoring: LLM-powered ATS-optimized resume generation per job.

THIS IS THE HEAVIEST REFACTOR. Every piece of personal data -- name, email, phone,
skills, companies, projects, school -- is loaded at runtime from the user's profile.
Zero hardcoded personal information.

The LLM returns structured JSON, code assembles the final text. Header (name, contact)
is always code-injected, never LLM-generated. Each retry starts a fresh conversation
to avoid apologetic spirals.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from applypilot.config import TAILORED_DIR, load_profile, load_resume_text
from applypilot.database import get_connection, get_jobs_by_stage
from applypilot.llm import get_client
from applypilot.resume_json import (
    format_education_entry,
    get_profile_company_names,
    get_profile_school_names,
    get_profile_skill_keywords,
    get_profile_skill_sections,
    get_profile_verified_metrics,
)
from applypilot.scoring.artifact_naming import build_artifact_prefix
from applypilot.scoring.validator import (
    BANNED_WORDS,
    FABRICATION_WATCHLIST,
    sanitize_text,
    validate_json_fields,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5  # max cross-run retries before giving up
_DEFAULT_MAX_RESUME_PAGES = 2.5
_DEFAULT_LINES_PER_PAGE = 52
_JOB_KEYWORD_STOPWORDS = {
    "with", "from", "that", "this", "they", "their", "there", "about", "into", "your",
    "will", "have", "has", "had", "our", "you", "for", "and", "the", "are", "but",
    "not", "all", "any", "can", "was", "were", "job", "role", "team", "work", "using",
}


# ── Prompt Builders (profile-driven) ──────────────────────────────────────

def _build_education_block(education_list: list[dict]) -> str:
    """Build the education block from structured profile education data."""

    if not education_list:
        return "N/A"
    lines: list[str] = []
    for edu in education_list:
        if not isinstance(edu, dict):
            continue
        rendered = format_education_entry(edu)
        if rendered:
            lines.append(rendered)
    return "\n".join(lines)


def _build_work_history_block(profile: dict) -> str:
    """Build a compact work-history inventory for the prompt."""

    work_entries = profile.get("work", [])
    if not isinstance(work_entries, list) or not work_entries:
        return "N/A"

    lines: list[str] = []
    for role in work_entries:
        if not isinstance(role, dict):
            continue
        company = str(role.get("company", "")).strip()
        position = str(role.get("position", "")).strip() or "Software Engineer"
        start = str(role.get("start_date", "")).strip()
        end = str(role.get("end_date", "")).strip() or "Present"
        if company:
            lines.append(f"- {company} | {position} | {start} - {end}".strip())

    return "\n".join(lines) if lines else "N/A"


def _build_tailor_prompt(
    profile: dict,
    resume_text: str | None = None,
    content_preparation_context: dict | None = None,
) -> str:
    """Build the resume tailoring system prompt from the user's profile.

    All skills boundaries, preserved entities, and formatting rules are
    derived from the profile -- nothing is hardcoded.
    """
    # Format skills boundary for the prompt
    skills_lines = []
    for label, items in get_profile_skill_sections(profile):
        skills_lines.append(f"{label}: {', '.join(items)}")
    skills_block = "\n".join(skills_lines)

    # Preserved entities
    companies = get_profile_company_names(profile)
    schools = get_profile_school_names(profile)
    school = schools[0] if schools else ""
    real_metrics = get_profile_verified_metrics(profile)

    companies_str = ", ".join(companies) if companies else "N/A"
    metrics_str = ", ".join(real_metrics) if real_metrics else "N/A"

    # Include ALL banned words from the validator so the LLM knows exactly
    # what will be rejected — the validator checks for these automatically.
    banned_str = ", ".join(BANNED_WORDS)

    education = profile.get("experience", {})
    education_level = education.get("education_level", "")
    education_block = _build_education_block(profile.get("education", []))
    work_history_block = _build_work_history_block(profile)
    if education_block == "N/A" and education_level:
        education_block = f"{school} | {education_level}" if school else education_level
    del resume_text

    context = content_preparation_context if isinstance(content_preparation_context, dict) else {}
    selected_pdf_template = str(context.get("pdf_template", "")).strip() or "professional_compact"
    raw_template_prefs = context.get("pdf_template_input_preferences", {})
    template_prefs = raw_template_prefs if isinstance(raw_template_prefs, dict) else {}

    requested_entry_fields = template_prefs.get("requested_entry_fields", [])
    if not isinstance(requested_entry_fields, list):
        requested_entry_fields = []
    requested_entry_fields_normalized = {
        str(field).strip().lower() for field in requested_entry_fields if str(field).strip()
    }
    wants_compact_summary = bool(template_prefs.get("prefers_compact_summary")) or (
        "compact_summary" in requested_entry_fields_normalized
    )

    compact_summary_section = ""
    experience_compact_summary_line = ""
    project_compact_summary_line = ""
    if wants_compact_summary:
        compact_summary_section = """
    ## COMPACT SUMMARY (OPTIONAL WHEN USEFUL)

    If useful for downstream template rendering, you may include compact_summary on experience entries and relevant project entries.

    compact_summary should:
    - be one concise sentence
    - preserve real evidence from the source
    - avoid new claims
    - include the strongest role-specific signal
    - preserve exact metrics when used
    - be suitable for a compact/selected experience layout

    compact_summary is optional. Do not replace bullets with compact_summary.
    Do not omit bullets because compact_summary exists.
"""
        experience_compact_summary_line = '\n          "compact_summary": "Optional concise sentence for compact layouts."'
        project_compact_summary_line = '\n          "compact_summary": "Optional concise sentence for compact layouts."'

    content_prep_context_text = json.dumps(
        {
            "pdf_template": selected_pdf_template,
            "pdf_template_input_preferences": template_prefs,
        },
        indent=2,
        sort_keys=True,
    )

    system_prompt = f"""
    You are a senior technical resume editor helping a strong senior engineer get an interview.

    Take the base resume and target job description. Return a tailored resume as a JSON object.

    Your goal is NOT to aggressively rewrite the resume.
    Your goal is to produce a credible, recruiter-ready, human-sounding resume by selecting, ordering, and lightly tailoring the strongest real evidence from the source resume.

    The resume should feel like a polished senior-engineer resume tailored to this job, not like generic AI-generated resume text.
    
    ## YOUR ROLE IN THE PIPELINE

    You are the content tailoring step, not the final layout or page-fitting step.

    Your job is to transform the source resume into complete, truthful, job-relevant structured resume content.

    Do not shorten, omit, or over-compress content merely to fit a page count. A later PDF template step is responsible for layout, page fitting, detailed-vs-compact rendering, and deciding what can fit in the final PDF.

    For this step, prefer complete and relevant evidence over premature brevity.

    Provide enough truthful material for downstream templates to decide what to render in detail or compact form.

    ## RECRUITER SCAN, 6 SECONDS

    A recruiter should immediately see:

    1. Title matches the target role closely enough to pass the scan.
    2. Summary proves the candidate has done this kind of work.
    3. Skills show the must-haves for this job near the top.
    4. First 3 bullets of the most relevant recent role show concrete work, technologies, and outcomes.
    5. The candidate's seniority and depth are immediately visible.

    ## SOURCE OF TRUTH

    The base resume is the factual source of truth.

    Use only real companies, roles, dates, skills, projects, degrees, certifications, tools, and accomplishments from the source resume and the allowed skills block.

    Do not invent responsibilities, metrics, domains, tools, degrees, certifications, titles, or outcomes.

    Do not turn a weaker source claim into a stronger claim.

    Do not change what a metric measures.

    Example:
    - If the source says "reduced test creation time from days to hours," do not rewrite it as "reduced test execution time."
    - If the source says "hundreds of repositories" or "thousands of repositories," preserve the original scale exactly.
    - If the source says "several hours," do not rewrite it as "minutes" or "dramatically faster."

    ## SKILLS BOUNDARY, REAL SKILLS ONLY

    {skills_block}

    You MAY add 2-3 closely related tools only when they are strongly implied by the source resume and common in the same ecosystem.
    Examples:
    - Kubernetes may be included if Docker and Kubernetes appear in the source.
    - JPA/Hibernate may be included if Hibernate or Spring backend database work appears in the source.
    - Redis may be included only if Redis appears in the source.

    Do not add unrelated languages, frameworks, cloud providers, databases, or AI tools.

    ## TITLE

    Match the target role while preserving truthful seniority.

    Good titles:
    - Senior Backend Engineer
    - Senior Software Engineer
    - Senior Platform Engineer
    - Lead Backend Engineer

    Avoid overfitting to internal company names, product names, or team names from the job description.

    Do not make the candidate a Staff Engineer, Principal Engineer, Architect, Manager, or ML Engineer unless the source resume clearly supports that positioning for this job.

    ## SUMMARY

    Write 4-6 sentences.

    The summary should be specific, grounded, and senior.

    It should lead with the strongest overlap between the candidate and the target job:
    - backend systems
    - Java/Spring Boot
    - APIs and microservices
    - event-driven systems/Kafka
    - AWS/cloud infrastructure
    - CI/CD and delivery automation
    - reliability, performance, maintainability
    - simplifying complex systems and fragile workflows
    - mentoring and engineering standards, when relevant

    The summary should sound like this kind of voice:

    Good:
    "Backend engineer focused on improving system performance and simplifying complex architectures so they scale reliably in real-world environments. Experienced building APIs, event-driven services, and delivery automation where reducing bottlenecks and operational complexity improves reliability and speed."

    Bad:
    "Experienced software engineer with a proven track record of leveraging cutting-edge technologies to deliver robust and scalable solutions."

    Avoid generic claims unless they are tied to specific evidence.

    ## SKILLS

    Reorder skills so the job's must-haves appear first.

    Keep skills concise and scannable.

    Prefer grouped, resume-friendly categories such as:
    - Languages
    - Backend
    - Cloud / DevOps
    - Data / Messaging
    - Testing
    - Frontend
    - AI / Data Tooling

    Only include categories that help this job.

    Do not bury the most important must-have skills.

    ## EXPERIENCE COVERAGE

    Keep EVERY real employer from the source work history in the JSON experience list.

    Do not remove roles. Do not merge two different employers into one entry.

    Source profile work history (newest first):
    {work_history_block}

    Hard requirements:
    - The experience array MUST have exactly one entry per profile company.
    - len(experience) MUST equal the number of profile companies in source work history.
    - Every profile company string MUST appear in exactly one experience entry
      (header, subtitle, or company field text).
    - No duplicate company entries in experience.
    - If any profile company is missing, output is invalid.
    - Provide enough truthful source material for the PDF template to decide what to render in detail or compact form.
    - For recent or highly relevant roles, provide 3-4 concise, concrete bullets grounded in source resume evidence.
    - For older roles, provide at least 2 concise, concrete bullets when source evidence exists. Use 3 when the role has strong relevant evidence.
    - Do not reduce any role to a single bullet unless the source resume truly contains only one useful evidence point for that role.
    - Do not reduce older roles to a single bullet merely to fit page length; page fitting is handled by the PDF template.

    ## BULLET STRATEGY

    Tailor by selection, ordering, emphasis, and light editing.

    Do not pre-compact the resume to fit a page budget. The PDF template handles page fitting, detailed-vs-compact rendering, and Selected/Earlier Experience layout.

    Do NOT rewrite every bullet just to make it different.

    Preserve strong source bullets when they are already:
    - specific
    - truthful
    - quantified
    - relevant
    - written in plain engineering language

    Rewrite only when:
    - the source bullet is too long
    - the source bullet is unclear
    - the target job needs a different emphasis
    - the bullet can be made more concise without changing its meaning
    - the most relevant technology or outcome is buried

    Every bullet should answer at least two of these:
    - What did the candidate build?
    - What system or workflow did it affect?
    - What technologies were involved?
    - What improved?
    - What scale, metric, or business/engineering outcome resulted?

    Prefer:
    "Built a configurable end-to-end integration test platform using Cucumber, GitHub Actions, and CloudFoundry, reducing test creation time from days to hours."

    Avoid:
    "Enhanced deployment efficiency through robust automation and comprehensive testing."

    {compact_summary_section}

    ## BULLET STYLE

    Use short, direct engineering language.

    Strong verbs are good, but clarity matters more than verb variety.

    Good verbs:
    Built, Designed, Implemented, Automated, Reduced, Improved, Created, Integrated, Migrated, Refactored, Documented, Mentored, Led, Supported

    Avoid forcing fancy verbs.

    Avoid vague or inflated language:
    - robust
    - seamless
    - advanced
    - cutting-edge
    - transformative
    - drastically
    - significantly
    - maximized
    - optimized, unless there is a concrete optimization
    - leveraged, unless there is no simpler verb
    - cultivated
    - spearheaded, unless clearly true
    - world-class
    - best-in-class

    Do not use "Borrowed engineering practices."

    Do not use em dashes. Use commas, periods, or hyphens.

    ## METRICS AND EVIDENCE

    Preserve all real metrics exactly.

    Known metrics and scale markers from the source must not be changed:
    {metrics_str}

    If a metric exists, prefer the metric over vague language.

    Good:
    "reduced a multi-day process to several hours"

    Bad:
    "improved operational efficiency significantly"

    Good:
    "supporting thousands of cryptocurrency buy/sell operations at a time"

    Bad:
    "supporting many high-volume transactions"

    Good:
    "processing millions of records"

    Bad:
    "processing large amounts of data"

    ## PROJECTS

    Use projects only when they improve the match.

    Reorder projects by relevance.

    Drop irrelevant projects when they do not improve targeting for this job.

    For this candidate:
    - TribeApp is relevant for backend, product, mobile, Spring Boot, MySQL, rules/attributes, discovery, and full-stack ownership.
    - Maudlin is relevant for Python, TensorFlow/Keras, model workflows, data analysis, and AI-adjacent roles.
    - Mock Programming Job is relevant for mentoring, engineering standards, pull requests, code review, and technical leadership.
    - Base is relevant for reusable backend/mobile application infrastructure.

    Do not overemphasize AI projects for a pure backend role unless the target job asks for AI, ML, LLMs, or model workflows.

    ## SENIORITY PRESERVATION

    The candidate has deep senior engineering experience.

    The resume should not read like a mid-level engineer.

    Preserve signals such as:
    - mentoring engineers
    - reviewing pull requests
    - improving team practices
    - reducing technical debt
    - building reusable platforms
    - creating developer tools
    - integrating distributed systems
    - supporting high-traffic or high-volume systems
    - improving delivery workflows

    Use role content to preserve depth.

    ## COMPANY, SCHOOL, AND CERTIFICATION RULES

    Preserved companies:
    {companies_str}

    Company names must stay as-is.

    Preserved school:
    {school}

    Do not invent degrees. If education is coursework, keep it as coursework.

    Do not invent certifications.

    ## FINAL QUALITY CHECK BEFORE OUTPUT

    Before returning JSON, silently verify:

    1. Did I preserve exact metrics and what they measure?
    2. Did I avoid converting concrete evidence into vague claims?
    3. Did I avoid generic AI resume language?
    4. Did I preserve seniority and depth?
    5. Did the first half page make the target-job match obvious?
    6. Did I avoid inventing tools, responsibilities, or outcomes?
    7. Did I avoid rewriting strong bullets merely to make them different?
    8. Would this sound credible to a senior engineer reading it?
    9. Does len(experience) equal the profile company count from source work history?
    10. Does each profile company appear exactly once in experience?

    ## TEMPLATE INPUT PREFERENCES (INFORMATIONAL)

    This context is informational and helps prioritize content quality for downstream rendering.
    It does NOT change the required output schema.
    Do not add new top-level fields and do not remove required fields.

    {content_prep_context_text}

    ## OUTPUT

    Return ONLY valid JSON.
    No markdown fences.
    No commentary.
    No "here is" preamble.

    Use this exact JSON shape:

    {{
      "title": "Role Title",
      "summary": "4-6 tailored sentences.",
      "skills": {{
        "Languages": "...",
        "Backend": "...",
        "Cloud / DevOps": "...",
        "Data / Messaging": "...",
        "Testing": "...",
        "Frontend": "...",
        "AI / Data Tooling": "..."
      }},
      "experience": [
        {{
          "header": "Title at Company",
          "subtitle": "Tech | Dates",
          "bullets": [
            "bullet 1",
            "bullet 2",
            "bullet 3",
            "bullet 4"
          ]{experience_compact_summary_line}
        }}
      ],
      "projects": [
        {{
          "header": "Project Name - Description",
          "subtitle": "Tech | Dates",
          "bullets": [
            "bullet 1",
            "bullet 2"
          ]{project_compact_summary_line}
        }}
      ],
      "education": "{education_block}"
    }}
    """

    return system_prompt;


def _build_judge_prompt(profile: dict) -> str:
    """Build the LLM judge prompt from the user's profile."""
    skills_str = ", ".join(get_profile_skill_keywords(profile)) or "N/A"
    real_metrics = get_profile_verified_metrics(profile)
    metrics_str = ", ".join(real_metrics) if real_metrics else "N/A"

    return f"""You are a resume quality judge. A tailoring engine rewrote a resume to target a specific job. Your job is to catch LIES, not style changes.

You must answer with EXACTLY this format:
VERDICT: PASS or FAIL
ISSUES: (list any problems, or "none")

## CONTEXT -- what the tailoring engine was instructed to do (all of this is ALLOWED):
- Change the title to match the target role
- Rewrite the summary from scratch for the target job
- Reorder bullets and projects to put the most relevant first
- Reframe bullets to use the job's language
- Drop low-relevance bullets and replace with more relevant ones from other sections
- Reorder the skills section to put job-relevant skills first
- Change tone and wording extensively

## WHAT IS FABRICATION (FAIL for these):
1. Adding tools, languages, or frameworks to TECHNICAL SKILLS that aren't in the original. The allowed skills are ONLY: {skills_str}
2. Inventing NEW metrics or numbers not in the original. The real metrics are: {metrics_str}
3. Inventing work that has no basis in any original bullet (completely new achievements).
4. Adding companies, roles, or degrees that don't exist.
5. Changing real numbers (inflating 80% to 95%, 500 nodes to 1000 nodes).

## WHAT IS NOT FABRICATION (do NOT fail for these):
- Rewording any bullet, even heavily, as long as the underlying work is real
- Combining two original bullets into one
- Splitting one original bullet into two
- Describing the same work with different emphasis
- Dropping bullets entirely
- Reordering anything
- Changing the title or summary completely

## TOLERANCE RULE:
The goal is to get interviews, not to be a perfect fact-checker. Allow up to 3 minor stretches per resume:
- Adding a closely related tool the candidate could realistically know is a MINOR STRETCH, not fabrication.
- Reframing a metric with slightly different wording is a MINOR STRETCH.
- Adding any LEARNABLE skill given their existing stack is a MINOR STRETCH.
- Only FAIL if there are MAJOR lies: completely invented projects, fake companies, fake degrees, wildly inflated numbers, or skills from a completely different domain.

Be strict about major lies. Be lenient about minor stretches and learnable skills. Do not fail for style, tone, or restructuring."""


# ── JSON Extraction ───────────────────────────────────────────────────────

def extract_json(raw: str) -> dict:
    """Robustly extract JSON from LLM response (handles fences, preamble).

    Args:
        raw: Raw LLM response text.

    Returns:
        Parsed JSON dict.

    Raises:
        ValueError: If no valid JSON found.
    """
    raw = raw.strip()

    # Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Markdown fences
    if "```" in raw:
        for part in raw.split("```")[1::2]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except json.JSONDecodeError:
                continue

    # Find outermost { ... }
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError("No valid JSON found in LLM response")


def _normalize_bullet(bullet: Any) -> str:
    """Normalize a bullet to plain text, stripping embedded JSON metadata."""

    if isinstance(bullet, dict):
        for key in ("text", "bullet", "content", "description"):
            value = bullet.get(key)
            if isinstance(value, str):
                return value.strip()
        return json.dumps(bullet, ensure_ascii=False)

    bullet_str = str(bullet).strip()
    if bullet_str.startswith("{") or bullet_str.startswith("["):
        try:
            parsed = json.loads(bullet_str)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            for key in ("text", "bullet", "content", "description"):
                value = parsed.get(key)
                if isinstance(value, str):
                    return value.strip()
            return json.dumps(parsed, ensure_ascii=False)

    json_start = bullet_str.find(" {")
    if json_start == -1:
        json_start = bullet_str.find("\t{")
    if json_start != -1:
        candidate = bullet_str[:json_start].rstrip()
        remainder = bullet_str[json_start:].strip()
        if remainder.startswith("{") and ("variants" in remainder or "tags" in remainder or "role_families" in remainder):
            return candidate
    return bullet_str


def _strip_disallowed_watchlist_skills(data: dict, profile: dict) -> list[str]:
    """Remove watchlist skills from generated skill output."""

    skills = data.get("skills")
    if not isinstance(skills, dict):
        return []

    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    # Keep function signature aligned with profile-aware sanitizers even though
    # watchlist terms are always stripped to match validator behavior.
    del profile
    watchlist_norm: set[str] = set()
    for skill in FABRICATION_WATCHLIST:
        if len(skill) <= 2:
            continue
        normalized_skill = _normalize(skill)
        if not normalized_skill:
            continue
        # Avoid collapsing values like "c++" to single-character tokens ("c").
        if len(normalized_skill.replace(" ", "")) <= 2:
            continue
        watchlist_norm.add(normalized_skill)

    removed: list[str] = []

    for key, value in list(skills.items()):
        if isinstance(value, str):
            entries = [part.strip() for part in value.split(",") if part.strip()]
        elif isinstance(value, list):
            entries = [str(part).strip() for part in value if str(part).strip()]
        else:
            entries = [str(value).strip()] if str(value).strip() else []

        kept: list[str] = []
        for entry in entries:
            entry_norm = _normalize(entry)
            if not entry_norm:
                continue
            is_watchlist = any(w in entry_norm for w in watchlist_norm)
            if is_watchlist:
                removed.append(entry)
                continue
            kept.append(entry)

        skills[key] = ", ".join(kept)

    return removed


def _collect_renderable_project_entries(data: dict) -> list[dict]:
    """Return project entries that contain at least one renderable field."""

    raw_projects = data.get("projects", [])
    if not isinstance(raw_projects, list):
        return []

    renderable: list[dict] = []
    for entry in raw_projects:
        if not isinstance(entry, dict):
            continue
        header = sanitize_text(str(entry.get("header", ""))).strip()
        subtitle = sanitize_text(str(entry.get("subtitle", ""))).strip()
        bullets = []
        for b in entry.get("bullets", []):
            bullet_text = _normalize_bullet(b)
            if bullet_text and sanitize_text(bullet_text).strip():
                bullets.append(bullet_text)
        if header or subtitle or bullets:
            renderable.append(entry)
    return renderable


def _build_tailored_prefix(job: dict) -> str:
    """Build a deterministic, collision-resistant filename prefix for a job."""

    return build_artifact_prefix(job)


# ── Resume Assembly (profile-driven header) ──────────────────────────────

def _normalize_company_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _coerce_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _coerce_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _get_tailored_max_lines(profile: dict) -> int:
    """Compute line budget from tailoring_config max pages settings.

    Supports:
      - tailoring_config.global_rules.max_resume_pages
      - tailoring_config.global_rules.formatting.lines_per_page
    """
    tailoring_config = profile.get("tailoring_config", {}) or {}
    global_rules = tailoring_config.get("global_rules", {}) or {}
    formatting = global_rules.get("formatting", {}) or {}

    max_pages = _coerce_float(global_rules.get("max_resume_pages"), _DEFAULT_MAX_RESUME_PAGES)
    lines_per_page = _coerce_int(formatting.get("lines_per_page"), _DEFAULT_LINES_PER_PAGE)

    return max(60, int(round(max_pages * lines_per_page)))


def _company_in_entry(entry: dict, company: str) -> bool:
    company_norm = _normalize_company_text(company)
    if not company_norm:
        return False
    entry_text = " ".join(
        str(entry.get(key, ""))
        for key in ("header", "company", "subtitle")
    )
    return company_norm in _normalize_company_text(entry_text)


def _missing_profile_companies_in_generated_experience(data: dict, profile: dict) -> list[str]:
    """Return profile companies absent from LLM-generated experience entries."""

    work_companies = get_profile_company_names(profile)
    generated_experience = data.get("experience", []) if isinstance(data.get("experience"), list) else []
    matched_companies: set[str] = set()

    for company in work_companies:
        if any(isinstance(entry, dict) and _company_in_entry(entry, company) for entry in generated_experience):
            matched_companies.add(company)

    return [company for company in work_companies if company not in matched_companies]


def _extract_job_keywords(job_text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z0-9\+\#\-]{4,}", job_text.lower())
    return {t for t in tokens if t not in _JOB_KEYWORD_STOPWORDS}


def _select_relevant_highlights(highlights: list[str], job_text: str, *, limit: int) -> list[str]:
    if not highlights:
        return []

    keywords = _extract_job_keywords(job_text)
    if not keywords:
        return highlights[:limit]

    def score(text: str) -> tuple[int, int]:
        words = set(re.findall(r"[a-zA-Z0-9\+\#\-]{4,}", text.lower()))
        overlap = len(words & keywords)
        return overlap, len(text)

    ranked = sorted(highlights, key=score, reverse=True)
    return ranked[:limit]


def _build_role_date_range(role: dict) -> str:
    start = str(role.get("start_date", "")).strip()
    end = str(role.get("end_date", "")).strip()
    end_display = end if end else "Present"
    if start and end_display:
        return f"{start} - {end_display}"
    return start or end_display


def _build_profile_full_entry(role: dict, job_text: str) -> dict:
    company = str(role.get("company", "")).strip()
    position = str(role.get("position", "")).strip() or "Software Engineer"
    highlights = [sanitize_text(str(h)) for h in role.get("highlights", []) if str(h).strip()]
    selected = _select_relevant_highlights(highlights, job_text, limit=3)
    if not selected and role.get("summary"):
        selected = [sanitize_text(str(role.get("summary", "")))]
    return {
        "header": f"{position}",
        "subtitle": f"{company} | {_build_role_date_range(role)}".strip(),
        "bullets": selected,
    }


def _build_profile_compact_entry(role: dict, job_text: str) -> dict:
    company = str(role.get("company", "")).strip()
    position = str(role.get("position", "")).strip() or "Software Engineer"
    highlights = [sanitize_text(str(h)) for h in role.get("highlights", []) if str(h).strip()]
    selected = _select_relevant_highlights(highlights, job_text, limit=1)
    if not selected and role.get("summary"):
        selected = [sanitize_text(str(role.get("summary", "")))]
    return {
        "header": f"{position} | {company}".strip(" |"),
        "subtitle": _build_role_date_range(role),
        "bullets": selected,
    }


def _sanitize_experience_entry(entry: dict) -> dict:
    sanitized = {
        "header": sanitize_text(str(entry.get("header", ""))).strip(),
        "subtitle": sanitize_text(str(entry.get("subtitle", ""))).strip(),
        "bullets": [],
    }
    for bullet in entry.get("bullets", []):
        bullet_text = _normalize_bullet(bullet)
        if bullet_text:
            clean = sanitize_text(bullet_text).strip()
            if clean:
                sanitized["bullets"].append(clean)
    return sanitized


def _find_matching_profile_role(entry: dict, profile_roles: list[dict]) -> dict | None:
    for role in profile_roles:
        if not isinstance(role, dict):
            continue
        company = str(role.get("company", "")).strip()
        if company and _company_in_entry(entry, company):
            return role
    return None


def _build_compact_entry_from_generated(entry: dict) -> dict:
    return {
        "header": str(entry.get("header", "")).strip(),
        "subtitle": str(entry.get("subtitle", "")).strip(),
        "bullets": list(entry.get("bullets", []))[:1],
    }


def _merge_unique_bullets(primary: list[str], fallback: list[str], *, max_items: int) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for bullet in primary + fallback:
        normalized = sanitize_text(str(bullet)).strip()
        if not normalized:
            continue
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        merged.append(normalized)
        seen.add(dedupe_key)
        if len(merged) >= max_items:
            break
    return merged


def _enrich_full_entry_from_profile(role: dict, entry: dict, job_text: str) -> dict:
    """Enrich thin generated entries using role highlights before compaction."""

    enriched = {
        "header": str(entry.get("header", "")).strip(),
        "subtitle": str(entry.get("subtitle", "")).strip(),
        "bullets": list(entry.get("bullets", [])),
    }

    fallback = _build_profile_full_entry(role, job_text)
    if not enriched["header"]:
        enriched["header"] = fallback.get("header", "")
    if not enriched["subtitle"]:
        enriched["subtitle"] = fallback.get("subtitle", "")

    bullets = [sanitize_text(str(b)).strip() for b in enriched.get("bullets", []) if str(b).strip()]
    fallback_bullets = [sanitize_text(str(b)).strip() for b in fallback.get("bullets", []) if str(b).strip()]

    # Build fuller role detail before downstream length-based compaction.
    min_full_bullets = 3
    max_full_bullets = 4
    target_count = max(min_full_bullets, min(max_full_bullets, len(bullets)))
    if len(bullets) < min_full_bullets:
        target_count = min_full_bullets

    enriched["bullets"] = _merge_unique_bullets(bullets, fallback_bullets, max_items=target_count)
    return enriched


def _render_resume_lines(
    data: dict,
    profile: dict,
    experience_entries: list[dict],
    selected_entries: list[dict],
) -> list[str]:
    """Render deterministic resume lines from structured sections."""
    personal = profile.get("personal", {})
    lines: list[str] = []

    # Header -- always code-injected from profile
    lines.append(personal.get("full_name", ""))
    lines.append(sanitize_text(data.get("title", "Software Engineer")))

    # Contact line
    contact_parts: list[str] = []
    if personal.get("email"):
        contact_parts.append(personal["email"])
    if personal.get("phone"):
        contact_parts.append(personal["phone"])
    if personal.get("github_url"):
        contact_parts.append(personal["github_url"])
    if personal.get("linkedin_url"):
        contact_parts.append(personal["linkedin_url"])
    if contact_parts:
        lines.append(" | ".join(contact_parts))
    lines.append("")

    # Summary
    lines.append("SUMMARY")
    lines.append(sanitize_text(data["summary"]))
    lines.append("")

    # Technical Skills
    lines.append("TECHNICAL SKILLS")
    if isinstance(data["skills"], dict):
        for cat, val in data["skills"].items():
            lines.append(f"{cat}: {sanitize_text(str(val))}")
    lines.append("")

    # Experience
    lines.append("EXPERIENCE")
    for entry in experience_entries:
        lines.append(entry.get("header", ""))
        if entry.get("subtitle"):
            lines.append(entry["subtitle"])
        for bullet in entry.get("bullets", []):
            lines.append(f"- {bullet}")
        lines.append("")

    # Selected Experience
    if selected_entries:
        lines.append("SELECTED EXPERIENCE")
        for entry in selected_entries:
            lines.append(entry.get("header", ""))
            if entry.get("subtitle"):
                lines.append(entry["subtitle"])
            for bullet in entry.get("bullets", []):
                lines.append(f"- {bullet}")
            lines.append("")

    # Projects (only include section when there is content)
    project_entries = _collect_renderable_project_entries(data)
    if project_entries:
        lines.append("PROJECTS")
        for entry in project_entries:
            lines.append(sanitize_text(entry.get("header", "")))
            if entry.get("subtitle"):
                lines.append(sanitize_text(entry["subtitle"]))
            for b in entry.get("bullets", []):
                bullet_text = _normalize_bullet(b)
                if bullet_text:
                    lines.append(f"- {sanitize_text(bullet_text)}")
            lines.append("")

    # Education
    lines.append("EDUCATION")
    lines.append(sanitize_text(str(data.get("education", ""))))

    return lines


def assemble_resume_text(data: dict, profile: dict, job: dict | None = None) -> str:
    """Convert JSON resume data to formatted plain text.

    Header (name, location, contact) is ALWAYS code-injected from the profile,
    never LLM-generated. All text fields are sanitized.

    Args:
        data: Parsed JSON resume from the LLM.
        profile: User profile dict from load_profile().

    Returns:
        Formatted resume text.
    """
    job = job or {}
    job_text = " ".join(
        str(job.get(key, "")).strip()
        for key in ("title", "full_description", "description")
    ).strip()

    raw_profile_roles = profile.get("work", [])
    profile_roles = [role for role in raw_profile_roles if isinstance(role, dict)]
    generated_experience = data.get("experience", []) if isinstance(data.get("experience"), list) else []

    # Start from model-generated ordering/content only.
    experience_bundles: list[dict] = []
    for entry in generated_experience:
        if not isinstance(entry, dict):
            continue
        sanitized = _sanitize_experience_entry(entry)
        if not sanitized.get("header") and not sanitized.get("subtitle") and not sanitized.get("bullets"):
            continue
        role = _find_matching_profile_role(sanitized, profile_roles)
        if isinstance(role, dict):
            sanitized = _enrich_full_entry_from_profile(role, sanitized, job_text)
        experience_bundles.append({"role": role, "entry": sanitized})

    full_entries = [bundle["entry"] for bundle in experience_bundles]
    selected_entries: list[dict] = []
    max_lines = _get_tailored_max_lines(profile)

    lines = _render_resume_lines(data, profile, full_entries, selected_entries)

    role_order: dict[str, int] = {}
    for idx, role in enumerate(profile_roles):
        company = _normalize_company_text(str(role.get("company", "")))
        if company and company not in role_order:
            role_order[company] = idx

    # Keep all jobs represented: move oldest roles into "SELECTED EXPERIENCE"
    # until the assembled resume fits the approximate maximum length.
    while len(lines) > max_lines and len(experience_bundles) > 1:
        move_idx = len(experience_bundles) - 1
        oldest_order = -1
        for idx, bundle in enumerate(experience_bundles):
            role = bundle.get("role")
            if isinstance(role, dict):
                company = _normalize_company_text(str(role.get("company", "")))
                order_val = role_order.get(company, -1)
                if order_val >= oldest_order:
                    oldest_order = order_val
                    move_idx = idx

        bundle = experience_bundles.pop(move_idx)
        role = bundle.get("role")
        if isinstance(role, dict):
            selected_entries.insert(0, _build_profile_compact_entry(role, job_text))
        else:
            compact = _build_compact_entry_from_generated(bundle.get("entry", {}))
            selected_entries.insert(0, compact)

        full_entries = [item["entry"] for item in experience_bundles]
        lines = _render_resume_lines(data, profile, full_entries, selected_entries)

    # If still over budget, further compress selected entries while preserving
    # one-line role identity per job.
    if len(lines) > max_lines and selected_entries:
        for entry in selected_entries:
            if len(lines) <= max_lines:
                break
            entry["bullets"] = list(entry.get("bullets", []))[:1]
            if len(lines) > max_lines and entry.get("subtitle"):
                entry["subtitle"] = ""
            lines = _render_resume_lines(data, profile, full_entries, selected_entries)

    return "\n".join(lines)


# ── LLM Judge ────────────────────────────────────────────────────────────

def judge_tailored_resume(
    original_text: str, tailored_text: str, job_title: str, profile: dict
) -> dict:
    """LLM judge layer: catches subtle fabrication that programmatic checks miss.

    Args:
        original_text: Base resume text.
        tailored_text: Tailored resume text.
        job_title: Target job title.
        profile: User profile for building the judge prompt.

    Returns:
        {"passed": bool, "verdict": str, "issues": str, "raw": str}
    """
    judge_prompt = _build_judge_prompt(profile)

    messages = [
        {"role": "system", "content": judge_prompt},
        {"role": "user", "content": (
            f"JOB TITLE: {job_title}\n\n"
            f"ORIGINAL RESUME:\n{original_text}\n\n---\n\n"
            f"TAILORED RESUME:\n{tailored_text}\n\n"
            "Judge this tailored resume:"
        )},
    ]

    client = get_client()
    response = client.chat(messages, max_output_tokens=512)

    passed = "VERDICT: PASS" in response.upper()
    issues = "none"
    if "ISSUES:" in response.upper():
        issues_idx = response.upper().index("ISSUES:")
        issues = response[issues_idx + 7:].strip()

    return {
        "passed": passed,
        "verdict": "PASS" if passed else "FAIL",
        "issues": issues,
        "raw": response,
    }


# ── Core Tailoring ───────────────────────────────────────────────────────

def tailor_resume(
    resume_text: str, job: dict, profile: dict,
    max_retries: int = 3, validation_mode: str = "normal",
    content_preparation_context: dict | None = None,
) -> tuple[str, dict]:
    """Generate a tailored resume via JSON output + fresh context on each retry.

    Key design choices:
    - LLM returns structured JSON, code assembles the text (no header leaks)
    - Each retry starts a FRESH conversation (no apologetic spiral)
    - Issues from previous attempts are noted in the system prompt
    - Em dashes and smart quotes are auto-fixed, not rejected

    Args:
        resume_text:      Base resume text.
        job:              Job dict with title, site, location, full_description.
        profile:          User profile dict.
        max_retries:      Maximum retry attempts.
        validation_mode:  "strict", "normal", or "lenient".
                          strict  -- banned words trigger retries; judge must pass
                          normal  -- banned words = warnings only; judge can fail on last retry
                          lenient -- banned words ignored; LLM judge skipped

    Returns:
        (tailored_text, report) where report contains validation details.
    """
    job_text = (
        f"TITLE: {job['title']}\n"
        f"COMPANY: {job['site']}\n"
        f"LOCATION: {job.get('location', 'N/A')}\n\n"
        f"DESCRIPTION:\n{(job.get('full_description') or '')[:6000]}"
    )

    report: dict = {
        "attempts": 0, "validator": None, "judge": None,
        "status": "pending", "validation_mode": validation_mode,
        "content_preparation_context": dict(content_preparation_context or {}),
    }
    avoid_notes: list[str] = []
    tailored = ""
    client = get_client()
    tailor_prompt_base = _build_tailor_prompt(
        profile,
        content_preparation_context=report["content_preparation_context"],
    )

    for attempt in range(max_retries + 1):
        report["attempts"] = attempt + 1

        # Fresh conversation every attempt
        prompt = tailor_prompt_base
        if avoid_notes:
            prompt += "\n\n## AVOID THESE ISSUES (from previous attempt):\n" + "\n".join(
                f"- {n}" for n in avoid_notes[-5:]
            )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"ORIGINAL RESUME:\n{resume_text}\n\n---\n\nTARGET JOB:\n{job_text}\n\nReturn the JSON:"},
        ]

        raw = client.chat(messages, max_output_tokens=16000)

        # Parse JSON from response
        try:
            data = extract_json(raw)
        except ValueError as exc:
            log.warning("Attempt %d JSON parse failed (%s). Raw response (first 500 chars):\n%s",
                        attempt + 1, exc, raw[:1000])
            avoid_notes.append("Output was not valid JSON. Return ONLY a JSON object, nothing else.")
            continue

        removed_skills = _strip_disallowed_watchlist_skills(data, profile)
        if removed_skills:
            log.info(
                "Attempt %d removed disallowed watchlist skills: %s",
                attempt + 1,
                ", ".join(removed_skills[:5]),
            )

        # Layer 1: Validate JSON fields
        validation = validate_json_fields(data, profile, mode=validation_mode)
        missing_companies = _missing_profile_companies_in_generated_experience(data, profile)
        if missing_companies:
            missing_msg = "ERROR: LLM omitted required experience companies: " + ", ".join(missing_companies)
            log.error("%s", missing_msg)
            warning_prefixes = tuple(f"Company '{company}' missing from experience" for company in missing_companies)
            warnings = validation.setdefault("warnings", [])
            validation["warnings"] = [w for w in warnings if not w.startswith(warning_prefixes)]
            validation.setdefault("errors", []).append(missing_msg)
            validation["passed"] = False
        if not _collect_renderable_project_entries(data):
            warnings = validation.setdefault("warnings", [])
            project_warning = "No projects available to list on resume."
            if project_warning not in warnings:
                warnings.append(project_warning)
        report["validator"] = validation

        if not validation["passed"]:
            # Only retry if there are hard errors (warnings never block)
            log.warning("Attempt %d validation failed: %s", attempt + 1, validation["errors"])
            avoid_notes.extend(validation["errors"])
            if attempt < max_retries:
                continue
            # Last attempt — assemble whatever we got
            tailored = assemble_resume_text(data, profile, job=job)
            report["tailored_json"] = data
            report["status"] = "failed_validation"
            return tailored, report

        # Assemble text (header injected by code, em dashes auto-fixed)
        tailored = assemble_resume_text(data, profile, job=job)

        # Layer 2: LLM judge (catches subtle fabrication) — skipped in lenient mode
        if validation_mode == "lenient":
            report["judge"] = {"verdict": "SKIPPED", "passed": True, "issues": "none"}
            report["tailored_json"] = data
            report["status"] = "approved"
            return tailored, report

        judge = judge_tailored_resume(resume_text, tailored, job.get("title", ""), profile)
        report["judge"] = judge

        if not judge["passed"]:
            avoid_notes.append(f"Judge rejected: {judge['issues']}")
            if attempt < max_retries:
                # In normal mode, only retry on judge failure if there are retries left
                if validation_mode != "lenient":
                    continue
            # Accept best attempt on last retry (all modes) or if lenient
            report["tailored_json"] = data
            report["status"] = "approved_with_judge_warning"
            return tailored, report

        # Both passed
        report["tailored_json"] = data
        report["status"] = "approved"
        return tailored, report

    report["status"] = "exhausted_retries"
    return tailored, report


# ── Batch Entry Point ────────────────────────────────────────────────────

def run_tailoring(
    min_score: int = 7,
    limit: int = 0,
    validation_mode: str = "normal",
    target_url: str | None = None,
    force: bool = False,
) -> dict:
    """Generate tailored resumes for high-scoring jobs.

    Args:
        min_score:       Minimum fit_score to tailor for.
        limit:           Maximum jobs to process (0 = all eligible jobs).
        validation_mode: "strict", "normal", or "lenient".
        target_url:      Optional URL to tailor a single matched job.
        force:           When target_url is provided, regenerate even if tailored resume exists
                         or fit_score is below min_score.

    Returns:
        {"approved": int, "failed": int, "errors": int, "elapsed": float}
    """
    profile = load_profile()
    try:
        resume_text = load_resume_text()
    except FileNotFoundError:
        log.error("Resume file not found. Run 'applypilot init' first.")
        return {"approved": 0, "failed": 0, "errors": 0, "elapsed": 0.0}
    conn = get_connection()

    if target_url:
        like = f"%{target_url.split('?')[0].rstrip('/')}%"
        row = conn.execute(
            """
            SELECT * FROM jobs
            WHERE (url = ? OR application_url = ? OR application_url LIKE ? OR url LIKE ?)
            LIMIT 1
            """,
            (target_url, target_url, like, like),
        ).fetchone()
        if not row:
            log.info("Target URL not found in database: %s", target_url)
            return {"approved": 0, "failed": 0, "errors": 0, "elapsed": 0.0}

        if isinstance(row, dict):
            target_job = dict(row)
        else:
            columns = row.keys()
            target_job = dict(zip(columns, row))
        if not target_job.get("full_description"):
            log.error("Target job has no full description. Run 'applypilot run enrich' first.")
            return {"approved": 0, "failed": 0, "errors": 0, "elapsed": 0.0}
        score = target_job.get("fit_score")
        if not force and score is not None and score < min_score:
            log.info(
                "Target job score %s is below min-score %d. Use --force to override.",
                score,
                min_score,
            )
            return {"approved": 0, "failed": 0, "errors": 0, "elapsed": 0.0}
        if not force and target_job.get("tailored_resume_path"):
            log.info("Target job already has a tailored resume. Use --force to regenerate.")
            return {"approved": 0, "failed": 0, "errors": 0, "elapsed": 0.0}
        jobs = [target_job]
    else:
        jobs = get_jobs_by_stage(conn=conn, stage="pending_tailor", min_score=min_score, limit=limit)

    if not jobs:
        log.info("No untailored jobs with score >= %d.", min_score)
        return {"approved": 0, "failed": 0, "errors": 0, "elapsed": 0.0}

    TAILORED_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Tailoring resumes for %d jobs (score >= %d)...", len(jobs), min_score)
    t0 = time.time()
    completed = 0
    results: list[dict] = []
    stats: dict[str, int] = {"approved": 0, "failed_validation": 0, "failed_judge": 0, "error": 0}
    from applypilot.scoring.pdf import DEFAULT_PDF_TEMPLATE, resolve_pdf_template_name
    from applypilot.scoring.pdf_templates.registry import get_template, get_template_input_preferences

    pdf_template_name = resolve_pdf_template_name(profile)
    try:
        get_template(pdf_template_name)
    except ValueError as exc:
        log.warning(
            "Configured PDF template '%s' is invalid (%s). Falling back to '%s'.",
            pdf_template_name,
            exc,
            DEFAULT_PDF_TEMPLATE,
        )
        pdf_template_name = DEFAULT_PDF_TEMPLATE
    try:
        pdf_template_input_preferences = get_template_input_preferences(pdf_template_name)
    except Exception as exc:  # pragma: no cover - defensive guard for metadata lookup
        log.warning(
            "Unable to load PDF template input preferences for '%s': %s. Continuing without preferences.",
            pdf_template_name,
            exc,
        )
        pdf_template_input_preferences = {}
    content_preparation_context = {
        "pdf_template": pdf_template_name,
        "pdf_template_input_preferences": pdf_template_input_preferences,
    }

    for job in jobs:
        completed += 1
        try:
            tailored, report = tailor_resume(
                resume_text,
                job,
                profile,
                validation_mode=validation_mode,
                content_preparation_context=content_preparation_context,
            )
            report["pdf_template"] = pdf_template_name
            report["pdf_template_input_preferences"] = pdf_template_input_preferences
            report["content_preparation_context"] = dict(content_preparation_context)

            # Build collision-resistant filename prefix
            prefix = _build_tailored_prefix(job)

            # Save tailored resume text
            txt_path = TAILORED_DIR / f"{prefix}.txt"
            txt_path.write_text(tailored, encoding="utf-8")
            if not txt_path.exists() or txt_path.stat().st_size == 0:
                raise RuntimeError(f"Failed to persist tailored TXT: {txt_path}")

            # Save job description for traceability
            job_path = TAILORED_DIR / f"{prefix}_JOB.txt"
            job_desc = (
                f"Title: {job['title']}\n"
                f"Company: {job['site']}\n"
                f"Location: {job.get('location', 'N/A')}\n"
                f"Score: {job.get('fit_score', 'N/A')}\n"
                f"URL: {job['url']}\n\n"
                f"{job.get('full_description', '')}"
            )
            job_path.write_text(job_desc, encoding="utf-8")

            # Save validation report
            report_path = TAILORED_DIR / f"{prefix}_REPORT.json"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

            # Generate PDF for approved resumes.
            # "approved_with_judge_warning" is also a success — resume was generated.
            pdf_path = None
            status = report["status"]
            if status in ("approved", "approved_with_judge_warning"):
                try:
                    from applypilot.scoring.pdf import convert_to_pdf, render_model_to_pdf
                    from applypilot.scoring.pdf_render_model import build_render_model_from_tailored_json

                    generated_pdf = txt_path.with_suffix(".pdf")
                    tailored_json = report.get("tailored_json")
                    if isinstance(tailored_json, dict):
                        try:
                            model = build_render_model_from_tailored_json(tailored_json, profile)
                            generated_pdf = render_model_to_pdf(
                                model,
                                generated_pdf,
                                template_name=pdf_template_name,
                            )
                        except Exception as structured_exc:
                            log.warning(
                                "Structured PDF render failed for %s, falling back to text-based render: %s",
                                txt_path,
                                structured_exc,
                            )
                            generated_pdf = convert_to_pdf(
                                txt_path,
                                output_path=generated_pdf,
                                template_name=pdf_template_name,
                            )
                    else:
                        generated_pdf = convert_to_pdf(
                            txt_path,
                            output_path=generated_pdf,
                            template_name=pdf_template_name,
                        )
                    pdf_path = str(generated_pdf)
                    if not generated_pdf.exists() or generated_pdf.stat().st_size == 0:
                        raise RuntimeError(f"Generated PDF missing or empty: {generated_pdf}")
                except Exception as exc:
                    # A submission-ready tailored resume needs both TXT and PDF.
                    log.error("PDF generation failed for %s: %s", txt_path, exc)
                    status = "error"

            result = {
                "url": job["url"],
                "path": str(txt_path),
                "pdf_path": pdf_path,
                "title": job["title"],
                "site": job["site"],
                "status": status,
                "attempts": report["attempts"],
            }
            if status in ("approved", "approved_with_judge_warning"):
                log.info("Saved tailored artifacts: txt=%s | pdf=%s", txt_path.resolve(), Path(pdf_path).resolve())
            else:
                log.info("Saved tailored TXT: %s", txt_path.resolve())
        except Exception as e:
            result = {
                "url": job["url"], "title": job["title"], "site": job["site"],
                "status": "error", "attempts": 0, "path": None, "pdf_path": None,
            }
            log.error("%d/%d [ERROR] %s -- %s", completed, len(jobs), job["title"][:40], e)

        results.append(result)
        stats[result.get("status", "error")] = stats.get(result.get("status", "error"), 0) + 1

        elapsed = time.time() - t0
        rate = completed / elapsed if elapsed > 0 else 0
        log.info(
            "%d/%d [%s] attempts=%s | %.1f jobs/min | %s",
            completed, len(jobs),
            result["status"].upper(),
            result.get("attempts", "?"),
            rate * 60,
            result["title"][:40],
        )

    # Persist to DB: increment attempt counter for ALL, save path only for approved
    now = datetime.now(timezone.utc).isoformat()
    _success_statuses = {"approved", "approved_with_judge_warning"}
    for r in results:
        if r["status"] in _success_statuses:
            conn.execute(
                "UPDATE jobs SET tailored_resume_path=?, tailored_at=?, "
                "tailor_attempts=COALESCE(tailor_attempts,0)+1 WHERE url=?",
                (r["path"], now, r["url"]),
            )
        else:
            conn.execute(
                "UPDATE jobs SET tailor_attempts=COALESCE(tailor_attempts,0)+1 WHERE url=?",
                (r["url"],),
            )
    conn.commit()

    elapsed = time.time() - t0
    log.info(
        "Tailoring done in %.1fs: %d approved, %d failed_validation, %d failed_judge, %d errors",
        elapsed,
        stats.get("approved", 0),
        stats.get("failed_validation", 0),
        stats.get("failed_judge", 0),
        stats.get("error", 0),
    )

    return {
        "approved": stats.get("approved", 0),
        "failed": stats.get("failed_validation", 0) + stats.get("failed_judge", 0),
        "errors": stats.get("error", 0),
        "elapsed": elapsed,
    }
