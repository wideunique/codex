from __future__ import annotations

import contextlib
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from .config import EnhancerConfig


TEMP_ROOT_DIR = Path("/tmp/promate-enhancer")
_TEMP_CREATION_RETRIES = 5


@dataclass
class Request:
    prompt: str


@dataclass
class Response:
    prompt: str


class Service:
    def enhance(self, req: Request) -> Response:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class TempFilePair:
    input_path: Path
    output_path: Path
    persist: bool

    def maybe_cleanup(self) -> None:
        if self.persist:
            return
        for path in (self.input_path, self.output_path):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()


def _timestamp_millis() -> str:
    now = time.gmtime()
    ms = int((time.time() - int(time.time())) * 1000)
    return time.strftime("%Y%m%d%H%M%S", now) + f"{ms:03d}"


def _create_timestamped_pair(root_dir: Path) -> tuple[Path, Path]:
    root_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(_TEMP_CREATION_RETRIES):
        timestamp = _timestamp_millis()
        input_path = root_dir / f"{timestamp}_in.txt"
        output_path = root_dir / f"{timestamp}_out.txt"
        try:
            fd_in = os.open(str(input_path), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
            os.close(fd_in)
            fd_out = os.open(str(output_path), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
            os.close(fd_out)
            return input_path, output_path
        except FileExistsError:
            with contextlib.suppress(FileNotFoundError):
                os.remove(str(input_path))
            time.sleep(0.001)
    raise RuntimeError(f"failed to allocate temp files in {root_dir}")


def maybe_create_temp_file_pair(
    auto_cleanup_enabled: bool,
    root_dir: str | Path | None = None,
) -> Optional[TempFilePair]:
    if auto_cleanup_enabled:
        return None

    base_dir = Path(root_dir) if root_dir is not None else TEMP_ROOT_DIR
    input_path, output_path = _create_timestamped_pair(base_dir)
    return TempFilePair(input_path=input_path, output_path=output_path, persist=True)


def _create_transient_file(suffix: str) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="promate-enhancer_", suffix=suffix, delete=False)
    try:
        path = Path(handle.name)
    finally:
        handle.close()
    os.chmod(path, 0o600)
    return path


def create_transient_temp_file_pair() -> TempFilePair:
    input_path: Optional[Path] = None
    try:
        input_path = _create_transient_file("_in.txt")
        output_path = _create_transient_file("_out.txt")
    except Exception:
        if input_path is not None:
            with contextlib.suppress(FileNotFoundError):
                input_path.unlink()
        raise
    return TempFilePair(input_path=input_path, output_path=output_path, persist=False)


def strip_separator_lines(text: str, logger: Optional[logging.Logger] = None) -> str:
    if not text:
        return text

    pattern = re.compile(r"^#+\s*(start|end)\s*#+$", re.IGNORECASE)
    lines = text.splitlines()
    filtered = [line for line in lines if not pattern.match(line.strip())]

    if filtered != lines and logger:
        logger.info("removed Gemini separator markers")

    cleaned = "\n".join(filtered)
    if text.endswith("\n") and not cleaned.endswith("\n"):
        cleaned += "\n"
    return cleaned


class ModeNotSupportedError(ValueError):
    """Raised when a requested enhancer mode cannot be served."""


def _normalize_mode(mode: str) -> str:
    return (mode or "").strip().lower()


class EnhancerCoordinator:
    def __init__(self, cfg: EnhancerConfig) -> None:
        self._cfg = cfg
        self._default_mode = _normalize_mode(cfg.mode)
        if self._default_mode not in {"command", "selenium"}:
            raise ModeNotSupportedError(f"unsupported enhancement mode: {cfg.mode}")
        self._services: Dict[str, Service] = {}

    @property
    def default_mode(self) -> str:
        return self._default_mode

    def get_service(self, mode: str) -> Service:
        normalized = _normalize_mode(mode) or self.default_mode
        if normalized not in {"command", "selenium"}:
            raise ModeNotSupportedError(f"unsupported enhancement mode: {mode}")

        if normalized not in self._services:
            factory = self._factory_for(normalized)
            service = factory()
            self._services[normalized] = service
        return self._services[normalized]

    def _factory_for(self, mode: str) -> Callable[[], Service]:
        if mode == "command":
            return self._create_command_service
        if mode == "selenium":
            return self._create_selenium_service
        raise ModeNotSupportedError(f"unsupported enhancement mode: {mode}")

    def _create_command_service(self) -> Service:
        from .mode_command import CommandService

        logger = logging.getLogger("prompt_enhancer.command")
        return CommandService(
            script_path=self._cfg.command.script_path,
            template_path=self._cfg.template_path,
            auto_cleanup_enabled=self._cfg.auto_cleanup_temp_files,
            logger=logger,
        )

    def _create_selenium_service(self) -> Service:
        from .mode_selenium import SeleniumService

        logger = logging.getLogger("prompt_enhancer.selenium")
        return SeleniumService(
            self._cfg.selenium,
            self._cfg.template_path,
            auto_cleanup_enabled=self._cfg.auto_cleanup_temp_files,
            logger=logger,
        )
