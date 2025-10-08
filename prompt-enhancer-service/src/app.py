from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .auth import auth_dependency
from .config import Config
from .enhancer import EnhancerCoordinator, ModeNotSupportedError
from .enhancer import Request as EnhanceReq
from .enhancer import Service
from .mode_selenium import SeleniumUnavailableError
from .models import EnhanceRequest, EnhanceResponse, ErrorResponse


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI()
    logger = logging.getLogger("prompt_enhancer")
    coordinator = EnhancerCoordinator(cfg.enhancer)

    try:
        coordinator.get_service("command")
    except Exception as exc:
        raise RuntimeError(f"unable to initialize command mode: {exc}") from exc

    if coordinator.default_mode == "selenium":
        try:
            coordinator.get_service("selenium")
        except SeleniumUnavailableError as exc:
            raise RuntimeError(f"unable to initialize selenium mode: {exc}") from exc

    def get_service(selected_mode: str) -> Service:
        try:
            return coordinator.get_service(selected_mode)
        except ModeNotSupportedError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    auth_dep = auth_dependency(cfg.security.api_key)

    @app.post("/api/v1/enhance", response_model=EnhanceResponse, responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    })
    def enhance_endpoint(payload: EnhanceRequest, _: bool = Depends(auth_dep)) -> EnhanceResponse:
        try:
            payload.validate_non_empty()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        requested_mode = (payload.mode or cfg.enhancer.mode).lower()
        try:
            service = get_service(requested_mode)
        except SeleniumUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        prompt_text = payload.prompt_text()
        logger.info(
            "prompt enhancement requested",
            extra={
                "request_id": payload.request_id,
                "prompt_len": len(prompt_text),
                "mode": requested_mode,
            },
        )
        try:
            resp = service.enhance(EnhanceReq(prompt=prompt_text))
        except HTTPException:
            raise
        except Exception as e:  # mirror 500 mapping
            logger.exception("enhance failed")
            raise HTTPException(status_code=500, detail="unable to enhance prompt") from e

        return EnhanceResponse(enhanced_prompt=resp.prompt)

    @app.exception_handler(HTTPException)
    async def http_exc_handler(_: Request, exc: HTTPException):
        status = exc.status_code
        if status == 400:
            code = "invalid_request"
        elif status == 401:
            # Match Go middleware: plain text body for unauthorized
            return PlainTextResponse("unauthorized", status_code=401)
        elif status == 500:
            # For misconfiguration in auth middleware, plain text
            if str(exc.detail) == "service misconfigured":
                return PlainTextResponse("service misconfigured", status_code=500)
            code = "enhancement_failed" if exc.detail == "unable to enhance prompt" else "internal_error"
        else:
            code = "error"
        return JSONResponse(
            status_code=status,
            content=ErrorResponse(error=code, message=str(exc.detail)).model_dump(),
        )

    return app
