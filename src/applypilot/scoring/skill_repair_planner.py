from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import re

from applypilot.resume.evidence import claim_variants, extract_visible_skill_claims
from applypilot.scoring.pdf_planning_types import PlanningOperation, ReplacementCandidate, SkillDisposition
from applypilot.scoring.pdf_render_model import ResumeRenderModel
from applypilot.scoring.render_planning_service import (
    RenderPlanningContext,
    RenderPlanningService,
)

GROUPED_SKILL_TAXONOMY: dict[str, set[str]] = {
    "aws": {"EC2", "Lambda", "Route53", "S3", "CloudFront", "RDS"},
    "adobe": {"Photoshop", "Illustrator", "InDesign"},
    "adobe creative suite": {"Photoshop", "Illustrator", "InDesign"},
    "healthcare coding": {"ICD-10", "CPT", "SNOMED"},
}


@dataclass
class SkillRepairContext:
    template_name: str
    job_description: str = ""
    skills_selection: dict[str, Any] | None = None
    render_planning_service: RenderPlanningService | None = None


@dataclass
class SkillRepairResult:
    model: ResumeRenderModel
    html: str
    prepared: Any
    planning: dict[str, Any]


SkillRepairFn = Callable[
    ...,
    tuple[ResumeRenderModel, str, Any, dict[str, Any]],
]


@dataclass
class SkillRepairDependencies:
    skill_score_map_from_selection_fn: Callable[[dict[str, Any] | None], dict[str, float]]
    build_claim_coverage_for_claims_fn: Callable[..., list[Any]]
    extract_all_skill_claims_fn: Callable[[ResumeRenderModel], list[str]]
    clone_model_with_swapped_skills_fn: Callable[[ResumeRenderModel, str, str], ResumeRenderModel | None]
    clone_model_without_skill_fn: Callable[[ResumeRenderModel, str], ResumeRenderModel | None]
    measured_fit_fn: Callable[[dict[str, Any]], tuple[int | None, bool]]
    build_html_and_prepared_fn: Callable[..., tuple[str, Any]]
    build_planning_with_evidence_fn: Callable[..., dict[str, Any]]


@dataclass
class SkillReplacementPassResult:
    model: ResumeRenderModel
    html: str
    prepared: Any
    planning: dict[str, Any]
    adjustments: list[dict[str, Any]] = field(default_factory=list)
    planning_step_ops: list[dict[str, Any]] = field(default_factory=list)
    dispositions: list[SkillDisposition] = field(default_factory=list)
    candidates_considered: list[dict[str, Any]] = field(default_factory=list)
    candidate_search_summaries: list[dict[str, Any]] = field(default_factory=list)
    candidate_search_lookup: dict[str, dict[str, Any]] = field(default_factory=dict)
    used_candidates: set[str] = field(default_factory=set)
    replaced_claim_keys: set[str] = field(default_factory=set)


@dataclass
class SkillUnsupportedRemovalResult:
    model: ResumeRenderModel
    html: str
    prepared: Any
    planning: dict[str, Any]
    unsupported_skill_removals: list[dict[str, Any]] = field(default_factory=list)
    planning_step_ops: list[dict[str, Any]] = field(default_factory=list)
    dispositions: list[SkillDisposition] = field(default_factory=list)
    removed_claim_keys: set[str] = field(default_factory=set)


