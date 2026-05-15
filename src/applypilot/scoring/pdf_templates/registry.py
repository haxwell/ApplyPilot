"""Minimal template registry for scored resume PDF rendering."""

from applypilot.scoring.pdf_templates import compact, default

TEMPLATES = {
    "default": default,
    "compact": compact,
}


def get_template(name: str = "default"):
    """Return a template module by name."""

    try:
        return TEMPLATES[name]
    except KeyError as exc:
        available = ", ".join(sorted(TEMPLATES))
        raise ValueError(f"Unknown PDF template '{name}'. Available templates: {available}") from exc
