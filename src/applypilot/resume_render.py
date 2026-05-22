"""JSON Resume theme rendering helpers."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from applypilot.config import RESUME_JSON_PATH, load_profile
from applypilot.resume_json import DEFAULT_RENDER_THEME, load_resume_json_from_path, resolve_jsonresume_theme
from applypilot.scoring.pdf import render_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_RESUMED = PROJECT_ROOT / "node_modules" / ".bin" / "resumed"
_KNOWN_APPLYPILOT_PDF_TEMPLATES = {
    "professional_compact",
    "editorial_timeline",
    "classic",
    "compact",
    "default",
}


def _resumed_command() -> list[str]:
    if LOCAL_RESUMED.exists():
        return [str(LOCAL_RESUMED)]
    raise FileNotFoundError(
        "Local 'resumed' CLI not found. Run `npm install` in the ApplyPilot project root first."
    )


def render_resume_html(
    resume_path: Path | None = None,
    theme: str | None = None,
    output_path: Path | None = None,
) -> tuple[Path, str]:
    """Render resume.json to HTML using the local resumed CLI."""

    source = Path(resume_path) if resume_path is not None else RESUME_JSON_PATH
    load_resume_json_from_path(source)
    try:
        profile = load_profile()
    except Exception:
        profile = {}
    resolved_theme = resolve_jsonresume_theme(profile, explicit_theme=theme) or DEFAULT_RENDER_THEME
    if resolved_theme in _KNOWN_APPLYPILOT_PDF_TEMPLATES:
        raise ValueError(
            "ApplyPilot PDF template names are not JSON Resume themes. "
            "Use profile.render.jsonresume_theme for JSON Resume rendering "
            "and profile.tailoring_config.pdf_template for ApplyPilot planned PDFs."
        )
    destination = Path(output_path) if output_path is not None else source.with_suffix(".html")

    command = _resumed_command() + [
        "render",
        str(source),
        "--theme",
        resolved_theme,
        "--output",
        str(destination),
    ]
    try:
        subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(
            f"Failed to render HTML with theme '{resolved_theme}'. {stderr or 'Check that the theme package is installed.'}"
        ) from exc

    return destination, resolved_theme


def render_resume_pdf(
    resume_path: Path | None = None,
    theme: str | None = None,
    output_path: Path | None = None,
) -> tuple[Path, str]:
    """Render resume.json to PDF by theme-rendering HTML then printing it."""

    source = Path(resume_path) if resume_path is not None else RESUME_JSON_PATH
    destination = Path(output_path) if output_path is not None else source.with_suffix(".pdf")

    with tempfile.TemporaryDirectory(prefix="applypilot-resume-render-") as tmp_dir:
        html_path = Path(tmp_dir) / "resume.html"
        rendered_html_path, resolved_theme = render_resume_html(source, theme=theme, output_path=html_path)
        html = rendered_html_path.read_text(encoding="utf-8")
        render_pdf(html, str(destination))

    return destination, resolved_theme
