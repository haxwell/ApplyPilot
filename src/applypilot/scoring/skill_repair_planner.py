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
