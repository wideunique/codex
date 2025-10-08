from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from .enhancer import (
    Request,
    Response,
    Service,
    create_transient_temp_file_pair,
    maybe_create_temp_file_pair,
    strip_separator_lines,
)
from .template_utils import load_template, render_template, resolve_template_path
from .config import template_dir as default_template_dir


class CommandService(Service):
    def __init__(
        self,
        script_path: str,
        template_name: str,
        template_dir: str | None = None,
        auto_cleanup_enabled: bool = False,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.script_path = (script_path or "enhance_prompt.sh").strip()
        name = (template_name or "default").strip()
        if not name:
            raise RuntimeError("enhancer template name must not be empty")
        self._template_name = name
        self._template_dir = Path(template_dir or str(default_template_dir())).resolve()
        self.auto_cleanup_enabled = bool(auto_cleanup_enabled)
        self._logger = logger or logging.getLogger("prompt_enhancer.command")

    def enhance(self, req: Request) -> Response:
        if not self.script_path:
            raise RuntimeError("enhancer script path must not be empty")

        temp_files = maybe_create_temp_file_pair(self.auto_cleanup_enabled)
        if temp_files is None:
            temp_files = create_transient_temp_file_pair()
        elif temp_files.persist:
            self._logger.info(
                "temporary enhancer files persisted: %s, %s",
                temp_files.input_path,
                temp_files.output_path,
            )
        try:
            path = resolve_template_path(self._template_dir, self._template_name, req.locale, logger=self._logger)
            template_text = load_template(path)
            rendered_prompt = render_template(template_text, req.prompt)
            temp_files.input_path.write_text(rendered_prompt)

            proc = subprocess.run(
                [
                    self.script_path,
                    "--in",
                    str(temp_files.input_path),
                    "--out",
                    str(temp_files.output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                stderr_msg = (proc.stderr or "").strip()
                if stderr_msg:
                    raise RuntimeError(f"enhance_prompt.sh failed: {stderr_msg}")
                raise RuntimeError("enhance_prompt.sh failed")

            data = temp_files.output_path.read_text()
            cleaned = strip_separator_lines(data)
            return Response(prompt=cleaned)
        finally:
            if temp_files:
                temp_files.maybe_cleanup()


# Backwards compatibility with existing references
StubService = CommandService
