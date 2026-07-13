from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator
from backend.schemas.task import CoachTaskResult, BetterPhrase, RiskItem
from backend.schemas.retrieval import Citation


class CoachReport(BaseModel):
    """Final rehearsal report.

    This final report intentionally lives in schemas/coach.py, not in
    business_config/coach/coach_schema.yaml. The YAML only describes Coach
    subtask output contracts.
    """

    session_id: str
    status: str = "success"
    overall_score: int | None = None
    summary: str
    top_risks: list[RiskItem] = Field(default_factory=list)
    key_strengths: list[str] = Field(default_factory=list)
    key_improvements: list[str] = Field(default_factory=list)
    better_phrases: list[BetterPhrase] = Field(default_factory=list)
    task_results: list[CoachTaskResult] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    next_step: str | None = None
    disclaimer: str = "Coach 报告仅提供演练复盘、建议和风险提示，最终判断由人工负责。"

    @field_validator("top_risks", "key_strengths", "key_improvements", "better_phrases", "task_results", "citations", mode="before")
    @classmethod
    def normalize_list_fields(cls, value: Any, info: ValidationInfo) -> Any:
        if info.field_name == "top_risks":
            return cls._normalize_risks(value)
        if info.field_name == "better_phrases":
            return cls._normalize_better_phrases(value)
        if info.field_name == "citations":
            return cls._normalize_citations(value)
        return cls._as_list(value)

    @classmethod
    def _as_list(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, dict):
            if not value:
                return []
            if any(key in value for key in {"task_id", "suggestion", "rule_id", "source_id", "title"}):
                return [value]
            return list(value.values())
        return [value]

    @classmethod
    def _normalize_risks(cls, value: Any) -> list[Any]:
        normalized: list[Any] = []
        for item in cls._as_list(value):
            if isinstance(item, dict):
                if "explanation" not in item:
                    item = {**item, "explanation": str(item.get("description") or item.get("risk") or item.get("summary") or item)}
                normalized.append(item)
            else:
                normalized.append({"explanation": str(item)})
        return normalized

    @classmethod
    def _normalize_better_phrases(cls, value: Any) -> list[Any]:
        normalized: list[Any] = []
        for item in cls._as_list(value):
            if isinstance(item, dict):
                suggestion = item.get("suggestion") or item.get("suggested_phrase") or item.get("better_phrase") or item.get("safer_phrase") or item.get("phrase")
                reason = item.get("reason") or item.get("explanation") or "建议替换表达，降低沟通风险。"
                original = item.get("original") or item.get("original_context") or item.get("matched_text")
                normalized.append({"original": original, "suggestion": str(suggestion or item), "reason": str(reason)})
            else:
                normalized.append({"suggestion": str(item), "reason": "建议替换表达，降低沟通风险。"})
        return normalized

    @classmethod
    def _normalize_citations(cls, value: Any) -> list[Any]:
        normalized: list[Any] = []
        for item in cls._as_list(value):
            if isinstance(item, dict):
                source = item.get("source_id") or item.get("source") or item.get("file") or item.get("title") or "unknown"
                title = item.get("title") or source
                normalized.append({**item, "source_id": str(source), "title": str(title)})
            else:
                normalized.append({"source_id": str(item), "title": str(item)})
        return normalized
