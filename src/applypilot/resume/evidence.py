from __future__ import annotations

from dataclasses import dataclass, field
import html
import re
from typing import Protocol

from applypilot.scoring.pdf_render_model import ResumeEntry, ResumeRenderModel


_GENERIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
    "you",
    "your",
    "we",
    "our",
    "will",
}

_REQUIREMENT_HINTS = {
    "required",
    "must",
    "responsible",
    "responsibilities",
    "requirements",
    "experience",
    "ability",
    "skills",
    "preferred",
    "expect",
    "needs",
}

_THEME_GENERIC_TERMS = {
    "experience",
    "preferred",
    "requirements",
    "required",
    "skills",
    "ability",
    "responsible",
    "responsibilities",
    "role",
    "team",
    "values",
    "mission",
    "culture",
    "definition",
}

_THEME_NOISE_TOKENS = {
    "s",
    "ll",
    "re",
    "ve",
    "d",
    "m",
    "t",
}

_THEME_BOILERPLATE_TERMS = {
    "benefits",
    "compensation",
    "salary",
    "time",
    "off",
    "base",
    "pay",
    "equity",
    "pto",
    "holiday",
    "holidays",
    "medical",
    "dental",
    "vision",
    "retirement",
    "insurance",
    "stipend",
    "stock",
    "spending",
    "wallets",
    "transparency",
    "equal",
    "employment",
    "opportunity",
    "eeo",
    "privacy",
    "policy",
    "accommodation",
    "accommodations",
    "veteran",
    "disability",
    "citizenship",
    "location",
    "office",
    "offices",
    "bonus",
    "healthcare",
    "hiring",
    "entities",
    "guidelines",
    "statement",
    "statements",
    "apply",
    "teammates",
    "labor",
    "local",
    "country",
    "region",
}

_THEME_BOILERPLATE_PHRASES = {
    "about us",
    "who we are",
    "equal employment",
    "pay transparency",
    "privacy policy",
    "salary range",
    "base pay",
    "time off",
    "flexible spending",
    "passionate about",
    "this role",
    "all affirm",
    "based spain",
    "equal employment opportunity",
}

_THEME_CONNECTOR_TERMS = {
    "this",
    "that",
    "these",
    "those",
    "through",
    "about",
    "across",
    "around",
    "within",
    "including",
    "using",
    "via",
    "all",
    "any",
    "other",
    "more",
    "most",
    "such",
    "passionate",
    "based",
}

_THEME_BOUNDARY_WEAK_TERMS = _GENERIC_STOPWORDS | _THEME_CONNECTOR_TERMS | _THEME_GENERIC_TERMS | {
    "work",
    "works",
    "working",
    "company",
    "organizations",
    "organization",
}

_THEME_SIGNAL_TERMS = {
    # Cross-profession responsibility/domain signals.
    "ownership",
    "reliability",
    "resilience",
    "automation",
    "deployment",
    "ci/cd",
    "pipeline",
    "pipelines",
    "platform",
    "infrastructure",
    "cloud",
    "backend",
    "distributed",
    "compute",
    "scalability",
    "tooling",
    "on-call",
    "compliance",
    "audit",
    "reconciliation",
    "reporting",
    "financial",
    "month-end",
    "close",
    "accounts",
    "payable",
    "receivable",
    "case",
    "management",
    "advocacy",
    "client",
    "crisis",
    "intervention",
    "community",
    "resources",
    "care",
    "coordination",
    "patient",
    "appointment",
    "scheduling",
    "coordinator",
    "education",
    "classroom",
    "curriculum",
    "assessment",
    "operations",
    "operational",
    "logistics",
    "safety",
    "quality",
    "governance",
    "support",
    "service",
    "services",
    "workflow",
    "workflows",
    "regulated",
    "measurable",
    "improvement",
    "improvements",
    "multi-site",
    "product",
    "engineering",
}

_THEME_QUALIFIER_TERMS = {
    "improve",
    "improved",
    "improving",
    "improvements",
    "lead",
    "build",
    "built",
    "support",
    "supports",
    "supporting",
    "deliver",
    "delivers",
    "delivering",
    "work",
    "works",
    "working",
    "partner",
    "partners",
    "own",
    "prepare",
    "provide",
    "resolve",
    "ownership",
    "outcomes",
}

_THEME_WEAK_HEAD_TERMS = {
    "account",
    "distributed",
    "operational",
    "improvements",
    "packages",
    "support",
    "families",
    "referrals",
    "agency",
    "plans",
    "operations",
    "multiple",
    "entities",
    "client",
    "care",
    "community",
    "crisis",
    "procurement",
}

_THEME_WEAK_LEAD_TERMS = {
    "families",
    "referrals",
    "management",
    "intervention",
    "preparation",
    "payable",
}

_THEME_HEAD_ACTIVITY_TERMS = {
    "automation",
    "reporting",
    "management",
    "advocacy",
    "intervention",
    "coordination",
    "reliability",
    "scalability",
    "preparation",
    "reconciliation",
    "engineering",
    "tooling",
    "rotation",
    "controls",
    "resources",
    "systems",
    "infrastructure",
    "platform",
    "compliance",
}

_THEME_DOMAIN_MODIFIER_TERMS = {
    "client",
    "case",
    "financial",
    "account",
    "accounts",
    "audit",
    "care",
    "community",
    "cloud",
    "service",
    "compute",
    "backend",
    "distributed",
    "deployment",
    "ci/cd",
    "on-call",
    "month-end",
    "procurement",
}

_GENERIC_CLAIM_TERMS = {
    "architecture",
    "development",
    "coordination",
    "management",
    "operations",
    "operation",
    "process",
    "processes",
    "service",
    "services",
    "system",
    "systems",
    "workflow",
    "workflows",
    "care",
    "reporting",
}

_GENERIC_CONTEXT_TERMS = {
    "system",
    "systems",
    "workflow",
    "workflows",
    "process",
    "processes",
    "platform",
    "service",
    "services",
    "program",
    "team",
    "teams",
    "care",
    "reporting",
    "operations",
    "integration",
}

