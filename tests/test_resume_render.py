from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import applypilot.resume_render as resume_render


def test_render_resume_html_uses_profile_jsonresume_theme(monkeypatch, tmp_path: Path) -> None:
    resume_path = tmp_path / "resume.json"
    output_path = tmp_path / "resume.html"
    resume_path.write_text("{}", encoding="utf-8")

    seen: dict[str, list[str]] = {}

    monkeypatch.setattr(resume_render, "load_resume_json_from_path", lambda _path: {})
    monkeypatch.setattr(
        resume_render,
        "load_profile",
        lambda: {"render": {"jsonresume_theme": "jsonresume-theme-even"}},
    )
    monkeypatch.setattr(resume_render, "_resumed_command", lambda: ["resumed"])

    def _fake_run(command, **_kwargs):  # noqa: ANN001
        seen["command"] = command
        output_path.write_text("<html/>", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(resume_render.subprocess, "run", _fake_run)

    destination, theme = resume_render.render_resume_html(resume_path=resume_path, output_path=output_path)

    assert destination == output_path
    assert theme == "jsonresume-theme-even"
    assert "--theme" in seen["command"]
    assert seen["command"][seen["command"].index("--theme") + 1] == "jsonresume-theme-even"


def test_render_resume_html_rejects_applypilot_template_name_as_theme(monkeypatch, tmp_path: Path) -> None:
    resume_path = tmp_path / "resume.json"
    output_path = tmp_path / "resume.html"
    resume_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(resume_render, "load_resume_json_from_path", lambda _path: {})
    monkeypatch.setattr(
        resume_render,
        "load_profile",
        lambda: {"render": {"jsonresume_theme": "jsonresume-theme-even"}},
    )
    monkeypatch.setattr(resume_render, "_resumed_command", lambda: ["resumed"])

    with pytest.raises(ValueError, match="ApplyPilot PDF template names are not JSON Resume themes"):
        resume_render.render_resume_html(
            resume_path=resume_path,
            output_path=output_path,
            theme="professional_compact",
        )


def test_render_resume_html_rejects_applypilot_template_name_from_profile_render_setting(
    monkeypatch,
    tmp_path: Path,
) -> None:
    resume_path = tmp_path / "resume.json"
    output_path = tmp_path / "resume.html"
    resume_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(resume_render, "load_resume_json_from_path", lambda _path: {})
    monkeypatch.setattr(
        resume_render,
        "load_profile",
        lambda: {"render": {"jsonresume_theme": "professional_compact"}},
    )
    monkeypatch.setattr(resume_render, "_resumed_command", lambda: ["resumed"])

    with pytest.raises(ValueError, match="ApplyPilot PDF template names are not JSON Resume themes"):
        resume_render.render_resume_html(
            resume_path=resume_path,
            output_path=output_path,
        )
