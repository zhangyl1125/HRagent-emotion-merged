from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

Speaker = Literal["manager", "employee", "system"]


class ConversationTurn(BaseModel):
    turn_index: int
    speaker: Speaker
    text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = Field(default_factory=dict)
