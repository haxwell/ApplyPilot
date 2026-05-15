"""Compatibility alias for the production professional compact template."""

from applypilot.scoring.pdf_templates.professional_compact import (
    build_html,
    prepare,
    prepare_with_measurement,
)

__all__ = ["prepare", "prepare_with_measurement", "build_html"]