_DISTINCTIVE_GENERIC_TOKENS = {
    "apache",
    "aws",
    "azure",
    "gcp",
    "actions",
    "ci",
    "cd",
    "api",
    "apis",
    "cloud",
    "platform",
    "system",
    "systems",
    "service",
    "services",
    "architecture",
    "development",
    "testing",
    "workflow",
    "workflows",
    "management",
    "tools",
    "tooling",
    "delivery",
    "automation",
    "integration",
    "process",
    "practices",
}

_OUTCOME_TERMS = {
    "reduced",
    "improved",
    "increased",
    "accelerated",
    "automated",
    "streamlined",
    "eliminated",
    "lowered",
    "raised",
    "delivered",
    "enabled",
    "saved",
    "grew",
    "decreased",
    "stabilized",
    "standardized",
}

_SCALE_TERMS = {
    "enterprise",
    "high-volume",
    "high",
    "volume",
    "multi-site",
    "multi",
    "site",
    "cross-functional",
    "cross",
    "functional",
    "national",
    "global",
    "production-critical",
    "production",
    "critical",
    "regulated",
    "large-scale",
    "large",
    "scale",
    "customers",
    "users",
    "patients",
    "students",
    "accounts",
    "records",
    "orders",
    "team",
    "teams",
}


@dataclass
class JobTheme:
    id: str
    label: str
    description: str
    importance: float
    source_terms: list[str]


@dataclass
class EvidenceItem:
    id: str
    source_type: str
    source_label: str
    source_path: str
    text: str
    is_retained_in_rendered_resume: bool
    matched_visible_claims: list[str]
    metric_signals: list[str]
    scale_signals: list[str]
    outcome_signals: list[str]
    evidence_score: float
    reason_not_rendered: str | None = None


@dataclass
class ThemeEvidenceMatch:
    theme_id: str
    evidence_id: str
    match_score: float
    match_method: str


@dataclass
class ClaimCoverage:
    claim: str
    claim_type: str
    is_visible: bool
    supporting_evidence_count: int
    retained_supporting_evidence_count: int
    primary_supporting_evidence_count: int
    retained_primary_supporting_evidence_count: int
    secondary_supporting_evidence_count: int
    coverage_status: str
    top_supporting_evidence: list[str]
    normalized_variants: list[str] = field(default_factory=list)
    distinctive_tokens_required: list[str] = field(default_factory=list)
    distinctive_tokens_matched: list[str] = field(default_factory=list)
    support_match_methods: list[str] = field(default_factory=list)
    supporting_evidence_match_reasons: list[dict[str, str]] = field(default_factory=list)


class SimilarityProvider(Protocol):
    def similarity(self, a: str, b: str) -> float:
        ...


class TokenOverlapSimilarityProvider:
    def similarity(self, a: str, b: str) -> float:
        at = set(_normalize_tokens(a))
        bt = set(_normalize_tokens(b))
        if not at or not bt:
            return 0.0
        inter = len(at & bt)
        union = len(at | bt)
        if union == 0:
            return 0.0
        return inter / union


class SkillAliasProvider:
    """Isolated alias expansion for common claim/evidence equivalences."""

    _ALIASES: dict[str, set[str]] = {
        "apache kafka": {"kafka"},
        "kafka": {"apache kafka"},
        "jenkins ci": {"jenkins"},
        "jenkins": {"jenkins ci"},
        "gitlab ci": {"gitlab"},
        "gitlab": {"gitlab ci"},
        "github actions": {"actions"},
        "aws ec2": {"ec2"},
        "ec2": {"aws ec2"},
        "aws s3": {"s3"},
        "s3": {"aws s3"},
        "tdd": {"test driven development"},
        "test driven development": {"tdd"},
        "e2e": {"end to end"},
        "end to end": {"e2e"},
        "ci/cd": {"continuous integration continuous delivery", "continuous integration", "continuous delivery"},
        "continuous integration continuous delivery": {"ci/cd"},
        "ap": {"accounts payable"},
        "accounts payable": {"ap"},
        "ar": {"accounts receivable"},
        "accounts receivable": {"ar"},
        "crm": {"customer relationship management"},
        "customer relationship management": {"crm"},
    }

    def expand(self, phrase: str) -> set[str]:
        key = " ".join(phrase.lower().split())
        return set(self._ALIASES.get(key, set()))


def _normalize_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9\+\#\.\-/]{2,}", text.lower())

    def _stem(token: str) -> str:
        if len(token) > 7 and token.endswith("ation"):
            return token[:-5]
        if len(token) > 5 and token.endswith("ing"):
            return token[:-3]
        if len(token) > 4 and token.endswith("ed"):
            return token[:-2]
        if len(token) > 4 and token.endswith("es"):
            return token[:-2]
        return token

    return [_stem(tok) for tok in tokens if tok not in _GENERIC_STOPWORDS]


