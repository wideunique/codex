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
    """Resolve a template path by name and optional locale.

    - Tries `<name>_<locale>.txt` when `locale` is provided (case-insensitive).
    - Falls back to `<name>.txt` if the locale-specific file is missing.
    - Returns the chosen `Path` (may be non-existent for callers to handle).
    """
    name = (template_name or "default").strip()
    base_dir = base_dir.resolve()

    candidates: list[Path] = []
    if locale:
        loc = locale.strip().lower()
        if loc:
            candidates.append(base_dir / f"{name}_{loc}.txt")
    candidates.append(base_dir / f"{name}.txt")

    for path in candidates:
        if path.exists():
            if logger:
                logger.info("selected template: %s", path)
            return path
    # Return the last candidate to produce a clear error on load.
    fallback = candidates[-1]
    if logger:
        logger.warning("no template matched; falling back to %s", fallback)
    return fallback
