from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from applypilot.scoring.pdf_render_model import ResumeRenderModel


@dataclass
class SkillRepairContext:
    template_name: str
    job_description: str = ""
    skills_selection: dict[str, Any] | None = None


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

    def __init__(self, *, apply_skill_repair: SkillRepairFn) -> None:
        self._apply_skill_repair = apply_skill_repair

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
        )
        return SkillRepairResult(
            model=model,
            html=html,
            prepared=prepared,
            planning=planning,
        )
