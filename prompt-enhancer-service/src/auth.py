from __future__ import annotations

from typing import Optional

from fastapi import Header, Request, HTTPException


def extract_token(request: Request, authorization: Optional[str], x_api_key: Optional[str]) -> str:
    # Match Go logic exactly: prefer Authorization if present; must be Bearer
    if authorization is not None and authorization != "":
        if not authorization.startswith("Bearer "):
            return ""
        return authorization[len("Bearer ") :]

    # Fallback to X-API-Key header
    if x_api_key is not None and x_api_key != "":
        return x_api_key

    # Fallback to query param
    return request.query_params.get("api_key", "")


def auth_dependency(expected_key: str):
    if not expected_key:
        # Misconfigured service -> 500 (Go behaviour)
        def _fail(_: Request, authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)):
            raise HTTPException(status_code=500, detail="service misconfigured")
        return _fail

    def _auth(request: Request, authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)):
        token = extract_token(request, authorization, x_api_key)
        if not token or token != expected_key:
            # Raise; exception handler will render plain text to match Go
            raise HTTPException(status_code=401, detail="unauthorized")
        return True

    return _auth
