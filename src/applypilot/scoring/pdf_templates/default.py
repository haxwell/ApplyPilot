"""Compatibility alias for the production professional compact template."""

from applypilot.scoring.pdf_templates.professional_compact import (
    build_html,
    prepare,
    prepare_with_measurement,
)

TEMPLATE_INFO = {
    "name": "default",
    "display_name": "Default (Alias)",
    "description": "Compatibility alias for professional_compact.",
    "alias_of": "professional_compact",
}
TEMPLATE_CAPABILITIES = [
    "measurement_aware_prepare",
    "selected_experience_rendering",
    "alias",
]
TEMPLATE_INPUT_PREFERENCES = {
    "expects": "ResumeRenderModel",
    "preferred_path": "structured_json_to_render_model",
    "requested_entry_fields": ["compact_summary"],
    "prefers_compact_summary": True,
}
TEMPLATE_REQUIREMENTS = {
    "hooks": ["build_html", "prepare", "prepare_with_measurement"],
}
TEMPLATE_OPTIONS = {
    "inherits_from": "professional_compact",
}

__all__ = ["prepare", "prepare_with_measurement", "build_html"]
