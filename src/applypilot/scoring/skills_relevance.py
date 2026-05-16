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


def _contains_phrase(text: str, phrase: str) -> bool:
    """Return True when phrase is present as a whole token/phrase, not substring."""

    normalized_text = _normalize_text(text)
    normalized_phrase = _normalize_text(phrase)
    if not normalized_text or not normalized_phrase:
        return False
    phrase_pattern = r"\s+".join(re.escape(part) for part in normalized_phrase.split())
    pattern = rf"(?<![a-z0-9]){phrase_pattern}(?![a-z0-9])"
    return bool(re.search(pattern, normalized_text))


def _skill_variants(skill_key: str) -> set[str]:
    """Return canonical variants for matching/synonym checks."""

    variants: set[str] = {skill_key}
    # Remove parenthetical metadata like versions: "Java (17-21)" -> "java"
    no_paren = re.sub(r"\([^)]*\)", "", skill_key).strip()
    if no_paren:
        variants.add(no_paren)
    # Remove trailing version hints: "spring boot 3.x" -> "spring boot"
    no_version = re.sub(r"\b\d+(?:\.\d+)?(?:\.[a-z0-9]+)?\b", "", no_paren or skill_key).strip()
    no_version = re.sub(r"\b\d+\s*-\s*\d+\b", "", no_version).strip()
    no_version = re.sub(r"\s*-\s*$", "", no_version).strip()
    no_version = re.sub(r"\s+", " ", no_version)
    if no_version:
        variants.add(no_version)

    words = skill_key.split()
    if len(words) >= 2:
        # Vendor/product prefixes commonly seen in resume skill tokens.
        if words[0] in {"apache", "amazon"}:
            variants.add(" ".join(words[1:]))
        if words[0] == "aws":
            variants.add("aws")
            variants.add(" ".join(words[1:]))
    if skill_key.endswith(" ci"):
        variants.add(skill_key[:-3].strip())
    # Useful alias for common "Name version" forms (e.g., Java 17-21 -> Java)
    match = re.match(r"^([a-z][a-z0-9\+\#\-]*)\s+[\d\.\-x]+$", skill_key)
    if match:
        variants.add(match.group(1))
    return {variant for variant in variants if variant}


def _split_skill_tokens(value: Any) -> list[str]:
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

    if value is None:
        return []
    if isinstance(value, list):
        items: list[str] = []
        for entry in value:
            items.extend(_split_skill_tokens(entry))
        return items
    text = str(value)
    if "," in text:
        parts = _split_preserving_parentheses(text)
    else:
        parts = re.split(_SPLIT_PATTERN, text)
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
        "delivery_support": 25.0,
        "weak_frontend_penalty": -20.0,
        "weak_ml_penalty": -20.0,
    }


