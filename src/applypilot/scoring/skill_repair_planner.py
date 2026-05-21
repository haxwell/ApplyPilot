from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import re

from applypilot.resume.evidence import claim_variants, extract_visible_skill_claims
from applypilot.scoring.pdf_planning_types import PlanningOperation, SkillDisposition
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


class SkillRepairPlanner:
    """Thin wrapper around the existing skill repair workflow."""

    def __init__(
        self,
        *,
        apply_skill_repair: SkillRepairFn,
        render_planning_service: RenderPlanningService | None = None,
        extract_visible_skill_claims_fn: Callable[[ResumeRenderModel, Any], list[str]] | None = None,
    ) -> None:
        self._apply_skill_repair = apply_skill_repair
        self._render_planning_service = render_planning_service
        self._extract_visible_skill_claims = extract_visible_skill_claims_fn or extract_visible_skill_claims

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

    def repair(
        self,
        *,
        model: ResumeRenderModel,
        html: str,
        prepared: Any,
        planning: dict[str, Any],
        context: SkillRepairContext,
    ) -> SkillRepairResult:
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
        return SkillRepairResult(
            model=model,
            html=html,
            prepared=prepared,
            planning=planning,
        )

    @staticmethod
    def _normalize_skill_claim_key(value: str) -> str:
        return re.sub(r"\s+", " ", str(value).strip().lower())
