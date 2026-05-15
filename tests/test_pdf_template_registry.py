from __future__ import annotations

import types
import sys

import pytest

from applypilot.scoring.pdf import DEFAULT_PDF_TEMPLATE, build_html_for_resume, resolve_pdf_template_name
from applypilot.scoring.pdf_render_model import ResumeRenderModel
from applypilot.scoring.pdf_templates.registry import TemplateLoadError, get_template


def test_get_template_without_ref_loads_production_default_template() -> None:
    template = get_template()

    assert hasattr(template, "prepare")
    assert hasattr(template, "prepare_with_measurement")
    assert hasattr(template, "build_html")


def test_get_template_default_alias_has_required_interface() -> None:
    template = get_template("default")

    assert hasattr(template, "prepare")
    assert hasattr(template, "prepare_with_measurement")
    assert hasattr(template, "build_html")


def test_get_template_compact_has_required_interface() -> None:
    template = get_template("compact")

    assert hasattr(template, "prepare")
    assert hasattr(template, "build_html")


def test_get_template_classic_has_required_interface() -> None:
    template = get_template("classic")

    assert hasattr(template, "prepare")
    assert hasattr(template, "build_html")


def test_get_template_professional_compact_has_required_interface() -> None:
    template = get_template("professional_compact")

    assert hasattr(template, "prepare")
    assert hasattr(template, "prepare_with_measurement")
    assert hasattr(template, "build_html")


def test_default_alias_matches_professional_compact_behavior() -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer")
    default_template = get_template("default")
    production_template = get_template("professional_compact")

    default_html = default_template.build_html(default_template.prepare(model))
    production_html = production_template.build_html(production_template.prepare(model))

    assert default_html == production_html


def test_get_template_missing_raises_clear_error() -> None:
    with pytest.raises(TemplateLoadError) as exc:
        get_template("missing")

    message = str(exc.value)
    assert "Unknown PDF template 'missing'" in message
    assert "applypilot.scoring.pdf_templates.missing" in message
    assert "Expected contract" in message


def test_get_template_rejects_module_missing_build_html(monkeypatch) -> None:
    module_name = "applypilot.scoring.pdf_templates.fake_missing_build"
    fake_module = types.ModuleType(module_name)
    fake_module.prepare = lambda model: model
    monkeypatch.setitem(sys.modules, module_name, fake_module)

    with pytest.raises(TemplateLoadError) as exc:
        get_template("fake_missing_build")

    message = str(exc.value)
    assert "fake_missing_build" in message
    assert "build_html" in message
    assert "Expected contract" in message


def test_build_html_for_resume_works_with_compact_template() -> None:
    model = ResumeRenderModel(name="Alex Example", title="Senior Engineer")
    html = build_html_for_resume(model, template_name="compact")
    assert "<html>" in html.lower()
    assert "Alex Example" in html


def test_build_html_for_resume_prefers_prepare_with_measurement(monkeypatch) -> None:
    class _FakeTemplate:
        @staticmethod
        def prepare_with_measurement(model, measure_fn):  # noqa: ANN001
            pages = measure_fn("<html><body>measure me</body></html>")
            return {"mode": "measurement", "name": model.name, "pages": pages}

        @staticmethod
        def prepare(model):  # noqa: ANN001
            return {"mode": "plain", "name": model.name}

        @staticmethod
        def build_html(prepared):  # noqa: ANN001
            return f"<html><body>{prepared['mode']}:{prepared['name']}:{prepared.get('pages', 0)}</body></html>"

    monkeypatch.setattr("applypilot.scoring.pdf.get_template", lambda _name: _FakeTemplate)
    monkeypatch.setattr("applypilot.scoring.pdf.measure_html_page_count", lambda _html: 7)

    html = build_html_for_resume(ResumeRenderModel(name="Alex Example"), template_name="fake")

    assert "measurement:Alex Example:7" in html


def test_resolve_pdf_template_name_defaults_to_production_template() -> None:
    assert resolve_pdf_template_name({}, None) == DEFAULT_PDF_TEMPLATE


def test_resolve_pdf_template_name_explicit_overrides_config() -> None:
    profile = {"tailoring_config": {"pdf_template": "compact"}}
    assert resolve_pdf_template_name(profile, "classic") == "classic"


def test_resolve_pdf_template_name_uses_tailoring_config_template() -> None:
    profile = {"tailoring_config": {"pdf_template": "compact"}}
    assert resolve_pdf_template_name(profile, None) == "compact"
