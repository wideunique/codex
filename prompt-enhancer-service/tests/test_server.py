from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.config import CommandConfig, Config, EnhancerConfig, SecurityConfig, ServerConfig
from src.enhancer import Request as EnhReq
from src.enhancer import Response as EnhResp
from src.enhancer import Service
from src.mode_command import CommandService
from src.mode_selenium import SeleniumUnavailableError


class FakeEnhancer(Service):
    def __init__(self, response: str | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    def enhance(self, req: EnhReq) -> EnhResp:
        if self._error is not None:
            raise self._error
        return EnhResp(prompt=self._response or "")


def make_client(api_key: str) -> TestClient:
    cfg = Config(
        server=ServerConfig(),
        security=SecurityConfig(api_key=api_key),
        enhancer=EnhancerConfig(
            auto_cleanup_temp_files=True,
            mode="command",
            command=CommandConfig(script_path="/bin/true"),
        ),
    )
    app = create_app(cfg)
    return TestClient(app)


def test_enhance_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client("secret")

    # Patch the enhancer inside the app by swapping route dependency through monkeypatch on module
    monkeypatch.setattr(CommandService, "enhance", lambda self, req: EnhResp(prompt="hello [Enhanced]"))

    resp = client.post(
        "/api/v1/enhance",
        headers={"Authorization": "Bearer secret"},
        json={"draft": "hello"},
    )
    assert resp.status_code == 200
    assert resp.json()["enhanced_prompt"] == "hello [Enhanced]"


def test_enhance_unauthorized() -> None:
    client = make_client("secret")
    resp = client.post("/api/v1/enhance", json={"draft": "hello"})
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized", "message": "unauthorized"}


def test_enhance_invalid_payload() -> None:
    client = make_client("secret")
    resp = client.post("/api/v1/enhance", headers={"Authorization": "Bearer secret"}, json={})
    assert resp.status_code == 400
    assert resp.json() == {"error": "invalid_request", "message": "prompt must not be empty"}


def test_enhance_invalid_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client("secret")
    resp = client.post(
        "/api/v1/enhance",
        headers={"Authorization": "Bearer secret"},
        json={"draft": "hello", "mode": "unknown"},
    )
    assert resp.status_code == 400
    assert resp.json() == {
        "error": "invalid_mode",
        "message": "unsupported enhancement mode: unknown",
    }


def test_enhance_selenium_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingService(Service):
        def __init__(self, *_args, **_kwargs) -> None:
            raise SeleniumUnavailableError("selenium not configured")

        def enhance(self, req: EnhReq) -> EnhResp:  # pragma: no cover - never reached
            raise AssertionError("should not be called")

    monkeypatch.setattr("src.mode_selenium.SeleniumService", FailingService)

    client = make_client("secret")
    resp = client.post(
        "/api/v1/enhance",
        headers={"Authorization": "Bearer secret"},
        json={"draft": "hello", "mode": "selenium"},
    )
    assert resp.status_code == 503
    assert resp.json() == {
        "error": "service_unavailable",
        "message": "selenium not configured",
    }


def test_enhance_default_selenium_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    class SuccessfulService(Service):
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def enhance(self, req: EnhReq) -> EnhResp:
            return EnhResp(prompt="selenium [Enhanced]")

    monkeypatch.setattr("src.mode_selenium.SeleniumService", SuccessfulService)

    cfg = Config(
        server=ServerConfig(),
        security=SecurityConfig(api_key="secret"),
        enhancer=EnhancerConfig(
            auto_cleanup_temp_files=True,
            mode="selenium",
            command=CommandConfig(script_path="/bin/true"),
        ),
    )
    client = TestClient(create_app(cfg))
    resp = client.post(
        "/api/v1/enhance",
        headers={"Authorization": "Bearer secret"},
        json={"draft": "hello"},
    )
    assert resp.status_code == 200
    assert resp.json()["enhanced_prompt"] == "selenium [Enhanced]"


def test_enhance_internal_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client("secret")

    def _fail(self, req: EnhReq) -> EnhResp:  # type: ignore[override]
        raise RuntimeError("boom")

    monkeypatch.setattr(CommandService, "enhance", _fail)
    resp = client.post(
        "/api/v1/enhance",
        headers={"Authorization": "Bearer secret"},
        json={"draft": "hello"},
    )
    assert resp.status_code == 500
    assert resp.json() == {
        "error": "enhancement_failed",
        "message": "unable to enhance prompt",
    }


def test_enhance_service_misconfigured() -> None:
    cfg = Config(
        server=ServerConfig(),
        security=SecurityConfig(api_key=""),
        enhancer=EnhancerConfig(
            auto_cleanup_temp_files=True,
            mode="command",
            command=CommandConfig(script_path="/bin/true"),
        ),
    )
    client = TestClient(create_app(cfg))
    resp = client.post(
        "/api/v1/enhance",
        json={"draft": "hello"},
    )
    assert resp.status_code == 500
    assert resp.json() == {
        "error": "service_misconfigured",
        "message": "service misconfigured",
    }
