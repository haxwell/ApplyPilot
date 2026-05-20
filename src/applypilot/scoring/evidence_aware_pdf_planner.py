from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from applypilot.scoring.pdf_render_model import ResumeRenderModel


@dataclass
class PdfPlanningContext:
    template_name: str
    job_description: str = ""
    skills_selection: dict[str, Any] | None = None


@dataclass
class PdfPlanningResult:
    model: ResumeRenderModel
    html: str
    prepared: Any
    planning: dict[str, Any]


PreservationFn = Callable[
    ...,
    tuple[ResumeRenderModel, str, Any, dict[str, Any]],
]
ReplacementFn = Callable[
    ...,
    tuple[ResumeRenderModel, str, Any, dict[str, Any]],
]


class EvidenceAwarePdfPlanner:
    """Thin orchestrator for evidence-aware PDF planning phases."""

    def __init__(
        self,
        *,
        apply_evidence_preservation: PreservationFn,
        apply_evidence_aware_skill_replacements: ReplacementFn,
    ) -> None:
        self._apply_evidence_preservation = apply_evidence_preservation
        self._apply_evidence_aware_skill_replacements = apply_evidence_aware_skill_replacements

    def plan(
        self,
        *,
        model: ResumeRenderModel,
        html: str,
        prepared: Any,
        planning: dict[str, Any],
        context: PdfPlanningContext,
    ) -> PdfPlanningResult:
        model, html, prepared, planning = self._apply_evidence_preservation(
            model=model,
            html=html,
            prepared=prepared,
            planning=planning,
            template_name=context.template_name,
            job_description=context.job_description,
        )
        model, html, prepared, planning = self._apply_evidence_aware_skill_replacements(
            model=model,
            html=html,
            prepared=prepared,
            planning=planning,
            template_name=context.template_name,
            job_description=context.job_description,
            skills_selection=context.skills_selection,
        )
        return PdfPlanningResult(
            model=model,
            html=html,
            prepared=prepared,
            planning=planning,
        )
