from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from applypilot.resume.evidence import extract_visible_skill_claims
from applypilot.scoring.pdf_render_model import ResumeRenderModel


@dataclass
class RenderPlanningContext:
    template_name: str
    job_description: str = ""


@dataclass
class RenderPlanningState:
    model: ResumeRenderModel
    html: str
    prepared: Any
    planning: dict[str, Any]

    @property
    def measured_pages(self) -> int | None:
        measured = self.planning.get("measured_pages_final")
        return measured if isinstance(measured, int) and measured > 0 else None

    @property
    def fits_page_target(self) -> bool | None:
        allowed = self.planning.get("allowed_physical_pages")
        allowed_pages = allowed if isinstance(allowed, int) and allowed > 0 else None
        measured_pages = self.measured_pages
        if measured_pages is None or allowed_pages is None:
            return None
        return measured_pages <= allowed_pages


BuildHtmlAndPreparedFn = Callable[..., tuple[str, Any]]
BuildPlanningWithEvidenceFn = Callable[..., dict[str, Any]]
MeasuredFitFn = Callable[[dict[str, Any]], tuple[int | None, bool]]
ExtractVisibleSkillClaimsFn = Callable[[ResumeRenderModel, Any], list[str]]


class RenderPlanningService:
    def __init__(
        self,
        *,
        build_html_and_prepared: BuildHtmlAndPreparedFn,
        build_planning_with_evidence: BuildPlanningWithEvidenceFn,
        measured_fit: MeasuredFitFn,
        extract_visible_skill_claims_fn: ExtractVisibleSkillClaimsFn | None = None,
    ) -> None:
        self._build_html_and_prepared = build_html_and_prepared
        self._build_planning_with_evidence = build_planning_with_evidence
        self._measured_fit = measured_fit
        self._extract_visible_skill_claims = extract_visible_skill_claims_fn or extract_visible_skill_claims

    def build_state(
        self,
        *,
        model: ResumeRenderModel,
        context: RenderPlanningContext,
    ) -> RenderPlanningState:
        html, prepared = self._build_html_and_prepared(model, template_name=context.template_name)
        planning = self._build_planning_with_evidence(
            model=model,
            prepared=prepared,
            template_name=context.template_name,
            job_description=context.job_description,
        )
        return RenderPlanningState(model=model, html=html, prepared=prepared, planning=planning)

    def rebuild_state(
        self,
        *,
        model: ResumeRenderModel,
        context: RenderPlanningContext,
    ) -> RenderPlanningState:
        return self.build_state(model=model, context=context)

    def measured_fit(self, state: RenderPlanningState) -> tuple[int | None, bool]:
        return self._measured_fit(state.planning)

    def visible_skill_names(self, state: RenderPlanningState) -> list[str]:
        claims = self._extract_visible_skill_claims(state.model, state.prepared)
        seen: set[str] = set()
        names: list[str] = []
        for claim in claims:
            raw = str(claim).strip()
            if not raw:
                continue
            key = " ".join(raw.lower().split())
            if key in seen:
                continue
            seen.add(key)
            names.append(raw)
        return names

    def visible_skill_count(self, state: RenderPlanningState) -> int:
        return len(self.visible_skill_names(state))