class SkillRepairPlanner:
    """Thin wrapper around the existing skill repair workflow."""

    def __init__(
        self,
        *,
        apply_skill_repair: SkillRepairFn | None = None,
        render_planning_service: RenderPlanningService | None = None,
        extract_visible_skill_claims_fn: Callable[[ResumeRenderModel, Any], list[str]] | None = None,
        dependencies: SkillRepairDependencies | None = None,
    ) -> None:
        self._apply_skill_repair = apply_skill_repair
        self._render_planning_service = render_planning_service
        self._extract_visible_skill_claims = extract_visible_skill_claims_fn or extract_visible_skill_claims
        self._dependencies = dependencies

    def claim_variants_set(self, claim_text: str) -> set[str]:
        return {self._normalize_skill_claim_key(item) for item in claim_variants(claim_text)}

    def alias_conflict(
        self,
        *,
        candidate: str,
        visible_claims: list[str],
        claim_being_replaced: str,
    ) -> bool:
        candidate_variants = self.claim_variants_set(candidate)
        if not candidate_variants:
            return False
        replacing_key = self._normalize_skill_claim_key(claim_being_replaced)
        for visible in visible_claims:
            if self._normalize_skill_claim_key(visible) == replacing_key:
                continue
            if candidate_variants & self.claim_variants_set(visible):
                return True
        return False

    def visible_skill_count_and_names(
        self,
        *,
        model: ResumeRenderModel,
        prepared: Any,
        planning: dict[str, Any],
    ) -> tuple[int, list[str]]:
        try:
            names = [claim for claim in self._extract_visible_skill_claims(model, prepared) if str(claim).strip()]
            deduped: list[str] = []
            seen: set[str] = set()
            for claim in names:
                key = self._normalize_skill_claim_key(claim)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(str(claim).strip())
            return len(deduped), deduped
        except Exception:
            claim_items = [item for item in planning.get("claim_coverage", []) if isinstance(item, dict)]
            names = [str(item.get("claim", "")).strip() for item in claim_items if str(item.get("claim", "")).strip()]
            return len(names), names

    def build_disposition(
        self,
        *,
        claim: str,
        coverage_status: str,
        final_action: str,
        reason: str,
        replacement: str | None = None,
        distinctive_tokens_required: list[str] | None = None,
        distinctive_tokens_matched: list[str] | None = None,
        replacement_search_performed: bool = False,
        replacement_candidates_available: int | None = None,
        supported_replacement_candidates_available: int | None = None,
        supported_replacement_candidates_available_raw: int | None = None,
        usable_supported_replacement_candidates_available: int | None = None,
        rejection_summary: list[str] | str | None = None,
        remaining_supported_retained_skills_not_visible: list[str] | None = None,
    ) -> SkillDisposition:
        payload = SkillDisposition(
            claim=claim,
            coverage_status=coverage_status,
            final_action=final_action,
            reason=reason,
            replacement=replacement,
            supported_replacement_candidates_available_raw=int(supported_replacement_candidates_available_raw or 0),
            usable_supported_replacement_candidates_available=int(usable_supported_replacement_candidates_available or 0),
            metadata={
                "distinctive_tokens_required": list(distinctive_tokens_required or []),
                "distinctive_tokens_matched": list(distinctive_tokens_matched or []),
                "replacement_search_performed": bool(replacement_search_performed),
            },
        )
        if replacement_candidates_available is not None:
            payload.metadata["replacement_candidates_available"] = int(replacement_candidates_available)
        if supported_replacement_candidates_available is not None:
            payload.metadata["supported_replacement_candidates_available"] = int(supported_replacement_candidates_available)
        if rejection_summary is not None:
            payload.metadata["rejection_summary"] = rejection_summary
        if remaining_supported_retained_skills_not_visible is not None:
            payload.metadata["remaining_supported_retained_skills_not_visible"] = list(
                remaining_supported_retained_skills_not_visible
            )
        if final_action in {"kept", "removed"}:
            payload.user_action = (
                f"Add a truthful experience bullet, compact summary, or project summary showing {claim} work if this skill should remain visible."
            )
        return payload

    def _claim_pattern(self, claim: str) -> re.Pattern[str]:
        escaped = re.escape(str(claim).strip())
        escaped = escaped.replace(r"\ ", r"\s+")
        return re.compile(rf"\b{escaped}\b", flags=re.IGNORECASE)

    def _summary_contains_claim(self, summary: str, claim: str) -> bool:
        if not summary.strip() or not str(claim).strip():
            return False
        return bool(self._claim_pattern(claim).search(summary))

    def _rewrite_summary_without_claim(self, summary: str, claim: str) -> str:
        text = str(summary or "")
        claim_escaped = re.escape(str(claim).strip())
        if not text.strip() or not claim_escaped:
            return text
        # Prefer precise phrase rewrites before token-level cleanup.
        text = re.sub(
            rf"\bAWS\s+and\s+{claim_escaped}\s+environments?\b",
            "AWS-backed environments",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            rf"\b{claim_escaped}\s+and\s+AWS\s+environments?\b",
            "AWS-backed environments",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            rf"\b{claim_escaped}\s+environments?\b",
            "deployment environments",
            text,
            flags=re.IGNORECASE,
        )
        # Remove unresolved claim from conjunctions/lists.
        text = re.sub(rf"(,\s*)?and\s+{claim_escaped}\b", "", text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{claim_escaped}\s+and\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{claim_escaped}\b", "", text, flags=re.IGNORECASE)
        # Cleanup punctuation/spacing artifacts from removals.
        text = re.sub(r"\s+,", ",", text)
        text = re.sub(r",\s*,+", ", ", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        text = re.sub(r"\s+([,.;:])", r"\1", text)
        text = re.sub(r",\s*([.;:])", r"\1", text)
        text = re.sub(r"\b(\w+)\s*-\s*based\b", r"\1-based", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(\w+)\s*-\s*driven\b", r"\1-driven", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(\w+)-\s*-\s*(based|driven)\b", r"\1-\2", text, flags=re.IGNORECASE)
        text = re.sub(r"\(\s*\)", "", text)

        # Light grammar polish: "using A, B, C" -> "using A, B, and C"
        def _oxford_for_using(match: re.Match[str]) -> str:
            prefix = match.group(1)
            segment = match.group(2)
            if re.search(r"\band\b", segment, flags=re.IGNORECASE):
                return match.group(0)
            parts = [part.strip() for part in segment.split(",") if part.strip()]
            if len(parts) < 3:
                return match.group(0)
            return f"{prefix}{parts[0]}, {parts[1]}, and {parts[2]}"

        text = re.sub(
            r"\b((?:using|with|including)\s+)([^.;:]+)",
            _oxford_for_using,
            text,
            flags=re.IGNORECASE,
        )
        return text.strip()

    def _taxonomy_children(self, parent: str) -> dict[str, str]:
        values = GROUPED_SKILL_TAXONOMY.get(self._normalize_skill_claim_key(parent), set())
        return {self._normalize_skill_claim_key(value): value for value in values}

    def _is_parent_child_subclaim(
        self,
        *,
        parent: str,
        subclaim: str,
        relation: str,
        evidence_span: str,
        sibling_subclaims: list[str],
    ) -> bool:
        parent_key = self._normalize_skill_claim_key(parent)
        sub_key = self._normalize_skill_claim_key(subclaim)
        taxonomy_children = self._taxonomy_children(parent)
        if taxonomy_children and sub_key not in taxonomy_children.keys():
            return False

        explicit_relations = {"existing_parenthetical", "repeated_prefix", "pool_parenthetical"}
        if relation in explicit_relations:
            return True

        if relation == "taxonomy_evidence":
            if not taxonomy_children or sub_key not in taxonomy_children.keys():
                return False
            if not evidence_span.strip():
                return False
            if not re.search(rf"\b{re.escape(parent.strip())}\b", evidence_span, flags=re.IGNORECASE):
                return False
            if not re.search(rf"\b{re.escape(subclaim.strip())}\b", evidence_span, flags=re.IGNORECASE):
                return False
            return True

        if relation == "pool_prefix":
            if not evidence_span.strip():
                return False
            if not re.search(rf"\b{re.escape(parent.strip())}\b", evidence_span, flags=re.IGNORECASE):
                return False
            if not re.search(rf"\b{re.escape(subclaim.strip())}\b", evidence_span, flags=re.IGNORECASE):
                return False
            if not ("," in evidence_span or re.search(r"\band\b", evidence_span, flags=re.IGNORECASE)):
                return False
            # Unknown parents stay conservative: require more than one sibling
            # signal in the same inferred group when we cannot validate taxonomy.
            if not taxonomy_children and len([item for item in sibling_subclaims if item.strip()]) < 2:
                return False
            return True

        # Standalone in-span attachment is high risk for false grouping; allow
        # only for taxonomy-backed parents.
        if relation == "standalone_span":
            return bool(taxonomy_children and sub_key in taxonomy_children.keys())

        return False

    def _parent_subclaim_removed_unsupported(
        self,
        *,
        parent: str,
        subclaim: str,
        removed_unsupported_claim_keys: set[str],
    ) -> bool:
        parent_child_key = self._normalize_skill_claim_key(f"{parent} {subclaim}")
        if parent_child_key in removed_unsupported_claim_keys:
            return True
        # Safe contextual fallback: if exact subclaim key was removed and the
        # parent has taxonomy children, block re-introducing that child.
        sub_key = self._normalize_skill_claim_key(subclaim)
        if sub_key in removed_unsupported_claim_keys and self._taxonomy_children(parent):
            return True
        return False

    def _split_skill_tokens_preserving_parentheses(self, text: str) -> list[str]:
        parts: list[str] = []
        buf: list[str] = []
        depth = 0
        for ch in str(text):
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

    def _parse_compound_skill_token(self, token: str) -> tuple[str, list[str]] | None:
        match = re.match(r"^\s*([^()]+?)\s*\(([^)]+)\)\s*$", str(token).strip())
        if not match:
            return None
        parent = str(match.group(1)).strip()
        raw_inside = str(match.group(2)).strip()
        if not parent or not raw_inside:
            return None
        subclaims = [part.strip().strip("() ,;:.") for part in re.split(r"[,;/]", raw_inside) if part.strip()]
        subclaims = [claim for claim in subclaims if claim]
        if not subclaims:
            return None
        return parent, subclaims

    def _skills_selection_pool(self, skills_selection: dict[str, Any] | None) -> list[str]:
        pool: list[str] = []
        seen: set[str] = set()
        if not isinstance(skills_selection, dict):
            return []
        retained = skills_selection.get("retained_skills")
        if isinstance(retained, list):
            for item in retained:
                if not isinstance(item, dict):
                    continue
                skill = str(item.get("skill", "")).strip()
                key = self._normalize_skill_claim_key(skill)
                if not skill or not key or key in seen:
                    continue
                seen.add(key)
                pool.append(skill)
        dropped = skills_selection.get("dropped_skills")
        if isinstance(dropped, list):
            for raw in dropped:
                skill = str(raw).strip()
                key = self._normalize_skill_claim_key(skill)
                if not skill or not key or key in seen:
                    continue
                seen.add(key)
                pool.append(skill)
        return pool

    def _rewrite_compound_skills(
        self,
        *,
        model: ResumeRenderModel,
        prepared: Any,
        build_claim_coverage_for_claims_fn: Callable[..., list[Any]],
        candidate_skill_pool: list[str] | None = None,
        removed_unsupported_claim_keys: set[str] | None = None,
    ) -> tuple[ResumeRenderModel, list[dict[str, Any]], list[str], list[str]]:
        repairs: list[dict[str, Any]] = []
        removed_subclaims: list[str] = []
        unresolved: list[str] = []
        updated_skills = list(model.skills)
        changed = False
        removed_unsupported_claim_keys = set(removed_unsupported_claim_keys or set())

        def _claim_supported(claim: str) -> bool:
            coverage = build_claim_coverage_for_claims_fn(
                claims=[claim],
                model=model,
                prepared=prepared,
            )
            claim_key = self._normalize_skill_claim_key(claim)
            item = next(
                (
                    candidate
                    for candidate in coverage
                    if self._normalize_skill_claim_key(str(getattr(candidate, "claim", ""))) == claim_key
                ),
                None,
            )
            if item is None:
                return False
            return (
                str(getattr(item, "coverage_status", "")) == "supported"
                and int(getattr(item, "retained_primary_supporting_evidence_count", 0) or 0) > 0
            )

        def _claim_evidence_sources(claim: str) -> list[str]:
            coverage = build_claim_coverage_for_claims_fn(
                claims=[claim],
                model=model,
                prepared=prepared,
            )
            claim_key = self._normalize_skill_claim_key(claim)
            item = next(
                (
                    candidate
                    for candidate in coverage
                    if self._normalize_skill_claim_key(str(getattr(candidate, "claim", ""))) == claim_key
                ),
                None,
            )
            if item is None:
                return []
            return list(getattr(item, "top_supporting_evidence", [])[:2])

        def _evidence_source_parts(evidence: str) -> tuple[str, str]:
            raw = str(evidence or "").strip()
            if ": " in raw:
                left, right = raw.split(": ", 1)
                return left.strip().lower(), right.strip().lower()
            return "", raw.lower()

        def _contains_token(text: str, token: str) -> bool:
            escaped = re.escape(str(token).strip())
            if not escaped:
                return False
            escaped = escaped.replace(r"\ ", r"\s+")
            return bool(re.search(rf"\b{escaped}\b", text, flags=re.IGNORECASE))

        def _subclaim_supported_in_parent_evidence_span(parent: str, subclaim: str) -> bool:
            parent_sources = _claim_evidence_sources(parent)
            sub_sources = _claim_evidence_sources(subclaim)
            if not parent_sources or not sub_sources:
                return False
            parent_parts = [_evidence_source_parts(item) for item in parent_sources]
            sub_parts = [_evidence_source_parts(item) for item in sub_sources]
            for p_label, p_text in parent_parts:
                for s_label, s_text in sub_parts:
                    if p_label and s_label and p_label != s_label:
                        continue
                    span = s_text if len(s_text) >= len(p_text) else p_text
                    if _contains_token(span, parent) and _contains_token(span, subclaim):
                        return True
                    if p_text and s_text and p_text == s_text:
                        return True
            return False

        def _subclaim_listed_with_parent_in_evidence_span(parent: str, subclaim: str) -> bool:
            parent_sources = _claim_evidence_sources(parent)
            sub_sources = _claim_evidence_sources(subclaim)
            if not parent_sources or not sub_sources:
                return False
            parent_parts = [_evidence_source_parts(item) for item in parent_sources]
            sub_parts = [_evidence_source_parts(item) for item in sub_sources]

            def _span_lists_token(span_text: str, parent_text: str, token_text: str) -> bool:
                match = re.search(rf"\b{re.escape(parent_text.strip())}\b", span_text, flags=re.IGNORECASE)
                if not match:
                    return False
                tail = span_text[match.end() :]
                sentence_end = re.search(r"[.;:\n]", tail)
                if sentence_end:
                    tail = tail[: sentence_end.start()]
                if "," not in tail and not re.search(r"\band\b", tail, flags=re.IGNORECASE):
                    return False
                normalized_tail = re.sub(r"\band\b", ",", tail, flags=re.IGNORECASE)
                items = [item.strip(" ()-") for item in normalized_tail.split(",") if item.strip(" ()-")]
                if len(items) < 2:
                    return False
                token_norm = self._normalize_skill_claim_key(token_text)
                for item in items:
                    item_norm = self._normalize_skill_claim_key(item)
                    if item_norm == token_norm:
                        return True
                    if _contains_token(item, token_text):
                        return True
                return False

            for p_label, p_text in parent_parts:
                for s_label, s_text in sub_parts:
                    if p_label and s_label and p_label != s_label:
                        continue
                    span = s_text if len(s_text) >= len(p_text) else p_text
                    if _span_lists_token(span, parent, subclaim):
                        return True
            return False

        for idx, section in enumerate(updated_skills):
            tokens = self._split_skill_tokens_preserving_parentheses(str(section.value))
            if not tokens:
                continue
            next_tokens = list(tokens)
            for token_idx, token in enumerate(tokens):
                parsed = self._parse_compound_skill_token(token)
                if not parsed:
                    continue
                parent, subclaims = parsed
                parent_coverage = build_claim_coverage_for_claims_fn(
                    claims=[parent],
                    model=model,
                    prepared=prepared,
                )
                parent_item = parent_coverage[0] if parent_coverage else None
                parent_supported = bool(
                    parent_item is not None
                    and str(getattr(parent_item, "coverage_status", "")) == "supported"
                    and int(getattr(parent_item, "retained_primary_supporting_evidence_count", 0) or 0) > 0
                )
                coverage = build_claim_coverage_for_claims_fn(
                    claims=[f"{parent} {claim}" for claim in subclaims],
                    model=model,
                    prepared=prepared,
                )
                by_key = {self._normalize_skill_claim_key(str(item.claim)): item for item in coverage}
                supported_subclaims: list[str] = []
                unsupported_subclaims: list[str] = []
                retained_evidence_sources: dict[str, list[str]] = {}
                for claim in subclaims:
                    parent_child_claim = f"{parent} {claim}"
                    parent_child_key = self._normalize_skill_claim_key(parent_child_claim)
                    if self._parent_subclaim_removed_unsupported(
                        parent=parent,
                        subclaim=claim,
                        removed_unsupported_claim_keys=removed_unsupported_claim_keys,
                    ):
                        unsupported_subclaims.append(claim)
                        continue
                    item = by_key.get(parent_child_key)
                    retained_primary = int(getattr(item, "retained_primary_supporting_evidence_count", 0) or 0) if item else 0
                    status = str(getattr(item, "coverage_status", "")) if item else "unsupported"
                    if status == "supported" and retained_primary > 0:
                        supported_subclaims.append(claim)
                        retained_evidence_sources[claim] = list(getattr(item, "top_supporting_evidence", [])[:2]) if item else []
                    else:
                        unsupported_subclaims.append(claim)
                if not unsupported_subclaims:
                    continue
                removed_subclaims.extend(unsupported_subclaims)
                if len(supported_subclaims) >= 2:
                    rewritten = f"{parent} ({', '.join(supported_subclaims)})"
                elif len(supported_subclaims) == 1:
                    rewritten = f"{parent} {supported_subclaims[0]}"
                elif parent_supported:
                    rewritten = parent
                else:
                    rewritten = token
                if rewritten.strip() != token.strip():
                    repairs.append(
                        {
                            "original_skill": token,
                            "rewritten_skill": rewritten,
                            "removed_subclaims": unsupported_subclaims,
                            "kept_subclaims": supported_subclaims,
                            "inferred_parent": parent,
                            "candidate_subclaims": list(subclaims),
                            "retained_subclaim_evidence_sources": retained_evidence_sources,
                            "family_cap_group_recovery": False,
                            "reason": "unsupported_compound_subclaims_removed",
                        }
                    )
                    next_tokens[token_idx] = rewritten
                    changed = True
                unresolved.extend(f"{parent}: {subclaim}" for subclaim in unsupported_subclaims)

            if next_tokens != tokens:
                updated_skills[idx] = type(section)(
                    category=section.category,
                    value=", ".join(next_tokens),
                )

        # Infer grouped skills from repeated-prefix flat skills, preserving
        # readable grouped output while removing unsupported subclaims.
        for idx, section in enumerate(updated_skills):
            tokens = self._split_skill_tokens_preserving_parentheses(str(section.value))
            if len(tokens) < 1:
                continue
            next_tokens = list(tokens)
            token_positions: dict[str, list[int]] = {}
            for pos, token in enumerate(tokens):
                token_positions.setdefault(token, []).append(pos)

            parent_groups: dict[str, list[tuple[int, str, str, str]]] = {}
            pool_tokens = list(tokens)
            if candidate_skill_pool:
                pool_tokens.extend([token for token in candidate_skill_pool if str(token).strip()])
            for pos, token in enumerate(pool_tokens):
                parsed_group = self._parse_compound_skill_token(token)
                if parsed_group is not None:
                    parent, group_subclaims = parsed_group
                    relation = "existing_parenthetical" if pos < len(tokens) else "pool_parenthetical"
                    for subclaim in group_subclaims:
                        parent_groups.setdefault(parent, []).append((pos, subclaim, token, relation))
                    continue
                parts = [part for part in token.strip().split() if part]
                if len(parts) < 2:
                    continue
                parent = " ".join(parts[:-1]).strip()
                subclaim = parts[-1].strip()
                if not parent or not subclaim:
                    continue
                relation = "repeated_prefix" if pos < len(tokens) else "pool_prefix"
                parent_groups.setdefault(parent, []).append((pos, subclaim, token, relation))

            if not parent_groups:
                continue

            for parent, entries in parent_groups.items():
                taxonomy_children = self._taxonomy_children(parent)
                if taxonomy_children:
                    synthetic_pos = len(pool_tokens) + 10_000
                    for child_key in sorted(taxonomy_children.keys()):
                        child = str(taxonomy_children.get(child_key, child_key)).strip()
                        child_already_present = any(
                            self._normalize_skill_claim_key(entry[1]) == child_key
                            for entry in entries
                        )
                        if child_already_present:
                            continue
                        if self._parent_subclaim_removed_unsupported(
                            parent=parent,
                            subclaim=child,
                            removed_unsupported_claim_keys=removed_unsupported_claim_keys,
                        ):
                            continue
                        parent_child_claim = f"{parent} {child}"
                        if not _claim_supported(parent_child_claim):
                            continue
                        if not _subclaim_supported_in_parent_evidence_span(parent, child):
                            continue
                        if not _subclaim_listed_with_parent_in_evidence_span(parent, child):
                            continue
                        entries.append((synthetic_pos, child, parent_child_claim, "taxonomy_evidence"))
                        synthetic_pos += 1

                # Only infer when there is meaningful grouping signal.
                unique_by_subclaim: dict[str, tuple[int, str, str, str]] = {}
                relation_rank = {
                    "existing_parenthetical": 0,
                    "repeated_prefix": 1,
                    "taxonomy_evidence": 2,
                    "pool_parenthetical": 3,
                    "pool_prefix": 4,
                }
                for entry in sorted(entries, key=lambda item: (item[0], relation_rank.get(item[3], 9))):
                    subclaim_key = self._normalize_skill_claim_key(entry[1])
                    current = unique_by_subclaim.get(subclaim_key)
                    if current is None or relation_rank.get(entry[3], 9) < relation_rank.get(current[3], 9):
                        unique_by_subclaim[subclaim_key] = entry
                entries = list(unique_by_subclaim.values())
                if len(entries) < 2:
                    continue
                ordered_supported: list[str] = []
                removed_for_parent: list[str] = []
                retained_evidence_sources: dict[str, list[str]] = {}
                remove_positions: set[int] = set()
                eligible_subclaims: list[str] = []
                ineligible_subclaims: list[str] = []
                for pos, subclaim, original_token, relation in sorted(entries, key=lambda item: item[0]):
                    if pos < len(tokens):
                        remove_positions.add(pos)
                    is_eligible = relation in {
                        "existing_parenthetical",
                        "repeated_prefix",
                        "taxonomy_evidence",
                        "pool_parenthetical",
                        "pool_prefix",
                    }
                    if is_eligible and subclaim not in eligible_subclaims:
                        eligible_subclaims.append(subclaim)
                    if not is_eligible and subclaim not in ineligible_subclaims:
                        ineligible_subclaims.append(subclaim)
                    parent_subclaim_claim = f"{parent} {subclaim}"
                    parent_subclaim_supported = (
                        not self._parent_subclaim_removed_unsupported(
                            parent=parent,
                            subclaim=subclaim,
                            removed_unsupported_claim_keys=removed_unsupported_claim_keys,
                        )
                        and _claim_supported(parent_subclaim_claim)
                    )
                    coherent_span = _subclaim_supported_in_parent_evidence_span(parent, subclaim)
                    listed_with_parent = _subclaim_listed_with_parent_in_evidence_span(parent, subclaim)
                    span_sources = _claim_evidence_sources(parent_subclaim_claim) or _claim_evidence_sources(parent)
                    evidence_span = " ".join(span_sources).lower()
                    parent_child_semantic = self._is_parent_child_subclaim(
                        parent=parent,
                        subclaim=subclaim,
                        relation=relation,
                        evidence_span=evidence_span,
                        sibling_subclaims=[entry[1] for entry in entries],
                    )
                    if relation == "pool_prefix":
                        relation_supported = (
                            parent_subclaim_supported
                            and coherent_span
                            and listed_with_parent
                            and parent_child_semantic
                        )
                    else:
                        relation_supported = parent_subclaim_supported and parent_child_semantic
                    if is_eligible and relation_supported:
                        if subclaim not in ordered_supported:
                            ordered_supported.append(subclaim)
                            retained_evidence_sources[subclaim] = (
                                _claim_evidence_sources(f"{parent} {subclaim}") or _claim_evidence_sources(subclaim)
                            )
                    else:
                        removed_for_parent.append(subclaim)

                # Add related standalone subclaims only when they are supported
                # and appear in a coherent retained parent-child evidence list.
                standalone_candidates: list[tuple[int | None, str]] = []
                for pos, token in enumerate(tokens):
                    if pos in remove_positions:
                        continue
                    if "(" in token or ")" in token:
                        continue
                    if " " in token.strip():
                        continue
                    standalone_candidates.append((pos, token.strip()))
                if candidate_skill_pool:
                    for pool_token in candidate_skill_pool:
                        if "(" in pool_token or ")" in pool_token:
                            continue
                        if " " in pool_token.strip():
                            continue
                        standalone_candidates.append((None, pool_token.strip()))

                seen_standalone_candidates: set[str] = set()
                for pos, standalone in standalone_candidates:
                    standalone_key = self._normalize_skill_claim_key(standalone)
                    if not standalone_key or standalone_key in seen_standalone_candidates:
                        continue
                    seen_standalone_candidates.add(standalone_key)
                    parent_subclaim_claim = f"{parent} {standalone}"
                    span_sources = _claim_evidence_sources(parent_subclaim_claim) or _claim_evidence_sources(parent)
                    evidence_span = " ".join(span_sources).lower()
                    if (
                        not self._parent_subclaim_removed_unsupported(
                            parent=parent,
                            subclaim=standalone,
                            removed_unsupported_claim_keys=removed_unsupported_claim_keys,
                        )
                        and _claim_supported(parent_subclaim_claim)
                        and _subclaim_supported_in_parent_evidence_span(parent, standalone)
                        and _subclaim_listed_with_parent_in_evidence_span(parent, standalone)
                        and self._is_parent_child_subclaim(
                            parent=parent,
                            subclaim=standalone,
                            relation="standalone_span",
                            evidence_span=evidence_span,
                            sibling_subclaims=[entry[1] for entry in entries],
                        )
                    ):
                        if pos is not None:
                            remove_positions.add(pos)
                        if standalone not in ordered_supported:
                            ordered_supported.append(standalone)
                            retained_evidence_sources[standalone] = _claim_evidence_sources(standalone)
                            if standalone not in eligible_subclaims:
                                eligible_subclaims.append(standalone)

                parent_supported = _claim_supported(parent)
                rewritten: str | None = None
                if len(ordered_supported) >= 2:
                    rewritten = f"{parent} ({', '.join(ordered_supported)})"
                elif len(ordered_supported) == 1:
                    rewritten = f"{parent} {ordered_supported[0]}"
                elif parent_supported:
                    rewritten = parent

                if rewritten is None:
                    unresolved.extend(f"{parent}: {subclaim}" for subclaim in removed_for_parent)
                    continue

                first_pos = min(remove_positions) if remove_positions else -1
                if first_pos < 0:
                    continue
                original_group = [tokens[pos] for pos in sorted(remove_positions)]
                for pos in sorted(remove_positions, reverse=True):
                    del next_tokens[pos]
                next_tokens.insert(first_pos, rewritten)
                if next_tokens != tokens:
                    changed = True
                    repairs.append(
                        {
                            "original_skill": ", ".join(original_group),
                            "rewritten_skill": rewritten,
                            "removed_subclaims": removed_for_parent,
                            "kept_subclaims": ordered_supported,
                            "inferred_parent": parent,
                            "candidate_subclaims": [entry[1] for entry in sorted(entries, key=lambda item: item[0])],
                            "eligible_subclaims": eligible_subclaims,
                            "ineligible_subclaims_rejected": ineligible_subclaims,
                            "retained_subclaim_evidence_sources": retained_evidence_sources,
                            "family_cap_group_recovery": any(entry[0] >= len(tokens) for entry in entries),
                            "grouping_inference_sources": sorted(
                                dict.fromkeys([entry[3] for entry in entries])
                            ),
                            "reason": "unsupported_compound_subclaims_removed",
                        }
                    )
                    removed_subclaims.extend(removed_for_parent)

            if next_tokens != tokens:
                updated_skills[idx] = type(section)(
                    category=section.category,
                    value=", ".join(next_tokens),
                )

        if not changed:
            return model, [], sorted(dict.fromkeys(removed_subclaims)), sorted(dict.fromkeys(unresolved))

        updated_model = ResumeRenderModel(
            name=model.name,
            title=model.title,
            location=model.location,
            contact=model.contact,
            summary=model.summary,
            skills=updated_skills,
            experience=list(model.experience),
            projects=list(model.projects),
            education=model.education,
            certifications=model.certifications,
            render_options=dict(model.render_options),
        )
        return updated_model, repairs, sorted(dict.fromkeys(removed_subclaims)), sorted(dict.fromkeys(unresolved))

    def apply_compound_skill_repairs(
        self,
        *,
        model: ResumeRenderModel,
        html: str,
        prepared: Any,
        planning: dict[str, Any],
        context: SkillRepairContext,
        removed_unsupported_claim_keys: set[str] | None,
        build_claim_coverage_for_claims_fn: Callable[..., list[Any]],
        build_html_and_prepared_fn: Callable[..., tuple[str, Any]],
        build_planning_with_evidence_fn: Callable[..., dict[str, Any]],
        measured_fit_fn: Callable[[dict[str, Any]], tuple[int | None, bool]],
    ) -> tuple[ResumeRenderModel, str, Any, dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
        candidate_skill_pool = self._skills_selection_pool(context.skills_selection)
        next_model, repairs, removed_subclaims, unresolved = self._rewrite_compound_skills(
            model=model,
            prepared=prepared,
            build_claim_coverage_for_claims_fn=build_claim_coverage_for_claims_fn,
            candidate_skill_pool=candidate_skill_pool,
            removed_unsupported_claim_keys=removed_unsupported_claim_keys,
        )
        if not repairs:
            next_model = model
            repairs = []
            removed_subclaims = []
            unresolved = []
            render_service = context.render_planning_service or self._render_planning_service
            if render_service is not None:
                state = render_service.rebuild_state(
                    model=next_model,
                    context=RenderPlanningContext(
                        template_name=context.template_name,
                        job_description=context.job_description,
                    ),
                )
                model, html, prepared, planning = state.model, state.html, state.prepared, state.planning
            else:
                model, html, prepared, planning = next_model, html, prepared, planning
        else:
            render_service = context.render_planning_service or self._render_planning_service
            render_context = RenderPlanningContext(
                template_name=context.template_name,
                job_description=context.job_description,
            )
            if render_service is not None:
                state = render_service.rebuild_state(model=next_model, context=render_context)
                model, html, prepared, planning = state.model, state.html, state.prepared, state.planning
            else:
                next_html, next_prepared = build_html_and_prepared_fn(next_model, template_name=context.template_name)
                next_planning = build_planning_with_evidence_fn(
                    model=next_model,
                    prepared=next_prepared,
                    template_name=context.template_name,
                    job_description=context.job_description,
                )
                measured_fit_fn(next_planning)
                model, html, prepared, planning = next_model, next_html, next_prepared, next_planning

        (
            model,
            html,
            prepared,
            planning,
            sanitizer_repairs,
            sanitizer_removed_subclaims,
            sanitizer_unresolved,
        ) = self._sanitize_final_grouped_claims(
            model=model,
            html=html,
            prepared=prepared,
            planning=planning,
            context=context,
            removed_unsupported_claim_keys=removed_unsupported_claim_keys,
            build_claim_coverage_for_claims_fn=build_claim_coverage_for_claims_fn,
            build_html_and_prepared_fn=build_html_and_prepared_fn,
            build_planning_with_evidence_fn=build_planning_with_evidence_fn,
            measured_fit_fn=measured_fit_fn,
        )
        repairs.extend(sanitizer_repairs)
        removed_subclaims.extend(sanitizer_removed_subclaims)
        unresolved.extend(sanitizer_unresolved)

        # Re-check unresolved subclaims in final state for reporting.
        final_unresolved: list[str] = []
        for section in model.skills:
            tokens = self._split_skill_tokens_preserving_parentheses(str(section.value))
            for token in tokens:
                parsed = self._parse_compound_skill_token(token)
                if not parsed:
                    continue
                parent, subclaims = parsed
                parent_subclaim_claims = [f"{parent} {subclaim}" for subclaim in subclaims]
                coverage = build_claim_coverage_for_claims_fn(
                    claims=parent_subclaim_claims,
                    model=model,
                    prepared=prepared,
                )
                by_key = {
                    self._normalize_skill_claim_key(str(getattr(item, "claim", ""))): item
                    for item in coverage
                }
                for subclaim in subclaims:
                    item = by_key.get(self._normalize_skill_claim_key(f"{parent} {subclaim}"))
                    status = str(getattr(item, "coverage_status", ""))
                    retained_primary = int(getattr(item, "retained_primary_supporting_evidence_count", 0) or 0)
                    evidence_span = " ".join(list(getattr(item, "top_supporting_evidence", [])[:2]))
                    allowed = self._is_parent_child_subclaim(
                        parent=parent,
                        subclaim=subclaim,
                        relation="existing_parenthetical",
                        evidence_span=evidence_span,
                        sibling_subclaims=list(subclaims),
                    )
                    removed_block = self._parent_subclaim_removed_unsupported(
                        parent=parent,
                        subclaim=subclaim,
                        removed_unsupported_claim_keys=removed_unsupported_claim_keys or set(),
                    )
                    if status != "supported" or retained_primary == 0 or not allowed or removed_block:
                        final_unresolved.append(f"{parent}: {subclaim}")

        return (
            model,
            html,
            prepared,
            planning,
            repairs,
            removed_subclaims,
            sorted(dict.fromkeys(final_unresolved)),
        )

    def _sanitize_final_grouped_claims(
        self,
        *,
        model: ResumeRenderModel,
        html: str,
        prepared: Any,
        planning: dict[str, Any],
        context: SkillRepairContext,
        removed_unsupported_claim_keys: set[str] | None,
        build_claim_coverage_for_claims_fn: Callable[..., list[Any]],
        build_html_and_prepared_fn: Callable[..., tuple[str, Any]],
        build_planning_with_evidence_fn: Callable[..., dict[str, Any]],
        measured_fit_fn: Callable[[dict[str, Any]], tuple[int | None, bool]],
    ) -> tuple[ResumeRenderModel, str, Any, dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
        removed_unsupported_claim_keys = set(removed_unsupported_claim_keys or set())
        repairs: list[dict[str, Any]] = []
        removed_subclaims: list[str] = []
        unresolved: list[str] = []
        updated_skills = list(model.skills)
        changed = False

        for idx, section in enumerate(updated_skills):
            tokens = self._split_skill_tokens_preserving_parentheses(str(section.value))
            if not tokens:
                continue
            next_tokens = list(tokens)
            for token_idx, token in enumerate(tokens):
                parsed = self._parse_compound_skill_token(token)
                if not parsed:
                    continue
                parent, subclaims = parsed
                kept: list[str] = []
                dropped: list[str] = []
                evidence_sources: dict[str, list[str]] = {}
                for subclaim in subclaims:
                    parent_child_claim = f"{parent} {subclaim}"
                    parent_child_key = self._normalize_skill_claim_key(parent_child_claim)
                    coverage_items = build_claim_coverage_for_claims_fn(
                        claims=[parent_child_claim],
                        model=model,
                        prepared=prepared,
                    )
                    item = next(
                        (
                            c
                            for c in coverage_items
                            if self._normalize_skill_claim_key(str(getattr(c, "claim", ""))) == parent_child_key
                        ),
                        None,
                    )
                    status = str(getattr(item, "coverage_status", "unsupported"))
                    retained_primary = int(getattr(item, "retained_primary_supporting_evidence_count", 0) or 0)
                    evidence_span = " ".join(list(getattr(item, "top_supporting_evidence", [])[:2]))
                    allowed = self._is_parent_child_subclaim(
                        parent=parent,
                        subclaim=subclaim,
                        relation="existing_parenthetical",
                        evidence_span=evidence_span,
                        sibling_subclaims=list(subclaims),
                    )
                    removed_block = self._parent_subclaim_removed_unsupported(
                        parent=parent,
                        subclaim=subclaim,
                        removed_unsupported_claim_keys=removed_unsupported_claim_keys,
                    )
                    if status == "supported" and retained_primary > 0 and allowed and not removed_block:
                        kept.append(subclaim)
                        evidence_sources[subclaim] = list(getattr(item, "top_supporting_evidence", [])[:2])
                    else:
                        dropped.append(subclaim)
                if not dropped:
                    continue
                rewritten: str
                if len(kept) >= 2:
                    rewritten = f"{parent} ({', '.join(kept)})"
                elif len(kept) == 1:
                    rewritten = f"{parent} {kept[0]}"
                else:
                    parent_cov = build_claim_coverage_for_claims_fn(
                        claims=[parent],
                        model=model,
                        prepared=prepared,
                    )
                    parent_item = next(
                        (
                            c
                            for c in parent_cov
                            if self._normalize_skill_claim_key(str(getattr(c, "claim", "")))
                            == self._normalize_skill_claim_key(parent)
                        ),
                        None,
                    )
                    parent_supported = bool(
                        parent_item is not None
                        and str(getattr(parent_item, "coverage_status", "")) == "supported"
                        and int(getattr(parent_item, "retained_primary_supporting_evidence_count", 0) or 0) > 0
                    )
                    rewritten = parent if parent_supported else token
                if rewritten.strip() != token.strip():
                    next_tokens[token_idx] = rewritten
                    changed = True
                    repairs.append(
                        {
                            "step": "grouped_skill_sanitizer",
                            "original_skill": token,
                            "rewritten_skill": rewritten,
                            "removed_subclaims": list(dropped),
                            "kept_subclaims": list(kept),
                            "retained_subclaim_evidence_sources": evidence_sources,
                        }
                    )
                    removed_subclaims.extend(dropped)
                    unresolved.extend(f"{parent}: {item}" for item in dropped)
            if next_tokens != tokens:
                updated_skills[idx] = type(section)(
                    category=section.category,
                    value=", ".join(next_tokens),
                )

        if not changed:
            return model, html, prepared, planning, [], [], []

        updated_model = ResumeRenderModel(
            name=model.name,
            title=model.title,
            location=model.location,
            contact=model.contact,
            summary=model.summary,
            skills=updated_skills,
            experience=list(model.experience),
            projects=list(model.projects),
            education=model.education,
            certifications=model.certifications,
            render_options=dict(model.render_options),
        )
        render_service = context.render_planning_service or self._render_planning_service
        if render_service is not None:
            state = render_service.rebuild_state(
                model=updated_model,
                context=RenderPlanningContext(
                    template_name=context.template_name,
                    job_description=context.job_description,
                ),
            )
            return (
                state.model,
                state.html,
                state.prepared,
                state.planning,
                repairs,
                sorted(dict.fromkeys(removed_subclaims)),
                sorted(dict.fromkeys(unresolved)),
            )
        next_html, next_prepared = build_html_and_prepared_fn(updated_model, template_name=context.template_name)
        next_planning = build_planning_with_evidence_fn(
            model=updated_model,
            prepared=next_prepared,
            template_name=context.template_name,
            job_description=context.job_description,
        )
        measured_fit_fn(next_planning)
        return (
            updated_model,
            next_html,
            next_prepared,
            next_planning,
            repairs,
            sorted(dict.fromkeys(removed_subclaims)),
            sorted(dict.fromkeys(unresolved)),
        )

    def apply_summary_claim_repairs(
        self,
        *,
        model: ResumeRenderModel,
        html: str,
        prepared: Any,
        planning: dict[str, Any],
        context: SkillRepairContext,
        dispositions: list[SkillDisposition],
        build_html_and_prepared_fn: Callable[..., tuple[str, Any]],
        build_planning_with_evidence_fn: Callable[..., dict[str, Any]],
        measured_fit_fn: Callable[[dict[str, Any]], tuple[int | None, bool]],
    ) -> tuple[ResumeRenderModel, str, Any, dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
        summary = str(model.summary or "")
        if not summary.strip():
            return model, html, prepared, planning, [], [], []

        final_lookup: dict[str, dict[str, Any]] = {}
        for item in planning.get("claim_coverage", []):
            if isinstance(item, dict):
                key = self._normalize_skill_claim_key(str(item.get("claim", "")))
                if key:
                    final_lookup[key] = item

        unresolved_claims: list[str] = []
        seen_keys: set[str] = set()

        for item in dispositions:
            if not isinstance(item, SkillDisposition):
                continue
            if item.final_action != "removed":
                continue
            claim = str(item.claim).strip()
            key = self._normalize_skill_claim_key(claim)
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            unresolved_claims.append(claim)

        for item in planning.get("claim_coverage", []):
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim", "")).strip()
            key = self._normalize_skill_claim_key(claim)
            if not key or key in seen_keys:
                continue
            status = str(item.get("coverage_status", ""))
            retained_primary = int(item.get("retained_primary_supporting_evidence_count", 0) or 0)
            if status in {"unsupported", "weak_summary_only"} or (status == "weak" and retained_primary == 0):
                seen_keys.add(key)
                unresolved_claims.append(claim)

        repairs: list[dict[str, Any]] = []
        rewritten_claims: list[str] = []
        updated_summary = summary
        for claim in unresolved_claims:
            if not self._summary_contains_claim(updated_summary, claim):
                continue
            rewritten = self._rewrite_summary_without_claim(updated_summary, claim)
            if rewritten == updated_summary:
                continue
            repairs.append(
                {
                    "claim": claim,
                    "action": "rewritten",
                    "summary_before": updated_summary,
                    "summary_after": rewritten,
                    "reason": "summary_claim_unresolved_after_skill_repair",
                }
            )
            rewritten_claims.append(claim)
            updated_summary = rewritten

        if updated_summary != summary:
            next_model = ResumeRenderModel(
                name=model.name,
                title=model.title,
                location=model.location,
                contact=model.contact,
                summary=updated_summary,
                skills=list(model.skills),
                experience=list(model.experience),
                projects=list(model.projects),
                education=model.education,
                certifications=model.certifications,
                render_options=dict(model.render_options),
            )
            render_service = context.render_planning_service or self._render_planning_service
            render_context = RenderPlanningContext(
                template_name=context.template_name,
                job_description=context.job_description,
            )
            if render_service is not None:
                state = render_service.rebuild_state(model=next_model, context=render_context)
                model, html, prepared, planning = state.model, state.html, state.prepared, state.planning
            else:
                next_html, next_prepared = build_html_and_prepared_fn(next_model, template_name=context.template_name)
                next_planning = build_planning_with_evidence_fn(
                    model=next_model,
                    prepared=next_prepared,
                    template_name=context.template_name,
                    job_description=context.job_description,
                )
                measured_fit_fn(next_planning)
                model, html, prepared, planning = next_model, next_html, next_prepared, next_planning

        unresolved_after = [claim for claim in unresolved_claims if self._summary_contains_claim(str(model.summary or ""), claim)]
        return model, html, prepared, planning, repairs, rewritten_claims, unresolved_after

    def find_usable_supported_replacements_for_claim(
        self,
        *,
        claim: str,
        claim_status: str,
        model: ResumeRenderModel,
        prepared: Any,
        planning: dict[str, Any],
        used_candidate_keys: set[str],
        score_map: dict[str, float],
        adjustments: list[dict[str, Any]],
        build_claim_coverage_for_claims_fn: Callable[..., list[Any]],
        extract_all_skill_claims_fn: Callable[[ResumeRenderModel], list[str]],
    ) -> tuple[list[str], list[str]]:
        claim_key = self._normalize_skill_claim_key(claim)
        claim_coverage_items_state = [item for item in planning.get("claim_coverage", []) if isinstance(item, dict)]
        visible_claims_state = [str(item.get("claim", "")) for item in claim_coverage_items_state if str(item.get("claim", "")).strip()]
        visible_set_state = {self._normalize_skill_claim_key(value) for value in visible_claims_state if value.strip()}
        all_claims_state = extract_all_skill_claims_fn(model)
        hidden_claims_state = [token for token in all_claims_state if self._normalize_skill_claim_key(token) not in visible_set_state]
        if not hidden_claims_state:
            return [], []

        hidden_coverage_state = build_claim_coverage_for_claims_fn(
            claims=hidden_claims_state,
            model=model,
            prepared=prepared,
        )
        hidden_lookup_state = {self._normalize_skill_claim_key(item.claim): item for item in hidden_coverage_state}
        source_score_state = score_map.get(claim_key)
        ranked_hidden_state = sorted(
            hidden_claims_state,
            key=lambda token: (
                score_map.get(self._normalize_skill_claim_key(token), float("-inf")),
                -all_claims_state.index(token),
            ),
            reverse=True,
        )

        overflow_pairs = {
            (
                self._normalize_skill_claim_key(str(item.get("from", ""))),
                self._normalize_skill_claim_key(str(item.get("to", ""))),
            )
            for item in adjustments
            if isinstance(item, dict)
            and str(item.get("step", "")) == "evidence_aware_skill_replacement"
            and not bool(item.get("kept", False))
            and str(item.get("reason", "")) == "weak_or_unsupported_claim_replaced_by_supported_retained_skill"
        }

        candidates: list[ReplacementCandidate] = []
        for token in ranked_hidden_state:
            token_key = self._normalize_skill_claim_key(token)
            coverage = hidden_lookup_state.get(token_key)
            candidate_score = score_map.get(token_key)
            candidate = ReplacementCandidate(
                original_claim=claim,
                candidate=token,
                coverage_status=coverage.coverage_status if coverage else "missing",
                supported=bool(coverage is not None and coverage.coverage_status == "supported"),
                metadata={"candidate_score": candidate_score},
            )
            if not candidate.supported:
                candidate.rejection_reasons.append("rejected_not_supported")
                candidates.append(candidate)
                continue
            if token_key in used_candidate_keys:
                candidate.already_used = True
                candidate.rejection_reasons.append("rejected_already_used")
                candidates.append(candidate)
                continue
            if self.alias_conflict(candidate=token, visible_claims=visible_claims_state, claim_being_replaced=claim):
                candidate.alias_conflict = True
                candidate.rejection_reasons.append("rejected_alias_conflict")
                candidates.append(candidate)
                continue
            if (claim_key, token_key) in overflow_pairs:
                candidate.failed_page_fit = True
                candidate.rejection_reasons.append("rejected_page_overflow")
                candidates.append(candidate)
                continue
            if claim_status == "weak" and source_score_state is not None and candidate_score is not None:
                if candidate_score + 6.0 < source_score_state:
                    candidate.rejection_reasons.append("rejected_lower_relevance")
                    candidates.append(candidate)
                    continue
            candidate.usable = True
            candidates.append(candidate)
        all_supported = [item.candidate for item in candidates if item.supported]
        usable = [item.candidate for item in candidates if item.usable]
        return all_supported, usable

    def apply_replacements(
        self,
        *,
        model: ResumeRenderModel,
        html: str,
        prepared: Any,
        planning: dict[str, Any],
        context: SkillRepairContext,
        score_map: dict[str, float],
        used_candidates: set[str] | None = None,
        replaced_claim_keys: set[str] | None = None,
        adjustments: list[dict[str, Any]] | None = None,
        planning_step_ops: list[dict[str, Any]] | None = None,
        dispositions: list[SkillDisposition] | None = None,
        candidates_considered: list[dict[str, Any]] | None = None,
        candidate_search_summaries: list[dict[str, Any]] | None = None,
        candidate_search_lookup: dict[str, dict[str, Any]] | None = None,
        build_claim_coverage_for_claims_fn: Callable[..., list[Any]],
        extract_all_skill_claims_fn: Callable[[ResumeRenderModel], list[str]],
        clone_model_with_swapped_skills_fn: Callable[[ResumeRenderModel, str, str], ResumeRenderModel | None],
        measured_fit_fn: Callable[[dict[str, Any]], tuple[int | None, bool]],
        build_html_and_prepared_fn: Callable[..., tuple[str, Any]],
        build_planning_with_evidence_fn: Callable[..., dict[str, Any]],
    ) -> SkillReplacementPassResult:
        current_model = model
        current_html = html
        current_prepared = prepared
        current_planning = planning
        used_candidates = set(used_candidates or set())
        replaced_claim_keys = set(replaced_claim_keys or set())
        adjustments = list(adjustments or [])
        planning_step_ops = list(planning_step_ops or [])
        dispositions = list(dispositions or [])
        candidates_considered = list(candidates_considered or [])
        candidate_search_summaries = list(candidate_search_summaries or [])
        candidate_search_lookup = dict(candidate_search_lookup or {})
        replacement_priority = ["unsupported", "weak_summary_only", "weak"]
        render_service = context.render_planning_service or self._render_planning_service
        render_context = RenderPlanningContext(
            template_name=context.template_name,
            job_description=context.job_description,
        )

        def _render_rebuild(next_model: ResumeRenderModel) -> tuple[str, Any, dict[str, Any], int | None, bool]:
            if render_service is not None:
                next_state = render_service.rebuild_state(
                    model=next_model,
                    context=render_context,
                )
                measured_pages, fit = render_service.measured_fit(next_state)
                return next_state.html, next_state.prepared, next_state.planning, measured_pages, fit
            next_html, next_prepared = build_html_and_prepared_fn(next_model, template_name=context.template_name)
            next_planning = build_planning_with_evidence_fn(
                model=next_model,
                prepared=next_prepared,
                template_name=context.template_name,
                job_description=context.job_description,
            )
            measured_pages, fit = measured_fit_fn(next_planning)
            return next_html, next_prepared, next_planning, measured_pages, fit

        for target_status in replacement_priority:
            claim_coverage_items = [item for item in current_planning.get("claim_coverage", []) if isinstance(item, dict)]
            claim_coverage_lookup = {
                self._normalize_skill_claim_key(str(item.get("claim", ""))): item for item in claim_coverage_items
            }
            target_claims = [
                str(item.get("claim", ""))
                for item in claim_coverage_items
                if str(item.get("coverage_status", "")) == target_status and str(item.get("claim", "")).strip()
            ]
            target_claims = list(dict.fromkeys(target_claims))
            for claim in target_claims:
                if self._parse_compound_skill_token(claim) is not None:
                    continue
                claim_key = self._normalize_skill_claim_key(claim)
                if claim_key in replaced_claim_keys:
                    continue

                all_claims = extract_all_skill_claims_fn(current_model)
                visible_claims = [str(item.get("claim", "")) for item in claim_coverage_items if isinstance(item, dict)]
                visible_set = {self._normalize_skill_claim_key(value) for value in visible_claims if value.strip()}
                hidden_claims = [token for token in all_claims if self._normalize_skill_claim_key(token) not in visible_set]
                rejection_codes: list[str] = []
                retained_skills_count = len(all_claims)
                visible_skills_count = len([claim_token for claim_token in visible_claims if claim_token.strip()])
                search_summary: dict[str, Any] = {
                    "claim": claim,
                    "coverage_status": target_status,
                    "retained_skills_count": retained_skills_count,
                    "visible_skills_count": visible_skills_count,
                    "non_visible_retained_candidates_count": len(hidden_claims),
                    "supported_non_visible_candidates_count": 0,
                    "result": "no_supported_retained_replacement_available",
                }
                visible_rejections_recorded = 0
                for token in all_claims:
                    token_key = self._normalize_skill_claim_key(token)
                    if token_key in visible_set and token_key != claim_key and visible_rejections_recorded < 3:
                        candidates_considered.append(
                            {
                                "claim": claim,
                                "claim_status": target_status,
                                "candidate": token,
                                "candidate_score": score_map.get(token_key),
                                "candidate_coverage_status": "visible",
                                "decision": "rejected_already_visible",
                            }
                        )
                        visible_rejections_recorded += 1
                        rejection_codes.append("rejected_already_visible")
                if not hidden_claims:
                    candidate_search_summaries.append(search_summary)
                    candidate_search_lookup[claim_key] = search_summary
                    dispositions.append(
                        self.build_disposition(
                            claim=claim,
                            coverage_status=target_status,
                            final_action="kept",
                            reason="no_supported_retained_replacement_available",
                            distinctive_tokens_required=list(claim_coverage_lookup.get(claim_key, {}).get("distinctive_tokens_required", [])),
                            distinctive_tokens_matched=list(claim_coverage_lookup.get(claim_key, {}).get("distinctive_tokens_matched", [])),
                            replacement_search_performed=True,
                            replacement_candidates_available=0,
                            supported_replacement_candidates_available=0,
                            supported_replacement_candidates_available_raw=0,
                            usable_supported_replacement_candidates_available=0,
                            rejection_summary=sorted(dict.fromkeys(rejection_codes)) or [
                                "All supported retained skills were already visible or no supported retained skills remained."
                            ],
                            remaining_supported_retained_skills_not_visible=[],
                        )
                    )
                    continue

                hidden_coverage = build_claim_coverage_for_claims_fn(
                    claims=hidden_claims,
                    model=current_model,
                    prepared=current_prepared,
                )
                hidden_lookup = {self._normalize_skill_claim_key(item.claim): item for item in hidden_coverage}
                supported_hidden_candidates = [
                    token
                    for token in hidden_claims
                    if (hidden_lookup.get(self._normalize_skill_claim_key(token)) is not None)
                    and hidden_lookup[self._normalize_skill_claim_key(token)].coverage_status == "supported"
                ]
                search_summary["supported_non_visible_candidates_count"] = len(supported_hidden_candidates)
                source_score = score_map.get(claim_key)
                ranked_hidden = sorted(
                    hidden_claims,
                    key=lambda token: (
                        score_map.get(self._normalize_skill_claim_key(token), float("-inf")),
                        -all_claims.index(token),
                    ),
                    reverse=True,
                )
                replacement: str | None = None
                replacement_reject_reason = "no_supported_retained_replacement_available"
                for token in ranked_hidden:
                    token_key = self._normalize_skill_claim_key(token)
                    coverage = hidden_lookup.get(token_key)
                    candidate_score = score_map.get(token_key)
                    decision = {
                        "claim": claim,
                        "claim_status": target_status,
                        "candidate": token,
                        "candidate_score": candidate_score,
                        "candidate_coverage_status": coverage.coverage_status if coverage else "missing",
                        "decision": "considered",
                    }
                    if token_key in used_candidates:
                        decision["decision"] = "rejected_already_used"
                        candidates_considered.append(decision)
                        rejection_codes.append("rejected_already_used")
                        continue
                    if coverage is None or coverage.coverage_status != "supported":
                        decision["decision"] = "rejected_not_supported"
                        candidates_considered.append(decision)
                        rejection_codes.append("rejected_not_supported")
                        continue
                    if self.alias_conflict(candidate=token, visible_claims=visible_claims, claim_being_replaced=claim):
                        decision["decision"] = "rejected_alias_conflict"
                        replacement_reject_reason = "replacement_duplicate_or_alias_conflict"
                        candidates_considered.append(decision)
                        rejection_codes.append("rejected_alias_conflict")
                        continue
                    if target_status == "weak" and source_score is not None and candidate_score is not None:
                        if candidate_score + 6.0 < source_score:
                            decision["decision"] = "rejected_lower_relevance"
                            candidates_considered.append(decision)
                            rejection_codes.append("rejected_lower_relevance")
                            continue
                    decision["decision"] = "selected"
                    candidates_considered.append(decision)
                    replacement = token
                    break

                if not replacement:
                    search_summary["result"] = replacement_reject_reason
                    candidate_search_summaries.append(search_summary)
                    candidate_search_lookup[claim_key] = search_summary
                    dispositions.append(
                        self.build_disposition(
                            claim=claim,
                            coverage_status=target_status,
                            final_action="kept",
                            reason=replacement_reject_reason,
                            distinctive_tokens_required=list(claim_coverage_lookup.get(claim_key, {}).get("distinctive_tokens_required", [])),
                            distinctive_tokens_matched=list(claim_coverage_lookup.get(claim_key, {}).get("distinctive_tokens_matched", [])),
                            replacement_search_performed=True,
                            replacement_candidates_available=len(hidden_claims),
                            supported_replacement_candidates_available=len(supported_hidden_candidates),
                            supported_replacement_candidates_available_raw=len(supported_hidden_candidates),
                            usable_supported_replacement_candidates_available=len(supported_hidden_candidates),
                            rejection_summary=sorted(dict.fromkeys(rejection_codes)) or [
                                "All supported retained skills were already visible or no supported retained skills remained."
                            ],
                            remaining_supported_retained_skills_not_visible=supported_hidden_candidates,
                        )
                    )
                    continue

                swapped_model = clone_model_with_swapped_skills_fn(current_model, claim, replacement)
                if swapped_model is None:
                    dispositions.append(
                        self.build_disposition(
                            claim=claim,
                            coverage_status=target_status,
                            final_action="kept",
                            reason="replacement_duplicate_or_alias_conflict",
                            distinctive_tokens_required=list(claim_coverage_lookup.get(claim_key, {}).get("distinctive_tokens_required", [])),
                            distinctive_tokens_matched=list(claim_coverage_lookup.get(claim_key, {}).get("distinctive_tokens_matched", [])),
                            replacement_search_performed=True,
                            replacement_candidates_available=len(hidden_claims),
                            supported_replacement_candidates_available=len(supported_hidden_candidates),
                            supported_replacement_candidates_available_raw=len(supported_hidden_candidates),
                            usable_supported_replacement_candidates_available=len(supported_hidden_candidates),
                            rejection_summary=sorted(dict.fromkeys(rejection_codes + ["rejected_alias_conflict"])),
                            remaining_supported_retained_skills_not_visible=supported_hidden_candidates,
                        )
                    )
                    continue
                swapped_html, swapped_prepared, swapped_planning, measured_pages, fit = _render_rebuild(swapped_model)
                op = PlanningOperation(
                    step="evidence_aware_skill_replacement",
                    claim=claim,
                    replacement=replacement,
                    reason="weak_or_unsupported_claim_replaced_by_supported_retained_skill",
                    fit=fit,
                    metadata={
                        "from": claim,
                        "to": replacement,
                        "measured_pages": measured_pages,
                        "kept": bool(fit),
                    },
                ).to_report_dict()
                adjustments.append(op)
                planning_step_ops.append(op)
                if fit:
                    search_summary["result"] = "replaced_by_supported_retained_skill"
                    candidate_search_summaries.append(search_summary)
                    candidate_search_lookup[claim_key] = search_summary
                    current_model = swapped_model
                    current_html = swapped_html
                    current_prepared = swapped_prepared
                    current_planning = swapped_planning
                    used_candidates.add(self._normalize_skill_claim_key(replacement))
                    replaced_claim_keys.add(claim_key)
                    dispositions.append(
                        self.build_disposition(
                            claim=claim,
                            coverage_status=target_status,
                            final_action="replaced",
                            reason="replaced_by_supported_retained_skill",
                            replacement=replacement,
                            distinctive_tokens_required=list(claim_coverage_lookup.get(claim_key, {}).get("distinctive_tokens_required", [])),
                            distinctive_tokens_matched=list(claim_coverage_lookup.get(claim_key, {}).get("distinctive_tokens_matched", [])),
                            replacement_search_performed=True,
                            replacement_candidates_available=len(hidden_claims),
                            supported_replacement_candidates_available=len(supported_hidden_candidates),
                            supported_replacement_candidates_available_raw=len(supported_hidden_candidates),
                            usable_supported_replacement_candidates_available=len(supported_hidden_candidates),
                            rejection_summary=sorted(dict.fromkeys(rejection_codes)),
                            remaining_supported_retained_skills_not_visible=supported_hidden_candidates,
                        )
                    )
                else:
                    rejection_codes.append("rejected_page_overflow")
                    search_summary["result"] = "replacement_would_overflow_page_target"
                    candidate_search_summaries.append(search_summary)
                    candidate_search_lookup[claim_key] = search_summary
                    dispositions.append(
                        self.build_disposition(
                            claim=claim,
                            coverage_status=target_status,
                            final_action="kept",
                            reason="replacement_would_overflow_page_target",
                            distinctive_tokens_required=list(claim_coverage_lookup.get(claim_key, {}).get("distinctive_tokens_required", [])),
                            distinctive_tokens_matched=list(claim_coverage_lookup.get(claim_key, {}).get("distinctive_tokens_matched", [])),
                            replacement_search_performed=True,
                            replacement_candidates_available=len(hidden_claims),
                            supported_replacement_candidates_available=len(supported_hidden_candidates),
                            supported_replacement_candidates_available_raw=len(supported_hidden_candidates),
                            usable_supported_replacement_candidates_available=len(supported_hidden_candidates),
                            rejection_summary=sorted(dict.fromkeys(rejection_codes)),
                            remaining_supported_retained_skills_not_visible=supported_hidden_candidates,
                        )
                    )

        return SkillReplacementPassResult(
            model=current_model,
            html=current_html,
            prepared=current_prepared,
            planning=current_planning,
            adjustments=adjustments,
            planning_step_ops=planning_step_ops,
            dispositions=dispositions,
            candidates_considered=candidates_considered,
            candidate_search_summaries=candidate_search_summaries,
            candidate_search_lookup=candidate_search_lookup,
            used_candidates=used_candidates,
            replaced_claim_keys=replaced_claim_keys,
        )

    def remove_unsupported_claims_until_stable(
        self,
        *,
        model: ResumeRenderModel,
        html: str,
        prepared: Any,
        planning: dict[str, Any],
        context: SkillRepairContext,
        min_visible_skill_count: int,
        dispositions: list[SkillDisposition],
        candidate_search_lookup: dict[str, dict[str, Any]],
        used_candidates: set[str],
        replaced_claim_keys: set[str],
        planning_step_ops: list[dict[str, Any]],
        unsupported_skill_removals: list[dict[str, Any]],
        score_map: dict[str, float],
        adjustments: list[dict[str, Any]],
        build_claim_coverage_for_claims_fn: Callable[..., list[Any]],
        extract_all_skill_claims_fn: Callable[[ResumeRenderModel], list[str]],
        clone_model_without_skill_fn: Callable[[ResumeRenderModel, str], ResumeRenderModel | None],
        measured_fit_fn: Callable[[dict[str, Any]], tuple[int | None, bool]],
        build_html_and_prepared_fn: Callable[..., tuple[str, Any]],
        build_planning_with_evidence_fn: Callable[..., dict[str, Any]],
    ) -> SkillUnsupportedRemovalResult:
        current_model = model
        current_html = html
        current_prepared = prepared
        current_planning = planning
        render_service = context.render_planning_service or self._render_planning_service
        render_context = RenderPlanningContext(
            template_name=context.template_name,
            job_description=context.job_description,
        )
        planning_step_ops = list(planning_step_ops)
        unsupported_skill_removals = list(unsupported_skill_removals)
        removed_claim_keys: set[str] = set()
        dispositions_by_key = {
            self._normalize_skill_claim_key(item.claim): item
            for item in dispositions
            if isinstance(item, SkillDisposition)
        }

        def _render_rebuild(next_model: ResumeRenderModel) -> tuple[str, Any, dict[str, Any], int | None, bool]:
            if render_service is not None:
                next_state = render_service.rebuild_state(
                    model=next_model,
                    context=render_context,
                )
                measured_pages, fit = render_service.measured_fit(next_state)
                return next_state.html, next_state.prepared, next_state.planning, measured_pages, fit
            next_html, next_prepared = build_html_and_prepared_fn(next_model, template_name=context.template_name)
            next_planning = build_planning_with_evidence_fn(
                model=next_model,
                prepared=next_prepared,
                template_name=context.template_name,
                job_description=context.job_description,
            )
            measured_pages, fit = measured_fit_fn(next_planning)
            return next_html, next_prepared, next_planning, measured_pages, fit

        while True:
            removal_made = False
            unsupported_targets = [
                str(claim).strip()
                for claim in current_planning.get("unsupported_visible_claims", [])
                if str(claim).strip()
            ]
            weak_targets: list[str] = []
            weak_claim_items = [item for item in current_planning.get("claim_coverage", []) if isinstance(item, dict)]
            weak_lookup = {
                self._normalize_skill_claim_key(str(item.get("claim", ""))): item for item in weak_claim_items
            }
            for claim in current_planning.get("weak_visible_claims", []):
                claim_text = str(claim).strip()
                if not claim_text:
                    continue
                item = weak_lookup.get(self._normalize_skill_claim_key(claim_text), {})
                if str(item.get("coverage_status", "")) in {"weak_summary_only", "weak"}:
                    weak_targets.append(claim_text)
            removal_targets = list(dict.fromkeys([*unsupported_targets, *weak_targets]))
            if not removal_targets:
                break

            for claim in removal_targets:
                claim_key = self._normalize_skill_claim_key(claim)
                claim_coverage_items = [item for item in current_planning.get("claim_coverage", []) if isinstance(item, dict)]
                claim_coverage_lookup = {
                    self._normalize_skill_claim_key(str(item.get("claim", ""))): item for item in claim_coverage_items
                }
                coverage_item = claim_coverage_lookup.get(claim_key, {})
                claim_status = str(coverage_item.get("coverage_status", ""))
                if claim_status not in {"unsupported", "weak_summary_only", "weak"}:
                    continue
                if int(coverage_item.get("retained_primary_supporting_evidence_count", 0) or 0) > 0:
                    continue

                supported_candidates_raw, usable_candidates = self.find_usable_supported_replacements_for_claim(
                    claim=claim,
                    claim_status=claim_status,
                    model=current_model,
                    prepared=current_prepared,
                    planning=current_planning,
                    used_candidate_keys=used_candidates,
                    score_map=score_map,
                    adjustments=adjustments,
                    build_claim_coverage_for_claims_fn=build_claim_coverage_for_claims_fn,
                    extract_all_skill_claims_fn=extract_all_skill_claims_fn,
                )
                if usable_candidates:
                    disp = dispositions_by_key.get(claim_key)
                    if isinstance(disp, SkillDisposition):
                        disp.metadata["replacement_candidates_available"] = max(
                            int(disp.metadata.get("replacement_candidates_available", 0) or 0),
                            len(supported_candidates_raw),
                        )
                        disp.metadata["supported_replacement_candidates_available"] = len(usable_candidates)
                        disp.supported_replacement_candidates_available_raw = len(supported_candidates_raw)
                        disp.usable_supported_replacement_candidates_available = len(usable_candidates)
                        disp.metadata["remaining_supported_retained_skills_not_visible"] = list(usable_candidates)
                    continue

                visible_before, _ = self.visible_skill_count_and_names(
                    model=current_model,
                    prepared=current_prepared,
                    planning=current_planning,
                )
                removal_reason = (
                    "unsupported_visible_claim_no_supported_replacement_no_source_evidence"
                    if claim_status == "unsupported"
                    else (
                        "weak_summary_only_visible_claim_no_supported_replacement_no_primary_evidence"
                        if claim_status == "weak_summary_only"
                        else "weak_visible_claim_no_supported_replacement_no_retained_primary_evidence"
                    )
                )
                removal_record: dict[str, Any] = {
                    "claim": claim,
                    "coverage_status": claim_status,
                    "reason": removal_reason,
                    "visible_skill_count_before": visible_before,
                    "min_visible_skill_count": min_visible_skill_count,
                    "kept": False,
                    "operation_kept": False,
                    "removal_applied": False,
                    "claim_removed": False,
                }
                op = PlanningOperation(
                    step="unsupported_skill_removal",
                    claim=claim,
                    reason=removal_reason,
                    visible_skill_count_before=visible_before,
                    metadata={"from": claim},
                ).to_report_dict()

                if visible_before - 1 < min_visible_skill_count:
                    removal_record["visible_skill_count_after"] = visible_before
                    removal_record["revert_reason"] = "visible_skill_count_below_minimum"
                    op["kept"] = False
                    op["operation_kept"] = False
                    op["removal_applied"] = False
                    op["fit"] = True
                    op["measured_pages"] = current_planning.get("measured_pages_final")
                    op["revert_reason"] = "visible_skill_count_below_minimum"
                    unsupported_skill_removals.append(removal_record)
                    planning_step_ops.append(op)
                    disp = dispositions_by_key.get(claim_key)
                    if isinstance(disp, SkillDisposition):
                        disp.reason = "min_visible_skill_count_guard"
                        disp.metadata["replacement_candidates_available"] = max(
                            int(disp.metadata.get("replacement_candidates_available", 0) or 0),
                            len(supported_candidates_raw),
                        )
                        disp.metadata["supported_replacement_candidates_available"] = len(usable_candidates)
                        disp.supported_replacement_candidates_available_raw = len(supported_candidates_raw)
                        disp.usable_supported_replacement_candidates_available = len(usable_candidates)
                        disp.metadata["remaining_supported_retained_skills_not_visible"] = list(usable_candidates)
                    continue

                next_model = clone_model_without_skill_fn(current_model, claim)
                if next_model is None:
                    removal_record["visible_skill_count_after"] = visible_before
                    removal_record["revert_reason"] = "unable_to_remove_claim"
                    op["kept"] = False
                    op["operation_kept"] = False
                    op["removal_applied"] = False
                    op["fit"] = True
                    op["measured_pages"] = current_planning.get("measured_pages_final")
                    op["revert_reason"] = "unable_to_remove_claim"
                    unsupported_skill_removals.append(removal_record)
                    planning_step_ops.append(op)
                    continue

                next_html, next_prepared, next_planning, measured_pages, fit = _render_rebuild(next_model)
                visible_after, _ = self.visible_skill_count_and_names(
                    model=next_model,
                    prepared=next_prepared,
                    planning=next_planning,
                )
                removal_record["visible_skill_count_after"] = visible_after
                removal_record["measured_pages"] = measured_pages
                removal_record["fit"] = fit
                op["measured_pages"] = measured_pages
                op["fit"] = fit

                if fit and visible_after >= min_visible_skill_count:
                    removal_record["kept"] = True
                    removal_record["operation_kept"] = True
                    removal_record["removal_applied"] = True
                    removal_record["claim_removed"] = True
                    op["kept"] = True
                    op["operation_kept"] = True
                    op["removal_applied"] = True
                    current_model = next_model
                    current_html = next_html
                    current_prepared = next_prepared
                    current_planning = next_planning
                    removed_claim_keys.add(claim_key)
                    disp = dispositions_by_key.get(claim_key)
                    if isinstance(disp, SkillDisposition):
                        remove_disposition_reason = (
                            "unsupported_no_replacement_no_source_evidence"
                            if claim_status == "unsupported"
                            else (
                                "weak_summary_only_no_replacement_no_primary_evidence"
                                if claim_status == "weak_summary_only"
                                else "weak_no_replacement_no_retained_primary_evidence"
                            )
                        )
                        disp.mark_removed(remove_disposition_reason)
                        disp.metadata["replacement_candidates_available"] = max(
                            int(disp.metadata.get("replacement_candidates_available", 0) or 0),
                            len(supported_candidates_raw),
                        )
                        disp.metadata["supported_replacement_candidates_available"] = len(usable_candidates)
                        disp.supported_replacement_candidates_available_raw = len(supported_candidates_raw)
                        disp.usable_supported_replacement_candidates_available = len(usable_candidates)
                        disp.metadata["remaining_supported_retained_skills_not_visible"] = list(usable_candidates)
                    else:
                        remove_disposition_reason = (
                            "unsupported_no_replacement_no_source_evidence"
                            if claim_status == "unsupported"
                            else (
                                "weak_summary_only_no_replacement_no_primary_evidence"
                                if claim_status == "weak_summary_only"
                                else "weak_no_replacement_no_retained_primary_evidence"
                            )
                        )
                        new_disp = self.build_disposition(
                            claim=claim,
                            coverage_status=claim_status,
                            final_action="removed",
                            reason=remove_disposition_reason,
                            replacement_search_performed=True,
                            replacement_candidates_available=len(supported_candidates_raw),
                            supported_replacement_candidates_available=len(usable_candidates),
                            supported_replacement_candidates_available_raw=len(supported_candidates_raw),
                            usable_supported_replacement_candidates_available=len(usable_candidates),
                            rejection_summary=["no_supported_retained_replacement_available"],
                            remaining_supported_retained_skills_not_visible=list(usable_candidates),
                        )
                        new_disp.mark_removed(remove_disposition_reason)
                        dispositions.append(new_disp)
                        dispositions_by_key[claim_key] = new_disp
                    unsupported_skill_removals.append(removal_record)
                    planning_step_ops.append(op)
                    removal_made = True
                    break
                else:
                    op["kept"] = False
                    op["operation_kept"] = False
                    op["removal_applied"] = False
                    removal_record["kept"] = False
                    removal_record["operation_kept"] = False
                    removal_record["removal_applied"] = False
                    removal_record["claim_removed"] = False
                    removal_record["revert_reason"] = (
                        "visible_skill_count_below_minimum" if visible_after < min_visible_skill_count else "page_fit_failed"
                    )
                    op["revert_reason"] = removal_record["revert_reason"]
                    unsupported_skill_removals.append(removal_record)
                    planning_step_ops.append(op)

            if not removal_made:
                break

        return SkillUnsupportedRemovalResult(
            model=current_model,
            html=current_html,
            prepared=current_prepared,
            planning=current_planning,
            unsupported_skill_removals=unsupported_skill_removals,
            planning_step_ops=planning_step_ops,
            dispositions=dispositions,
            removed_claim_keys=removed_claim_keys,
        )

    def finalize_repair_report(
        self,
        *,
        planning: dict[str, Any],
        planning_step_ops: list[dict[str, Any]],
        preserved_attempts: list[dict[str, Any]],
        preserved_decisions: list[dict[str, Any]],
        unsupported_before: list[str],
        weak_before: list[str],
        adjustments: list[dict[str, Any]],
        unsupported_skill_removals: list[dict[str, Any]],
        candidates_considered: list[dict[str, Any]],
        candidate_search_summaries: list[dict[str, Any]],
        candidate_search_lookup: dict[str, dict[str, Any]],
        dispositions: list[SkillDisposition],
        replaced_claim_keys: set[str],
        removed_claim_keys: set[str],
        summary_claim_repairs: list[dict[str, Any]],
        removed_or_rewritten_summary_claims: list[str],
        summary_claims_final_unresolved: list[str],
        compound_skill_repairs: list[dict[str, Any]],
        unsupported_compound_subclaims_removed: list[str],
        compound_skill_claims_final_unresolved: list[str],
    ) -> dict[str, Any]:
        current_planning = planning
        dispositions_by_key = {
            self._normalize_skill_claim_key(item.claim): item
            for item in dispositions
            if isinstance(item, SkillDisposition)
        }

        def _default_kept_reason_for_claim(claim_key: str) -> str:
            summary = candidate_search_lookup.get(claim_key, {})
            result = str(summary.get("result", "")).strip()
            if result:
                return result
            return "no_supported_retained_replacement_available"

        existing_ops = current_planning.get("planning_operations")
        if not isinstance(existing_ops, list):
            existing_ops = []
        if planning_step_ops:
            current_planning["planning_operations"] = [*existing_ops, *planning_step_ops]

        final_claim_coverage = [item for item in current_planning.get("claim_coverage", []) if isinstance(item, dict)]
        final_lookup = {
            self._normalize_skill_claim_key(str(item.get("claim", ""))): item for item in final_claim_coverage
        }
        final_visible_claim_keys = set(final_lookup.keys())
        for claim_key, disp in list(dispositions_by_key.items()):
            if not isinstance(disp, SkillDisposition):
                continue
            if claim_key in removed_claim_keys:
                continue
            if claim_key in final_visible_claim_keys and disp.final_action == "replaced":
                status = str(final_lookup.get(claim_key, {}).get("coverage_status", "unsupported"))
                disp.final_action = "kept"
                disp.coverage_status = status
                disp.reason = _default_kept_reason_for_claim(claim_key)

        for claim in current_planning.get("unsupported_visible_claims", []):
            key = self._normalize_skill_claim_key(str(claim))
            if key in replaced_claim_keys:
                continue
            if key in removed_claim_keys:
                continue
            if any(self._normalize_skill_claim_key(item.claim) == key for item in dispositions):
                continue
            status = str(final_lookup.get(key, {}).get("coverage_status", "unsupported"))
            dispositions.append(
                self.build_disposition(
                    claim=str(claim),
                    coverage_status=status,
                    final_action="kept",
                    reason="no_supported_retained_replacement_available",
                    distinctive_tokens_required=list(final_lookup.get(key, {}).get("distinctive_tokens_required", [])),
                    distinctive_tokens_matched=list(final_lookup.get(key, {}).get("distinctive_tokens_matched", [])),
                    replacement_search_performed=bool(candidate_search_lookup.get(key)),
                    replacement_candidates_available=(
                        int(candidate_search_lookup.get(key, {}).get("non_visible_retained_candidates_count", 0))
                        if candidate_search_lookup.get(key)
                        else 0
                    ),
                    supported_replacement_candidates_available=(
                        int(candidate_search_lookup.get(key, {}).get("supported_non_visible_candidates_count", 0))
                        if candidate_search_lookup.get(key)
                        else 0
                    ),
                    supported_replacement_candidates_available_raw=(
                        int(candidate_search_lookup.get(key, {}).get("supported_non_visible_candidates_count", 0))
                        if candidate_search_lookup.get(key)
                        else 0
                    ),
                    usable_supported_replacement_candidates_available=(
                        int(candidate_search_lookup.get(key, {}).get("supported_non_visible_candidates_count", 0))
                        if candidate_search_lookup.get(key)
                        else 0
                    ),
                    rejection_summary=(
                        [str(candidate_search_lookup.get(key, {}).get("result", "no_supported_retained_replacement_available"))]
                        if candidate_search_lookup.get(key)
                        else ["no_supported_retained_replacement_available"]
                    ),
                    remaining_supported_retained_skills_not_visible=[],
                )
            )
        for claim in current_planning.get("weak_visible_claims", []):
            key = self._normalize_skill_claim_key(str(claim))
            if key in replaced_claim_keys:
                continue
            if key in removed_claim_keys:
                continue
            if any(self._normalize_skill_claim_key(item.claim) == key for item in dispositions):
                continue
            status = str(final_lookup.get(key, {}).get("coverage_status", "weak"))
            dispositions.append(
                self.build_disposition(
                    claim=str(claim),
                    coverage_status=status,
                    final_action="kept",
                    reason="no_supported_retained_replacement_available",
                    distinctive_tokens_required=list(final_lookup.get(key, {}).get("distinctive_tokens_required", [])),
                    distinctive_tokens_matched=list(final_lookup.get(key, {}).get("distinctive_tokens_matched", [])),
                    replacement_search_performed=bool(candidate_search_lookup.get(key)),
                    replacement_candidates_available=(
                        int(candidate_search_lookup.get(key, {}).get("non_visible_retained_candidates_count", 0))
                        if candidate_search_lookup.get(key)
                        else 0
                    ),
                    supported_replacement_candidates_available=(
                        int(candidate_search_lookup.get(key, {}).get("supported_non_visible_candidates_count", 0))
                        if candidate_search_lookup.get(key)
                        else 0
                    ),
                    supported_replacement_candidates_available_raw=(
                        int(candidate_search_lookup.get(key, {}).get("supported_non_visible_candidates_count", 0))
                        if candidate_search_lookup.get(key)
                        else 0
                    ),
                    usable_supported_replacement_candidates_available=(
                        int(candidate_search_lookup.get(key, {}).get("supported_non_visible_candidates_count", 0))
                        if candidate_search_lookup.get(key)
                        else 0
                    ),
                    rejection_summary=(
                        [str(candidate_search_lookup.get(key, {}).get("result", "no_supported_retained_replacement_available"))]
                        if candidate_search_lookup.get(key)
                        else ["no_supported_retained_replacement_available"]
                    ),
                    remaining_supported_retained_skills_not_visible=[],
                )
            )

        current_planning["evidence_preservation_attempts"] = preserved_attempts
        current_planning["evidence_preservation_decisions"] = preserved_decisions
        current_planning["unsupported_visible_claims_before_preservation"] = unsupported_before
        current_planning["weak_visible_claims_before_preservation"] = weak_before
        current_planning["evidence_aware_skill_adjustments"] = adjustments
        current_planning["unsupported_skill_removals"] = unsupported_skill_removals
        current_planning["supported_replacement_candidates_considered"] = candidates_considered
        current_planning["supported_replacement_candidate_searches"] = candidate_search_summaries
        current_planning["final_weak_or_unsupported_claim_dispositions"] = [item.to_report_dict() for item in dispositions]
        current_planning["unsupported_visible_claims_final"] = list(current_planning.get("unsupported_visible_claims", []))
        current_planning["weak_visible_claims_final"] = list(current_planning.get("weak_visible_claims", []))
        current_planning["summary_claim_repairs"] = summary_claim_repairs
        current_planning["removed_or_rewritten_summary_claims"] = list(dict.fromkeys(removed_or_rewritten_summary_claims))
        current_planning["summary_claims_final_unresolved"] = list(dict.fromkeys(summary_claims_final_unresolved))
        current_planning["compound_skill_repairs"] = list(compound_skill_repairs)
        current_planning["grouped_skill_repairs"] = list(compound_skill_repairs)
        current_planning["unsupported_compound_subclaims_removed"] = list(
            dict.fromkeys(unsupported_compound_subclaims_removed)
        )
        current_planning["compound_skill_claims_final_unresolved"] = list(
            dict.fromkeys(compound_skill_claims_final_unresolved)
        )
        rendered_visible_skill_names: list[str] = []
        seen_rendered: set[str] = set()
        for item in final_claim_coverage:
            claim = str(item.get("claim", "")).strip()
            if not claim:
                continue
            key = self._normalize_skill_claim_key(claim)
            if key in seen_rendered:
                continue
            seen_rendered.add(key)
            rendered_visible_skill_names.append(claim)
        current_planning["rendered_visible_skill_names"] = rendered_visible_skill_names
        current_planning["rendered_visible_skill_count"] = len(rendered_visible_skill_names)
        current_planning["unsupported_visible_claims_without_source_evidence"] = [
            {"claim": item.get("claim"), "reason": "no_primary_source_evidence_found"}
            for item in current_planning.get("claim_coverage", [])
            if isinstance(item, dict)
            and str(item.get("coverage_status")) == "unsupported"
            and int(item.get("primary_supporting_evidence_count", 0) or 0) == 0
        ]
        return current_planning

    def repair(
        self,
        *,
        model: ResumeRenderModel,
        html: str,
        prepared: Any,
        planning: dict[str, Any],
        context: SkillRepairContext,
    ) -> SkillRepairResult:
        deps = self._dependencies
        if deps is not None:
            adjustments: list[dict[str, Any]] = []
            planning_step_ops: list[dict[str, Any]] = []
            unsupported_skill_removals: list[dict[str, Any]] = []
            dispositions: list[SkillDisposition] = []
            candidates_considered: list[dict[str, Any]] = []
            candidate_search_summaries: list[dict[str, Any]] = []
            candidate_search_lookup: dict[str, dict[str, Any]] = {}
            compound_skill_repairs: list[dict[str, Any]] = []
            unsupported_compound_subclaims_removed: list[str] = []
            compound_skill_claims_final_unresolved: list[str] = []
            score_map = deps.skill_score_map_from_selection_fn(context.skills_selection)
            current_model = model
            current_html = html
            current_prepared = prepared
            current_planning = planning
            preserved_attempts = list(planning.get("evidence_preservation_attempts", [])) if isinstance(
                planning.get("evidence_preservation_attempts"), list
            ) else []
            preserved_decisions = list(planning.get("evidence_preservation_decisions", [])) if isinstance(
                planning.get("evidence_preservation_decisions"), list
            ) else []
            unsupported_before = list(planning.get("unsupported_visible_claims_before_preservation", []))
            weak_before = list(planning.get("weak_visible_claims_before_preservation", []))
            used_candidates: set[str] = set()
            replaced_claim_keys: set[str] = set()
            min_visible_skill_count = 12
            if isinstance(context.skills_selection, dict):
                try:
                    min_visible_skill_count = max(1, int(context.skills_selection.get("min_count", min_visible_skill_count)))
                except (TypeError, ValueError):
                    min_visible_skill_count = 12

            replacement_result = self.apply_replacements(
                model=current_model,
                html=current_html,
                prepared=current_prepared,
                planning=current_planning,
                context=SkillRepairContext(
                    template_name=context.template_name,
                    job_description=context.job_description,
                    skills_selection=context.skills_selection,
                    render_planning_service=context.render_planning_service or self._render_planning_service,
                ),
                score_map=score_map,
                used_candidates=used_candidates,
                replaced_claim_keys=replaced_claim_keys,
                adjustments=adjustments,
                planning_step_ops=planning_step_ops,
                dispositions=dispositions,
                candidates_considered=candidates_considered,
                candidate_search_summaries=candidate_search_summaries,
                candidate_search_lookup=candidate_search_lookup,
                build_claim_coverage_for_claims_fn=deps.build_claim_coverage_for_claims_fn,
                extract_all_skill_claims_fn=deps.extract_all_skill_claims_fn,
                clone_model_with_swapped_skills_fn=deps.clone_model_with_swapped_skills_fn,
                measured_fit_fn=deps.measured_fit_fn,
                build_html_and_prepared_fn=deps.build_html_and_prepared_fn,
                build_planning_with_evidence_fn=deps.build_planning_with_evidence_fn,
            )
            current_model = replacement_result.model
            current_html = replacement_result.html
            current_prepared = replacement_result.prepared
            current_planning = replacement_result.planning
            adjustments = replacement_result.adjustments
            planning_step_ops = replacement_result.planning_step_ops
            dispositions = replacement_result.dispositions
            candidates_considered = replacement_result.candidates_considered
            candidate_search_summaries = replacement_result.candidate_search_summaries
            candidate_search_lookup = replacement_result.candidate_search_lookup
            used_candidates = replacement_result.used_candidates
            replaced_claim_keys = replacement_result.replaced_claim_keys

            removal_result = self.remove_unsupported_claims_until_stable(
                model=current_model,
                html=current_html,
                prepared=current_prepared,
                planning=current_planning,
                context=SkillRepairContext(
                    template_name=context.template_name,
                    job_description=context.job_description,
                    skills_selection=context.skills_selection,
                    render_planning_service=context.render_planning_service or self._render_planning_service,
                ),
                min_visible_skill_count=min_visible_skill_count,
                dispositions=dispositions,
                candidate_search_lookup=candidate_search_lookup,
                used_candidates=used_candidates,
                replaced_claim_keys=replaced_claim_keys,
                planning_step_ops=planning_step_ops,
                unsupported_skill_removals=unsupported_skill_removals,
                score_map=score_map,
                adjustments=adjustments,
                build_claim_coverage_for_claims_fn=deps.build_claim_coverage_for_claims_fn,
                extract_all_skill_claims_fn=deps.extract_all_skill_claims_fn,
                clone_model_without_skill_fn=deps.clone_model_without_skill_fn,
                measured_fit_fn=deps.measured_fit_fn,
                build_html_and_prepared_fn=deps.build_html_and_prepared_fn,
                build_planning_with_evidence_fn=deps.build_planning_with_evidence_fn,
            )
            current_model = removal_result.model
            current_html = removal_result.html
            current_prepared = removal_result.prepared
            current_planning = removal_result.planning
            unsupported_skill_removals = removal_result.unsupported_skill_removals
            planning_step_ops = removal_result.planning_step_ops
            dispositions = removal_result.dispositions
            removed_claim_keys = removal_result.removed_claim_keys
            removed_unsupported_claim_keys: set[str] = set()
            for disp in dispositions:
                if not isinstance(disp, SkillDisposition):
                    continue
                if disp.final_action != "removed":
                    continue
                if str(disp.coverage_status) != "unsupported":
                    continue
                key = self._normalize_skill_claim_key(disp.claim)
                if key:
                    removed_unsupported_claim_keys.add(key)
            for item in unsupported_skill_removals:
                if not isinstance(item, dict):
                    continue
                if not bool(item.get("claim_removed")):
                    continue
                if str(item.get("coverage_status", "")) != "unsupported":
                    continue
                claim = str(item.get("claim", "")).strip()
                key = self._normalize_skill_claim_key(claim)
                if key:
                    removed_unsupported_claim_keys.add(key)
            (
                current_model,
                current_html,
                current_prepared,
                current_planning,
                compound_skill_repairs,
                unsupported_compound_subclaims_removed,
                compound_skill_claims_final_unresolved,
            ) = self.apply_compound_skill_repairs(
                model=current_model,
                html=current_html,
                prepared=current_prepared,
                planning=current_planning,
                context=SkillRepairContext(
                    template_name=context.template_name,
                    job_description=context.job_description,
                    skills_selection=context.skills_selection,
                    render_planning_service=context.render_planning_service or self._render_planning_service,
                ),
                removed_unsupported_claim_keys=removed_unsupported_claim_keys,
                build_claim_coverage_for_claims_fn=deps.build_claim_coverage_for_claims_fn,
                build_html_and_prepared_fn=deps.build_html_and_prepared_fn,
                build_planning_with_evidence_fn=deps.build_planning_with_evidence_fn,
                measured_fit_fn=deps.measured_fit_fn,
            )
            (
                current_model,
                current_html,
                current_prepared,
                current_planning,
                summary_claim_repairs,
                removed_or_rewritten_summary_claims,
                summary_claims_final_unresolved,
            ) = self.apply_summary_claim_repairs(
                model=current_model,
                html=current_html,
                prepared=current_prepared,
                planning=current_planning,
                context=SkillRepairContext(
                    template_name=context.template_name,
                    job_description=context.job_description,
                    skills_selection=context.skills_selection,
                    render_planning_service=context.render_planning_service or self._render_planning_service,
                ),
                dispositions=dispositions,
                build_html_and_prepared_fn=deps.build_html_and_prepared_fn,
                build_planning_with_evidence_fn=deps.build_planning_with_evidence_fn,
                measured_fit_fn=deps.measured_fit_fn,
            )
            current_planning = self.finalize_repair_report(
                planning=current_planning,
                planning_step_ops=planning_step_ops,
                preserved_attempts=preserved_attempts,
                preserved_decisions=preserved_decisions,
                unsupported_before=unsupported_before,
                weak_before=weak_before,
                adjustments=adjustments,
                unsupported_skill_removals=unsupported_skill_removals,
                candidates_considered=candidates_considered,
                candidate_search_summaries=candidate_search_summaries,
                candidate_search_lookup=candidate_search_lookup,
                dispositions=dispositions,
                replaced_claim_keys=replaced_claim_keys,
                removed_claim_keys=removed_claim_keys,
                summary_claim_repairs=summary_claim_repairs,
                removed_or_rewritten_summary_claims=removed_or_rewritten_summary_claims,
                summary_claims_final_unresolved=summary_claims_final_unresolved,
                compound_skill_repairs=compound_skill_repairs,
                unsupported_compound_subclaims_removed=unsupported_compound_subclaims_removed,
                compound_skill_claims_final_unresolved=compound_skill_claims_final_unresolved,
            )
            model, html, prepared, planning = (
                current_model,
                current_html,
                current_prepared,
                current_planning,
            )
        elif self._apply_skill_repair is not None:
            model, html, prepared, planning = self._apply_skill_repair(
                model=model,
                html=html,
                prepared=prepared,
                planning=planning,
                template_name=context.template_name,
                job_description=context.job_description,
                skills_selection=context.skills_selection,
                render_planning_service=context.render_planning_service or self._render_planning_service,
                skill_repair_helpers=self,
            )
        else:
            raise NotImplementedError(
                "SkillRepairPlanner.repair requires direct dependencies or apply_skill_repair."
            )
        return SkillRepairResult(
            model=model,
            html=html,
            prepared=prepared,
            planning=planning,
        )

    @staticmethod
    def _normalize_skill_claim_key(value: str) -> str:
        return re.sub(r"\s+", " ", str(value).strip().lower())
