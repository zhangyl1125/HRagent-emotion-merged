from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AsrFrontendEvent(BaseModel):
    type: Literal["status", "partial", "final", "error"]
    text: str | None = None
    preview: str | None = None
    transcript: str | None = None
    emotion: str | None = None
    message: str | None = None
    code: str | None = None


class AsrControlEvent(BaseModel):
    type: Literal["start", "stop", "ping"]
    language: str | None = None
