from __future__ import annotations

from types import SimpleNamespace

from applypilot.scoring.pdf_render_model import ResumeRenderModel
from applypilot.scoring.skill_repair_planner import (
    SkillRepairContext,
    SkillRepairPlanner,
    SkillRepairResult,
)


def test_skill_repair_planner_calls_injected_repair_fn() -> None:
    calls: list[dict] = []

    def _repair(**kwargs):
        calls.append(kwargs)
        planning = dict(kwargs["planning"])
        planning["phase"] = "repaired"
        return kwargs["model"], kwargs["html"] + "r", kwargs["prepared"], planning

    planner = SkillRepairPlanner(apply_skill_repair=_repair)
    model = ResumeRenderModel(name="Alex")
    result = planner.repair(
        model=model,
        html="<html>",
        prepared=SimpleNamespace(),
        planning={"a": 1},
        context=SkillRepairContext(
            template_name="professional_compact",
            job_description="job desc",
            skills_selection={"retained_skills": []},
        ),
    )

    assert isinstance(result, SkillRepairResult)
    assert result.model is model
    assert result.html == "<html>r"
    assert result.planning["phase"] == "repaired"
    assert len(calls) == 1
    call = calls[0]
    assert call["template_name"] == "professional_compact"
    assert call["job_description"] == "job desc"
    assert call["skills_selection"] == {"retained_skills": []}
