from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

import yaml


_DURATION_RE = re.compile(r"^(?P<value>\d+)(?P<unit>ms|s|m|h)?$")
_SRC_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SRC_DIR.parent
_DEFAULT_TEMPLATE_DIR = _PROJECT_ROOT / "templates"
_DEFAULT_FIREFOX_BINARY = "/Applications/Firefox.app/Contents/MacOS/firefox"
_DEFAULT_SELENIUM_TIMEOUT = 120


def _parse_duration(s: str) -> float:
    s = s.strip()
    if not s:
        return 0.0
    match = _DURATION_RE.match(s)
    if not match:
        raise ValueError(f"invalid duration: {s}")
    value = float(match.group("value"))
    unit = match.group("unit") or "s"
    if unit == "ms":
        return value / 1000.0
    if unit == "s":
        return value
    if unit == "m":
        return value * 60.0
    if unit == "h":
        return value * 3600.0
    raise ValueError(f"unsupported duration unit: {unit}")


@dataclass
class ServerConfig:
    address: str = ":8080"
    read_timeout_s: float = 5.0
    write_timeout_s: float = 10.0


@dataclass
class SecurityConfig:
    api_key: str = ""


@dataclass
class SeleniumConfig:
    firefox_binary: str = _DEFAULT_FIREFOX_BINARY
    firefox_profile_dir: Optional[str] = None
    timeout: int = _DEFAULT_SELENIUM_TIMEOUT
    auto_update_driver: bool = False
    show_gui: bool = False


@dataclass
class CommandConfig:
    script_path: str = "enhance_prompt.sh"


@dataclass
class EnhancerConfig:
    auto_cleanup_temp_files: bool = False
    # Base template name, without locale suffix or extension.
    # Example: "default" -> resolves default.txt, default_cn.txt, etc.
    template_name: str = "default"
    mode: str = "selenium"
    command: CommandConfig = field(default_factory=CommandConfig)
    selenium: SeleniumConfig = field(default_factory=SeleniumConfig)


@dataclass
class Config:
    server: ServerConfig
    security: SecurityConfig
    enhancer: EnhancerConfig


def _merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _defaults_dict() -> dict:
    return {
        "server": {
            "address": ":8080",
            "read_timeout": "5s",
            "write_timeout": "10s",
        },
        "security": {"api_key": ""},
        "enhancer": {
            "auto_cleanup_temp_files": False,
            "template_name": "default",
            "mode": "selenium",
            "command": {
                "script_path": "enhance_prompt.sh",
            },
            "selenium": {
                "firefox_binary": _DEFAULT_FIREFOX_BINARY,
                "firefox_profile_dir": None,
                "timeout": _DEFAULT_SELENIUM_TIMEOUT,
                "auto_update_driver": False,
                "show_gui": False,
            },
        },
    }


def _apply_env(cfg: dict) -> dict:
    if value := os.getenv("SERVER_ADDRESS"):
        cfg["server"]["address"] = value
    if value := os.getenv("READ_TIMEOUT"):
        cfg["server"]["read_timeout"] = value
    if value := os.getenv("WRITE_TIMEOUT"):
        cfg["server"]["write_timeout"] = value

    if value := os.getenv("API_KEY"):
        cfg["security"]["api_key"] = value

    if value := os.getenv("ENHANCE_SCRIPT_PATH"):
        command_cfg = cfg["enhancer"].setdefault("command", {})
        command_cfg["script_path"] = value
    if value := os.getenv("AUTO_CLEANUP_TEMP_FILES"):
        cfg["enhancer"]["auto_cleanup_temp_files"] = _as_bool(value)
    if value := os.getenv("ENHANCER_TEMPLATE_NAME"):
        cfg["enhancer"]["template_name"] = value
    if value := os.getenv("ENHANCER_MODE"):
        cfg["enhancer"]["mode"] = value

    selenium_cfg = cfg["enhancer"].setdefault("selenium", {})
    if value := os.getenv("SELENIUM_FIREFOX_BINARY"):
        selenium_cfg["firefox_binary"] = value
    if value := os.getenv("SELENIUM_FIREFOX_PROFILE_DIR"):
        selenium_cfg["firefox_profile_dir"] = value
    if value := os.getenv("SELENIUM_TIMEOUT"):
        selenium_cfg["timeout"] = _to_int(value, _DEFAULT_SELENIUM_TIMEOUT)
    if value := os.getenv("SELENIUM_AUTO_UPDATE_DRIVER"):
        selenium_cfg["auto_update_driver"] = _as_bool(value)
    if value := os.getenv("SELENIUM_SHOW_GUI"):
        selenium_cfg["show_gui"] = _as_bool(value)
    return cfg