def _default_thresholds() -> dict[str, float]:
    return {
        "word_overlap_ratio": 0.5,
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


def _merged_thresholds(render_options: dict[str, Any] | None) -> dict[str, float]:
    thresholds = _default_thresholds()
    if not isinstance(render_options, dict):
        return thresholds
    raw = render_options.get("skills_relevance_thresholds")
    if not isinstance(raw, dict):
        return thresholds
    for key, value in raw.items():
        try:
            thresholds[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return thresholds


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


def _synonym_match(skill_keys: set[str], jd_text: str, groups: tuple[set[str], ...]) -> bool:
    for group in groups:
        if any(skill_key in group for skill_key in skill_keys) and any(_contains_phrase(jd_text, term) for term in group):
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
    thresholds = _merged_thresholds(render_options)
    catalog = _resolved_catalog(render_options)
    policy = _resolved_policy(render_options)
    synonym_groups = _compiled_synonym_groups(catalog, policy)
    rules = policy.get("rules", [])
    cues_cache: dict[str, bool] = {}

    scored: list[ScoredSkill] = []
    for item in items:
        reasons: list[str] = []
        score = 0.0
        variants = _skill_variants(item.token_key)

        if variants and any(_contains_phrase(jd_text, variant) for variant in variants):
            score += weights["exact_match"]
            reasons.append("exact_match")

        if variants and title_text and any(_contains_phrase(title_text, variant) for variant in variants):
            score += weights["title_match"]
            reasons.append("title_match")

        token_words = _tokenize_words(" ".join(variants))
        if token_words and jd_words:
            overlap = token_words & jd_words
            overlap_ratio = len(overlap) / len(token_words)
            if overlap_ratio >= thresholds["word_overlap_ratio"]:
                score += weights["word_overlap"] * overlap_ratio
                reasons.append("word_overlap")

        if _synonym_match(variants, jd_text, synonym_groups):
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
                    cues_cache[cue_ref] = any(_contains_phrase(jd_text, term) for term in cue_terms)
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
                if not any(variant in skill_terms for variant in variants):
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


def _default_family_caps() -> dict[str, int]:
    # Keep cloud provider sub-service lists from crowding out broader signals.
    return {"aws": 2}


def _resolved_family_caps(render_options: dict[str, Any] | None) -> dict[str, int]:
    caps = _default_family_caps()
    if not isinstance(render_options, dict):
        return caps
    raw = render_options.get("skills_family_caps")
    if not isinstance(raw, dict):
        return caps
    for key, value in raw.items():
        family = str(key).strip().lower()
        if not family:
            continue
        try:
            limit = int(value)
        except (TypeError, ValueError):
            continue
        if limit < 1:
            continue
        caps[family] = limit
    return caps


def _skill_family(item: SkillItem) -> str:
    key = item.token_key
    if key == "aws" or key.startswith("aws "):
        return "aws"
    if key == "azure" or key.startswith("azure "):
        return "azure"
    if key in {"gcp", "google cloud"} or key.startswith("gcp ") or key.startswith("google cloud "):
        return "gcp"
    return ""


def select_top_skills(
    scored: list[ScoredSkill],
    *,
    render_options: dict[str, Any] | None = None,
) -> tuple[list[SkillItem], dict[str, Any]]:
    """Select a capped set of top relevant skills."""

    options = render_options if isinstance(render_options, dict) else {}
    family_caps = _resolved_family_caps(options)
    target = _resolve_limit(options.get("skills_target_count"), DEFAULT_TARGET_SKILLS)
    maximum = _resolve_limit(options.get("skills_max_count"), DEFAULT_MAX_SKILLS)
    minimum = _resolve_limit(options.get("skills_min_count"), DEFAULT_MIN_SKILLS)

    if maximum < target:
        target = maximum
    if minimum > maximum:
        minimum = maximum

    strong = [entry for entry in scored if entry.score > 0]
    if len(strong) >= minimum:
        selected_count = min(target, len(strong), maximum)
        selected_ranked = list(strong[:selected_count])
    elif strong:
        selected_count = min(minimum, len(scored), maximum)
        selected_ranked = list(strong[:selected_count])
        selected_keys = {entry.item.token_key for entry in selected_ranked}
        if len(selected_ranked) < selected_count:
            for entry in scored:
                if entry.item.token_key in selected_keys:
                    continue
                selected_ranked.append(entry)
                selected_keys.add(entry.item.token_key)
                if len(selected_ranked) >= selected_count:
                    break
    else:
        selected_count = min(minimum, len(scored), maximum)
        selected_ranked = scored[:selected_count]
    selected_set = {entry.item.token_key for entry in selected_ranked}

    # Apply optional family caps (e.g., AWS sub-services) and refill from next best skills.
    kept_ranked: list[ScoredSkill] = []
    kept_keys: set[str] = set()
    family_counts: dict[str, int] = {}
    for entry in selected_ranked:
        family = _skill_family(entry.item)
        if family and family in family_caps:
            used = family_counts.get(family, 0)
            if used >= family_caps[family]:
                continue
            family_counts[family] = used + 1
        kept_ranked.append(entry)
        kept_keys.add(entry.item.token_key)

    if len(kept_ranked) < len(selected_ranked):
        for entry in scored:
            if entry.item.token_key in kept_keys:
                continue
            family = _skill_family(entry.item)
            if family and family in family_caps:
                used = family_counts.get(family, 0)
                if used >= family_caps[family]:
                    continue
                family_counts[family] = used + 1
            kept_ranked.append(entry)
            kept_keys.add(entry.item.token_key)
            if len(kept_ranked) >= len(selected_ranked):
                break
        selected_ranked = kept_ranked
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
        "retained_skills": [
            {
                "skill": entry.item.token,
                "score": entry.score,
                "reasons": list(entry.reasons),
            }
            for entry in selected_ranked
        ],
        "family_caps_applied": dict(family_caps),
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
