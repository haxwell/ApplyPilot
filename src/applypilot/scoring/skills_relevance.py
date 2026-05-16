"""Relevance scoring and selection for tailored technical skills."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from applypilot.scoring.skills_taxonomy import (
    DEFAULT_SKILLS_CATALOG,
    DEFAULT_SKILLS_RELEVANCE_POLICY,
)

DEFAULT_TARGET_SKILLS = 20
DEFAULT_MAX_SKILLS = 24
DEFAULT_MIN_SKILLS = 12

_SPLIT_PATTERN = r"[,;|•\n]+"


@dataclass(frozen=True)
class SkillItem:
    category: str
    token: str
    token_key: str
    index: int


@dataclass(frozen=True)
class ScoredSkill:
    item: SkillItem
    score: float
    reasons: tuple[str, ...]


def _normalize_text(value: str) -> str:
    lowered = value.lower().replace("/", " ")
    lowered = re.sub(r"[^a-z0-9\+\#\.\-\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _tokenize_words(value: str) -> set[str]:
    return {word for word in _normalize_text(value).split() if len(word) >= 2}


def _split_skill_tokens(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items: list[str] = []
        for entry in value:
            items.extend(_split_skill_tokens(entry))
        return items
    parts = re.split(_SPLIT_PATTERN, str(value))
    return [part.strip() for part in parts if part and part.strip()]


def flatten_skills(raw_skills: Any) -> list[SkillItem]:
    """Normalize dict/list skills payloads into ordered unique skill items."""

    items: list[SkillItem] = []
    seen: set[str] = set()
    idx = 0

    def _add(category: str, token: str) -> None:
        nonlocal idx
        key = _normalize_text(token)
        if not key or key in seen:
            return
        seen.add(key)
        items.append(SkillItem(category=category, token=token.strip(), token_key=key, index=idx))
        idx += 1

    if isinstance(raw_skills, dict):
        for category, value in raw_skills.items():
            category_text = str(category).strip()
            if not category_text:
                continue
            for token in _split_skill_tokens(value):
                _add(category_text, token)
    elif isinstance(raw_skills, list):
        for i, value in enumerate(raw_skills):
            category = f"Skill {i + 1}"
            for token in _split_skill_tokens(value):
                _add(category, token)
    elif raw_skills:
        for token in _split_skill_tokens(raw_skills):
            _add("Skills", token)

    return items


def _build_job_context_text(job: dict | None, profile: dict | None) -> str:
    parts: list[str] = []
    if isinstance(job, dict):
        for key in ("title", "full_description", "description"):
            text = str(job.get(key, "")).strip()
            if text:
                parts.append(text)
    if isinstance(profile, dict):
        job_context = profile.get("job_context")
        if isinstance(job_context, dict):
            for key in ("title", "description", "full_description"):
                text = str(job_context.get(key, "")).strip()
                if text:
                    parts.append(text)
    return "\n".join(parts)


def _default_weights() -> dict[str, float]:
    return {
        "exact_match": 100.0,
        "title_match": 120.0,
        "word_overlap": 35.0,
        "synonym_match": 55.0,
        "responsibility_support": 20.0,
        "weak_frontend_penalty": -20.0,
        "weak_ml_penalty": -20.0,
    }


def _merged_weights(render_options: dict[str, Any] | None) -> dict[str, float]:
    weights = _default_weights()
    if not isinstance(render_options, dict):
        return weights
    raw = render_options.get("skills_relevance_weights")
    if not isinstance(raw, dict):
        return weights
    for key, value in raw.items():
        try:
            weights[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return weights


def _normalize_terms(terms: list[Any]) -> set[str]:
    return {_normalize_text(str(term)) for term in terms if _normalize_text(str(term))}


def _resolved_catalog(render_options: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {k: dict(v) for k, v in DEFAULT_SKILLS_CATALOG.items()}
    if not isinstance(render_options, dict):
        return catalog
    overrides = render_options.get("skills_taxonomy_overrides")
    if not isinstance(overrides, dict):
        return catalog
    for ref, payload in overrides.items():
        if not isinstance(payload, dict):
            continue
        base = catalog.get(str(ref), {})
        merged = dict(base)
        merged.update(payload)
        catalog[str(ref)] = merged
    return catalog


def _resolved_policy(render_options: dict[str, Any] | None) -> dict[str, Any]:
    policy = dict(DEFAULT_SKILLS_RELEVANCE_POLICY)
    policy["rules"] = list(DEFAULT_SKILLS_RELEVANCE_POLICY.get("rules", []))
    if not isinstance(render_options, dict):
        return policy
    override = render_options.get("skills_relevance_policy")
    if not isinstance(override, dict):
        return policy
    if isinstance(override.get("synonym_group_refs"), list):
        policy["synonym_group_refs"] = list(override["synonym_group_refs"])
    if isinstance(override.get("rules"), list):
        policy["rules"] = list(override["rules"])
    return policy


def _catalog_terms(catalog: dict[str, dict[str, Any]], ref: str, expected_kind: str) -> set[str]:
    payload = catalog.get(ref)
    if not isinstance(payload, dict):
        return set()
    if str(payload.get("kind", "")).strip() != expected_kind:
        return set()
    terms = payload.get("terms")
    if not isinstance(terms, list):
        return set()
    return _normalize_terms(terms)


def _compiled_synonym_groups(catalog: dict[str, dict[str, Any]], policy: dict[str, Any]) -> tuple[set[str], ...]:
    refs = policy.get("synonym_group_refs")
    if not isinstance(refs, list):
        return tuple()
    groups: list[set[str]] = []
    for ref in refs:
        terms = _catalog_terms(catalog, str(ref), "synonym_group")
        if terms:
            groups.append(terms)
    return tuple(groups)


def _synonym_match(skill_key: str, jd_text: str, groups: tuple[set[str], ...]) -> bool:
    for group in groups:
        if skill_key in group and any(term in jd_text for term in group):
            return True
    return False


def score_skills(
    items: list[SkillItem],
    *,
    job: dict | None = None,
    profile: dict | None = None,
    render_options: dict[str, Any] | None = None,
) -> list[ScoredSkill]:
    """Score skills for relevance to the current job context."""

    job_text_raw = _build_job_context_text(job, profile)
    jd_text = _normalize_text(job_text_raw)
    title_text = _normalize_text(str((job or {}).get("title", "")) if isinstance(job, dict) else "")
    jd_words = _tokenize_words(jd_text)
    weights = _merged_weights(render_options)
    catalog = _resolved_catalog(render_options)
    policy = _resolved_policy(render_options)
    synonym_groups = _compiled_synonym_groups(catalog, policy)
    rules = policy.get("rules", [])
    cues_cache: dict[str, bool] = {}

    scored: list[ScoredSkill] = []
    for item in items:
        reasons: list[str] = []
        score = 0.0

        if item.token_key and item.token_key in jd_text:
            score += weights["exact_match"]
            reasons.append("exact_match")

        if item.token_key and title_text and item.token_key in title_text:
            score += weights["title_match"]
            reasons.append("title_match")

        token_words = _tokenize_words(item.token_key)
        if token_words and jd_words:
            overlap = token_words & jd_words
            overlap_ratio = len(overlap) / len(token_words)
            if overlap_ratio >= 0.6:
                score += weights["word_overlap"] * overlap_ratio
                reasons.append("word_overlap")

        if _synonym_match(item.token_key, jd_text, synonym_groups):
            score += weights["synonym_match"]
            reasons.append("synonym_match")

        if isinstance(rules, list):
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                name = str(rule.get("name", "rule")).strip() or "rule"
                when = str(rule.get("when", "cue_present")).strip()
                cue_ref = str(rule.get("cue_set_ref", "")).strip()
                skill_ref = str(rule.get("skill_set_ref", "")).strip()
                weight_key = str(rule.get("weight_key", "")).strip()
                explicit_weight = rule.get("weight")
                if not cue_ref or not skill_ref:
                    continue
                if cue_ref not in cues_cache:
                    cue_terms = _catalog_terms(catalog, cue_ref, "cue_set")
                    cues_cache[cue_ref] = any(term in jd_text for term in cue_terms)
                cue_present = cues_cache.get(cue_ref, False)
                if when == "cue_present":
                    condition_met = cue_present
                elif when == "cue_absent":
                    condition_met = not cue_present
                else:
                    condition_met = False
                if not condition_met:
                    continue
                skill_terms = _catalog_terms(catalog, skill_ref, "skill_set")
                if item.token_key not in skill_terms:
                    continue
                if weight_key in weights:
                    applied_weight = weights[weight_key]
                else:
                    try:
                        applied_weight = float(explicit_weight)
                    except (TypeError, ValueError):
                        applied_weight = 0.0
                score += applied_weight
                reasons.append(name)

        scored.append(ScoredSkill(item=item, score=score, reasons=tuple(reasons)))

    return sorted(scored, key=lambda s: (-s.score, s.item.index))


def _resolve_limit(value: Any, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def select_top_skills(
    scored: list[ScoredSkill],
    *,
    render_options: dict[str, Any] | None = None,
) -> tuple[list[SkillItem], dict[str, Any]]:
    """Select a capped set of top relevant skills."""

    options = render_options if isinstance(render_options, dict) else {}
    target = _resolve_limit(options.get("skills_target_count"), DEFAULT_TARGET_SKILLS)
    maximum = _resolve_limit(options.get("skills_max_count"), DEFAULT_MAX_SKILLS)
    minimum = _resolve_limit(options.get("skills_min_count"), DEFAULT_MIN_SKILLS)

    if maximum < target:
        target = maximum
    if minimum > maximum:
        minimum = maximum

    strong = [entry for entry in scored if entry.score > 0]
    if len(strong) >= minimum:
        pool = strong
        selected_count = min(target, len(pool), maximum)
    elif strong:
        pool = scored
        selected_count = min(max(minimum, len(strong)), len(pool), maximum)
    else:
        pool = scored
        selected_count = min(minimum, len(pool), maximum)

    selected_ranked = pool[:selected_count]
    selected_set = {entry.item.token_key for entry in selected_ranked}

    # Preserve original ordering for readable category rendering.
    selected_items = sorted(
        [entry.item for entry in scored if entry.item.token_key in selected_set],
        key=lambda item: item.index,
    )

    meta = {
        "before_count": len(scored),
        "after_count": len(selected_items),
        "target_count": target,
        "max_count": maximum,
        "min_count": minimum,
        "dropped_skills": [entry.item.token for entry in scored if entry.item.token_key not in selected_set],
    }
    return selected_items, meta


def build_relevant_skills(
    raw_skills: Any,
    *,
    job: dict | None = None,
    profile: dict | None = None,
    render_options: dict[str, Any] | None = None,
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    """Return selected skills as (category, token) pairs plus selection metadata."""

    items = flatten_skills(raw_skills)
    if not items:
        return [], {"before_count": 0, "after_count": 0, "dropped_skills": []}
    scored = score_skills(items, job=job, profile=profile, render_options=render_options)
    selected_items, meta = select_top_skills(scored, render_options=render_options)
    return [(item.category, item.token) for item in selected_items], meta
