from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from applypilot.scoring.pdf_render_model import ResumeRenderModel
from applypilot.scoring.render_planning_service import RenderPlanningService
from applypilot.scoring.skill_repair_planner import (
    SkillRepairContext,
    SkillRepairPlanner,
)


@dataclass
class PdfPlanningContext:
    template_name: str
    job_description: str = ""
    skills_selection: dict[str, Any] | None = None
    render_planning_service: RenderPlanningService | None = None


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
class EvidenceAwarePdfPlanner:
    """Thin orchestrator for evidence-aware PDF planning phases."""

    def __init__(
        self,
        *,
        apply_evidence_preservation: PreservationFn,
        skill_repair_planner: SkillRepairPlanner,
    ) -> None:
        self._apply_evidence_preservation = apply_evidence_preservation
        self._skill_repair_planner = skill_repair_planner

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
        repair_result = self._skill_repair_planner.repair(
            model=model,
            html=html,
            prepared=prepared,
            planning=planning,
            context=SkillRepairContext(
                template_name=context.template_name,
                job_description=context.job_description,
                skills_selection=context.skills_selection,
                render_planning_service=context.render_planning_service,
            ),
        )
        return PdfPlanningResult(
            model=repair_result.model,
            html=repair_result.html,
            prepared=repair_result.prepared,
            planning=repair_result.planning,
        )
