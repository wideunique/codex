from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class PromptEnhancerMessage(BaseModel):
    role: str
    text: str


class WorkspaceContext(BaseModel):
    model: str
    recent_messages: Optional[List[PromptEnhancerMessage]] = Field(default=None, alias="recent_messages")


class EnhanceRequest(BaseModel):
    prompt: Optional[str] = None
    draft: Optional[str] = None
    request_id: Optional[str] = None
    format: Optional[str] = None
    locale: Optional[str] = None
    cursor_byte_offset: Optional[int] = Field(default=None, alias="cursor_byte_offset")
    workspace_context: Optional[WorkspaceContext] = Field(default=None, alias="workspace_context")
    mode: Optional[str] = None

    def prompt_text(self) -> str:
        d = (self.draft or "").strip()
        if d:
            return d
        return (self.prompt or "").strip()

    @field_validator("prompt", "draft")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v

    @field_validator("mode")
    @classmethod
    def _normalize_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None

    def validate_non_empty(self) -> None:
        if not self.prompt_text():
            raise ValueError("prompt must not be empty")


class EnhanceResponse(BaseModel):
    enhanced_prompt: str


class ErrorResponse(BaseModel):
    error: str
    message: str
