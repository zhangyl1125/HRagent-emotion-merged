from __future__ import annotations

from pydantic import BaseModel, Field
from backend.schemas.retrieval import Citation


class GuidanceReport(BaseModel):
    session_id: str
    intent_id: str
    persona_id: str | None = None
    difficulty_id: str | None = None
    purpose: str
    opening_suggestion: str
    risk_preview: list[str] = Field(default_factory=list)
    response_strategies: list[str] = Field(default_factory=list)
    safer_phrases: list[str] = Field(default_factory=list)
    evidence_policy: str = "谈前指导不评价用户表现，不引用用户对话原话，不做评分。"
    citations: list[Citation] = Field(default_factory=list)
    disclaimer: str = "本建议用于演练准备，不替代 HR/Legal 或 Manager 的最终判断。"
