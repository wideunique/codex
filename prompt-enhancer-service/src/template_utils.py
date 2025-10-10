from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from jinja2 import Template


class TemplateError(RuntimeError):
    """Raised when template rendering fails."""


def load_template(path: Path, logger: Optional[logging.Logger] = None) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise TemplateError(f"Template file not found: {path}") from exc
    except OSError as exc:  # pragma: no cover - filesystem errors
        raise TemplateError(f"Failed to read template {path}: {exc}") from exc
    if logger:
        logger.info("loaded template from %s", path)
    return text


def render_template(template_text: str, prompt: str, logger: Optional[logging.Logger] = None) -> str:
    try:
        rendered = Template(template_text).render({"prompt": prompt})
    except Exception as exc:
        raise TemplateError(f"Template rendering failed: {exc}") from exc
    rendered = rendered.strip()
    if not rendered:
        raise TemplateError("Rendered template is empty")
    if logger:
        logger.info("rendered template (%d characters)", len(rendered))
    return rendered


def resolve_template_path(
    base_dir: Path,
    template_name: str,
    locale: Optional[str],
    logger: Optional[logging.Logger] = None,
) -> Path:
    """Resolve the template path for the requested locale.

    Preference order:
    1. `<name>_<locale>.txt` when `locale` is provided.
    2. `<name>.txt` as the default fallback.

    Raises:
        TemplateError: if no matching template file exists.
    """
    raw_name = template_name if template_name is not None else "default"
    name = raw_name.strip()
    if not name:
        raise TemplateError("template name must not be empty")

    base_dir = base_dir.resolve()
    locale_key = (locale or "").strip().lower()
    locale_path: Optional[Path] = None

    if locale_key:
        locale_path = base_dir / f"{name}_{locale_key}.txt"
        if locale_path.exists():
            if logger:
                logger.info("using template: %s", locale_path)
            return locale_path

    default_path = base_dir / f"{name}.txt"
    if default_path.exists():
        if logger:
            logger.info("using template: %s", default_path)
        return default_path

    if locale_path is not None:
        raise TemplateError(
            f"template not found: {locale_path} (fallback {default_path} missing)"
        )
    raise TemplateError(f"template not found: {default_path}")
