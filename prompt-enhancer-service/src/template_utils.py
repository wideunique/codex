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
