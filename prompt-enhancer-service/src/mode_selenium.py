from __future__ import annotations

import logging
from contextlib import suppress
from pathlib import Path
from typing import Optional

from .config import SeleniumConfig
from .enhancer import (
    Request,
    Response,
    Service,
    maybe_create_temp_file_pair,
    strip_separator_lines,
)
from .template_utils import load_template, render_template, resolve_template_path
from .config import template_dir as default_template_dir
from .utils.gemini_client import GeminiClient



class SeleniumUnavailableError(RuntimeError):
    """Raised when Selenium-based enhancement cannot be used."""


def call_gemini(query_text: str, cfg: SeleniumConfig, logger: logging.Logger) -> str:
    client = GeminiClient(
        firefox_binary=cfg.firefox_binary,
        firefox_profile_dir=cfg.firefox_profile_dir,
        timeout=cfg.timeout,
        auto_update_driver=cfg.auto_update_driver,
        show_gui=cfg.show_gui,
        logger=logger,
    )
    response = ""
    try:
        client.init_driver()
        logger.info("sending Gemini query via Selenium")
        response = client.send_query(query_text)
    except SystemExit as exc:
        logger.exception("selenium-based enhancement aborted")
        raise RuntimeError("selenium enhancement failed: Gemini client aborted") from exc
    except Exception as exc:
        logger.exception("selenium-based enhancement failed")
        raise RuntimeError(f"selenium enhancement failed: {exc}") from exc
    finally:
        with suppress(Exception):
            client.close()

    if not response.strip():
        raise RuntimeError("selenium enhancement failed: Gemini returned empty response")

    logger.info("Gemini response size: %d characters", len(response))
    return strip_separator_lines(response, logger=logger)


class SeleniumService(Service):
    def __init__(
        self,
        cfg: SeleniumConfig,
        template_name: str,
        template_dir: str | None = None,
        auto_cleanup_enabled: bool = False,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._cfg = cfg
        self._logger = logger or logging.getLogger("prompt_enhancer.selenium")
        name = (template_name or "default").strip()
        if not name:
            raise RuntimeError("enhancer template name must not be empty")
        self._template_name = name
        self._template_dir = Path(template_dir or str(default_template_dir())).resolve()
        self._auto_cleanup_enabled = bool(auto_cleanup_enabled)

    def enhance(self, req: Request) -> Response:
        if not req.prompt.strip():
            raise RuntimeError("prompt must not be empty")

        path = resolve_template_path(self._template_dir, self._template_name, req.locale, logger=self._logger)
        template_text = load_template(path, logger=self._logger)
        query_text = render_template(template_text, req.prompt, logger=self._logger)
        temp_files = maybe_create_temp_file_pair(self._auto_cleanup_enabled)
        if temp_files:
            temp_files.input_path.write_text(query_text)
            if temp_files.persist:
                self._logger.info(
                    "temporary enhancer files persisted: %s, %s",
                    temp_files.input_path,
                    temp_files.output_path,
                )

        cleaned = call_gemini(query_text, self._cfg, self._logger)
        if temp_files:
            temp_files.output_path.write_text(cleaned)
        return Response(prompt=cleaned)