def load_config(path: str | None) -> Config:
    file_cfg: dict = {}
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            file_cfg = yaml.safe_load(handle) or {}

    merged = _apply_env(_merge(_defaults_dict(), file_cfg))

    api_key = (merged.get("security") or {}).get("api_key") or ""
    if not api_key:
        raise ValueError("security.api_key must be provided via config file or API_KEY environment variable")

    server_dict = merged.get("server") or {}
    address = (server_dict.get("address") or "").strip()
    if not address:
        raise ValueError("server address must not be empty")

    read_timeout_s = _parse_duration(_strip_optional(server_dict.get("read_timeout")) or "0")
    write_timeout_s = _parse_duration(_strip_optional(server_dict.get("write_timeout")) or "0")

    enhancer_dict = merged.get("enhancer") or {}

    command_dict = enhancer_dict.get("command") or {}
    script_path = _strip_optional(command_dict.get("script_path"))
    if not script_path:
        raise ValueError("enhancer.command.script_path must not be empty in config file")

    auto_cleanup = _as_bool(enhancer_dict.get("auto_cleanup_temp_files"))
    mode = (_strip_optional(enhancer_dict.get("mode")) or "selenium").lower()
    if mode not in {"command", "selenium"}:
        raise ValueError("enhancer mode must be either 'command' or 'selenium'")


    template_name_value = _strip_or_default(enhancer_dict.get("template_name"), "default")
    command_cfg = CommandConfig(
        script_path=script_path,
    )

    selenium_dict = enhancer_dict.get("selenium") or {}
    selenium_cfg = SeleniumConfig(
        firefox_binary=_strip_or_default(selenium_dict.get("firefox_binary"), _DEFAULT_FIREFOX_BINARY),
        firefox_profile_dir=_strip_optional(selenium_dict.get("firefox_profile_dir")),
        timeout=_to_int(selenium_dict.get("timeout"), _DEFAULT_SELENIUM_TIMEOUT),
        auto_update_driver=_as_bool(selenium_dict.get("auto_update_driver")),
        show_gui=_as_bool(selenium_dict.get("show_gui")),
    )

    return Config(
        server=ServerConfig(
            address=address,
            read_timeout_s=read_timeout_s,
            write_timeout_s=write_timeout_s,
        ),
        security=SecurityConfig(api_key=api_key),
        enhancer=EnhancerConfig(
            auto_cleanup_temp_files=auto_cleanup,
            template_name=template_name_value,
            mode=mode,
            command=command_cfg,
            selenium=selenium_cfg,
        ),
    )


def parse_host_port(address: str) -> Tuple[str, int]:
    if address.startswith(":"):
        host = "0.0.0.0"
        port_str = address[1:]
    else:
        host, _, port_str = address.rpartition(":")
        if not host:
            host = "0.0.0.0"
    if not port_str.isdigit():
        raise ValueError(f"invalid address: {address}")
    return host, int(port_str)


def _strip_optional(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _strip_or_default(value, default: str) -> str:
    stripped = _strip_optional(value)
    return stripped if stripped is not None else default


def _to_int(value, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer value: {value}") from exc


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def template_dir() -> Path:
    """Return absolute path to the templates directory."""
    return _DEFAULT_TEMPLATE_DIR.resolve()
