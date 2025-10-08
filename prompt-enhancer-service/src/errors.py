from __future__ import annotations

from fastapi import HTTPException


def http_error(status_code: int, error_code: str, message: str) -> HTTPException:
    """Create a structured HTTP error payload."""
    return HTTPException(status_code=status_code, detail={"error": error_code, "message": message})