def normalize_phrase_for_matching(text: str) -> str:
    cleaned = text.strip().lower()
    cleaned = cleaned.replace("-", " ")
    cleaned = cleaned.replace("/", " ")
    cleaned = re.sub(r"[^\w\s\+\#\.]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _split_sentences(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = re.split(r"(?<=[\.\!\?;])\s+|^\-\s*", raw)
        lines.extend(part.strip(" -\t") for part in parts if part.strip(" -\t"))
    return lines


def clean_job_description_text(text: str) -> str:
    if not text:
        return ""
    cleaned = html.unescape(text)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # Remove escaped/orphan tag fragments like "lt strong gt" or "lt /li gt".
    cleaned = re.sub(r"\blt\s+/?(?:strong|li|p|ul|ol|div|span|br)\s+gt\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\blt\s+/?\w+\s+gt\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?<!\w)/(?:strong|li|p|ul|ol|div|span|br)(?!\w)", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:lt|gt|li|p|ul|ol|div|span|br)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _canonicalize_theme_label(label: str, job_description: str) -> str:
    tokens = [tok for tok in re.findall(r"[a-z0-9][a-z0-9\-/\+]*", str(label).lower()) if tok]
    if len(tokens) != 2:
        return " ".join(tokens).strip()

    left, right = tokens[0], tokens[1]
    original = f"{left} {right}"
    flipped = f"{right} {left}"

    jd_norm = normalize_phrase_for_matching(job_description)
    original_norm = normalize_phrase_for_matching(original)
    flipped_norm = normalize_phrase_for_matching(flipped)

    def _contains_phrase(text: str, phrase: str) -> bool:
        if not text or not phrase:
            return False
        pattern = r"\s+".join(re.escape(part) for part in phrase.split())
        return bool(re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text))

    original_in_jd = _contains_phrase(jd_norm, original_norm)
    flipped_in_jd = _contains_phrase(jd_norm, flipped_norm)
    if original_in_jd and not flipped_in_jd:
        return original
    if flipped_in_jd and not original_in_jd:
        return flipped

    def _looks_domain_modifier(token: str) -> bool:
        return (
            token in _THEME_DOMAIN_MODIFIER_TERMS
            or "/" in token
            or "-" in token
            or (len(token) <= 4 and token.isalpha())
        )

    left_is_head = left in _THEME_HEAD_ACTIVITY_TERMS
    right_is_head = right in _THEME_HEAD_ACTIVITY_TERMS
    right_is_domain = _looks_domain_modifier(right)
    left_is_domain = _looks_domain_modifier(left)

    if left_is_head and right_is_domain and not right_is_head:
        return flipped
    if right_is_head and left_is_domain:
        return original
    return original


def derive_job_themes(job_description: str, *, max_themes: int = 8) -> list[JobTheme]:
    cleaned_jd = clean_job_description_text(job_description)
    sentences = _split_sentences(cleaned_jd)
    if not sentences:
        return []

    phrase_scores: dict[str, float] = {}
    phrase_terms: dict[str, set[str]] = {}
    phrase_labels: dict[str, str] = {}

    def _token_is_weak_boundary(token: str) -> bool:
        return token in _THEME_BOUNDARY_WEAK_TERMS or token in _THEME_BOILERPLATE_TERMS

    def _has_meaningful_signal(gram: list[str]) -> tuple[int, int]:
        signal_hits = sum(1 for token in gram if token in _THEME_SIGNAL_TERMS)
        non_weak_hits = sum(
            1
            for token in gram
            if token not in _THEME_BOUNDARY_WEAK_TERMS
            and token not in _THEME_BOILERPLATE_TERMS
            and token not in _THEME_NOISE_TOKENS
        )
        return signal_hits, non_weak_hits

    def _compact_label_tokens(tokens: list[str]) -> list[str]:
        if len(tokens) < 2:
            return []
        candidates: list[tuple[float, int, int, list[str]]] = []
        upper = min(2, len(tokens))
        for length in (2,):
            if length > upper:
                continue
            for start in range(0, len(tokens) - length + 1):
                window = tokens[start : start + length]
                if _token_is_weak_boundary(window[0]) or _token_is_weak_boundary(window[-1]):
                    continue
                if window[0] in _THEME_WEAK_LEAD_TERMS:
                    continue
                if any(token in _THEME_QUALIFIER_TERMS for token in window):
                    # Keep qualifiers out of compact labels to avoid sliding chains like
                    # "pipeline improvements on-call" and "packages support audit".
                    continue
                if window[-1] in _THEME_WEAK_HEAD_TERMS:
                    continue
                signal_hits, non_weak_hits = _has_meaningful_signal(window)
                if signal_hits == 0 or non_weak_hits < 2:
                    continue
                connector_hits = sum(1 for token in window if token in _THEME_CONNECTOR_TERMS)
                boilerplate_hits = sum(1 for token in window if token in _THEME_BOILERPLATE_TERMS)
                score = (
                    (signal_hits * 3.0)
                    + (non_weak_hits * 1.15)
                    - (connector_hits * 2.0)
                    - (boilerplate_hits * 3.0)
                    - (abs(length - 2) * 1.2)
                )
                candidates.append((score, length, start, window))
        if not candidates:
            return []
        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        return list(candidates[0][3])

    for idx, sentence in enumerate(sentences):
        tokens = [token.strip(".,;:()") for token in re.findall(r"[a-z0-9][a-z0-9\-/\+\.]*", sentence.lower())]
        tokens = [tok for tok in tokens if tok not in _GENERIC_STOPWORDS]
        if not tokens:
            continue
        boost = 1.0
        if any(hint in tokens for hint in _REQUIREMENT_HINTS):
            boost += 0.6
        if idx < 5:
            boost += 0.2

        # 2-gram through 4-gram phrases are theme-like planning signals.
        for n in (4, 3, 2):
            for i in range(0, max(0, len(tokens) - n + 1)):
                gram = tokens[i : i + n]
                if len(set(gram)) == 1:
                    continue
                if any(token in _THEME_NOISE_TOKENS or (len(token) == 1 and token.isalpha()) for token in gram):
                    continue
                if _token_is_weak_boundary(gram[0]) or _token_is_weak_boundary(gram[-1]):
                    continue
                phrase = " ".join(gram)
                generic_ratio = sum(1 for token in gram if token in _THEME_GENERIC_TERMS) / max(1, len(gram))
                if generic_ratio >= 0.67:
                    continue
                connector_ratio = sum(1 for token in gram if token in _THEME_CONNECTOR_TERMS) / max(1, len(gram))
                if connector_ratio >= 0.5:
                    continue
                boilerplate_token_ratio = sum(1 for token in gram if token in _THEME_BOILERPLATE_TERMS) / max(1, len(gram))
                if boilerplate_token_ratio >= 0.34:
                    continue
                if any(noise_phrase in phrase for noise_phrase in _THEME_BOILERPLATE_PHRASES):
                    continue
                signal_hits, non_weak_hits = _has_meaningful_signal(gram)
                if signal_hits == 0:
                    continue
                if non_weak_hits < 2:
                    continue
                weighted_boost = boost + (signal_hits * 0.45) + (0.08 * n)
                phrase_scores[phrase] = phrase_scores.get(phrase, 0.0) + weighted_boost
                phrase_terms.setdefault(phrase, set()).update(gram)
                phrase_labels.setdefault(phrase, " ".join(gram))

    ranked = sorted(phrase_scores.items(), key=lambda item: item[1], reverse=True)
    themes: list[JobTheme] = []
    used_terms: list[set[str]] = []
    seen_labels: set[str] = set()
    for phrase, score in ranked:
        terms = phrase_terms.get(phrase, set())
        if not terms:
            continue
        raw_label = phrase_labels.get(phrase, phrase).strip()
        raw_tokens = [tok for tok in re.findall(r"[a-z0-9][a-z0-9\-/\+\.]*", raw_label.lower()) if tok]
        label_tokens = _compact_label_tokens(raw_tokens)
        if not label_tokens:
            continue
        label = " ".join(label_tokens).strip()
        label = _canonicalize_theme_label(label, cleaned_jd)
        label_tokens = [tok for tok in re.findall(r"[a-z0-9][a-z0-9\-/\+\.]*", label.lower()) if tok]
        if not label_tokens:
            continue
        if any(noise_phrase in label for noise_phrase in _THEME_BOILERPLATE_PHRASES):
            continue
        label_key = " ".join(label.split())
        if label_key in seen_labels:
            continue
        if (sum(1 for token in label_tokens if token in _THEME_BOILERPLATE_TERMS) / max(1, len(label_tokens))) >= 0.34:
            continue
        compact_terms = set(label_tokens)
        # Keep dynamic themes distinct.
        # Reject overlap-chain labels unless they introduce genuinely new signal content.
        overlap_rejected = False
        for existing in used_terms:
            shared = compact_terms & existing
            overlap_ratio = len(shared) / max(1, len(compact_terms | existing))
            if len(shared) >= 2 or overlap_ratio > 0.5:
                new_signal = {
                    token for token in compact_terms - existing if token in _THEME_SIGNAL_TERMS
                }
                if not new_signal:
                    overlap_rejected = True
                    break
        if overlap_rejected:
            continue
        used_terms.append(compact_terms)
        seen_labels.add(label_key)
        idx = len(themes) + 1
        themes.append(
            JobTheme(
                id=f"theme_{idx}",
                label=label,
                description=f"Derived from recurring job-description language around '{label}'.",
                importance=round(min(1.0, score / max(1.0, ranked[0][1])), 3),
                source_terms=sorted(compact_terms),
            )
        )
        if len(themes) >= max_themes:
            break
    return themes


