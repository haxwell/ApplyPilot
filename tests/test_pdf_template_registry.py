from __future__ import annotations

import pytest

from applypilot.scoring.pdf import resolve_pdf_template_name
from applypilot.scoring.pdf_templates.registry import get_template


def test_get_template_default_has_required_interface() -> None:
    template = get_template("default")

    assert hasattr(template, "prepare")
    assert hasattr(template, "build_html")


def test_get_template_compact_has_required_interface() -> None:
    template = get_template("compact")

    assert hasattr(template, "prepare")
    assert hasattr(template, "build_html")


def test_get_template_missing_raises_clear_error() -> None:
    with pytest.raises(ValueError) as exc:
        get_template("missing")

    message = str(exc.value)
    assert "Unknown PDF template 'missing'" in message
    assert "default" in message
    assert "compact" in message


def test_resolve_pdf_template_name_defaults_to_default() -> None:
    assert resolve_pdf_template_name({}, None) == "default"


def test_resolve_pdf_template_name_explicit_overrides_config() -> None:
    profile = {"tailoring_config": {"pdf_template": "compact"}}
    assert resolve_pdf_template_name(profile, "default") == "default"


def test_resolve_pdf_template_name_uses_tailoring_config_template() -> None:
    profile = {"tailoring_config": {"pdf_template": "compact"}}
    assert resolve_pdf_template_name(profile, None) == "compact"
