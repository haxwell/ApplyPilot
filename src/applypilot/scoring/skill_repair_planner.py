from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import re

from applypilot.resume.evidence import claim_variants, extract_visible_skill_claims
from applypilot.scoring.pdf_planning_types import SkillDisposition
from applypilot.scoring.pdf_render_model import ResumeRenderModel
from applypilot.scoring.render_planning_service import RenderPlanningService


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
