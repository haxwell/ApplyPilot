"""Dynamic template loader for scored resume PDF rendering."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType

_BUILTIN_TEMPLATE_PACKAGE = "applypilot.scoring.pdf_templates"
_TEMPLATE_CONTRACT = "build_html(prepared) and prepare(model) or prepare_with_measurement(model, measure_html_page_count)"
_OPTIONAL_METADATA = (
    "TEMPLATE_INFO",
    "TEMPLATE_CAPABILITIES",
    "TEMPLATE_INPUT_PREFERENCES",
    "TEMPLATE_REQUIREMENTS",
    "TEMPLATE_OPTIONS",
)


class TemplateLoadError(ValueError):
    """Raised when a PDF template reference cannot be loaded or validated."""


def _load_template_module(template_ref: str) -> ModuleType:
    ref = str(template_ref).strip()
    if not ref:
        raise TemplateLoadError(f"Invalid PDF template reference '{template_ref}'. Expected contract: {_TEMPLATE_CONTRACT}.")

    if ref.endswith(".py"):
        path = Path(ref).expanduser()
        if not path.exists():
            raise TemplateLoadError(
                f"PDF template '{template_ref}' was treated as a path but does not exist. "
                f"Expected contract: {_TEMPLATE_CONTRACT}."
            )
        module_name = f"{_BUILTIN_TEMPLATE_PACKAGE}.file_template_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise TemplateLoadError(
                f"Failed to load PDF template '{template_ref}' from path '{path}'. "
                f"Expected contract: {_TEMPLATE_CONTRACT}."
            )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    module_name = f"{_BUILTIN_TEMPLATE_PACKAGE}.{ref}"
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise TemplateLoadError(
                f"Unknown PDF template '{template_ref}'. Tried module '{module_name}'. "
                f"Expected contract: {_TEMPLATE_CONTRACT}."
            ) from exc
        raise


def _validate_template_contract(module: ModuleType, template_ref: str) -> None:
    has_build_html = callable(getattr(module, "build_html", None))
    has_prepare = callable(getattr(module, "prepare", None))
    has_prepare_with_measurement = callable(getattr(module, "prepare_with_measurement", None))

    missing: list[str] = []
    if not has_build_html:
        missing.append("build_html")
    if not (has_prepare or has_prepare_with_measurement):
        missing.append("prepare or prepare_with_measurement")

    if missing:
        missing_str = ", ".join(missing)
        raise TemplateLoadError(
            f"PDF template '{template_ref}' is missing required callables: {missing_str}. "
            f"Expected contract: {_TEMPLATE_CONTRACT}."
        )


def _validate_optional_template_metadata(module: ModuleType, template_ref: str) -> None:
    """Validate optional template metadata fields when present."""

    info = getattr(module, "TEMPLATE_INFO", None)
    if info is not None and not isinstance(info, dict):
        raise TemplateLoadError(
            f"PDF template '{template_ref}' has invalid TEMPLATE_INFO (expected dict). "
            f"Optional metadata fields: {', '.join(_OPTIONAL_METADATA)}."
        )

    capabilities = getattr(module, "TEMPLATE_CAPABILITIES", None)
    if capabilities is not None:
        if not isinstance(capabilities, (list, tuple)) or not all(isinstance(item, str) for item in capabilities):
            raise TemplateLoadError(
                f"PDF template '{template_ref}' has invalid TEMPLATE_CAPABILITIES "
                "(expected list[str] or tuple[str, ...]). "
                f"Optional metadata fields: {', '.join(_OPTIONAL_METADATA)}."
            )

    input_preferences = getattr(module, "TEMPLATE_INPUT_PREFERENCES", None)
    if input_preferences is not None and not isinstance(input_preferences, dict):
        raise TemplateLoadError(
            f"PDF template '{template_ref}' has invalid TEMPLATE_INPUT_PREFERENCES (expected dict). "
            f"Optional metadata fields: {', '.join(_OPTIONAL_METADATA)}."
        )

    requirements = getattr(module, "TEMPLATE_REQUIREMENTS", None)
    if requirements is not None and not isinstance(requirements, dict):
        raise TemplateLoadError(
            f"PDF template '{template_ref}' has invalid TEMPLATE_REQUIREMENTS (expected dict). "
            f"Optional metadata fields: {', '.join(_OPTIONAL_METADATA)}."
        )

    options = getattr(module, "TEMPLATE_OPTIONS", None)
    if options is not None and not isinstance(options, dict):
        raise TemplateLoadError(
            f"PDF template '{template_ref}' has invalid TEMPLATE_OPTIONS (expected dict). "
            f"Optional metadata fields: {', '.join(_OPTIONAL_METADATA)}."
        )


def get_template(template_ref: str = "professional_compact") -> ModuleType:
    """Load and validate a PDF template module by reference."""

    module = _load_template_module(template_ref)
    _validate_template_contract(module, template_ref)
    _validate_optional_template_metadata(module, template_ref)
    return module


def get_template_input_preferences(template_ref: str) -> dict:
    """Return a template's declared input preferences when available."""

    template = get_template(template_ref)
    prefs = getattr(template, "TEMPLATE_INPUT_PREFERENCES", None)
    if isinstance(prefs, dict):
        return dict(prefs)
    return {}