def detect_metric_signals(text: str) -> list[str]:
    patterns = [
        r"\b\d+(?:\.\d+)?%\b",
        r"[$€£]\s?\d[\d,]*(?:\.\d+)?",
        r"\b\d[\d,]*(?:\.\d+)?\s*(?:hours?|days?|weeks?|months?|years?)\b",
        r"\b\d[\d,]*(?:\.\d+)?\b",
    ]
    signals: list[str] = []
    for pattern in patterns:
        signals.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    # dedupe while preserving order
    out: list[str] = []
    seen: set[str] = set()
    for signal in signals:
        low = signal.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(signal)
    return out


def detect_scale_signals(text: str) -> list[str]:
    low = text.lower()
    found: list[str] = []
    for term in sorted(_SCALE_TERMS):
        if term in low:
            found.append(term)
    return found


def detect_outcome_signals(text: str) -> list[str]:
    low = text.lower()
    found: list[str] = []
    for term in sorted(_OUTCOME_TERMS):
        if term in low:
            found.append(term)
    return found


def _split_skill_tokens_preserving_parentheses(text: str) -> list[str]:
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


def extract_all_skill_claims(model: ResumeRenderModel) -> list[str]:
    """Flatten all selected skill claims in deterministic visual order."""

    tokens: list[str] = []
    seen: set[str] = set()
    for section in model.skills:
        parts = _split_skill_tokens_preserving_parentheses(str(section.value))
        for part in parts:
            claim = part.strip().strip(";")
            if not claim:
                continue
            key = claim.lower()
            if key in seen:
                continue
            seen.add(key)
            tokens.append(claim)
    return tokens


def extract_visible_skill_claims(model: ResumeRenderModel, prepared: object) -> list[str]:
    """Return currently visible skill claims for the prepared template view."""

    skills_mode = str(getattr(prepared, "skills_mode", "full"))
    selected_skills_max_lines = int(getattr(prepared, "selected_skills_max_lines", 2) or 2)
    return _flatten_skill_tokens(
        model,
        skills_mode=skills_mode,
        selected_skills_max_lines=selected_skills_max_lines,
    )


def _flatten_skill_tokens(model: ResumeRenderModel, *, skills_mode: str, selected_skills_max_lines: int) -> list[str]:
    tokens = extract_all_skill_claims(model)
    if not tokens:
        return []

    # Mirror template chunking: 6 tokens per visual line.
    lines: list[list[str]] = []
    chunk_size = 6
    for idx in range(0, len(tokens), chunk_size):
        lines.append(tokens[idx : idx + chunk_size])

    if skills_mode == "minimal":
        lines = lines[:1]
    elif skills_mode == "selected":
        lines = lines[: max(1, selected_skills_max_lines)]
    return [token for line in lines for token in line]


def _normalize_claim_fragment(text: str) -> str:
    normalized = " ".join(text.strip().split())
    normalized = re.sub(r"\s+", " ", normalized)
    # Trim trailing versions/ranges: "17-21", "3.x", "3.11", "v2", "2024".
    normalized = re.sub(
        r"\s+(?:(?:\d+\s*-\s*\d+)|(?:\d+\.x)|(?:v?\d+(?:\.\d+)*(?:\.[a-z])?))\b",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\s*[-/]\s*$", "", normalized)
    return normalized.strip(" ,;:.")


def _phrase_tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9\+\#]{2,}", text.lower()) if token not in _GENERIC_STOPWORDS]


def claim_distinctive_tokens(claim: str) -> list[str]:
    normalized = normalize_phrase_for_matching(_normalize_claim_fragment(claim))
    if not normalized:
        return []
    tokens = [token for token in _phrase_tokens(normalized) if token]
    if not tokens:
        return []
    if len(tokens) == 1:
        # Distinctive-token gating is mainly for compound claims.
        return []
    distinctive = [token for token in tokens if token not in _DISTINCTIVE_GENERIC_TOKENS]
    return sorted(dict.fromkeys(distinctive))


def _distinctive_tokens_matched(claim: str, evidence_text: str) -> list[str]:
    required = claim_distinctive_tokens(claim)
    if not required:
        return []
    evidence_tokens = set(_phrase_tokens(normalize_phrase_for_matching(evidence_text)))
    matched = [token for token in required if token in evidence_tokens]
    return sorted(dict.fromkeys(matched))


def _claim_has_required_distinctive_match(claim: str, evidence_text: str) -> bool:
    required = claim_distinctive_tokens(claim)
    if not required:
        # Claims like CI/CD are inherently generic and can be supported by generic CI/CD evidence.
        return True
    return bool(_distinctive_tokens_matched(claim, evidence_text))


def _concept_support_match_reason(claim: str, evidence_text: str) -> str | None:
    claim_key = normalize_phrase_for_matching(_normalize_claim_fragment(claim))
    evidence_norm = normalize_phrase_for_matching(evidence_text)
    evidence_tokens = set(_phrase_tokens(evidence_norm))
    if claim_key == "distributed systems":
        if "distributed" not in evidence_tokens:
            return None
        context_terms = {
            "services",
            "systems",
            "microservices",
            "transactional",
            "workflows",
            "workflow",
            "messaging",
            "queues",
            "pipelines",
            "apis",
            "orchestration",
            "kafka",
            "event",
            "events",
            "driven",
        }
        if evidence_tokens & context_terms:
            return "concept_support_distributed_systems_context"
        return None
    return None


def claim_supports_distinctive_tokens(claim: str, evidence_text: str) -> bool:
    """Public helper to determine if evidence text satisfies claim distinctiveness requirements."""

    return _claim_has_required_distinctive_match(claim, evidence_text)


def claim_variants(claim: str, *, alias_provider: SkillAliasProvider | None = None) -> list[str]:
    alias_provider = alias_provider or SkillAliasProvider()
    original = " ".join(claim.strip().split())
    if not original:
        return []
    variants: list[str] = [original.strip(" ,;:.")]
    normalized = _normalize_claim_fragment(original)
    if normalized and normalized.lower() not in {v.lower() for v in variants}:
        variants.append(normalized)
    phrase_normalized = normalize_phrase_for_matching(normalized or original)
    if phrase_normalized and phrase_normalized.lower() not in {v.lower() for v in variants}:
        variants.append(phrase_normalized)

    # Parenthetical decomposition: "AWS (EC2, S3)" -> ["AWS", "EC2", "S3", ...]
    for match in re.finditer(r"\(([^)]+)\)", original):
        inside = match.group(1)
        parts = [
            part.strip().strip("() ,;:.")
            for part in re.split(r",|;|\s+/\s+", inside)
            if part.strip()
        ]
        for part in parts:
            norm = _normalize_claim_fragment(part)
            if norm and norm.lower() not in {v.lower() for v in variants}:
                variants.append(norm)
    base = re.sub(r"\([^)]*\)", "", original).strip(" ,;:.")
    base_norm = _normalize_claim_fragment(base)
    if base_norm and base_norm.lower() not in {v.lower() for v in variants}:
        variants.append(base_norm)
    base_phrase_norm = normalize_phrase_for_matching(base_norm or base)
    if base_phrase_norm and base_phrase_norm.lower() not in {v.lower() for v in variants}:
        variants.append(base_phrase_norm)
    # Slash-separated sub-claims for generic grouped claims.
    # Preserve slash phrases with trailing terms (e.g., "CI/CD Automation",
    # "A/B Testing", "client/server architecture") as single claims.
    for item in list(variants):
        raw_item = str(item).strip()
        if " " in raw_item and " / " not in raw_item:
            continue
        for sub in re.split(r"\s*/\s*", item):
            sub_norm = _normalize_claim_fragment(sub)
            if sub_norm and sub_norm.lower() not in {v.lower() for v in variants}:
                variants.append(sub_norm)
            sub_phrase = normalize_phrase_for_matching(sub_norm or sub)
            if sub_phrase and sub_phrase.lower() not in {v.lower() for v in variants}:
                variants.append(sub_phrase)
            if len(sub_phrase) >= 2 and " " not in sub_phrase and len(sub_phrase) <= 4:
                # Keep short acronym-like terms (e.g., CI, CD, AP, AR), skip one-letter noise.
                variants.append(sub_phrase.upper())
    # Alias expansion
    for item in list(variants):
        for alias in alias_provider.expand(item):
            alias_norm = _normalize_claim_fragment(alias)
            if alias_norm and alias_norm.lower() not in {v.lower() for v in variants}:
                variants.append(alias_norm)
            alias_phrase = normalize_phrase_for_matching(alias_norm or alias)
            if alias_phrase and alias_phrase.lower() not in {v.lower() for v in variants}:
                variants.append(alias_phrase)
    # Compound phrase fallback: preserve the strongest two-token stem for context matching.
    tokenized = _normalize_tokens(normalized or original)
    if len(tokenized) >= 2:
        lead = " ".join(tokenized[:2])
        if lead and lead.lower() not in {v.lower() for v in variants}:
            variants.append(lead)
    # Remove malformed fragments.
    cleaned: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        v = variant.strip().strip("()")
        if not v or "(" in v or ")" in v:
            continue
        if len(v) == 1:
            continue
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(v)
    return cleaned


def _evidence_text_variants(text: str) -> list[str]:
    base = text.strip()
    if not base:
        return []
    variants = [base]
    norm = normalize_phrase_for_matching(base)
    if norm and norm.lower() not in {v.lower() for v in variants}:
        variants.append(norm)
    return variants


def _compound_claim_match_score(variant: str, evidence_text: str, similarity: SimilarityProvider) -> float:
    claim_tokens = _normalize_tokens(variant)
    if not claim_tokens:
        return 0.0
    evidence_tokens = set(_normalize_tokens(evidence_text))
    if not evidence_tokens:
        return 0.0

    shared = set(claim_tokens) & evidence_tokens
    base_score = similarity.similarity(variant, evidence_text)

    distinctive = [token for token in claim_tokens if token not in _GENERIC_CLAIM_TERMS]
    distinctive_matches = [token for token in distinctive if token in evidence_tokens]
    context_matches = [token for token in _GENERIC_CONTEXT_TERMS if token in evidence_tokens]

    bonus = 0.0
    if len(claim_tokens) >= 2:
        if len(distinctive_matches) >= 2:
            bonus = 0.35
        elif len(distinctive_matches) >= 1 and (len(shared) >= 2 or bool(context_matches)):
            bonus = 0.22
    elif len(distinctive_matches) >= 1:
        bonus = 0.1
    return base_score + bonus


def extract_evidence_items(model: ResumeRenderModel, prepared: object) -> list[EvidenceItem]:
    detailed_entries = list(getattr(prepared, "detailed_experience", model.experience))
    compact_entries = list(getattr(prepared, "compact_experience", []))
    projects_mode = str(getattr(prepared, "projects_mode", "full"))
    projects_to_render = list(getattr(prepared, "projects_to_render", model.projects))
    experience_mode = str(getattr(prepared, "experience_mode", "detailed"))
    earlier_mode = str(getattr(prepared, "earlier_experience_mode", "compact"))
    detailed_bullet_cap = getattr(prepared, "detailed_bullet_cap", None)
    bullet_cap = detailed_bullet_cap if isinstance(detailed_bullet_cap, int) and detailed_bullet_cap > 0 else None

    rendered_entry_ids: set[int] = set()
    detailed_index_by_entry_id: dict[int, int] = {}
    compact_index_by_entry_id: dict[int, int] = {}
    if experience_mode != "hidden":
        for idx, entry in enumerate(detailed_entries):
            rendered_entry_ids.add(id(entry))
            detailed_index_by_entry_id[id(entry)] = idx
        if earlier_mode in {"compact", "earlier_one_line", "grouped"}:
            for idx, entry in enumerate(compact_entries):
                rendered_entry_ids.add(id(entry))
                compact_index_by_entry_id[id(entry)] = idx

    rendered_project_ids: set[int] = set()
    if projects_mode != "hidden":
        if projects_mode == "selected":
            rendered_project_ids.update(id(entry) for entry in projects_to_render[:2])
        else:
            rendered_project_ids.update(id(entry) for entry in projects_to_render)

    items: list[EvidenceItem] = []

    def _add_item(
        *,
        source_type: str,
        source_label: str,
        source_path: str,
        text: str,
        retained: bool,
        reason_not_rendered: str | None = None,
    ) -> None:
        stripped = text.strip()
        if not stripped:
            return
        metric = detect_metric_signals(stripped)
        scale = detect_scale_signals(stripped)
        outcome = detect_outcome_signals(stripped)
        evidence_score = min(1.0, 0.15 + 0.15 * len(metric) + 0.2 * len(scale) + 0.25 * len(outcome))
        items.append(
            EvidenceItem(
                id=f"e{len(items) + 1}",
                source_type=source_type,
                source_label=source_label,
                source_path=source_path,
                text=stripped,
                is_retained_in_rendered_resume=retained,
                matched_visible_claims=[],
                metric_signals=metric,
                scale_signals=scale,
                outcome_signals=outcome,
                evidence_score=round(evidence_score, 3),
                reason_not_rendered=reason_not_rendered,
            )
        )

    for idx, entry in enumerate(model.experience):
        label = entry.company or entry.title or f"Experience {idx + 1}"
        retained = id(entry) in rendered_entry_ids
        is_detailed = id(entry) in detailed_index_by_entry_id
        is_compact = id(entry) in compact_index_by_entry_id

        compact_summary_rendered = False
        if retained and is_compact:
            compact_summary_rendered = earlier_mode in {"compact", "grouped"} and bool(entry.compact_summary.strip())

        compact_bullets_rendered_count = 0
        if retained and is_compact:
            if earlier_mode == "compact" and not entry.compact_summary.strip():
                compact_bullets_rendered_count = min(2, len(entry.bullets))
            elif earlier_mode == "grouped" and not entry.compact_summary.strip():
                compact_bullets_rendered_count = 1 if entry.bullets else 0

        detailed_bullets_limit: int | None = None
        if retained and is_detailed:
            detailed_idx = detailed_index_by_entry_id[id(entry)]
            if experience_mode == "detailed":
                if detailed_idx > 0 and bullet_cap is not None:
                    detailed_bullets_limit = bullet_cap
            elif experience_mode == "medium":
                medium_cap = 2
                if detailed_idx > 0 and bullet_cap is not None:
                    medium_cap = min(medium_cap, bullet_cap)
                detailed_bullets_limit = medium_cap
            else:
                detailed_bullets_limit = 0

        def _reason_for_hidden_experience_item(*, bullet_idx: int | None = None, is_compact_summary: bool = False) -> str:
            if not retained:
                return "role_collapsed"
            if is_detailed:
                if detailed_bullets_limit is None:
                    return "unknown"
                if detailed_bullets_limit == 0:
                    return "role_collapsed"
                if bullet_idx is not None and bullet_idx >= detailed_bullets_limit:
                    return "bullet_trimmed"
                return "unknown"
            if is_compact:
                if earlier_mode == "grouped":
                    if is_compact_summary or (bullet_idx is not None and bullet_idx == 0 and not entry.compact_summary.strip()):
                        return "unknown"
                    return "earlier_grouped"
                if earlier_mode == "earlier_one_line":
                    return "role_collapsed"
                if earlier_mode == "compact":
                    if is_compact_summary and entry.compact_summary.strip():
                        return "unknown"
                    if bullet_idx is not None and bullet_idx < compact_bullets_rendered_count and not entry.compact_summary.strip():
                        return "unknown"
                    if bullet_idx is not None and bullet_idx >= compact_bullets_rendered_count:
                        return "bullet_trimmed"
                    return "unknown"
            return "unknown"

        if entry.compact_summary.strip():
            _add_item(
                source_type="experience_compact_summary",
                source_label=label,
                source_path=f"experience[{idx}].compact_summary",
                text=entry.compact_summary,
                retained=compact_summary_rendered,
                reason_not_rendered=None if compact_summary_rendered else _reason_for_hidden_experience_item(is_compact_summary=True),
            )
        for bidx, bullet in enumerate(entry.bullets):
            bullet_retained = False
            if retained and is_detailed:
                if detailed_bullets_limit is None:
                    bullet_retained = True
                else:
                    bullet_retained = bidx < detailed_bullets_limit
            elif retained and is_compact:
                bullet_retained = bidx < compact_bullets_rendered_count
            _add_item(
                source_type="experience_bullet",
                source_label=label,
                source_path=f"experience[{idx}].bullets[{bidx}]",
                text=bullet,
                retained=bullet_retained,
                reason_not_rendered=None if bullet_retained else _reason_for_hidden_experience_item(bullet_idx=bidx),
            )

    for idx, entry in enumerate(model.projects):
        label = entry.title or f"Project {idx + 1}"
        retained = id(entry) in rendered_project_ids
        if projects_mode == "hidden":
            reason = "hidden_project"
        elif projects_mode == "selected" and not retained:
            reason = "not_selected_by_bullet_cap"
        elif projects_mode == "compact":
            reason = "bullet_trimmed"
        else:
            reason = "unknown"
        if entry.compact_summary.strip():
            _add_item(
                source_type="project_compact_summary",
                source_label=label,
                source_path=f"projects[{idx}].compact_summary",
                text=entry.compact_summary,
                retained=retained and projects_mode == "compact",
                reason_not_rendered=None if (retained and projects_mode == "compact") else reason,
            )
        for bidx, bullet in enumerate(entry.bullets):
            _add_item(
                source_type="project_bullet",
                source_label=label,
                source_path=f"projects[{idx}].bullets[{bidx}]",
                text=bullet,
                retained=retained and projects_mode in {"full", "selected"},
                reason_not_rendered=None if (retained and projects_mode in {"full", "selected"}) else reason,
            )

    if model.summary.strip():
        _add_item(
            source_type="summary",
            source_label="Summary",
            source_path="summary",
            text=model.summary,
            retained=str(getattr(prepared, "summary_mode", "full")) != "hidden",
            reason_not_rendered="unknown",
        )

    return items


def _is_primary_evidence(item: EvidenceItem) -> bool:
    return item.source_type in {
        "experience_bullet",
        "experience_compact_summary",
        "project_bullet",
        "project_compact_summary",
    }


def _match_themes(
    themes: list[JobTheme],
    evidence_items: list[EvidenceItem],
    similarity: SimilarityProvider,
) -> list[ThemeEvidenceMatch]:
    matches: list[ThemeEvidenceMatch] = []
    for theme in themes:
        scored = []
        for evidence in evidence_items:
            score = similarity.similarity(theme.label, evidence.text)
            if score >= 0.12:
                scored.append((score, evidence.id))
        scored.sort(reverse=True)
        for score, evidence_id in scored[:4]:
            matches.append(
                ThemeEvidenceMatch(
                    theme_id=theme.id,
                    evidence_id=evidence_id,
                    match_score=round(score, 3),
                    match_method="token_overlap",
                )
            )
    return matches


def _build_claim_coverage(
    claims: list[str],
    evidence_items: list[EvidenceItem],
    similarity: SimilarityProvider,
) -> list[ClaimCoverage]:
    def _rank_tuple(claim: str, evidence: EvidenceItem) -> tuple[int, int, float, float]:
        score = max(similarity.similarity(claim, evidence.text), float(claim.lower() in evidence.text.lower()) * 0.2)
        primary = 1 if _is_primary_evidence(evidence) else 0
        retained = 1 if evidence.is_retained_in_rendered_resume else 0
        signal = float(len(evidence.metric_signals) + len(evidence.scale_signals) + len(evidence.outcome_signals))
        score_with_signal = score + min(0.2, signal * 0.05)
        return (primary, retained, score_with_signal, score)

    coverage: list[ClaimCoverage] = []
    alias_provider = SkillAliasProvider()
    for claim in claims:
        matched: list[EvidenceItem] = []
        match_reasons_by_evidence_id: dict[str, set[str]] = {}
        variants = claim_variants(claim, alias_provider=alias_provider)
        claim_key_normalized = normalize_phrase_for_matching(_normalize_claim_fragment(claim))
        required_distinctive = claim_distinctive_tokens(claim)
        matched_distinctive: set[str] = set()
        for evidence in evidence_items:
            evidence_variants = _evidence_text_variants(evidence.text)
            score = max(
                [
                    _compound_claim_match_score(variant, evidence_variant, similarity)
                    for variant in variants
                    for evidence_variant in evidence_variants
                ]
                + [0.0]
            )
            direct = any(
                variant.lower() in evidence_variant.lower()
                for variant in variants
                for evidence_variant in evidence_variants
                if variant
            )
            distinctive_ok = any(
                _claim_has_required_distinctive_match(claim, evidence_variant)
                for evidence_variant in evidence_variants
            )
            concept_reason = _concept_support_match_reason(claim, evidence.text)
            concept_ok = concept_reason is not None
            require_concept_support = claim_key_normalized == "distributed systems"
            base_match = (score >= 0.18 or direct) and distinctive_ok
            if (base_match and not require_concept_support) or concept_ok:
                matched.append(evidence)
                evidence.matched_visible_claims.append(claim)
                reasons = match_reasons_by_evidence_id.setdefault(evidence.id, set())
                if concept_reason:
                    reasons.add("concept_support")
                elif direct:
                    reasons.add("direct_phrase")
                else:
                    reasons.add("alias_or_similarity")
                for evidence_variant in evidence_variants:
                    matched_distinctive.update(_distinctive_tokens_matched(claim, evidence_variant))
        primary = [item for item in matched if _is_primary_evidence(item)]
        retained_primary = [item for item in primary if item.is_retained_in_rendered_resume]
        secondary = [item for item in matched if not _is_primary_evidence(item)]
        retained_count = sum(1 for item in matched if item.is_retained_in_rendered_resume)
        missing_required_distinctive = sorted(set(required_distinctive) - set(matched_distinctive))
        if retained_primary:
            status = "supported"
        elif primary:
            status = "weak"
        elif secondary:
            status = "weak_summary_only"
        else:
            status = "unsupported"
        # Compound claims with required distinctive sub-claims cannot be marked
        # fully supported until all required tokens are matched across evidence.
        if status == "supported" and missing_required_distinctive:
            status = "weak"
        ranked = sorted(matched, key=lambda item: _rank_tuple(claim, item), reverse=True)
        top = [f"{item.source_label}: {item.text[:140]}" for item in ranked[:3]]
        coverage.append(
            ClaimCoverage(
                claim=claim,
                claim_type="skill",
                is_visible=True,
                supporting_evidence_count=len(matched),
                retained_supporting_evidence_count=retained_count,
                primary_supporting_evidence_count=len(primary),
                retained_primary_supporting_evidence_count=len(retained_primary),
                secondary_supporting_evidence_count=len(secondary),
                coverage_status=status,
                top_supporting_evidence=top,
                normalized_variants=variants,
                distinctive_tokens_required=required_distinctive,
                distinctive_tokens_matched=sorted(matched_distinctive),
                support_match_methods=sorted(
                    {
                        reason
                        for evidence_id in match_reasons_by_evidence_id
                        for reason in match_reasons_by_evidence_id[evidence_id]
                    }
                ),
                supporting_evidence_match_reasons=[
                    {
                        "source_label": item.source_label,
                        "source_path": item.source_path,
                        "reason": ",".join(sorted(match_reasons_by_evidence_id.get(item.id, set()))),
                        "text": item.text[:180],
                    }
                    for item in ranked[:3]
                ],
            )
        )
    return coverage


def build_claim_coverage_for_claims(
    *,
    claims: list[str],
    model: ResumeRenderModel,
    prepared: object,
    similarity_provider: SimilarityProvider | None = None,
) -> list[ClaimCoverage]:
    """Build claim coverage details for an explicit claim list."""

    similarity = similarity_provider or TokenOverlapSimilarityProvider()
    evidence_items = extract_evidence_items(model, prepared)
    return _build_claim_coverage(claims, evidence_items, similarity)


def build_evidence_mapping_report(
    *,
    job_description: str,
    model: ResumeRenderModel,
    prepared: object,
    similarity_provider: SimilarityProvider | None = None,
) -> dict:
    similarity = similarity_provider or TokenOverlapSimilarityProvider()
    themes = derive_job_themes(job_description)
    evidence_items = extract_evidence_items(model, prepared)
    matches = _match_themes(themes, evidence_items, similarity)

    visible_claims = extract_visible_skill_claims(model, prepared)
    claim_coverage = _build_claim_coverage(visible_claims, evidence_items, similarity)

    unsupported = list(dict.fromkeys(c.claim for c in claim_coverage if c.coverage_status == "unsupported"))
    weak = list(dict.fromkeys(c.claim for c in claim_coverage if c.coverage_status in {"weak", "weak_summary_only"}))

    theme_map: dict[str, set[str]] = {}
    for match in matches:
        theme_map.setdefault(match.evidence_id, set()).add(match.theme_id)

    strong_unused = []
    for evidence in evidence_items:
        has_signal = bool(evidence.metric_signals or evidence.scale_signals or evidence.outcome_signals)
        matched_theme_ids = sorted(theme_map.get(evidence.id, set()))
        if evidence.is_retained_in_rendered_resume or not matched_theme_ids or not has_signal:
            continue
        if not _is_primary_evidence(evidence):
            continue
        if evidence.evidence_score < 0.45:
            continue
        strong_unused.append(
            {
                "source_label": evidence.source_label,
                "source_type": evidence.source_type,
                "text": evidence.text,
                "matched_theme_ids": matched_theme_ids,
                "evidence_score": evidence.evidence_score,
                "signals": {
                    "metric": evidence.metric_signals,
                    "scale": evidence.scale_signals,
                    "outcome": evidence.outcome_signals,
                },
            }
        )
    strong_unused.sort(key=lambda item: float(item.get("evidence_score", 0.0)), reverse=True)

    evidence_available_but_not_rendered = [
        {
            "claim": c.claim,
            "coverage_status": c.coverage_status,
            "source_primary_evidence_count": c.primary_supporting_evidence_count,
            "retained_primary_evidence_count": c.retained_primary_supporting_evidence_count,
            "candidate_evidence_items": [
                {
                    "source_type": item.source_type,
                    "source_label": item.source_label,
                    "source_path": item.source_path,
                    "text": item.text[:180],
                    "evidence_score": item.evidence_score,
                    "reason_not_rendered": item.reason_not_rendered or "unknown",
                }
                for item in evidence_items
                if _is_primary_evidence(item)
                and c.claim in item.matched_visible_claims
                and not item.is_retained_in_rendered_resume
            ],
            "recommendation": "preserve_supporting_evidence_in_future_planner",
        }
        for c in claim_coverage
        if c.primary_supporting_evidence_count > 0 and c.retained_primary_supporting_evidence_count == 0
    ]

    return {
        "job_themes": [theme.__dict__ for theme in themes],
        "theme_evidence_matches": [match.__dict__ for match in matches],
        "claim_coverage": [claim.__dict__ for claim in claim_coverage],
        "unsupported_visible_claims": unsupported,
        "weak_visible_claims": weak,
        "evidence_available_but_not_rendered": evidence_available_but_not_rendered,
        "strong_unused_evidence": strong_unused[:10],
    }
